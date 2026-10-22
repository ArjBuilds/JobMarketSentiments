"""Company detail page: everything known about one employer (F3).

Reads only from SQLite. Review sentiment (F4) comes from review_summary,
filled by process.review_sentiment; the rules for when a figure is hidden or
"not available" live in jmsa.sentiment.read_summary, not here. Data roles
(F8) come from jobs, filled by ingest.load_jobs, through jmsa.jobs.read_roles.
Skills (F7) are market-wide, so this page only points to the Market skills
page. News (F6) comes from articles, filled by ingest.load_news, through
jmsa.news.read_news; the page never calls GNews. Turnover (F5) comes from
turnover through jmsa.turnover.read_turnover: published figures and the
review-based proxy, shown separately and never mixed. Each section's
source-and-date line comes from jmsa.freshness, read from the database.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app.state import init_state  # noqa: E402
from jmsa.db import get_conn  # noqa: E402
from app.ui.components import PAGES, freshness_note, proxy_tag  # noqa: E402
from jmsa.display import NOT_AVAILABLE, show  # noqa: E402
from jmsa.freshness import freshness_notes  # noqa: E402
from jmsa.jobs import ROLES_HELP, ROLES_LABEL, read_roles  # noqa: E402
from jmsa.news import read_news  # noqa: E402
from jmsa.turnover import read_turnover  # noqa: E402
from jmsa.sentiment import read_summary  # noqa: E402

init_state()


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
def notes() -> dict[str, str]:
    """Each source's short name and date, read from the database."""
    conn = get_conn()
    try:
        return freshness_notes(conn)
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

# app/app.py has already checked the database exists and has companies.
library = companies()

sources = notes()
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
    rating = f"{company['glassdoor_rating']:.1f}" + (f" from {count:,} ratings" if count is not None else "")
else:
    rating = NOT_AVAILABLE
st.markdown(f"**Glassdoor rating** {rating}")
freshness_note(sources, "ratings")

st.subheader("Employee review sentiment")
summary = sentiment(company["company_id"])
if not summary["available"]:
    st.markdown(f"Review sentiment: **{NOT_AVAILABLE}**")
else:
    if summary["note"]:
        st.caption(summary["note"])
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
freshness_note(sources, "reviews")

# Current openings live on the company's own careers site, kept apart from
# the historical F8 snapshot below.
if company["careers_url"]:
    openings = f"[{company['name']} careers page]({company['careers_url']})"
else:
    openings = NOT_AVAILABLE
st.markdown(f"**Current openings:** {openings}")

st.subheader(ROLES_LABEL, help=ROLES_HELP)
posted = roles(company["company_id"])
if not posted["available"]:
    st.markdown(f"**{NOT_AVAILABLE}**")
else:
    st.markdown(f"**{posted['count']}** listings")
    st.dataframe(posted["rows"], hide_index=True)
freshness_note(sources, "roles")

st.subheader("Data-role skills")
st.markdown(f"**{NOT_AVAILABLE}** for one company.")
st.page_link(PAGES["market_skills"], label="See market-wide skills", icon=":material/arrow_forward:")

st.subheader("News coverage")
coverage = news(company["company_id"])
if not coverage["available"]:
    st.markdown(f"News: **{NOT_AVAILABLE}**")
else:
    st.markdown("\n".join(
        f"- [{a['title']}]({a['url']}) · {a['outlet']} · {a['date']} · {a['sentiment']}"
        for a in coverage["rows"]
    ))
freshness_note(sources, "news")

# Published attrition and the proxy measure different things (a share of
# staff, a share of reviews), so each has its own heading and neither stands
# in for the other.
st.subheader("Turnover")
figures = turnover(company["company_id"])
st.markdown("#### Published attrition")
figure = figures["published"]
if figure is None:
    st.markdown(f"**{NOT_AVAILABLE}**")
else:
    st.markdown(f"**{figure['value']}** · {figure['basis']} · {figure['scope']} · {figure['period']} · "
                f"[Source]({figure['source_url']}) ({figure['source_ref']})")
freshness_note(sources, "attrition")
st.markdown("#### Proxy from reviews")
proxy_tag()
st.markdown(figures["proxy"])
if figures["note"]:
    st.caption(figures["note"])
freshness_note(sources, "proxy")
