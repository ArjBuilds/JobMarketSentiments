import csv
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
import requests

from ingest.load_news import (
    MAX_ARTICLES,
    NewsError,
    QUOTA_STOP,
    build_report,
    company_patterns,
    dedupe,
    main,
    parse_articles,
    read_queries,
    redact,
    reselect_from_cache,
    run,
    select_articles,
    without_content,
)
from jmsa.sentiment import label

# The library fixture holds acme, globex and initech. No test sends a real
# request: every HTTP call goes to FakeSession.

KEY = "TEST-SECRET-KEY-123"
NOW = datetime(2026, 10, 21, 9, 30, tzinfo=timezone.utc)


def article(title, url=None, published="2026-10-19T08:00:00Z", description="", outlet="Daily Paper",
            content="Full text that must never be stored."):
    return {
        "id": "x", "title": title, "description": description, "content": content,
        "url": url or f"https://news.example.com/{re.sub(r'[^a-z]+', '-', title.lower())}",
        "image": None, "publishedAt": published, "lang": "en",
        "source": {"id": "s", "name": outlet, "url": "https://news.example.com", "country": "us"},
    }


def body(*articles):
    return {"totalArticles": len(articles), "articles": list(articles)}


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class FakeSession:
    """Hands out queued replies in order: a (status, payload) pair or an exception to raise."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return FakeResponse(*reply)


def ok(*articles):
    return (200, body(*articles))


def write_aliases(tmp_path, rows=()):
    path = tmp_path / "aliases.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["company_id", "alias_in_dataset", "source"])
        writer.writerows(rows)
    return path


@pytest.fixture
def patterns(library, tmp_path):
    return company_patterns(library, write_aliases(tmp_path, [
        ("acme", "Acme Corp", "gnews"),
        ("globex", "GBX", "gnews"),
        ("initech", "Initrode", "naukri"),  # another source's alias: never used for news
    ]))


QUERIES = {"acme": '"Acme" AND (employees)', "globex": '"Globex" AND (employees)',
           "initech": '"Initech" AND (employees)'}


@pytest.fixture
def fetch(library, patterns):
    """Run the loader against a fake session, with time fixed and no real waiting."""
    def go(session, *, now=NOW, say=None, **kwargs):
        said = []
        result = run(library, key=KEY, queries=QUERIES, patterns=patterns, session=session,
                     now=lambda: now, sleep=lambda seconds: None, say=say or said.append, **kwargs)
        result["said"] = said
        return result
    return go


def stored(db, company_id):
    return [dict(row) for row in db.execute(
        "SELECT * FROM articles WHERE company_id = ? ORDER BY published_at DESC", (company_id,))]


class Analyzer:
    """Stands in for VADER where only the plumbing is under test."""
    def polarity_scores(self, text):
        return {"compound": 0.0}


# --- parsing ---------------------------------------------------------------

def test_parse_keeps_the_display_fields_and_never_the_content():
    [parsed] = parse_articles(body(article("Acme hires 500", description="A short summary.",
                                           published="2026-10-19T08:15:00Z", outlet="The Hindu")))
    assert parsed == {"title": "Acme hires 500", "outlet": "The Hindu", "published_at": "2026-10-19T08:15:00Z",
                      "url": "https://news.example.com/acme-hires-", "summary": "A short summary."}


def test_parse_handles_a_missing_description_and_normalises_the_date():
    item = article("Acme hires", published="2026-10-19T08:15:00.000+00:00")
    item["description"] = None
    [parsed] = parse_articles(body(item))
    assert parsed["summary"] is None
    assert parsed["published_at"] == "2026-10-19T08:15:00Z"


def test_an_article_without_a_url_or_title_is_skipped():
    no_url = article("Acme hires")
    no_url["url"] = ""
    assert parse_articles(body(no_url, article(""))) == []


# --- relevance -------------------------------------------------------------

def test_relevance_keeps_the_name_in_the_title_or_the_description(patterns):
    rows, counts = select_articles(body(
        article("Acme cuts 200 jobs"),
        article("Layoffs hit the sector", description="Acme said on Monday it would cut staff."),
        article("Unrelated story about another firm"),
    ), patterns["acme"], Analyzer())
    assert {r["title"] for r in rows} == {"Acme cuts 200 jobs", "Layoffs hit the sector"}
    assert counts["dropped_irrelevant"] == 1
    assert counts["dropped_titles"] == ["Unrelated story about another firm"]


def test_relevance_is_case_sensitive_and_whole_word(patterns):
    rows, counts = select_articles(body(
        article("Brands target acme of performance"),       # lower case: not the company
        article("Acmeville council hires staff"),           # not a whole word
        article("GBX staff vote to strike"),                # globex's gnews alias
    ), patterns["acme"], Analyzer())
    assert rows == [] and counts["dropped_irrelevant"] == 3
    rows, _ = select_articles(body(article("GBX staff vote to strike")), patterns["globex"], Analyzer())
    assert len(rows) == 1


def test_only_gnews_aliases_count_for_relevance(patterns):
    rows, _ = select_articles(body(article("Initrode staff vote")), patterns["initech"], Analyzer())
    assert rows == []


# --- dedup and cap ---------------------------------------------------------

def test_the_same_url_with_tracking_tags_is_one_article():
    a = parse_articles(body(
        article("Acme hires", url="https://news.example.com/acme-hires?utm_source=x"),
        article("Acme is hiring again", url="https://NEWS.example.com/acme-hires/"),
    ))
    assert len(dedupe(a)) == 1


def test_syndicated_copies_collapse_to_the_earliest():
    a = parse_articles(body(
        article("Acme to cut 1,000 jobs in India - Reuters", url="https://a.example/1",
                published="2026-10-19T08:00:00Z", outlet="Reuters"),
        article("Acme to cut 1,000 jobs in India | Yahoo Finance", url="https://b.example/2",
                published="2026-10-19T10:00:00Z", outlet="Yahoo Finance"),
        article("Acme opens a new campus in Pune", url="https://c.example/3"),
    ))
    kept = dedupe(a)
    assert len(kept) == 2
    assert "Reuters" in {k["outlet"] for k in kept}


def test_at_most_ten_articles_are_kept_newest_first(patterns):
    # Distinct stories: titles this different are never merged as copies.
    stories = ["opens Pune campus", "cuts 200 jobs", "names new CEO", "wins union vote", "raises pay",
               "freezes hiring", "settles lawsuit", "reports profit", "moves to hybrid work",
               "expands in Hyderabad", "faces strike", "trims bonuses", "launches graduate scheme",
               "closes Chennai office"]
    items = [article(f"Acme {story}", url=f"https://news.example.com/{n}",
                     published=f"2026-10-{n + 1:02d}T08:00:00Z") for n, story in enumerate(stories)]
    rows, counts = select_articles(body(*items), patterns["acme"], Analyzer())
    assert len(rows) == MAX_ARTICLES == counts["kept"]
    dates = [r["published_at"] for r in rows]
    assert dates == sorted(dates, reverse=True)
    assert dates[0] == "2026-10-14T08:00:00Z"


def test_sentiment_uses_title_and_description_and_the_shared_label(patterns):
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    analyzer = SentimentIntensityAnalyzer()
    [row], _ = select_articles(body(article("Acme staff praise great new benefits",
                                            description="Employees are happy.")), patterns["acme"], analyzer)
    expected = analyzer.polarity_scores("Acme staff praise great new benefits. Employees are happy.")["compound"]
    assert row["sentiment_compound"] == expected
    assert row["sentiment_label"] == label(expected) == "positive"


# --- storage ---------------------------------------------------------------

def test_a_fetch_stores_articles_and_a_fetch_record(library, fetch):
    fetch(FakeSession(ok(article("Acme hires 500", description="Big news."))), companies=["acme"])
    [row] = stored(library, "acme")
    assert row["title"] == "Acme hires 500" and row["summary"] == "Big news."
    assert row["article_id"].startswith("acme:")
    record = library.execute("SELECT * FROM news_fetches WHERE company_id = 'acme'").fetchone()
    assert record["fetched_at"] == "2026-10-21T09:30:00Z"
    assert record["window_from"] == "2026-09-21T09:30:00Z"
    assert (record["returned"], record["kept"]) == (1, 1)


def test_article_content_is_stored_nowhere(library, fetch):
    fetch(FakeSession(ok(article("Acme hires", content="SECRET ARTICLE BODY"))), companies=["acme"])
    cached = json.loads(library.execute("SELECT response_json FROM news_fetches").fetchone()[0])
    assert all("content" not in a for a in cached["articles"])
    dump = "\n".join(library.iterdump())
    assert "SECRET ARTICLE BODY" not in dump


def test_without_content_leaves_the_original_response_untouched():
    original = body(article("Acme hires"))
    stripped = without_content(original)
    assert "content" in original["articles"][0]
    assert "content" not in stripped["articles"][0]


def test_the_request_sends_the_query_and_a_30_day_window(fetch):
    session = FakeSession(ok())
    fetch(session, companies=["acme"])
    [params] = session.calls
    assert params["q"] == QUERIES["acme"]
    assert params["from"] == "2026-09-21T09:30:00Z"
    assert (params["max"], params["lang"], params["sortby"]) == (10, "en", "publishedAt")


def test_a_company_with_no_matching_articles_still_records_its_fetch(library, fetch):
    fetch(FakeSession(ok(article("Unrelated story"))), companies=["acme"])
    assert stored(library, "acme") == []
    record = library.execute("SELECT kept, dropped_irrelevant FROM news_fetches").fetchone()
    assert tuple(record) == (0, 1)


# --- quota and errors ------------------------------------------------------

def test_403_stops_the_run_and_keeps_what_was_saved(library, fetch):
    session = FakeSession(ok(article("Acme hires")), (403, {"errors": ["You have reached your daily quota"]}))
    result = fetch(session)
    assert len(session.calls) == 2                    # initech was never requested
    assert "quota" in result["stopped"] and "00:00 UTC" in result["stopped"]
    assert len(stored(library, "acme")) == 1
    assert library.execute("SELECT count(*) FROM news_fetches").fetchone()[0] == 1


def test_429_is_retried(library, fetch):
    session = FakeSession((429, {"errors": ["Too many requests"]}), ok(article("Acme hires")))
    result = fetch(session, companies=["acme"])
    assert len(session.calls) == 2 and result["companies"]["acme"]["kept"] == 1


def test_a_failed_company_keeps_its_old_news_and_the_run_continues(library, fetch):
    fetch(FakeSession(ok(article("Acme old story"))), companies=["acme"])
    session = FakeSession((503, {}), (503, {}), (503, {}), (503, {}), ok(article("Globex hires")))
    result = fetch(session, companies=["acme", "globex"], refresh=True, now=NOW + timedelta(days=2))
    assert "acme" in result["failed"]
    assert [r["title"] for r in stored(library, "acme")] == ["Acme old story"]
    assert len(stored(library, "globex")) == 1


def test_a_connection_error_is_retried(fetch):
    session = FakeSession(requests.ConnectionError("boom"), ok(article("Acme hires")))
    result = fetch(session, companies=["acme"])
    assert result["companies"]["acme"]["kept"] == 1


def test_400_fails_that_company_without_retrying(fetch):
    session = FakeSession((400, {"errors": {"q": "syntax error"}}), ok(article("Globex hires")))
    result = fetch(session, companies=["acme", "globex"])
    assert "syntax error" in result["failed"]["acme"]
    assert len(session.calls) == 2


def test_401_stops_the_run(fetch):
    session = FakeSession((401, {"errors": ["Unknown API key"]}))
    result = fetch(session)
    assert "rejected the API key" in result["stopped"] and len(session.calls) == 1


def test_main_exits_with_the_quota_code(monkeypatch, tmp_path):
    monkeypatch.setattr("ingest.load_news.run", lambda *a, **k: {
        "companies": {}, "skipped": [], "failed": {}, "stopped": "quota", "requests": 1})
    monkeypatch.setattr("ingest.load_news.REPORT_PATH", tmp_path / "report.txt")
    monkeypatch.setattr("ingest.load_news.get_conn", lambda: _library_conn())
    monkeypatch.setattr("ingest.load_news.company_patterns", lambda conn: {})
    monkeypatch.setattr("ingest.load_news.read_queries", lambda path, ids: {})
    assert main([]) == QUOTA_STOP


def _library_conn():
    import sqlite3

    from jmsa.db import apply_schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    apply_schema(conn)
    conn.execute("INSERT INTO companies (company_id, name, sector) VALUES ('acme', 'Acme', 'IT Services')")
    return conn


# --- resume and selection --------------------------------------------------

def test_a_company_fetched_recently_is_skipped(fetch):
    fetch(FakeSession(ok()), companies=["acme"])
    session = FakeSession()
    result = fetch(session, companies=["acme"], now=NOW + timedelta(hours=2))
    assert session.calls == [] and [c for c, _ in result["skipped"]] == ["acme"]


def test_a_company_fetched_over_a_day_ago_is_fetched_again(fetch):
    fetch(FakeSession(ok()), companies=["acme"])
    session = FakeSession(ok())
    fetch(session, companies=["acme"], now=NOW + timedelta(hours=30))
    assert len(session.calls) == 1


def test_refresh_fetches_regardless(fetch):
    fetch(FakeSession(ok()), companies=["acme"])
    session = FakeSession(ok())
    fetch(session, companies=["acme"], refresh=True, now=NOW + timedelta(hours=2))
    assert len(session.calls) == 1


def test_a_refetch_replaces_the_old_articles(library, fetch):
    fetch(FakeSession(ok(article("Acme old story"))), companies=["acme"])
    fetch(FakeSession(ok(article("Acme new story"))), companies=["acme"], now=NOW + timedelta(days=2))
    assert [r["title"] for r in stored(library, "acme")] == ["Acme new story"]


def test_limit_takes_the_first_companies_due(fetch):
    fetch(FakeSession(ok()), companies=["acme"])
    session = FakeSession(ok(), ok())
    result = fetch(session, limit=2, now=NOW + timedelta(hours=1))
    assert list(result["companies"]) == ["globex", "initech"]   # acme is skipped, not counted


def test_an_unknown_company_is_rejected(fetch):
    with pytest.raises(NewsError):
        fetch(FakeSession(), companies=["no-such-company"])


def test_from_cache_reselects_without_a_request(library, fetch, tmp_path):
    fetch(FakeSession(ok(article("GBX staff vote"))), companies=["acme"])
    assert stored(library, "acme") == []
    # An acme alias added later picks the cached article up; no session exists to call.
    patterns = company_patterns(library, write_aliases(tmp_path, [("acme", "GBX", "gnews")]))
    reselect_from_cache(library, patterns, say=lambda text: None)
    assert [r["title"] for r in stored(library, "acme")] == ["GBX staff vote"]
    assert library.execute("SELECT fetched_at FROM news_fetches").fetchone()[0] == "2026-10-21T09:30:00Z"


# --- the key never leaks ---------------------------------------------------

def test_the_key_appears_in_no_output_report_or_row(library, fetch, capsys):
    leaky = requests.ConnectionError(f"Max retries exceeded with url: /api/v4/search?q=x&apikey={KEY}")
    session = FakeSession(
        leaky, leaky, leaky, leaky,                                         # acme: fails
        (400, {"errors": [f"bad request for apikey={KEY}"]}),               # globex: fails
        (403, {"errors": [f"quota reached for {KEY}"]}),                    # initech: stops
    )
    result = fetch(session, say=print)
    fetch(FakeSession(ok(article("Acme hires"))), companies=["acme"], say=print)
    report = build_report(result)
    out = capsys.readouterr()
    assert KEY not in out.out + out.err
    assert KEY not in report
    assert KEY not in "\n".join(library.iterdump())
    assert result["failed"] and result["stopped"]


def test_no_request_is_sent_without_a_key(library, patterns):
    session = FakeSession()
    with pytest.raises(NewsError, match="GNEWS_API_KEY"):
        run(library, key=None, queries=QUERIES, patterns=patterns, session=session)
    assert session.calls == []


def test_redact():
    assert redact(f"url?apikey={KEY}", KEY) == "url?apikey=***"
    assert redact("nothing here", None) == "nothing here"


# --- the queries file ------------------------------------------------------

def write_queries(tmp_path, rows):
    path = tmp_path / "queries.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["company_id", "query"])
        writer.writerows(rows)
    return path


def test_queries_load_when_every_company_has_one(tmp_path):
    path = write_queries(tmp_path, [("acme", '"Acme"'), ("globex", '"Globex"')])
    assert read_queries(path, {"acme", "globex"}) == {"acme": '"Acme"', "globex": '"Globex"'}


@pytest.mark.parametrize("rows, problem", [
    ([("acme", '"Acme"')], "no query for globex"),
    ([("acme", '"Acme"'), ("globex", '"Globex"'), ("umbrella", '"Umbrella"')], "unknown company_id"),
    ([("acme", '"Acme"'), ("globex", "x" * 201)], "201 characters"),
    ([("acme", '"Acme"'), ("globex", "")], "empty query"),
])
def test_bad_queries_are_rejected(tmp_path, rows, problem):
    with pytest.raises(NewsError) as error:
        read_queries(write_queries(tmp_path, rows), {"acme", "globex"})
    assert any(problem in p for p in error.value.problems)


def test_the_committed_queries_file_covers_the_library():
    from jmsa.config import COMPANIES_CSV
    from ingest.load_news import QUERIES_CSV
    with COMPANIES_CSV.open(newline="", encoding="utf-8") as handle:
        ids = {row["company_id"] for row in csv.DictReader(handle)}
    assert set(read_queries(QUERIES_CSV, ids)) == ids
