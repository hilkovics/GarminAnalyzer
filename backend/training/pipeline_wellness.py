"""Phase-5 wellness pipeline: DB ↔ pure `training.analysis` functions (METRICS §8–§9). Fully offline.

- `compute_readiness` recomputes `daily_load.readiness` for the whole series after the PMC (§8 needs `TSB[D]`
  and the trailing 28-day baselines, so a changed day moves the next 28 days – the whole series is cheap).
- The frame loaders are shared with `services/sleep.py`, which hands them to the same pure functions.
"""

import datetime as dt
import logging

import pandas as pd
from sqlalchemy import bindparam, select, update
from sqlmodel import Session

from training.analysis.readiness import readiness_frame
from training.analysis.wellness import with_baselines
from training.db.models import Activity, ActivityMetric, DailyLoad, DailyWellness, Subjective

log = logging.getLogger(__name__)

WELLNESS_FIELDS = (
    "sleep_start",
    "sleep_end",
    "sleep_s",
    "deep_s",
    "light_s",
    "rem_s",
    "awake_s",
    "sleep_score",
    "rhr",
    "body_battery_wake",
    "body_battery_min",
    "stress_avg",
    "steps",
    "weight_kg",
)
NUMERIC_WELLNESS = tuple(f for f in WELLNESS_FIELDS if f not in ("sleep_start", "sleep_end"))


def wellness_frame(
    session: Session, date_from: dt.date | None = None, date_to: dt.date | None = None
) -> pd.DataFrame:
    """`daily_wellness` as a date-indexed frame (sparse index, numeric columns as float)."""
    stmt = select(DailyWellness).order_by(DailyWellness.date)
    if date_from is not None:
        stmt = stmt.where(DailyWellness.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(DailyWellness.date <= date_to)
    rows = session.execute(stmt).scalars().all()
    frame = pd.DataFrame(
        [{"date": r.date, **{f: getattr(r, f) for f in WELLNESS_FIELDS}} for r in rows],
        columns=["date", *WELLNESS_FIELDS],
    ).set_index("date")
    for column in NUMERIC_WELLNESS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").astype(float)
    return frame


def daily_frame(session: Session) -> pd.DataFrame:
    """`daily_load` as a date-indexed frame with load_total, atl, tsb, ctl, readiness."""
    rows = session.execute(
        select(
            DailyLoad.date,
            DailyLoad.load_total,
            DailyLoad.atl,
            DailyLoad.tsb,
            DailyLoad.ctl,
            DailyLoad.readiness,
        ).order_by(DailyLoad.date)
    ).all()
    frame = pd.DataFrame(rows, columns=["date", "load_total", "atl", "tsb", "ctl", "readiness"]).set_index(
        "date"
    )
    return frame.astype(float)


def compute_readiness(session: Session) -> int:
    """METRICS §8: readiness for every `daily_load` day; null where there is no wellness component."""
    days = list(session.execute(select(DailyLoad.date)).scalars())
    if not days:
        return 0
    wellness = wellness_frame(session)
    scores: dict[dt.date, float | None] = dict.fromkeys(days)
    if not wellness.empty:
        frame = readiness_frame(with_baselines(wellness), daily_frame(session)["tsb"])
        for day, value in frame["readiness"].items():
            if day in scores and value == value and value is not None:  # NaN → keep None
                scores[day] = float(value)
    table = DailyLoad.__table__
    session.execute(
        update(table).where(table.c.date == bindparam("d")).values(readiness=bindparam("r")),
        [{"d": d, "r": r} for d, r in scores.items()],
        execution_options={"synchronize_session": False},
    )
    session.commit()
    return sum(v is not None for v in scores.values())


def correlation_activities(session: Session) -> pd.DataFrame:
    """Run/bike activities with their §9 outcome inputs (one row per activity, rpe from `subjective`)."""
    rows = session.execute(
        select(
            Activity.id,
            Activity.local_date,
            Activity.sport,
            Activity.moving_s,
            ActivityMetric.load_method,
            ActivityMetric.if_hr,
            ActivityMetric.if_pace,
            ActivityMetric.ef,
            ActivityMetric.decoupling_pct,
            ActivityMetric.pace_at_ref_hr_day,
            Subjective.rpe,
        )
        .join(ActivityMetric, ActivityMetric.activity_id == Activity.id)
        .join(Subjective, Subjective.activity_id == Activity.id, isouter=True)
        .where(Activity.sport.in_(("run", "bike")))
        .order_by(Activity.local_date, Activity.id)  # deterministic order → stable cache hash
    ).all()
    columns = [
        "activity_id",
        "local_date",
        "sport",
        "moving_s",
        "load_method",
        "if_hr",
        "if_pace",
        "ef",
        "decoupling_pct",
        "pace_at_ref_hr_day",
        "rpe",
    ]
    return pd.DataFrame(rows, columns=columns)
