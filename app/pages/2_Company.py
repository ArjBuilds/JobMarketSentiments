"""Company detail page: everything known about one employer (F3).

Reads only from SQLite. Review sentiment (F4) comes from review_summary,
filled by process.review_sentiment; the rules for when a figure is hidden or
"not available" live in jmsa.sentiment.read_summary, not here. Data roles
(F8) come from jobs, filled by ingest.load_jobs, through jmsa.jobs.read_roles.
Turnover, skills and news arrive in later milestones.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.display import NOT_AVAILABLE, show  # noqa: E402
from jmsa.jobs import DATA_ROLES_NOTE, LOWER_BOUND_NOTE, ROLES_INTRO, read_roles  # noqa: E402
from jmsa.sentiment import MIN_REVIEWS, read_summary  # noqa: E402

st.set_page_config(page_title="Company · Job Market Analyser", page_icon="📊", layout="wide")


# Cached results, not connections, for the reason given on the Library page:
# sqlite3 won't share a connection across Streamlit's threads. Restart
# Streamlit (or press C) after reloading the database.
@st.cache_data
def companies() -> list[dict]:
    conn = get_conn()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT company_id, name, sector, hq_country, india_cities, size_band,"
            " glassdoor_rating, glassdoor_review_count FROM companies ORDER BY name COLLATE NOCASE"
        )]
    finally:
        conn.close()


@st.cache_data
def sentiment(company_id: str) -> dict:
    conn = get_conn()
    try:
        return read_summary(conn, company_id)
    finally:
        conn.close()


@st.cache_data
def roles(company_id: str) -> dict:
    conn = get_conn()
    try:
        return read_roles(conn, company_id)
    finally:
        conn.close()


st.title("Company")

# Checked before connecting, because get_conn would create an empty file.
if not DB_PATH.exists():
    st.warning(
        f"No database at `{DB_PATH}`. Create it and load the library with:\n\n"
        "```bash\npython -m jmsa.db init\npython -m ingest.load_companies\n```"
    )
    st.stop()

library = companies()
if not library:
    st.warning("The companies table is empty. Load it with:\n\n```bash\npython -m ingest.load_companies\n```")
    st.stop()

by_id = {c["company_id"]: c for c in library}
company = by_id[st.selectbox("Company", list(by_id), format_func=lambda company_id: by_id[company_id]["name"])]

st.header(company["name"])
cities = ", ".join(company["india_cities"].split(";")) if company["india_cities"] else None
st.markdown(
    f"**Sector** {show(company['sector'])} · **HQ** {show(company['hq_country'])} · "
    f"**Size band** {show(company['size_band'])}  \n"
    f"**India cities** {show(cities)}"
)
if company["glassdoor_rating"] is not None:
    rating = f"{company['glassdoor_rating']:.1f} from {company['glassdoor_review_count']:,} ratings"
else:
    rating = NOT_AVAILABLE
st.markdown(f"**Glassdoor rating** {rating}")
st.caption("The rating comes from a Glassdoor ratings snapshot, a different source "
           "from the review text scored below.")

st.subheader("Employee review sentiment")
summary = sentiment(company["company_id"])
if not summary["available"]:
    st.markdown(f"Review sentiment: **{NOT_AVAILABLE}**. The review dataset has no reviews for this company.")
else:
    if summary["note"]:
        st.warning(summary["note"])
    for column, view in zip(st.columns(len(summary["periods"])), summary["periods"]):
        with column:
            st.markdown(f"#### {view['title']}")
            st.caption(f"Reviews dated {view['range']}")
            st.markdown(
                f"**Average score** {view['average']}  \n"
                f"**Share** {view['shares']}  \n"
                f"**Based on** {view['reviews']} reviews"
            )
            if view["themes"]:
                st.dataframe(view["themes"], hide_index=True)
    st.caption(
        "VADER scores the headline, pros and cons separately; a review's score is "
        "mean(headline, mean(pros, cons)), from −1 (negative) to +1 (positive), labelled "
        "positive at ≥ 0.05 and negative at ≤ −0.05. A theme's score is the VADER score of the "
        "section that mentions it, so praise in the pros and complaints in the cons both count. "
        f"Figures based on fewer than {MIN_REVIEWS} reviews are hidden. Reviews end in mid-2023."
    )

st.subheader("Data roles posted in India")
posted = roles(company["company_id"])
if not posted["available"]:
    st.markdown(f"Data roles posted: **{NOT_AVAILABLE}**. The postings dataset has none for this company.")
else:
    st.markdown(ROLES_INTRO)
    st.markdown(f"**{posted['count']}** distinct listings. {LOWER_BOUND_NOTE}")
    st.dataframe(posted["rows"], hide_index=True)
st.caption(DATA_ROLES_NOTE)

st.subheader("Coming in later milestones")
st.caption("Data-role skills (F7: milestone 6, stage B) · News coverage (F6: milestone 7) · "
           "Turnover (F5: milestone 8)")
