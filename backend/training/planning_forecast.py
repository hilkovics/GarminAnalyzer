"""Predictions glue: DB ↔ the pure `training.coach.forecast` (METRICS §11.5). Fully offline.

- `sleep_effect` / `morning_note`: the personal sleep → pace effect from the §9 run dataset.
- `outlook`: the 7-day readiness outlook and the best days for quality.
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd
from sqlalchemy import select
from sqlmodel import Session

from training import planning, planning_fitness as pf
from training.analysis.correlation import build_dataset
from training.analysis.wellness import with_baselines
from training.coach import forecast as fc
from training.db.models import Athlete, DailyLoad, DailyWellness
from training.pipeline_wellness import correlation_activities, daily_frame, wellness_frame

PENDING = ("planned", "pushed")
BASELINE_LOOKBACK_D = 40


@dataclass(frozen=True)
class Outlook:
    days: list[fc.OutlookDay]
    best: list[dt.date]
    available: set[dt.date]


def sleep_effect(session: Session) -> fc.SleepEffect:
    """§11.5 effect on the §9 run dataset (all history)."""
    dataset = build_dataset(
        correlation_activities(session), with_baselines(wellness_frame(session)), daily_frame(session), "run"
    )
    return fc.sleep_effect(dataset)


def last_night_sleep(session: Session, day: dt.date) -> float | None:
    row = session.get(DailyWellness, day)
    return row.sleep_s if row is not None else None


def morning_note(session: Session, day: dt.date) -> fc.SleepNote | None:
    return fc.sleep_note(sleep_effect(session), last_night_sleep(session, day))


def _today_baselines(session: Session, today: dt.date) -> tuple[float | None, float | None]:
    frame = wellness_frame(session, today - dt.timedelta(days=BASELINE_LOOKBACK_D), today)
    if today not in frame.index:
        frame.loc[today] = float("nan")  # a row for today, so its trailing baseline exists
    row = with_baselines(frame.sort_index()).loc[today]

    def value(column: str) -> float | None:
        v = row.get(column)
        return None if v is None or pd.isna(v) else float(v)

    return value("rhr_median28"), value("sleep_s_median28")


def _load_today(session: Session, today: dt.date) -> float:
    row = session.get(DailyLoad, today)
    load = float(row.load_total or 0.0) if row is not None else 0.0
    for planned in planning.planned_for(session, today):
        if planned.status in PENDING and planned.sport != "rest":
            load += float(planned.estimated_load or 0.0)
    return load


def outlook(session: Session, today: dt.date) -> Outlook:
    """§11.5 outlook for `today + 1 … today + 7`."""
    start = today - dt.timedelta(weeks=fc.TYPICAL_WEEKS)
    wellness_rows = session.execute(
        select(DailyWellness).where(DailyWellness.date >= start, DailyWellness.date < today)
    ).scalars()
    wellness = {r.date: {f: getattr(r, f) for f in fc.WELLNESS_FIELDS} for r in wellness_rows}
    loads = dict(
        session.execute(
            select(DailyLoad.date, DailyLoad.load_total).where(
                DailyLoad.date >= start, DailyLoad.date < today
            )
        ).all()
    )
    last = session.execute(
        select(DailyLoad).where(DailyLoad.date < today).order_by(DailyLoad.date.desc()).limit(1)
    ).scalar()
    ctl_prev, atl_prev = (0.0, 0.0) if last is None else (float(last.ctl or 0.0), float(last.atl or 0.0))
    if last is not None:  # a sync gap: the missing days had no known load (§11.5)
        ctl_prev, atl_prev = fc.carry_forward(
            ctl_prev, atl_prev, (today - dt.timedelta(days=1) - last.date).days
        )
    rhr_median, sleep_median = _today_baselines(session, today)
    days = fc.outlook(
        today=today,
        ctl_prev=ctl_prev,
        atl_prev=atl_prev,
        load_today=_load_today(session, today),
        wellness=wellness,
        loads=loads,
        rhr_median28=rhr_median,
        sleep_s_median28=sleep_median,
    )
    athlete = session.execute(select(Athlete)).scalars().first()
    mondays = {pf.monday_of(d.day) for d in days}
    available = set().union(*(pf.available_days(athlete, m) for m in mondays))
    return Outlook(days, fc.best_days(days, available), available)
