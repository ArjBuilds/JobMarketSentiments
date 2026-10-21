"""Load the matched Glassdoor reviews into the reviews table.

Source: data/raw/glassdoor_reviews_matched.csv, written by
ingest.load_glassdoor_reviews (1,799,628 reviews of 78 companies). This step
copies the rows in; scoring them is process.review_sentiment.

Run with:  python -m ingest.load_reviews [--company ID] [--limit N] [--resume]

The file is read as a stream and written 50,000 rows per transaction, so a
crash loses at most the batch in progress. Two ways to run it:

    default   delete the scope (every review, or one --company) and load it
              again from the top. Running it twice leaves the same table.
    --resume  delete nothing; skip every record up to the highest review_id
              already loaded in the scope. Batches commit in file order, so
              everything up to that id is complete. Use after a crash or Ctrl+C.

review_id is the record's position in the CSV (gd-0000001), zero-padded so
that comparing ids as text gives the same order as comparing the numbers.
Each load also drops the scope's review_summary rows, which
process.review_sentiment rebuilds.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path

from ingest.load_glassdoor_reviews import OUT_COLUMNS, OUT_CSV
from jmsa.db import apply_schema, get_conn

REVIEWS_CSV = OUT_CSV

# The row count in data/raw/glassdoor_match_report.txt. Used only for the
# progress display and the --limit time estimate.
EXPECTED_ROWS = 1_799_628

BATCH_ROWS = 50_000
PROGRESS_EVERY = 100_000

TEXT_COLUMNS = ("headline", "pros", "cons", "job_title")
CODE_COLUMNS = ("recommend", "ceo_approval", "business_outlook")
STAR_COLUMNS = (
    "career_opportunities",
    "compensation_and_benefits",
    "senior_management",
    "work_life_balance",
    "culture_and_values",
    "diversity_and_inclusion",
)
CODES = {"v", "r", "o", "x"}
# "4" or "4.0". Anything else (the source has scraped codes such as "10u0eun"
# in some cells) is not a star rating and is stored as NULL.
STAR_RE = re.compile(r"^([1-5])(\.0)?$")

INSERT_COLUMNS = [
    "review_id", "company_id", "review_date", "rating", *TEXT_COLUMNS,
    "is_pre_merger", *CODE_COLUMNS, *STAR_COLUMNS,
]
INSERT_SQL = (
    f"INSERT INTO reviews ({', '.join(INSERT_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in INSERT_COLUMNS)})"
)

REBUILD_HINT = (
    "rebuild it: rm data/jmsa.db, then python -m jmsa.db init, "
    "python -m ingest.load_companies and python -m ingest.load_glassdoor_ratings"
)


class ReviewsError(ValueError):
    """The inputs or the database failed a check."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def review_id(record_no: int) -> str:
    return f"gd-{record_no:07d}"


def parse(values: dict[str, str], discarded: Counter) -> list:
    """One CSV record -> the INSERT_COLUMNS values after review_id.

    Empty cells become None (NULL). A sub-rating that isn't a valid value is
    also None, and is counted in discarded so the report can say how many.
    """
    out = [
        values["company_id"],
        values["review_date"] or None,
        float(values["rating"]) if values["rating"] else None,
    ]
    out += [values[column] or None for column in TEXT_COLUMNS]
    out.append(int(values["is_pre_merger"]))
    for column in CODE_COLUMNS:
        code = values[column]
        if code and code not in CODES:
            discarded[column] += 1
        out.append(code if code in CODES else None)
    for column in STAR_COLUMNS:
        match = STAR_RE.match(values[column])
        if values[column] and not match:
            discarded[column] += 1
        out.append(int(match.group(1)) if match else None)
    return out


def check_schema(conn: sqlite3.Connection) -> None:
    have = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    missing = [column for column in INSERT_COLUMNS if column not in have]
    if missing:
        raise ReviewsError([
            f"the reviews table has no column {missing[0]!r}: the database "
            f"predates milestone 4, and init can't add columns to an existing table",
            REBUILD_HINT,
        ])


def load_reviews(
    conn: sqlite3.Connection,
    path: str | Path = REVIEWS_CSV,
    company: str | None = None,
    limit: int | None = None,
    resume: bool = False,
    batch_rows: int = BATCH_ROWS,
    progress=None,
) -> dict:
    """Load the CSV (or one company of it) into reviews. Returns run stats.

    progress, if given, is called with a line of text every PROGRESS_EVERY
    records read.
    """
    check_schema(conn)
    companies = {row[0] for row in conn.execute("SELECT company_id FROM companies")}
    if not companies:
        raise ReviewsError(["the companies table is empty; run python -m ingest.load_companies first"])
    if company is not None and company not in companies:
        raise ReviewsError([f"--company {company!r} is not in the companies table"])

    scope_sql, scope_args = ("WHERE company_id = ?", [company]) if company else ("", [])
    start_after = None
    if resume:
        start_after = conn.execute(f"SELECT max(review_id) FROM reviews {scope_sql}", scope_args).fetchone()[0]

    stats = {"read": 0, "loaded": 0, "undated": 0, "companies": set(),
             "discarded": Counter(), "resumed_after": start_after}
    started = time.perf_counter()
    csv.field_size_limit(2**31 - 1)

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header != OUT_COLUMNS:
            raise ReviewsError([f"{path}: header is {header}", f"expected {OUT_COLUMNS}"])

        # Nothing is committed until the first batch is, so a check that
        # fails in the first batch leaves the old rows exactly as they were.
        try:
            conn.execute(f"DELETE FROM review_summary {scope_sql}", scope_args)
            if not resume:
                conn.execute(f"DELETE FROM reviews {scope_sql}", scope_args)

            batch: list[list] = []
            for record_no, row in enumerate(reader, start=1):
                stats["read"] = record_no
                if progress and record_no % PROGRESS_EVERY == 0:
                    progress(f"  read {record_no:,} of ~{EXPECTED_ROWS:,} records, "
                             f"loaded {stats['loaded']:,}  ({time.perf_counter() - started:.0f} s)")
                if len(row) != len(OUT_COLUMNS):
                    raise ReviewsError([f"record {record_no}: {len(row)} fields, expected {len(OUT_COLUMNS)}"])
                values = dict(zip(OUT_COLUMNS, row))
                if company is not None and values["company_id"] != company:
                    continue
                rid = review_id(record_no)
                if start_after is not None and rid <= start_after:
                    continue
                if values["company_id"] not in companies:
                    raise ReviewsError([
                        f"record {record_no}: company_id {values['company_id']!r} is not in "
                        "the companies table; check companies.csv and company_aliases.csv",
                    ])

                batch.append([rid, *parse(values, stats["discarded"])])
                stats["loaded"] += 1
                stats["companies"].add(values["company_id"])
                if not values["review_date"]:
                    stats["undated"] += 1

                if len(batch) >= batch_rows:
                    conn.executemany(INSERT_SQL, batch)
                    conn.commit()
                    batch.clear()
                if limit is not None and stats["loaded"] >= limit:
                    break

            conn.executemany(INSERT_SQL, batch)
            conn.commit()
        except BaseException:
            # Covers Ctrl+C too: the batch in progress is undone, every
            # committed batch stays, and --resume carries on from there.
            conn.rollback()
            raise

    stats["seconds"] = time.perf_counter() - started
    return stats


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest.load_reviews")
    parser.add_argument("--csv", type=Path, default=REVIEWS_CSV, help="matched reviews CSV to load")
    parser.add_argument("--company", help="load only this company_id")
    parser.add_argument("--limit", type=int, help="stop after this many rows (for test runs)")
    parser.add_argument("--resume", action="store_true",
                        help="keep loaded rows and continue after the last one")
    args = parser.parse_args(argv)

    conn = get_conn()
    try:
        apply_schema(conn)
        db_file = conn.execute("PRAGMA database_list").fetchone()["file"]
        print(f"database: {db_file}", flush=True)
        try:
            stats = load_reviews(conn, args.csv, args.company, args.limit, args.resume,
                                 progress=lambda line: print(line, flush=True))
        except ReviewsError as error:
            print(f"{args.csv}: not loaded", file=sys.stderr)
            for problem in error.problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
    finally:
        conn.close()

    seconds = stats["seconds"]
    rate = stats["loaded"] / seconds if seconds else 0
    if stats["resumed_after"]:
        print(f"resumed after {stats['resumed_after']}")
    print(f"loaded {stats['loaded']:,} reviews for {len(stats['companies'])} companies "
          f"in {seconds:.1f} s ({rate:,.0f} rows/s)")
    print(f"  {stats['undated']:,} without a date (kept, review_date NULL)")
    if stats["discarded"]:
        print("  sub-rating values not stored (not 1-5, or not a v/r/o/x code):")
        for column, count in stats["discarded"].most_common():
            print(f"    {column:28} {count:>8,}")
    if args.limit is not None:
        if args.company is None and rate:
            print(f"--limit run: at this rate all {EXPECTED_ROWS:,} rows take about "
                  f"{EXPECTED_ROWS / rate / 60:.1f} min")
        print("this is a partial load; rerun without --limit before using the dashboard")
    print("next: python -m process.review_sentiment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
