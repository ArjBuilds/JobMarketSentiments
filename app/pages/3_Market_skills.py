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

from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.display import NOT_AVAILABLE  # noqa: E402
from jmsa.freshness import naukri_dates  # noqa: E402
from jmsa.skills import (  # noqa: E402
    MARKET_SKILLS_NOTE, MIN_SCORED_POSTINGS, TOP_N, VIEWS,
    read_export_comparison, read_market_skills, read_scope_sizes,
)

st.set_page_config(page_title="Market skills · Job Market Analyser", page_icon="📊", layout="wide")

# One series, so one hue (the palette's first categorical slot) and no legend.
BAR_COLOUR = "#2a78d6"


# Cached results, not connections, for the reason given on the Library page.
@st.cache_data
def snapshot_dates() -> str:
    conn = get_conn()
    try:
        return naukri_dates(conn)
    finally:
        conn.close()


@st.cache_data
def market(view: str) -> dict:
    conn = get_conn()
    try:
        return read_market_skills(conn, view)
    finally:
        conn.close()


@st.cache_data
def comparison(view: str) -> tuple[list[dict], list[dict]]:
    conn = get_conn()
    try:
        return read_export_comparison(conn, view), read_scope_sizes(conn)
    finally:
        conn.close()


def bar_chart(rows: list[dict]) -> go.Figure:
    """Horizontal bars, largest at the top, each labelled with its share."""
    shares = [row["Share"] * 100 for row in rows]
    figure = go.Figure(go.Bar(
        x=shares,
        y=[row["Skill"] for row in rows],
        orientation="h",
        marker={"color": BAR_COLOUR, "cornerradius": 4},
        text=[f"{share:.1f}%" for share in shares],
        textposition="outside",
        cliponaxis=False,
        customdata=[row["Postings"] for row in rows],
        hovertemplate="%{y}: %{x:.1f}% of skill lists (%{customdata:,} lists)<extra></extra>",
    ))
    figure.update_layout(
        height=60 + 42 * len(rows),
        bargap=0.45,               # keeps each bar about 23 px thick
        margin={"l": 10, "r": 40, "t": 10, "b": 40},
        xaxis={"title": "Share of distinct skill lists", "ticksuffix": "%",
               "range": [0, max(shares) * 1.15], "showgrid": True},
        yaxis={"autorange": "reversed", "showgrid": False},
    )
    return figure


st.title("Market skills")
st.markdown("What Indian data-role postings ask for. **Market-wide, not any one company's.**")

# Checked before connecting, because get_conn would create an empty file.
if not DB_PATH.exists():
    st.warning(
        f"No database at `{DB_PATH}`. Create it and count the skills with:\n\n"
        "```bash\npython -m jmsa.db init\npython -m process.skill_counts\n```"
    )
    st.stop()

view = st.radio("Show", list(VIEWS), horizontal=True,
                help="Tools are named products and languages; methods are techniques. "
                     "All three views share one base: every distinct skill list scored.")
skills = market(view)

st.subheader(f"Top {TOP_N} {view.lower() if view != 'All' else 'skills'}")
if not skills["available"]:
    st.markdown(
        f"Market skills: **{NOT_AVAILABLE}**. Fewer than {MIN_SCORED_POSTINGS} skill lists have been "
        "scored. Count them with:\n\n```bash\npython -m process.skill_counts\n```"
    )
else:
    st.plotly_chart(bar_chart(skills["rows"]), width="stretch")
    st.caption(f"Based on {skills['scored']:,} distinct skill lists from the two data-science exports. "
               + MARKET_SKILLS_NOTE + f" Snapshot {snapshot_dates()}.")

    with st.expander("Compare the three exports"):
        rows, sizes = comparison(view)
        st.markdown(
            "Each export's distinct skill lists, counted on their own. The headline pools the two "
            "data-science exports, whose titles are 87–91% data roles, and counts a list found in both "
            "once. The data_analytics export is left out of it: only 38% of its titles are data roles."
        )
        st.dataframe(rows, hide_index=True)
        st.dataframe(sizes, hide_index=True)
