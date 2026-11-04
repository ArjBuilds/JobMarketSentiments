"""Where the worker's rows go.

SQLiteStore needs nothing installed and backs the tests; ClickHouseStore is
the production store (docker-compose.yml). Both expose the same methods.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

SQLITE_SCHEMA = Path(__file__).resolve().parent / "schema_sqlite.sql"

COLUMNS = ("dedupe_key", "board", "job_id", "company", "title", "location", "department",
           "first_published", "posted_day", "updated_at", "url", "skills", "is_synthetic", "fetched_at")

# What the live stream sends: the last WINDOW_DAYS days of volume, up to the
# newest posted_day stored, and the TOP_SKILLS skills over the same days.
WINDOW_DAYS = 30
TOP_SKILLS = 10


def aggregate_delta(rows: list[dict]) -> tuple[Counter, Counter]:
    """What new postings add to volume_daily ({day: n}) and skill_daily ({(day, skill): n})."""
    volume = Counter(r["posted_day"] for r in rows)
    skills = Counter((r["posted_day"], s) for r in rows for s in r["skills"])
    return volume, skills


def snapshot_dict(volume: list[tuple], skills: list[tuple], total: int, synthetic: bool) -> dict:
    """The live stream's message body, the same for both stores."""
    return {
        "dataset": "synthetic" if synthetic else "live",
        "synthetic": synthetic,
        "total_postings": total,
        "window_days": WINDOW_DAYS,
        "volume": [{"day": str(d), "postings": n} for d, n in volume],
        "top_skills": [{"skill": s, "postings": n} for s, n in skills],
    }


class SQLiteStore:
    def __init__(self, path: str | Path = ":memory:"):
        # The API reads from a worker thread that changes between polls.
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.executescript(SQLITE_SCHEMA.read_text(encoding="utf-8"))

    def write_rows(self, rows: list[dict]) -> int:
        """Insert rows; a dedupe_key already stored is skipped. Returns rows added.

        The new rows' counts are added to the aggregates in the same
        transaction, so the aggregates can never disagree with postings.
        """
        insert = f"INSERT OR IGNORE INTO postings ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})"
        new = []
        with self.conn:
            for r in rows:
                values = tuple(";".join(r[c]) if c == "skills" else r[c] for c in COLUMNS)
                if self.conn.execute(insert, values).rowcount:
                    new.append(r)
            volume, skills = aggregate_delta(new)
            self.conn.executemany("INSERT INTO volume_daily VALUES (?, ?) ON CONFLICT (day)"
                                  " DO UPDATE SET postings = postings + excluded.postings", volume.items())
            self.conn.executemany("INSERT INTO skill_daily VALUES (?, ?, ?) ON CONFLICT (day, skill)"
                                  " DO UPDATE SET postings = postings + excluded.postings",
                                  [(d, s, n) for (d, s), n in skills.items()])
        return len(new)

    def aggregates(self, synthetic: bool = False) -> dict:
        """The live stream's snapshot. Synthetic rows live only in ClickHouse."""
        if synthetic:
            raise ValueError("synthetic data is only in the ClickHouse store")
        last = self.conn.execute("SELECT MAX(day) FROM volume_daily").fetchone()[0]
        if last is None:
            return snapshot_dict([], [], 0, False)
        first = (date.fromisoformat(last) - timedelta(days=WINDOW_DAYS - 1)).isoformat()
        volume = self.conn.execute("SELECT day, postings FROM volume_daily WHERE day >= ? ORDER BY day",
                                   (first,)).fetchall()
        skills = self.conn.execute("SELECT skill, SUM(postings) AS n FROM skill_daily WHERE day >= ?"
                                   " GROUP BY skill ORDER BY n DESC, skill LIMIT ?", (first, TOP_SKILLS)).fetchall()
        total = self.conn.execute("SELECT COALESCE(SUM(postings), 0) FROM volume_daily").fetchone()[0]
        return snapshot_dict(volume, skills, total, False)

    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM postings").fetchone()[0]

    def keys(self) -> list[str]:
        """Every stored dedupe_key, duplicates included (the kill check counts them)."""
        return [k for (k,) in self.conn.execute("SELECT dedupe_key FROM postings")]

    def start_or_resume_run(self, started_at: str) -> tuple[int, set[str] | None]:
        """The unfinished run and its done boards, or a new run and None."""
        row = self.conn.execute("SELECT run_id FROM runs WHERE finished_at IS NULL ORDER BY run_id DESC").fetchone()
        if row:
            done = {b for (b,) in self.conn.execute(
                "SELECT board FROM checkpoints WHERE run_id = ? AND status = 'done'", row)}
            return row[0], done
        with self.conn:
            run_id = self.conn.execute("INSERT INTO runs (started_at) VALUES (?)", (started_at,)).lastrowid
        return run_id, None

    def checkpoint(self, run_id: int, board: str, status: str, postings: int, at: str) -> None:
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?, ?, ?)",
                              (run_id, board, status, postings, at))

    def finish_run(self, run_id: int, at: str) -> None:
        with self.conn:
            self.conn.execute("UPDATE runs SET finished_at = ? WHERE run_id = ?", (at, run_id))

    def close(self) -> None:
        self.conn.close()


CLICKHOUSE_SCHEMA = Path(__file__).resolve().parent / "schema_clickhouse.sql"


def _utc(stamp: str | None) -> datetime:
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class ClickHouseStore:
    """The same methods as SQLiteStore, on ClickHouse, which has no transactions.

    Idempotency comes from the order of writes instead: a batch inserts only
    the keys the table doesn't have (one insert is atomic), and the board's
    checkpoint is appended after its last batch. A kill between the two
    re-reads the board, finds every key present and inserts nothing.
    Assumes one worker per database.
    """

    @staticmethod
    def connect(database: str):
        """A clickhouse-connect client on the configured server."""
        import clickhouse_connect

        from backend import config

        return clickhouse_connect.get_client(host=config.CLICKHOUSE_HOST, port=config.CLICKHOUSE_PORT,
                                             username=config.CLICKHOUSE_USER, password=config.CLICKHOUSE_PASSWORD,
                                             database=database)

    def __init__(self, database: str):
        admin = self.connect("default")
        admin.command(f"CREATE DATABASE IF NOT EXISTS {database}")
        admin.close()
        self.client = self.connect(database)
        for statement in schema_statements(CLICKHOUSE_SCHEMA):
            self.client.command(statement)

    def write_rows(self, rows: list[dict]) -> int:
        """Insert the rows whose dedupe_key isn't stored yet. Returns rows added."""
        batch = {r["dedupe_key"]: r for r in rows}  # also drops repeats within the batch
        if not batch:
            return 0
        stored = self.client.query("SELECT dedupe_key FROM postings WHERE dedupe_key IN %(keys)s",
                                   parameters={"keys": list(batch)}).result_rows
        new = [r for k, r in batch.items() if k not in {s for (s,) in stored}]
        if new:
            self.client.insert("postings", [[
                r["dedupe_key"], r["board"], r["job_id"], r["company"], r["title"], r["location"],
                r["department"], _utc(r["first_published"] or r["fetched_at"]),
                _utc(r["first_published"] or r["fetched_at"]).date(), _utc(r["updated_at"] or r["fetched_at"]),
                r["url"], r["skills"], r["is_synthetic"], _utc(r["fetched_at"]),
            ] for r in new], column_names=list(COLUMNS))
        return len(new)

    def aggregates(self, synthetic: bool = False) -> dict:
        """The live stream's snapshot, from the materialized views' tables.

        sum() ... GROUP BY because SummingMergeTree adds rows up only when
        parts merge, which happens in the background at no fixed time.
        """
        prefix = "synthetic_" if synthetic else ""
        last = self.client.command(f"SELECT max(day) FROM {prefix}volume_daily")
        if not self.client.command(f"SELECT count() FROM {prefix}volume_daily"):
            return snapshot_dict([], [], 0, synthetic)
        params = {"last": last, "days": WINDOW_DAYS - 1, "top": TOP_SKILLS}
        volume = self.client.query(
            f"SELECT day, sum(postings) FROM {prefix}volume_daily"
            " WHERE day >= toDate(%(last)s) - %(days)s GROUP BY day ORDER BY day", parameters=params).result_rows
        skills = self.client.query(
            f"SELECT skill, sum(postings) AS n FROM {prefix}skill_daily WHERE day >= toDate(%(last)s) - %(days)s"
            " GROUP BY skill ORDER BY n DESC, skill LIMIT %(top)s", parameters=params).result_rows
        total = self.client.command(f"SELECT sum(postings) FROM {prefix}volume_daily")
        return snapshot_dict(volume, skills, int(total), synthetic)

    def count(self) -> int:
        return self.client.command("SELECT count() FROM postings")

    def keys(self) -> list[str]:
        """Every stored dedupe_key, duplicates included: no FINAL, so a duplicate shows."""
        return [k for (k,) in self.client.query("SELECT dedupe_key FROM postings").result_rows]

    def start_or_resume_run(self, started_at: str) -> tuple[int, set[str] | None]:
        rows = self.client.query(
            "SELECT run_id FROM run_events GROUP BY run_id HAVING countIf(event = 'finish') = 0"
            " ORDER BY run_id DESC LIMIT 1").result_rows
        if rows:
            run_id = rows[0][0]
            done = self.client.query("SELECT board FROM checkpoints FINAL WHERE run_id = %(r)s AND status = 'done'",
                                     parameters={"r": run_id}).result_rows
            return run_id, {b for (b,) in done}
        run_id = self.client.command("SELECT max(run_id) + 1 FROM run_events")
        self.client.insert("run_events", [[run_id, "start", _utc(started_at)]],
                           column_names=["run_id", "event", "at"])
        return run_id, None

    def checkpoint(self, run_id: int, board: str, status: str, postings: int, at: str) -> None:
        self.client.insert("checkpoints", [[run_id, board, status, postings, _utc(at)]],
                           column_names=["run_id", "board", "status", "postings", "finished_at"])

    def finish_run(self, run_id: int, at: str) -> None:
        self.client.insert("run_events", [[run_id, "finish", _utc(at)]], column_names=["run_id", "event", "at"])

    def close(self) -> None:
        self.client.close()


def schema_statements(path: Path) -> list[str]:
    """The ;-separated statements of a .sql file, comment lines removed."""
    text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines()
                     if not line.lstrip().startswith("--"))
    return [s.strip() for s in text.split(";") if s.strip()]


def open_store(kind: str, sqlite_path: str | Path, clickhouse_db: str | None = None):
    if kind == "sqlite":
        return SQLiteStore(sqlite_path)
    if kind == "clickhouse":
        from backend import config
        return ClickHouseStore(clickhouse_db or config.CLICKHOUSE_DB)
    raise ValueError(f"BACKEND_STORE must be sqlite or clickhouse, not {kind!r}")
