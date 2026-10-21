import csv
import sqlite3

import pytest

from ingest.load_glassdoor_reviews import OUT_COLUMNS
from jmsa.db import apply_schema


@pytest.fixture
def db():
    """An empty database with the real schema, in memory.

    Tests never touch data/jmsa.db, so a test run can't disturb the frozen
    demo database.
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    apply_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def library(db):
    """The in-memory database with three companies, enough for review tests."""
    db.executemany(
        "INSERT INTO companies (company_id, name, sector) VALUES (?, ?, 'IT Services')",
        [("acme", "Acme"), ("globex", "Globex"), ("initech", "Initech")],
    )
    db.commit()
    return db


# A review row as glassdoor_reviews_matched.csv writes it, before overrides.
REVIEW_DEFAULTS = {column: "" for column in OUT_COLUMNS} | {
    "review_date": "2022-06-01", "rating": "4.0", "is_pre_merger": "0",
}


@pytest.fixture
def write_reviews(tmp_path):
    """Write a small matched-reviews CSV; each row is a dict of overrides."""
    def write(rows, name="reviews.csv"):
        path = tmp_path / name
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=OUT_COLUMNS, lineterminator="\n")
            writer.writeheader()
            for row in rows:
                writer.writerow({**REVIEW_DEFAULTS, **row})
        return path
    return write
