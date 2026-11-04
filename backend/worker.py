"""Poll the Greenhouse job boards in backend/boards.csv and store their postings.

Run with:  python -m backend.worker [--source live|cache|fixture] [--loop SECONDS]
                                    [--batch-size N] [--throttle SECONDS]

One pass (a run) reads every board once; --loop repeats it every SECONDS.
--throttle sleeps after each write batch. It exists so
scripts/kill_restart_check.py can kill the worker part-way through a board.

Self-healing, in three parts:
  retries      a failed request is retried with exponential backoff
               (backend.greenhouse.fetch_with_retry); a board that still
               fails is checkpointed as failed and the pass moves on.
  checkpoints  a board is checkpointed only after all its rows are stored.
               A killed run is resumed on the next start, skipping its done boards.
  idempotency  every row has a stable dedupe_key (greenhouse:<board>:<id>)
               and the store skips a key it already has, so re-reading a
               half-written board adds no duplicates.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

from backend import config
from backend.greenhouse import SOURCES, FetchError, fetch_with_retry, parse_board
from backend.store import open_store

log = logging.getLogger("backend.worker")

BATCH_SIZE = 500


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_pass(store, boards: list[tuple[str, str]], source: str, fetch=fetch_with_retry,
             batch_size: int = BATCH_SIZE, throttle: float = 0) -> int:
    """One run over the boards, resuming a killed one. Returns rows added."""
    run_id, done = store.start_or_resume_run(now_iso())
    if done is not None:
        log.info("resuming run %d: %d of %d boards already done", run_id, len(done), len(boards))
    added = 0
    for board, _name in boards:
        if done and board in done:
            continue
        try:
            payload = fetch(board, source)
        except FetchError as exc:
            log.error("%s", exc)
            store.checkpoint(run_id, board, "failed", 0, now_iso())
            continue
        rows = parse_board(board, payload, now_iso(), synthetic=source == "fixture")
        new = 0
        for start in range(0, len(rows), batch_size):
            new += store.write_rows(rows[start:start + batch_size])
            if throttle:
                time.sleep(throttle)
        store.checkpoint(run_id, board, "done", len(rows), now_iso())
        added += new
        log.info("%s: %d postings, %d new", board, len(rows), new)
    store.finish_run(run_id, now_iso())
    return added


def boards_for(source: str) -> list[tuple[str, str]]:
    # The fixture has its own two fake boards, so it never pretends to be a real one.
    return config.read_boards(config.FIXTURE_DIR / "boards.csv" if source == "fixture" else config.BOARDS_CSV)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=SOURCES, default="live")
    parser.add_argument("--loop", type=float, default=0, help="seconds between passes; 0 runs once")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    parser.add_argument("--throttle", type=float, default=0, help="seconds to sleep after each batch")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    store = open_store(config.STORE, config.SQLITE_PATH)
    boards = boards_for(args.source)
    try:
        while True:
            added = run_pass(store, boards, args.source, batch_size=args.batch_size, throttle=args.throttle)
            log.info("pass done: %d new rows, %d stored", added, store.count())
            if not args.loop:
                return 0
            time.sleep(args.loop)
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
