"""Company page: everything known about one employer (F3).

Reads only from SQLite. Review sentiment (F4) comes from review_summary,
filled by process.review_sentiment; the rules for when a figure is hidden or
"Not available" live in jmsa.sentiment (read_summary for the text,
summary_numbers for the charts), not here. Data roles (F8) come from jobs
through jmsa.jobs.read_roles. Skills (F7) are market-wide, so this page only
links to the Market skills page. News (F6) comes from articles through
jmsa.news.read_news; the page never calls GNews. Turnover (F5) comes from
turnover through jmsa.turnover.read_turnover: the published figure and the
review-based proxy, shown separately and never mixed. Each block's
source-and-date line comes from jmsa.freshness, read from the database.

Which company is shown lives in st.session_state.selected_company (set by a
click on Explore or Compare, or by the picker here) and is mirrored to the
URL's ?company= so a refresh or a shared link opens the same company.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

from app.state import add_to_compare, init_state, remove_from_compare  # noqa: E402
from app.ui.charts import share_bar, theme_bars  # noqa: E402
from app.ui.components import (  # noqa: E402
    PAGES, company_header, freshness_note, label_badge, metric_or_na, proxy_tag,
)
from jmsa.db import get_conn  # noqa: E402
from jmsa.display import NOT_AVAILABLE  # noqa: E402
from jmsa.freshness import freshness_notes  # noqa: E402
from jmsa.jobs import ROLES_HELP, ROLES_LABEL, read_roles  # noqa: E402
from jmsa.news import read_news  # noqa: E402
from jmsa.sentiment import PERIOD_TITLES, PERIODS, hidden, read_summary, summary_numbers  # noqa: E402
from jmsa.turnover import read_turnover  # noqa: E402

init_state()


# Cached results, not connections, for the reason given on the Explore page:
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
def sentiment(company_id: str) -> tuple[dict, dict]:
    """The review figures as text (read_summary) and as numbers for the charts."""
    conn = get_conn()
    try:
        return read_summary(conn, company_id), summary_numbers(conn, company_id)
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


def pick_company() -> None:
    st.session_state.selected_company = st.session_state.company_pick


# app/app.py has already checked the database exists and has companies.
library = companies()
by_id = {c["company_id"]: c for c in library}

# Which company: the one chosen in this session, else the URL's ?company=
# (a refresh or a shared link starts a new session), else the first.
if st.session_state.selected_company not in by_id:
    param = st.query_params.get("company")
    st.session_state.selected_company = param if param in by_id else next(iter(by_id))
company_id = st.session_state.selected_company
st.query_params["company"] = company_id
company = by_id[company_id]

# --- top row: switch company, go back, add to compare -----------------------
# The picker is refilled from selected_company on every run and writes back
# only when the user changes it, so a click on another page always wins.
st.session_state.company_pick = company_id
pick_col, back_col, compare_col = st.columns([4, 1.4, 1.6], vertical_alignment="bottom")
with pick_col:
    st.selectbox("Company", list(by_id), format_func=lambda c: by_id[c]["name"], key="company_pick",
                 on_change=pick_company, label_visibility="collapsed")
with back_col:
    st.page_link(PAGES["explore"], label="Back to results", icon=":material/arrow_back:")
with compare_col:
    if company_id in st.session_state.compare_ids:
        st.button("Remove from compare", on_click=remove_from_compare, args=(company_id,),
                  icon=":material/remove:", width="stretch")
    else:
        st.button("Add to compare", on_click=add_to_compare, args=(company_id,), icon=":material/add:",
                  type="primary", width="stretch")
# Set by add_to_compare when the list is already full; shown once.
notice = st.session_state.pop("compare_notice", None)
if notice:
    st.warning(notice, icon=":material/info:")
    st.page_link(PAGES["compare"], label="Go to Compare", icon=":material/compare_arrows:")

company_header(company)

# --- the four headline figures ---------------------------------------------
summary, numbers = sentiment(company_id)
everything = numbers["all"]
posted = roles(company_id)
figures = turnover(company_id)
published = figures["published"]

if everything is None:
    score = None
elif everything["average"] is None:
    score = hidden(everything["reviews"])
else:
    score = summary["periods"][0]["average"]   # "+0.31 · Positive", all time
sentiment_col, reviews_col, attrition_col, roles_col = st.columns(4)
with sentiment_col:
    # LTM's reviews are pre-merger Mindtree's: the tooltip says so (CLAUDE.md).
    metric_or_na("Employee sentiment", score, help=summary["note"] or "All reviews, VADER from −1 to +1.",
                 reason="No reviews in the dataset.")
with reviews_col:
    metric_or_na("Reviews analysed", f"{everything['reviews']:,}" if everything else None,
                 reason="No reviews in the dataset.")
with attrition_col:
    metric_or_na("Published attrition", published["value"] if published else None,
                 help=" · ".join([published["basis"], published["scope"], published["period"]]) if published else None,
                 reason="No figure in the company's own reports.")
with roles_col:
    metric_or_na(ROLES_LABEL, posted["count"] if posted["available"] else None, help=ROLES_HELP,
                 reason="None in the dataset.")

sources = notes()
sentiment_tab, roles_tab, news_tab, turnover_tab = st.tabs(
    ["Sentiment", "Data roles & skills", "News", "Turnover"])

with sentiment_tab:
    if not summary["available"]:
        st.markdown(f"Review sentiment: **{NOT_AVAILABLE}**")
    else:
        period = st.radio("Review period", list(PERIODS), format_func=PERIOD_TITLES.get, horizontal=True,
                          index=list(PERIODS).index(st.session_state.filters["period"]), key="company_period")
        view = summary["periods"][list(PERIODS).index(period)]
        chart = numbers[period]
        if summary["note"]:
            st.caption(summary["note"])
        if chart is None:
            st.markdown(f"**{NOT_AVAILABLE}** for {PERIOD_TITLES[period].lower()}.")
        elif chart["shares"] is None:
            st.markdown(f"**{hidden(chart['reviews'])}**")
        else:
            with st.container(border=True):
                st.markdown(f"**{view['average']}** from {view['reviews']} reviews · dated {view['range']}")
                st.plotly_chart(share_bar(chart["shares"]), width="stretch", key="share_bar")
            shown_themes = [t for t in chart["themes"] if t["score"] is not None]
            with st.container(border=True):
                st.markdown("**By theme**")
                if shown_themes:
                    st.plotly_chart(theme_bars(shown_themes), width="stretch", key="theme_bars")
                hidden_themes = [t for t in chart["themes"] if t["score"] is None]
                if hidden_themes:
                    st.caption(" · ".join(f"{t['theme']}: {hidden(t['mentions'])}" for t in hidden_themes))
    freshness_note(sources, "reviews")

    with st.container(border=True):
        if company["glassdoor_rating"] is not None:
            count = company["glassdoor_review_count"]
            rating = f"**{company['glassdoor_rating']:.1f}**" + (f" from {count:,} ratings" if count else "")
        else:
            rating = f"**{NOT_AVAILABLE}**"
        st.markdown(f"Glassdoor rating {rating}")
        freshness_note(sources, "ratings")

with roles_tab:
    # Current openings live on the company's own careers site, kept apart
    # from the historical snapshot below.
    if company["careers_url"]:
        st.link_button("Current openings", company["careers_url"], icon=":material/open_in_new:")
    else:
        st.markdown(f"Current openings: **{NOT_AVAILABLE}**")
    with st.container(border=True):
        st.markdown(f"**{ROLES_LABEL}**", help=ROLES_HELP)
        if posted["available"]:
            st.dataframe(posted["rows"], hide_index=True)
        else:
            st.markdown(f"**{NOT_AVAILABLE}**")
        freshness_note(sources, "roles")
    with st.container(border=True):
        st.markdown(f"**Data-role skills** · {NOT_AVAILABLE} for one company")
        st.page_link(PAGES["market_skills"], label="See market-wide skills", icon=":material/arrow_forward:")

with news_tab:
    coverage = news(company_id)
    if not coverage["available"]:
        st.markdown(f"News: **{NOT_AVAILABLE}**")
    else:
        for article in coverage["rows"]:
            with st.container(border=True):
                st.markdown(f"[{article['title']}]({article['url']})  \n"
                            f"{article['outlet']} · {article['date']} · {label_badge(article['sentiment'])}")
    freshness_note(sources, "news")

# Published attrition and the proxy measure different things (a share of
# staff, a share of reviews), so each has its own box and neither stands in
# for the other.
with turnover_tab:
    published_col, proxy_col = st.columns(2)
    with published_col, st.container(border=True):
        st.markdown("**Published attrition**")
        if published is None:
            st.markdown(f"**{NOT_AVAILABLE}**")
        else:
            st.markdown(f"### {published['value']}")
            st.markdown(f"{published['basis']} · {published['scope']} · {published['period']} · "
                        f"[Source]({published['source_url']}) ({published['source_ref']})")
        freshness_note(sources, "attrition")
    with proxy_col, st.container(border=True):
        st.markdown("**From reviews**")
        proxy_tag()
        st.markdown(figures["proxy"])
        if figures["note"]:
            st.caption(figures["note"])
        freshness_note(sources, "proxy")
