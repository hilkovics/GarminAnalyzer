"""Phase-6 coach glue: DB ↔ pure `training.coach` functions (METRICS §10). Fully offline.

- `week_target` / `season_weeks`: §10.1–§10.2 from the active goal, the stored CTL and the run:bike split.
- `build_context` assembles the §10.4 inputs for one day; `plan_day` runs `coach.rules.decide` and persists
  the result as a `planned_workout` (one per day; kept unless regenerated).
- `match_completed`: a planned workout is done when an activity of the same sport exists on its date.
- `nightly` = match + plan today if nothing is planned yet, or decide again an automatic plan made before
  the day's sync (called at the end of `training sync` and `POST /sync`).
"""

import datetime as dt
import logging

from sqlalchemy import func, select
from sqlmodel import Session

from training.coach import library, rules, season, template
from training.coach.workout import estimated_load, from_structure, to_structure
from training.db import repo
from training.db.models import Activity, ActivityMetric, Athlete, DailyLoad, Goal, PlannedWorkout
from training.db.state_keys import LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE

log = logging.getLogger(__name__)

SHARE_DAYS = 28
REPLACEABLE = ("planned", "pushed")  # statuses a regeneration may overwrite
STATUSES = ("planned", "pushed", "done", "skipped")


class PlanError(ValueError):
    """Invalid plan request (unknown workout, status, sport, or a done workout that cannot be replaced)."""


# --- inputs ------------------------------------------------------------------------------------------------


def active_goal(session: Session, day: dt.date) -> Goal | None:
    """The active goal with the earliest race date on or after the Monday of `day` (§10.1 clarified)."""
    return session.execute(
        select(Goal)
        .where(Goal.active.is_(True), Goal.race_date >= season.monday(day))
        .order_by(Goal.race_date, Goal.id)
        .limit(1)
    ).scalar()


def _athlete(session: Session) -> Athlete | None:
    return session.execute(select(Athlete).order_by(Athlete.id).limit(1)).scalar()


def _daily(session: Session, day: dt.date) -> DailyLoad | None:
    return session.get(DailyLoad, day)


def _ctl_before(session: Session, monday: dt.date) -> float:
    """CTL of the day before `monday`, 0 if unknown (§10.2 clarified; `daily_load` rows are dense)."""
    row = _daily(session, monday - dt.timedelta(days=1))
    return float(row.ctl) if row is not None and row.ctl is not None else 0.0


def run_share_for(session: Session, day: dt.date) -> float:
    """§10.2 run share from the 28 days before the week's Monday (stable within a week)."""
    athlete = _athlete(session)
    day = season.monday(day)
    start = day - dt.timedelta(days=SHARE_DAYS)
    run, bike = session.execute(
        select(
            func.coalesce(func.sum(DailyLoad.load_run), 0.0),
            func.coalesce(func.sum(DailyLoad.load_bike), 0.0),
        ).where(DailyLoad.date >= start, DailyLoad.date < day)
    ).one()
    return season.run_share(athlete.run_bike_split if athlete else None, float(run), float(run) + float(bike))


def _race_date(goal: Goal | None) -> dt.date | None:
    return goal.race_date if goal is not None else None


def _pre_taper_target(session: Session, monday: dt.date, race_date: dt.date | None) -> float | None:
    """Inside the taper: the target of the last pre-taper week from *its* stored CTL (review phase 6 B1),
    so every taper week is 0.5 × the same reference (§10.2 clarified, no compounding)."""
    if season.week_info(monday, race_date).phase != "taper":
        return None
    reference = season.pre_taper_monday(monday, race_date)
    return season.weekly_target(_ctl_before(session, reference), season.week_info(reference, race_date))


def season_weeks(session: Session, today: dt.date, weeks: int) -> list[season.WeekTarget]:
    """This week plus `weeks − 1` projected weeks (targets assumed to be met, §10.2 clarified)."""
    monday = season.monday(today)
    race_date = _race_date(active_goal(session, today))
    return season.season_plan(
        monday,
        weeks,
        _ctl_before(session, monday),
        race_date,
        run_share_for(session, today),
        pre_taper_target=_pre_taper_target(session, monday, race_date),
    )


def week_target(session: Session, day: dt.date) -> season.WeekTarget:
    """§10.2 target of the week containing `day`, from the stored CTL before its Monday."""
    return season_weeks(session, day, 1)[0]


def _sum_load(session: Session, start: dt.date, end: dt.date) -> tuple[float, float, float]:
    total, run, bike = session.execute(
        select(
            func.coalesce(func.sum(DailyLoad.load_total), 0.0),
            func.coalesce(func.sum(DailyLoad.load_run), 0.0),
            func.coalesce(func.sum(DailyLoad.load_bike), 0.0),
        ).where(DailyLoad.date >= start, DailyLoad.date < end)
    ).one()
    return float(total), float(run), float(bike)


def _done_sessions(session: Session, start: dt.date, end: dt.date) -> tuple[rules.DoneSession, ...]:
    rows = session.execute(
        select(PlannedWorkout)
        .where(PlannedWorkout.status == "done", PlannedWorkout.date >= start, PlannedWorkout.date < end)
        .order_by(PlannedWorkout.date, PlannedWorkout.id)
    ).scalars()
    out = []
    for row in rows:
        structure = row.structure or {}
        out.append(
            rules.DoneSession(
                date=row.date,
                sport=row.sport,
                key=str(structure.get("key") or ""),
                slot=structure.get("slot"),
            )
        )
    return tuple(out)


def _yesterday_max_if(session: Session, day: dt.date) -> float | None:
    rows = session.execute(
        select(ActivityMetric.load_method, ActivityMetric.if_hr, ActivityMetric.if_pace)
        .join(Activity, Activity.id == ActivityMetric.activity_id)
        .where(Activity.local_date == day - dt.timedelta(days=1))
    ).all()
    values = [(r.if_pace if (r.load_method or "").lower() == "rtss" else r.if_hr) for r in rows]
    values = [float(v) for v in values if v is not None]
    return max(values) if values else None


def _num(value: object) -> float | None:
    return None if value is None or value != value else float(value)  # type: ignore[arg-type]


def build_context(session: Session, day: dt.date, sport_override: str | None = None) -> rules.DayContext:
    """METRICS §10.4 clarified inputs for day `day`."""
    monday = season.monday(day)
    goal = active_goal(session, day)
    info = season.week_info(monday, _race_date(goal))
    athlete = _athlete(session)
    target = week_target(session, day)
    total, run, bike = _sum_load(session, monday, day)
    active = frozenset(
        session.execute(
            select(Activity.local_date).where(Activity.local_date >= monday, Activity.local_date < day)
        ).scalars()
    )
    today_row, prev_row = _daily(session, day), _daily(session, day - dt.timedelta(days=1))
    return rules.DayContext(
        day=day,
        info=info,
        roles=template.week_roles(info.phase, athlete.preferred_days if athlete else None),
        weekly_target=target.target_load,
        run_target=target.run_target,
        bike_target=target.bike_target,
        load_done_week=total,
        run_load_done_week=run,
        bike_load_done_week=bike,
        active_days_week=active,
        done=_done_sessions(session, min(monday, day - dt.timedelta(days=7)), day),
        yesterday_max_if=_yesterday_max_if(session, day),
        readiness=_num(today_row.readiness) if today_row else None,
        tsb=_num(today_row.tsb) if today_row else None,
        acwr_prev=_num(prev_row.acwr) if prev_row else None,
        monotony_prev=_num(prev_row.monotony) if prev_row else None,
        goal_sport=goal.sport if goal else None,
        race_zone=library.race_zone(
            goal.sport if goal else None,
            goal.distance_m if goal else None,
            goal.target_time_s if goal else None,
        ),
        sport_override=sport_override,
    )


# --- planned workouts --------------------------------------------------------------------------------------


def planned_for(session: Session, day: dt.date) -> list[PlannedWorkout]:
    return list(
        session.execute(
            select(PlannedWorkout).where(PlannedWorkout.date == day).order_by(PlannedWorkout.id)
        ).scalars()
    )


def plan_day(
    session: Session, day: dt.date, *, force: bool = False, sport_override: str | None = None
) -> tuple[PlannedWorkout, rules.Decision | None]:
    """Today's planned workout: the existing one unless `force`; else decide (§10.4) and store it.

    A regeneration replaces planned/pushed rows of that day; a done or skipped workout is never replaced.
    Returns the row and the decision (None when an existing row was kept).
    """
    if sport_override is not None and sport_override not in template.SPORTS:
        raise PlanError(f"sport must be one of {', '.join(template.SPORTS)}")
    existing = planned_for(session, day)
    if existing and not force and sport_override is None:
        return existing[0], None
    user = force or sport_override is not None
    return _decide_and_store(session, day, existing, sport_override, origin="user" if user else "auto")


def _inputs_complete(session: Session, day: dt.date) -> bool:
    """Whether the day's sync already ran: daily_load[D] exists and both sync cursors reached D.

    The activity cursor is saved before the wellness fetch, so readiness also needs the wellness cursor.
    """
    if _daily(session, day) is None:
        return False
    cursors = [repo.get_state_date(session, key) for key in (LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE)]
    return all(c is not None and c >= day for c in cursors)


def is_provisional(row: PlannedWorkout) -> bool:
    """An automatic decision made before the day's sync (review phase 6 B2): the nightly step redoes it."""
    structure = row.structure or {}
    return (
        row.status == "planned" and structure.get("origin") == "auto" and bool(structure.get("provisional"))
    )


def _decide_and_store(
    session: Session, day: dt.date, existing: list[PlannedWorkout], sport_override: str | None, *, origin: str
) -> tuple[PlannedWorkout, rules.Decision]:
    if any(row.status not in REPLACEABLE for row in existing):
        raise PlanError(f"{day} already has a done or skipped workout – it is not replaced")
    decision = rules.decide(build_context(session, day, sport_override))
    provisional = not _inputs_complete(session, day)  # before the delete: a flush would free the old id
    for row in existing:
        session.delete(row)
    workout = decision.workout
    structure = {**to_structure(workout), "origin": origin, "provisional": provisional}
    row = PlannedWorkout(
        date=day,
        sport=workout.sport,
        name=workout.name,
        structure=structure,
        estimated_load=round(estimated_load(workout), 1),
        reason=decision.reason,
        status="planned",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row, decision


def set_status(session: Session, planned_id: int, status: str) -> PlannedWorkout:
    """Manual done / skipped (POST /plan/{id}/status). "planned" undoes a manual mark."""
    if status not in ("done", "skipped", "planned"):
        raise PlanError("status must be done, skipped or planned")
    row = session.get(PlannedWorkout, planned_id)
    if row is None:
        raise LookupError(f"planned workout {planned_id} not found")
    row.status = status
    if status != "done":
        row.completed_activity_id = None
    else:
        row.completed_activity_id = row.completed_activity_id or _matching_activity(session, row)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _matching_activity(session: Session, row: PlannedWorkout) -> int | None:
    """The longest activity of the planned sport on the planned date (date + sport match, PLAN phase 6)."""
    if row.sport == "rest":
        return None
    return session.execute(
        select(Activity.id)
        .where(Activity.local_date == row.date, Activity.sport == row.sport)
        .order_by(func.coalesce(Activity.moving_s, Activity.duration_s, 0).desc(), Activity.id)
        .limit(1)
    ).scalar()


def match_completed(session: Session, today: dt.date) -> int:
    """Mark planned/pushed workouts up to `today` done when a same-sport activity exists that day."""
    rows = session.execute(
        select(PlannedWorkout).where(
            PlannedWorkout.status.in_(REPLACEABLE),
            PlannedWorkout.date <= today,
            PlannedWorkout.sport != "rest",
        )
    ).scalars()
    matched = 0
    for row in rows:
        activity_id = _matching_activity(session, row)
        if activity_id is not None:
            row.status, row.completed_activity_id = "done", activity_id
            session.add(row)
            matched += 1
    session.commit()
    return matched


def nightly(session: Session, today: dt.date) -> PlannedWorkout:
    """`training sync` step: match completed workouts, then plan today if nothing is planned yet.

    An automatic plan decided before this sync (e.g. the page was opened first) is decided again with the
    fresh readiness/TSB and done sessions; user regenerations, pushed, done and skipped rows are kept.
    """
    match_completed(session, today)
    existing = planned_for(session, today)
    if existing and all(is_provisional(row) for row in existing):
        row, _ = _decide_and_store(session, today, existing, None, origin="auto")
        return row
    row, _ = plan_day(session, today)
    return row


def workout_of(row: PlannedWorkout):  # -> coach.workout.Workout
    return from_structure(row.structure)
