"""How a company's turnover (F5) is defined, read and shown.

One definition for process.turnover_proxy, the Company page and the Library
page. No Streamlit here, so the tests call it directly.

Two kinds of figure live in the turnover table and are never mixed:

    published   attrition % from the company's own documents (is_proxy = 0)
    proxy       the share of Glassdoor reviews in a fixed window whose
                headline or cons mention leaving, attrition or layoffs
                (is_proxy = 1)

The proxy counts reviews, not people, so it is always shown "per 100
reviews", never with a % sign, and always labelled "proxy".
"""

from __future__ import annotations

import sqlite3

from jmsa.display import NOT_AVAILABLE, show
from jmsa.sentiment import hidden, is_shown, month_year

# The last 24 months with full coverage. Reviews thin out from April 2023
# (4,311 that month, then about 250 a month against 21,000+ before), and only
# for some companies, so later months would make the window uneven.
WINDOW_START = "2021-04-01"
WINDOW_END = "2023-03-31"
WINDOW_PERIOD = "2021-04 to 2023-03"
WINDOW_TITLE = f"{month_year(WINDOW_START)} – {month_year(WINDOW_END)}"

# The two kinds of keyword in data/turnover_keywords.csv, shown separately:
# the window spans both the 2021-22 resignation wave and the late-2022 layoffs.
KINDS = ("leaving", "layoffs")
KIND_NAMES = {"leaving": "leaving/attrition", "layoffs": "layoffs"}

PROXY_DEFINITION = ("Share of Glassdoor reviews whose headline or cons mention people leaving, "
                    "attrition or layoffs")
PROXY_SOURCE_URL = "https://www.kaggle.com/datasets/davidgauthier/glassdoor-job-reviews-2"

PROXY_NOTE = (
    "The proxy counts reviews, not people: a review can mention colleagues leaving or layoffs "
    "elsewhere, and reviewers aren't a representative sample of staff. Don't read it as an "
    f"attrition rate. It covers reviews dated {WINDOW_TITLE}, the last two years with full "
    "coverage in the review dataset, and searches the headline and cons only (keywords in "
    "data/turnover_keywords.csv). A review can mention both kinds, so the two parts can add "
    "up to more than the total."
)

PRE_MERGER_NOTE = ("These reviews are of Mindtree, before its 2022 merger into LTIMindtree, "
                   "and describe the pre-merger company.")


def per_100(count: int, total: int) -> str:
    """41 of 1,000 -> '4.1'."""
    return f"{100 * count / total:.1f}"


def proxy_parts(row) -> dict[str, str] | None:
    """The proxy as display text: total, split and size. None if there is no row.

    Below 20 reviews in the window the figures are hidden, but the count is
    still shown, as with review sentiment.
    """
    if row is None:
        return None
    n = row["reviews_in_window"]
    if not is_shown(n):
        return {"total": hidden(n), "split": hidden(n), "reviews": f"{n:,}"}
    return {
        "total": per_100(row["reviews_matched"], n),
        "split": " · ".join(f"{KIND_NAMES[kind]} {per_100(row[f'reviews_{kind}'], n)}" for kind in KINDS),
        "reviews": f"{n:,}",
    }


def proxy_text(parts: dict[str, str] | None) -> str:
    """'6.1 per 100 reviews (leaving/attrition 4.0, layoffs 2.1), from 41,203 reviews dated ...'."""
    if parts is None:
        return NOT_AVAILABLE
    if parts["total"].startswith("hidden"):
        return parts["total"]
    split = parts["split"].replace(" · ", ", ")
    return (f"{parts['total']} per 100 reviews ({split}), from {parts['reviews']} reviews "
            f"dated {WINDOW_TITLE}")


def published_text(row) -> dict[str, str]:
    """A published figure as display text."""
    return {
        "value": f"{row['attrition_pct']:.1f}%",
        "period": show(row["period"]),
        "definition": show(row["definition"]),
        "entity": show(row["entity"]),
        "source_url": row["source_url"],
        "source_ref": show(row["source_ref"]),
    }


def read_turnover(conn: sqlite3.Connection, company_id: str) -> dict:
    """A company's turnover, ready to display.

    published is a list, latest period first, possibly empty. proxy is the
    proxy's text, "not available" when the company has no reviews in the
    window. note carries the pre-merger warning for the proxy.
    """
    rows = conn.execute(
        "SELECT * FROM turnover WHERE company_id = ? ORDER BY is_proxy, period_end DESC",
        (company_id,),
    ).fetchall()
    published = [published_text(row) for row in rows if not row["is_proxy"]]
    proxy_row = next((row for row in rows if row["is_proxy"]), None)
    note = None
    if proxy_row is not None:
        summary = conn.execute(
            "SELECT pre_merger_count FROM review_summary WHERE company_id = ? AND period = 'all'",
            (company_id,),
        ).fetchone()
        if summary is not None and summary["pre_merger_count"]:
            note = PRE_MERGER_NOTE
    return {
        "published": published,
        "proxy": proxy_text(proxy_parts(proxy_row)),
        "proxy_available": proxy_row is not None,
        "note": note,
    }
