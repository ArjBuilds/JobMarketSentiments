"""One look for every chart: the shared Plotly template and the fixed colours.

Every figure uses TEMPLATE, "streamlit+jma": Streamlit's own template first,
which recolours text and gridlines for the viewer's light or dark mode, then
ours on top, which only sets what Streamlit's leaves open (transparent
background, margins, bar shape, hover box). Replacing Streamlit's template
instead would fix the text to one mode's colour.

The semantic colours are fixed (DESIGN.md) and also set in
.streamlit/config.toml, so the badges match the charts; tests/test_charts.py
checks the two agree. They were chosen with a colour-blindness check rather
than by eye: positive blue, negative orange-red and the proxy's aqua stay
apart for red-green and blue-yellow colour blindness, in light and dark mode
(one hex each works for both). Neutral grey is the midpoint between them. The
accent is violet so a button or selection never reads as a sentiment. Every
coloured mark still carries its label.
"""

import plotly.graph_objects as go
import plotly.io as pio
import streamlit  # noqa: F401  registers Streamlit's "streamlit" Plotly template, which TEMPLATE builds on

POSITIVE = "#2a78d6"   # blue
NEUTRAL = "#9E9E9E"    # grey
NEGATIVE = "#d95926"   # orange-red
PROXY = "#199e70"      # aqua: marks a proxy, never a sentiment
ACCENT = "#6250d6"     # violet, the theme's primaryColor: a single-series chart's one colour

SENTIMENT_COLOURS = {"positive": POSITIVE, "neutral": NEUTRAL, "negative": NEGATIVE}

pio.templates["jma"] = go.layout.Template(
    layout={
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "margin": {"l": 10, "r": 40, "t": 10, "b": 40},
        "bargap": 0.45,                   # thin bars: about 23 px each at 42 px a row
        "hoverlabel": {"align": "left"},
        "xaxis": {"automargin": True},
        "yaxis": {"automargin": True},
        "legend": {"orientation": "h", "yanchor": "bottom", "y": 1.02, "x": 0},
    },
    data={"bar": [go.Bar(marker={"cornerradius": 4})]},
)
TEMPLATE = "streamlit+jma"
