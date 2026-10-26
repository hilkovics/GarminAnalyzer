"""Block progress glue: DB ↔ the pure `training.coach.block_progress` (METRICS §11.4). Fully offline.

- `baseline`: the stored snapshot of the day before the block (computed and stored when missing).
- `progress`: baseline, the elapsed week records, check-run results and the summary of one block.
Runs only; commutes (§2.6) never count.
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import not_, select
from sqlmodel import Session

from training import planning_fitness as pf
from training.coach import block_progress as bp, fitness
from training.commute import commute_expr
from training.db.models import (
    Activity,
    ActivityMetric,
    BestEffort,
    CoachBlock,
    CoachWeek,
    DailyLoad,
    DailyWellness,
    PlannedWorkout,
)
from training.metrics.efficiency import TREND_WINDOW_DAYS

RUN_COLUMNS = ["local_date", "ef", "steady_state", "pace_at_ref_hr_day"]
CANDIDATE_COLUMNS = ["local_date", "distance_m", "time_s", "source"]


@dataclass(frozen=True)
class BlockProgress:
    block: CoachBlock
    baseline: bp.Snapshot
    weeks: list[bp.WeekRecord]
    check_runs: list[bp.CheckRun]
    summary: bp.Summary


def _runs(session: Session, start: dt.date, end: dt.date) -> pd.DataFrame:
    rows = session.execute(
        select(
            Activity.local_date,
            ActivityMetric.ef,
            ActivityMetric.steady_state,
            ActivityMetric.pace_at_ref_hr_day,
        )
        .join(ActivityMetric, ActivityMetric.activity_id == Activity.id)
        .where(
            Activity.sport == "run",
            Activity.local_date >= start - dt.timedelta(days=TREND_WINDOW_DAYS - 1),
            Activity.local_date <= end,
            not_(commute_expr()),
        )
    ).all()
    return pd.DataFrame([tuple(r) for r in rows], columns=RUN_COLUMNS)


def _candidates(session: Session, end: dt.date) -> pd.DataFrame:
    """§7 candidates up to `end` (run races and gap_speed efforts W ≥ 600 s), commutes excluded."""
    races = session.execute(
        select(Activity.local_date, Activity.distance_m, Activity.duration_s).where(
            Activity.sport == "run",
            Activity.is_race.is_(True),
            Activity.local_date <= end,
            not_(commute_expr()),
        )
    ).all()
    efforts = session.execute(
        select(Activity.local_date, BestEffort.distance_m, BestEffort.window_s)
        .join(Activity, Activity.id == BestEffort.activity_id)
        .where(
            BestEffort.sport == "run",
            BestEffort.kind == "gap_speed",
            BestEffort.window_s >= 600,
            BestEffort.distance_m.is_not(None),
            Activity.local_date <= end,
            not_(commute_expr()),
        )
    ).all()
    records = [(*r, "race") for r in races] + [(*r, "effort") for r in efforts]
    return pd.DataFrame(records, columns=CANDIDATE_COLUMNS)


def snapshot_on(session: Session, day: dt.date) -> bp.Snapshot:
    return bp.snapshot(day, _runs(session, day, day), _candidates(session, day))


def baseline(session: Session, block: CoachBlock, *, refresh: bool = False) -> bp.Snapshot:
    """§11.4 baseline (the snapshot of the day before the block): stored; derived again while missing, not
    final (the block's Monday sync has not run, so Sunday's data may be missing) or refreshed."""
    stored = None if refresh else bp.from_json(block.baseline)
    if stored is not None and (block.baseline or {}).get("final"):
        return stored
    value = snapshot_on(session, block.start_monday - dt.timedelta(days=1))
    block.baseline = bp.to_json(value) | {"final": pf._inputs_complete(session, block.start_monday)}
    session.add(block)
    session.commit()
    return value


def refresh_baselines(session: Session) -> int:
    """`training recompute`: every block's baseline from the current data."""
    blocks = session.execute(select(CoachBlock)).scalars().all()
    for block in blocks:
        baseline(session, block, refresh=True)
    return len(blocks)


def _daily_values(session: Session, start: dt.date, end: dt.date) -> tuple[list, list]:
    readiness = session.execute(
        select(DailyLoad.readiness).where(DailyLoad.date >= start, DailyLoad.date <= end)
    ).scalars()
    sleep = session.execute(
        select(DailyWellness.sleep_s).where(DailyWellness.date >= start, DailyWellness.date <= end)
    ).scalars()
    return list(readiness), list(sleep)


def _week_record(session: Session, row: CoachWeek, today: dt.date) -> bp.WeekRecord:
    end = min(row.monday + dt.timedelta(days=6), today)
    readiness, sleep = _daily_values(session, row.monday, end)
    return bp.WeekRecord(
        monday=row.monday,
        week_no=row.week_no,
        target_s=row.target_s,
        run_s=pf.weekly_run_seconds(session, row.monday),
        items_done=len(pf.menu_done(session, row.monday)),
        brake=row.brake,
        recovery=row.recovery,
        test=row.test,
        mean_readiness=bp.mean(readiness),
        mean_sleep_s=bp.mean(sleep),
        value=snapshot_on(session, end),
    )


def _check_runs(session: Session, start: dt.date, end: dt.date) -> list[bp.CheckRun]:
    rows = session.execute(
        select(PlannedWorkout).where(
            PlannedWorkout.status == "done",
            PlannedWorkout.date >= start,
            PlannedWorkout.date <= end,
            PlannedWorkout.completed_activity_id.is_not(None),
        )
    ).scalars()
    out = []
    for row in rows:
        if (row.structure or {}).get("key") != pf.CHECK_KEY or row.completed_activity_id is None:
            continue
        efforts = {
            kind: (value, distance)
            for kind, value, distance in session.execute(
                select(BestEffort.kind, BestEffort.value, BestEffort.distance_m).where(
                    BestEffort.activity_id == row.completed_activity_id,
                    BestEffort.window_s == int(bp.CHECK_RUN_S),
                )
            ).all()
        }
        distance = efforts.get("gap_speed", (None, None))[1]
        result = bp.check_run_result(
            row.date, row.completed_activity_id, distance, efforts.get("hr", (None, None))[0]
        )
        if result is not None:
            out.append(result)
    return sorted(out, key=lambda r: r.day)


def progress(session: Session, block: CoachBlock, today: dt.date) -> BlockProgress:
    """§11.4 progress of `block` as of `today` (only weeks that have started)."""
    end = block.start_monday + dt.timedelta(weeks=fitness.BLOCK_WEEKS, days=-1)
    rows = session.execute(
        select(CoachWeek)
        .where(CoachWeek.block_id == block.id, CoachWeek.monday <= today)
        .order_by(CoachWeek.monday)
    ).scalars()
    weeks = [_week_record(session, row, today) for row in rows]
    base = baseline(session, block)
    last_day = min(end, today)
    readiness, sleep = _daily_values(session, block.start_monday, last_day)
    return BlockProgress(
        block=block,
        baseline=base,
        weeks=weeks,
        check_runs=_check_runs(session, block.start_monday, last_day),
        summary=bp.summarize(weeks, base, final=today > end, readiness=readiness, sleep_s=sleep),
    )


def blocks(session: Session) -> list[CoachBlock]:
    """All blocks, newest first."""
    return list(session.execute(select(CoachBlock).order_by(CoachBlock.start_monday.desc())).scalars())
