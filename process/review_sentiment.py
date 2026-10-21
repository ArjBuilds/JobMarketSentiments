"""Score the loaded reviews with VADER, tag their themes, and summarise per company.

Run with:  python -m process.review_sentiment [--company ID] [--limit N] [--rescore]

Run ingest.load_reviews first. For each review:

    sentiment   headline, pros and cons are scored by VADER separately and
                combined as mean(headline, mean(pros, cons)) -- see
                jmsa.sentiment.combine. A review with no text stays NULL.
    themes      data/themes.csv lists keywords for pay, culture, wlb and
                management. A theme's score for a review is the VADER score
                of the section(s) that mention it, so a mention in the cons
                counts as a complaint and one in the pros as praise.

Reviews are scored 50,000 per transaction. By default only reviews with no
score yet are scored, so after a crash or Ctrl+C just run it again. Use
--rescore after editing themes.csv or the scoring method.

Finally review_summary is rebuilt for the scope: one row per company for
all time and one for 2020-2023, which is what the dashboard reads.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
import time
from pathlib import Path

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from ingest.load_reviews import EXPECTED_ROWS, REBUILD_HINT
from jmsa.config import DATA_DIR
from jmsa.db import apply_schema, get_conn
from jmsa.sentiment import MIN_REVIEWS, PERIODS, THEMES, combine, label, mean

THEMES_CSV = DATA_DIR / "themes.csv"

BATCH_ROWS = 50_000

SECTIONS = ("headline", "pros", "cons")

UPDATE_SQL = f"""
    UPDATE reviews SET
        sentiment_compound = ?,
        sentiment_label = ?,
        themes = ?,
        {", ".join(f"theme_{theme} = ?" for theme in THEMES)}
    WHERE review_id = ?
"""


class ThemesError(ValueError):
    """themes.csv failed a check; nothing was scored."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def keyword_pattern(keyword: str) -> str:
    """Regex for one keyword. A space also matches a hyphen or slash, so
    "work life balance" finds "work-life balance" and "work/life balance"."""
    return r"[\s\-/]+".join(re.escape(word) for word in keyword.lower().split())


def read_themes(path: str | Path = THEMES_CSV) -> dict[str, re.Pattern]:
    """theme -> one compiled pattern matching any of its keywords.

    \\b on both sides means whole words only: "pay" matches "pay" but not
    "PayPal" or "payment".
    """
    keywords: dict[str, list[str]] = {theme: [] for theme in THEMES}
    problems: list[str] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["theme", "keyword"]:
            raise ThemesError([f"{path}: header is {reader.fieldnames}, expected ['theme', 'keyword']"])
        for row in reader:
            theme, keyword = (row["theme"] or "").strip(), (row["keyword"] or "").strip()
            if theme not in keywords:
                problems.append(f"line {reader.line_num}: theme {theme!r} is not one of {list(THEMES)}")
            elif not keyword:
                problems.append(f"line {reader.line_num}: empty keyword")
            else:
                keywords[theme].append(keyword)
    problems += [f"theme {theme!r} has no keywords" for theme, words in keywords.items() if not words]
    if problems:
        raise ThemesError(problems)

    return {
        theme: re.compile(r"\b(?:" + "|".join(keyword_pattern(k) for k in words) + r")\b", re.IGNORECASE)
        for theme, words in keywords.items()
    }


def score_review(analyzer, patterns: dict[str, re.Pattern], texts: dict[str, str | None]) -> list:
    """One review -> [compound, label, themes, theme_pay, theme_culture, ...]."""
    part = {
        section: analyzer.polarity_scores(texts[section])["compound"] if texts[section] else None
        for section in SECTIONS
    }
    compound = combine(part["headline"], part["pros"], part["cons"])
    theme_scores = [
        mean(part[section] for section in SECTIONS if texts[section] and pattern.search(texts[section]))
        for pattern in patterns.values()
    ]
    matched = [theme for theme, score in zip(patterns, theme_scores) if score is not None]
    return [compound, label(compound), ";".join(matched) or None, *theme_scores]


def check_schema(conn: sqlite3.Connection) -> None:
    have = {row[1] for row in conn.execute("PRAGMA table_info(reviews)")}
    if f"theme_{THEMES[0]}" not in have:
        raise SystemExit(f"the reviews table predates milestone 4; {REBUILD_HINT}")


def score_reviews(
    conn: sqlite3.Connection,
    themes_path: str | Path = THEMES_CSV,
    company: str | None = None,
    limit: int | None = None,
    rescore: bool = False,
    batch_rows: int = BATCH_ROWS,
    progress=None,
) -> dict:
    """Score reviews in the scope, batch by batch. Returns run stats."""
    patterns = read_themes(themes_path)
    analyzer = SentimentIntensityAnalyzer()

    # Paging by "review_id > the last one seen" rather than re-asking for
    # unscored rows: reviews with no text stay NULL, and would otherwise be
    # fetched again forever.
    conditions, args = ["review_id > ?"], []
    if company is not None:
        conditions.append("company_id = ?")
        args.append(company)
    if not rescore:
        conditions.append("sentiment_compound IS NULL")
    query = (f"SELECT review_id, {', '.join(SECTIONS)} FROM reviews "
             f"WHERE {' AND '.join(conditions)} ORDER BY review_id LIMIT ?")

    stats = {"processed": 0, "scored": 0, "no_text": 0}
    started = time.perf_counter()
    last = ""
    try:
        while limit is None or stats["processed"] < limit:
            size = batch_rows if limit is None else min(batch_rows, limit - stats["processed"])
            rows = conn.execute(query, [last, *args, size]).fetchall()
            if not rows:
                break
            updates = []
            for row in rows:
                values = score_review(analyzer, patterns, {s: row[s] for s in SECTIONS})
                updates.append([*values, row["review_id"]])
                if values[0] is None:
                    stats["no_text"] += 1
                else:
                    stats["scored"] += 1
            conn.executemany(UPDATE_SQL, updates)
            conn.commit()
            stats["processed"] += len(rows)
            last = rows[-1]["review_id"]
            if progress:
                progress(f"  scored {stats['processed']:,} reviews, up to {last}  "
                         f"({time.perf_counter() - started:.0f} s)")
    except BaseException:
        # Covers Ctrl+C too: committed batches stay, and the next run picks
        # up from the first review that still has no score.
        conn.rollback()
        raise

    stats["seconds"] = time.perf_counter() - started
    return stats


SUMMARY_COLUMNS = [
    "company_id", "period", "review_count", "first_date", "last_date", "avg_compound",
    "share_positive", "share_neutral", "share_negative",
    *(f"{theme}_{part}" for theme in THEMES for part in ("count", "compound")),
    "pre_merger_count",
]

# Only scored reviews are counted, so a review with no text adds nothing.
# sentiment_label = 'positive' is 1 or 0 per review; its average is the share.
SUMMARY_SELECT = f"""
    SELECT company_id, ?, count(*), min(review_date), max(review_date), avg(sentiment_compound),
           avg(sentiment_label = 'positive'), avg(sentiment_label = 'neutral'),
           avg(sentiment_label = 'negative'),
           {", ".join(f"count(theme_{theme}), avg(theme_{theme})" for theme in THEMES)},
           sum(is_pre_merger)
    FROM reviews
"""


def rebuild_summary(conn: sqlite3.Connection, company: str | None = None) -> None:
    """Recompute review_summary for one company or all, in one transaction.

    A company gets a row for a period only if it has a scored review in it;
    a review with no date can't be placed in 2020-2023 and only counts in "all".
    """
    with conn:
        if company is None:
            conn.execute("DELETE FROM review_summary")
        else:
            conn.execute("DELETE FROM review_summary WHERE company_id = ?", (company,))
        for period, bounds in PERIODS.items():
            conditions, args = ["sentiment_compound IS NOT NULL"], [period]
            if bounds is not None:
                conditions.append("review_date BETWEEN ? AND ?")
                args += bounds
            if company is not None:
                conditions.append("company_id = ?")
                args.append(company)
            conn.execute(
                f"INSERT INTO review_summary ({', '.join(SUMMARY_COLUMNS)}) "
                f"{SUMMARY_SELECT} WHERE {' AND '.join(conditions)} GROUP BY company_id",
                args,
            )


def build_report(conn: sqlite3.Connection) -> str:
    def one(sql: str):
        return conn.execute(sql).fetchone()[0]

    no_text = "headline IS NULL AND pros IS NULL AND cons IS NULL"
    scored = one("SELECT count(*) FROM reviews WHERE sentiment_compound IS NOT NULL")
    empty = one(f"SELECT count(*) FROM reviews WHERE {no_text}")
    waiting = one(f"SELECT count(*) FROM reviews WHERE sentiment_compound IS NULL AND NOT ({no_text})")
    with_figures = one("SELECT count(*) FROM review_summary WHERE period = 'all'")
    unavailable = [r[0] for r in conn.execute(
        "SELECT company_id FROM companies WHERE company_id NOT IN "
        "(SELECT company_id FROM review_summary WHERE period = 'all') ORDER BY company_id")]
    thin = [f"{r[0]} ({r[1]})" for r in conn.execute(
        "SELECT company_id, review_count FROM review_summary "
        "WHERE period = 'all' AND review_count < ? ORDER BY company_id", (MIN_REVIEWS,))]
    pre = one("SELECT coalesce(sum(pre_merger_count), 0) FROM review_summary WHERE period = 'all'")

    lines = [
        f"reviews scored: {scored:,}",
        f"reviews with no text (sentiment stays NULL): {empty:,}",
        f"companies with figures: {with_figures}",
        f"not available ({len(unavailable)}): {', '.join(unavailable) or 'none'}",
        f"under {MIN_REVIEWS} reviews, figures hidden ({len(thin)}): {', '.join(thin) or 'none'}",
        f"pre-merger reviews: {pre:,}",
    ]
    if waiting:
        lines.append(f"{waiting:,} reviews still have no score; run again without --limit")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m process.review_sentiment")
    parser.add_argument("--company", help="score only this company_id")
    parser.add_argument("--limit", type=int, help="stop after this many reviews (for test runs)")
    parser.add_argument("--rescore", action="store_true",
                        help="score every review again, not only unscored ones")
    parser.add_argument("--themes", type=Path, default=THEMES_CSV, help="theme keywords CSV")
    args = parser.parse_args(argv)

    conn = get_conn()
    try:
        apply_schema(conn)
        check_schema(conn)
        print(f"database: {conn.execute('PRAGMA database_list').fetchone()['file']}", flush=True)
        try:
            stats = score_reviews(conn, args.themes, args.company, args.limit, args.rescore,
                                  progress=lambda line: print(line, flush=True))
        except ThemesError as error:
            print(f"{args.themes}: not used, nothing scored", file=sys.stderr)
            for problem in error.problems:
                print(f"  {problem}", file=sys.stderr)
            return 1

        seconds = stats["seconds"]
        rate = stats["processed"] / seconds if seconds else 0
        print(f"scored {stats['scored']:,} reviews in {seconds:.1f} s ({rate:,.0f} rows/s); "
              f"{stats['no_text']:,} had no text")
        if args.company is None and 0 < stats["processed"] < EXPECTED_ROWS and rate:
            print(f"at this rate all {EXPECTED_ROWS:,} reviews take about {EXPECTED_ROWS / rate / 60:.1f} min")

        started = time.perf_counter()
        rebuild_summary(conn, args.company)
        print(f"review_summary rebuilt in {time.perf_counter() - started:.1f} s")
        print()
        print(build_report(conn))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
