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

from jmsa.sentiment import label, score_text

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


def share_bar(shares: dict[str, float]) -> go.Figure:
    """One stacked bar: the share of reviews that are positive, neutral and negative.

    Each segment is labelled with its share and name, so no meaning rests on
    colour; no legend is needed.
    """
    figure = go.Figure()
    for name, share in shares.items():
        figure.add_trace(go.Bar(
            x=[share * 100], y=[""], orientation="h", name=name.capitalize(),
            marker={"color": SENTIMENT_COLOURS[name], "cornerradius": 0},
            text=[f"{share:.0%} {name}" if share >= 0.08 else ""], textposition="inside",
            # White reads on blue and orange-red; grey needs dark text.
            insidetextanchor="middle", textfont={"color": "#1a1a1a" if name == "neutral" else "white"},
            hovertemplate=f"{name.capitalize()}: %{{x:.0f}}% of reviews<extra></extra>",
        ))
    figure.update_layout(template=TEMPLATE, barmode="stack", height=110, showlegend=False,
                         margin={"l": 10, "r": 10, "t": 10, "b": 40},
                         xaxis={"title": "Share of reviews", "ticksuffix": "%", "range": [0, 100]},
                         yaxis={"showticklabels": False})
    return figure


def theme_bars(themes: list[dict]) -> go.Figure:
    """One horizontal bar per theme: its average score, coloured and labelled by sentiment.

    themes are jmsa.sentiment.summary_numbers rows with a score (hidden themes
    are left out by the caller). Bars point left of zero when negative, so the
    sign shows in the shape as well as the colour and label.
    """
    scores = [t["score"] for t in themes]
    reach = max(0.25, max(abs(s) for s in scores) * 1.4)
    figure = go.Figure(go.Bar(
        x=scores, y=[t["theme"] for t in themes], orientation="h",
        marker={"color": [SENTIMENT_COLOURS[label(s)] for s in scores]},
        text=[score_text(s) for s in scores], textposition="outside", cliponaxis=False,
        customdata=[f"{t['mentions']:,}" for t in themes],
        hovertemplate="%{y}: %{text} (%{customdata} reviews mention it)<extra></extra>",
    ))
    figure.update_layout(template=TEMPLATE, height=60 + 42 * len(themes),
                         xaxis={"title": "Average sentiment (−1 to +1)", "range": [-reach, reach],
                                "zeroline": True, "tickformat": "+.1f"},
                         yaxis={"autorange": "reversed", "showgrid": False})
    return figure
