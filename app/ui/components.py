"""The dashboard's shared pieces (DESIGN.md, "Shared components").

Every page draws headers, metrics, badges, source lines and empty states
through these, so a sentiment, a proxy figure or a missing value looks the
same everywhere. Formatting rules stay in jmsa (score_text, show,
source_line); this module only decides how they are drawn.

The badge colours are names ("green", "red", "gray", "orange") that
.streamlit/config.toml maps to the fixed semantic colours, so badges and
charts (app/ui/charts.py) always agree. Red and green look alike to
red-green colour-blind viewers, so a badge always carries its label text.
"""

import streamlit as st

from jmsa.display import NOT_AVAILABLE, show
from jmsa.freshness import source_line
from jmsa.jobs import cities_text
from jmsa.sentiment import label, score_text
from jmsa.turnover import WINDOW_TITLE

# Each page's file, relative to app/app.py. The router builds its st.Page
# list from these, and links and st.switch_page use the same strings.
PAGES = {
    "explore": "pages/1_Library.py",
    "company": "pages/2_Company.py",
    "market_skills": "pages/3_Market_skills.py",
    "compare": "pages/4_Compare.py",
    "about": "pages/5_About_and_methods.py",
}

BADGE_COLOURS = {"positive": "green", "neutral": "gray", "negative": "red"}

PROXY_DEFINITION = (
    "Proxy, not an attrition rate: reviews whose headline or cons mention people leaving, "
    f"attrition or layoffs, per 100 reviews dated {WINDOW_TITLE}. It counts reviews, not people."
)


def show_sector(sector: str) -> None:
    """Open Explore filtered to one sector. The other filters stay as the user left them."""
    st.session_state.filters = {**st.session_state.filters, "sectors": (sector,)}
    st.switch_page(PAGES["explore"])


def company_header(company: dict) -> None:
    """Name, then the sector as a link to Explore filtered by it, HQ, size band and India cities."""
    st.header(company["name"], anchor=False)
    sector, details = st.columns([1, 4], vertical_alignment="center")
    with sector:
        if company["sector"] and st.button(company["sector"], type="tertiary", icon=":material/filter_list:",
                                           help=f"Show every {company['sector']} company on Explore"):
            show_sector(company["sector"])
    with details:
        st.caption(f"HQ {show(company['hq_country'])} · Size band {show(company['size_band'])} · "
                   f"India cities {show(cities_text(company['india_cities']))}")


def metric_or_na(label_text: str, value, help: str | None = None, reason: str | None = None,
                 source: str | None = None) -> None:
    """st.metric, or "Not available" with the reason it's missing in the tooltip.

    value is display text (already formatted) or None. A value that show()
    turns into "Not available" counts as missing too, so a page can pass
    either.
    """
    missing = show(value) == NOT_AVAILABLE
    tooltip = " ".join(part for part in ((reason if missing else help), source and f"Source: {source}") if part)
    st.metric(label_text, NOT_AVAILABLE if missing else value, help=tooltip or None)


def sentiment_badge(compound: float | None) -> str:
    """':green-badge[+0.31 · Positive]', as markdown to place inside any text.

    A missing score is plain "Not available": a grey badge would read as neutral.
    """
    if compound is None:
        return NOT_AVAILABLE
    return f":{BADGE_COLOURS[label(compound)]}-badge[{score_text(compound)}]"


def label_badge(sentiment_label: str | None) -> str:
    """':red-badge[Negative]' for a stored label with no score beside it (a news headline)."""
    if sentiment_label not in BADGE_COLOURS:
        return NOT_AVAILABLE
    return f":{BADGE_COLOURS[sentiment_label]}-badge[{sentiment_label.capitalize()}]"


def proxy_tag() -> None:
    """The amber "Proxy" badge, with what the proxy is on hover. Beside every proxy figure."""
    st.badge("Proxy", color="orange", icon=":material/info:", help=PROXY_DEFINITION)


def freshness_note(freshness: dict, key: str) -> None:
    """The small source-and-dates line under a data block, read from the database."""
    st.caption(source_line(freshness, key))


def empty_state(message: str, action_label: str | None = None, target_page: str | None = None,
                on_click=None) -> None:
    """One sentence and one next step: a link to a page, or a button that runs on_click."""
    st.info(message)
    if action_label and target_page:
        st.page_link(target_page, label=action_label, icon=":material/arrow_forward:")
    elif action_label and on_click:
        st.button(action_label, on_click=on_click)
