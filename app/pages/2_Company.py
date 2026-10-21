"""Company detail page: everything known about one employer."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="Company · Job Market Analyser", page_icon="📊", layout="wide")

st.title("Company")
st.info(
    "Placeholder. F3 (the page itself) and F4 (review sentiment, overall and "
    "by theme) land here in milestone 3, then open roles (F8, M5), skills "
    "(F7, M6), news (F6, M7) and turnover (F5, M8)."
)
st.caption(
    "Fields with no data show \"not available\" — never an estimate or a "
    "default. Sentiment stays hidden below 20 reviews."
)
