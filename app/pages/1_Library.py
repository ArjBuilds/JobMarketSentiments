"""Company library: the table over every tracked company (F1), with filters
and sorting (F2).

Reads only from SQLite. The Glassdoor columns are filled by
ingest.load_glassdoor_ratings and the sentiment columns come from
review_summary, and the data-role counts from jobs (ingest.load_jobs). The
turnover proxy columns come from turnover (process.turnover_proxy). Filtering, sorting and formatting live in jmsa.library; this
page only draws the controls and the table.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.library import (  # noqa: E402
    REVIEW_MINIMUMS,
    SORT_KEYS,
    SORT_LABELS,
    Filters,
    apply,
    display_row,
    load_library,
    minimum_steps,
    sentiment,
)
from jmsa.jobs import LOWER_BOUND_NOTE  # noqa: E402
from jmsa.sentiment import MIN_REVIEWS, PERIOD_TITLES, PERIODS  # noqa: E402

st.set_page_config(page_title="Library · Job Market Analyser", page_icon="📊", layout="wide")

ANY = "Any"


@st.cache_data
def library() -> list[dict]:
    """Every company's raw record. Cached, so a filter change runs no query.

    The result is cached rather than the connection: sqlite3 refuses to use
    a connection from a thread other than the one that opened it, and
    Streamlit may run each visit on a different thread.

    The cache lasts until the app restarts, so restart Streamlit (or press C
    in the page and clear the cache) after reloading the database.
    """
    conn = get_conn()
    try:
        return load_library(conn)
    finally:
        conn.close()


st.title("Company library")

# Checked before connecting, because get_conn would create an empty file.
if not DB_PATH.exists():
    st.warning(
        f"No database at `{DB_PATH}`. Create it and load the library with:\n\n"
        "```bash\npython -m jmsa.db init\npython -m ingest.load_companies\n```"
    )
    st.stop()

records = library()
if not records:
    st.warning(
        "The companies table is empty. Load it with:\n\n"
        "```bash\npython -m ingest.load_companies\n```"
    )
    st.stop()

with st.sidebar:
    st.header("Filter")
    period = st.radio("Review period", list(PERIODS), format_func=PERIOD_TITLES.get, horizontal=True)
    sectors = st.multiselect("Sector", sorted({r["sector"] for r in records}))
    countries = st.multiselect("HQ country", sorted({r["hq_country"] for r in records if r["hq_country"]}))
    # "Any" as the first stop makes "no minimum" explicit, rather than
    # treating the slider's lowest number as off.
    min_rating = st.select_slider(
        "Minimum Glassdoor rating",
        [ANY, *minimum_steps([r["glassdoor_rating"] for r in records], 0.1)],
        format_func=lambda v: v if v == ANY else f"{v:.1f}",
    )
    min_sentiment = st.select_slider(
        "Minimum review sentiment",
        [ANY, *minimum_steps([sentiment(r, p) for r in records for p in PERIODS], 0.05)],
        format_func=lambda v: v if v == ANY else f"{v:+.2f}",
    )
    min_reviews = st.select_slider(
        "Minimum reviews scored",
        REVIEW_MINIMUMS,
        format_func=lambda v: f"{v:,}",
        help=f"{MIN_REVIEWS} is the standing rule: below it a score is hidden. "
             "Raise it to drop companies whose score rests on a small sample.",
    )
    has_data_roles = st.checkbox(
        "Has data roles in the dataset",
        help="Keep only companies with at least one data-science or analytics posting "
             "in the Naukri snapshot.",
    )
    include_missing = st.toggle(
        "Include companies with no value for a minimum you've set",
        help="Off: a company with no rating, no sentiment or no reviews is left out "
             "when you set a minimum on that field. On: it stays in, shown as not available.",
    )

    st.header("Sort")
    sort_key = st.selectbox("Sort by", list(SORT_KEYS), format_func=SORT_LABELS.get)
    descending = st.toggle("Descending")

filters = Filters(
    period=period,
    sectors=tuple(sectors),
    countries=tuple(countries),
    min_rating=None if min_rating == ANY else min_rating,
    min_sentiment=None if min_sentiment == ANY else min_sentiment,
    min_reviews=min_reviews,
    has_data_roles=has_data_roles,
    include_missing=include_missing,
)
shown = apply(records, filters, sort_key, descending)

st.caption(f"{len(shown)} of {len(records)} companies")
if not shown:
    st.info("No companies match these filters. Remove a sector or country, lower a minimum, "
            "or turn on the toggle that includes companies with no value.")
    st.stop()

st.dataframe([display_row(record, period) for record in shown], hide_index=True)
st.caption(
    "Use **Sort** in the sidebar: it sorts by the numbers and always puts \"not available\" last. "
    "Clicking a column header sorts the cells as text. "
    "The Glassdoor rating comes from a ratings snapshot; review sentiment is VADER over a "
    "separate set of review texts, from −1 to +1, so a company can have one without the other. "
    f"Scores based on fewer than {MIN_REVIEWS} reviews are hidden. Reviews end in mid-2023. "
    "Data-role listings are distinct Naukri data-science and analytics listings in India in the "
    "dataset snapshot, collected in or after late October 2023, not roles open now. "
    f"{LOWER_BOUND_NOTE} "
    "The turnover proxy counts reviews whose headline or cons mention people leaving, attrition "
    "or layoffs, per 100 reviews; it is not a share of staff, so it can't be sorted here. "
    "A review can mention both kinds, so the split can add up to more than the total."
)
