"""Explore: the table over every tracked company (F1), with filters and
sorting (F2). Clicking a row opens that company's page.

Reads only from SQLite. The Glassdoor columns are filled by
ingest.load_glassdoor_ratings, the sentiment columns come from
review_summary, the data-role counts from jobs (ingest.load_jobs), and the
turnover columns from turnover. Filtering, sorting and formatting live in
jmsa.library; this page only draws the controls and the table.

The filters live in st.session_state.filters (app.state), not only in the
widgets, because Streamlit deletes a widget's value when the user leaves its
page. Each visit refills the widgets from that dict and writes them back, so
the filters survive a trip to Company or Compare and back.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.state import default_filters, init_state  # noqa: E402
from app.ui.charts import SENTIMENT_COLOURS  # noqa: E402
from app.ui.components import PAGES, empty_state, freshness_note  # noqa: E402
from jmsa.compare import MAX_COMPANIES  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.freshness import freshness_notes  # noqa: E402
from jmsa.jobs import ROLES_HELP  # noqa: E402
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
from jmsa.sentiment import PERIOD_TITLES, PERIODS, label  # noqa: E402
from jmsa.turnover import BASES, BASIS_NAMES, PROXY_HELP, SCOPE_NAMES, SCOPES  # noqa: E402

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


# --- filters that survive leaving the page ------------------------------------

# How a stored filter maps to its widget's value and back. The minimum
# sliders and attrition boxes show "Any" where the filter stores None;
# multiselects want a list where Filters stores a tuple.
NONE_AS_ANY = ("min_rating", "min_sentiment", "attrition_basis", "attrition_scope")
TO_WIDGET = {**{name: (lambda v: ANY if v is None else v) for name in NONE_AS_ANY},
             "sectors": list, "countries": list}
FROM_WIDGET = {**{name: (lambda v: None if v == ANY else v) for name in NONE_AS_ANY},
               "sectors": tuple, "countries": tuple}


def widget_key(name: str) -> str:
    """The filter widget's key, refilled from the stored filters if Streamlit dropped it."""
    key = f"filter_{name}"
    if key not in st.session_state:
        st.session_state[key] = TO_WIDGET.get(name, lambda v: v)(st.session_state.filters[name])
    return key


def store_filters() -> None:
    """Copy every filter widget's value back into the stored filters."""
    st.session_state.filters = {
        name: FROM_WIDGET.get(name, lambda v: v)(st.session_state[f"filter_{name}"])
        for name in st.session_state.filters
    }


def clear_filters() -> None:
    """Back to filtering nothing. A button callback, so it runs before the widgets are drawn."""
    st.session_state.filters = default_filters()
    for name in st.session_state.filters:
        st.session_state.pop(f"filter_{name}", None)


def store_compare() -> None:
    st.session_state.compare_ids = list(st.session_state.explore_compare)


st.title("Explore companies")
st.caption("Large employers that hire in India: filter, sort and open any company.")

# app/app.py has already checked the database exists and has companies.
records = library()
names = {r["company_id"]: r["name"] for r in records}

sector_col, country_col, sentiment_col, roles_col, sort_col, order_col = st.columns(
    [3, 2.5, 2, 1.6, 2, 1.2], vertical_alignment="bottom")
with sector_col:
    st.multiselect("Sector", sorted({r["sector"] for r in records}), key=widget_key("sectors"))
with country_col:
    st.multiselect("HQ country", sorted({r["hq_country"] for r in records if r["hq_country"]}),
                   key=widget_key("countries"))
with sentiment_col:
    # "Any" as the first stop makes "no minimum" explicit, rather than
    # treating the slider's lowest number as off.
    st.select_slider("Min sentiment",
                     [ANY, *minimum_steps([sentiment(r, p) for r in records for p in PERIODS], 0.05)],
                     format_func=lambda v: v if v == ANY else f"{v:+.2f}", key=widget_key("min_sentiment"))
with roles_col:
    st.toggle("Has data roles", key=widget_key("has_data_roles"), help=ROLES_HELP)
with sort_col:
    st.selectbox("Sort by", list(SORT_KEYS), format_func=SORT_LABELS.get, key=widget_key("sort"))
with order_col:
    st.toggle("Descending", key=widget_key("descending"))

with st.expander("More filters"):
    period_col, rating_col, reviews_col = st.columns(3)
    with period_col:
        st.radio("Review period", list(PERIODS), format_func=PERIOD_TITLES.get, horizontal=True,
                 key=widget_key("period"))
    with rating_col:
        st.select_slider("Min Glassdoor rating",
                         [ANY, *minimum_steps([r["glassdoor_rating"] for r in records], 0.1)],
                         format_func=lambda v: v if v == ANY else f"{v:.1f}", key=widget_key("min_rating"))
    with reviews_col:
        st.select_slider("Min reviews scored", REVIEW_MINIMUMS, format_func=lambda v: f"{v:,}",
                         key=widget_key("min_reviews"), help="Drop companies whose score rests on few reviews.")
    basis_col, scope_col, missing_col = st.columns(3)
    with basis_col:
        st.selectbox("Attrition basis", [ANY, *BASES], format_func=lambda v: v if v == ANY else BASIS_NAMES[v],
                     key=widget_key("attrition_basis"), help="Voluntary exits, all exits, or not stated.")
    with scope_col:
        st.selectbox("Attrition scope", [ANY, *SCOPES], format_func=lambda v: v if v == ANY else SCOPE_NAMES[v],
                     key=widget_key("attrition_scope"), help="The whole group, one segment, or the India subsidiary.")
    with missing_col:
        st.toggle("Include companies with no value", key=widget_key("include_missing"),
                  help="Keep companies that have no value for a minimum you've set.")
store_filters()

chosen = st.session_state.filters
filters = Filters(**{name: chosen[name] for name in Filters.__dataclass_fields__})
period = filters.period
shown = apply(records, filters, chosen["sort"], chosen["descending"])

if not shown:
    empty_state("No companies match these filters.", "Clear filters", on_click=clear_filters)
    st.stop()

count_col, clear_col = st.columns([5, 1], vertical_alignment="center")
with count_col:
    st.caption(f"{len(shown)} of {len(records)} companies")
with clear_col:
    st.button("Clear filters", on_click=clear_filters, width="stretch")

if chosen["sort"] == "attrition" and (filters.attrition_basis is None or filters.attrition_scope is None):
    st.caption("Pick an attrition basis and scope under More filters to rank like with like.")

# The compare list lives in st.session_state.compare_ids, which the Company
# and Compare pages change too. The picker is refilled from it on every run
# and writes back only when the user changes it (on_change), so it never
# shows a stale list.
st.session_state.explore_compare = list(st.session_state.compare_ids)
pick_col, go_col = st.columns([5, 1], vertical_alignment="bottom")
with pick_col:
    st.multiselect("Compare list", list(names), format_func=names.get, max_selections=MAX_COMPANIES,
                   key="explore_compare", on_change=store_compare, placeholder="Add companies to compare")
with go_col:
    st.page_link(PAGES["compare"], label=f"Compare ({len(st.session_state.compare_ids)})",
                 icon=":material/compare_arrows:")

headers = column_headers(period)


def sentiment_colours(column: pd.Series) -> list[str]:
    """Text colour for each sentiment cell, from the number, never by parsing the text.
    A hidden or missing score keeps the default colour."""
    colours = []
    for record in shown:
        score = sentiment(record, period)
        colours.append(f"color: {SENTIMENT_COLOURS[label(score)]}" if score is not None else "")
    return colours


table = pd.DataFrame([display_row(record, period) for record in shown])
event = st.dataframe(
    table.style.apply(sentiment_colours, subset=[headers["sentiment"]]),
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    key="explore_table",
    column_order=[headers[key] for key in ("name", "sector", "hq_country", "india_cities", "rating",
                                           "sentiment", "reviews", "data_roles", "attrition", "proxy")],
    column_config={
        headers["rating"]: st.column_config.Column(help="From a Glassdoor ratings snapshot."),
        headers["sentiment"]: st.column_config.Column(help="VADER score from −1 to +1."),
        headers["data_roles"]: st.column_config.Column(help=ROLES_HELP),
        headers["attrition"]: st.column_config.Column(help="Latest figure · basis · scope · period."),
        headers["proxy"]: st.column_config.Column(help=PROXY_HELP),
    },
)

# A click on a row opens that company. The table's selection is dropped when
# the page is left, so coming back shows nothing selected.
if event.selection.rows:
    st.session_state.selected_company = shown[event.selection.rows[0]]["company_id"]
    st.switch_page(PAGES["company"])

st.caption("Click a row to open the company.")
freshness_note(notes(), "ratings", "reviews", "roles", "attrition", "proxy")
