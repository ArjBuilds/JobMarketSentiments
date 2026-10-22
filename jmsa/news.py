"""How a company's news coverage (F6) is read and shown.

One definition for the Company page and Explore's recent articles, with no Streamlit code so the tests
call it directly. Every value comes back as display text, with the
missing-data rule already applied. The articles come from ingest.load_news;
the page never calls GNews.
"""

from __future__ import annotations

import re
import sqlite3

from jmsa.display import show
from jmsa.sentiment import MONTHS

# The stored sentiment labels, in the order Explore's news tabs show them.
LABELS = ("positive", "neutral", "negative")

# The free tier searches only the last 30 days and returns 10 articles a
# request, so news is never labelled "the last 12 months" (docs/methods.md).


def day_month_year(iso_date: str | None) -> str | None:
    """'2026-10-19T08:15:00Z' -> '19 Oct 2026'."""
    if not iso_date:
        return None
    return f"{int(iso_date[8:10])} {MONTHS[int(iso_date[5:7]) - 1]} {iso_date[:4]}"


def escape_markdown(text: str) -> str:
    """A headline safe to put inside [link text]: brackets, * and _ can't break the link."""
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~$])", r"\\\1", text)


def article_row(row: sqlite3.Row) -> dict:
    """One stored article as display text, the same on every page."""
    return {
        "title": escape_markdown(row["title"]),
        "url": row["url"],
        "outlet": show(row["outlet"]),
        "date": show(day_month_year(row["published_at"])),
        "sentiment": show(row["sentiment_label"]),
    }


def read_news(conn: sqlite3.Connection, company_id: str) -> dict:
    """A company's articles, newest first, ready to display.

    fetched_on is None when news has never been fetched for the company.
    available is False when there are no articles, fetched or not; message
    then says which of the two it is.
    """
    fetch = conn.execute("SELECT fetched_at FROM news_fetches WHERE company_id = ?", (company_id,)).fetchone()
    fetched_on = day_month_year(fetch["fetched_at"]) if fetch else None
    rows = [
        article_row(row)
        for row in conn.execute(
            "SELECT title, url, outlet, published_at, sentiment_label FROM articles"
            " WHERE company_id = ? ORDER BY published_at DESC, article_id",
            (company_id,),
        )
    ]
    if fetched_on is None:
        message = "News hasn't been fetched for this company."
    elif not rows:
        message = f"No articles naming this company in the 30 days before news was fetched on {fetched_on}."
    else:
        message = None
    return {"available": bool(rows), "fetched_on": fetched_on, "message": message, "rows": rows}


def read_recent(conn: sqlite3.Connection, limit: int = 15) -> dict[str, dict]:
    """The newest articles across every company, by sentiment label, for Explore.

    label -> {"count": every article with that label, "rows": the newest
    `limit` of them}. Each row is article_row()'s plus the company it names
    and the article_id, which keeps each row's button key unique.
    """
    recent = {name: {"count": 0, "rows": []} for name in LABELS}
    for row in conn.execute(
        "SELECT a.article_id, a.company_id, c.name AS company, a.title, a.url, a.outlet,"
        " a.published_at, a.sentiment_label FROM articles a JOIN companies c USING (company_id)"
        " WHERE a.sentiment_label IS NOT NULL ORDER BY a.published_at DESC, a.article_id"
    ):
        group = recent[row["sentiment_label"]]
        group["count"] += 1
        if len(group["rows"]) < limit:
            group["rows"].append({**article_row(row), "article_id": row["article_id"],
                                  "company_id": row["company_id"], "company": row["company"]})
    return recent


def news_moods(conn: sqlite3.Connection) -> dict[str, tuple[float, int]]:
    """company_id -> (mean headline compound, number of articles), for companies with any.

    The mean of the stored headline scores, so it is labelled with the same
    cut-offs as everything else (jmsa.sentiment.label).
    """
    return {
        row["company_id"]: (row["mood"], row["articles"])
        for row in conn.execute(
            "SELECT company_id, AVG(sentiment_compound) AS mood, COUNT(*) AS articles FROM articles"
            " WHERE sentiment_compound IS NOT NULL GROUP BY company_id"
        )
    }
