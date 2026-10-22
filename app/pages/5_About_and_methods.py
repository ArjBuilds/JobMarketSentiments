"""About the data: each source, what it is used for and its dates, plus a
collapsed "How scores work" expander that explains every calculation.

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
from jmsa.sentiment import (  # noqa: E402
    MIN_REVIEWS, NEGATIVE_AT, PERIOD_TITLES, POSITIVE_AT, THEME_NAMES, THEMES,
)
from jmsa.turnover import PROXY_HELP, WINDOW_TITLE  # noqa: E402

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

# Every calculation, one short headed section each, drawn from
# docs/methods.md. Numbers come from the constants the pipeline uses, so the
# text can't drift from the code. Collapsed, so the page itself stays short.
THEME_LIST = ", ".join(THEME_NAMES[theme].lower() for theme in THEMES)
HOW_SCORES_WORK = {
    "Review sentiment": (
        "VADER scores each review's headline, pros and cons separately, from −1 (negative) to +1 "
        "(positive). A review's score is the mean of its headline score and the mean of its pros and "
        "cons scores. Cons aren't subtracted, because VADER already scores complaints negative. A "
        "company's score is the mean over its reviews, for all time or "
        f"{PERIOD_TITLES['2020-2023']}. A review with no text gets no score, not zero."
    ),
    "Theme sentiment": (
        f"The themes ({THEME_LIST}) are found by keyword. A theme's score is the VADER score of the "
        "section (headline, pros or cons) that mentions it, averaged over the reviews that mention it, so praise in "
        "the pros and complaints in the cons both count."
    ),
    "Thresholds": (
        f"- Positive at {POSITIVE_AT:+.2f} or more, Negative at {NEGATIVE_AT:+.2f} or less, Neutral "
        "in between. The same cut-offs label reviews, themes and news.\n"
        f"- With fewer than {MIN_REVIEWS} reviews (or theme mentions), the score is hidden and the "
        "count is shown instead.\n"
        "- Where a source has nothing for a company, the figure reads Not available. Nothing is "
        "estimated or filled in."
    ),
    "Glassdoor rating vs review sentiment": (
        "The Glassdoor rating is the 1–5 star rating from a separate Glassdoor ratings snapshot, shown "
        "with its number of ratings. Review sentiment is computed from review text in another dataset. "
        "Their coverage differs, so a company can have one without the other, and neither stands in "
        "for the other."
    ),
    "Published attrition": (
        "Copied by hand from the company's own annual report, BRSR, quarterly results or ESG report, "
        "with a page reference. Each figure is shown as printed, with its basis (voluntary, total or "
        "not stated), scope (group, segment or India subsidiary) and period; only the latest is "
        "shown. Definitions differ, so filter by basis and scope before ranking."
    ),
    "Turnover proxy": (
        f"The reviews dated {WINDOW_TITLE} whose headline or cons mention people leaving, attrition "
        "or layoffs, per 100 reviews in that window, split into the two kinds. Pros aren't searched: "
        "there, leave means time off and no layoffs is praise. A review can mention both kinds, so "
        f"the parts can add up to more than the total. {PROXY_HELP} It is never sorted or ranked."
    ),
    "News sentiment": (
        "Up to 10 articles per company from GNews, from the 30 days before news was fetched, kept "
        "only if the title or description names the company. VADER scores the headline and short "
        "description, not the article. A featured company's news figure is the mean of its "
        "articles' scores."
    ),
    "Data-role listings": (
        "Naukri postings for data-science and analytics roles in India, kept when the job title names "
        "a data role, matched to the company and deduplicated. Counts are a lower bound. "
        f"{ROLES_HELP} The careers button on each company's page links to current openings."
    ),
    "Skills counts": (
        "Known skills, tools and methods, are matched in the postings' skills text. The counts are "
        "market-wide only, because the source can't tie a skill to an employer. Each distinct skill "
        "list counts once, and a skill's share is the share of those lists that name it."
    ),
}

with st.expander("How scores work"):
    for heading, text in HOW_SCORES_WORK.items():
        st.markdown(f"**{heading}**")
        st.markdown(text)
