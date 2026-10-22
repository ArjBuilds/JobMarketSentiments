"""Session state shared by every page, set up in one place.

Streamlit forgets a widget's value when the widget isn't drawn on the
current page, so anything that must survive a page change (the chosen
company, the compare list, the Explore filters) lives in plain
st.session_state keys instead. Widgets read their starting value from these
keys and write back to them.

init_state() only fills keys that are missing, so app/app.py and every page
can call it: the router sets the state up for a real visit, and a page run
on its own (as tests/test_pages.py does) still finds it.
"""

from dataclasses import asdict

import streamlit as st

from jmsa.compare import MAX_COMPANIES
from jmsa.library import Filters


def default_filters() -> dict:
    """Filters that filter nothing, sorted by name A to Z: the Explore page's starting point."""
    return {**asdict(Filters()), "sort": "name", "descending": False}


def set_filter(name: str, value) -> None:
    """Set one Explore filter from another page (e.g. the Company page's sector link).

    The Explore widget's own key is dropped too, so the next visit refills
    the widget from the new value instead of keeping the one it showed last.
    """
    st.session_state.filters = {**st.session_state.filters, name: value}
    st.session_state.pop(f"filter_{name}", None)


def add_to_compare(company_id: str) -> None:
    """Add a company to the compare list. A full list is left as it is and
    compare_notice says why, for the page to show; nothing fails silently."""
    ids = st.session_state.compare_ids
    if company_id in ids:
        return
    if len(ids) >= MAX_COMPANIES:
        st.session_state.compare_notice = (f"The compare list is full ({MAX_COMPANIES} companies). "
                                           "Remove one on Compare first.")
        return
    st.session_state.compare_ids = [*ids, company_id]


def remove_from_compare(company_id: str) -> None:
    st.session_state.compare_ids = [c for c in st.session_state.compare_ids if c != company_id]


def init_state() -> None:
    """Fill each shared key that isn't set yet; never overwrite one that is."""
    st.session_state.setdefault("selected_company", None)   # a company_id slug
    st.session_state.setdefault("compare_ids", [])          # up to 4 company_id slugs
    st.session_state.setdefault("filters", default_filters())
