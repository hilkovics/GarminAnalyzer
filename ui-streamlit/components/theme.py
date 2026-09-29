"""Colours and the shared Plotly layout. Presentation only.

Series colours follow the fixed categorical order blue, orange, aqua, yellow (dataviz palette) and are
mid-tone so that they read on Streamlit's light and dark themes; backgrounds are transparent so the page
theme shows through. Each chart panel has one y-axis, never a dual axis.
"""

import plotly.graph_objects as go

BLUE = "#2a78d6"
ORANGE = "#eb6834"
AQUA = "#1baf7a"
YELLOW = "#eda100"
RED = "#e34948"
GRAY = "#8a8983"

# Fixed colour per sport – the colour follows the entity, never its rank.
SPORT_COLORS = {"run": BLUE, "bike": ORANGE, "other": AQUA}

# Sequential blue ramp for HR/pace zones (Z1 light … Z5 dark).
ZONE_COLORS = {1: "#9ec5f4", 2: "#6da7ec", 3: "#3987e5", 4: "#1c5cab", 5: "#104281"}

GRID = "rgba(128, 128, 128, 0.22)"
BAND = "rgba(128, 128, 128, 0.16)"


def apply_base_layout(fig: go.Figure, *, height: int, legend: bool = True) -> go.Figure:
    """Transparent background, recessive grid, horizontal legend on top, unified hover."""
    fig.update_layout(
        height=height,
        margin={"l": 8, "r": 8, "t": 36 if legend else 12, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hovermode="x unified",
        showlegend=legend,
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.0, "xanchor": "left", "x": 0},
    )
    fig.update_xaxes(gridcolor=GRID, zeroline=False)
    fig.update_yaxes(gridcolor=GRID, zeroline=False)
    return fig


def empty_figure(message: str, *, height: int = 240) -> go.Figure:
    """A figure that only says why there is nothing to draw."""
    fig = go.Figure()
    fig.add_annotation(text=message, x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return apply_base_layout(fig, height=height, legend=False)
