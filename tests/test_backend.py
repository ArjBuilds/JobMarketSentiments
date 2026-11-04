"""The backend's three focused tests: dedupe, checkpoint recovery, aggregates.

All three use the labelled synthetic fixture boards and an in-memory
SQLite store, so they need no network and no Docker.
"""

import pytest

from backend.greenhouse import fetch_board, parse_board
from backend.store import SQLiteStore
from backend.worker import boards_for, run_pass

BOARDS = boards_for("fixture")


@pytest.fixture
def store():
    s = SQLiteStore(":memory:")
    yield s
    s.close()


def fixture_rows(board, fetched_at="2026-11-01T00:00:00Z"):
    return parse_board(board, fetch_board(board, "fixture"), fetched_at, synthetic=True)


def test_dedupe_same_posting_stored_once(store):
    rows = fixture_rows("fixture-alpha")
    assert store.write_rows(rows) == len(rows)
    # A later fetch of the same postings has a new fetched_at but the same keys,
    # and an overlapping batch mixes old and new: only the new rows are added.
    again = fixture_rows("fixture-alpha", fetched_at="2026-11-02T00:00:00Z")
    assert store.write_rows(again) == 0
    beta = fixture_rows("fixture-beta")
    assert store.write_rows(again[:2] + beta) == len(beta)
    keys = store.keys()
    assert len(keys) == len(set(keys)) == len(rows) + len(beta)


def test_checkpoint_recovery_resumes_without_loss_or_duplicates(store):
    fetched = []

    def crash_on_second_board(board, source):
        fetched.append(board)
        if board == BOARDS[1][0]:
            # Stored part of the board, then died before its checkpoint.
            store.write_rows(fixture_rows(board)[:1])
            raise KeyboardInterrupt("killed")
        return fetch_board(board, source)

    with pytest.raises(KeyboardInterrupt):
        run_pass(store, BOARDS, "fixture", fetch=crash_on_second_board)
    assert store.conn.execute("SELECT COUNT(*) FROM runs WHERE finished_at IS NULL").fetchone()[0] == 1

    fetched.clear()
    run_pass(store, BOARDS, "fixture", fetch=lambda b, s: (fetched.append(b), fetch_board(b, s))[1])
    # The done board is skipped, the half-written one re-read.
    assert fetched == [BOARDS[1][0]]

    clean = SQLiteStore(":memory:")
    run_pass(clean, BOARDS, "fixture")
    assert sorted(store.keys()) == sorted(clean.keys())
    assert store.conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 1
    clean.close()
