"""Plán page: workout step text, status badges, season and week figures over the phase-6 DTOs.

DTO in, string / Plotly figure out; no Streamlit import. Seconds become "15 min" here, weekday codes Slovak
names; targets, phases and statuses come from the DTOs (nothing is decided here).
"""

import plotly.graph_objects as go

from training.services.dto import PlannedWorkoutDTO, SeasonDTO, WeekPlanDTO, WorkoutStepDTO

from .badges import Badge
from .format import fmt_pace, fmt_window
from .theme import AQUA, BLUE, GRAY, ORANGE, RED, YELLOW, apply_base_layout, empty_figure

PHASE_LABELS = {"base": "Základ", "build": "Budovanie", "peak": "Vrchol", "taper": "Ladenie"}
PHASE_COLORS = {"base": BLUE, "build": ORANGE, "peak": RED, "taper": AQUA}
PHASE_LIGHT = {  # recovery weeks: the phase colour, lighter
    "base": "rgba(42, 120, 214, 0.35)",
    "build": "rgba(235, 104, 52, 0.35)",
    "peak": "rgba(227, 73, 72, 0.35)",
    "taper": "rgba(27, 175, 122, 0.35)",
}
WEEKDAY_LABELS = {
    "mon": "Po",
    "tue": "Ut",
    "wed": "St",
    "thu": "Št",
    "fri": "Pi",
    "sat": "So",
    "sun": "Ne",
}
ROLE_LABELS = {
    "rest": "Voľno",
    "easy": "Ľahký",
    "long": "Dlhý",
    "q1": "Kvalita 1",
    "q2": "Kvalita 2",
}
STEP_LABELS = {
    "warmup": "Rozcvička",
    "work": "Záťaž",
    "recovery": "Oddych",
    "cooldown": "Vychladenie",
    "steady": "Rovnomerne",
}


def _target(step: WorkoutStepDTO) -> str:
    if step.target_kind == "open":
        return f"úsilie Z{step.zone}"
    if step.target_kind == "pace_range":
        span = (
            f" {fmt_pace(step.low_mps)}–{fmt_pace(step.high_mps)}" if step.low_mps and step.high_mps else ""
        )
        return f"Z{step.zone} tempo{span}"
    return f"Z{step.zone}"


def _short(step: WorkoutStepDTO) -> str:
    return f"{fmt_window(step.duration_s)} {_target(step)}"


def step_lines(steps: list[WorkoutStepDTO]) -> list[str]:
    """Readable lines: "Rozcvička 15 min Z2", "5× (6 min Z4 / 2 min Z1)"."""
    lines: list[str] = []
    seen: set[int] = set()
    for step in steps:
        if step.group is None:
            lines.append(f"{STEP_LABELS.get(step.type, step.type)} {_short(step)}")
        elif step.group not in seen:
            seen.add(step.group)
            body = " / ".join(_short(s) for s in steps if s.group == step.group)
            lines.append(f"{step.repeat}× ({body})")
    return lines


def status_badge(planned: PlannedWorkoutDTO | None, role: str | None = None) -> Badge:
    """done / skipped / missed / planned / rest; no plan on a template rest day is "voľno"."""
    if planned is None:
        return Badge("voľno", "gray") if role == "rest" else Badge("bez plánu", "gray")
    if planned.status == "done":
        return Badge("hotovo", "green")
    if planned.status == "skipped":
        return Badge("vynechané", "gray")
    if planned.missed:
        return Badge("zmeškané", "red")
    if planned.sport == "rest":
        return Badge("voľno", "gray")
    return Badge("odoslané" if planned.status == "pushed" else "plánované", "blue")


def season_chart(season: SeasonDTO) -> go.Figure:
    """Target load per week coloured by phase (recovery weeks lighter, hatched); now/race markers."""
    if not season.weeks:
        return empty_figure("Sezóna nie je k dispozícii.")
    fig = go.Figure()
    for phase, label in PHASE_LABELS.items():
        for recovery in (False, True):
            weeks = [w for w in season.weeks if w.phase == phase and w.recovery is recovery]
            if not weeks:
                continue
            fig.add_bar(
                x=[w.monday for w in weeks],
                y=[w.target_load for w in weeks],
                name=f"{label}{' (regenerácia)' if recovery else ''}",
                marker={
                    "color": PHASE_LIGHT[phase] if recovery else PHASE_COLORS[phase],
                    "line": {"color": PHASE_COLORS[phase], "width": 1 if recovery else 0},
                    "pattern": {"shape": "/" if recovery else "", "fgcolor": PHASE_COLORS[phase]},
                },
                customdata=[[w.run_target, w.bike_target, w.ctl_start] for w in weeks],
                hovertemplate="Týždeň od %{x|%d. %m.}: %{y:.0f}<br>beh %{customdata[0]:.0f}, "
                "bicykel %{customdata[1]:.0f}<br>CTL na začiatku %{customdata[2]:.0f}<extra></extra>",
            )
    top = max(w.target_load for w in season.weeks) or 1.0
    for flag, name, symbol, color in (
        ("is_current", "Tento týždeň", "triangle-down", YELLOW),
        ("is_race_week", "Preteky", "star", GRAY),
    ):
        weeks = [w for w in season.weeks if getattr(w, flag)]
        if weeks:
            fig.add_scatter(
                x=[w.monday for w in weeks],
                y=[w.target_load + 0.06 * top for w in weeks],
                mode="markers",
                name=name,
                marker={"symbol": symbol, "size": 14, "color": color, "line": {"width": 1, "color": "#333"}},
                hovertemplate=name + "<extra></extra>",
            )
    fig.update_layout(barmode="stack")
    fig.update_yaxes(title_text="Cieľová záťaž týždňa (TSS-ekv.)")
    return apply_base_layout(fig, height=360)


def week_chart(week: WeekPlanDTO) -> go.Figure:
    """Per weekday: estimated load of the plan next to the actual load."""
    labels = [f"{WEEKDAY_LABELS.get(d.weekday, d.weekday)} {d.date.day}. {d.date.month}." for d in week.days]
    planned = [d.planned.estimated_load or 0.0 if d.planned else 0.0 for d in week.days]
    fig = go.Figure()
    fig.add_bar(x=labels, y=planned, name="Plán (odhad)", marker_color="rgba(42, 120, 214, 0.40)")
    fig.add_bar(x=labels, y=[d.actual_load for d in week.days], name="Skutočnosť", marker_color=BLUE)
    fig.update_layout(barmode="group")
    fig.update_yaxes(title_text="Záťaž (TSS-ekv.)")
    return apply_base_layout(fig, height=300)


def phase_text(phase: str, recovery: bool = False) -> str:
    label = PHASE_LABELS.get(phase, phase)
    return f"{label} (regeneračný týždeň)" if recovery else label
