"""SQLite access for the Job Market Analyser.

The dashboard never calls a live source; it reads this database, which the
ingest and process steps fill in. Create an empty one with:

    python -m jmsa.db init
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from jmsa.config import DB_PATH, SCHEMA_SQL

# Declaration order matters: a table is listed after the one it references.
# review_summary is derived from reviews by process.review_sentiment, and
# skill_counts from the postings CSV by process.skill_counts. news_fetches
# records each company's last GNews fetch, alongside articles.
TABLES = ("companies", "reviews", "turnover", "articles", "jobs", "job_skills", "review_summary",
          "skill_counts", "news_fetches")


def get_conn(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Open the database, creating its parent directory if needed."""
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # sqlite3 leaves foreign keys off per connection, which would make every
    # REFERENCES in schema.sql decorative.
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create any missing tables and indexes. Safe to run repeatedly."""
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.commit()


def init_db(db_path: str | Path | None = None) -> Path:
    """Create an empty database and return its path."""
    conn = get_conn(db_path)
    try:
        apply_schema(conn)
        return Path(conn.execute("PRAGMA database_list").fetchone()["file"])
    finally:
        conn.close()


def table_counts(conn: sqlite3.Connection | None = None) -> dict[str, int]:
    """Row count per table, for the smoke check and last-refresh surfaces."""
    own_conn = conn is None
    conn = conn or get_conn()
    try:
        return {
            table: conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }
    finally:
        if own_conn:
            conn.close()


def main(argv: list[str]) -> int:
    if argv != ["init"]:
        print("usage: python -m jmsa.db init", file=sys.stderr)
        return 2
    path = init_db()
    print(f"schema applied to {path}")
    for table, count in table_counts().items():
        print(f"  {table:<12} {count:>8} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
