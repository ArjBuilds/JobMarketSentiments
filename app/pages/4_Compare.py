"""Compare page: 2-4 companies side by side in one table (F9).

Reads only from SQLite. The table is built by jmsa.compare from the same
records and formatting as the Library page (jmsa.library) and the same news
reader as the Company page (jmsa.news), so labels, caveats and "not
available" match both. This page only draws the picker and the table.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from jmsa.compare import MAX_COMPANIES, MIN_COMPANIES, compare_table  # noqa: E402
from app.state import init_state  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.freshness import freshness_table, read_freshness, review_end  # noqa: E402
from jmsa.jobs import LOWER_BOUND_NOTE  # noqa: E402
from jmsa.library import load_library  # noqa: E402
from jmsa.news import NEWS_NOTE, read_news  # noqa: E402
from jmsa.sentiment import MIN_REVIEWS  # noqa: E402
from jmsa.turnover import PROXY_CHECK_NOTE, PUBLISHED_NOTE  # noqa: E402

init_state()


# Cached results, not connections, for the reason given on the Library page.
@st.cache_data
def library() -> list[dict]:
    conn = get_conn()
    try:
        return load_library(conn)
    finally:
        conn.close()


@st.cache_data
def news(company_id: str) -> dict:
    conn = get_conn()
    try:
        return read_news(conn, company_id)
    finally:
        conn.close()


@st.cache_data
def sources() -> tuple[dict, str]:
    conn = get_conn()
    try:
        return read_freshness(conn), review_end(conn)
    finally:
        conn.close()


st.title("Compare companies")

# app/app.py has already checked the database exists and has companies.
records = library()

names = {r["company_id"]: r["name"] for r in records}
picked = st.multiselect(f"Companies ({MIN_COMPANIES} to {MAX_COMPANIES})", list(names),
                        format_func=names.get, max_selections=MAX_COMPANIES)
if len(picked) < MIN_COMPANIES:
    st.info(f"Pick {MIN_COMPANIES} to {MAX_COMPANIES} companies to compare.")
    st.stop()

st.dataframe(compare_table(records, {company_id: news(company_id) for company_id in picked}, picked),
             hide_index=True)

freshness, reviews_end = sources()
st.caption(
    "The Glassdoor rating comes from a ratings snapshot; review sentiment is VADER over a separate set "
    "of review texts, from −1 to +1, so a company can have one without the other. "
    f"Scores based on fewer than {MIN_REVIEWS} reviews are hidden, and the review count is always "
    f"shown beside a score. Reviews end {reviews_end}. "
    "Data-role listings are distinct Naukri data-science and analytics listings in India in the "
    f"dataset snapshot, not roles open now. {LOWER_BOUND_NOTE} "
    f"{PUBLISHED_NOTE} "
    "The turnover proxy counts reviews whose headline or cons mention people leaving, attrition or "
    f"layoffs, per 100 reviews; it is not a share of staff. {PROXY_CHECK_NOTE} "
    f"{NEWS_NOTE}"
)

with st.expander("Sources and dates"):
    st.dataframe(freshness_table(freshness), hide_index=True)
