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

st.set_page_config(page_title="Job Market Analyser", page_icon="📊", layout="wide")


@st.cache_resource
def connection():
    # check_same_thread is left at its default; Streamlit reruns this script on
    # one thread per session and the cached connection is read-only here.
    return get_conn()


st.title("Job Market Analyser")
st.caption(
    "Employee sentiment, turnover, news coverage, in-demand skills and open "
    "India roles for a curated library of large employers."
)

if not DB_PATH.exists():
    st.warning(
        f"No database at `{DB_PATH}`. Create an empty one with:\n\n"
        "```bash\npython -m jmsa.db init\n```"
    )
    st.stop()

st.subheader("Database")
st.write(f"Reading `{DB_PATH}`.")
counts = table_counts(connection())
st.dataframe(
    [{"table": table, "rows": rows} for table, rows in counts.items()],
    hide_index=True,
)

if not any(counts.values()):
    st.info(
        "The schema is in place but empty. Loading the company library is "
        "milestone 2 — see PRD.md for the build order."
    )
