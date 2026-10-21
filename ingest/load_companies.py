"""Load the curated company library into the companies table.

Source: data/companies.csv, hand-curated. It is the spine every other source
joins to, so it is checked strictly before anything is written.

Run with:  python -m ingest.load_companies [--csv PATH]

Re-runnable: each run inserts new companies and overwrites the CSV columns of
existing ones, so running it twice leaves the same table. The glassdoor_*
columns belong to the ratings loader and are never touched here.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from pathlib import Path

from jmsa.config import COMPANIES_CSV, SECTORS
from jmsa.db import apply_schema, get_conn

# Must equal the CSV header exactly, in order, and the first block of the
# companies table in schema.sql (tests/test_load_companies.py checks both).
EXPECTED_HEADER = [
    "company_id",
    "name",
    "sector",
    "hq_country",
    "india_cities",
    "size_band",
    "careers_url",
    "publishes_attrition",
]

# The F1 fields: a company missing any of these can't appear in the library.
REQUIRED = ("company_id", "name", "sector", "hq_country", "india_cities", "size_band")

# Lowercase letters and digits in hyphen-joined words: tata-consultancy-services.
SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

ATTRITION_VALUES = {"yes", "no"}


class LibraryError(ValueError):
    """companies.csv (or the database) failed a check; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def read_library(path: str | Path = COMPANIES_CSV) -> list[dict]:
    """Read and validate the library CSV, returning one dict per company.

    Every problem in the file is collected before raising, so one run lists
    them all. Empty cells come back as None, which sqlite3 stores as NULL.
    """
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != EXPECTED_HEADER:
            raise LibraryError([
                f"header is {reader.fieldnames}",
                f"expected  {EXPECTED_HEADER}",
            ])

        rows: list[dict] = []
        problems: list[str] = []
        first_seen: dict[str, int] = {}
        for raw in reader:
            line = reader.line_num
            row = {column: (raw[column] or "").strip() or None for column in EXPECTED_HEADER}

            for column in REQUIRED:
                if row[column] is None:
                    problems.append(f"line {line}: {column} is empty")

            company_id = row["company_id"]
            if company_id is not None:
                if not SLUG_RE.match(company_id):
                    problems.append(f"line {line}: company_id {company_id!r} is not a lowercase slug")
                if company_id in first_seen:
                    problems.append(
                        f"line {line}: duplicate company_id {company_id!r}"
                        f" (first on line {first_seen[company_id]})"
                    )
                else:
                    first_seen[company_id] = line

            if row["sector"] is not None and row["sector"] not in SECTORS:
                problems.append(f"line {line}: sector {row['sector']!r} is not in the PRD's fixed list")

            attrition = row["publishes_attrition"]
            if attrition is not None and attrition not in ATTRITION_VALUES:
                problems.append(f"line {line}: publishes_attrition {attrition!r} must be yes, no or empty")

            # The company-run careers site, linked from the Company page.
            careers_url = row["careers_url"]
            if careers_url is not None and not careers_url.startswith("https://"):
                problems.append(f"line {line}: careers_url {careers_url!r} must start with https://")

            rows.append(row)

    if problems:
        raise LibraryError(problems)
    return rows


# "Upsert": insert the row, or if the company_id is already there, overwrite
# its CSV columns. That is what makes a second run a no-op instead of a
# duplicate-key error, and it leaves the glassdoor_* columns alone.
UPSERT_SQL = f"""
    INSERT INTO companies ({", ".join(EXPECTED_HEADER)})
    VALUES ({", ".join("?" for _ in EXPECTED_HEADER)})
    ON CONFLICT(company_id) DO UPDATE SET
        {", ".join(f"{c} = excluded.{c}" for c in EXPECTED_HEADER[1:])}
"""


def load_companies(conn: sqlite3.Connection, path: str | Path = COMPANIES_CSV) -> int:
    """Validate the CSV, then write it in one transaction. Returns the row count."""
    rows = read_library(path)

    # A company dropped from the CSV may already have reviews or jobs pointing
    # at it, so deleting it is a decision for a person, not this loader.
    csv_ids = {row["company_id"] for row in rows}
    db_ids = {r[0] for r in conn.execute("SELECT company_id FROM companies")}
    orphans = sorted(db_ids - csv_ids)
    if orphans:
        raise LibraryError([f"in the database but not in the CSV: {company_id}" for company_id in orphans])

    # `with conn` commits if the block finishes and rolls back if it raises,
    # so a failure halfway leaves the table exactly as it was.
    with conn:
        conn.executemany(UPSERT_SQL, [[row[c] for c in EXPECTED_HEADER] for row in rows])
    return len(rows)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest.load_companies")
    parser.add_argument("--csv", type=Path, default=COMPANIES_CSV, help="library CSV to load")
    args = parser.parse_args(argv)

    conn = get_conn()
    try:
        apply_schema(conn)
        db_file = conn.execute("PRAGMA database_list").fetchone()["file"]
        try:
            count = load_companies(conn, args.csv)
        except LibraryError as error:
            print(f"{args.csv}: not loaded, nothing written", file=sys.stderr)
            for problem in error.problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
    finally:
        conn.close()

    print(f"loaded {count} companies into {db_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
