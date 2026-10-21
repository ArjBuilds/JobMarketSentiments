"""The compare view (F9): 2-4 companies side by side in one table.

No Streamlit here, so the tests call it directly. Nothing is computed anew:
the company figures are the Library page's records (jmsa.library) formatted
by the Library's own display_row, so every label, caveat and "not available"
matches that page, and the news figures are jmsa.news.read_news's.
"""

from __future__ import annotations

from jmsa.display import NOT_AVAILABLE, show
from jmsa.library import column_headers, display_row
from jmsa.sentiment import PERIODS

MIN_COMPANIES = 2
MAX_COMPANIES = 4

# Library keys shown once, before and after the review figures, which are
# shown for every review period.
BEFORE_REVIEWS = ("sector", "hq_country", "rating", "rating_count")
REVIEW_KEYS = ("sentiment", "reviews")
AFTER_REVIEWS = ("data_roles", "attrition", "proxy", "proxy_split")

NEWS_ARTICLES = "News articles (up to 10, published in the 30 days before the fetch)"
NEWS_FETCHED = "News fetched on"


def news_cells(news: dict | None) -> dict[str, str]:
    """A company's two news rows. No articles reads "not available", never 0,
    as on the Company page; None means news was never read for it."""
    if news is None:
        return {NEWS_ARTICLES: NOT_AVAILABLE, NEWS_FETCHED: NOT_AVAILABLE}
    return {
        NEWS_ARTICLES: f"{len(news['rows']):,}" if news["available"] else NOT_AVAILABLE,
        NEWS_FETCHED: show(news["fetched_on"]),
    }


def metric_labels() -> list[str]:
    """The table's row labels, in order."""
    labels = [column_headers("all")[key] for key in BEFORE_REVIEWS]
    for period in PERIODS:
        labels += [column_headers(period)[key] for key in REVIEW_KEYS]
    labels += [column_headers("all")[key] for key in AFTER_REVIEWS]
    return labels + [NEWS_ARTICLES, NEWS_FETCHED]


def compare_table(records: list[dict], news_by_id: dict[str, dict],
                  company_ids: list[str]) -> list[dict[str, str]]:
    """One row per metric, one column per company (by name), all display text.

    records are load_library()'s; news_by_id maps company_id to read_news()'s
    result. Raises ValueError for fewer than 2 or more than 4 companies, or
    an id that isn't in the library.
    """
    if not MIN_COMPANIES <= len(company_ids) <= MAX_COMPANIES:
        raise ValueError(f"pick {MIN_COMPANIES} to {MAX_COMPANIES} companies, not {len(company_ids)}")
    by_id = {record["company_id"]: record for record in records}
    unknown = [company_id for company_id in company_ids if company_id not in by_id]
    if unknown:
        raise ValueError(f"not in the library: {', '.join(unknown)}")

    # Each company's cells, label -> text. display_row gives the review figures
    # under period-specific headers, so merging both periods keeps both.
    columns = {}
    for company_id in company_ids:
        record = by_id[company_id]
        cells = {}
        for period in PERIODS:
            cells |= display_row(record, period)
        columns[record["name"]] = cells | news_cells(news_by_id.get(company_id))
    return [{"Metric": label, **{name: cells[label] for name, cells in columns.items()}}
            for label in metric_labels()]
