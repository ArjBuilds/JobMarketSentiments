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

A company can have several published rows (data/turnover.csv): its latest
figure, which is the one shown, and older rows whose period overlaps the
proxy window, kept only to compare the proxy against published attrition.
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

# The one line beside every proxy figure. What the proxy can't tell you,
# and how it was checked against published attrition, is in docs/methods.md.
PROXY_HELP = "Reviews mentioning people leaving, per 100 reviews. Not a share of staff."

# What a published figure measures, as its document says. "not-stated" when
# the document doesn't say voluntary or total; never inferred.
BASES = ("voluntary", "total", "not-stated")
BASIS_NAMES = {"voluntary": "voluntary", "total": "total", "not-stated": "basis not stated"}

# Whose figure it is: the library company as a whole, one segment of it
# (e.g. IT services), or its listed India subsidiary.
SCOPES = ("group", "segment", "india-subsidiary")
SCOPE_NAMES = {"group": "group", "segment": "segment", "india-subsidiary": "India subsidiary"}

PRE_MERGER_NOTE = ("These reviews are of Mindtree, before its 2022 merger into LTIMindtree, "
                   "and describe the pre-merger company.")


def per_100(count: int, total: int) -> str:
    """41 of 1,000 -> '4.1'."""
    return f"{100 * count / total:.1f}"


def proxy_parts(row) -> dict[str, str] | None:
    """The proxy as display text: total, split and size, plus whether the
    figures are shown at all. None if there is no row.

    Below 20 reviews in the window the figures are hidden, but the count is
    still shown, as with review sentiment.
    """
    if row is None:
        return None
    n = row["reviews_in_window"]
    if not is_shown(n):
        return {"total": hidden(n), "split": hidden(n), "reviews": f"{n:,}", "shown": False}
    return {
        "total": per_100(row["reviews_matched"], n),
        "split": " · ".join(f"{KIND_NAMES[kind]} {per_100(row[f'reviews_{kind}'], n)}" for kind in KINDS),
        "reviews": f"{n:,}",
        "shown": True,
    }


def proxy_text(parts: dict[str, str] | None) -> str:
    """'6.1 per 100 reviews (leaving/attrition 4.0, layoffs 2.1), from 41,203 reviews dated ...'."""
    if parts is None:
        return NOT_AVAILABLE
    if not parts["shown"]:
        return parts["total"]
    split = parts["split"].replace(" · ", ", ")
    return (f"{parts['total']} per 100 reviews ({split}), from {parts['reviews']} reviews "
            f"dated {WINDOW_TITLE}")


def overlaps_window(start: str | None, end: str | None) -> bool:
    """Does a period overlap the proxy window? Both ends are needed to say."""
    return bool(start and end) and start <= WINDOW_END and end >= WINDOW_START


def published_text(row) -> dict[str, str]:
    """A published figure as display text. The value is shown as printed:
    Accenture's '13' stays '13%', not '13.0%'."""
    return {
        "value": f"{row['attrition_text']}%",
        "period": show(row["period"]),
        "basis": BASIS_NAMES.get(row["basis"], NOT_AVAILABLE),
        "scope": SCOPE_NAMES.get(row["scope"], NOT_AVAILABLE),
        "definition": show(row["definition"]),
        "entity": show(row["entity"]),
        "source_url": row["source_url"],
        "source_ref": show(row["source_ref"]),
        "retrieved_on": show(row["retrieved_on"]),
        "note": row["method_note"] or None,
    }


def latest_published(conn: sqlite3.Connection, company_id: str):
    """A company's latest published row (latest period_end), or None."""
    return conn.execute(
        "SELECT * FROM turnover WHERE company_id = ? AND is_proxy = 0"
        " ORDER BY period_end DESC, period DESC LIMIT 1",
        (company_id,),
    ).fetchone()


def read_turnover(conn: sqlite3.Connection, company_id: str) -> dict:
    """A company's turnover, ready to display.

    published is the latest published figure as display text, or None;
    older rows are only for the proxy comparison and are never shown. proxy
    is the proxy's text, "not available" when the company has no reviews in
    the window. note carries the pre-merger warning for the proxy.
    """
    latest = latest_published(conn, company_id)
    published = published_text(latest) if latest is not None else None
    proxy_row = conn.execute(
        "SELECT * FROM turnover WHERE company_id = ? AND is_proxy = 1", (company_id,)
    ).fetchone()
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
