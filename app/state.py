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

from jmsa.library import Filters


def default_filters() -> dict:
    """Filters that filter nothing, sorted by name A to Z: the Explore page's starting point."""
    return {**asdict(Filters()), "sort": "name", "descending": False}


def init_state() -> None:
    """Fill each shared key that isn't set yet; never overwrite one that is."""
    st.session_state.setdefault("selected_company", None)   # a company_id slug
    st.session_state.setdefault("compare_ids", [])          # up to 4 company_id slugs
    st.session_state.setdefault("filters", default_filters())
