"""Plán page blocks: goal editor, this week, today's card, preferred-days editor.

Rendering and service calls only – every plan, target and reason comes from the DTOs; the buttons call
`training.services.plan` (and `settings` for the preferred days) and rerun the page.
"""

import datetime as dt

import _db
import pandas as pd
import streamlit as st
from components.badges import readiness_badge
from components.format import (
    DASH,
    fmt_date,
    fmt_duration,
    fmt_km,
    fmt_num,
    fmt_time_hms,
    parse_time_hms,
    sport_label,
)
from components.plan import ROLE_LABELS, WEEKDAY_LABELS, phase_text, status_badge, step_lines, week_chart
from pydantic import ValidationError

from training.config import get_settings
from training.services import plan as plan_service, plan_push, settings as settings_service
from training.services.dto import (
    AthleteDTO,
    AthleteIn,
    DailyDecisionDTO,
    GoalDTO,
    GoalIn,
    PreferredDayDTO,
    SeasonDTO,
    WeekPlanDTO,
)
from training.services.errors import ServiceError
from training.services.plan import (
    DEFAULT_PREFERRED_DAYS as DEFAULT_ROLES,
    PREFERRED_DAY_ROLES as ROLES,
    PREFERRED_WEEKDAYS as WEEKDAYS,
)

FLASH_KEY = "plan_flash"
DISTANCES = {"5 km": 5000.0, "10 km": 10000.0, "Polmaratón": 21097.5, "Maratón": 42195.0, "Vlastná": None}
GOAL_SPORTS = {"run": "Beh", "bike": "Bicykel"}
REGENERATE_SPORTS = {None: "Podľa pravidiel", "run": "Beh", "bike": "Bicykel"}
COACH_SPORTS = {None: "Podľa trénera", "run": "Beh", "bike": "Bicykel"}


def flash_and_rerun(message: str) -> None:
    """Show `message` after the rerun that refreshes everything computed from the changed plan."""
    st.session_state[FLASH_KEY] = message
    st.rerun()


def _call(action, success: str) -> None:
    """Run a service call; a ServiceError is shown, success reruns the page."""
    try:
        with _db.session() as session:
            action(session)
    except ServiceError as exc:
        st.error(str(exc))
    else:
        flash_and_rerun(success)


# --- goal ---------------------------------------------------------------------------------------------------


def goal_summary(goal: GoalDTO | None, season: SeasonDTO) -> None:
    if goal is None:
        st.info("Cieľ nie je nastavený – plán beží v nekonečnom cykle 3 týždne záťaž + 1 regenerácia.")
        return
    parts = [
        f"**{fmt_date(goal.race_date)}**",
        sport_label(goal.sport),
        fmt_km(goal.distance_m) if goal.distance_m else None,
        fmt_time_hms(goal.target_time_s) if goal.target_time_s else None,
    ]
    st.markdown(" · ".join(p for p in parts if p) + f" · aktuálna fáza: {phase_text(season.current_phase)}")


def goal_editor(goal: GoalDTO | None) -> None:
    """Date, distance preset or custom km, optional target time h:mm:ss, sport; plus "Zmazať cieľ"."""
    today = _db.today()
    presets = list(DISTANCES)
    preset_now = next((k for k, v in DISTANCES.items() if goal and v == goal.distance_m), "Vlastná")
    with st.form("goal_form"):
        c1, c2, c3 = st.columns(3)
        race_date = c1.date_input(
            "Dátum pretekov",
            value=goal.race_date if goal and goal.race_date >= today else today + dt.timedelta(weeks=12),
            min_value=today,
            key="goal_date",
        )
        preset = c2.selectbox(
            "Vzdialenosť", presets, index=presets.index(preset_now) if goal else 1, key="goal_preset"
        )
        custom_km = c2.number_input(
            "Vlastná vzdialenosť (km)",
            min_value=0.0,
            value=goal.distance_m / 1000 if goal and goal.distance_m and preset_now == "Vlastná" else 0.0,
            step=0.5,
            key="goal_km",
        )
        sport = c3.selectbox(
            "Šport",
            list(GOAL_SPORTS),
            index=list(GOAL_SPORTS).index(goal.sport) if goal else 0,
            format_func=GOAL_SPORTS.get,  # type: ignore[arg-type]
            key="goal_sport",
        )
        target = st.text_input(
            "Cieľový čas (h:mm:ss, nepovinné)",
            value=fmt_time_hms(goal.target_time_s) if goal and goal.target_time_s else "",
            key="goal_time",
        )
        submitted = st.form_submit_button("Uložiť cieľ")
    if submitted:
        try:
            distance = DISTANCES[preset] if DISTANCES[preset] is not None else custom_km * 1000 or None
            data = GoalIn(
                race_date=race_date,  # type: ignore[arg-type]
                distance_m=distance,
                target_time_s=parse_time_hms(target),
                sport=sport,  # type: ignore[arg-type]
            )
            _call(lambda s: plan_service.set_goal(s, data, today=today), "Cieľ uložený.")
        except (ValueError, ValidationError) as exc:
            st.error(str(exc))
    st.caption("Po zmene cieľa použi „Prepočítať“ pri dnešnom tréningu, aby sa zohľadnil nový plán.")
    if st.button("Zmazať cieľ", disabled=goal is None, key="goal_clear"):
        _call(plan_service.clear_goal, "Cieľ zmazaný.")


# --- week ---------------------------------------------------------------------------------------------------


def week_block(week: WeekPlanDTO) -> None:
    st.caption(
        f"Fáza: {phase_text(week.phase, week.recovery)} · cieľ {fmt_num(week.target_load)} "
        f"(beh {fmt_num(week.run_target)}, bicykel {fmt_num(week.bike_target)}) · hotovo "
        f"{fmt_num(week.done_load)} · zostáva {fmt_num(week.remaining_load)}"
    )
    st.plotly_chart(week_chart(week), width="stretch", key="plan_week_chart")
    rows = [
        {
            "Deň": f"{WEEKDAY_LABELS[d.weekday]} {fmt_date(d.date)}",
            "Rola": ROLE_LABELS.get(d.role, d.role),
            "Plán": (d.planned.name if d.planned else DASH),
            "Odhad záťaže": fmt_num(d.planned.estimated_load) if d.planned else DASH,
            "Skutočná záťaž": fmt_num(d.actual_load) if d.activities else DASH,
            "Stav": status_badge(d.planned, d.role).text,
        }
        for d in week.days
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


# --- today --------------------------------------------------------------------------------------------------


def today_card(decision: DailyDecisionDTO) -> None:
    """Workout name, steps, duration, estimated load, reason, readiness and the action buttons."""
    workout = decision.workout
    st.markdown(f"### {workout.name}  {status_badge(workout, None).markdown}")
    if workout.sport == "rest":
        st.write("Dnes voľno – oddych je súčasť tréningu.")
    else:
        st.caption(f"{sport_label(workout.sport)} · {fmt_duration(workout.duration_s)} h")
        for line in step_lines(workout.steps):
            st.markdown(f"- {line}")
        c1, c2 = st.columns(2)
        c1.metric("Odhad záťaže", fmt_num(workout.estimated_load))
        c2.metric("Skutočná záťaž", fmt_num(workout.actual_load) if workout.actual_load else DASH)
    if decision.reason:
        st.markdown(f"*{decision.reason}*")
    if decision.readiness is None:
        st.caption("Pripravenosť: bez wellness dát.")
    else:
        st.markdown(
            f"Pripravenosť: **{int(decision.readiness)}** {readiness_badge(decision.readiness_band).markdown}"
            f" · ACWR {fmt_num(decision.acwr, 2)} · TSB {fmt_num(decision.tsb, 1)}"
        )
    _today_buttons(decision)


def _today_buttons(decision: DailyDecisionDTO) -> None:
    workout = decision.workout
    today = _db.today()
    closed = workout.status in ("done", "skipped")
    cols = st.columns(3)
    in_garmin = workout.garmin_workout_id is not None
    if workout.sport == "rest" and in_garmin and not closed:  # a regeneration to rest (METRICS §10.8)
        st.caption("Pôvodný tréning je ešte v Garmin Connect kalendári.")
        if cols[0].button("Odstrániť z Garmin", key="plan_push"):
            _call(
                lambda s: plan_push.push_planned(s, workout.id, settings=get_settings()),
                "Odstránené z Garmin.",
            )
    if workout.sport != "rest":
        if closed:
            if cols[0].button("Späť na plánované", key="plan_undo"):
                _call(lambda s: plan_service.set_status(s, workout.id, "planned", today=today), "Vrátené.")
        else:
            if cols[0].button("Hotovo", key="plan_done", type="primary"):
                _call(lambda s: plan_service.set_status(s, workout.id, "done", today=today), "Hotovo.")
            if cols[1].button("Vynechať", key="plan_skip"):
                _call(lambda s: plan_service.set_status(s, workout.id, "skipped", today=today), "Vynechané.")
            label = "Aktualizovať v Garmin" if in_garmin else "Poslať do Garmin"
            if in_garmin and workout.status == "planned":
                st.caption("Plán sa zmenil – v Garmin je ešte predchádzajúca verzia, aktualizuj ju.")
            if cols[2].button(label, key="plan_push"):
                _call(
                    lambda s: plan_push.push_planned(s, workout.id, settings=get_settings()),
                    "Tréning je v Garmin Connect kalendári – hodinky ho dostanú pri ďalšej synchronizácii.",
                )
    left, right = st.columns([2, 1], vertical_alignment="bottom")
    sport = left.selectbox(
        "Prepočítať pre šport",
        list(REGENERATE_SPORTS),
        format_func=REGENERATE_SPORTS.get,  # type: ignore[arg-type]
        key="plan_regen_sport",
        disabled=closed,
    )
    if right.button("Prepočítať", key="plan_regen", disabled=closed):
        _call(lambda s: plan_service.regenerate(s, decision.date, sport), "Plán prepočítaný.")


# --- preferred days -----------------------------------------------------------------------------------------


def preferred_days_editor(athlete: AthleteDTO | None) -> None:
    """Weekday → role [+ sport] (METRICS §10.3); saved through the settings service."""
    current = athlete.preferred_days if athlete and athlete.preferred_days else {}
    roles = list(ROLES)
    sports = list(COACH_SPORTS)
    values: dict[str, PreferredDayDTO] = {}
    with st.form("preferred_days_form"):
        for day in WEEKDAYS:
            now = current.get(day, PreferredDayDTO(role=DEFAULT_ROLES[day]))
            c1, c2, c3 = st.columns([1, 2, 2])
            c1.markdown(f"**{WEEKDAY_LABELS[day]}**")
            role = c2.selectbox(
                "Rola",
                roles,
                index=roles.index(now.role),
                format_func=ROLE_LABELS.get,  # type: ignore[arg-type]
                key=f"pd_role_{day}",
                label_visibility="collapsed",
            )
            sport = c3.selectbox(
                "Šport",
                sports,
                index=sports.index(now.sport),
                format_func=COACH_SPORTS.get,  # type: ignore[arg-type]
                key=f"pd_sport_{day}",
                label_visibility="collapsed",
            )
            values[day] = PreferredDayDTO(role=role, sport=None if role == "rest" else sport)
        save = st.form_submit_button("Uložiť dni")
    if save:
        _save_days(values, "Preferované dni uložené.")
    if st.button("Predvolené dni", key="pd_reset"):
        _save_days({}, "Preferované dni vrátené na predvolené.")


def _save_days(days: dict[str, PreferredDayDTO], message: str) -> None:
    _call(
        lambda s: settings_service.update_athlete(s, AthleteIn(preferred_days=days), today=_db.today()),
        message,
    )
