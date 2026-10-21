"""Compute the review-based turnover proxy (F5) into turnover.

Run with:  python -m process.turnover_proxy [--company ID] [--check N]

Run ingest.load_reviews first. For each company, over the reviews dated in
the window (jmsa.turnover.WINDOW_START to WINDOW_END):

    proxy   the share of reviews whose headline or cons mention a keyword
            in data/turnover_keywords.csv, overall and for each kind
            (leaving, which includes attrition, and layoffs).

Pros are not searched: there "leave" means time off ("good leave policy")
and "no layoffs" is praise. Keywords match whole words, any case, and a
space also matches a hyphen or slash ("lay-off"), as in themes.csv.

Every run replaces the proxy rows (is_proxy = 1) in one transaction and
never touches published figures. A company with no reviews in the window
gets no row, so it shows "not available"; under 20 reviews its row is kept
and hidden when shown, with the count.

--check N writes a hand-check sample to data/raw/turnover_proxy_check.txt
instead: N matched, N unmatched and N/2 near-miss reviews, plus N/2 for
each keyword with many hits, so each keyword's precision can be judged.
The turnover table is not touched.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

from jmsa.config import DATA_DIR, RAW_DIR
from jmsa.db import apply_schema, get_conn
from jmsa.display import plural
from jmsa.sentiment import is_shown
from jmsa.turnover import (
    KINDS,
    PROXY_DEFINITION,
    PROXY_SOURCE_URL,
    WINDOW_END,
    WINDOW_PERIOD,
    WINDOW_START,
    WINDOW_TITLE,
    per_100,
)
from process.review_sentiment import keyword_pattern

KEYWORDS_CSV = DATA_DIR / "turnover_keywords.csv"
REPORT_PATH = RAW_DIR / "turnover_proxy_report.txt"
CHECK_PATH = RAW_DIR / "turnover_proxy_check.txt"

FIELDS = ("headline", "cons")

# Words deliberately not keywords, because their usual sense in reviews isn't
# leaving. The check sample draws "near misses" from unmatched reviews whose
# cons use them, to see what leaving talk the keywords miss.
NEAR_MISS = re.compile(r"\b(?:leaves?|left|switch(?:ing)?|job security|notice period|exit)\b", re.IGNORECASE)

# Keywords sampled on their own in --check: these, plus any with this many hits.
ALWAYS_CHECK = ("turnover", "restructuring", "retention", "fired", "layoffs")
CHECK_MIN_HITS = 500
SEED = 8

METHOD_NOTE = (
    f"Reviews dated {WINDOW_START} to {WINDOW_END} (the last 24 months with full coverage in the "
    "review dataset). A review counts if its headline or cons match a keyword in "
    "data/turnover_keywords.csv as a whole word, any case; pros are not searched. "
    "Hidden below 20 reviews in the window."
)


class KeywordsError(ValueError):
    """turnover_keywords.csv failed a check; nothing was computed."""

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("\n".join(problems))


def read_keywords(path: str | Path = KEYWORDS_CSV) -> dict[str, list[str]]:
    """kind -> its keywords, in file order."""
    keywords: dict[str, list[str]] = {kind: [] for kind in KINDS}
    problems: list[str] = []
    seen: set[str] = set()
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["kind", "keyword"]:
            raise KeywordsError([f"{path}: header is {reader.fieldnames}, expected ['kind', 'keyword']"])
        for row in reader:
            kind, keyword = (row["kind"] or "").strip(), (row["keyword"] or "").strip().lower()
            if kind not in keywords:
                problems.append(f"line {reader.line_num}: kind {kind!r} is not one of {list(KINDS)}")
            elif not keyword:
                problems.append(f"line {reader.line_num}: empty keyword")
            elif keyword in seen:
                problems.append(f"line {reader.line_num}: {keyword!r} is listed twice")
            else:
                seen.add(keyword)
                keywords[kind].append(keyword)
    problems += [f"kind {kind!r} has no keywords" for kind, words in keywords.items() if not words]
    if problems:
        raise KeywordsError(problems)
    return keywords


def compile_keywords(keywords: dict[str, list[str]]) -> tuple[dict[str, re.Pattern], dict[str, re.Pattern]]:
    """(kind -> one pattern for all its keywords, keyword -> its own pattern).

    The kind patterns decide what counts; the per-keyword ones only feed the
    report and the check sample, and run only on reviews that already matched.
    """
    def pattern(words):
        return re.compile(r"\b(?:" + "|".join(keyword_pattern(w) for w in words) + r")\b", re.IGNORECASE)
    by_kind = {kind: pattern(words) for kind, words in keywords.items()}
    by_keyword = {word: pattern([word]) for words in keywords.values() for word in words}
    return by_kind, by_keyword


def kinds_mentioned(texts: dict[str, str | None], by_kind: dict[str, re.Pattern]) -> set[str]:
    """The kinds whose keywords appear in any searched field."""
    return {kind for kind, rx in by_kind.items() if any(rx.search(texts[f] or "") for f in FIELDS)}


def keyword_hits(texts: dict[str, str | None], by_keyword: dict[str, re.Pattern]) -> list[tuple[str, str]]:
    """(keyword, field) for every keyword found, e.g. [('attrition', 'cons')]."""
    return [(word, f) for word, rx in by_keyword.items() for f in FIELDS if rx.search(texts[f] or "")]


def window_reviews(conn: sqlite3.Connection, companies: list[str] | None = None):
    """The reviews dated in the window. An undated review is never in it."""
    query = ("SELECT review_id, company_id, headline, pros, cons FROM reviews"
             " WHERE review_date BETWEEN ? AND ?")
    params: list = [WINDOW_START, WINDOW_END]
    if companies:
        query += f" AND company_id IN ({', '.join('?' * len(companies))})"
        params += companies
    return conn.execute(query, params)


def compute(conn: sqlite3.Connection, by_kind, by_keyword, companies=None, sampler=None) -> dict:
    """Per-company counts, plus per-keyword hits for the report.

    sampler, if given, is called with every review and what it matched; the
    check sample uses it.
    """
    counts: dict[str, Counter] = defaultdict(Counter)
    hits: Counter = Counter()          # (keyword, field) -> reviews
    for row in window_reviews(conn, companies):
        texts = {"headline": row["headline"], "cons": row["cons"]}
        kinds = kinds_mentioned(texts, by_kind)
        company = counts[row["company_id"]]
        company["n"] += 1
        found = []
        if kinds:
            company["matched"] += 1
            for kind in kinds:
                company[kind] += 1
            found = keyword_hits(texts, by_keyword)
            hits.update(found)
        if sampler is not None:
            sampler(row, kinds, found)
    return {"companies": counts, "hits": hits}


def proxy_rows(conn: sqlite3.Connection, counts: dict[str, Counter]) -> list[tuple]:
    names = dict(conn.execute("SELECT company_id, name FROM companies"))
    pre_merger = dict(conn.execute(
        "SELECT company_id, count(*) FROM reviews WHERE is_pre_merger = 1"
        " AND review_date BETWEEN ? AND ? GROUP BY company_id", (WINDOW_START, WINDOW_END)))
    rows = []
    for company_id, c in sorted(counts.items()):
        if pre_merger.get(company_id) == c["n"]:
            entity = "Glassdoor reviews of Mindtree (pre-merger)"
        else:
            entity = f"Glassdoor reviews of {names[company_id]}"
        rows.append((company_id, 1, WINDOW_PERIOD, WINDOW_START, WINDOW_END, c["matched"] / c["n"], c["n"],
                     c["matched"], c["leaving"], c["layoffs"], PROXY_DEFINITION, entity, PROXY_SOURCE_URL,
                     METHOD_NOTE))
    return rows


def save(conn: sqlite3.Connection, rows: list[tuple], companies: list[str] | None = None) -> None:
    """Replace the proxy rows (all of them, or only the companies given). Published rows stay."""
    with conn:
        if companies:
            conn.execute(f"DELETE FROM turnover WHERE is_proxy = 1 AND company_id IN"
                         f" ({', '.join('?' * len(companies))})", companies)
        else:
            conn.execute("DELETE FROM turnover WHERE is_proxy = 1")
        conn.executemany(
            "INSERT INTO turnover (company_id, is_proxy, period, period_start, period_end, proxy_share,"
            " reviews_in_window, reviews_matched, reviews_leaving, reviews_layoffs, definition, entity,"
            " source_url, method_note) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )


def build_report(result: dict, keywords: dict[str, list[str]]) -> str:
    lines = []
    add = lines.append
    counts = result["companies"]
    total = sum(c["n"] for c in counts.values())
    matched = sum(c["matched"] for c in counts.values())
    add(f"Window: {WINDOW_TITLE}; fields searched: {', '.join(FIELDS)}")
    add(f"Reviews in window: {total:,}; matched: {matched:,}"
        + (f" ({per_100(matched, total)} per 100)" if total else ""))
    add(f"Companies with reviews in window: {len(counts)}; hidden (under 20): "
        f"{sum(1 for c in counts.values() if not is_shown(c['n']))}")
    add("")
    add(f"  {'company':28} {'reviews':>8} {'matched':>8} {'per 100':>8} {'leaving':>8} {'layoffs':>8}")
    for company_id, c in sorted(counts.items(), key=lambda item: -item[1]["matched"] / item[1]["n"]):
        add(f"  {company_id:28} {c['n']:>8,} {c['matched']:>8,} {per_100(c['matched'], c['n']):>8}"
            f" {per_100(c['leaving'], c['n']):>8} {per_100(c['layoffs'], c['n']):>8}")
    add("")
    add("Reviews per keyword (a review can match several), by field")
    add(f"  {'kind':8} {'keyword':22} {'headline':>9} {'cons':>9}")
    for kind, words in keywords.items():
        for word in words:
            add(f"  {kind:8} {word:22} {result['hits'][(word, 'headline')]:>9,} {result['hits'][(word, 'cons')]:>9,}")
    return "\n".join(lines)


class Sampler:
    """Reservoir samples for the hand-check, seeded so a rerun gives the same reviews."""

    def __init__(self, size: int, seed: int = SEED):
        self.size = size
        self.rng = random.Random(seed)
        self.pools = {"matched": [], "unmatched": [], "near_miss": []}
        self.seen = Counter()

    def offer(self, pool: str, item, size: int) -> None:
        """Reservoir sampling: every item seen has the same chance of being kept."""
        self.seen[pool] += 1
        sample = self.pools.setdefault(pool, [])
        if len(sample) < size:
            sample.append(item)
        else:
            slot = self.rng.randrange(self.seen[pool])
            if slot < size:
                sample[slot] = item

    def __call__(self, row, kinds, found) -> None:
        item = (row["review_id"], row["company_id"], row["headline"], row["cons"], sorted(kinds), found)
        if kinds:
            self.offer("matched", item, self.size)
            for word in {word for word, _ in found}:
                self.offer(f"keyword:{word}", item, self.size // 2)
        else:
            self.offer("unmatched", item, self.size)
            if NEAR_MISS.search(row["cons"] or ""):
                self.offer("near_miss", item, self.size // 2)


def snippet(text: str | None, rx: re.Pattern | None, width: int = 160) -> str:
    """The text around the first match, with the match in [[ ]], or the start of it."""
    text = " ".join((text or "").split())
    match = rx.search(text) if rx else None
    if not match:
        return text[: 2 * width] + ("…" if len(text) > 2 * width else "")
    start, end = max(0, match.start() - width), min(len(text), match.end() + width)
    return (("…" if start else "") + text[start:match.start()] + "[[" + match.group(0) + "]]"
            + text[match.end():end] + ("…" if end < len(text) else ""))


def keywords_to_check(sampler: Sampler, keywords: dict[str, list[str]]) -> list[str]:
    """The keywords sampled on their own: ALWAYS_CHECK plus any with many hits."""
    return [word for words in keywords.values() for word in words
            if word in ALWAYS_CHECK or sampler.seen[f"keyword:{word}"] >= CHECK_MIN_HITS]


def build_check(sampler: Sampler, by_kind, by_keyword, to_check: list[str]) -> str:
    lines = []
    add = lines.append
    every = re.compile("|".join(rx.pattern for rx in by_kind.values()), re.IGNORECASE)
    titles = {"matched": "Matched (random)", "unmatched": "Unmatched (random)",
              "near_miss": "Near misses: unmatched, cons use leave/left/switch/job security/notice period/exit"}
    pools = ["matched", "unmatched", "near_miss"] + [f"keyword:{word}" for word in to_check]
    for pool in pools:
        sample = sampler.pools.get(pool, [])
        if pool.startswith("keyword:"):
            word = pool.split(":", 1)[1]
            title, rx = f"Keyword '{word}' ({sampler.seen[pool]:,} reviews)", by_keyword[word]
        else:
            title = f"{titles[pool]} ({sampler.seen[pool]:,} reviews)"
            rx = NEAR_MISS if pool == "near_miss" else every
        add(f"=== {title}: {len(sample)} sampled ===")
        for number, (review_id, company_id, headline, cons, kinds, found) in enumerate(sample, start=1):
            hits = ", ".join(f"{w}/{f}" for w, f in found) or "none"
            add(f"[{number}] {review_id} {company_id}  kinds: {', '.join(kinds) or '-'}  hits: {hits}")
            add(f"    headline: {snippet(headline, rx, 100)}")
            add(f"    cons:     {snippet(cons, rx)}")
        add("")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m process.turnover_proxy")
    parser.add_argument("--company", action="append", metavar="ID", help="only this company (repeatable)")
    parser.add_argument("--check", type=int, metavar="N",
                        help="write a hand-check sample of N matched and N unmatched reviews; no table change")
    args = parser.parse_args(argv)

    try:
        keywords = read_keywords()
    except KeywordsError as error:
        print(f"{KEYWORDS_CSV}: not used, nothing computed", file=sys.stderr)
        for problem in error.problems:
            print(f"  {problem}", file=sys.stderr)
        return 1
    by_kind, by_keyword = compile_keywords(keywords)

    conn = get_conn()
    try:
        apply_schema(conn)
        if args.check:
            sampler = Sampler(args.check)
            compute(conn, by_kind, by_keyword, args.company, sampler)
            to_check = keywords_to_check(sampler, keywords)
            CHECK_PATH.write_text(build_check(sampler, by_kind, by_keyword, to_check) + "\n",
                                  encoding="utf-8")
            print(f"Check sample written to {CHECK_PATH}; turnover not changed")
            return 0
        result = compute(conn, by_kind, by_keyword, args.company)
        rows = proxy_rows(conn, result["companies"])
        save(conn, rows, args.company)
    finally:
        conn.close()

    report = build_report(result, keywords)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\n{plural(len(rows), 'proxy row')} written. Report written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
