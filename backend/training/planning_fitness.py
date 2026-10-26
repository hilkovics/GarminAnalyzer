"""Fitness coach glue: DB ↔ the pure `training.coach.fitness` rules (METRICS §11). Fully offline.

- `ensure_week`: the §11.3 numbers of an ISO week, created on first use (a block of 12 weeks starts when none
  is open; missing weeks in between are filled in order, so the progression never skips a brake).
- `build_context`: the §11.2 inputs for one day (menu items done, yesterday, readiness, available days).
- `sleep_missing` / `before_noon`: the §11.2 "wait for last night's sleep until 12:00" rule.
Commutes (§2.6) never count as runs or hard days here.
"""

import datetime as dt
import logging
import statistics
from collections.abc import Callable

from sqlalchemy import func, not_, select
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from training import localtime
from training.coach import fitness
from training.commute import commute_expr
from training.db.models import (
    Activity,
    ActivityMetric,
    Athlete,
    CoachBlock,
    CoachWeek,
    DailyLoad,
    DailyWellness,
    PlannedWorkout,
)

log = logging.getLogger(__name__)

HARD_SK = {"k": "kvalitný tréning", "d": "dlhší beh"}
CHECK_KEY = "fit_check"


def now_local() -> dt.datetime:
    """The wall clock in the system's zone (patched in tests)."""
    return dt.datetime.now(localtime.local_zone())


def monday_of(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


# --- §11.3 weeks and blocks ---------------------------------------------------------------------------------


def weekly_run_seconds(session: Session, monday: dt.date) -> float:
    """Non-commute run moving time of the ISO week starting `monday`."""
    total = session.execute(
        select(func.coalesce(func.sum(func.coalesce(Activity.moving_s, Activity.duration_s)), 0.0)).where(
            Activity.sport == "run",
            Activity.local_date >= monday,
            Activity.local_date < monday + dt.timedelta(days=7),
            not_(commute_expr()),
        )
    ).scalar_one()
    return float(total)


def _brake_for(session: Session, monday: dt.date) -> str | None:
    """§11.3 brake from the 7 days before `monday`: mean readiness, Sunday's sleep debt and ACWR."""
    from training.analysis.wellness import with_baselines  # local: keeps the import graph light
    from training.pipeline_wellness import wellness_frame

    start, sunday = monday - dt.timedelta(days=7), monday - dt.timedelta(days=1)
    rows = session.execute(
        select(DailyLoad.readiness).where(DailyLoad.date >= start, DailyLoad.date <= sunday)
    ).scalars()
    values = [float(r) for r in rows if r is not None]
    mean_readiness = statistics.fmean(values) if values else None
    sunday_row = session.get(DailyLoad, sunday)
    acwr = sunday_row.acwr if sunday_row is not None else None
    frame = with_baselines(wellness_frame(session, sunday - dt.timedelta(days=40), sunday))
    debt = None
    if sunday in frame.index and "sleep_debt_7" in frame.columns:
        value = frame.loc[sunday, "sleep_debt_7"]
        debt = None if value != value else float(value)  # NaN → missing
    return fitness.brake(mean_readiness, debt, acwr)


def _open_block(session: Session, monday: dt.date) -> CoachBlock | None:
    block = (
        session.execute(
            select(CoachBlock)
            .where(CoachBlock.start_monday <= monday)
            .order_by(CoachBlock.start_monday.desc())
        )
        .scalars()
        .first()
    )
    if block is None or monday >= block.start_monday + dt.timedelta(weeks=fitness.BLOCK_WEEKS):
        return None
    return block


def _inputs_complete(session: Session, monday: dt.date) -> bool:
    """§11.3: the week's numbers are final once the Monday sync ran (Sunday's data and ACWR are in)."""
    from training import planning  # local: planning imports this module

    return planning._inputs_complete(session, monday)


def _start_base(session: Session, monday: dt.date) -> float:
    weeks = [weekly_run_seconds(session, monday - dt.timedelta(weeks=i)) for i in range(1, 5)]
    return fitness.first_base(weeks)


def _derive(session: Session, block: CoachBlock, previous: CoachWeek | None, row: CoachWeek) -> None:
    """Fill `row`'s §11.3 numbers from the previous week and the data before its Monday."""
    if row.week_no == 1:
        block.base_s = _start_base(session, block.start_monday)
        session.add(block)
    reason = None if row.week_no == 1 else _brake_for(session, row.monday)
    load = fitness.week_load(row.week_no, previous.base_s if previous else None, reason, block.base_s)
    row.base_s, row.target_s, row.brake = load.base_s, load.target_s, load.brake
    row.recovery, row.test = load.recovery, load.test
    row.final = _inputs_complete(session, row.monday)
    session.add(row)


def _fill(session: Session, block: CoachBlock, upto: dt.date, rederive: bool = False) -> None:
    """Create the block's weeks up to `upto` in order; a week that is not final (its Monday sync has not run
    yet) is derived again, and so is every week after one that changed."""
    assert block.id is not None
    week_no = (upto - block.start_monday).days // 7 + 1
    previous: CoachWeek | None = None
    changed = rederive
    for no in range(1, week_no + 1):
        day = block.start_monday + dt.timedelta(weeks=no - 1)
        row = session.get(CoachWeek, day)
        if row is None:
            row = CoachWeek(monday=day, block_id=block.id, week_no=no, base_s=0.0, target_s=0.0)
            changed = True
        elif not row.final:
            changed = True
        if changed:
            _derive(session, block, previous, row)
            session.flush()
        previous = row


def ensure_week(session: Session, monday: dt.date) -> CoachWeek:
    """The §11.3 row of the week starting `monday` (created on first use, kept up to date until final;
    commits). A concurrent writer that created the same rows first wins (IntegrityError → re-read)."""
    existing = session.get(CoachWeek, monday)
    if existing is not None and existing.final:
        return existing
    try:
        block = _open_block(session, monday)
        if block is None:
            block = CoachBlock(start_monday=monday, base_s=_start_base(session, monday))
            session.add(block)
            session.flush()
        _fill(session, block, monday)
        session.commit()
    except IntegrityError:
        session.rollback()
        log.info("coach week %s was created concurrently – re-reading", monday)
    result = session.get(CoachWeek, monday)
    if result is None:
        raise LookupError(f"coach week {monday} could not be created")
    return result


def rederive_weeks(session: Session) -> int:
    """`recompute`: derive every stored week again from the current data (block starts stay); commits."""
    blocks = session.execute(select(CoachBlock).order_by(CoachBlock.start_monday)).scalars().all()
    count = 0
    for block in blocks:
        last = session.execute(
            select(func.max(CoachWeek.monday)).where(CoachWeek.block_id == block.id)
        ).scalar_one()
        if last is not None:
            _fill(session, block, last, rederive=True)
            count += (last - block.start_monday).days // 7 + 1
    session.commit()
    return count


def week_load_of(row: CoachWeek) -> fitness.WeekLoad:
    return fitness.WeekLoad(row.week_no, row.base_s, row.target_s, row.brake, row.recovery, row.test)


# --- §11.2 inputs -------------------------------------------------------------------------------------------


def available_days(athlete: Athlete | None, monday: dt.date) -> frozenset[dt.date]:
    """Days of the week not marked "rest" in the athlete's preferred days (all seven by default)."""
    prefs = (athlete.preferred_days if athlete else None) or {}
    days = []
    for i, code in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun")):
        value = prefs.get(code)
        role = value.get("role") if isinstance(value, dict) else value
        if role != "rest":
            days.append(monday + dt.timedelta(days=i))
    return frozenset(days)


def _done_slots(session: Session, start: dt.date, end: dt.date) -> dict[dt.date, tuple[str, str]]:
    """Done fitness slots by date in [start, end): (slot, key)."""
    rows = session.execute(
        select(PlannedWorkout).where(
            PlannedWorkout.status == "done", PlannedWorkout.date >= start, PlannedWorkout.date < end
        )
    ).scalars()
    out = {}
    for row in rows:
        structure = row.structure or {}
        slot = structure.get("slot")
        if slot in fitness.SLOTS:
            out[row.date] = (slot, str(structure.get("key") or ""))
    return out


def _runs_per_day(session: Session, start: dt.date, end: dt.date) -> dict[dt.date, int]:
    """Non-commute runs per day in [start, end)."""
    rows = session.execute(
        select(Activity.local_date, func.count())
        .where(
            Activity.sport == "run",
            Activity.local_date >= start,
            Activity.local_date < end,
            not_(commute_expr()),
        )
        .group_by(Activity.local_date)
    ).all()
    return {day: int(n) for day, n in rows}


def _run_days(session: Session, start: dt.date, end: dt.date) -> set[dt.date]:
    return set(_runs_per_day(session, start, end))


def _extra_run_days(session: Session, start: dt.date, end: dt.date, done: dict) -> list[dt.date]:
    """Days with a run that fulfilled no planned slot (a done plan uses up one run of its day), §11.1."""
    return sorted(
        day for day, n in _runs_per_day(session, start, end).items() if n > (1 if day in done else 0)
    )


def open_items(session: Session, day: dt.date) -> frozenset[str]:
    """§11.1: menu items not yet done on `Mon … day−1` (an unplanned run fills Ľ)."""
    monday = monday_of(day)
    done = _done_slots(session, monday, day)
    remaining = set(fitness.SLOTS) - {slot for slot, _ in done.values()}
    extra_runs = _extra_run_days(session, monday, day, done)
    if extra_runs and "e" in remaining:
        remaining.discard("e")
    return frozenset(remaining)


def menu_done(session: Session, monday: dt.date) -> dict[str, dt.date]:
    """§11.1 menu items done in the ISO week starting `monday` → the day each was done (an unplanned run fills
    Ľ, as in `open_items`)."""
    end = monday + dt.timedelta(days=7)
    done = _done_slots(session, monday, end)
    out: dict[str, dt.date] = {}
    for day, (slot, _) in sorted(done.items()):
        out.setdefault(slot, day)
    extra_runs = _extra_run_days(session, monday, end, done)
    if extra_runs and "e" not in out:
        out["e"] = extra_runs[0]
    return out


def existing_week(session: Session, monday: dt.date, today: dt.date) -> CoachWeek | None:
    """The stored §11.3 week; this week's row is created on first use, other weeks are never created here
    (a past week before the first block has none, a future week depends on brakes not known yet)."""
    row = session.get(CoachWeek, monday)
    if row is None and monday == monday_of(today):
        row = ensure_week(session, monday)
    return row


def hard_yesterday(session: Session, day: dt.date) -> str | None:
    """§11.2: Slovak description of a hard session on `day − 1`, or None."""
    yesterday = day - dt.timedelta(days=1)
    done = _done_slots(session, yesterday, day).get(yesterday)
    if done is not None and done[0] in HARD_SK:
        return "kontrolný beh" if done[1] == CHECK_KEY else HARD_SK[done[0]]
    rows = session.execute(
        select(
            Activity.sport,
            Activity.moving_s,
            ActivityMetric.load_method,
            ActivityMetric.if_hr,
            ActivityMetric.if_pace,
        )
        .join(ActivityMetric, ActivityMetric.activity_id == Activity.id, isouter=True)
        .where(Activity.local_date == yesterday, not_(commute_expr()))
    ).all()
    for sport, moving, method, if_hr, if_pace in rows:
        intensity = if_pace if (method or "").lower() == "rtss" else if_hr
        if intensity is not None and intensity >= fitness.QUALITY_IF:
            return "náročný tréning"
        if sport == "bike" and moving is not None and moving >= fitness.HARD_RIDE_S:
            return "dlhá jazda na bicykli"
    return None


def build_context(
    session: Session, day: dt.date, sport_override: str | None = None
) -> fitness.FitnessContext:
    """METRICS §11.2 inputs for `day`."""
    monday = monday_of(day)
    week = ensure_week(session, monday)
    load_row = session.get(DailyLoad, day)
    readiness = load_row.readiness if load_row is not None else None
    athlete = session.execute(select(Athlete)).scalars().first()
    return fitness.FitnessContext(
        day=day,
        readiness=readiness,
        available=available_days(athlete, monday),
        open_items=open_items(session, day),
        hard_yesterday=hard_yesterday(session, day),
        ran_yesterday=(day - dt.timedelta(days=1)) in _run_days(session, day - dt.timedelta(days=1), day),
        week=week_load_of(week),
        sport_override=sport_override,
    )


# --- §11.2 waiting for last night's sleep -------------------------------------------------------------------


def sleep_missing(session: Session, day: dt.date) -> bool:
    """Today's wellness has neither sleep duration nor sleep score yet (the watch has not synced)."""
    row = session.get(DailyWellness, day)
    return row is None or (row.sleep_s is None and row.sleep_score is None)


def waiting_for_sleep(session: Session, day: dt.date, now: Callable[[], dt.datetime] | None = None) -> bool:
    """§11.2: today, before 12:00 local time, without last night's sleep → the decision is provisional."""
    current = (now or now_local)()
    return day == current.date() and current.hour < fitness.NOON_HOUR and sleep_missing(session, day)
