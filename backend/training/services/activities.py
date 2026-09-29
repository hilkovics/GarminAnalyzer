"""Activity services: list, detail (laps, zones, subjective), downsampled streams, subjective form.

Queries and DTO assembly only; every number comes from `activity_metric` / `activity_stream` (written by
`training.pipeline`) or from `metrics.preprocess` for the two derived stream fields.
"""

import datetime as dt
import math
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlmodel import Session

from training import pipeline
from training.db import repo
from training.db.models import Activity, ActivityMetric, Subjective, Threshold
from training.garmin import endpoints as ep
from training.metrics.preprocess import preprocess
from training.services.dto import (
    ActivityDetailDTO,
    ActivityListDTO,
    LapDTO,
    StreamsDTO,
    SubjectiveDTO,
    SubjectiveIn,
)
from training.services.errors import InvalidInputError, NotFoundError
from training.services.lttb import MIN_POINTS, select_indices
from training.services.mappers import (
    hr_zone_bounds,
    pace_zone_bounds,
    subjective_dto,
    summary_dto,
    threshold_dto,
    zone_times,
)

SPORTS = ("run", "bike", "other")
MAX_PAGE_SIZE = 500
STREAM_FIELDS = ("hr", "speed", "gap_speed", "alt", "grade", "cadence", "distance")
DEFAULT_STREAM_FIELDS = ["hr", "speed", "alt"]
DERIVED_FIELDS = ("gap_speed", "grade")  # from metrics.preprocess, not stored (STATUS → Decisions)
MAX_POINTS = 2000  # PLAN §5


def list_activities(
    session: Session,
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    sport: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> ActivityListDTO:
    """Activities with `local_date` in [date_from, date_to] (either bound optional), newest first."""
    if sport is not None and sport not in SPORTS:
        raise InvalidInputError(f"sport must be one of {', '.join(SPORTS)}")
    if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise InvalidInputError(f"page must be ≥ 1 and page_size between 1 and {MAX_PAGE_SIZE}")
    conditions = []
    if date_from is not None:
        conditions.append(Activity.local_date >= date_from)
    if date_to is not None:
        conditions.append(Activity.local_date <= date_to)
    if sport is not None:
        conditions.append(Activity.sport == sport)
    total = session.execute(select(func.count()).select_from(Activity).where(*conditions)).scalar_one()
    rows = session.execute(
        select(Activity, ActivityMetric)
        .join(ActivityMetric, ActivityMetric.activity_id == Activity.id, isouter=True)
        .where(*conditions)
        .order_by(Activity.start_utc.desc(), Activity.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ActivityListDTO(
        items=[summary_dto(a, m) for a, m in rows], total=total, page=page, page_size=page_size
    )


def get_activity(session: Session, activity_id: int) -> ActivityDetailDTO:
    """Summary + metrics, laps, time in HR/pace zones (bounds of the threshold used), subjective row."""
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise NotFoundError(f"activity {activity_id} not found")
    metric = session.get(ActivityMetric, activity_id)
    if metric is None:  # no metrics computed yet: show the record that is valid at the activity date
        threshold = pipeline.resolve_threshold(session, activity.sport, activity.local_date)
    elif metric.threshold_id_used is not None:
        threshold = session.get(Threshold, metric.threshold_id_used)
    else:
        threshold = None

    hr_zones = []
    pace_zones = None
    if metric is not None and threshold is not None:
        if threshold.lthr:
            hr_zones = zone_times(metric.time_in_hr_zone, hr_zone_bounds(threshold))
        if threshold.threshold_speed and metric.time_in_pace_zone is not None:
            pace_zones = zone_times(metric.time_in_pace_zone, pace_zone_bounds(threshold))
    subjective = session.execute(
        select(Subjective)
        .where(Subjective.activity_id == activity_id)
        .order_by(Subjective.id.desc())
        .limit(1)
    ).scalar_one_or_none()
    return ActivityDetailDTO(
        summary=summary_dto(activity, metric),
        laps=_laps(session, activity.garmin_id),
        hr_zones=hr_zones,
        pace_zones=pace_zones,
        threshold=threshold_dto(threshold) if threshold is not None else None,
        subjective=subjective_dto(subjective) if subjective is not None else None,
    )


def get_streams(
    session: Session, activity_id: int, fields: list[str] | None = None, points: int = 1500
) -> StreamsDTO:
    """1 Hz streams of `fields`, LTTB-downsampled to at most `points` samples on one shared `t`.

    hr, speed, alt, cadence and distance are the stored values; gap_speed and grade come from
    `metrics.preprocess` (only running seconds have a value there, paused seconds are null).
    """
    names = list(dict.fromkeys(fields or DEFAULT_STREAM_FIELDS))
    unknown = [f for f in names if f not in STREAM_FIELDS]
    if unknown:
        raise InvalidInputError(
            f"unknown stream field(s): {', '.join(unknown)}; allowed: {', '.join(STREAM_FIELDS)}"
        )
    if not MIN_POINTS <= points <= MAX_POINTS:
        raise InvalidInputError(f"points must be between {MIN_POINTS} and {MAX_POINTS}")
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise NotFoundError(f"activity {activity_id} not found")

    frame = pipeline.load_streams(session, activity_id)
    t = frame["t"].to_numpy()
    values = {f: frame[f].to_numpy(dtype=float) for f in names if f not in DERIVED_FIELDS}
    derived = [f for f in names if f in DERIVED_FIELDS]
    if derived and len(frame):
        samples = preprocess(frame, activity.sport).samples.set_index("t")
        for f in derived:
            values[f] = samples[f].reindex(t).to_numpy(dtype=float)
    else:
        values.update({f: np.full(len(frame), np.nan) for f in derived})

    keep = select_indices(t, values, points)
    return StreamsDTO(
        activity_id=activity_id,
        points=len(keep),
        source_points=len(frame),
        t=[int(v) for v in t[keep]],
        series={f: [_finite(v) for v in values[f][keep]] for f in names},
    )


def save_subjective(session: Session, activity_id: int, data: SubjectiveIn) -> SubjectiveDTO:
    """Upsert the subjective record of an activity (one row per activity; `date` = the activity's local date).

    The four fields are replaced as given – null clears a value, so a form can post its full state.
    """
    activity = session.get(Activity, activity_id)
    if activity is None:
        raise NotFoundError(f"activity {activity_id} not found")
    row = session.execute(
        select(Subjective).where(Subjective.activity_id == activity_id).order_by(Subjective.id).limit(1)
    ).scalar_one_or_none() or Subjective(activity_id=activity_id, date=activity.local_date)
    row.date = activity.local_date
    row.rpe, row.feel, row.soreness, row.notes = data.rpe, data.feel, data.soreness, data.notes
    session.add(row)
    session.commit()
    session.refresh(row)
    return subjective_dto(row)


# --- helpers -----------------------------------------------------------------------------------------------


def _laps(session: Session, garmin_id: int) -> list[LapDTO]:
    """Laps from the raw `get_activity_splits` payload (`lapDTOs[]`).

    The keys are unverified guesses, so every lookup is defensive: an unexpected shape gives fewer fields
    or no laps, never an error.
    """
    payload = repo.get_raw(session, ep.LAPS, str(garmin_id))
    raw = payload.get("lapDTOs") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    return [
        LapDTO(
            index=index,
            duration_s=_number(lap.get("duration")),
            distance_m=_number(lap.get("distance")),
            avg_hr=_number(lap.get("averageHR")),
            max_hr=_number(lap.get("maxHR")),
            avg_speed=_number(lap.get("averageSpeed")),
            elev_gain_m=_number(lap.get("elevationGain")),
        )
        for index, lap in enumerate((x for x in raw if isinstance(x, dict)), start=1)
    ]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value) if math.isfinite(value) else None


def _finite(value: float) -> float | None:
    return float(value) if math.isfinite(value) else None
