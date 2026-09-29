"""Phase-4 progress metrics: DB ↔ pure metric functions (METRICS §5–§6). Fully offline.

- Per activity (`compute_activity_progress`): steady state, EF, decoupling and `pace_at_ref_hr_day` into
  `activity_metric`; best efforts (§6.2) into `best_effort` (replaced per activity).
- Monthly speed–HR curve snapshots (§6.1) into `curve_snapshot`: the 28 days ending on each month end (or on
  `today` for the current month). A run's 60 s aggregates are computed once per call and reused across the
  windows it falls into.
Thresholds are resolved at the activity date (rule 7); the curve's reference HR uses the run threshold valid
at the window end.
"""

import datetime as dt
import logging
from collections.abc import Iterable

import pandas as pd
from sqlalchemy import delete, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from training.db.models import Activity, ActivityMetric, BestEffort, CurveSnapshot
from training.metrics.curve import (
    REF_FRACTION,
    aggregates_60s,
    curve_to_json,
    pace_at_ref_hr_day,
    speed_hr_curve,
)
from training.metrics.efficiency import efficiency
from training.metrics.efforts import best_efforts
from training.metrics.preprocess import preprocess

log = logging.getLogger(__name__)

CURVE_WINDOW_DAYS = 28


def _lthr(session: Session, sport: str, day: dt.date) -> float | None:
    from training.pipeline import resolve_threshold  # local import: pipeline imports this module

    threshold = resolve_threshold(session, sport, day)
    return threshold.lthr if threshold is not None else None


def compute_activity_progress(session: Session, activity_id: int) -> None:
    """METRICS §5 + §6.1 (day value) + §6.2 for one activity; needs its `activity_metric` row (phase 2)."""
    from training.pipeline import load_streams

    activity = session.get(Activity, activity_id)
    if activity is None:
        raise LookupError(f"activity {activity_id} not found")
    prep = preprocess(load_streams(session, activity_id), activity.sport)
    lthr = _lthr(session, activity.sport, activity.local_date)
    eff = efficiency(prep, sport=activity.sport, lthr=lthr)
    day_pace = None
    if activity.sport == "run" and lthr:
        day_pace = pace_at_ref_hr_day(aggregates_60s(prep), REF_FRACTION * lthr)
    metric = session.get(ActivityMetric, activity_id)
    if metric is not None:
        metric.steady_state = eff.steady_state
        metric.ef = eff.ef
        metric.decoupling_pct = eff.decoupling_pct
        metric.pace_at_ref_hr_day = day_pace
        session.add(metric)
    session.execute(delete(BestEffort.__table__).where(BestEffort.__table__.c.activity_id == activity_id))
    rows = [
        {
            "activity_id": activity_id,
            "sport": activity.sport,
            "kind": e.kind,
            "window_s": e.window_s,
            "value": e.value,
            "distance_m": e.distance_m,
            "start_t": e.start_t,
        }
        for e in best_efforts(prep, activity.sport)
    ]
    if rows:
        session.execute(insert(BestEffort.__table__), rows)


# --- monthly speed–HR curve snapshots (§6.1) ---------------------------------------------------------------


def _month_end(day: dt.date) -> dt.date:
    nxt = (day.replace(day=1) + dt.timedelta(days=32)).replace(day=1)
    return nxt - dt.timedelta(days=1)


def curve_months(first: dt.date, today: dt.date) -> list[str]:
    """ "YYYY-MM" for every month from `first` to `today`."""
    months, cur = [], first.replace(day=1)
    while cur <= today:
        months.append(f"{cur:%Y-%m}")
        cur = _month_end(cur) + dt.timedelta(days=1)
    return months


def compute_curve_snapshots(session: Session, today: dt.date, months: Iterable[str] | None = None) -> int:
    """Upsert `curve_snapshot` (sport "run") for `months` (default: every month with run data)."""
    runs = session.execute(
        select(Activity.id, Activity.local_date).where(Activity.sport == "run").order_by(Activity.local_date)
    ).all()
    if not runs:
        return 0
    wanted = sorted(set(months)) if months is not None else curve_months(runs[0].local_date, today)
    wanted = [m for m in wanted if m <= f"{today:%Y-%m}"]  # never a snapshot for a month after today
    cache: dict[int, pd.DataFrame] = {}
    from training.pipeline import load_streams

    def aggregates(activity_id: int) -> pd.DataFrame:
        if activity_id not in cache:
            cache[activity_id] = aggregates_60s(preprocess(load_streams(session, activity_id), "run"))
        return cache[activity_id]

    written = 0
    for month in wanted:
        first = dt.date.fromisoformat(f"{month}-01")
        end = min(_month_end(first), today)
        start = end - dt.timedelta(days=CURVE_WINDOW_DAYS - 1)
        in_window = [r.id for r in runs if start <= r.local_date <= end]
        frames = [aggregates(a) for a in in_window]
        pooled = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=["gap_speed", "hr"])
        curve = speed_hr_curve(pooled, lthr=_lthr(session, "run", end))
        values = {"month": month, "sport": "run", "curve": curve_to_json(curve)}
        stmt = sqlite_insert(CurveSnapshot.__table__).values(**values)
        session.execute(
            stmt.on_conflict_do_update(index_elements=["month", "sport"], set_={"curve": stmt.excluded.curve})
        )
        written += 1
    session.commit()
    return written


def months_touched(days: Iterable[dt.date]) -> set[str]:
    """Snapshot months whose 28-day window contains any of `days` (the day's month and, for the last 27 days
    of a month, also the next month)."""
    out: set[str] = set()
    for d in days:
        out.add(f"{d:%Y-%m}")
        out.add(f"{d + dt.timedelta(days=CURVE_WINDOW_DAYS - 1):%Y-%m}")
    return out
