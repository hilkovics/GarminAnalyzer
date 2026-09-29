"""Season, week plan, daily decision and workout status services (phase 6, METRICS §10).

Glue only: the coach logic lives in `training.planning` / `training.coach`; this module reads the DB rows,
calls it and assembles DTOs. Errors are mapped to `ServiceError`s (`PlanError` → InvalidInputError, an
unknown id → NotFoundError). Loads are TSS-equivalent points; durations seconds.
"""

import datetime as dt

from sqlalchemy import func, select
from sqlmodel import Session

from training import pipeline, planning
from training.analysis.readiness import band
from training.coach import season, template
from training.coach.workout import (
    PaceRangeTarget,
    RepeatStep,
    Workout,
    step_zone,
    total_duration_s,
)
from training.db.models import Activity, ActivityMetric, DailyLoad, Goal, PlannedWorkout
from training.services.dto import (
    DailyDecisionDTO,
    GoalDTO,
    GoalIn,
    PlannedWorkoutDTO,
    SeasonDTO,
    SeasonWeekDTO,
    WeekDayDTO,
    WeekPlanDTO,
    WorkoutStepDTO,
)
from training.services.errors import InvalidInputError, NotFoundError

GOAL_SPORTS = ("run", "bike")
STATUSES = ("done", "skipped", "planned")
SEASON_WEEKS_NO_GOAL = 20
SEASON_WEEKS_MAX = 60
PENDING = ("planned", "pushed")  # statuses that become "missed" once the date has passed


# --- goal ---------------------------------------------------------------------------------------------------


def _goal_dto(goal: Goal) -> GoalDTO:
    assert goal.id is not None
    return GoalDTO(
        id=goal.id,
        race_date=goal.race_date,
        distance_m=goal.distance_m,
        target_time_s=goal.target_time_s,
        sport=goal.sport,
        active=goal.active,
    )


def get_goal(session: Session, today: dt.date) -> GoalDTO | None:
    """The goal the season is planned against (active, earliest race on or after this week's Monday)."""
    goal = planning.active_goal(session, today)
    return _goal_dto(goal) if goal else None


def _deactivate_all(session: Session) -> None:
    for goal in session.execute(select(Goal).where(Goal.active.is_(True))).scalars():
        goal.active = False
        session.add(goal)


def set_goal(session: Session, data: GoalIn, *, today: dt.date) -> GoalDTO:
    """Store a new goal; an active one deactivates all others (there is a single active goal)."""
    if data.sport not in GOAL_SPORTS:
        raise InvalidInputError(f"sport must be one of {', '.join(GOAL_SPORTS)}")
    if data.race_date < today:
        raise InvalidInputError("the race date must not be in the past")
    if data.active:
        _deactivate_all(session)
    goal = Goal(
        race_date=data.race_date,
        distance_m=data.distance_m,
        target_time_s=data.target_time_s,
        sport=data.sport,
        active=data.active,
    )
    session.add(goal)
    session.commit()
    session.refresh(goal)
    return _goal_dto(goal)


def clear_goal(session: Session) -> None:
    """Deactivate every goal (rows are kept); the season falls back to the no-goal cycle."""
    _deactivate_all(session)
    session.commit()


# --- planned workouts ---------------------------------------------------------------------------------------


def _flat_steps(workout: Workout) -> list[WorkoutStepDTO]:
    out: list[WorkoutStepDTO] = []
    group = 0
    for item in workout.steps:
        inner, count, gid = (
            (item.steps, item.count, group) if isinstance(item, RepeatStep) else ([item], None, None)
        )
        group += isinstance(item, RepeatStep)
        for step in inner:
            target = step.target
            out.append(
                WorkoutStepDTO(
                    type=step.type,
                    duration_s=step.duration_s,
                    target_kind=target.kind,
                    zone=step_zone(step),
                    low_mps=target.low_mps if isinstance(target, PaceRangeTarget) else None,
                    high_mps=target.high_mps if isinstance(target, PaceRangeTarget) else None,
                    repeat=count,
                    group=gid,
                )
            )
    return out


def _planned_dto(session: Session, row: PlannedWorkout, today: dt.date) -> PlannedWorkoutDTO:
    assert row.id is not None
    workout = planning.workout_of(row)
    actual = session.get(ActivityMetric, row.completed_activity_id) if row.completed_activity_id else None
    return PlannedWorkoutDTO(
        id=row.id,
        date=row.date,
        sport=row.sport,
        name=row.name,
        key=workout.key,
        slot=workout.slot,
        status=row.status,
        missed=row.status in PENDING and row.date < today,
        estimated_load=row.estimated_load,
        duration_s=total_duration_s(workout),
        reason=row.reason,
        completed_activity_id=row.completed_activity_id,
        actual_load=actual.load_primary if actual is not None else None,
        steps=_flat_steps(workout),
        structure=row.structure,
    )


def get_planned(session: Session, planned_id: int, *, today: dt.date) -> PlannedWorkoutDTO:
    row = session.get(PlannedWorkout, planned_id)
    if row is None:
        raise NotFoundError(f"planned workout {planned_id} not found")
    return _planned_dto(session, row, today)


def set_status(session: Session, planned_id: int, status: str, *, today: dt.date) -> PlannedWorkoutDTO:
    """Mark a planned workout done / skipped, or back to planned (done also links a matching activity)."""
    if status not in STATUSES:
        raise InvalidInputError(f"status must be one of {', '.join(STATUSES)}")
    try:
        row = planning.set_status(session, planned_id, status)
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except planning.PlanError as exc:
        raise InvalidInputError(str(exc)) from exc
    return _planned_dto(session, row, today)


# --- daily decision -----------------------------------------------------------------------------------------


def _num(value: float | None) -> float | None:
    return None if value is None or value != value else float(value)


def _decision_dto(
    session: Session,
    row: PlannedWorkout,
    decision_rule: int | None,
    reason: str | None,
    created: bool,
    today: dt.date,
) -> DailyDecisionDTO:
    today_row = session.get(DailyLoad, row.date)
    prev_row = session.get(DailyLoad, row.date - dt.timedelta(days=1))
    readiness = _num(today_row.readiness) if today_row else None
    return DailyDecisionDTO(
        date=row.date,
        workout=_planned_dto(session, row, today),
        reason=reason if reason is not None else row.reason,
        rule=decision_rule,
        readiness=readiness,
        readiness_band=band(readiness),
        acwr=_num(prev_row.acwr) if prev_row else None,
        tsb=_num(today_row.tsb) if today_row else None,
        created=created,
    )


def get_today(session: Session, today: dt.date) -> DailyDecisionDTO:
    """Today's plan; decided (and stored) on the first call, the same plan afterwards."""
    try:
        row, decision = planning.plan_day(session, today)
    except planning.PlanError as exc:
        raise InvalidInputError(str(exc)) from exc
    rule, reason = (decision.rule, decision.reason) if decision else (None, None)
    return _decision_dto(session, row, rule, reason, decision is not None, today)


def regenerate(session: Session, day: dt.date, sport: str | None = None) -> DailyDecisionDTO:
    """Decide `day` again (forced), optionally for another sport; a done or skipped workout stays."""
    try:
        row, decision = planning.plan_day(session, day, force=True, sport_override=sport)
    except planning.PlanError as exc:
        raise InvalidInputError(str(exc)) from exc
    assert decision is not None
    return _decision_dto(session, row, decision.rule, decision.reason, True, day)


# --- season and week ----------------------------------------------------------------------------------------


def get_season(session: Session, today: dt.date) -> SeasonDTO:
    """This week plus the projected weeks up to the race week + 1 (20 weeks without a goal)."""
    goal = planning.active_goal(session, today)
    this_monday = season.monday(today)
    if goal is None:
        count = SEASON_WEEKS_NO_GOAL
    else:
        ahead = (season.monday(goal.race_date) - this_monday).days // 7
        count = min(ahead + 2, SEASON_WEEKS_MAX)
    race_monday = season.monday(goal.race_date) if goal else None
    weeks = [
        SeasonWeekDTO(
            monday=w.monday,
            phase=w.phase,
            recovery=w.recovery,
            days_to_race=w.days_to_race,
            ctl_start=w.ctl_start,
            target_load=w.target_load,
            run_target=w.run_target,
            bike_target=w.bike_target,
            is_current=w.monday == this_monday,
            is_race_week=w.monday == race_monday,
        )
        for w in planning.season_weeks(session, today, count)
    ]
    return SeasonDTO(
        today=today,
        goal=_goal_dto(goal) if goal else None,
        current_phase=weeks[0].phase,
        weeks=weeks,
    )


def get_week(session: Session, day: dt.date, *, today: dt.date) -> WeekPlanDTO:
    """The ISO week containing `day`: targets, the template role, the plan and the actual load per day."""
    monday = season.monday(day)
    sunday = monday + dt.timedelta(days=6)
    target = planning.week_target(session, day)
    athlete = pipeline.get_athlete(session)
    roles = template.week_roles(target.phase, athlete.preferred_days if athlete else None)
    loads = {
        r.date: r
        for r in session.execute(select(DailyLoad).where(DailyLoad.date.between(monday, sunday))).scalars()
    }
    counts = dict(
        session.execute(
            select(Activity.local_date, func.count())
            .where(Activity.local_date.between(monday, sunday))
            .group_by(Activity.local_date)
        ).all()
    )
    days = []
    for i, weekday in enumerate(template.WEEKDAYS):
        date = monday + dt.timedelta(days=i)
        planned = planning.planned_for(session, date)
        load = loads.get(date)
        days.append(
            WeekDayDTO(
                date=date,
                weekday=weekday,
                role=roles[weekday].role,
                planned=_planned_dto(session, planned[0], today) if planned else None,
                actual_load=float(load.load_total) if load else 0.0,
                activities=int(counts.get(date, 0)),
            )
        )
    done = sum(d.actual_load for d in days)
    return WeekPlanDTO(
        monday=monday,
        phase=target.phase,
        recovery=target.recovery,
        target_load=target.target_load,
        run_target=target.run_target,
        bike_target=target.bike_target,
        done_load=done,
        remaining_load=max(0.0, target.target_load - done),
        days=days,
    )
