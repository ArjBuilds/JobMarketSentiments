"""Paths and environment for the Job Market Analyser.

One definition of where the database and inputs live, so the loaders, the
process steps and the dashboard never disagree. API keys are read from .env
here and nowhere else.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
COMPANIES_CSV = DATA_DIR / "companies.csv"
SCHEMA_SQL = Path(__file__).resolve().parent / "schema.sql"

load_dotenv(REPO_ROOT / ".env")

# Override with JMSA_DB_PATH to point at a frozen database for the demo.
DB_PATH = Path(os.getenv("JMSA_DB_PATH") or DATA_DIR / "jmsa.db")
