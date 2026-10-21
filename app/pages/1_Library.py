"""Company library: the table over every tracked company (F1).

Reads only from SQLite. The Glassdoor columns are filled by
ingest.load_glassdoor_ratings. Filters and sorting (F2) come in a later
milestone.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.display import NOT_AVAILABLE, show  # noqa: E402

st.set_page_config(page_title="Library · Job Market Analyser", page_icon="📊", layout="wide")

# Database column -> header shown on the page, in display order.
COLUMNS = {
    "name": "Company",
    "sector": "Sector",
    "hq_country": "HQ country",
    "india_cities": "India cities",
    "size_band": "Size band",
    # The Glassdoor ratings snapshot: an overall star rating and how many
    # reviews it rests on. Not review-text sentiment, which is a separate source.
    "glassdoor_rating": "Glassdoor rating",
    "glassdoor_review_count": "Glassdoor reviews",
}


@st.cache_data
def library_rows() -> list[dict]:
    """One display-ready dict per company. Cached, so reruns skip the query.

    The result is cached rather than the connection: sqlite3 refuses to use
    a connection from a thread other than the one that opened it, and
    Streamlit may run each visit on a different thread.

    The cache lasts until the app restarts, so restart Streamlit (or press C
    in the page and clear the cache) after reloading the database.
    """
    query = f"SELECT {', '.join(COLUMNS)} FROM companies ORDER BY name COLLATE NOCASE"
    conn = get_conn()
    try:
        records = conn.execute(query).fetchall()
    finally:
        conn.close()

    rows = []
    for record in records:
        row = {header: show(record[column]) for column, header in COLUMNS.items()}
        if record["india_cities"]:
            row["India cities"] = ", ".join(record["india_cities"].split(";"))
        # Formatted as text because a column can't mix numbers with the
        # "not available" string; numeric sorting comes with the F2 filters.
        if record["glassdoor_rating"] is not None:
            row["Glassdoor rating"] = f"{record['glassdoor_rating']:.1f}"
        if record["glassdoor_review_count"] is not None:
            row["Glassdoor reviews"] = f"{record['glassdoor_review_count']:,}"
        rows.append(row)
    return rows


st.title("Company library")

# Checked before connecting, because get_conn would create an empty file.
if not DB_PATH.exists():
    st.warning(
        f"No database at `{DB_PATH}`. Create it and load the library with:\n\n"
        "```bash\npython -m jmsa.db init\npython -m ingest.load_companies\n```"
    )
    st.stop()

rows = library_rows()
if not rows:
    st.warning(
        "The companies table is empty. Load it with:\n\n"
        "```bash\npython -m ingest.load_companies\n```"
    )
    st.stop()

rated = sum(1 for row in rows if row["Glassdoor rating"] != NOT_AVAILABLE)
st.caption(f"{len(rows)} companies, {rated} with a Glassdoor rating")
st.dataframe(rows, hide_index=True)
