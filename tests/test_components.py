"""The shared components (DESIGN.md, "Shared components").

Badges are markdown strings, so they are checked directly; the parts that
draw are run headlessly with AppTest.
"""

from streamlit.testing.v1 import AppTest

from app.ui.components import label_badge, markdown_safe, sentiment_badge
from jmsa.display import NOT_AVAILABLE


def test_sentiment_badge_colour_follows_the_vader_cut_offs_and_keeps_the_sign():
    assert sentiment_badge(0.31) == ":blue-badge[+0.31 · Positive]"
    assert sentiment_badge(0.05) == ":blue-badge[+0.05 · Positive]"
    assert sentiment_badge(0.0) == ":gray-badge[+0.00 · Neutral]"
    assert sentiment_badge(-0.12) == ":red-badge[-0.12 · Negative]"


def test_a_missing_score_is_plain_text_not_a_grey_badge():
    assert sentiment_badge(None) == NOT_AVAILABLE
    assert label_badge(None) == NOT_AVAILABLE
    assert label_badge(NOT_AVAILABLE) == NOT_AVAILABLE


def test_label_badge_for_a_stored_label():
    assert label_badge("negative") == ":red-badge[Negative]"
    assert label_badge("neutral") == ":gray-badge[Neutral]"


def metrics_script():
    from app.ui.components import metric_or_na
    metric_or_na("Published attrition", "12.8%", help="Latest figure.", source="Annual report")
    metric_or_na("Data-role listings", None, help="Distinct listings.", reason="No postings in the dataset.")


def test_metric_or_na_shows_the_value_or_not_available_with_the_reason():
    app = AppTest.from_function(metrics_script).run()
    assert not app.exception, app.exception
    shown, missing = app.metric
    assert (shown.value, shown.help) == ("12.8%", "Latest figure. Source: Annual report")
    assert (missing.value, missing.help) == (NOT_AVAILABLE, "No postings in the dataset.")


def empty_script():
    import streamlit as st
    from app.ui.components import empty_state, proxy_tag

    def clear():
        st.session_state.cleared = True

    empty_state("No companies match these filters.", "Clear filters", on_click=clear)
    proxy_tag()


def test_empty_state_offers_one_action_and_the_proxy_tag_draws():
    app = AppTest.from_function(empty_script).run()
    assert not app.exception, app.exception
    assert app.info[0].value == "No companies match these filters."
    app.button[0].click().run()
    assert app.session_state.cleared


def test_markdown_safe_escapes_cells_but_not_kept_columns_or_numbers():
    frame = markdown_safe([{"Metric": "Score (all)", "Acme": "Pays $5 *cash*", "n": 3}], keep=("Metric",))
    assert frame.loc[0, "Metric"] == "Score (all)"
    assert frame.loc[0, "Acme"] == r"Pays \$5 \*cash\*"
    assert frame.loc[0, "n"] == 3
