"""Market skills page: the data-role skills Indian postings list, market-wide (F7).

Reads only from SQLite. The counts come from skill_counts, filled by
process.skill_counts; what is read and when the chart is hidden live in
jmsa.skills, not here. No company appears on this page: the postings source
doesn't tie skills to an employer.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import plotly.graph_objects as go  # noqa: E402
import streamlit as st  # noqa: E402

from app.state import init_state  # noqa: E402
from app.ui.charts import ACCENT, TEMPLATE  # noqa: E402
from app.ui.components import freshness_note  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.display import NOT_AVAILABLE  # noqa: E402
from jmsa.freshness import freshness_notes  # noqa: E402
from jmsa.skills import MARKET_SKILLS_LABEL, TOP_N, VIEWS, read_market_skills  # noqa: E402

init_state()


# Cached results, not connections, for the reason given on the Library page.
@st.cache_data
def notes() -> dict[str, str]:
    conn = get_conn()
    try:
        return freshness_notes(conn)
    finally:
        conn.close()


@st.cache_data
def market(view: str) -> dict:
    conn = get_conn()
    try:
        return read_market_skills(conn, view)
    finally:
        conn.close()


def bar_chart(rows: list[dict]) -> go.Figure:
    """Horizontal bars, largest at the top, each labelled with its share.

    One series, so one colour (the accent) and no legend; the shared
    template sets the background, margins and bar shape.
    """
    shares = [row["Share"] * 100 for row in rows]
    figure = go.Figure(go.Bar(
        x=shares,
        y=[row["Skill"] for row in rows],
        orientation="h",
        marker={"color": ACCENT},
        text=[f"{share:.1f}%" for share in shares],
        textposition="outside",
        cliponaxis=False,
        customdata=[row["Postings"] for row in rows],
        hovertemplate="%{y}: %{x:.1f}% of skill lists (%{customdata:,} lists)<extra></extra>",
    ))
    figure.update_layout(
        template=TEMPLATE,
        height=60 + 42 * len(rows),
        xaxis={"title": "Share of postings' skill lists", "ticksuffix": "%",
               "range": [0, max(shares) * 1.15], "showgrid": True},
        yaxis={"autorange": "reversed", "showgrid": False},
    )
    return figure


st.title("Market skills")
st.caption(MARKET_SKILLS_LABEL)

view = st.radio("Skill type", list(VIEWS), horizontal=True,
                help="Tools are named products and languages; methods are techniques.")
skills = market(view)

with st.container(border=True):
    st.markdown(f"**Top {TOP_N} {view.lower() if view != 'All' else 'skills'}**")
    if not skills["available"]:
        st.markdown(f"**{NOT_AVAILABLE}**")
    else:
        st.plotly_chart(bar_chart(skills["rows"]), width="stretch", key="skills_chart")
    freshness_note(notes(), "skills")
