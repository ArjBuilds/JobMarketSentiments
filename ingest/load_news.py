"""Fetch news about working at each company from GNews into articles (F6).

GNews is the only API in the project. Run with:  python -m ingest.load_news

Run ingest.load_companies first. One request per company, using its query
in data/news_queries.csv. Then, for each company:

    1. parse       title, outlet, published_at, url and GNews's short
                   description; the article content is never stored;
    2. relevance   keep an article only if its title or description names
                   the company: its library name or a gnews alias in
                   company_aliases.csv, as a whole word with matching case,
                   so "Target" counts and "target audience" doesn't;
    3. dedupe      by URL, then by near-identical titles (one story
                   syndicated by several outlets), keeping the earliest copy;
    4. cap         the 10 newest;
    5. sentiment   VADER on title + description, labelled by jmsa.sentiment.

Each company is saved in its own transaction: its old articles are replaced
and its news_fetches row records the fetch and caches the response. So a
run that stops part way keeps what it saved, and rerunning resumes: a
company fetched in the last 24 hours is skipped unless --refresh is given.

The free tier allows 100 requests a day, 1 a second and 10 articles a
request, and searches only the last 30 days. A 403 means the day's quota is
used up; the run stops there.

The API key travels only in the request's parameters. requests puts it in
the URL, and so in its error messages, so no exception text is ever printed
or stored, and every message that is goes through redact() first.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import json
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

from jmsa.aliases import ALIASES_CSV, read_aliases
from jmsa.config import DATA_DIR, GNEWS_API_KEY, RAW_DIR
from jmsa.db import apply_schema, get_conn
from jmsa.sentiment import label

QUERIES_CSV = DATA_DIR / "news_queries.csv"
REPORT_PATH = RAW_DIR / "news_fetch_report.txt"
GNEWS_URL = "https://gnews.io/api/v4/search"

MAX_QUERY_LENGTH = 200     # GNews rejects longer queries
MAX_ARTICLES = 10          # per request on the free tier, and per company on the page
WINDOW_DAYS = 30           # the free tier's archive
SKIP_HOURS = 24            # news runs at most once a day
PAUSE_SECONDS = 1.5        # between requests; the free tier allows 1 a second
RETRY_WAITS = (2, 4, 8)    # seconds before each retry of a transient failure
RETRY_STATUSES = {429, 500, 503}
TIMEOUT_SECONDS = 20
SAME_TITLE = 0.9           # difflib ratio at which two titles are one story

# Exit codes
QUOTA_STOP = 3


class NewsError(Exception):
    """data/news_queries.csv can't be used; nothing was fetched."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


class StopRun(Exception):
    """GNews refused every further request (quota used up or key rejected)."""


class FetchFailed(Exception):
    """This company's request failed; the run moves on to the next one."""


def redact(text: str, key: str | None) -> str:
    """text with the API key replaced by ***, so a message can't leak it."""
    return text.replace(key, "***") if key else text


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(moment: datetime) -> str:
    """2026-10-21T09:30:00Z"""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_queries(path: Path, company_ids: set[str]) -> dict[str, str]:
    """company_id -> query, after checking every library company has a usable one."""
    with Path(path).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    problems, queries = [], {}
    for number, row in enumerate(rows, start=2):
        company_id, query = (row.get("company_id") or "").strip(), (row.get("query") or "").strip()
        if company_id not in company_ids:
            problems.append(f"line {number}: unknown company_id {company_id!r}")
        elif company_id in queries:
            problems.append(f"line {number}: second query for {company_id}")
        elif not query:
            problems.append(f"line {number}: empty query for {company_id}")
        elif len(query) > MAX_QUERY_LENGTH:
            problems.append(f"line {number}: {company_id} query is {len(query)} characters; "
                            f"GNews allows {MAX_QUERY_LENGTH}")
        else:
            queries[company_id] = query
    for company_id in sorted(company_ids - set(queries) - {(r.get("company_id") or "").strip() for r in rows}):
        problems.append(f"no query for {company_id}")
    if problems:
        raise NewsError(problems)
    return queries


def company_patterns(conn: sqlite3.Connection, aliases_path: Path = ALIASES_CSV) -> dict[str, re.Pattern]:
    """company_id -> a pattern matching its library name or any gnews alias.

    Whole words only, and case-sensitive: case is what tells Target the
    company from "target", and Meta from "metadata" (which whole words
    already rule out) or "meta" in a headline about something else.
    """
    names = {row["company_id"]: [row["name"]] for row in conn.execute("SELECT company_id, name FROM companies")}
    for company_id, alias in read_aliases("gnews", aliases_path):
        if company_id in names:
            names[company_id].append(alias)
    return {
        company_id: re.compile(
            r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
            + r")(?![A-Za-z0-9])"
        )
        for company_id, terms in names.items()
    }


def error_text(response) -> str:
    """GNews's own error message, e.g. {"errors": ["..."]}, or just the status."""
    try:
        errors = response.json().get("errors")
    except ValueError:
        errors = None
    if isinstance(errors, dict):
        errors = list(errors.values())
    if isinstance(errors, list) and errors:
        return f"HTTP {response.status_code}: " + "; ".join(str(e) for e in errors)
    return f"HTTP {response.status_code}"


def request_news(session, query: str, key: str, window_from: datetime, sleep=time.sleep) -> dict:
    """One GNews search, retried on transient failures. Returns the JSON body.

    Raises StopRun on 401 or 403, which no retry can fix, and FetchFailed
    when this one request can't succeed. Messages never carry the key.
    """
    params = {"q": query, "lang": "en", "max": MAX_ARTICLES, "sortby": "publishedAt",
              "from": iso(window_from), "apikey": key}
    problem = ""
    for attempt in range(len(RETRY_WAITS) + 1):
        if attempt:
            sleep(RETRY_WAITS[attempt - 1])
        try:
            response = session.get(GNEWS_URL, params=params, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as error:
            # Only the exception's type: its message holds the URL, key included.
            problem = f"network error ({type(error).__name__})"
            continue
        status = response.status_code
        if status == 200:
            try:
                return response.json()
            except ValueError:
                raise FetchFailed("HTTP 200 but the body isn't JSON") from None
        if status == 403:
            raise StopRun(redact(
                f"GNews daily quota reached or subscription expired ({error_text(response)}). "
                "The quota resets at 00:00 UTC (05:30 IST); rerun after that to resume.", key))
        if status == 401:
            raise StopRun(redact(f"GNews rejected the API key ({error_text(response)}). "
                                 "Check GNEWS_API_KEY in .env.", key))
        problem = redact(error_text(response), key)
        if status not in RETRY_STATUSES:
            break
    raise FetchFailed(f"{problem}, after {attempt + 1} attempt(s)")


def without_content(body: dict) -> dict:
    """The response with each article's content removed, as it is cached.

    The free tier's content is a truncated excerpt of the article itself,
    which the project doesn't store anywhere.
    """
    body = dict(body)
    body["articles"] = [{k: v for k, v in a.items() if k != "content"} for a in body.get("articles") or []]
    return body


def published_iso(value: str | None) -> str | None:
    """GNews's publishedAt ('2026-10-19T08:15:00Z') normalised to the same form."""
    if not value:
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return iso(moment)


def parse_articles(body: dict) -> list[dict]:
    """The fields kept from each article in a response; never its content."""
    articles = []
    for item in body.get("articles") or []:
        url = (item.get("url") or "").strip()
        title = (item.get("title") or "").strip()
        if not url or not title:
            continue
        articles.append({
            "title": title,
            "outlet": ((item.get("source") or {}).get("name") or "").strip() or None,
            "published_at": published_iso(item.get("publishedAt")),
            "url": url,
            "summary": (item.get("description") or "").strip() or None,
        })
    return articles


def url_key(url: str) -> str:
    """A URL without query string, fragment or trailing slash: utm tags don't make a new article."""
    parts = urlsplit(url.strip())
    return f"{parts.netloc.lower()}{parts.path.rstrip('/')}"


def title_key(title: str) -> str:
    """A title without its ' - Outlet' or ' | Outlet' tail, lowercased, punctuation removed."""
    text = re.sub(r"\s+[-|–—]\s+[^-|–—]+$", "", title)
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def dedupe(articles: list[dict]) -> list[dict]:
    """One article per story: same URL, or titles at least SAME_TITLE alike.

    Read oldest first, so the earliest copy, usually the original, is kept.
    """
    kept, urls, titles = [], set(), []
    for article in sorted(articles, key=lambda a: a["published_at"] or ""):
        key, title = url_key(article["url"]), title_key(article["title"])
        if key in urls:
            continue
        if any(difflib.SequenceMatcher(None, title, other).ratio() >= SAME_TITLE for other in titles):
            continue
        urls.add(key)
        titles.append(title)
        kept.append(article)
    return kept


def select_articles(body: dict, pattern: re.Pattern, analyzer) -> tuple[list[dict], dict]:
    """The articles to store from one response, and how many each step dropped."""
    parsed = parse_articles(body)
    relevant = [a for a in parsed if pattern.search(a["title"]) or pattern.search(a["summary"] or "")]
    distinct = dedupe(relevant)
    newest = sorted(distinct, key=lambda a: a["published_at"] or "", reverse=True)[:MAX_ARTICLES]
    for article in newest:
        text = article["title"] + (f". {article['summary']}" if article["summary"] else "")
        article["sentiment_compound"] = analyzer.polarity_scores(text)["compound"]
        article["sentiment_label"] = label(article["sentiment_compound"])
    counts = {
        "returned": len(body.get("articles") or []),
        "dropped_irrelevant": len(parsed) - len(relevant),
        "dropped_duplicate": len(relevant) - len(distinct),
        "kept": len(newest),
    }
    dropped = [a["title"] for a in parsed if a not in relevant]
    return newest, counts | {"dropped_titles": dropped}


def save_company(conn: sqlite3.Connection, company_id: str, fetch: dict, body: dict,
                 articles: list[dict], counts: dict) -> None:
    """Replace a company's articles and record its fetch, in one transaction."""
    with conn:
        conn.execute("DELETE FROM articles WHERE company_id = ?", (company_id,))
        conn.executemany(
            "INSERT INTO articles (article_id, company_id, title, outlet, published_at, url, summary,"
            " sentiment_compound, sentiment_label) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(f"{company_id}:{hashlib.sha1(url_key(a['url']).encode()).hexdigest()[:12]}", company_id,
              a["title"], a["outlet"], a["published_at"], a["url"], a["summary"],
              a["sentiment_compound"], a["sentiment_label"]) for a in articles],
        )
        conn.execute(
            "INSERT OR REPLACE INTO news_fetches (company_id, fetched_at, query, window_from, returned,"
            " dropped_irrelevant, dropped_duplicate, kept, response_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (company_id, fetch["fetched_at"], fetch["query"], fetch["window_from"], counts["returned"],
             counts["dropped_irrelevant"], counts["dropped_duplicate"], counts["kept"],
             json.dumps(without_content(body), ensure_ascii=False)),
        )


def last_fetched(conn: sqlite3.Connection) -> dict[str, datetime]:
    return {
        row["company_id"]: datetime.fromisoformat(row["fetched_at"].replace("Z", "+00:00"))
        for row in conn.execute("SELECT company_id, fetched_at FROM news_fetches")
    }


def run(conn: sqlite3.Connection, *, key: str | None, queries: dict[str, str],
        patterns: dict[str, re.Pattern], session, companies: list[str] | None = None,
        limit: int | None = None, refresh: bool = False, now=now_utc, sleep=time.sleep,
        say=print) -> dict:
    """Fetch, select and save news for the companies that are due.

    companies narrows the run to those ids (in the order given); limit takes
    the first N due. A company fetched in the last SKIP_HOURS is skipped
    unless refresh is set. say prints progress; it never receives the key.
    """
    if not key:
        raise NewsError(["GNEWS_API_KEY is not set in .env"])
    wanted = companies if companies else sorted(queries)
    unknown = [c for c in wanted if c not in queries]
    if unknown:
        raise NewsError([f"no query for {c}" for c in unknown])

    started, fetched = now(), last_fetched(conn)
    due, skipped = [], []
    for company_id in wanted:
        age = started - fetched[company_id] if company_id in fetched else None
        if age is not None and age < timedelta(hours=SKIP_HOURS) and not refresh:
            skipped.append((company_id, age))
        else:
            due.append(company_id)
    if limit is not None:
        due = due[:limit]

    result = {"companies": {}, "skipped": skipped, "failed": {}, "stopped": None, "requests": 0}
    for company_id, age in skipped:
        say(f"  {company_id:28} fetched {age.total_seconds() / 3600:.1f} h ago, skipped")
    analyzer = SentimentIntensityAnalyzer()
    for position, company_id in enumerate(due):
        if position:
            sleep(PAUSE_SECONDS)
        moment = now()
        window_from = moment - timedelta(days=WINDOW_DAYS)
        result["requests"] += 1
        try:
            body = request_news(session, queries[company_id], key, window_from, sleep)
        except StopRun as stop:
            result["stopped"] = redact(str(stop), key)
            say(f"  {company_id:28} STOPPED: {result['stopped']}")
            break
        except FetchFailed as failure:
            result["failed"][company_id] = redact(str(failure), key)
            say(f"  {company_id:28} failed: {result['failed'][company_id]}; previous news kept")
            continue
        fetch = {"fetched_at": iso(moment), "query": queries[company_id], "window_from": iso(window_from)}
        articles, counts = select_articles(body, patterns[company_id], analyzer)
        save_company(conn, company_id, fetch, body, articles, counts)
        result["companies"][company_id] = counts
        say(f"  {company_id:28} {line(counts)}")
    return result


def reselect_from_cache(conn: sqlite3.Connection, patterns: dict[str, re.Pattern],
                        companies: list[str] | None = None, say=print) -> dict:
    """Redo selection from the cached responses, after editing aliases. No requests."""
    result = {"companies": {}, "skipped": [], "failed": {}, "stopped": None, "requests": 0}
    analyzer = SentimentIntensityAnalyzer()
    rows = conn.execute("SELECT company_id, fetched_at, query, window_from, response_json"
                        " FROM news_fetches ORDER BY company_id").fetchall()
    for row in rows:
        if companies and row["company_id"] not in companies:
            continue
        body = json.loads(row["response_json"])
        articles, counts = select_articles(body, patterns[row["company_id"]], analyzer)
        save_company(conn, row["company_id"], dict(row), body, articles, counts)
        result["companies"][row["company_id"]] = counts
        say(f"  {row['company_id']:28} {line(counts)}")
    return result


def line(counts: dict) -> str:
    return (f"returned {counts['returned']:>2} · irrelevant {counts['dropped_irrelevant']:>2} · "
            f"duplicate {counts['dropped_duplicate']:>2} · kept {counts['kept']:>2} · ok")


def build_report(result: dict) -> str:
    lines = []
    add = lines.append
    done = result["companies"]
    returned = sum(c["returned"] for c in done.values())
    irrelevant = sum(c["dropped_irrelevant"] for c in done.values())
    add(f"Requests sent:            {result['requests']:>4}")
    add(f"Companies saved:          {len(done):>4}")
    add(f"Companies skipped:        {len(result['skipped']):>4}  (fetched in the last {SKIP_HOURS} h)")
    add(f"Companies failed:         {len(result['failed']):>4}  (previous news kept)")
    add(f"Articles returned:        {returned:>4}")
    add(f"Dropped by the relevance check: {irrelevant} of {returned}")
    add(f"Dropped as duplicates:    {sum(c['dropped_duplicate'] for c in done.values()):>4}")
    add(f"Articles kept:            {sum(c['kept'] for c in done.values()):>4}")
    if result["stopped"]:
        add("")
        add(f"STOPPED: {result['stopped']}")
    add("")
    add("Per company")
    for company_id, counts in done.items():
        add(f"  {company_id:28} {line(counts)}")
    for company_id, problem in result["failed"].items():
        add(f"  {company_id:28} failed: {problem}")
    add("")
    add("Titles dropped by the relevance check (check these against the queries and gnews aliases)")
    for company_id, counts in done.items():
        for title in counts["dropped_titles"]:
            add(f"  {company_id:28} {title}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m ingest.load_news")
    parser.add_argument("--company", action="append", metavar="ID", help="fetch only this company (repeatable)")
    parser.add_argument("--limit", type=int, metavar="N", help="fetch at most N companies")
    parser.add_argument("--refresh", action="store_true",
                        help=f"fetch even companies fetched in the last {SKIP_HOURS} hours")
    parser.add_argument("--from-cache", action="store_true",
                        help="re-select articles from cached responses; sends no requests")
    args = parser.parse_args(argv)

    conn = get_conn()
    try:
        apply_schema(conn)
        company_ids = {row["company_id"] for row in conn.execute("SELECT company_id FROM companies")}
        if not company_ids:
            print("The companies table is empty. Run python -m ingest.load_companies first.", file=sys.stderr)
            return 1
        patterns = company_patterns(conn)
        try:
            if args.from_cache:
                result = reselect_from_cache(conn, patterns, args.company)
            else:
                queries = read_queries(QUERIES_CSV, company_ids)
                with requests.Session() as session:
                    result = run(conn, key=GNEWS_API_KEY, queries=queries, patterns=patterns,
                                 session=session, companies=args.company, limit=args.limit,
                                 refresh=args.refresh)
        except NewsError as error:
            print("Not fetched, nothing written:", file=sys.stderr)
            for problem in error.problems:
                print(f"  {problem}", file=sys.stderr)
            return 1
    finally:
        conn.close()

    report = redact(build_report(result), GNEWS_API_KEY)
    REPORT_PATH.write_text(report + "\n", encoding="utf-8")
    print()
    print(report)
    print(f"\nReport written to {REPORT_PATH}")
    return QUOTA_STOP if result["stopped"] else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
