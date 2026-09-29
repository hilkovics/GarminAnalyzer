"""Activity detail chart: heart rate, pace (or speed) and altitude on a shared x-axis.

Takes a `StreamsDTO` (already downsampled by the service) and returns a Plotly figure. Conversions for display
only: s → min on the x-axis, m/s → s/km for pace (axis reversed so that faster is higher) or km/h for cycling.
"""

import math

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from training.services.dto import StreamsDTO

from .format import fmt_pace_s
from .theme import BLUE, GRAY, RED, apply_base_layout, empty_figure

PACE_CAP_S = 900.0  # slower than 15:00/km is drawn as a gap (standing still) so it cannot flatten the axis


def _has_values(values: list[float | None] | None) -> bool:
    return bool(values) and any(v is not None and not math.isnan(v) for v in values)


def _pace_s(speed_ms: float | None) -> float | None:
    """m/s → s/km for display; standing still (or slower than the cap) → None."""
    if speed_ms is None or math.isnan(speed_ms) or speed_ms <= 0:
        return None
    pace = 1000.0 / speed_ms
    return pace if pace <= PACE_CAP_S else None


def _kmh(speed_ms: float | None) -> float | None:
    return None if speed_ms is None else speed_ms * 3.6


def _pace_ticks(*series: list[float | None]) -> tuple[list[float], list[str]]:
    """Tick positions (every 30 s/km, or 60 s/km on a wide range) with m:ss labels."""
    values = [v for s in series for v in s if v is not None]
    if not values:
        return [], []
    lo, hi = min(values), max(values)
    step = 60 if hi - lo > 300 else 30
    first = int(lo // step) * step
    ticks = [float(t) for t in range(first, int(hi) + step + 1, step)]
    return ticks, [fmt_pace_s(t) for t in ticks]


def activity_chart(streams: StreamsDTO, *, sport: str | None = "run") -> go.Figure:
    """HR, pace (bike: km/h) and altitude panels stacked with one shared time axis.

    Panels without data are left out. The pace panel is reversed (faster on top); a `gap_speed` series, when
    present, is drawn dashed on it.
    """
    series = streams.series
    is_bike = sport == "bike"
    speed = series.get("speed")
    gap = None if is_bike else series.get("gap_speed")
    panels = [
        key
        for key, values in (("hr", series.get("hr")), ("speed", speed), ("alt", series.get("alt")))
        if _has_values(values)
    ]
    if not streams.t or not panels:
        return empty_figure("Pre túto aktivitu nie sú k dispozícii dáta streamu.")

    x = [s / 60.0 for s in streams.t]
    fig = make_subplots(rows=len(panels), cols=1, shared_xaxes=True, vertical_spacing=0.05)
    for row, key in enumerate(panels, start=1):
        if key == "hr":
            fig.add_scatter(
                x=x,
                y=series["hr"],
                name="Tep",
                mode="lines",
                line={"color": RED, "width": 1.5},
                hovertemplate="%{y:.0f} bpm",
                row=row,
                col=1,
            )
            fig.update_yaxes(title_text="bpm", row=row, col=1)
        elif key == "speed" and is_bike:
            fig.add_scatter(
                x=x,
                y=[_kmh(v) for v in speed],
                name="Rýchlosť",
                mode="lines",
                line={"color": BLUE, "width": 1.5},
                hovertemplate="%{y:.1f} km/h",
                row=row,
                col=1,
            )
            fig.update_yaxes(title_text="km/h", row=row, col=1)
        elif key == "speed":
            pace = [_pace_s(v) for v in speed]
            gap_pace = [_pace_s(v) for v in gap] if _has_values(gap) else None
            fig.add_scatter(
                x=x,
                y=pace,
                name="Tempo",
                mode="lines",
                line={"color": BLUE, "width": 1.5},
                customdata=[fmt_pace_s(p) if p else "–" for p in pace],
                hovertemplate="%{customdata}/km",
                row=row,
                col=1,
            )
            if gap_pace is not None:
                fig.add_scatter(
                    x=x,
                    y=gap_pace,
                    name="GAP",
                    mode="lines",
                    line={"color": GRAY, "width": 1.2, "dash": "dash"},
                    customdata=[fmt_pace_s(p) if p else "–" for p in gap_pace],
                    hovertemplate="%{customdata}/km",
                    row=row,
                    col=1,
                )
            ticks, labels = _pace_ticks(pace, gap_pace or [])
            fig.update_yaxes(
                title_text="min/km",
                autorange="reversed",
                tickvals=ticks or None,
                ticktext=labels or None,
                row=row,
                col=1,
            )
        else:
            alt = [v for v in series["alt"] if v is not None]
            pad = max(5.0, 0.1 * (max(alt) - min(alt)))
            fig.add_scatter(
                x=x,
                y=series["alt"],
                name="Výška",
                mode="lines",
                line={"color": GRAY, "width": 1},
                fill="tozeroy",
                fillcolor="rgba(138, 137, 131, 0.30)",
                hovertemplate="%{y:.0f} m",
                row=row,
                col=1,
            )
            fig.update_yaxes(title_text="m n. m.", range=[min(alt) - pad, max(alt) + pad], row=row, col=1)
    fig.update_xaxes(title_text="čas (min)", row=len(panels), col=1)
    return apply_base_layout(fig, height=170 * len(panels) + 60)
