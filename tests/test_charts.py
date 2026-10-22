"""The shared chart template and the fixed colours (DESIGN.md, "Visual direction")."""

import tomllib
from pathlib import Path

import plotly.graph_objects as go

from app.ui.charts import (
    ACCENT, NEGATIVE, NEUTRAL, POSITIVE, PROXY, SENTIMENT_COLOURS, TEMPLATE, share_bar, theme_bars,
)

CONFIG = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"


def test_the_theme_and_the_charts_use_the_same_colours_in_both_modes():
    theme = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]
    assert "base" not in theme   # setting base would remove the viewer's light/dark switch
    for mode in ("light", "dark"):
        assert theme[mode] == {"primaryColor": ACCENT, "blueColor": POSITIVE, "redColor": NEGATIVE,
                               "grayColor": NEUTRAL, "greenColor": PROXY}, mode


def test_sentiment_colours_cover_every_label():
    assert SENTIMENT_COLOURS == {"positive": POSITIVE, "neutral": NEUTRAL, "negative": NEGATIVE}


def test_a_figure_on_the_template_keeps_streamlits_layer_and_adds_ours():
    figure = go.Figure(go.Bar(x=[1], y=["a"]), layout={"template": TEMPLATE})
    layout = figure.layout.template.layout
    assert layout.paper_bgcolor == "rgba(0,0,0,0)"
    assert layout.margin.l == 10
    # Streamlit's layer: its placeholder colours, which the browser swaps for
    # the viewer's light or dark mode.
    assert layout.coloraxis.colorscale[0][1] == "#000011"
    assert figure.layout.template.data.bar[0].marker.cornerradius == 4


def test_share_bar_labels_every_segment_with_its_name():
    figure = share_bar({"positive": 0.6, "neutral": 0.25, "negative": 0.15})
    assert [trace.marker.color for trace in figure.data] == [POSITIVE, NEUTRAL, NEGATIVE]
    assert [trace.text[0] for trace in figure.data] == ["60% positive", "25% neutral", "15% negative"]
    assert figure.layout.xaxis.title.text == "Share of reviews"


def test_theme_bars_colour_and_label_each_score_by_its_sentiment():
    figure = theme_bars([{"theme": "Pay", "score": 0.31, "mentions": 120},
                         {"theme": "Management", "score": -0.12, "mentions": 80}])
    bar = figure.data[0]
    assert list(bar.marker.color) == [POSITIVE, NEGATIVE]
    assert list(bar.text) == ["+0.31 · Positive", "-0.12 · Negative"]
    low, high = figure.layout.xaxis.range
    assert low == -high   # zero stays in the middle, so the sign shows in the bar's direction
