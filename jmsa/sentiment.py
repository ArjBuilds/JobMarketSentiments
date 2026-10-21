"""How a sentiment score is labelled, combined and shown.

One definition for the loaders, the process steps and the dashboard:

    label()         the standard VADER cut-offs (positive >= 0.05, negative <= -0.05)
    combine()       a review's score from its three separately scored parts
    read_summary()  a company's review figures, ready to display, with the
                    20-review rule and the missing-data rule already applied
"""

from __future__ import annotations

import sqlite3

from jmsa.display import NOT_AVAILABLE

POSITIVE_AT = 0.05
NEGATIVE_AT = -0.05

# Below this many scored reviews a figure is hidden rather than shown.
MIN_REVIEWS = 20

# Fixed by the PRD. The keywords for each live in data/themes.csv; the names
# here are also column names (reviews.theme_pay, review_summary.pay_count).
THEMES = ("pay", "culture", "wlb", "management")
THEME_NAMES = {"pay": "Pay", "culture": "Culture", "wlb": "Work-life balance", "management": "Management"}

# period -> (first day, last day), or None for every review. A review with no
# date is in "all" but can't be placed in a date range.
PERIODS = {"all": None, "2020-2023": ("2020-01-01", "2023-12-31")}
PERIOD_TITLES = {"all": "All time", "2020-2023": "2020–2023"}

MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def label(compound: float | None) -> str | None:
    """positive / neutral / negative by the standard VADER cut-offs."""
    if compound is None:
        return None
    if compound >= POSITIVE_AT:
        return "positive"
    if compound <= NEGATIVE_AT:
        return "negative"
    return "neutral"


def mean(values) -> float | None:
    """Average of the values that aren't None; None if there are none."""
    present = [v for v in values if v is not None]
    return sum(present) / len(present) if present else None


def combine(headline: float | None, pros: float | None, cons: float | None) -> float | None:
    """A review's score: mean(headline, mean(pros, cons)).

    Each argument is that part's VADER compound, or None if the part has no
    text. Pros and cons are averaged first because Glassdoor makes pros
    positive and cons negative by design: their average is the review's net
    view, with the cons' negative sign doing the subtracting. Missing parts
    are skipped, and a review with no text at all gets None, not 0.
    """
    return mean([headline, mean([pros, cons])])


def month_year(iso_date: str | None) -> str | None:
    """'2023-04-19' -> 'Apr 2023'."""
    if not iso_date:
        return None
    return f"{MONTHS[int(iso_date[5:7]) - 1]} {iso_date[:4]}"


def is_shown(count: int) -> bool:
    """The 20-review rule: is a figure based on count reviews shown at all?"""
    return count >= MIN_REVIEWS


def hidden(count: int) -> str:
    return f"hidden: fewer than {MIN_REVIEWS} reviews ({count})"


def score_text(compound: float) -> str:
    return f"{compound:+.2f} ({label(compound)})"


def period_view(period: str, row: sqlite3.Row | None) -> dict:
    """Display strings for one period. Every value is text, never None."""
    view = {"title": PERIOD_TITLES[period]}
    if row is None:
        view.update(range=NOT_AVAILABLE, reviews=NOT_AVAILABLE, average=NOT_AVAILABLE,
                    shares=NOT_AVAILABLE, themes=[])
        return view

    count = row["review_count"]
    first, last = month_year(row["first_date"]), month_year(row["last_date"])
    view["range"] = f"{first} – {last}" if first and last else NOT_AVAILABLE
    # The count is always shown, even when the score is hidden, so a thin
    # sample (intuit has 22) is never presented without its size.
    view["reviews"] = f"{count:,}"
    shown = is_shown(count)
    view["average"] = score_text(row["avg_compound"]) if shown else hidden(count)
    view["shares"] = (
        f"{row['share_positive']:.0%} positive · {row['share_neutral']:.0%} neutral · "
        f"{row['share_negative']:.0%} negative"
    ) if shown else hidden(count)

    view["themes"] = []
    for theme in THEMES:
        mentions = row[f"{theme}_count"] or 0
        compound = row[f"{theme}_compound"]
        view["themes"].append({
            "Theme": THEME_NAMES[theme],
            "Reviews mentioning": f"{mentions:,}",
            "Score": score_text(compound) if is_shown(mentions) else hidden(mentions),
        })
    return view


def read_summary(conn: sqlite3.Connection, company_id: str) -> dict:
    """A company's review figures from review_summary, ready to display.

    available is False when the company has no scored reviews at all; every
    figure then reads "not available". note carries the pre-merger warning.
    """
    rows = {
        row["period"]: row
        for row in conn.execute("SELECT * FROM review_summary WHERE company_id = ?", (company_id,))
    }
    note = None
    everything = rows.get("all")
    if everything is not None and everything["pre_merger_count"]:
        pre, total = everything["pre_merger_count"], everything["review_count"]
        share = "All" if pre == total else f"{pre:,} of"
        note = (f"{share} {total:,} reviews are from Mindtree, before its 2022 merger "
                "into LTIMindtree, and describe the pre-merger company.")
    return {
        "available": everything is not None,
        "note": note,
        "periods": [period_view(period, rows.get(period)) for period in PERIODS],
    }
