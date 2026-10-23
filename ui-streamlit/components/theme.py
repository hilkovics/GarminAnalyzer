"""Colours and the shared Plotly layout of the "Kokpit" design. Presentation only.

The design defines a dark and a light value for every colour. A Plotly figure cannot ask which theme is
active, so chart colours are one fixed set: the light-theme tokens, which keep at least 3:1 contrast on both
the dark card (#161a1f) and the white card; the zone ramp is the design's dark ramp for the same reason.
Backgrounds are transparent so the page theme shows through; theme-dependent colours (page, cards, text,
badge text) live in `.streamlit/config.toml`, which uses these same hex values for its colour families.
Each chart panel has one y-axis, never a dual axis.
"""

import plotly.graph_objects as go

# Series / sport / status tokens (design: sport.run, sport.bike, sport.other, status.warn, status.danger).
BLUE = "#2a78d6"
ORANGE = "#e2622c"
AQUA = "#17a673"  # the design's green (sport.other, TSB, green readiness)
YELLOW = "#d99a00"  # readiness yellow – used by the gauge and (via config.toml) by the badge
RED = "#dc4544"
GRAY = "#8a8983"  # neutral: averages, medians, daily load

# Fixed colour per sport – the colour follows the entity, never its rank.
SPORT_COLORS = {"run": BLUE, "bike": ORANGE, "other": AQUA}

# Sequential blue ramp for HR/pace zones (Z1 light … Z5 dark); the design's ramp for dark cards.
ZONE_COLORS = {1: "#a9cbf5", 2: "#79acee", 3: "#4a8ee6", 4: "#2f6cc0", 5: "#1f4f94"}

# Grid and bands are translucent grey: ≈ #232930 on the dark card and ≈ #dde1e6 on the light one.
GRID = "rgba(128, 128, 128, 0.22)"
BAND = "rgba(128, 128, 128, 0.16)"

NUMBER_FONT = "Barlow Semi Condensed, Barlow, sans-serif"
LEGEND_FONT_SIZE = 12


def apply_base_layout(fig: go.Figure, *, height: int, legend: bool = True) -> go.Figure:
    """Transparent background, recessive grid, small legend top right, unified hover, decimal comma."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 36 if legend else 12, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        hoverlabel={"font": {"size": 12}, "namelength": -1},
        showlegend=legend,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.0,
            "xanchor": "right",
            "x": 1,
            "bgcolor": "rgba(0,0,0,0)",
            "font": {"size": LEGEND_FONT_SIZE},
        },
        separators=", ",  # Slovak: decimal comma, space as the thousands separator
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False, showline=False, tickfont={"size": 12})
    fig.update_yaxes(
        gridcolor=GRID, zeroline=False, showline=False, tickfont={"size": 12}, title_font={"size": 12}
    )
    return fig


def date_axis(fig: go.Figure) -> go.Figure:
    """Slovak day.month ticks and hover ("23. 10.") on every x-axis of a time-series figure."""
    fig.update_xaxes(tickformat="%-d. %-m.", hoverformat="%-d. %-m. %Y")
    return fig


def empty_figure(message: str, *, height: int = 240) -> go.Figure:
    """A figure that only says why there is nothing to draw."""
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_base_layout(fig, height=height, legend=False)
