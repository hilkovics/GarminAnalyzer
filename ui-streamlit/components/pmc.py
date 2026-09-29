"""Performance Management Chart (METRICS §4): CTL / ATL / TSB lines over daily load bars.

Takes a `PmcDTO` and returns a Plotly figure – no calculation. The DTO's `warming_up_until` becomes a shaded
band (the first 90 days of the series are not reliable yet).
"""

import datetime as dt

import plotly.graph_objects as go

from training.services.dto import PmcDTO

from .theme import AQUA, BAND, BLUE, GRAY, ORANGE, apply_base_layout, empty_figure

WARMING_UP_NAME = "warming_up"
_HALF_DAY = dt.timedelta(hours=12)


def _midnight(d: dt.date) -> dt.datetime:
    return dt.datetime.combine(d, dt.time.min)


def warming_up_span(pmc: PmcDTO) -> tuple[dt.datetime, dt.datetime] | None:
    """x-range of the shaded band, clipped to the plotted points; None if nothing to shade."""
    if not pmc.points or pmc.series_start is None or pmc.warming_up_until is None:
        return None
    start = max(pmc.series_start, pmc.points[0].date)
    end = min(pmc.warming_up_until, pmc.points[-1].date)
    if start > end:
        return None
    return _midnight(start) - _HALF_DAY, _midnight(end) + _HALF_DAY


def pmc_chart(pmc: PmcDTO, *, compact: bool = False) -> go.Figure:
    """CTL, ATL, TSB lines and daily-load bars on one axis; `compact` gives the dashboard mini version."""
    if not pmc.points:
        return empty_figure("Zatiaľ žiadne dáta.")
    x = [p.date for p in pmc.points]
    fig = go.Figure()
    fig.add_bar(
        x=x,
        y=[p.load_total for p in pmc.points],
        name="Denná záťaž",
        marker_color=GRAY,
        opacity=0.4,
        hovertemplate="%{y:.0f}",
    )
    for name, attr, color in (("CTL", "ctl", BLUE), ("ATL", "atl", ORANGE), ("TSB", "tsb", AQUA)):
        fig.add_scatter(
            x=x,
            y=[getattr(p, attr) for p in pmc.points],
            name=name,
            mode="lines",
            line={"color": color, "width": 2},
            hovertemplate="%{y:.1f}",
        )
    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color=GRAY)

    span = warming_up_span(pmc)
    if span is not None:
        x0, x1 = span
        fig.add_shape(
            type="rect",
            name=WARMING_UP_NAME,
            xref="x",
            yref="paper",
            x0=x0,
            x1=x1,
            y0=0,
            y1=1,
            fillcolor=BAND,
            line_width=0,
            layer="below",
        )
        fig.add_annotation(
            x=x0 + (x1 - x0) / 2,
            y=0.98,
            xref="x",
            yref="paper",
            text="zahrievanie (prvých 90 dní)",
            showarrow=False,
            yanchor="top",
            font={"size": 11, "color": GRAY},
        )
    fig.update_yaxes(title_text=None if compact else "TSS-ekvivalent")
    return apply_base_layout(fig, height=260 if compact else 420)
