"""Shortlist dashboard entry point: the router every page runs through.

Run from the repo root:  streamlit run app/app.py

st.navigation, not the pages/ folder, decides each page's title, icon, URL
and order. This file runs on every visit before the page does, so it is the
one place that sets up shared state (app.state), draws the sidebar, and
checks the database is there.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Streamlit puts this script's own directory on sys.path, not the repo root,
# so `import jmsa` and `import app` need the root added first. Only needed
# here and in the pages: the ingest and process steps run as `python -m ...`
# from the root.
sys.path.insert(0, str(ROOT))

# A fresh clone has no data/jmsa.db (770 MB, gitignored), only the committed
# data/demo.db. Point the dashboard at it then, before jmsa.config reads
# JMSA_DB_PATH. Only the dashboard does this, so a loader never writes into
# the demo copy. An explicit JMSA_DB_PATH always wins.
if (not os.getenv("JMSA_DB_PATH") and not (ROOT / "data" / "jmsa.db").exists()
        and (ROOT / "data" / "demo.db").exists()):
    os.environ["JMSA_DB_PATH"] = str(ROOT / "data" / "demo.db")

import streamlit as st  # noqa: E402

from app.state import init_state  # noqa: E402
from app.ui.components import PAGES  # noqa: E402
from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.freshness import last_refreshed  # noqa: E402

# The sidebar starts collapsed so Explore opens on its content; Explore's
# caption above the table points to the filters inside it.
st.set_page_config(page_title="Shortlist", page_icon="📊", layout="wide",
                   initial_sidebar_state="collapsed")
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

page = st.navigation({"Shortlist": [explore, company, compare, skills, about]})

with st.sidebar:
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
