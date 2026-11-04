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
import logging
import random
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

from backend.config import CACHE_DIR, FIXTURE_DIR, GREENHOUSE_URL
from backend.skills import extract_skills

SOURCES = ("live", "cache", "fixture")
TIMEOUT = 20  # seconds, per request

# A failed request is tried up to ATTEMPTS times in all. The wait before
# retry k is a random time in [0, min(CAP, BASE * 2**k)] seconds ("full
# jitter"), so workers that failed together don't all retry at once.
ATTEMPTS = 5
BASE_DELAY = 0.5
CAP_DELAY = 30.0
# Worth retrying: rate limiting and server-side errors. Any other 4xx (a
# board token that doesn't exist) fails the same way every time.
RETRY_STATUS = {429, 500, 502, 503, 504}

log = logging.getLogger("backend.greenhouse")
_rng = random.Random()


class FetchError(RuntimeError):
    """A board could not be read, after retrying where that could help."""


def backoff(attempt: int) -> float:
    return _rng.uniform(0, min(CAP_DELAY, BASE_DELAY * 2 ** attempt))


def fetch_with_retry(board: str, source: str = "live", session=None, sleep=time.sleep) -> dict:
    """fetch_board, retried with exponential backoff on network errors, 429 and 5xx."""
    for attempt in range(ATTEMPTS):
        try:
            return fetch_board(board, source, session)
        except (requests.ConnectionError, requests.Timeout) as exc:
            reason, delay = type(exc).__name__, backoff(attempt)
        except requests.HTTPError as exc:
            status = exc.response.status_code
            if status not in RETRY_STATUS:
                raise FetchError(f"{board}: HTTP {status}, not retried") from exc
            reason, delay = f"HTTP {status}", backoff(attempt)
            # When the server says how long to wait, never wait less than that.
            retry_after = exc.response.headers.get("Retry-After", "")
            if retry_after.isdigit():
                delay = max(delay, min(float(retry_after), CAP_DELAY))
        if attempt + 1 < ATTEMPTS:
            log.warning("%s: %s, retry %d/%d in %.1fs", board, reason, attempt + 1, ATTEMPTS - 1, delay)
            sleep(delay)
    raise FetchError(f"{board}: gave up after {ATTEMPTS} attempts ({reason})")


def fetch_board(board: str, source: str = "live", session: requests.Session | None = None) -> dict:
    """The board's JSON ({"jobs": [...], "meta": {...}}) from the chosen source."""
    if source == "live":
        response = (session or requests).get(GREENHOUSE_URL.format(board=board), timeout=TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        # Written aside and renamed, so a kill mid-write never leaves half a file.
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        part = CACHE_DIR / f"{board}.json.part"
        part.write_bytes(response.content)
        part.replace(CACHE_DIR / f"{board}.json")
        return payload
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
