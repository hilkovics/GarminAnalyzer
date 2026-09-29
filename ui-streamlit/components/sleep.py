"""Sleep page charts over `WellnessDTO` / `ReadinessDTO`: readiness gauge, sleep stages, score and RHR with
the 28-day baseline band, sleep debt.

DTO in, Plotly figure out. Seconds become hours (bars) or h:mm (hover text) here; nothing is computed
beyond unit conversion and the median ± MAD band edges.
"""

import math

import plotly.graph_objects as go

from training.services.dto import ReadinessDTO, WellnessDayDTO, WellnessDTO

from .format import fmt_duration
from .theme import AQUA, BAND, BLUE, GRAY, ORANGE, RED, YELLOW, apply_base_layout, empty_figure

BAND_COLORS = {"green": AQUA, "yellow": YELLOW, "red": RED}
BAND_TINTS = {
    "red": "rgba(227, 73, 72, 0.22)",
    "yellow": "rgba(237, 161, 0, 0.22)",
    "green": "rgba(27, 175, 122, 0.22)",
}
STAGES = (  # (WellnessDayDTO field, label, colour): deep darkest, awake in the warning colour
    ("deep_s", "Hlboký", "#104281"),
    ("light_s", "Ľahký", "#6da7ec"),
    ("rem_s", "REM", AQUA),
    ("awake_s", "Bdelý", ORANGE),
)
NO_DATA = "Zatiaľ žiadne wellness dáta v tomto rozsahu."


def readiness_gauge(dto: ReadinessDTO) -> go.Figure:
    """Gauge 0–100 with the three §8 bands; the number is the score truncated to an integer."""
    if not dto.available or dto.score is None:
        return empty_figure("Pripravenosť dnes nie je k dispozícii.", height=260)
    color = BAND_COLORS.get(dto.band or "", GRAY)
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=math.floor(dto.score),  # METRICS §8: shown truncated, so the number matches its band
            number={"font": {"size": 54}},
            gauge={
                "axis": {"range": [0, 100]},
                "bar": {"color": color, "thickness": 0.35},
                "steps": [
                    {"range": [0, 45], "color": BAND_TINTS["red"]},
                    {"range": [45, 70], "color": BAND_TINTS["yellow"]},
                    {"range": [70, 100], "color": BAND_TINTS["green"]},
                ],
            },
        )
    )
    fig.update_layout(height=260, margin={"l": 24, "r": 24, "t": 24, "b": 8}, paper_bgcolor="rgba(0,0,0,0)")
    return fig


def _hours(seconds: float | None) -> float | None:
    return None if seconds is None else seconds / 3600.0


def _days(dto: WellnessDTO, field: str) -> list[WellnessDayDTO]:
    return [d for d in dto.days if getattr(d, field) is not None]


def sleep_stages_chart(dto: WellnessDTO) -> go.Figure:
    """Stacked bars (h) of deep / light / REM / awake per night; nights without stages are left out."""
    days = [d for d in dto.days if any(getattr(d, f) is not None for f, _, _ in STAGES)]
    if not days:
        return empty_figure(NO_DATA)
    fig = go.Figure()
    for field, label, color in STAGES:
        fig.add_bar(
            x=[d.date for d in days],
            y=[_hours(getattr(d, field)) for d in days],
            name=label,
            marker_color=color,
            customdata=[fmt_duration(getattr(d, field)) for d in days],
            hovertemplate="%{customdata}",
        )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Spánok (h)")
    return apply_base_layout(fig, height=340)


def _baseline_chart(
    dto: WellnessDTO, *, field: str, name: str, unit: str, y_of, hover, color: str, height: int = 300
) -> go.Figure:
    """Line of `field`, the 28-day median line and a median ± MAD band."""
    days = _days(dto, field)
    if not days:
        return empty_figure(NO_DATA)
    fig = go.Figure()
    with_band = [d for d in dto.days if getattr(d.baselines, field).median is not None]
    if with_band:
        mad = [getattr(d.baselines, field).mad or 0.0 for d in with_band]
        median = [getattr(d.baselines, field).median for d in with_band]
        x = [d.date for d in with_band]
        fig.add_scatter(
            x=x, y=[y_of(m + a) for m, a in zip(median, mad, strict=True)], mode="lines",
            line={"width": 0}, showlegend=False, hoverinfo="skip",
        )  # fmt: skip
        fig.add_scatter(
            x=x, y=[y_of(m - a) for m, a in zip(median, mad, strict=True)], mode="lines",
            line={"width": 0}, fill="tonexty", fillcolor=BAND, name="± MAD", hoverinfo="skip",
        )  # fmt: skip
        fig.add_scatter(
            x=x, y=[y_of(m) for m in median], mode="lines", name="Medián 28 dní",
            line={"color": GRAY, "width": 2, "dash": "dash"},
            customdata=[hover(m) for m in median], hovertemplate="%{customdata}",
        )  # fmt: skip
    fig.add_scatter(
        x=[d.date for d in days],
        y=[y_of(getattr(d, field)) for d in days],
        mode="lines+markers",
        name=name,
        line={"color": color, "width": 2},
        marker={"size": 5},
        connectgaps=False,
        customdata=[hover(getattr(d, field)) for d in days],
        hovertemplate="%{customdata}",
    )
    fig.update_yaxes(title_text=unit)
    return apply_base_layout(fig, height=height)


def sleep_score_chart(dto: WellnessDTO) -> go.Figure:
    """Garmin sleep score with its 28-day median and ± MAD band."""
    return _baseline_chart(
        dto, field="sleep_score", name="Skóre spánku", unit="Skóre spánku", color=BLUE,
        y_of=lambda v: v, hover=lambda v: f"{v:.0f}",
    )  # fmt: skip


def rhr_chart(dto: WellnessDTO) -> go.Figure:
    """Resting HR with its 28-day median and ± MAD band."""
    return _baseline_chart(
        dto, field="rhr", name="Pokojový tep", unit="Pokojový tep (bpm)", color=ORANGE,
        y_of=lambda v: v, hover=lambda v: f"{v:.0f} bpm",
    )  # fmt: skip


def _signed_duration(seconds: float) -> str:
    return ("−" if seconds < 0 else "") + fmt_duration(abs(seconds))


def sleep_debt_chart(dto: WellnessDTO) -> go.Figure:
    """7-night sleep debt in hours (positive = debt, negative = surplus), with a zero line."""
    days = [d for d in dto.days if d.sleep_debt_7_s is not None]
    if not days:
        return empty_figure("Spánkový dlh sa počíta z aspoň 5 nocí za posledných 7.")
    fig = go.Figure()
    fig.add_scatter(
        x=[d.date for d in days],
        y=[_hours(d.sleep_debt_7_s) for d in days],
        mode="lines",
        name="Spánkový dlh (7 nocí)",
        line={"color": RED, "width": 2.5},
        customdata=[_signed_duration(d.sleep_debt_7_s) for d in days],
        hovertemplate="%{customdata}",
    )
    fig.add_hline(y=0, line_width=1, line_dash="dot", line_color=GRAY)
    fig.update_yaxes(title_text="Spánkový dlh (h)")
    return apply_base_layout(fig, height=280, legend=False)
