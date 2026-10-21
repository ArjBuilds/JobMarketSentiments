"""Load the Naukri data-role postings into jobs (F8).

Source: data/raw/naukri_jobs_merged.csv, three merged Naukri exports of
Indian postings. Run with:  python -m ingest.load_jobs

Run ingest.load_companies first. Every run replaces jobs (and job_skills,
which hangs off it) in one transaction, so re-running gives the same rows.

The source's columns don't line up row by row. job_title and company_name
belong together, but post_url, post_time_relative, locations,
experience_required and skills_raw often come from a different posting. So,
for each row:

    1. title filter   keep it only if the title names a data role, using the
                      include/exclude keywords in data/data_role_keywords.csv;
    2. match          its company_name to one library company, by exact name
                      or a naukri alias in company_aliases.csv. A name in
                      REJECTED_NAMES never matches;
    3. verify         its link: keep url, posted_relative and city only when
                      the link's slug starts with this row's title and then
                      names this row's employer (as posted, as in the library,
                      or by a legal name in LINK_NAMES). Otherwise all three
                      are NULL. The city is read from the slug after the employer.

Then the matched rows are deduplicated (see dedupe()), because the same
title and employer were copied onto many rows whose other columns differ, so
whole-row dedup missed them. What's loaded is distinct listings, a lower
bound: same-title listings without a verified link count once.

locations, experience_required, package and skills_raw are never stored.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from jmsa.aliases import ALIASES_CSV, normalise, read_aliases
from jmsa.config import DATA_DIR, RAW_DIR
from jmsa.db import apply_schema, get_conn

NAUKRI_CSV = RAW_DIR / "naukri_jobs_merged.csv"
KEYWORDS_CSV = DATA_DIR / "data_role_keywords.csv"
REPORT_PATH = RAW_DIR / "naukri_match_report.txt"

SOURCE_COLUMNS = ("job_row_id", "job_title", "company_name", "post_url", "post_time_relative", "source_file")

# The alias rule: a company's own India operations and service centres count
# for it; agencies, namesakes and majority-owned businesses in a different
# line of work don't. These names were checked and turned down, so they can
# never match, even by an alias added later.
REJECTED_NAMES = {
    "ICICI Prudential Life": "majority-owned business in a different line of work (life insurance), not ICICI Bank",
    "ICICI Securities": "majority-owned business in a different line of work (broking), not ICICI Bank",
    "ICICI Lombard": "general insurer, not an ICICI Bank subsidiary in 2023",
    "HDFC Life": "majority-owned business in a different line of work (life insurance), not HDFC Bank",
    "HDFC ERGO": "majority-owned business in a different line of work (general insurance), not HDFC Bank",
    "Hdfc Securities": "majority-owned business in a different line of work (broking), not HDFC Bank",
    "Tata Motors Finance": "majority-owned business in a different line of work (vehicle finance), not Tata Motors",
    "Tata Technologies": "separately listed engineering-services company with its own brand",
    "Siemens Healthcare": "majority-owned business in a different line of work (Siemens Healthineers)",
    "Siemens Energy": "spun off from Siemens in 2020, a separate company",
    "Siemens Gamesa Renewable Energy": "part of Siemens Energy, not Siemens",
    "Bain Capital": "investment firm, separate from Bain & Company",
    "Micron Software": "unrelated Indian software firm",
    "Micron Technologies": "unrelated Coimbatore firm, not Micron Technology",
    "GE Appliances": "owned by Haier since 2016",
    "American Express Global Business Travel": "separately listed travel company",
    "Samsung Data Systems": "Samsung group affiliate (Samsung SDS), not Samsung Electronics",
    "Samsung Engineering India": "Samsung group affiliate, not Samsung Electronics",
    "Reliance Games": "Reliance Entertainment (ADA group), not Reliance Industries",
    "Reliance Broadcast Network": "ADA group, not Reliance Industries",
    "Reliance Elektrik Works": "unrelated company",
    "Canara HSBC OBC Life Insurance": "joint venture in which HSBC holds 26%",
    "Larsen & Toubro (L&T)": "LTIMindtree's parent, not LTIMindtree",
    "Deutsche Telekom Digital Labs": "unrelated to Deutsche Bank",
    "Johnson Controls": "unrelated to Johnson & Johnson",
    "Johnson Electric": "unrelated to Johnson & Johnson",
    "Johnson Matthey": "unrelated to Johnson & Johnson",
    "Tridhya Intuit": "unrelated to Intuit",
    "Intuitive Apps": "unrelated to Intuit",
    "Shell Infotech": "unrelated to Shell",
    "Citiustech": "unrelated to Citi",
}

# Words a link's slug uses for a city -> the name shown. Matched longest
# first, so "navi mumbai" is read before "mumbai". A city not listed here is
# left out rather than guessed; add it if the report shows one missing.
CITIES = {
    "bangalore": "Bengaluru", "bengaluru": "Bengaluru", "bangalore rural": "Bengaluru",
    "hyderabad": "Hyderabad", "secunderabad": "Hyderabad",
    "gurgaon": "Gurugram", "gurugram": "Gurugram",
    "mumbai": "Mumbai", "mumbai suburban": "Mumbai", "navi mumbai": "Navi Mumbai", "thane": "Thane",
    "delhi": "Delhi", "new delhi": "Delhi", "delhi ncr": "Delhi NCR",
    "noida": "Noida", "greater noida": "Noida", "ghaziabad": "Ghaziabad", "faridabad": "Faridabad",
    "pune": "Pune", "chennai": "Chennai", "kolkata": "Kolkata", "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur", "indore": "Indore", "bhopal": "Bhopal", "lucknow": "Lucknow",
    "nagpur": "Nagpur", "nashik": "Nashik", "nasik": "Nashik", "vadodara": "Vadodara", "surat": "Surat",
    "kochi": "Kochi", "cochin": "Kochi", "coimbatore": "Coimbatore", "mohali": "Mohali",
    "chandigarh": "Chandigarh", "bhubaneswar": "Bhubaneswar", "bhubaneshwar": "Bhubaneswar",
    "thiruvananthapuram": "Thiruvananthapuram", "trivandrum": "Thiruvananthapuram",
    "visakhapatnam": "Visakhapatnam", "vizag": "Visakhapatnam", "mysore": "Mysuru", "mysuru": "Mysuru",
    "mangalore": "Mangaluru", "mangaluru": "Mangaluru", "remote": "Remote",
}

# Legal names a link's slug uses that are neither the posted name nor the
# library name. A link is verified if its slug names the employer by any of
# these, so without this PwC's links ("pricewaterhouse-coopers-private-limited")
# would all fail.
LINK_NAMES = {"pwc": ("Pricewaterhouse Coopers",)}

# A Naukri link: https://www.naukri.com/job-listings-<slug>-<x>-to-<y>-years-<12-digit id>
LINK = re.compile(r"/job-listings-(.+)-\d+-to-\d+-years-(\d{12})")

# "Business analyst" is mostly a requirements role, so it is an exclude
# keyword. These excludes are lifted when the title also has an include
# keyword that names data work, e.g. "Business Analyst - Data Science" or
# "Senior Business Analyst - BI". The generic words below don't count: a
# plain business-analyst title already has them, or they don't name data
# work on their own ("Gap Analysis", "Life Science").
OVERRIDABLE_EXCLUDES = {"business analyst"}
GENERIC_INCLUDES = {"analyst", "analysts", "analysis", "analytical", "science"}

# Relative post times as Naukri shows them. "Starts in 1-3 months" and
# "Starts : 13th Nov' 23" are internship start dates, not post times.
POST_TIME = re.compile(r"(ago|just now|today)$", re.IGNORECASE)

INSERT_SQL = """
    INSERT INTO jobs (job_id, company_id, employer_name, title, city, posted_relative,
                      url, skills_raw, source, loaded_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'naukri', ?)
"""


class JobsError(ValueError):
    """The inputs failed a check; nothing was written."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def read_keywords(path: str | Path = KEYWORDS_CSV) -> tuple[list[str], list[str]]:
    """(include, exclude) keyword lists, each normalised like a title."""
    include, exclude = [], []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            keyword, kind = normalise(row["keyword"]), row["kind"].strip()
            if kind not in ("include", "exclude"):
                raise JobsError([f"{path}: kind must be include or exclude, not {kind!r} ({row['keyword']!r})"])
            (include if kind == "include" else exclude).append(keyword)
    return include, exclude


def has_phrase(text: str, phrase: str) -> bool:
    """Is phrase in text as whole words? Both are normalised, so words are space-separated."""
    return f" {phrase} " in f" {text} "


def is_data_role(title: str, include: list[str], exclude: list[str]) -> bool:
    """A title is a data role if it has an include keyword and no exclude keyword.

    The one exception: OVERRIDABLE_EXCLUDES are lifted by a data-specific
    include keyword (any but GENERIC_INCLUDES).
    """
    text = normalise(title)
    excluded_by = [phrase for phrase in exclude if has_phrase(text, phrase)]
    if excluded_by:
        if not all(phrase in OVERRIDABLE_EXCLUDES for phrase in excluded_by):
            return False
        return any(has_phrase(text, phrase) for phrase in include if phrase not in GENERIC_INCLUDES)
    return any(has_phrase(text, phrase) for phrase in include)


def words(text: str) -> list[str]:
    """Normalised words without "and": a slug drops the "&" that normalise() spells out."""
    return [w for w in normalise(text).split() if w != "and"]


def employer_words(name: str) -> list[str]:
    """A name as a slug would spell it, bracketed parts dropped.

    'Tata Consultancy Services (TCS)' -> ['tata', 'consultancy', 'services'].
    """
    return words(re.sub(r"\(.*?\)", " ", name))


def link_tail(url: str, title: str, employers: list[str]) -> list[str] | None:
    """Verify a link; return the slug words after the employer, or None.

    A Naukri slug reads <title>-<employer>-<cities>-<x>-to-<y>-years. The
    link belongs to this row only if the slug starts with the row's title
    (its first three words) and one of the employer's names comes after it.
    Checking the title alone isn't enough: "Data Analyst" starts thousands
    of slugs, most of them other employers' postings.
    """
    found = LINK.search(url or "")
    start = normalise(title).split()[:3]
    if not found or not start:
        return None
    slug = normalise(found.group(1)).split()
    if slug[:len(start)] != start:
        return None
    rest = [w for w in slug[len(start):] if w != "and"]
    for name in employers:
        name = employer_words(name)
        for i in range(len(rest) - len(name) + 1):
            if name and rest[i:i + len(name)] == name:
                return rest[i + len(name):]
    return None


def cities_from_slug(tail: list[str]) -> list[str]:
    """City names in the slug words after the employer, in order, without repeats."""
    cities: list[str] = []
    i = 0
    while i < len(tail):
        # Try the longest phrase first: three words, then two, then one.
        for size in (3, 2, 1):
            city = CITIES.get(" ".join(tail[i:i + size]))
            if city:
                if city not in cities:
                    cities.append(city)
                i += size
                break
        else:
            i += 1
    return cities


def posted_text(value: str) -> str | None:
    value = (value or "").strip()
    return value if POST_TIME.search(value) else None


def name_index(
    companies: list[sqlite3.Row],
    names_in_file: set[str],
    aliases: list[tuple[str, str]],
    rejected: dict[str, str],
) -> dict[str, str]:
    """normalised company_name -> company_id, for every name that may match.

    A company matches its own name and its naukri aliases. Raises JobsError
    for an alias that can't be right, before anything is written.
    """
    company_ids = {c["company_id"] for c in companies}
    rejected_keys = {normalise(name) for name in rejected}
    index: dict[str, str] = {}
    problems: list[str] = []

    for company in companies:
        key = normalise(company["name"])
        if key not in rejected_keys:
            index[key] = company["company_id"]
    for company_id, alias in aliases:
        key = normalise(alias)
        if company_id not in company_ids:
            problems.append(f"alias {alias!r} is for {company_id!r}, which is not in companies")
        elif key in rejected_keys:
            problems.append(f"alias {alias!r} for {company_id!r} is in REJECTED_NAMES")
        elif key not in names_in_file:
            problems.append(f"alias {alias!r} for {company_id!r} is not a company_name in the postings file")
        elif index.get(key, company_id) != company_id:
            problems.append(f"alias {alias!r} is claimed by both {index[key]!r} and {company_id!r}")
        else:
            index[key] = company_id
    if problems:
        raise JobsError(problems)
    return index


def listing_key(row: dict) -> tuple[str, str]:
    return normalise(row["employer"]), normalise(row["title"])


def dedupe(rows: list[dict]) -> list[dict]:
    """One row per listing, the lowest job_row_id of each kept.

    - A row with a verified link is a listing of its own Naukri job ID, so
      verified rows are deduplicated by that ID. Two verified rows with the
      same title but different IDs are two listings.
    - An unverified row has no trustworthy ID, so unverified rows are
      deduplicated by (employer as posted, title), and one is dropped when a
      verified row already has its employer and title.
    """
    verified: dict[str, dict] = {}
    unverified: dict[tuple[str, str], dict] = {}
    for row in sorted(rows, key=lambda r: r["row_id"]):
        if row["naukri_id"]:
            verified.setdefault(row["naukri_id"], row)
        else:
            unverified.setdefault(listing_key(row), row)
    verified_keys = {listing_key(row) for row in verified.values()}
    kept = [*verified.values(), *(row for key, row in unverified.items() if key not in verified_keys)]
    return sorted(kept, key=lambda r: r["row_id"])


def read_postings(path: str | Path) -> list[dict]:
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        missing = [c for c in SOURCE_COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            raise JobsError([f"{path}: missing columns {missing}"])
        return list(reader)


def load_jobs(
    conn: sqlite3.Connection,
    postings_path: str | Path = NAUKRI_CSV,
    aliases_path: str | Path = ALIASES_CSV,
    keywords_path: str | Path = KEYWORDS_CSV,
    rejected: dict[str, str] = REJECTED_NAMES,
) -> dict:
    """Replace jobs with the matched data-role postings; return the counts for the report."""
    companies = conn.execute("SELECT company_id, name FROM companies ORDER BY company_id").fetchall()
    if not companies:
        raise JobsError(["the companies table is empty; run python -m ingest.load_companies first"])

    postings = read_postings(postings_path)
    include, exclude = read_keywords(keywords_path)
    index = name_index(companies, {normalise(p["company_name"]) for p in postings},
                       read_aliases("naukri", aliases_path), rejected)
    loaded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    names = {c["company_id"]: c["name"] for c in companies}

    result = {
        "companies": names,
        "read": len(postings),
        "kept_titles": Counter(), "dropped_titles": Counter(),
        "unmatched": 0,
        "matched": Counter(),              # company_id -> matched data-role rows, before dedup
        "verified_rows": Counter(),        # company_id -> of those, rows with a verified link
        "names": defaultdict(Counter),     # company_id -> posted name -> listings after dedup
        "dropped_by_company": Counter(),   # company_id -> matched postings the title filter dropped
        "verified": Counter(),             # company_id -> listings with a verified link, after dedup
        "file_names": Counter(normalise(p["company_name"]) for p in postings),
        "rejected_seen": Counter(),        # rejected name -> postings
    }
    rejected_keys = {normalise(name): name for name in rejected}
    candidates = []
    for posting in postings:
        title, employer = posting["job_title"].strip(), posting["company_name"].strip()
        key = normalise(employer)
        company_id = index.get(key)
        if key in rejected_keys:
            result["rejected_seen"][rejected_keys[key]] += 1

        if not is_data_role(title, include, exclude):
            result["dropped_titles"][title] += 1
            if company_id:
                result["dropped_by_company"][company_id] += 1
            continue
        result["kept_titles"][title] += 1
        if company_id is None:
            result["unmatched"] += 1
            continue

        url = posting["post_url"].strip()
        tail = link_tail(url, title, [employer, names[company_id], *LINK_NAMES.get(company_id, ())])
        if tail is None:
            url = posted = city = naukri_id = None
        else:
            posted = posted_text(posting["post_time_relative"])
            city = ";".join(cities_from_slug(tail)) or None
            naukri_id = LINK.search(url).group(2)
            result["verified_rows"][company_id] += 1
        result["matched"][company_id] += 1
        candidates.append({"row_id": int(posting["job_row_id"]), "company_id": company_id,
                           "employer": employer, "title": title, "city": city, "posted": posted,
                           "url": url, "naukri_id": naukri_id})

    kept = dedupe(candidates)
    for row in kept:
        result["names"][row["company_id"]][row["employer"]] += 1
        if row["naukri_id"]:
            result["verified"][row["company_id"]] += 1
    rows = [(f"nk-{r['row_id']}", r["company_id"], r["employer"], r["title"], r["city"], r["posted"],
             r["url"], loaded_at) for r in kept]

    # One transaction: a failure leaves the previous load in place.
    with conn:
        conn.execute("DELETE FROM job_skills")
        conn.execute("DELETE FROM jobs")
        conn.executemany(INSERT_SQL, rows)
    result["loaded"] = len(rows)
    return result


def build_report(result: dict, rejected: dict[str, str] = REJECTED_NAMES) -> str:
    lines: list[str] = []
    add = lines.append
    kept, dropped = sum(result["kept_titles"].values()), sum(result["dropped_titles"].values())
    matched_rows = sum(result["matched"].values())
    verified = sum(result["verified"].values())
    matched = [c for c in result["companies"] if result["names"].get(c)]

    add(f"Postings in file:                 {result['read']:>7,}")
    add(f"  not a data role (title filter): {dropped:>7,}")
    add(f"  data-role postings:             {kept:>7,}")
    add(f"  matched to a library company:   {matched_rows:>7,}  ({len(matched)} companies)")
    add(f"  unmatched:                      {result['unmatched']:>7,}")
    add(f"  matched with a verified link:   {sum(result['verified_rows'].values()):>7,}")
    add("")
    add(f"Distinct listings loaded:         {result['loaded']:>7,}  ({matched_rows - result['loaded']:,} duplicates removed)")
    add(f"  verified, one per job ID:       {verified:>7,}")
    add(f"  unverified, one per employer and title: {result['loaded'] - verified:,}")
    add("")

    add("Matched companies: rows before -> listings after dedup, verified links after dedup,")
    add("and each name as posted (listings)")
    for company_id in matched:
        names = ", ".join(f"{name} ({n:,})" for name, n in result["names"][company_id].most_common())
        add(f"  {company_id:28} {result['matched'][company_id]:>5,} -> {sum(result['names'][company_id].values()):>4,}"
            f"  links {result['verified'][company_id]:>4,}  {names}")
    add(f"  {'TOTAL':28} {matched_rows:>5,} -> {result['loaded']:>4,}  links {verified:>4,}")
    add("")

    add(f"Rejected names found in the file ({len(result['rejected_seen'])})")
    for name, n in result["rejected_seen"].most_common():
        add(f"  {name} ({n:,}): {rejected[name]}")
    add("")

    missing = [c for c in result["companies"] if c not in matched]
    add(f"Not available: no data-role postings ({len(missing)})")
    file_names = list(result["file_names"])
    for company_id in missing:
        note = ""
        if result["dropped_by_company"][company_id]:
            note = f"  [{result['dropped_by_company'][company_id]} matched, all dropped by the title filter]"
        suggestions = difflib.get_close_matches(normalise(result["companies"][company_id]), file_names,
                                                n=3, cutoff=0.6)
        hint = "; ".join(f"{s} ({result['file_names'][s]})" for s in suggestions) or "none"
        add(f"  {company_id:28} suggestions, not accepted: {hint}{note}")
    add("")

    for heading, counter in (("kept", result["kept_titles"]), ("dropped", result["dropped_titles"])):
        add(f"30 most common titles {heading} by the title filter")
        for title, n in counter.most_common(30):
            add(f"  {n:>5,}  {title}")
        add("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest.load_jobs")
    parser.add_argument("--csv", type=Path, default=NAUKRI_CSV, help="postings CSV to load")
    args = parser.parse_args(argv)

    conn = get_conn()
    try:
        apply_schema(conn)
        try:
            result = load_jobs(conn, args.csv)
        except JobsError as error:
            print(f"{args.csv}: not loaded, nothing written", file=sys.stderr)
            for problem in error.problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
    finally:
        conn.close()

    report = build_report(result)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nReport written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
