"""Weekly aggregate charts (METRICS §4 weekly aggregates): stacked bars per sport and this-week comparison.

Takes `WeeklyDTO` lists and returns Plotly figures. Only unit conversion for display happens here (s → h,
m → km); the DTOs already hold the aggregates.
"""

import plotly.graph_objects as go

from training.services.dto import WeeklyDTO

from .format import sport_label
from .theme import GRAY, SPORT_COLORS, apply_base_layout, empty_figure

# metric key → (label, unit, DTO attribute, multiplier for display)
WEEKLY_METRICS: dict[str, tuple[str, str, str, float]] = {
    "load": ("Záťaž", "TSS-ekv.", "load", 1.0),
    "duration": ("Čas", "h", "duration_s", 1.0 / 3600.0),
    "distance": ("Vzdialenosť", "km", "distance_m", 1.0 / 1000.0),
}

_SPORT_ORDER = ("run", "bike", "other")


def _metric(metric: str) -> tuple[str, str, str, float]:
    try:
        return WEEKLY_METRICS[metric]
    except KeyError:
        raise ValueError(
            f"Unknown weekly metric {metric!r}; expected one of {sorted(WEEKLY_METRICS)}"
        ) from None


def weekly_bars(weeks: list[WeeklyDTO], metric: str = "load") -> go.Figure:
    """Stacked bars per ISO week, one trace per sport ("all" rows are skipped)."""
    label, unit, attr, factor = _metric(metric)
    rows = [w for w in weeks if w.sport != "all"]
    if not rows:
        return empty_figure("Zatiaľ žiadne týždenné dáta.")
    starts = sorted({w.week_start for w in rows})
    sports = [s for s in _SPORT_ORDER if any(w.sport == s for w in rows)]
    sports += sorted({w.sport for w in rows} - set(_SPORT_ORDER))
    iso = {w.week_start: f"T{w.iso_week}/{w.iso_year}" for w in rows}

    fig = go.Figure()
    for sport in sports:
        by_start = {w.week_start: getattr(w, attr) * factor for w in rows if w.sport == sport}
        fig.add_bar(
            x=starts,
            y=[by_start.get(s, 0.0) for s in starts],
            name=sport_label(sport),
            marker_color=SPORT_COLORS.get(sport, GRAY),
            customdata=[iso[s] for s in starts],
            hovertemplate="%{customdata}: %{y:.1f} " + unit,
        )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text=f"{label} ({unit})")
    return apply_base_layout(fig, height=360)


def week_compare_bars(
    this_week: list[WeeklyDTO], last4_avg: list[WeeklyDTO], metric: str = "load"
) -> go.Figure:
    """Grouped bars per sport: this week vs the mean of the 4 previous weeks ("all" rows are skipped)."""
    label, unit, attr, factor = _metric(metric)
    current = {w.sport: w for w in this_week if w.sport != "all"}
    average = {w.sport: w for w in last4_avg if w.sport != "all"}
    sports = [s for s in _SPORT_ORDER if s in current or s in average]
    sports += sorted((set(current) | set(average)) - set(_SPORT_ORDER))
    if not sports:
        return empty_figure("Zatiaľ žiadne týždenné dáta.")
    labels = [sport_label(s) for s in sports]

    def values(source: dict[str, WeeklyDTO]) -> list[float]:
        return [getattr(source[s], attr) * factor if s in source else 0.0 for s in sports]

    fig = go.Figure()
    fig.add_bar(x=labels, y=values(current), name="Tento týždeň", marker_color=SPORT_COLORS["run"])
    fig.add_bar(x=labels, y=values(average), name="Ø 4 predch. týždne", marker_color=GRAY)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text=f"{label} ({unit})")
    return apply_base_layout(fig, height=300)
