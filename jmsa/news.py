"""How a company's news coverage (F6) is read and shown.

One definition for the Company page, with no Streamlit code so the tests
call it directly. Every value comes back as display text, with the
missing-data rule already applied. The articles come from ingest.load_news;
the page never calls GNews.
"""

from __future__ import annotations

import re
import sqlite3

from jmsa.display import NOT_AVAILABLE
from jmsa.sentiment import MONTHS

# The free tier searches only the last 30 days and returns 10 articles a
# request, so "the last 12 months" isn't something this source can give.
NEWS_NOTE = (
    "Headline sentiment is approximate: VADER scores only the headline and GNews's short "
    "description, not the article, and a neutral-sounding headline can report bad news. "
    "Up to 10 most recent articles published in the 30 days before the fetch date "
    "(GNews free tier, up to 12 hours behind), kept only if they name the company in the "
    "title or description."
)


def day_month_year(iso_date: str | None) -> str | None:
    """'2026-10-19T08:15:00Z' -> '19 Oct 2026'."""
    if not iso_date:
        return None
    return f"{int(iso_date[8:10])} {MONTHS[int(iso_date[5:7]) - 1]} {iso_date[:4]}"


def escape_markdown(text: str) -> str:
    """A headline safe to put inside [link text]: brackets, * and _ can't break the link."""
    return re.sub(r"([\\`*_{}\[\]()#+!|<>~$])", r"\\\1", text)


def read_news(conn: sqlite3.Connection, company_id: str) -> dict:
    """A company's articles, newest first, ready to display.

    fetched_on is None when news has never been fetched for the company.
    available is False when there are no articles, fetched or not; message
    then says which of the two it is.
    """
    fetch = conn.execute("SELECT fetched_at FROM news_fetches WHERE company_id = ?", (company_id,)).fetchone()
    fetched_on = day_month_year(fetch["fetched_at"]) if fetch else None
    rows = [
        {
            "title": escape_markdown(row["title"]),
            "url": row["url"],
            "outlet": row["outlet"] or NOT_AVAILABLE,
            "date": day_month_year(row["published_at"]) or NOT_AVAILABLE,
            "sentiment": row["sentiment_label"] or NOT_AVAILABLE,
        }
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
