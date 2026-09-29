"""Speed–HR curves (METRICS §6.1) and best-effort curves (§6.2): DTOs in, Plotly figures out.

Display conversions only: m/s → s/km for the pace axes (drawn reversed, faster on top), seconds → "n min".
"""

import plotly.graph_objects as go

from training.services.dto import BestEffortDTO, BestEffortsDTO, CurveDTO

from .format import fmt_date, fmt_pace, fmt_window
from .pace_axis import pace_axis, pace_s
from .theme import BLUE, GRAY, ORANGE, apply_base_layout, empty_figure

# Light → dark blues: the oldest month is the palest, the newest the darkest and thickest.
_RAMP = ("#c5dbf7", "#9ec5f4", "#6da7ec", "#3987e5", "#1c5cab", "#104281")


def _ramp_color(index: int, count: int) -> str:
    return _RAMP[-1] if count <= 1 else _RAMP[round(index * (len(_RAMP) - 1) / (count - 1))]


def curves_chart(curves: list[CurveDTO]) -> go.Figure:
    """One line per month snapshot: x = HR bin (lower edge, bpm), y = GAP pace (min/km, reversed)."""
    drawn = [c for c in curves if c.bins]
    if not drawn:
        return empty_figure("Zatiaľ žiadna krivka rýchlosť–tep (potrebné ≥ 10 minút v tepovom pásme).")
    fig = go.Figure()
    all_pace: list[float | None] = []
    for i, curve in enumerate(drawn):
        pace = [pace_s(b.gap_speed) for b in curve.bins]
        all_pace += pace
        newest = i == len(drawn) - 1
        fig.add_scatter(
            x=[b.hr_bin for b in curve.bins],
            y=pace,
            mode="lines+markers",
            name=curve.month,
            line={"color": _ramp_color(i, len(drawn)), "width": 3.5 if newest else 2},
            marker={"size": 6 if newest else 4},
            customdata=[f"{fmt_pace(b.gap_speed)} (n = {b.count})" for b in curve.bins],
            hovertemplate="%{x} bpm: %{customdata}<extra>" + curve.month + "</extra>",
        )
    ref = drawn[-1].ref_hr
    if ref is not None:
        fig.add_vline(
            x=ref,
            line={"color": GRAY, "dash": "dot", "width": 1.5},
            annotation_text=f"ref. tep {ref:.0f}",
            annotation_position="top",
        )
    fig.update_xaxes(title_text="Tepové pásmo (bpm, dolná hranica)")
    pace_axis(fig, all_pace, title="GAP tempo (min/km)")
    fig.update_layout(hovermode="closest")
    return apply_base_layout(fig, height=380)


def _by_window(dto: BestEffortsDTO, kind: str) -> dict[int, BestEffortDTO]:
    return {e.window_s: e for e in dto.efforts if e.kind == kind}


def _effort_traces(
    fig: go.Figure, recent: BestEffortsDTO, all_time: BestEffortsDTO, kind: str, y_of, hover
) -> list[float | None]:
    windows = sorted(set(_by_window(recent, kind)) | set(_by_window(all_time, kind)))
    labels = [fmt_window(w) for w in windows]
    values: list[float | None] = []
    for dto, name, color in ((recent, "Posledných 90 dní", BLUE), (all_time, "Celá história", ORANGE)):
        found = _by_window(dto, kind)
        y = [y_of(found[w].value) if w in found else None for w in windows]
        values += y
        fig.add_scatter(
            x=labels,
            y=y,
            mode="lines+markers",
            name=name,
            line={"color": color, "width": 2.5},
            customdata=[
                f"{hover(found[w].value)} ({fmt_date(found[w].local_date)})" if w in found else "–"
                for w in windows
            ],
            hovertemplate="%{x}: %{customdata}<extra></extra>",
        )
    return values


def _has_kind(kind: str, *dtos: BestEffortsDTO) -> bool:
    return any(e.kind == kind for d in dtos for e in d.efforts)


def best_efforts_chart(recent: BestEffortsDTO, all_time: BestEffortsDTO) -> go.Figure:
    """Best pace per window, 90 days vs all time (run: GAP pace; bike: speed shown as km/h)."""
    kind = "gap_speed" if recent.sport == "run" else "speed"
    if not _has_kind(kind, recent, all_time):
        return empty_figure("Zatiaľ žiadne najlepšie úseky.")
    fig = go.Figure()
    if kind == "gap_speed":
        values = _effort_traces(fig, recent, all_time, kind, pace_s, fmt_pace)
        pace_axis(fig, values, title="GAP tempo (min/km)")
    else:
        _effort_traces(fig, recent, all_time, kind, lambda v: v * 3.6, lambda v: f"{v * 3.6:.1f} km/h")
        fig.update_yaxes(title_text="Rýchlosť (km/h)")
    fig.update_xaxes(title_text="Dĺžka úseku", type="category")
    return apply_base_layout(fig, height=340)


def hr_efforts_chart(recent: BestEffortsDTO, all_time: BestEffortsDTO) -> go.Figure:
    """Highest mean heart rate per window (20/30/60 min), 90 days vs all time. Separate from pace."""
    if not _has_kind("hr", recent, all_time):
        return empty_figure("Zatiaľ žiadne tepové maximá úsekov.")
    fig = go.Figure()
    _effort_traces(fig, recent, all_time, "hr", lambda v: v, lambda v: f"{v:.0f} bpm")
    fig.update_xaxes(title_text="Dĺžka úseku", type="category")
    fig.update_yaxes(title_text="Priemerný tep (bpm)")
    return apply_base_layout(fig, height=300)
