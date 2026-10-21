"""Match the Glassdoor review dump to our company library.

Source: data/raw/all_reviews.csv, from the Kaggle dataset
davidgauthier/glassdoor-job-reviews-2, licensed CC BY-NC-SA 4.0.

Run with:  python -m ingest.load_glassdoor_reviews

Reads the 3.8 GB file as a stream and writes only the rows belonging to a
company in data/raw/company_aliases.csv, so nothing is ever held in memory
except the per-company counters and one output chunk. Writes:

    data/raw/glassdoor_reviews_matched.csv   the matched reviews
    data/raw/glassdoor_match_report.txt      per-company coverage

Loading these rows into the SQLite reviews table is a separate, later step.
No reviewer names or other personal fields are read or stored; the source has
no name column, and the free-text advice and employment-status columns are
left behind.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import defaultdict

from jmsa.aliases import ALIASES_CSV, normalise, read_aliases
from jmsa.config import COMPANIES_CSV, RAW_DIR

SOURCE_CSV = RAW_DIR / "all_reviews.csv"
OUT_CSV = RAW_DIR / "glassdoor_reviews_matched.csv"
REPORT_TXT = RAW_DIR / "glassdoor_match_report.txt"

CITATION = (
    "davidgauthier/glassdoor-job-reviews-2 (all_reviews.csv), Kaggle, "
    "licensed CC BY-NC-SA 4.0"
)

# Reviews carried over from Mindtree, which merged into LTIMindtree in 2022.
# They describe the pre-merger company, so they are flagged rather than
# silently presented as LTIMindtree.
PRE_MERGER_ALIASES = {"mindtree"}

# Rows are buffered and written in batches; nothing accumulates in memory.
CHUNK_ROWS = 50_000

OUT_COLUMNS = [
    "company_id",
    "review_date",
    "rating",
    "headline",
    "pros",
    "cons",
    "job_title",
    # Every sub-rating the source carries. The first three are Glassdoor's
    # v/o/x codes (yes / neutral / no), not numbers.
    "recommend",
    "ceo_approval",
    "business_outlook",
    "career_opportunities",
    "compensation_and_benefits",
    "senior_management",
    "work_life_balance",
    "culture_and_values",
    "diversity_and_inclusion",
    "is_pre_merger",
]

# The source pads its free-text fields with spaces (" Senior Analyst"), which
# would otherwise read as distinct job titles once these rows are grouped.
STRIP_COLUMNS = frozenset({"headline", "pros", "cons", "job_title"})

# Source header -> our output column, for the fields copied straight across.
SOURCE_FIELDS = {
    "rating": "rating",
    "title": "headline",
    "pros": "pros",
    "cons": "cons",
    "job": "job_title",
    "Recommend": "recommend",
    "CEO Approval": "ceo_approval",
    "Business Outlook": "business_outlook",
    "Career Opportunities": "career_opportunities",
    "Compensation and Benefits": "compensation_and_benefits",
    "Senior Management": "senior_management",
    "Work/Life Balance": "work_life_balance",
    "Culture & Values": "culture_and_values",
    "Diversity & Inclusion": "diversity_and_inclusion",
}

MONTHS = {
    m: i for i, m in enumerate(
        "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), start=1
    )
}
# Source dates look like "Nov 19, 2022" with occasional trailing spaces.
DATE_RE = re.compile(r"([A-Za-z]{3})[a-z]*\s+(\d{1,2}),\s*(\d{4})")

# The employer sits inside firm_link, which comes in two shapes:
#   Reviews/Oracle-Reviews-E1737.htm
#   https://www.glassdoor.com/Reviews/Oracle-Reviews-E1737.htm
# Take the text before "-Reviews-E<digits>", then keep the last path segment.
LINK_RE = re.compile(r"(.+?)-Reviews-E\d+", re.IGNORECASE)


def iso_date(raw: str) -> str:
    """'Nov 19, 2022' -> '2022-11-19'. Empty string when unparseable."""
    match = DATE_RE.search(raw or "")
    if not match:
        return ""
    mon, day, year = match.groups()
    month = MONTHS.get(mon.title())
    if not month:
        return ""
    return f"{year}-{month:02d}-{int(day):02d}"


def firm_from_link(link: str) -> str:
    match = LINK_RE.search(link or "")
    if not match:
        return ""
    return match.group(1).rsplit("/", 1)[-1]


def load_aliases() -> dict[str, tuple[str, int]]:
    """normalised alias -> (company_id, is_pre_merger), reviews aliases only."""
    aliases: dict[str, tuple[str, int]] = {}
    for company_id, alias in read_aliases("glassdoor_reviews"):
        key = normalise(alias)
        flag = 1 if key in PRE_MERGER_ALIASES else 0
        aliases[key] = (company_id, flag)
    return aliases


def load_library_ids() -> list[str]:
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as handle:
        return [row["company_id"] for row in csv.DictReader(handle)]


def main() -> None:
    # One cell can hold a very long review, so lift the field cap.
    csv.field_size_limit(2**31 - 1)

    for path in (SOURCE_CSV, ALIASES_CSV):
        if not path.exists():
            raise SystemExit(f"missing input: {path}")

    aliases = load_aliases()
    library_ids = load_library_ids()

    stats: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "since2020": 0, "first": "", "last": "", "nodate": 0, "pre": 0}
    )
    scanned = 0
    kept = 0

    with SOURCE_CSV.open(newline="", encoding="utf-8", errors="replace") as src, \
            OUT_CSV.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.reader(src)
        header = next(reader)
        index = {name: position for position, name in enumerate(header)}

        missing = [name for name in SOURCE_FIELDS if name not in index]
        if missing or "firm_link" not in index or "date" not in index:
            raise SystemExit(f"unexpected source header; missing {missing or ['firm_link/date']}")

        # Pre-compute the source position for each output column once.
        copy_plan = [(index[source], SOURCE_FIELDS[source]) for source in SOURCE_FIELDS]
        link_at, date_at = index["firm_link"], index["date"]

        writer = csv.writer(dst, lineterminator="\n")
        writer.writerow(OUT_COLUMNS)

        buffer: list[list] = []
        for row in reader:
            scanned += 1
            if scanned % 2_000_000 == 0:
                print(f"  scanned {scanned:,} rows, kept {kept:,}", flush=True)

            match = aliases.get(normalise(firm_from_link(row[link_at])))
            if match is None:
                continue
            company_id, pre_merger = match

            review_date = iso_date(row[date_at])
            values = {
                name: row[position].strip() if name in STRIP_COLUMNS else row[position]
                for position, name in copy_plan
            }
            values["company_id"] = company_id
            values["review_date"] = review_date
            values["is_pre_merger"] = pre_merger
            buffer.append([values[column] for column in OUT_COLUMNS])
            kept += 1

            entry = stats[company_id]
            entry["total"] += 1
            entry["pre"] += pre_merger
            if review_date:
                if review_date >= "2020-01-01":
                    entry["since2020"] += 1
                if not entry["first"] or review_date < entry["first"]:
                    entry["first"] = review_date
                if not entry["last"] or review_date > entry["last"]:
                    entry["last"] = review_date
            else:
                entry["nodate"] += 1

            if len(buffer) >= CHUNK_ROWS:
                writer.writerows(buffer)
                buffer.clear()

        if buffer:
            writer.writerows(buffer)

    report = build_report(stats, library_ids, scanned, kept)
    REPORT_TXT.write_text(report, encoding="utf-8")
    print(report)
    print(f"wrote {OUT_CSV}")
    print(f"wrote {REPORT_TXT}")


def build_report(stats, library_ids, scanned, kept) -> str:
    lines: list[str] = []
    add = lines.append

    add("Glassdoor review match report")
    add(f"Source: {CITATION}")
    add("")
    add(f"Rows scanned in all_reviews.csv : {scanned:,}")
    add(f"Rows kept (matched a company)   : {kept:,}")
    add(f"Companies in library            : {len(library_ids)}")
    add(f"Companies with >=1 review       : {sum(1 for c in library_ids if stats[c]['total'])}")
    add("")

    add("Per company")
    add(f"  {'company_id':30} {'total':>9} {'2020+':>9}  {'first':<10} {'last':<10}")
    ranked = sorted(library_ids, key=lambda c: -stats[c]["total"])
    for company_id in ranked:
        entry = stats[company_id]
        if not entry["total"]:
            continue
        flag = "  (pre-merger Mindtree)" if entry["pre"] else ""
        add(
            f"  {company_id:30} {entry['total']:>9,} {entry['since2020']:>9,}"
            f"  {entry['first'] or 'n/a':<10} {entry['last'] or 'n/a':<10}{flag}"
        )
    add("")

    thin = [c for c in ranked if 0 < stats[c]["total"] < 20]
    add(f"Companies under the 20-review threshold ({len(thin)})")
    if thin:
        for company_id in thin:
            add(f"  {company_id:30} {stats[company_id]['total']:>9,}")
    else:
        add("  none")
    add("")

    zero = [c for c in library_ids if not stats[c]["total"]]
    add(f"Companies with zero matched reviews ({len(zero)})")
    for company_id in sorted(zero):
        add(f"  {company_id}")
    add("")

    nodate = sum(stats[c]["nodate"] for c in library_ids)
    pre = sum(stats[c]["pre"] for c in library_ids)
    add(f"Reviews with an unparseable date (kept, review_date empty): {nodate:,}")
    add(f"Reviews flagged is_pre_merger: {pre:,}")
    add(f"Grand total matched reviews: {kept:,}")
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
