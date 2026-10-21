from jmsa.display import NOT_AVAILABLE
from jmsa.news import day_month_year, escape_markdown, read_news

# The library fixture holds acme, globex and initech.


def add_fetch(db, company_id, fetched_at="2026-10-21T09:30:00Z"):
    db.execute(
        "INSERT INTO news_fetches (company_id, fetched_at, query, window_from, returned, dropped_irrelevant,"
        " dropped_duplicate, kept, response_json) VALUES (?, ?, 'q', '2026-09-21T09:30:00Z', 0, 0, 0, 0, '{}')",
        (company_id, fetched_at),
    )


def add_article(db, article_id, company_id, title="Acme hires", published="2026-10-19T08:00:00Z",
                outlet="Reuters", sentiment="positive"):
    db.execute(
        "INSERT INTO articles (article_id, company_id, title, outlet, published_at, url, sentiment_label)"
        " VALUES (?, ?, ?, ?, ?, 'https://example.com/a', ?)",
        (article_id, company_id, title, outlet, published, sentiment),
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
