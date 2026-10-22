"""Compare page: 2-4 companies side by side in one table (F9).

Reads only from SQLite. The table is built by jmsa.compare from the same
records and formatting as the Explore page (jmsa.library) and the same news
reader as the Company page (jmsa.news), so labels and "Not available" match
both. The theme chart uses jmsa.sentiment.summary_numbers, as the Company
page does.

The companies are st.session_state.compare_ids, the list built on Explore and
the Company page, so this page shows whatever was added there.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.state import init_state, remove_from_compare  # noqa: E402
from app.ui.charts import SENTIMENT_COLOURS, theme_groups  # noqa: E402
from app.ui.components import PAGES, empty_state, freshness_note, open_company  # noqa: E402
from jmsa.compare import MAX_COMPANIES, MIN_COMPANIES, compare_table  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.freshness import freshness_notes  # noqa: E402
from jmsa.library import column_headers, load_library, sentiment  # noqa: E402
from jmsa.news import read_news  # noqa: E402
from jmsa.sentiment import PERIODS, label, summary_numbers  # noqa: E402

init_state()


# Cached results, not connections, for the reason given on the Explore page.
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
def themes(company_id: str) -> list[dict] | None:
    """The company's all-time theme scores, or None with no reviews."""
    conn = get_conn()
    try:
        numbers = summary_numbers(conn, company_id)["all"]
        return numbers["themes"] if numbers else None
    finally:
        conn.close()


@st.cache_data
def notes() -> dict[str, str]:
    conn = get_conn()
    try:
        return freshness_notes(conn)
    finally:
        conn.close()


def store_compare() -> None:
    st.session_state.compare_ids = list(st.session_state.compare_pick)


st.title("Compare companies")
st.caption(f"Up to {MAX_COMPANIES} companies side by side.")

# app/app.py has already checked the database exists and has companies.
records = library()
by_id = {r["company_id"]: r for r in records}
names = {company_id: record["name"] for company_id, record in by_id.items()}

# Refilled from compare_ids on every run, written back only when the user
# changes it, like the picker on Explore.
st.session_state.compare_pick = [c for c in st.session_state.compare_ids if c in by_id]
st.multiselect("Companies", list(names), format_func=names.get, max_selections=MAX_COMPANIES,
               key="compare_pick", on_change=store_compare, placeholder="Add companies to compare",
               label_visibility="collapsed")

picked = st.session_state.compare_pick
if len(picked) < MIN_COMPANIES:
    message = ("Your compare list is empty." if not picked
               else f"Add one more company to compare with {names[picked[0]]}.")
    empty_state(message, "Go to Explore", PAGES["explore"])
    st.stop()

# One box per company: its name opens its page, and a button drops it.
for column, company_id in zip(st.columns(len(picked)), picked):
    with column, st.container(border=True):
        if st.button(names[company_id], key=f"open_{company_id}", type="tertiary",
                     icon=":material/arrow_forward:", help="Open this company's page"):
            open_company(company_id)
        st.button("Remove", key=f"remove_{company_id}", on_click=remove_from_compare, args=(company_id,),
                  icon=":material/close:")

table = pd.DataFrame(compare_table(records, {company_id: news(company_id) for company_id in picked}, picked))


def sentiment_colours(frame: pd.DataFrame) -> pd.DataFrame:
    """Colour each sentiment cell from its score, as on Explore; every other cell stays plain."""
    styles = pd.DataFrame("", index=frame.index, columns=frame.columns)
    for period in PERIODS:
        row = frame.index[frame["Metric"] == column_headers(period)["sentiment"]][0]
        for company_id in picked:
            score = sentiment(by_id[company_id], period)
            if score is not None:
                styles.loc[row, names[company_id]] = f"color: {SENTIMENT_COLOURS[label(score)]}"
    return styles


st.dataframe(table.style.apply(sentiment_colours, axis=None), hide_index=True)

with st.container(border=True):
    st.markdown("**Sentiment by theme**")
    scored = [(names[company_id], themes(company_id)) for company_id in picked]
    missing = [name for name, company_themes in scored if company_themes is None]
    shown = [(name, company_themes) for name, company_themes in scored if company_themes is not None]
    if shown:
        st.plotly_chart(theme_groups(shown), width="stretch", key="theme_groups")
    if missing:
        st.caption(f"Not available: {', '.join(missing)}")

freshness_note(notes(), "ratings", "reviews", "roles", "attrition", "proxy", "news")
