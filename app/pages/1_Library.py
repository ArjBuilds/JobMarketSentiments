"""Company library: the sortable, filterable table over every tracked company."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Library · Job Market Analyser", page_icon="📊", layout="wide")

st.title("Company library")
st.info(
    "Placeholder. F1 (the company table) lands here in milestone 2, and F2 "
    "(filter by sector, HQ country, open roles, minimum sentiment and "
    "required skill; sort by sentiment, open roles or attrition) in milestone 4."
)
