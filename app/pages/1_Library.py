"""Company library: the table over every tracked company (F1), with filters
and sorting (F2).

Reads only from SQLite. The Glassdoor columns are filled by
ingest.load_glassdoor_ratings and the sentiment columns come from
review_summary, and the data-role counts from jobs (ingest.load_jobs). The
turnover columns come from turnover: the proxy from process.turnover_proxy,
published attrition from ingest.load_turnover. Filtering, sorting and
formatting live in jmsa.library; this page only draws the controls and the
table. The source-and-date line under it comes from jmsa.freshness.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app.state import init_state  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from app.ui.components import freshness_note  # noqa: E402
from jmsa.freshness import freshness_notes  # noqa: E402
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
from jmsa.jobs import ROLES_HELP  # noqa: E402
from jmsa.turnover import BASES, BASIS_NAMES, PROXY_HELP, SCOPE_NAMES, SCOPES  # noqa: E402
from jmsa.sentiment import PERIOD_TITLES, PERIODS  # noqa: E402

init_state()

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
def notes() -> dict[str, str]:
    """Each source's short name and date, read from the database."""
    conn = get_conn()
    try:
        return freshness_notes(conn)
    finally:
        conn.close()


st.title("Company library")

# app/app.py has already checked the database exists and has companies.
records = library()

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
        help="Drop companies whose score rests on few reviews.",
    )
    has_data_roles = st.checkbox(
        "Has data roles in the dataset",
        help=ROLES_HELP,
    )
    include_missing = st.toggle(
        "Include companies with no value for a minimum you've set",
        help="Keep companies that have no value for a field you've set a minimum on.",
    )

    st.header("Compare attrition like with like")
    attrition_basis = st.selectbox(
        "Published attrition basis", [ANY, *BASES],
        format_func=lambda v: v if v == ANY else BASIS_NAMES[v],
        help="Voluntary exits, all exits, or not stated by the company.",
    )
    attrition_scope = st.selectbox(
        "Published attrition scope", [ANY, *SCOPES],
        format_func=lambda v: v if v == ANY else SCOPE_NAMES[v],
        help="The whole group, one segment, or the India subsidiary.",
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
    st.info("No companies match these filters.")
    st.stop()

if sort_key == "attrition" and (filters.attrition_basis is None or filters.attrition_scope is None):
    st.caption("Pick a basis and scope to rank like with like.")
headers = column_headers(period)
# The tooltip on both proxy columns, so the proxy is never read without it.
proxy_help = st.column_config.Column(help=PROXY_HELP)
st.dataframe([display_row(record, period) for record in shown], hide_index=True,
             column_config={headers["proxy"]: proxy_help, headers["proxy_split"]: proxy_help,
                            headers["data_roles"]: st.column_config.Column(help=ROLES_HELP)})
freshness_note(notes(), "ratings", "reviews", "roles", "attrition", "proxy")
