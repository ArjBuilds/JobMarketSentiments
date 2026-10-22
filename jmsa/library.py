"""The company library behind F1 and F2: load, filter, sort and format.

No Streamlit here, so the tests can call every step directly. The Library page
loads the records once (cached), then each widget change reruns apply() and
display_row() over the 82 records in memory. No query per filter.

Values stay numeric until display_row(), so sorting compares numbers rather
than text, and a missing value is None until it becomes "not available".

Milestone 6 added data roles: a count per company, the "has data roles"
filter and a sort. There is no "required skill" filter: the postings' skills
can't be tied to an employer (see PRD.md, "The postings snapshot").
Milestone 8 adds turnover. The proxy is two display-only columns, the total
and its split, and deliberately not a sort key: a share of reviews must never
be ranked as if it were attrition. Published attrition (each company's latest
figure) is a column and a sort key, shown with its basis and scope, and the
basis and scope filters let a ranking compare like with like.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from jmsa.display import NOT_AVAILABLE, show
from jmsa.jobs import ROLES_LABEL, cities_text
from jmsa.sentiment import MIN_REVIEWS, PERIOD_TITLES, hidden, is_shown, score_text
from jmsa.turnover import BASIS_NAMES, SCOPE_NAMES, proxy_parts

# Choices for the minimum-reviews filter. The first is the 20-review rule
# itself, which already hides small samples, so it filters nothing further.
REVIEW_MINIMUMS = (MIN_REVIEWS, 100, 500, 1000, 5000)


@dataclass(frozen=True)
class Filters:
    """What the user has narrowed the library to. The defaults filter nothing."""
    period: str = "all"                 # review_summary period the sentiment figures use
    sectors: tuple[str, ...] = ()       # empty means every sector
    countries: tuple[str, ...] = ()     # empty means every HQ country
    min_rating: float | None = None     # None means no minimum
    min_sentiment: float | None = None
    min_reviews: int = MIN_REVIEWS
    has_data_roles: bool = False        # True keeps only companies with postings in the dataset
    # Keep only companies whose latest published attrition has this basis /
    # scope (None means any, and keeps companies with no figure too).
    attrition_basis: str | None = None
    attrition_scope: str | None = None
    # When a minimum is set, may a company with no value for it stay in?
    include_missing: bool = False


def load_library(conn: sqlite3.Connection) -> list[dict]:
    """One record per company, in name order, with the raw numbers.

    The sentiment of a period is None both when the company has no reviews
    in it and when it has fewer than 20, so the 20-review rule holds for
    every filter and sort. The review count is kept either way, so it can
    still be shown beside the hidden score.
    """
    # A company with no reviews has no review_summary rows, so the LEFT JOIN
    # gives it one row with NULLs; a company with reviews gets one per period.
    # Its data roles are counted once in a subquery and repeat on each row.
    query = """
        SELECT c.company_id, c.name, c.sector, c.hq_country, c.india_cities, c.size_band,
               c.glassdoor_rating, c.glassdoor_review_count, j.roles,
               s.period, s.review_count, s.avg_compound, s.pre_merger_count,
               t.reviews_in_window, t.reviews_matched, t.reviews_leaving, t.reviews_layoffs,
               p.attrition_pct, p.attrition_text, p.basis, p.scope, p.period AS attrition_period
        FROM companies c
        LEFT JOIN review_summary s ON s.company_id = c.company_id
        LEFT JOIN turnover t ON t.company_id = c.company_id AND t.is_proxy = 1
        -- Only the latest published figure; older rows are for the proxy comparison.
        LEFT JOIN turnover p ON p.company_id = c.company_id AND p.is_proxy = 0
               AND p.period_end = (SELECT MAX(period_end) FROM turnover
                                   WHERE company_id = c.company_id AND is_proxy = 0)
        LEFT JOIN (SELECT company_id, COUNT(*) AS roles FROM jobs GROUP BY company_id) j
               ON j.company_id = c.company_id
        ORDER BY c.name COLLATE NOCASE, c.company_id
    """
    records: dict[str, dict] = {}
    for row in conn.execute(query):
        record = records.setdefault(row["company_id"], {
            "company_id": row["company_id"],
            "name": row["name"],
            "sector": row["sector"],
            "hq_country": row["hq_country"],
            "india_cities": row["india_cities"],
            "size_band": row["size_band"],
            "glassdoor_rating": row["glassdoor_rating"],
            "glassdoor_review_count": row["glassdoor_review_count"],
            # None, not 0, when the dataset has no postings: "not available".
            "data_roles": row["roles"],
            # Display text for the turnover proxy, or None with no reviews in its window.
            "proxy": proxy_parts(row) if row["reviews_in_window"] is not None else None,
            # Latest published attrition, None when the company publishes none.
            "attrition": row["attrition_pct"],
            "attrition_text": row["attrition_text"],
            "attrition_basis": row["basis"],
            "attrition_scope": row["scope"],
            "attrition_period": row["attrition_period"],
            "reviews": {},       # period -> scored review count
            "sentiment": {},     # period -> average compound, None if hidden
            "pre_merger": {},    # period -> True if any of the reviews are pre-merger
        })
        period = row["period"]
        if period is None:
            continue
        count = row["review_count"]
        record["reviews"][period] = count
        record["sentiment"][period] = row["avg_compound"] if is_shown(count) else None
        record["pre_merger"][period] = bool(row["pre_merger_count"])
    return list(records.values())


def sentiment(record: dict, period: str) -> float | None:
    return record["sentiment"].get(period)


def reviews(record: dict, period: str) -> int | None:
    return record["reviews"].get(period)


# Sort key -> function giving a record's value for it, None when missing.
SORT_KEYS = {
    "name": lambda record, period: record["name"].casefold(),
    "rating": lambda record, period: record["glassdoor_rating"],
    "sentiment": sentiment,
    "reviews": reviews,
    "data_roles": lambda record, period: record["data_roles"],
    # Published figures only: the proxy never enters this ranking.
    "attrition": lambda record, period: record["attrition"],
}
SORT_LABELS = {
    "name": "Name",
    "rating": "Glassdoor rating",
    "sentiment": "Review sentiment",
    "reviews": "Reviews scored",
    "data_roles": "Data-role listings",
    "attrition": "Published attrition",
}


def meets(value, minimum, include_missing: bool) -> bool:
    """Does a value pass a minimum? Missing values pass only if included."""
    if minimum is None:
        return True
    if value is None:
        return include_missing
    return value >= minimum


def matches(record: dict, filters: Filters) -> bool:
    period = filters.period
    # At the 20-review rule the minimum is already enforced by hiding the
    # score, so it counts as no minimum; it doesn't drop the four companies
    # that have no reviews.
    min_reviews = filters.min_reviews if filters.min_reviews > MIN_REVIEWS else None
    return (
        (not filters.sectors or record["sector"] in filters.sectors)
        and (not filters.countries or record["hq_country"] in filters.countries)
        and meets(record["glassdoor_rating"], filters.min_rating, filters.include_missing)
        and meets(sentiment(record, period), filters.min_sentiment, filters.include_missing)
        and meets(reviews(record, period), min_reviews, filters.include_missing)
        and (not filters.has_data_roles or record["data_roles"] is not None)
        and (filters.attrition_basis is None or record["attrition_basis"] == filters.attrition_basis)
        and (filters.attrition_scope is None or record["attrition_scope"] == filters.attrition_scope)
    )


def apply(records: list[dict], filters: Filters, sort_key: str = "name",
          descending: bool = False) -> list[dict]:
    """The records that pass every filter, sorted, with missing values last.

    Records with no value for the sort key are set aside before sorting and
    added at the end, so they come last in both directions. They keep the
    name order they arrived in, as do ties (Python's sort is stable, even
    with reverse=True).
    """
    value = SORT_KEYS[sort_key]
    kept = [record for record in records if matches(record, filters)]
    present = [record for record in kept if value(record, filters.period) is not None]
    missing = [record for record in kept if value(record, filters.period) is None]
    present.sort(key=lambda record: value(record, filters.period), reverse=descending)
    return present + missing


def minimum_steps(values, step: float) -> list[float]:
    """Slider stops every step from just below the smallest value to just above the largest.

    Worked in whole steps and rounded, so 3.6 is exactly 3.6 and a company
    rated 3.6 passes a minimum of 3.6.
    """
    present = [v for v in values if v is not None]
    if not present:
        return []
    # The 1e-9 stops float error (3.5 / 0.1 = 34.999...) from moving a bound a step.
    low = math.floor(min(present) / step + 1e-9)
    high = math.ceil(max(present) / step - 1e-9)
    return [round(i * step, 2) for i in range(low, high + 1)]


def column_headers(period: str) -> dict[str, str]:
    """Key -> header, in display order. The review headers name the period."""
    title = PERIOD_TITLES[period].lower()
    return {
        "name": "Company",
        "sector": "Sector",
        "hq_country": "HQ country",
        "india_cities": "India cities",
        "size_band": "Size band",
        # The Glassdoor ratings snapshot: a star rating and how many ratings it
        # rests on. A different source from the review text scored below.
        "rating": "Glassdoor rating",
        "rating_count": "Glassdoor ratings",
        "sentiment": f"Review sentiment ({title})",
        "reviews": f"Reviews scored ({title})",
        "data_roles": ROLES_LABEL,
        # Each cell reads "value · basis · scope · period", so the header stays short.
        "attrition": "Published attrition",
        "proxy": "Turnover proxy (per 100 reviews)",
        "proxy_split": "Proxy split (per 100 reviews)",
    }


def attrition_text(record: dict) -> str | None:
    """'12.8% · voluntary · segment · LTM to Sep 2026 (Q2 FY27)', so a figure is never read
    without its definition. None when the company publishes none."""
    if record["attrition"] is None:
        return None
    return " · ".join([f"{record['attrition_text']}%", BASIS_NAMES[record["attrition_basis"]],
                       SCOPE_NAMES[record["attrition_scope"]], record["attrition_period"]])


def display_row(record: dict, period: str) -> dict[str, str]:
    """A record as display text. Every value is text, never None."""
    count = reviews(record, period)
    if count is None:
        score = NOT_AVAILABLE
    elif not is_shown(count):
        score = hidden(count)
    else:
        score = score_text(sentiment(record, period))
        if record["pre_merger"].get(period):
            score += " · pre-merger Mindtree reviews"

    rating, rating_count = record["glassdoor_rating"], record["glassdoor_review_count"]
    roles = record["data_roles"]
    values = {
        "name": record["name"],
        "sector": record["sector"],
        "hq_country": record["hq_country"],
        "india_cities": cities_text(record["india_cities"]),
        "size_band": record["size_band"],
        "rating": f"{rating:.1f}" if rating is not None else None,
        "rating_count": f"{rating_count:,}" if rating_count is not None else None,
        "sentiment": score,
        "reviews": f"{count:,}" if count is not None else None,
        "data_roles": f"{roles:,}" if roles is not None else None,
        "attrition": attrition_text(record),
        "proxy": record["proxy"]["total"] if record["proxy"] else None,
        "proxy_split": record["proxy"]["split"] if record["proxy"] else None,
    }
    return {header: show(values[key]) for key, header in column_headers(period).items()}
