"""The shared chart template and the fixed colours (DESIGN.md, "Visual direction")."""

import tomllib
from pathlib import Path

import plotly.graph_objects as go

from app.ui.charts import ACCENT, NEGATIVE, NEUTRAL, POSITIVE, PROXY, SENTIMENT_COLOURS, TEMPLATE

CONFIG = Path(__file__).resolve().parents[1] / ".streamlit" / "config.toml"


def test_the_theme_and_the_charts_use_the_same_colours_in_both_modes():
    theme = tomllib.loads(CONFIG.read_text(encoding="utf-8"))["theme"]
    assert "base" not in theme   # setting base would remove the viewer's light/dark switch
    for mode in ("light", "dark"):
        assert theme[mode] == {"primaryColor": ACCENT, "greenColor": POSITIVE, "redColor": NEGATIVE,
                               "grayColor": NEUTRAL, "orangeColor": PROXY}, mode


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
