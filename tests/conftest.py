import sqlite3

import pytest

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
