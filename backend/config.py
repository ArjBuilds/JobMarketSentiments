"""Paths and settings for the backend, read from .env like jmsa.config.

Every setting has a default that works on a laptop with no Docker: the
SQLite store, the live Greenhouse API and data/backend.db.
"""

from __future__ import annotations

import csv
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

BOARDS_CSV = Path(__file__).resolve().parent / "boards.csv"
# Raw API responses, one file per board, so a run can be replayed offline
# (--source cache). Under data/raw/, so gitignored.
CACHE_DIR = REPO_ROOT / "data" / "raw" / "greenhouse"
# Hand-written, labelled fake boards for tests and for when the API is down.
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "greenhouse"

GREENHOUSE_URL = "https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"

# sqlite (default, no Docker) or clickhouse (docker compose up -d).
STORE = os.getenv("BACKEND_STORE", "sqlite")
SQLITE_PATH = Path(os.getenv("BACKEND_SQLITE_PATH") or REPO_ROOT / "data" / "backend.db")

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST", "localhost")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8123"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD", "")
CLICKHOUSE_DB = os.getenv("CLICKHOUSE_DB", "jmsa")


def read_boards(path: str | Path = BOARDS_CSV) -> list[tuple[str, str]]:
    """(board_token, name) pairs from the config file, in file order."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [(row["board_token"].strip(), row["name"].strip()) for row in csv.DictReader(handle)]
