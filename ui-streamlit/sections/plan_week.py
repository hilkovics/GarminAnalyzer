"""Plán page: "Tento týždeň" – the target line, planned-vs-done chart, seven day cards and the table.

Rendering only. Every number, status and role comes from `WeekPlanDTO`; the day card is a bordered container
per weekday (the columns stack on a narrow screen), today's card carries a key that `_style.py` outlines.
"""

import datetime as dt

import streamlit as st
from components.format import DASH, fmt_date, fmt_num
from components.plan import (
    ROLE_LABELS,
    ROLE_SHORT,
    SPORT_ICONS,
    WEEKDAY_LABELS,
    phase_text,
    status_badge,
    week_chart,
)

from training.services.dto import WeekDayDTO, WeekPlanDTO


def _estimate(day: WeekDayDTO) -> str:
    return fmt_num(day.planned.estimated_load) if day.planned and day.planned.sport != "rest" else DASH


def _actual(day: WeekDayDTO) -> str:
    return fmt_num(day.actual_load) if day.activities else DASH


def day_card(day: WeekDayDTO, *, is_today: bool) -> None:
    """Weekday + date + role chip, workout name, estimate / actual load and the status badge."""
    planned = day.planned
    icon = SPORT_ICONS.get(planned.sport, "") if planned else ""
    name = planned.name if planned else DASH
    key = f"daycard_{'today_' if is_today else ''}{day.weekday}"
    with st.container(border=True, key=key):
        st.markdown(
            f"**{WEEKDAY_LABELS[day.weekday]}** {day.date.day}. {day.date.month}. "
            f":gray-badge[{ROLE_SHORT.get(day.role, day.role)}]"
        )
        st.markdown(f"{icon} {name}".strip())
        commute = f"  \nDoch. {fmt_num(day.commute_load)}" if day.commute_load else ""
        st.caption(f"Odhad {_estimate(day)}  \nSkut. {_actual(day)}{commute}")
        st.markdown(status_badge(planned, day.role).markdown)


def week_table(week: WeekPlanDTO) -> str:
    """The week as a markdown table; the status column is a coloured badge."""
    lines = [
        "| Deň | Rola | Plán | Odhad záťaže | Skutočná záťaž | Stav |",
        "|---|---|---|---|---|---:|",
    ]
    for d in week.days:
        name = (d.planned.name if d.planned else DASH).replace("|", "/")
        lines.append(
            f"| {WEEKDAY_LABELS[d.weekday]} {fmt_date(d.date)} | {ROLE_LABELS.get(d.role, d.role)} | {name} "
            f"| {_estimate(d)} | {_actual(d)} | {status_badge(d.planned, d.role).markdown} |"
        )
    return "\n".join(lines)


def week_block(week: WeekPlanDTO, today: dt.date | None = None) -> None:
    st.caption(
        f"Fáza: {phase_text(week.phase, week.recovery)} · cieľ {fmt_num(week.target_load)} "
        f"(beh {fmt_num(week.run_target)}, bicykel {fmt_num(week.bike_target)}) · hotovo "
        f"{fmt_num(week.done_load)} · zostáva {fmt_num(week.remaining_load)}"
    )
    st.plotly_chart(week_chart(week), width="stretch", key="plan_week_chart")
    for col, day in zip(st.columns(len(week.days)), week.days, strict=True):
        with col:
            day_card(day, is_today=day.date == today)
    with st.expander("Tabuľka týždňa"):
        st.markdown(week_table(week))
