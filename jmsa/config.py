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

# The fixed sector list from PRD.md. The library loader rejects anything else,
# so a typo in companies.csv can't quietly create a sixteenth sector.
SECTORS = (
    "Aerospace & Automotive",
    "Banking & Financial Services",
    "Conglomerate",
    "Consulting & Professional Services",
    "E-commerce & Retail",
    "Energy",
    "FMCG",
    "Hardware & Electronics",
    "IT Services",
    "Industrial & Engineering",
    "Payments & Fintech",
    "Pharma & Healthcare",
    "Semiconductors",
    "Software & Internet",
    "Telecom & Networking",
)

load_dotenv(REPO_ROOT / ".env")

# The only API key in the project (GNews, for F6). Read by ingest.load_news
# and never printed or written anywhere.
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY") or None

# Override with JMSA_DB_PATH to point at a frozen database for the demo.
DB_PATH = Path(os.getenv("JMSA_DB_PATH") or DATA_DIR / "jmsa.db")

# The committed copy of the dashboard's data, without the review text
# (scripts/make_demo_db.py). Only the dashboard falls back to it, in
# app/app.py; the loaders and process steps always use DB_PATH, so they
# never write into it.
DEMO_DB_PATH = DATA_DIR / "demo.db"
