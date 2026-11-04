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

    def close(self) -> None:
        self.conn.close()


def open_store(kind: str, sqlite_path: str | Path):
    if kind == "sqlite":
        return SQLiteStore(sqlite_path)
    raise ValueError(f"BACKEND_STORE must be sqlite or clickhouse, not {kind!r}")
