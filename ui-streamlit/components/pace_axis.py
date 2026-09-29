"""Pace axis helpers for the progress charts: m/s → s/km values, a reversed y-axis with m:ss tick labels."""

import math

import plotly.graph_objects as go

from .format import fmt_pace_s

PACE_CAP_S = 900.0  # slower than 15:00/km is not drawn


def pace_s(speed_ms: float | None) -> float | None:
    """m/s → s/km for display; None, non-positive or slower than the cap → None."""
    if speed_ms is None or math.isnan(speed_ms) or speed_ms <= 0:
        return None
    pace = 1000.0 / speed_ms
    return pace if pace <= PACE_CAP_S else None


def pace_axis(fig: go.Figure, *series: list[float | None], title: str = "Tempo (min/km)") -> None:
    """Reverse the y-axis (faster on top) and label it as m:ss every 15/30/60 s depending on the range."""
    values = [v for s in series for v in s if v is not None]
    fig.update_yaxes(title_text=title, autorange="reversed")
    if not values:
        return
    lo, hi = min(values), max(values)
    step = 60 if hi - lo > 300 else 30 if hi - lo > 90 else 15
    ticks = [float(t) for t in range(int(lo // step) * step, int(hi) + step + 1, step)]
    fig.update_yaxes(tickmode="array", tickvals=ticks, ticktext=[fmt_pace_s(t) for t in ticks])
