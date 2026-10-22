"""Where each source's data comes from and when (milestone 9).

One definition for every page's source lines, for the sources table on the
Compare and About pages, and for the sidebar's last-refreshed date. No Streamlit here, so the tests call it
directly. Every date is read from the database, never written into a
caption, so a reload changes what the pages say. Every value comes back as
display text, with the missing-data rule applied through show().

The ratings file is the one source with no date: it records none.
"""

from __future__ import annotations

import sqlite3

from jmsa.display import NOT_AVAILABLE, plural, show
from jmsa.jobs import link_date
from jmsa.news import day_month_year
from jmsa.sentiment import month_year
from jmsa.skills import EXPORTS
from jmsa.turnover import WINDOW_END

REVIEWS_URL = "https://www.kaggle.com/datasets/davidgauthier/glassdoor-job-reviews-2"
REVIEWS_SOURCE = "Glassdoor reviews, Kaggle dataset davidgauthier/glassdoor-job-reviews-2 (all_reviews.csv)"
REVIEWS_LICENCE = "CC BY-NC-SA 4.0: non-commercial, share-alike; this project is non-commercial coursework"

# Where the ratings and postings files came from, as recorded by the project
# owner. Nothing more is known, so nothing more is claimed.
UNRECORDED_KAGGLE = ("Kaggle dataset, downloaded October 2026; exact dataset page not recorded; "
                     "licence unknown. Used only for non-commercial coursework")
RATINGS_SOURCE = ("Glassdoor company ratings snapshot, data/raw/glassdoor_company_ratings.csv "
                  "(originally Glassdoor_Dataset.csv)")
NAUKRI_SOURCE = ("Naukri postings, data/raw/naukri_jobs_merged.csv: three exports merged ("
                 + ", ".join(EXPORTS) + ")")

GNEWS_SOURCE = "GNews API (https://gnews.io), free tier"
GNEWS_LICENCE = "GNews free tier: non-commercial use only"

ATTRITION_SOURCE = ("Companies' own annual reports, BRSR, quarterly results or fact sheets and "
                    "official ESG reports, copied by hand into data/turnover.csv")
ATTRITION_LICENCE = "Public company documents, cited per figure with a source link and page reference"


def sparse_note(last_iso: str | None) -> str:
    """' (sparse after Mar 2023)' when a review range runs past the proxy window's end.

    Reviews fall from about 21,000 a month to a few hundred after the window
    ends (jmsa.turnover.WINDOW_END), so a range ending in Jul 2023 overstates
    how recent the reviews are without this.
    """
    if last_iso and last_iso > WINDOW_END:
        return f" (sparse after {month_year(WINDOW_END)})"
    return ""


def span(first: str | None, last: str | None, fmt) -> str | None:
    """'Jan 2008 – Jul 2023' through fmt; one date when both ends agree; None if either is missing."""
    first, last = fmt(first), fmt(last)
    if not first or not last:
        return None
    return first if first == last else f"{first} – {last}"


def review_range(conn: sqlite3.Connection) -> str:
    """'Jan 2008 – Jul 2023 (sparse after Mar 2023)': every scored review's date range.

    Read from review_summary, never from the 1.8M-row reviews table, so it costs nothing.
    """
    first, last = conn.execute(
        "SELECT MIN(first_date), MAX(last_date) FROM review_summary WHERE period = 'all'"
    ).fetchone()
    text = span(first, last, month_year)
    return text + sparse_note(last) if text else NOT_AVAILABLE


def review_end(conn: sqlite3.Connection) -> str:
    """'Jul 2023 (sparse after Mar 2023)': when the reviews end."""
    last = conn.execute("SELECT MAX(last_date) FROM review_summary WHERE period = 'all'").fetchone()[0]
    return month_year(last) + sparse_note(last) if last else NOT_AVAILABLE


def newest_link(conn: sqlite3.Connection):
    """The newest job-ID date among the stored (verified) links, or None."""
    dates = [d for (url,) in conn.execute("SELECT url FROM jobs WHERE url IS NOT NULL")
             if (d := link_date(url)) is not None]
    return max(dates) if dates else None


def snapshot_month(conn: sqlite3.Connection) -> str:
    """'Oct 2023': the month of the newest stored link, for ROLES_INTRO."""
    newest = newest_link(conn)
    return month_year(newest.isoformat()) if newest else NOT_AVAILABLE


def naukri_dates(conn: sqlite3.Connection) -> str:
    """When the postings were collected (bounded by their job IDs) and loaded."""
    newest = newest_link(conn)
    loaded = conn.execute("SELECT MAX(loaded_at) FROM jobs").fetchone()[0]
    if newest is None and loaded is None:
        return NOT_AVAILABLE
    collected = (f"collected in or after {day_month_year(newest.isoformat())} (the newest Naukri "
                 "job-ID date among the stored links; the third export has no links and is undated)"
                 if newest else f"collection date {NOT_AVAILABLE}")
    return f"{collected}; loaded {show(day_month_year(loaded))}"


def news_dates(conn: sqlite3.Connection) -> str:
    """'fetched 21 Oct 2026 for 82 of 82 companies': when GNews was last asked."""
    first, last, fetched = conn.execute(
        "SELECT MIN(fetched_at), MAX(fetched_at), COUNT(*) FROM news_fetches"
    ).fetchone()
    when = span(first, last, day_month_year)
    if when is None:
        return NOT_AVAILABLE
    companies = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    return (f"fetched {when} for {fetched:,} of {plural(companies, 'company')}; each article "
            "published in the 30 days before its company's fetch")


def attrition_dates(conn: sqlite3.Connection) -> str:
    """'periods vary by company; retrieved 22 Oct 2026'."""
    first, last = conn.execute(
        "SELECT MIN(retrieved_on), MAX(retrieved_on) FROM turnover WHERE is_proxy = 0"
    ).fetchone()
    when = span(first, last, day_month_year)
    return f"periods vary by company (shown with each figure); retrieved {when}" if when else NOT_AVAILABLE


def last_refreshed(conn: sqlite3.Connection) -> str:
    """'22 Oct 2026': the newest date the pipeline last touched a source, for the sidebar.

    Only three sources record when they were loaded: the Naukri load, the
    GNews fetches and the attrition retrievals. The ratings and review files
    record no load date, so they can't count. ISO dates sort as text, and a
    date sorts before a timestamp on the same day, which day_month_year
    reads the same.
    """
    dates = [conn.execute(sql).fetchone()[0] for sql in (
        "SELECT MAX(loaded_at) FROM jobs",
        "SELECT MAX(fetched_at) FROM news_fetches",
        "SELECT MAX(retrieved_on) FROM turnover WHERE is_proxy = 0",
    )]
    present = [d for d in dates if d]
    return day_month_year(max(present)) if present else NOT_AVAILABLE


def proxy_window(conn: sqlite3.Connection) -> str:
    """'reviews dated Apr 2021 – Mar 2023': the window the stored proxy rows cover."""
    first, last = conn.execute(
        "SELECT MIN(period_start), MAX(period_end) FROM turnover WHERE is_proxy = 1"
    ).fetchone()
    when = span(first, last, month_year)
    return f"reviews dated {when}" if when else NOT_AVAILABLE


def read_freshness(conn: sqlite3.Connection) -> dict[str, dict[str, str]]:
    """Every source: what it is, what it feeds, its dates and its licence. All text."""
    reviews = review_range(conn)
    naukri = naukri_dates(conn)
    return {
        "ratings": {
            "Source": RATINGS_SOURCE,
            "Used for": "Glassdoor rating and number of ratings",
            "Dates": f"{NOT_AVAILABLE}: the file records no snapshot date",
            "Licence": UNRECORDED_KAGGLE,
        },
        "reviews": {
            "Source": REVIEWS_SOURCE,
            "Used for": "Review sentiment and themes",
            "Dates": f"reviews dated {reviews}" if reviews != NOT_AVAILABLE else NOT_AVAILABLE,
            "Licence": REVIEWS_LICENCE,
        },
        "roles": {
            "Source": NAUKRI_SOURCE,
            "Used for": "Data-role listings",
            "Dates": naukri,
            "Licence": UNRECORDED_KAGGLE,
        },
        "skills": {
            "Source": "The same Naukri snapshot as the data-role listings",
            "Used for": "Market-wide data-role skills",
            "Dates": naukri,
            "Licence": UNRECORDED_KAGGLE,
        },
        "news": {
            "Source": GNEWS_SOURCE,
            "Used for": "News coverage and headline sentiment",
            "Dates": news_dates(conn),
            "Licence": GNEWS_LICENCE,
        },
        "attrition": {
            "Source": ATTRITION_SOURCE,
            "Used for": "Published attrition",
            "Dates": attrition_dates(conn),
            "Licence": ATTRITION_LICENCE,
        },
        "proxy": {
            "Source": "The Glassdoor review dataset above",
            "Used for": "Turnover proxy",
            "Dates": proxy_window(conn),
            "Licence": REVIEWS_LICENCE,
        },
    }


def freshness_table(freshness: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    """The sources as table rows, in read_freshness's order."""
    return list(freshness.values())


def source_line(freshness: dict[str, dict[str, str]], key: str) -> str:
    """'Source: <source>; <dates>.' for the caption under one section."""
    entry = freshness[key]
    return f"Source: {entry['Source']}; {entry['Dates']}."
