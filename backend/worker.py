"""Poll the Greenhouse job boards in backend/boards.csv and store their postings.

Run with:  python -m backend.worker [--source live|cache|fixture] [--loop SECONDS]

One pass reads every board once. --loop repeats the pass every SECONDS.
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timezone

from backend import config
from backend.greenhouse import SOURCES, fetch_board, parse_board
from backend.store import open_store

log = logging.getLogger("backend.worker")


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_pass(store, boards: list[tuple[str, str]], source: str) -> int:
    added = 0
    for board, _name in boards:
        rows = parse_board(board, fetch_board(board, source), now_iso(), synthetic=source == "fixture")
        new = store.write_rows(rows)
        added += new
        log.info("%s: %d postings, %d new", board, len(rows), new)
    return added


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", choices=SOURCES, default="live")
    parser.add_argument("--loop", type=float, default=0, help="seconds between passes; 0 runs once")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    store = open_store(config.STORE, config.SQLITE_PATH)
    # The fixture has its own two fake boards, so it never pretends to be a real one.
    boards = config.read_boards(config.FIXTURE_DIR / "boards.csv" if args.source == "fixture" else config.BOARDS_CSV)
    try:
        while True:
            added = run_pass(store, boards, args.source)
            log.info("pass done: %d new rows, %d stored", added, store.count())
            if not args.loop:
                return 0
            time.sleep(args.loop)
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
