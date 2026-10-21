"""Fill the glassdoor_* columns of companies from the Glassdoor ratings snapshot.

Source: data/raw/glassdoor_company_ratings.csv, one row per employer with an
overall rating, review count, employer size and industry. It has no review
text; that comes from a different file with different coverage.

Run with:  python -m ingest.load_glassdoor_ratings

Run ingest.load_companies first. Each company is matched once, here:

    1. a company in REJECTED gets no rating, whatever the file says;
    2. a company with glassdoor_ratings aliases matches those names only;
    3. any other company matches its own name, compared through normalise().

When several rows match, the one with the highest review_count wins. Every
company is written on every run, so a company that stops matching goes back
to empty ("not available") instead of keeping a stale rating.
"""

from __future__ import annotations

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from jmsa.aliases import ALIASES_CSV, normalise, read_aliases
from jmsa.config import RAW_DIR
from jmsa.db import apply_schema, get_conn

RATINGS_CSV = RAW_DIR / "glassdoor_company_ratings.csv"

SOURCE_COLUMNS = ("company_name", "overall_rating", "employer_size", "industry", "review_count")

# Exact name matches that point at the wrong page. Each one is left as
# "not available" rather than shown as the company's rating.
REJECTED = {
    "wipro": "only 2,700 reviews and a head office in Dresden, Germany: a regional page, not Wipro Ltd",
    "ey": "only 3,800 reviews and a head office in Riyadh, Saudi Arabia: a regional page, not EY globally",
    "tata-motors": "only 4,100 reviews and a head office in Coventry, England, where ours is India: a UK operation page",
}

# A very large employer with few reviews may have matched a regional page.
# These are flagged in the report for a person to check; nothing is changed.
LARGE_SIZE_BANDS = {"200k+", "50k-200k"}
REGIONAL_CHECK_BELOW = 5_000

UPDATE_SQL = """
    UPDATE companies SET
        glassdoor_rating = ?,
        glassdoor_review_count = ?,
        glassdoor_employer_size = ?,
        glassdoor_industry = ?
    WHERE company_id = ?
"""


class RatingsError(ValueError):
    """The inputs failed a check; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def read_ratings(path: str | Path = RATINGS_CSV) -> dict[str, list[dict]]:
    """normalised company_name -> every row with that name."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in SOURCE_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise RatingsError([f"{path}: missing columns {missing}"])

        by_name: dict[str, list[dict]] = defaultdict(list)
        for raw in reader:
            # Empty cells become None. "Unknown" employer size is the source
            # saying it has no value, so it is treated as empty too.
            size = (raw["employer_size"] or "").strip()
            rating = (raw["overall_rating"] or "").strip()
            by_name[normalise(raw["company_name"])].append({
                "company_name": raw["company_name"].strip(),
                "rating": float(rating) if rating else None,
                "review_count": int(raw["review_count"]),
                "employer_size": None if size in ("", "Unknown") else size,
                "industry": (raw["industry"] or "").strip() or None,
            })
    return by_name


def match_companies(
    companies: list[sqlite3.Row],
    by_name: dict[str, list[dict]],
    aliases: list[tuple[str, str]],
    rejected: dict[str, str],
) -> list[dict]:
    """One result per company: the chosen row (or None) and how it was found."""
    company_ids = {c["company_id"] for c in companies}
    alias_names: dict[str, list[str]] = defaultdict(list)
    problems: list[str] = []

    for company_id, alias in aliases:
        if company_id not in company_ids:
            problems.append(f"alias {alias!r} is for {company_id!r}, which is not in companies")
        elif company_id in rejected:
            problems.append(f"{company_id!r} is in REJECTED but also has the alias {alias!r}")
        elif normalise(alias) not in by_name:
            problems.append(f"alias {alias!r} for {company_id!r} is not a company_name in the ratings file")
        alias_names[company_id].append(alias)
    if problems:
        raise RatingsError(problems)

    results = []
    for company in companies:
        company_id = company["company_id"]
        result = {"company_id": company_id, "size_band": company["size_band"],
                  "row": None, "how": None, "candidates": []}
        if company_id in rejected:
            result["how"] = "rejected"
        else:
            if company_id in alias_names:
                result["how"] = "alias"
                names = alias_names[company_id]
            else:
                result["how"] = "exact"
                names = [company["name"]]
            candidates = [row for name in names for row in by_name.get(normalise(name), [])]
            if candidates:
                result["candidates"] = candidates
                result["row"] = max(candidates, key=lambda row: row["review_count"])
            else:
                result["how"] = None
        results.append(result)
    return results


def load_ratings(
    conn: sqlite3.Connection,
    ratings_path: str | Path = RATINGS_CSV,
    aliases_path: str | Path = ALIASES_CSV,
    rejected: dict[str, str] = REJECTED,
) -> list[dict]:
    """Match every company and write the glassdoor_* columns in one transaction."""
    companies = conn.execute("SELECT company_id, name, size_band FROM companies ORDER BY company_id").fetchall()
    if not companies:
        raise RatingsError(["the companies table is empty; run python -m ingest.load_companies first"])

    results = match_companies(
        companies,
        read_ratings(ratings_path),
        read_aliases("glassdoor_ratings", aliases_path),
        rejected,
    )

    updates = []
    for result in results:
        row = result["row"] or {}
        updates.append([
            row.get("rating"),
            row.get("review_count"),
            row.get("employer_size"),
            row.get("industry"),
            result["company_id"],
        ])
    with conn:
        conn.executemany(UPDATE_SQL, updates)
    return results


def needs_regional_check(result: dict) -> bool:
    row = result["row"]
    return (
        row is not None
        and result["size_band"] in LARGE_SIZE_BANDS
        and row["review_count"] < REGIONAL_CHECK_BELOW
    )


def build_report(results: list[dict], rejected: dict[str, str] = REJECTED) -> str:
    lines: list[str] = []
    add = lines.append

    matched = [r for r in results if r["row"] is not None]
    by_alias = [r for r in matched if r["how"] == "alias"]
    add(f"Matched {len(matched)} of {len(results)} companies "
        f"({len(matched) - len(by_alias)} by exact name, {len(by_alias)} by alias)")
    add("")

    add("Matched by alias")
    for r in by_alias:
        add(f"  {r['company_id']:28} {r['row']['company_name']}")
    add("")

    several = [r for r in matched if len(r["candidates"]) > 1]
    add(f"Several rows matched, highest review_count kept ({len(several)})")
    for r in several:
        others = sorted((c["review_count"] for c in r["candidates"] if c is not r["row"]), reverse=True)
        add(f"  {r['company_id']:28} kept {r['row']['review_count']:,}; "
            f"skipped {', '.join(f'{n:,}' for n in others)}")
    add("")

    add(f"Rejected exact matches ({sum(1 for r in results if r['how'] == 'rejected')})")
    for r in results:
        if r["how"] == "rejected":
            add(f"  {r['company_id']:28} {rejected[r['company_id']]}")
    add("")

    unmatched = [r["company_id"] for r in results if r["row"] is None]
    add(f"Not available ({len(unmatched)})")
    for company_id in unmatched:
        add(f"  {company_id}")
    add("")

    flagged = [r for r in matched if needs_regional_check(r)]
    add(f"check: possibly a regional page ({len(flagged)}) "
        f"-- size band {' or '.join(sorted(LARGE_SIZE_BANDS))} with under {REGIONAL_CHECK_BELOW:,} reviews")
    for r in flagged:
        add(f"  {r['company_id']:28} {r['size_band']:9} {r['row']['review_count']:>7,} reviews"
            f"  ({r['row']['company_name']})")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest.load_glassdoor_ratings")
    parser.add_argument("--csv", type=Path, default=RATINGS_CSV, help="ratings CSV to load")
    args = parser.parse_args(argv)

    conn = get_conn()
    try:
        apply_schema(conn)
        try:
            results = load_ratings(conn, args.csv)
        except RatingsError as error:
            print(f"{args.csv}: not loaded, nothing written", file=sys.stderr)
            for problem in error.problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
    finally:
        conn.close()

    print(build_report(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
