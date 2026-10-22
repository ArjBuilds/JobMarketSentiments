"""The dashboard's shared pieces (DESIGN.md, "Shared components").

Every page draws headers, metrics, badges, source lines and empty states
through these, so a sentiment, a proxy figure or a missing value looks the
same everywhere. Formatting rules stay in jmsa (score_text, show,
source_line); this module only decides how they are drawn.

The badge colours are Streamlit's names ("blue", "red", "gray", "green")
that .streamlit/config.toml maps to the fixed semantic colours (positive
blue, negative orange-red, neutral grey, proxy aqua), so badges and charts
(app/ui/charts.py) always agree. A badge always carries its label text too,
so no meaning rests on colour alone.
"""

import streamlit as st

from app.state import set_filter
from jmsa.display import NOT_AVAILABLE, show
from jmsa.jobs import cities_text
from jmsa.sentiment import label, score_text
from jmsa.turnover import PROXY_HELP

# Each page's file, relative to app/app.py. The router builds its st.Page
# list from these, and links and st.switch_page use the same strings.
PAGES = {
    "explore": "pages/1_Library.py",
    "company": "pages/2_Company.py",
    "market_skills": "pages/3_Market_skills.py",
    "compare": "pages/4_Compare.py",
    "about": "pages/5_About_and_methods.py",
}

BADGE_COLOURS = {"positive": "blue", "neutral": "gray", "negative": "red"}
PROXY_BADGE_COLOUR = "green"   # config.toml's greenColor is the proxy's aqua, not a sentiment


def show_sector(sector: str) -> None:
    """Open Explore filtered to one sector. The other filters stay as the user left them."""
    set_filter("sectors", (sector,))
    st.switch_page(PAGES["explore"])


def company_header(company: dict) -> None:
    """Name, then the sector as a link to Explore filtered by it, HQ, size band and India cities."""
    st.title(company["name"], anchor=False)
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
    st.badge("Proxy", color=PROXY_BADGE_COLOUR, icon=":material/info:", help=PROXY_HELP)


def freshness_note(notes: dict[str, str], *keys: str) -> None:
    """'Glassdoor reviews · to Jul 2023' under a data block; several sources share one line.

    notes is jmsa.freshness.freshness_notes(), read from the database.
    """
    st.caption("  |  ".join(notes[key] for key in keys))


def empty_state(message: str, action_label: str | None = None, target_page: str | None = None,
                on_click=None, key: str | None = None) -> None:
    """One sentence and one next step: a link to a page, or a button that runs on_click.

    key tells the button apart from one with the same label elsewhere on the page."""
    st.info(message)
    if action_label and target_page:
        st.page_link(target_page, label=action_label, icon=":material/arrow_forward:")
    elif action_label and on_click:
        st.button(action_label, on_click=on_click, key=key)
