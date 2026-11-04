"""Kill the worker mid-run, restart it, and check no row was lost or duplicated.

Run with:  python scripts/kill_restart_check.py [--store sqlite|clickhouse]
                                                [--source cache|fixture|live] [--kills N]

1. A reference run, never interrupted, into its own store.
2. A test run into a fresh store, written in small throttled batches and
   hard-killed (TerminateProcess on Windows, SIGKILL elsewhere: no cleanup
   code runs) each time its row count passes another fraction of the
   reference. Then it is restarted once and left to finish.
3. The test store must hold exactly the reference's dedupe keys, each once,
   and at least one kill must have landed part-way through a board (rows
   stored, no checkpoint), or the check proves nothing and fails.

--source cache (the default) replays the responses saved by the last live
run, so both runs see the same postings. --store clickhouse uses two
throwaway databases (kill_check_reference, kill_check_test), dropped first.
On ClickHouse a duplicate can really be stored (there is no primary key
constraint), so "no duplicates" tests the worker, not the database.
Exit code 0 means every check passed.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.store import ClickHouseStore, SQLiteStore  # noqa: E402


def worker(db: Path | str, source: str, *extra: str) -> subprocess.Popen:
    if isinstance(db, Path):
        env = dict(os.environ, BACKEND_STORE="sqlite", BACKEND_SQLITE_PATH=str(db))
    else:
        env = dict(os.environ, BACKEND_STORE="clickhouse", CLICKHOUSE_DB=db)
    return subprocess.Popen([sys.executable, "-m", "backend.worker", "--source", source, *extra],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)


def snapshot(db: Path | str) -> tuple[int, int, int]:
    """(rows stored, boards checkpointed, rows of boards with no checkpoint yet).

    Read-only, so polling never takes a write lock from the worker; all
    zeros until the worker has created its tables.
    """
    if isinstance(db, str):
        return clickhouse_snapshot(db)
    if not db.exists():
        return 0, 0, 0
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=5)
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'checkpoints'").fetchone():
            return 0, 0, 0
        rows = conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]
        boards = conn.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
        partial = conn.execute(
            "SELECT COUNT(*) FROM postings WHERE board NOT IN (SELECT board FROM checkpoints)").fetchone()[0]
        return rows, boards, partial
    finally:
        conn.close()


def clickhouse_snapshot(db: str) -> tuple[int, int, int]:
    client = ClickHouseStore.connect("default")
    try:
        if not client.command(f"EXISTS TABLE {db}.checkpoints"):
            return 0, 0, 0
        return tuple(client.query(
            f"SELECT (SELECT count() FROM {db}.postings), (SELECT count() FROM {db}.checkpoints FINAL),"
            f" (SELECT count() FROM {db}.postings WHERE board NOT IN (SELECT board FROM {db}.checkpoints))"
        ).result_rows[0])
    finally:
        client.close()


def open_target(db: Path | str):
    return SQLiteStore(db) if isinstance(db, Path) else ClickHouseStore(db)


def unfinished_runs(store) -> int:
    if isinstance(store, SQLiteStore):
        return store.conn.execute("SELECT COUNT(*) FROM runs WHERE finished_at IS NULL").fetchone()[0]
    return len(store.client.query("SELECT run_id FROM run_events GROUP BY run_id"
                                  " HAVING countIf(event = 'finish') = 0").result_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--store", default="sqlite", choices=("sqlite", "clickhouse"))
    parser.add_argument("--source", default="cache", choices=("cache", "fixture", "live"))
    parser.add_argument("--kills", type=int, default=2)
    parser.add_argument("--batch-size", default="25")
    parser.add_argument("--throttle", default="0.02")
    args = parser.parse_args()
    if args.source == "fixture":  # 7 rows: one row per batch, or the kill misses
        args.batch_size, args.throttle = "1", "0.3"

    if args.store == "sqlite":
        tmp = Path(tempfile.mkdtemp(prefix="kill_check_"))
        ref_db, test_db = tmp / "reference.db", tmp / "test.db"
    else:
        ref_db, test_db = "kill_check_reference", "kill_check_test"
        client = ClickHouseStore.connect("default")
        for db in (ref_db, test_db):
            client.command(f"DROP DATABASE IF EXISTS {db}")
        client.close()

    started = time.perf_counter()
    ref = worker(ref_db, args.source)
    if ref.wait() != 0:
        print(ref.stderr.read())
        return 1
    reference = open_target(ref_db)
    expected = Counter(reference.keys())
    reference.close()
    print(f"reference run: {sum(expected.values())} rows in {time.perf_counter() - started:.1f}s")

    mid_board = False
    for k in range(1, args.kills + 1):
        target = sum(expected.values()) * k // (args.kills + 1)
        proc = worker(test_db, args.source, "--batch-size", args.batch_size, "--throttle", args.throttle)
        while proc.poll() is None and snapshot(test_db)[0] < target:
            time.sleep(0.01)
        if proc.poll() is not None:
            print(f"kill {k}: the worker finished before row {target}; raise --throttle")
            return 1
        proc.kill()
        proc.wait()
        rows, boards, partial = snapshot(test_db)
        mid_board |= partial > 0
        print(f"kill {k}: killed at {rows} rows, {boards} boards checkpointed, "
              f"{partial} rows of an unfinished board")

    restart = worker(test_db, args.source)
    if restart.wait() != 0:
        print(restart.stderr.read())
        return 1
    resumed = [line for line in restart.stderr.read().splitlines() if "resuming run" in line]
    print("restart:", resumed[0].split("INFO ")[-1] if resumed else "did NOT resume a run")

    test = open_target(test_db)
    got = Counter(test.keys())
    unfinished = unfinished_runs(test)
    test.close()

    checks = {
        "no rows lost": not (expected.keys() - got.keys()),
        "no unexpected rows": not (got.keys() - expected.keys()),
        "no duplicates": all(n == 1 for n in got.values()),
        "a kill landed mid-board": mid_board,
        "restart resumed the killed run": bool(resumed),
        "run finished": unfinished == 0,
    }
    print(f"test store: {sum(got.values())} rows, {len(got)} distinct keys; reference {len(expected)}")
    for name, ok in checks.items():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
