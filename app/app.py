"""Job Market Analyser dashboard entry point: the router every page runs through.

Run from the repo root:  streamlit run app/app.py

st.navigation, not the pages/ folder, decides each page's title, icon, URL
and order. This file runs on every visit before the page does, so it is the
one place that sets up shared state (app.state), draws the sidebar, and
checks the database is there.
"""

import sys
from pathlib import Path

# Streamlit puts this script's own directory on sys.path, not the repo root,
# so `import jmsa` and `import app` need the root added first. Only needed
# here and in the pages: the ingest and process steps run as `python -m ...`
# from the root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from app.state import init_state  # noqa: E402
from app.ui.components import PAGES  # noqa: E402
from jmsa.compare import MAX_COMPANIES  # noqa: E402
from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.freshness import last_refreshed  # noqa: E402

st.set_page_config(page_title="Job Market Analyser", page_icon="📊", layout="wide")
init_state()

# File paths come from app.ui.components.PAGES, which links and
# st.switch_page use too, relative to this file.
explore = st.Page(PAGES["explore"], title="Explore", icon=":material/search:", default=True)
company = st.Page(PAGES["company"], title="Company", icon=":material/business:", url_path="company")
skills = st.Page(PAGES["market_skills"], title="Market skills", icon=":material/bar_chart:",
                 url_path="market-skills")
compare = st.Page(PAGES["compare"], title="Compare", icon=":material/compare_arrows:", url_path="compare")
about = st.Page(PAGES["about"], title="About the data", icon=":material/info:", url_path="about")


# Cached results, not a connection: sqlite3 refuses to use a connection from
# a thread other than the one that opened it, and Streamlit may run each
# visit on a different thread. Restart Streamlit (or press C) after
# reloading the database.
@st.cache_data
def database_status() -> tuple[int, str]:
    """How many companies are loaded, and the newest pipeline date."""
    conn = get_conn()
    try:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'companies'").fetchone():
            return 0, ""
        return conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0], last_refreshed(conn)
    finally:
        conn.close()


# Checked before connecting, because get_conn would create an empty file.
if not DB_PATH.exists():
    problem = f"There is no database at `{DB_PATH}`."
    refreshed = None
else:
    loaded, refreshed = database_status()
    problem = None if loaded else f"The database at `{DB_PATH}` has no companies loaded."

page = st.navigation({"Job Market Analyser": [explore, company, skills, compare, about]})

with st.sidebar:
    st.caption(f"Compare list: {len(st.session_state.compare_ids)} of {MAX_COMPANIES}")
    if refreshed:
        st.page_link(about, label=f"Data last refreshed: {refreshed}", icon=":material/update:",
                     help="Each source's own dates are on About the data.")

# Every page but About needs the database. About's methods text doesn't, so
# it still opens and says which dates it can't show.
if problem and page.url_path != about.url_path:
    st.error(
        f"{problem} Build it from the repo root with the venv active:\n\n"
        "```bash\npython -m jmsa.db init\npython -m ingest.load_companies\n```\n\n"
        "then run the remaining loaders in the order the README's \"Build the database\" section "
        "gives, and restart Streamlit."
    )
    st.stop()

page.run()
