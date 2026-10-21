"""Company detail page: everything known about one employer (F3).

Reads only from SQLite. Review sentiment (F4) comes from review_summary,
filled by process.review_sentiment; the rules for when a figure is hidden or
"not available" live in jmsa.sentiment.read_summary, not here. Data roles
(F8) come from jobs, filled by ingest.load_jobs, through jmsa.jobs.read_roles.
Skills (F7) are market-wide, so this page only points to the Market skills
page. News (F6) comes from articles, filled by ingest.load_news, through
jmsa.news.read_news; the page never calls GNews. Turnover (F5) comes from
turnover through jmsa.turnover.read_turnover: published figures and the
review-based proxy, shown separately and never mixed. Each section's source
line and dates come from jmsa.freshness, read from the database.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from jmsa.config import DB_PATH  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from jmsa.display import NOT_AVAILABLE, show  # noqa: E402
from jmsa.freshness import (  # noqa: E402
    ATTRITION_SOURCE, GNEWS_SOURCE, REVIEWS_SOURCE,
    read_freshness, review_end, snapshot_month, source_line, sparse_note,
)
from jmsa.jobs import DATA_ROLES_NOTE, LOWER_BOUND_NOTE, ROLES_INTRO, read_roles  # noqa: E402
from jmsa.news import NEWS_NOTE, read_news  # noqa: E402
from jmsa.turnover import PROXY_CHECK_NOTE, PROXY_NOTE, PUBLISHED_NOTE, read_turnover  # noqa: E402
from jmsa.sentiment import MIN_REVIEWS, read_summary  # noqa: E402
from jmsa.skills import COMPANY_SKILLS_NOTE  # noqa: E402

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
            " careers_url, glassdoor_rating, glassdoor_review_count FROM companies"
            " ORDER BY name COLLATE NOCASE"
        )]
    finally:
        conn.close()


@st.cache_data
def sources() -> tuple[dict, str, str]:
    """Each source's dates, when the reviews end, and the postings snapshot's month."""
    conn = get_conn()
    try:
        return read_freshness(conn), review_end(conn), snapshot_month(conn)
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


@st.cache_data
def news(company_id: str) -> dict:
    conn = get_conn()
    try:
        return read_news(conn, company_id)
    finally:
        conn.close()


@st.cache_data
def turnover(company_id: str) -> dict:
    conn = get_conn()
    try:
        return read_turnover(conn, company_id)
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

freshness, reviews_end, snapshot = sources()
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
    count = company["glassdoor_review_count"]
    rating = f"{company['glassdoor_rating']:.1f} " + (f"from {count:,} ratings" if count is not None
                                                      else f"(number of ratings {NOT_AVAILABLE})")
else:
    rating = (f"**{NOT_AVAILABLE}**. The ratings snapshot has no trustworthy row for this company "
              "(only a subsidiary or regional page, or none at all).")
st.markdown(f"**Glassdoor rating** {rating}")
st.caption("The rating comes from a Glassdoor ratings snapshot, a different source "
           "from the review text scored below. " + source_line(freshness, "ratings"))

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
            st.caption(f"Reviews dated {view['range']}{sparse_note(view['last_date'])}")
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
        f"Figures based on fewer than {MIN_REVIEWS} reviews are hidden."
    )
st.caption(f"Source: {REVIEWS_SOURCE}. Reviews end {reviews_end}.")

# Current openings live on the company's own careers site, kept apart from
# the historical F8 snapshot below.
if company["careers_url"]:
    openings = f"[{company['name']} careers page]({company['careers_url']}) (external link)"
else:
    openings = f"**{NOT_AVAILABLE}**. No official careers site is recorded for this company."
st.markdown(f"**Current openings:** {openings}")

st.subheader("Data roles posted in India")
posted = roles(company["company_id"])
if not posted["available"]:
    st.markdown(f"Data roles posted: **{NOT_AVAILABLE}**. The postings dataset has none for this company.")
else:
    st.markdown(ROLES_INTRO.format(snapshot=snapshot))
    st.markdown(f"**{posted['count']}** distinct listings. {LOWER_BOUND_NOTE}")
    st.dataframe(posted["rows"], hide_index=True)
st.caption(f"{DATA_ROLES_NOTE} {source_line(freshness, 'roles')}")

st.subheader("Data-role skills")
st.markdown(COMPANY_SKILLS_NOTE)

st.subheader("News coverage")
coverage = news(company["company_id"])
if not coverage["available"]:
    st.markdown(f"News: **{NOT_AVAILABLE}**. {coverage['message']}")
else:
    st.markdown(f"News fetched on {coverage['fetched_on']}.")
    st.markdown("\n".join(
        f"- [{a['title']}]({a['url']}) · {a['outlet']} · {a['date']} · {a['sentiment']}"
        for a in coverage["rows"]
    ))
st.caption(f"{NEWS_NOTE} Source: {GNEWS_SOURCE}.")

# Published attrition and the proxy measure different things (a share of
# staff, a share of reviews), so each has its own heading and neither stands
# in for the other.
st.subheader("Turnover")
figures = turnover(company["company_id"])
st.markdown("#### Published attrition")
figure = figures["published"]
if figure is None:
    st.markdown(f"Published attrition: **{NOT_AVAILABLE}**. No figure from the company's own "
                "reports has been recorded.")
else:
    st.markdown(
        f"**{figure['value']}** · {figure['period']} · {figure['basis']} · {figure['scope']}  \n"
        f"Definition: {figure['definition']}  \n"
        f"Entity: {figure['entity']}  \n"
        f"[Source]({figure['source_url']}) ({figure['source_ref']}), retrieved {figure['retrieved_on']}"
        + (f"  \nNote: {figure['note']}" if figure["note"] else "")
    )
st.caption(f"{PUBLISHED_NOTE} Source: {ATTRITION_SOURCE}.")
st.markdown("#### Proxy from reviews")
st.markdown(f"**Proxy:** {figures['proxy']}")
st.markdown(PROXY_CHECK_NOTE)
if figures["note"]:
    st.warning(figures["note"])
st.caption(f"{PROXY_NOTE} {source_line(freshness, 'proxy')}")
