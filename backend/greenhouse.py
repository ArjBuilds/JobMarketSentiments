"""Read one Greenhouse job board and turn its postings into rows.

Uses only the public Job Board API (boards-api.greenhouse.io), which needs
no key and returns a board's open postings as JSON. No website is scraped.
Three sources give the same JSON, so the worker can run with no network:
live (the API, saving each response to data/raw/greenhouse/), cache (those
saved responses) and fixture (tests/fixtures/greenhouse/, hand-written and
labelled synthetic).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

from backend.config import CACHE_DIR, FIXTURE_DIR, GREENHOUSE_URL
from backend.skills import extract_skills

SOURCES = ("live", "cache", "fixture")
TIMEOUT = 20  # seconds, per request


def fetch_board(board: str, source: str = "live", session: requests.Session | None = None) -> dict:
    """The board's JSON ({"jobs": [...], "meta": {...}}) from the chosen source."""
    if source == "live":
        response = (session or requests).get(GREENHOUSE_URL.format(board=board), timeout=TIMEOUT)
        response.raise_for_status()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{board}.json").write_bytes(response.content)
        return response.json()
    folder = CACHE_DIR if source == "cache" else FIXTURE_DIR
    return json.loads((folder / f"{board}.json").read_text(encoding="utf-8"))


def utc_iso(stamp: str | None) -> str | None:
    """'2025-01-28T18:57:29-05:00' -> '2025-01-28T23:57:29Z'."""
    if not stamp:
        return None
    return datetime.fromisoformat(stamp).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def dedupe_key(board: str, job_id) -> str:
    """Stable across runs: a posting keeps its Greenhouse id for life."""
    return f"greenhouse:{board}:{job_id}"


def parse_board(board: str, payload: dict, fetched_at: str, synthetic: bool = False) -> list[dict]:
    """One row per posting. The content HTML is read for skills, never stored."""
    rows = []
    for job in payload.get("jobs", []):
        published = utc_iso(job.get("first_published") or job.get("updated_at"))
        rows.append({
            "dedupe_key": dedupe_key(board, job["id"]),
            "board": board,
            "job_id": str(job["id"]),
            "company": job.get("company_name") or board,
            "title": job.get("title") or "",
            "location": (job.get("location") or {}).get("name") or "",
            "department": ((job.get("departments") or [{}])[0] or {}).get("name") or "",
            "first_published": published,
            "posted_day": published[:10] if published else None,
            "updated_at": utc_iso(job.get("updated_at")),
            "url": job.get("absolute_url") or "",
            "skills": extract_skills(job.get("content")),
            "is_synthetic": int(synthetic),
            "fetched_at": fetched_at,
        })
    return rows
