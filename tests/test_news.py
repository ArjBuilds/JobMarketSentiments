import pytest

from jmsa.display import NOT_AVAILABLE
from jmsa.news import day_month_year, escape_markdown, news_moods, read_news, read_recent

# The library fixture holds acme, globex and initech.


def add_fetch(db, company_id, fetched_at="2026-10-21T09:30:00Z"):
    db.execute(
        "INSERT INTO news_fetches (company_id, fetched_at, query, window_from, returned, dropped_irrelevant,"
        " dropped_duplicate, kept, response_json) VALUES (?, ?, 'q', '2026-09-21T09:30:00Z', 0, 0, 0, 0, '{}')",
        (company_id, fetched_at),
    )


def add_article(db, article_id, company_id, title="Acme hires", published="2026-10-19T08:00:00Z",
                outlet="Reuters", sentiment="positive", compound=None):
    db.execute(
        "INSERT INTO articles (article_id, company_id, title, outlet, published_at, url, sentiment_label,"
        " sentiment_compound) VALUES (?, ?, ?, ?, ?, 'https://example.com/a', ?, ?)",
        (article_id, company_id, title, outlet, published, sentiment, compound),
    )


def test_never_fetched_is_not_available(library):
    news = read_news(library, "acme")
    assert news["available"] is False and news["fetched_on"] is None
    assert "hasn't been fetched" in news["message"]


def test_fetched_with_no_articles_says_when(library):
    add_fetch(library, "acme")
    news = read_news(library, "acme")
    assert news["available"] is False
    assert news["message"] == ("No articles naming this company in the 30 days before news was "
                               "fetched on 21 Oct 2026.")


def test_articles_come_newest_first_with_display_text(library):
    add_fetch(library, "acme")
    add_article(library, "acme:1", "acme", title="Older", published="2026-10-02T08:00:00Z")
    add_article(library, "acme:2", "acme", title="Newer", published="2026-10-19T08:00:00Z", outlet=None)
    news = read_news(library, "acme")
    assert news["available"] and news["message"] is None and news["fetched_on"] == "21 Oct 2026"
    assert [r["title"] for r in news["rows"]] == ["Newer", "Older"]
    assert news["rows"][0] == {"title": "Newer", "url": "https://example.com/a", "outlet": NOT_AVAILABLE,
                               "date": "19 Oct 2026", "sentiment": "positive"}


def test_titles_are_escaped_so_they_cant_break_the_link():
    assert escape_markdown("Acme [update]: *big* cuts") == r"Acme \[update\]: \*big\* cuts"


def test_day_month_year():
    assert day_month_year("2026-10-01T08:00:00Z") == "1 Oct 2026"
    assert day_month_year(None) is None


# --- across companies, for Explore ------------------------------------------

def test_recent_articles_are_grouped_by_label_newest_first_with_their_company(library):
    add_article(library, "acme:1", "acme", title="Old", published="2026-10-01T08:00:00Z")
    add_article(library, "globex:1", "globex", title="New", published="2026-10-20T08:00:00Z")
    add_article(library, "acme:2", "acme", title="Cuts", sentiment="negative")
    recent = read_recent(library)
    assert list(recent) == ["positive", "neutral", "negative"]
    assert [r["title"] for r in recent["positive"]["rows"]] == ["New", "Old"]
    assert recent["positive"]["rows"][0]["company_id"] == "globex"
    assert recent["positive"]["rows"][0]["company"] == "Globex"
    assert recent["negative"]["count"] == 1 and recent["neutral"] == {"count": 0, "rows": []}


def test_recent_articles_cap_each_label_but_count_them_all(library):
    for n in range(5):
        add_article(library, f"acme:{n}", "acme", published=f"2026-10-1{n}T08:00:00Z")
    recent = read_recent(library, limit=3)
    assert recent["positive"]["count"] == 5
    assert [r["article_id"] for r in recent["positive"]["rows"]] == ["acme:4", "acme:3", "acme:2"]


def test_news_mood_is_the_mean_headline_score_and_its_article_count(library):
    add_article(library, "acme:1", "acme", compound=0.5)
    add_article(library, "acme:2", "acme", compound=-0.1, sentiment="negative")
    moods = news_moods(library)
    assert moods["acme"][0] == pytest.approx(0.2) and moods["acme"][1] == 2
    assert "globex" not in moods
