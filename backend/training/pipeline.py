"""Metric pipeline: typed tables → pure metric functions → activity_metric / daily_load. Fully offline.

This is the only place that joins the DB with `training.metrics` (which stays pure, CLAUDE.md). It lives here
rather than in `metrics/pipeline.py` (PLAN §6 phase 2) so that `metrics/` never does I/O.

- Thresholds are historical (CLAUDE.md rule 7): each activity uses the record of its sport with the latest
  `valid_from ≤ local_date`; `other` uses the run record (METRICS §1, clarified).
- `rest_hr` = athlete override, else the median Garmin RHR of the 28 days ending on the activity date (§2.2).
- The PMC is always recomputed for the whole series (cheap; CTL/ATL are recursive, §4).
"""

import datetime as dt
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session

from training.db import repo
from training.db.models import (
    Activity,
    ActivityMetric,
    ActivityStream,
    Athlete,
    DailyLoad,
    DailyWellness,
    Threshold,
)
from training.db.rebuild import rebuild_all
from training.db.state_keys import (
    LAST_ACTIVITY_SYNC,
    LAST_WELLNESS_DATE,
    METRICS_DIRTY_ACTIVITIES,
    METRICS_DIRTY_WELLNESS,
)
from training.metrics.activity import AthleteParams, ThresholdParams, activity_metrics
from training.metrics.pmc import daily_load_series, pmc
from training.metrics.zones import default_zones
from training.normalize.streams import STREAM_COLUMNS

log = logging.getLogger(__name__)

REST_HR_WINDOW_DAYS = 28


@dataclass
class RecomputeResult:
    rebuilt_activities: int = 0
    metrics_computed: int = 0
    daily_load_days: int = 0
    errors: list[str] = field(default_factory=list)


# --- lookups -----------------------------------------------------------------------------------------------


def resolve_threshold(session: Session, sport: str, day: dt.date) -> Threshold | None:
    """Threshold valid at `day` for `sport` (`other` → run) – METRICS §1 (clarified), CLAUDE.md rule 7."""
    key = "run" if sport == "other" else sport
    stmt = (
        select(Threshold)
        .where(Threshold.sport == key, Threshold.valid_from <= day)
        .order_by(Threshold.valid_from.desc())
        .limit(1)
    )
    return session.exec(stmt).scalars().first()


def get_athlete(session: Session) -> Athlete | None:
    return session.exec(select(Athlete).order_by(Athlete.id).limit(1)).scalars().first()


def rest_hr_for(session: Session, athlete: Athlete | None, day: dt.date) -> float | None:
    """METRICS §1/§2.2: athlete override, else the median Garmin RHR of the 28 days ending on `day`."""
    if athlete is not None and athlete.rest_hr_override is not None:
        return athlete.rest_hr_override
    start = day - dt.timedelta(days=REST_HR_WINDOW_DAYS - 1)
    values = session.exec(
        select(DailyWellness.rhr).where(
            DailyWellness.date >= start, DailyWellness.date <= day, DailyWellness.rhr.is_not(None)
        )
    ).scalars()
    series = pd.Series(list(values), dtype=float)
    return float(series.median()) if not series.empty else None


def load_streams(session: Session, activity_id: int) -> pd.DataFrame:
    """The activity's 1 Hz `activity_stream` rows as a DataFrame with `STREAM_COLUMNS` (NULL → NaN)."""
    table = ActivityStream.__table__
    rows = session.execute(
        select(*[table.c[c] for c in STREAM_COLUMNS])
        .where(table.c.activity_id == activity_id)
        .order_by(table.c.t)
    ).all()
    frame = pd.DataFrame(rows, columns=STREAM_COLUMNS)
    for c in STREAM_COLUMNS:
        if c == "t":
            frame[c] = frame[c].astype("int64")
        elif c == "moving":
            frame[c] = frame[c].fillna(True).astype(bool)
        else:
            frame[c] = pd.to_numeric(frame[c], errors="coerce").astype(float)
    return frame


# --- per activity ------------------------------------------------------------------------------------------


def compute_activity_metrics(session: Session, activity_id: int) -> ActivityMetric:
    """Compute and upsert `activity_metric` for one activity (METRICS §0–§2)."""
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise LookupError(f"activity {activity_id} not found")
    threshold = resolve_threshold(session, activity.sport, activity.local_date)
    athlete = get_athlete(session)
    params = ThresholdParams(
        lthr=threshold.lthr if threshold else None,
        threshold_speed=threshold.threshold_speed if threshold and activity.sport == "run" else None,
        zones=(threshold.zones if threshold and threshold.zones else None),
    )
    athlete_params = AthleteParams(
        sex=athlete.sex if athlete else None,
        max_hr=athlete.max_hr if athlete else None,
        rest_hr=rest_hr_for(session, athlete, activity.local_date),
    )
    m = activity_metrics(
        load_streams(session, activity_id),
        sport=activity.sport,
        is_indoor=activity.is_indoor,
        threshold=params,
        athlete=athlete_params,
    )
    row = {
        "activity_id": activity_id,
        "load_primary": m.load_primary,
        "load_method": m.load_method,
        "hrtss": m.hrtss,
        "trimp_norm": m.trimp_norm,
        "rtss": m.rtss,
        "if_hr": m.if_hr,
        "if_pace": m.if_pace,
        "hr_coverage": m.hr_coverage,
        "low_confidence": m.low_confidence,
        "time_in_hr_zone": m.time_in_hr_zone,
        "time_in_pace_zone": m.time_in_pace_zone,
        "threshold_id_used": threshold.id if threshold else None,
    }
    stmt = sqlite_insert(ActivityMetric.__table__).values(**row)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["activity_id"], set_={k: stmt.excluded[k] for k in row if k != "activity_id"}
        )
    )
    return session.get(ActivityMetric, activity_id)  # type: ignore[return-value]


def activity_ids(
    session: Session, *, since: dt.date | None = None, sports: Iterable[str] | None = None
) -> list[int]:
    stmt = select(Activity.id).order_by(Activity.local_date, Activity.id)
    if since is not None:
        stmt = stmt.where(Activity.local_date >= since)
    if sports is not None:
        stmt = stmt.where(Activity.sport.in_(list(sports)))
    return list(session.execute(stmt).scalars())


def compute_metrics_for(session: Session, ids: Iterable[int], result: RecomputeResult) -> list[int]:
    """Compute metrics per activity (commit each); returns the ids whose computation failed."""
    failed: list[int] = []
    for activity_id in ids:
        try:
            compute_activity_metrics(session, activity_id)
            session.commit()
            result.metrics_computed += 1
        except Exception as exc:  # one broken activity must not stop the run
            session.rollback()
            log.exception("metrics for activity %s failed", activity_id)
            result.errors.append(f"metrics activity {activity_id}: {type(exc).__name__}")
            failed.append(activity_id)
    return failed


# --- daily load / PMC ----------------------------------------------------------------------------------


def series_bounds(session: Session, end: dt.date | None = None) -> tuple[dt.date, dt.date] | None:
    """First synced day (earliest activity or wellness date) … last day.

    The last day is the latest of: the data, the last sync dates in sync_state (so rest days up to the last
    sync are part of the series whichever entry point runs), and `end` if given. No wall clock is used.
    """
    dates: list[dt.date] = []
    for column in (Activity.local_date, DailyWellness.date):
        lo = session.execute(select(column).order_by(column).limit(1)).scalar()
        hi = session.execute(select(column).order_by(column.desc()).limit(1)).scalar()
        dates += [d for d in (lo, hi) if d is not None]
    if not dates:
        return None
    ends = [max(dates)] + [
        d for d in (repo.get_state_date(session, k) for k in (LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE)) if d
    ]
    if end is not None:
        ends.append(end)
    return min(dates), max(ends)


def compute_daily_load(session: Session, end: dt.date | None = None) -> int:
    """Recompute `daily_load` (loads + PMC) for the whole series; keeps phase-5 `readiness`. Returns days."""
    bounds = series_bounds(session, end)
    if bounds is None:
        return 0
    start, last = bounds
    rows = session.execute(
        select(Activity.local_date, Activity.sport, ActivityMetric.load_primary).join(
            ActivityMetric, ActivityMetric.activity_id == Activity.id, isouter=True
        )
    ).all()
    activities = pd.DataFrame(rows, columns=["local_date", "sport", "load_primary"])
    daily = daily_load_series(activities, start, last)
    chart = pmc(daily["load_total"])
    out = daily.join(chart)
    session.execute(delete(DailyLoad.__table__).where(DailyLoad.__table__.c.date < start))
    for index, rec in out.iterrows():
        day = index.date() if hasattr(index, "date") else index
        values = {
            "date": day,
            **{c: _num(rec.get(c)) for c in ("load_total", "load_run", "load_bike")},
            **{c: _num(rec.get(c)) for c in ("ctl", "atl", "tsb", "acwr", "monotony", "strain", "ramp_rate")},
        }
        stmt = sqlite_insert(DailyLoad.__table__).values(**values)
        session.execute(
            stmt.on_conflict_do_update(
                index_elements=["date"], set_={k: v for k, v in values.items() if k != "date"}
            )
        )
    session.execute(delete(DailyLoad.__table__).where(DailyLoad.__table__.c.date > last))
    session.commit()
    return len(out)


def _num(value: object) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if f != f else f  # NaN → None


# --- entry points ------------------------------------------------------------------------------------------


def recompute(
    session: Session, *, since: dt.date | None = None, renormalize: bool = True, end: dt.date | None = None
) -> RecomputeResult:
    """`training recompute`: raw → typed tables (optional) → activity metrics → daily load. No network."""
    result = RecomputeResult()
    if renormalize:
        rebuilt = rebuild_all(session)
        result.rebuilt_activities = rebuilt.activities
        result.errors.extend(rebuilt.errors)
    failed = compute_metrics_for(session, activity_ids(session, since=since), result)
    if since is None:  # everything was recomputed, so pending markers are satisfied
        _reset_markers(session, failed)
    result.daily_load_days = compute_daily_load(session, end)
    return result


def _reset_markers(session: Session, failed_activity_ids: list[int]) -> None:
    """Clear the "metrics needed" markers, keeping activities whose computation failed (retried next run)."""
    garmin_ids = []
    if failed_activity_ids:
        garmin_ids = sorted(
            session.execute(select(Activity.garmin_id).where(Activity.id.in_(failed_activity_ids))).scalars()
        )
    repo.set_state_json(session, METRICS_DIRTY_ACTIVITIES, garmin_ids)
    repo.set_state_json(session, METRICS_DIRTY_WELLNESS, [])
    session.commit()


def update_after_sync(session: Session, garmin_ids: Iterable[int] = (), *, today: dt.date) -> RecomputeResult:
    """Recompute everything an ingest run changed, then the PMC up to `today`.

    Driven by the "metrics needed" markers that sync/backfill write together with the typed rows, so an
    interrupted run (Ctrl+C, 429, network) is caught up by the next one. Covers:
    - activities marked dirty (plus `garmin_ids`) and any activity that has no `activity_metric` row,
    - activities on the 28 days starting at each changed wellness day (the RHR median feeds TRIMP, §2.2).
    """
    result = RecomputeResult()
    dirty_ids = {int(g) for g in repo.get_state_json(session, METRICS_DIRTY_ACTIVITIES) or []} | set(
        garmin_ids
    )
    dirty_days = sorted(
        dt.date.fromisoformat(d) for d in repo.get_state_json(session, METRICS_DIRTY_WELLNESS) or []
    )
    ids = set(session.execute(select(Activity.id).where(Activity.garmin_id.in_(sorted(dirty_ids)))).scalars())
    ids |= set(
        session.execute(
            select(Activity.id)
            .join(ActivityMetric, ActivityMetric.activity_id == Activity.id, isouter=True)
            .where(ActivityMetric.activity_id.is_(None))
        ).scalars()
    )
    if dirty_days:
        window_end = dirty_days[-1] + dt.timedelta(days=REST_HR_WINDOW_DAYS - 1)
        ids |= set(
            session.execute(
                select(Activity.id).where(
                    Activity.local_date >= dirty_days[0], Activity.local_date <= window_end
                )
            ).scalars()
        )
    failed = compute_metrics_for(session, sorted(ids), result)
    _reset_markers(session, failed)
    result.daily_load_days = compute_daily_load(session, today)
    return result


def set_threshold(
    session: Session,
    *,
    sport: str,
    valid_from: dt.date,
    lthr: float | None,
    threshold_speed: float | None = None,
    source: str = "manual",
    end: dt.date | None = None,
) -> RecomputeResult:
    """Insert/replace the threshold record for (sport, valid_from) and recompute only what it affects:
    activities of that sport (and `other` for run) from `valid_from` on, then the PMC."""
    if sport not in ("run", "bike"):
        raise ValueError("sport must be 'run' or 'bike'")
    values = {
        "sport": sport,
        "valid_from": valid_from,
        "lthr": lthr,
        "threshold_speed": threshold_speed if sport == "run" else None,
        "zones": default_zones(),
        "source": source,
    }
    stmt = sqlite_insert(Threshold.__table__).values(**values)
    session.execute(
        stmt.on_conflict_do_update(
            index_elements=["sport", "valid_from"],
            set_={k: v for k, v in values.items() if k not in ("sport", "valid_from")},
        )
    )
    session.commit()
    result = RecomputeResult()
    sports = ["run", "other"] if sport == "run" else ["bike"]
    compute_metrics_for(session, activity_ids(session, since=valid_from, sports=sports), result)
    result.daily_load_days = compute_daily_load(session, end)
    return result


def set_athlete(session: Session, **fields: object) -> Athlete:
    """Create or update the single athlete row with the given non-None fields."""
    athlete = get_athlete(session) or Athlete()
    for key, value in fields.items():
        if value is not None:
            setattr(athlete, key, value)
    session.add(athlete)
    session.commit()
    session.refresh(athlete)
    return athlete
