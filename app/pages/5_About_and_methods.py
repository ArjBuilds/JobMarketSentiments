"""About the data: each source, what it is used for and its dates, plus a
short "How scores work" note.

Reads only from SQLite, for the dates (jmsa.freshness.sources_rows). The full
method, licences and caveats are in docs/methods.md, not on the page.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app.state import init_state  # noqa: E402
from app.ui.components import static_table  # noqa: E402
from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.freshness import sources_rows  # noqa: E402
from jmsa.jobs import ROLES_HELP  # noqa: E402
from jmsa.sentiment import MIN_REVIEWS, NEGATIVE_AT, POSITIVE_AT  # noqa: E402
from jmsa.turnover import PROXY_HELP  # noqa: E402

init_state()


# Cached results, not connections, for the reason given on the Library page.
@st.cache_data
def sources() -> list[dict[str, str]]:
    conn = get_conn()
    try:
        return sources_rows(conn)
    finally:
        conn.close()


st.title("About the data")
st.caption("Where every figure comes from; nothing is fetched live.")

# The one page that opens without a database (app/app.py lets it through).
# Checked before connecting, because get_conn would create an empty file.
with st.container(border=True):
    st.markdown("**Sources**")
    if DB_PATH.exists():
        static_table(sources())
    else:
        st.warning(f"No database at `{DB_PATH}`, so the sources' dates can't be shown.")

with st.expander("How scores work"):
    st.markdown(
        f"- **Sentiment**: VADER, from −1 to +1. Positive at {POSITIVE_AT:+.2f} or more, "
        f"Negative at {NEGATIVE_AT:+.2f} or less.\n"
        f"- **Fewer than {MIN_REVIEWS} reviews**: the score is hidden; the count is still shown.\n"
        f"- **Turnover proxy**: {PROXY_HELP}\n"
        f"- **Data-role listings**: {ROLES_HELP}"
    )
