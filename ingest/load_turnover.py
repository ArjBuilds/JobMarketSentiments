"""Load published attrition (F5) from data/turnover.csv into turnover.

Run with:  python -m ingest.load_turnover

Run ingest.load_companies first, and process.turnover_proxy before it if you
want the proxy comparison in the report. data/turnover.csv is curated by
hand from primary documents only (annual reports, BRSR, quarterly results,
official ESG reports), one row per figure, each with its period, definition,
entity, source URL and page reference. Nothing is estimated or rounded.

The file is checked as a whole: if any row fails, nothing is written and
every problem is listed. Otherwise every run replaces the published rows
(is_proxy = 0) in one transaction and never touches the proxy rows.

A company can have several rows. The latest (by period_end) is the one the
dashboard shows; rows whose period overlaps the proxy window are used only
in the report's proxy comparison: a Spearman rank correlation between the
proxy and published attrition for the same years.
"""

from __future__ import annotations

import argparse
import csv
import re
import sqlite3
import sys
from collections import Counter
from datetime import date
from pathlib import Path

from jmsa.config import DATA_DIR, RAW_DIR
from jmsa.db import apply_schema, get_conn
from jmsa.display import plural
from jmsa.sentiment import is_shown
from jmsa.stats import MIN_PAIRS, ranks, spearman  # noqa: F401 (ranks: tests import it from here)
from jmsa.turnover import BASES, SCOPES, WINDOW_TITLE, overlaps_window

TURNOVER_CSV = DATA_DIR / "turnover.csv"
REPORT_PATH = RAW_DIR / "turnover_load_report.txt"

COLUMNS = ["company_id", "period", "period_start", "period_end", "attrition_pct", "basis", "scope",
           "definition", "entity", "source_url", "source_ref", "retrieved_on", "note"]
REQUIRED = [c for c in COLUMNS if c != "note"]

# A percentage as printed: digits, optionally a decimal point and digits.
# "12,5" or "12.5%" is a typo in the file, not something to guess at.
NUMBER = re.compile(r"\d+(\.\d+)?")

class TurnoverError(ValueError):
    """turnover.csv failed a check; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def iso_date(text: str) -> bool:
    try:
        date.fromisoformat(text)
    except ValueError:
        return False
    return len(text) == 10


def read_turnover_csv(path: str | Path, company_ids: set[str]) -> list[dict]:
    """The file's rows, after checking every one. Raises TurnoverError listing all problems."""
    problems: list[str] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            raise TurnoverError([f"{path}: header is {reader.fieldnames}, expected {COLUMNS}"])
        rows = []
        seen: set[tuple[str, str]] = set()
        ends: set[tuple[str, str]] = set()
        for row in reader:
            line = reader.line_num
            row = {k: (v or "").strip() for k, v in row.items()}
            missing = [c for c in REQUIRED if not row[c]]
            if missing:
                problems.append(f"line {line}: missing {', '.join(missing)}")
                continue
            if row["company_id"] not in company_ids:
                problems.append(f"line {line}: unknown company_id {row['company_id']!r}")
            key = (row["company_id"], row["period"])
            if key in seen:
                problems.append(f"line {line}: second row for {row['company_id']}, {row['period']!r}")
            seen.add(key)
            if not NUMBER.fullmatch(row["attrition_pct"]) or not 0 <= float(row["attrition_pct"]) <= 100:
                problems.append(f"line {line}: attrition_pct {row['attrition_pct']!r} is not a number from 0 to 100")
            if row["basis"] not in BASES:
                problems.append(f"line {line}: basis {row['basis']!r} is not one of {list(BASES)}")
            if row["scope"] not in SCOPES:
                problems.append(f"line {line}: scope {row['scope']!r} is not one of {list(SCOPES)}")
            if not row["source_url"].startswith("https://"):
                problems.append(f"line {line}: source_url must start with https://")
            dates_ok = True
            for column in ("period_start", "period_end", "retrieved_on"):
                if not iso_date(row[column]):
                    problems.append(f"line {line}: {column} {row[column]!r} is not an ISO date (YYYY-MM-DD)")
                    dates_ok = False
            if dates_ok and row["period_end"] < row["period_start"]:
                problems.append(f"line {line}: period_end is before period_start")
            # The latest figure is the one with the latest period_end, so two
            # rows of a company ending the same day would make it ambiguous.
            end = (row["company_id"], row["period_end"])
            if end in ends:
                problems.append(f"line {line}: another {row['company_id']} row also ends on {row['period_end']}")
            ends.add(end)
            rows.append(row)
    if problems:
        raise TurnoverError(problems)
    return rows


def load_turnover(conn: sqlite3.Connection, path: str | Path = TURNOVER_CSV) -> list[dict]:
    """Check the file, then replace every published row with its rows."""
    company_ids = {row["company_id"] for row in conn.execute("SELECT company_id FROM companies")}
    rows = read_turnover_csv(path, company_ids)
    with conn:
        conn.execute("DELETE FROM turnover WHERE is_proxy = 0")
        conn.executemany(
            "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, attrition_pct,"
            " attrition_text, basis, scope, definition, entity, source_url, source_ref, retrieved_on,"
            " method_note) VALUES (?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(r["company_id"], r["period"], r["period_start"], r["period_end"], float(r["attrition_pct"]),
              r["attrition_pct"], r["basis"], r["scope"], r["definition"], r["entity"], r["source_url"],
              r["source_ref"], r["retrieved_on"], r["note"] or None) for r in rows],
        )
    return rows


# --- the proxy comparison ---------------------------------------------------

def comparison_pairs(conn: sqlite3.Connection) -> list[dict]:
    """One pair per company with both a shown proxy and a published figure
    whose period overlaps the proxy window (the latest such figure)."""
    proxies = {row["company_id"]: row for row in conn.execute("SELECT * FROM turnover WHERE is_proxy = 1")}
    published: dict[str, sqlite3.Row] = {}
    for row in conn.execute("SELECT * FROM turnover WHERE is_proxy = 0 ORDER BY period_end"):
        if overlaps_window(row["period_start"], row["period_end"]):
            published[row["company_id"]] = row
    flags = {row["company_id"]: row for row in conn.execute(
        "SELECT c.company_id, c.publishes_attrition, s.pre_merger_count FROM companies c"
        " LEFT JOIN review_summary s ON s.company_id = c.company_id AND s.period = 'all'")}
    pairs = []
    for company_id, row in sorted(published.items()):
        proxy = proxies.get(company_id)
        if proxy is None or not is_shown(proxy["reviews_in_window"]):
            continue
        n = proxy["reviews_in_window"]
        flag = flags.get(company_id)
        pairs.append({
            "company_id": company_id,
            "attrition": row["attrition_pct"],
            "period": row["period"],
            "basis": row["basis"],
            "proxy": 100 * proxy["reviews_matched"] / n,
            "leaving": 100 * proxy["reviews_leaving"] / n,
            "it_major": bool(flag and flag["publishes_attrition"] == "yes"),
            "pre_merger": bool(flag and flag["pre_merger_count"]),
        })
    return pairs


def comparison_lines(pairs: list[dict]) -> list[str]:
    lines = [f"Proxy against published attrition for periods overlapping {WINDOW_TITLE}",
             "Spearman rank correlation. Small samples: read as a sanity check, not a finding.", ""]
    if not pairs:
        return lines + ["  No company has both a shown proxy and an overlapping published figure.",
                        "  Run python -m process.turnover_proxy first."]
    lines.append(f"  {'company':28} {'published':>9} {'proxy':>7} {'leaving':>8}  basis       period")
    for p in pairs:
        lines.append(f"  {p['company_id']:28} {p['attrition']:>8g}% {p['proxy']:>7.1f} {p['leaving']:>8.1f}"
                     f"  {p['basis']:11} {p['period']}")
    lines.append("  (proxy and leaving are per 100 reviews; leaving is the leaving/attrition part)")
    lines.append("")
    for title, group in (("IT majors (publishes_attrition = yes)", [p for p in pairs if p["it_major"]]),
                         ("All companies with both", pairs)):
        attrition = [p["attrition"] for p in group]
        total = spearman([p["proxy"] for p in group], attrition)
        leaving = spearman([p["leaving"] for p in group], attrition)
        mix = ", ".join(f"{basis} {count}" for basis, count in sorted(Counter(p["basis"] for p in group).items()))
        lines.append(f"{title}: n = {len(group)}; basis mix: {mix or 'none'}")
        lines.append(f"  proxy total vs published:            "
                     f"{f'{total:+.2f}' if total is not None else f'not computed (needs {MIN_PAIRS}+ pairs with spread)'}")
        lines.append(f"  proxy leaving/attrition vs published: "
                     f"{f'{leaving:+.2f}' if leaving is not None else f'not computed (needs {MIN_PAIRS}+ pairs with spread)'}")
    caveats = [p["company_id"] for p in pairs if p["pre_merger"]]
    if caveats:
        lines.append("")
        lines.append(f"Caveat: {', '.join(caveats)}: the proxy comes from pre-merger Mindtree reviews, while the "
                     "published figure is the merged company's.")
    lines.append("Caveat: periods differ in length and alignment (e.g. Accenture's fiscal year ends in August, "
                 "Cognizant's and Nestle India's 2022 figures are calendar years), and definitions differ.")
    return lines


def build_report(rows: list[dict], pairs: list[dict]) -> str:
    latest: dict[str, dict] = {}
    for row in rows:
        if row["company_id"] not in latest or row["period_end"] > latest[row["company_id"]]["period_end"]:
            latest[row["company_id"]] = row
    lines = [f"Published rows loaded: {len(rows)} for {plural(len(latest), 'company')} "
             f"({plural(len(rows) - len(latest), 'older row')} kept for the proxy comparison only)", ""]
    lines.append("Shown on the dashboard (latest per company)")
    for company_id, row in sorted(latest.items()):
        lines.append(f"  {company_id:28} {row['attrition_pct']:>6}%  {row['basis']:11} {row['scope']:17} "
                     f"{row['period']}")
    lines.append("")
    lines.append(f"By basis: {dict(Counter(r['basis'] for r in latest.values()))}")
    lines.append(f"By scope: {dict(Counter(r['scope'] for r in latest.values()))}")
    lines.append("")
    return "\n".join(lines + comparison_lines(pairs))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest.load_turnover")
    parser.add_argument("--csv", type=Path, default=TURNOVER_CSV, help="published attrition CSV to load")
    args = parser.parse_args(argv)

    conn = get_conn()
    try:
        apply_schema(conn)
        try:
            rows = load_turnover(conn, args.csv)
        except TurnoverError as error:
            print(f"{args.csv}: not loaded, nothing written", file=sys.stderr)
            for problem in error.problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
        pairs = comparison_pairs(conn)
    finally:
        conn.close()

    report = build_report(rows, pairs)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nReport written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
