"""Where the worker's rows go.

SQLiteStore needs nothing installed and backs the tests; ClickHouseStore is
the production store (docker-compose.yml). Both expose the same methods.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SQLITE_SCHEMA = Path(__file__).resolve().parent / "schema_sqlite.sql"

COLUMNS = ("dedupe_key", "board", "job_id", "company", "title", "location", "department",
           "first_published", "posted_day", "updated_at", "url", "skills", "is_synthetic", "fetched_at")


class SQLiteStore:
    def __init__(self, path: str | Path = ":memory:"):
        self.conn = sqlite3.connect(str(path))
        self.conn.executescript(SQLITE_SCHEMA.read_text(encoding="utf-8"))

    def write_rows(self, rows: list[dict]) -> int:
        """Insert rows; a dedupe_key already stored is skipped. Returns rows added."""
        before = self.conn.total_changes
        with self.conn:
            self.conn.executemany(
                f"INSERT OR IGNORE INTO postings ({', '.join(COLUMNS)}) VALUES ({', '.join('?' * len(COLUMNS))})",
                [tuple(";".join(r[c]) if c == "skills" else r[c] for c in COLUMNS) for r in rows],
            )
        return self.conn.total_changes - before

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


def open_store(kind: str, sqlite_path: str | Path):
    if kind == "sqlite":
        return SQLiteStore(sqlite_path)
    raise ValueError(f"BACKEND_STORE must be sqlite or clickhouse, not {kind!r}")
