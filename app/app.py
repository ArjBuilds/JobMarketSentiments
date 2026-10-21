"""Job Market Analyser dashboard entry point.

Run from the repo root:  streamlit run app/app.py
"""

import sys
from pathlib import Path

# Streamlit puts this script's own directory on sys.path, not the repo root,
# so `import jmsa` needs the root added first. Only needed here: the ingest
# and process steps run as `python -m ...` from the root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import streamlit as st  # noqa: E402

from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn, table_counts  # noqa: E402
from jmsa.freshness import freshness_table, read_freshness  # noqa: E402

st.set_page_config(page_title="Job Market Analyser", page_icon="📊", layout="wide")


# Cached results, not a connection: sqlite3 refuses to use a connection from
# a thread other than the one that opened it, and Streamlit may run each
# visit on a different thread. Restart Streamlit (or press C) after
# reloading the database.
@st.cache_data
def overview() -> tuple[dict, dict]:
    conn = get_conn()
    try:
        return read_freshness(conn), table_counts(conn)
    finally:
        conn.close()


st.title("Job Market Analyser")
st.caption(
    "Employee sentiment, turnover, news coverage, in-demand skills and the "
    "India data roles posted in a dataset snapshot, for a curated library of large employers."
)

# Checked before connecting, because get_conn would create an empty file.
if not DB_PATH.exists():
    st.warning(
        f"No database at `{DB_PATH}`. Create an empty one with:\n\n"
        "```bash\npython -m jmsa.db init\n```\n\nthen run the loaders in the order the README gives."
    )
    st.stop()

freshness, counts = overview()

st.markdown(
    "- **Library**: every company in one table, with filters and sorting.\n"
    "- **Company**: everything known about one employer.\n"
    "- **Market skills**: the skills Indian data-role postings ask for, market-wide.\n"
    "- **Compare**: 2 to 4 companies side by side.\n"
    "- **About and methods**: sources, licences, how matching works and what the figures can't tell you."
)

st.subheader("Data sources and freshness")
st.dataframe(freshness_table(freshness), hide_index=True)
st.caption("Dates are read from the database, so they change when the loaders are rerun. "
           "The dashboard never calls a live source.")

with st.expander("Database row counts"):
    st.write(f"Reading `{DB_PATH}`.")
    st.dataframe([{"Table": table, "Rows": f"{rows:,}"} for table, rows in counts.items()], hide_index=True)
    if not counts["companies"]:
        st.info("The companies table is empty. Load it with `python -m ingest.load_companies`.")
