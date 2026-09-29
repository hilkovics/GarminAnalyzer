"""Progress charts over a `SeriesDTO`: EF trend, decoupling scatter with the §5.3 bands, pace at reference HR.

DTO in, Plotly figure out. Points are markers, the 28-day median trend is a line (gaps stay gaps). Unit
conversion for display only: pace at reference HR arrives in m/s and is drawn as min/km.
"""

import plotly.graph_objects as go

from training.services.dto import SeriesDTO

from .format import fmt_date, fmt_pace
from .pace_axis import pace_axis, pace_s
from .theme import BLUE, ORANGE, RED, YELLOW, apply_base_layout, empty_figure

DECOUPLING_BANDS = ((5.0, "5 % – dobré", YELLOW), (10.0, "10 % – slabé", RED))  # METRICS §5.3


def _base(series: SeriesDTO, *, y_of, hover, name: str, message: str, height: int) -> go.Figure:
    """Markers for the points and the trend line; `y_of` converts a DTO value, `hover` labels a value."""
    points = [p for p in series.points if p.value is not None]
    if not points:
        return empty_figure(message)
    fig = go.Figure()
    fig.add_scatter(
        x=[p.local_date for p in points],
        y=[y_of(p.value) for p in points],
        mode="markers",
        name=name,
        marker={"color": BLUE, "size": 7, "opacity": 0.65},
        customdata=[hover(p.value) for p in points],
        hovertemplate="%{x|%d. %m. %Y}: %{customdata}<extra></extra>",
    )
    if any(t.value is not None for t in series.trend):
        fig.add_scatter(
            x=[t.date for t in series.trend],
            y=[y_of(t.value) if t.value is not None else None for t in series.trend],
            mode="lines",
            name="Medián 28 dní",
            line={"color": ORANGE, "width": 2.5},
            connectgaps=False,
            customdata=[hover(t.value) if t.value is not None else "–" for t in series.trend],
            hovertemplate="%{x|%d. %m. %Y}: %{customdata}<extra></extra>",
        )
    return apply_base_layout(fig, height=height)


def ef_chart(series: SeriesDTO) -> go.Figure:
    """EF (m/min per bpm) of steady-state activities with the 28-day median line (METRICS §5.2)."""
    fig = _base(
        series,
        y_of=lambda v: v,
        hover=lambda v: f"{v:.3f}",
        name="EF (steady-state)",
        message="Zatiaľ žiadne steady-state aktivity s EF.",
        height=340,
    )
    fig.update_yaxes(title_text="EF (m/min na úder)")
    return fig


def decoupling_chart(series: SeriesDTO) -> go.Figure:
    """Decoupling scatter (%) with the 5 % and 10 % band lines (METRICS §5.3)."""
    fig = _base(
        series,
        y_of=lambda v: v,
        hover=lambda v: f"{v:.1f} %",
        name="Decoupling",
        message="Zatiaľ žiadne steady-state aktivity s decouplingom.",
        height=320,
    )
    if fig.data:
        for level, label, color in DECOUPLING_BANDS:
            fig.add_hline(
                y=level,
                line={"color": color, "dash": "dash", "width": 1.5},
                annotation_text=label,
                annotation_position="top left",
            )
    fig.update_yaxes(title_text="Decoupling (%)")
    return fig


def pace_ref_chart(series: SeriesDTO) -> go.Figure:
    """Pace at the reference HR (0.80 · LTHR) per run and its 28-day median, as min/km, faster on top."""
    fig = _base(
        series,
        y_of=pace_s,
        hover=fmt_pace,
        name="Tempo pri referenčnom tepe",
        message="Zatiaľ žiadne behy s dostatkom dát okolo referenčného tepu (≥ 20 min).",
        height=320,
    )
    if fig.data:
        values = [pace_s(p.value) for p in series.points] + [pace_s(t.value) for t in series.trend]
        pace_axis(fig, values)
    return fig


def series_span(series: SeriesDTO) -> str:
    """Caption text "od – do" of the plotted points."""
    dates = [p.local_date for p in series.points]
    return f"{fmt_date(min(dates))} – {fmt_date(max(dates))}" if dates else "–"
