"""Company library: the table over every tracked company (F1), with filters
and sorting (F2).

Reads only from SQLite. The Glassdoor columns are filled by
ingest.load_glassdoor_ratings and the sentiment columns come from
review_summary, and the data-role counts from jobs (ingest.load_jobs). The
turnover columns come from turnover: the proxy from process.turnover_proxy,
published attrition from ingest.load_turnover. Filtering, sorting and
formatting live in jmsa.library; this page only draws the controls and the
table. The source lines and dates under it come from jmsa.freshness.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.freshness import read_freshness, review_end, source_line  # noqa: E402
from jmsa.library import (  # noqa: E402
    REVIEW_MINIMUMS,
    SORT_KEYS,
    SORT_LABELS,
    Filters,
    apply,
    column_headers,
    display_row,
    load_library,
    minimum_steps,
    sentiment,
)
from jmsa.jobs import LOWER_BOUND_NOTE  # noqa: E402
from jmsa.turnover import BASES, BASIS_NAMES, PROXY_CHECK_NOTE, SCOPE_NAMES, SCOPES  # noqa: E402
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


@st.cache_data
def sources() -> tuple[dict, str]:
    """Each source's dates, and when the reviews end, read from the database."""
    conn = get_conn()
    try:
        return read_freshness(conn), review_end(conn)
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

    st.header("Compare attrition like with like")
    attrition_basis = st.selectbox(
        "Published attrition basis", [ANY, *BASES],
        format_func=lambda v: v if v == ANY else BASIS_NAMES[v],
        help="Keep only companies whose latest published figure has this basis. "
             "\"Basis not stated\" means the document doesn't say voluntary or total.",
    )
    attrition_scope = st.selectbox(
        "Published attrition scope", [ANY, *SCOPES],
        format_func=lambda v: v if v == ANY else SCOPE_NAMES[v],
        help="Keep only companies whose latest published figure covers this: the group, one "
             "segment of it, or its listed India subsidiary.",
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
    attrition_basis=None if attrition_basis == ANY else attrition_basis,
    attrition_scope=None if attrition_scope == ANY else attrition_scope,
)
shown = apply(records, filters, sort_key, descending)

st.caption(f"{len(shown)} of {len(records)} companies")
if not shown:
    st.info("No companies match these filters. Remove a sector or country, lower a minimum, "
            "or turn on the toggle that includes companies with no value.")
    st.stop()

if sort_key == "attrition" and (filters.attrition_basis is None or filters.attrition_scope is None):
    st.warning("Published attrition figures use different definitions and cover different entities, "
               "as each cell says. Choose a basis and a scope under \"Compare attrition like with "
               "like\" to rank only comparable figures.")
freshness, reviews_end = sources()
headers = column_headers(period)
# The tooltip on both proxy columns, so the proxy is never read without it.
proxy_help = st.column_config.Column(help=PROXY_CHECK_NOTE)
st.dataframe([display_row(record, period) for record in shown], hide_index=True,
             column_config={headers["proxy"]: proxy_help, headers["proxy_split"]: proxy_help})
st.caption(
    "Use **Sort** in the sidebar: it sorts by the numbers and always puts \"not available\" last. "
    "Clicking a column header sorts the cells as text. "
    "The Glassdoor rating comes from a ratings snapshot; review sentiment is VADER over a "
    "separate set of review texts, from −1 to +1, so a company can have one without the other. "
    f"Scores based on fewer than {MIN_REVIEWS} reviews are hidden. Reviews end {reviews_end}. "
    "Data-role listings are distinct Naukri data-science and analytics listings in India in the "
    "dataset snapshot, not roles open now. "
    f"{LOWER_BOUND_NOTE} "
    "Published attrition is each company's latest figure from its own reports; the proxy is never "
    "part of that ranking. "
    "The turnover proxy counts reviews whose headline or cons mention people leaving, attrition "
    "or layoffs, per 100 reviews; it is not a share of staff, so it can't be sorted here. "
    "A review can mention both kinds, so the split can add up to more than the total. "
    f"{PROXY_CHECK_NOTE}"
)
st.caption("  \n".join(source_line(freshness, key) for key in ("ratings", "reviews", "roles", "attrition", "proxy")))
