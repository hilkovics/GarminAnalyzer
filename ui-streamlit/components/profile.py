"""Workout profile: bars along time (width = step duration, height and colour = zone).

Takes the `WorkoutStepDTO` list the plan services return and draws what the watch will do: repeats are
expanded (a "2×" bracket marks each repeated block), an open step uses its effort zone. Seconds become minutes
here.
"""

import plotly.graph_objects as go

from training.services.dto import WorkoutStepDTO

from .format import fmt_num
from .plan import STEP_LABELS
from .theme import GRAY, ZONE_COLORS, apply_base_layout, empty_figure

_MAX_ZONE = 5


def expand_steps(steps: list[WorkoutStepDTO]) -> list[tuple[WorkoutStepDTO, float, float]]:
    """(step, start_s, end_s) in play order; a repeat block is unrolled `repeat` times."""
    out: list[tuple[WorkoutStepDTO, float, float]] = []
    clock = 0.0
    done_groups: set[int] = set()
    for step in steps:
        if step.group is None:
            out.append((step, clock, clock + step.duration_s))
            clock += step.duration_s
        elif step.group not in done_groups:
            done_groups.add(step.group)
            block = [s for s in steps if s.group == step.group]
            for _ in range(step.repeat or 1):
                for inner in block:
                    out.append((inner, clock, clock + inner.duration_s))
                    clock += inner.duration_s
    return out


def repeat_spans(steps: list[WorkoutStepDTO]) -> list[tuple[int, float, float]]:
    """(repeat count, start_s, end_s) of every repeat block that runs more than once."""
    spans: list[tuple[int, float, float]] = []
    clock = 0.0
    done: set[int] = set()
    for step in steps:
        if step.group is None:
            clock += step.duration_s
        elif step.group not in done:
            done.add(step.group)
            block = [s for s in steps if s.group == step.group]
            length = sum(s.duration_s for s in block) * (step.repeat or 1)
            if (step.repeat or 1) > 1:
                spans.append((step.repeat or 1, clock, clock + length))
            clock += length
    return spans


def _minutes(seconds: float) -> str:
    minutes = seconds / 60.0
    return fmt_num(minutes, 0 if abs(minutes - round(minutes)) < 0.05 else 1)


def workout_profile(steps: list[WorkoutStepDTO], *, height: int = 170) -> go.Figure:
    """One bar per (unrolled) step; ticks on the step boundaries in minutes, brackets over repeat blocks."""
    played = expand_steps(steps)
    if not played:
        return empty_figure("Tréning nemá kroky.", height=height)
    total = played[-1][2]
    fig = go.Figure()
    for zone in sorted({s.zone for s, _, _ in played}):
        rows = [(s, a, b) for s, a, b in played if s.zone == zone]
        fig.add_bar(
            x=[(a + b) / 2 / 60.0 for _, a, b in rows],
            y=[min(zone, _MAX_ZONE)] * len(rows),
            width=[(b - a) / 60.0 for _, a, b in rows],
            marker={"color": ZONE_COLORS[min(max(zone, 1), _MAX_ZONE)], "line": {"width": 0}},
            name=f"Z{zone}",
            customdata=[
                f"{STEP_LABELS.get(s.type, s.type)} · {_minutes(b - a)} min · Z{s.zone}" for s, a, b in rows
            ],
            hovertemplate="%{customdata}<extra></extra>",
        )
    bounds = sorted({0.0, *(b for _, _, b in played)})
    fig.update_xaxes(
        range=[0, total / 60.0],
        tickvals=[b / 60.0 for b in bounds],
        ticktext=[_minutes(b) + (" min" if b == total else "") for b in bounds],
        showgrid=False,
        zeroline=False,
    )
    fig.update_yaxes(range=[0, _MAX_ZONE + 0.2], visible=False, fixedrange=True)
    for count, start, end in repeat_spans(steps):
        x0, x1 = start / 60.0, end / 60.0
        fig.add_shape(
            type="path",
            path=f"M {x0} 1.02 L {x0} 1.07 L {x1} 1.07 L {x1} 1.02",  # paper units: above the plot area
            xref="x",
            yref="paper",
            line={"color": GRAY, "width": 1},
        )
        fig.add_annotation(
            x=(x0 + x1) / 2, y=1.08, xref="x", yref="paper", text=f"{count}×", showarrow=False,
            yanchor="bottom", font={"size": 12},
        )  # fmt: skip
    apply_base_layout(fig, height=height, legend=False)
    fig.update_layout(
        barmode="overlay",
        bargap=0,
        hovermode="closest",
        margin={"l": 8, "r": 28, "t": 34, "b": 8},  # room for the brackets and the last tick label
    )
    return fig
