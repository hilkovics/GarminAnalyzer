"""SQLModel table definitions for every table in PLAN.md §4.

Conventions (CLAUDE.md): seconds, metres, m/s, bpm; timestamps are timezone-aware UTC `datetime` (SQLModel's
UTCDateTime rejects naive values) with the activity's timezone stored separately; local dates are `date`.
JSON columns hold plain dicts/lists.
Schema changes always go through an Alembic migration (backend/alembic/versions/).

Deviations from PLAN §4, documented in docs/STATUS.md → Decisions:
- `raw_garmin` has a unique (kind, ref_key) and a `payload_sha256` for cheap change detection.
- `activity_stream` has an extra cumulative `distance` column (needed for grade, METRICS §0.5);
  `moving` means "timer running" (METRICS §0.2).
"""

import datetime as dt
from typing import Any

from sqlalchemy import JSON, Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


class Athlete(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    sex: str | None = None  # "male" | "female" (METRICS §2.2 TRIMP constants)
    birth_year: int | None = None
    max_hr: float | None = None
    rest_hr_override: float | None = None
    weight_kg: float | None = None
    run_bike_split: float | None = None  # share of weekly load for running, e.g. 0.6 for 60:40
    preferred_days: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class Threshold(SQLModel, table=True):
    """Time-versioned thresholds per sport (METRICS §1, CLAUDE.md rule 7)."""

    __table_args__ = (UniqueConstraint("sport", "valid_from"),)

    id: int | None = Field(default=None, primary_key=True)
    sport: str = Field(index=True)  # "run" | "bike"
    valid_from: dt.date
    lthr: float | None = None
    threshold_speed: float | None = None  # m/s, run only
    zones: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    source: str = "manual"  # "manual" | "proposal"


class RawGarmin(SQLModel, table=True):
    """Verbatim Garmin responses (CLAUDE.md rule 4). The DB is a cache; this table makes it rebuildable."""

    __tablename__ = "raw_garmin"
    __table_args__ = (UniqueConstraint("kind", "ref_key"),)

    id: int | None = Field(default=None, primary_key=True)
    kind: str = Field(index=True)
    ref_key: str  # garmin activity id or ISO date / date range
    fetched_at: dt.datetime = Field(default_factory=utcnow)
    payload_sha256: str
    payload: Any = Field(sa_column=Column(JSON))


class Activity(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    garmin_id: int = Field(unique=True, index=True)
    sport: str = Field(index=True)  # "run" | "bike" | "other"
    sub_sport: str | None = None  # Garmin typeKey
    name: str | None = None
    start_utc: dt.datetime
    tz: str | None = None
    local_date: dt.date = Field(index=True)
    duration_s: float | None = None
    moving_s: float | None = None  # Garmin movingDuration (metrics use the stream, METRICS §0.2)
    distance_m: float | None = None
    elev_gain_m: float | None = None
    avg_hr: float | None = None
    max_hr: float | None = None
    avg_speed: float | None = None
    avg_cadence: float | None = None
    calories: float | None = None
    is_race: bool = False
    is_indoor: bool = False
    garmin_training_load: float | None = None
    garmin_aerobic_te: float | None = None
    garmin_anaerobic_te: float | None = None
    garmin_vo2max: float | None = None


class ActivityStream(SQLModel, table=True):
    """1 Hz samples on a regular grid (METRICS §0.1); `moving` = timer running (§0.2)."""

    __tablename__ = "activity_stream"

    activity_id: int = Field(foreign_key="activity.id", primary_key=True, ondelete="CASCADE")
    t: int = Field(primary_key=True)  # seconds since first sample
    hr: float | None = None
    speed: float | None = None
    gap_speed: float | None = None
    alt: float | None = None
    grade: float | None = None
    cadence: float | None = None
    lat: float | None = None
    lon: float | None = None
    distance: float | None = None  # cumulative metres
    moving: bool = True


class ActivityMetric(SQLModel, table=True):
    __tablename__ = "activity_metric"

    activity_id: int = Field(foreign_key="activity.id", primary_key=True, ondelete="CASCADE")
    load_primary: float | None = None
    load_method: str | None = None
    hrtss: float | None = None
    trimp_norm: float | None = None
    rtss: float | None = None
    if_hr: float | None = None
    if_pace: float | None = None
    hr_coverage: float | None = None
    low_confidence: bool = False
    time_in_hr_zone: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    time_in_pace_zone: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    steady_state: bool | None = None
    ef: float | None = None
    decoupling_pct: float | None = None
    pace_at_ref_hr_day: float | None = None
    threshold_id_used: int | None = Field(default=None, foreign_key="threshold.id")


class BestEffort(SQLModel, table=True):
    __tablename__ = "best_effort"
    __table_args__ = (UniqueConstraint("activity_id", "kind", "window_s"),)

    id: int | None = Field(default=None, primary_key=True)
    activity_id: int = Field(foreign_key="activity.id", index=True, ondelete="CASCADE")
    sport: str
    kind: str  # "gap_speed" | "speed" | "hr"
    window_s: int
    value: float  # m/s or bpm
    distance_m: float | None = None  # distance covered in the window (METRICS §6.2 clarified, used by §7)
    start_t: int | None = None  # stream second where the window starts


class DailyWellness(SQLModel, table=True):
    __tablename__ = "daily_wellness"

    date: dt.date = Field(primary_key=True)
    sleep_start: dt.datetime | None = None  # UTC
    sleep_end: dt.datetime | None = None
    sleep_s: float | None = None
    deep_s: float | None = None
    light_s: float | None = None
    rem_s: float | None = None
    awake_s: float | None = None
    sleep_score: float | None = None
    rhr: float | None = None
    body_battery_wake: float | None = None
    body_battery_min: float | None = None
    stress_avg: float | None = None
    steps: int | None = None
    weight_kg: float | None = None


class DailyLoad(SQLModel, table=True):
    __tablename__ = "daily_load"

    date: dt.date = Field(primary_key=True)
    load_total: float = 0.0
    load_run: float = 0.0
    load_bike: float = 0.0
    ctl: float | None = None
    atl: float | None = None
    tsb: float | None = None
    acwr: float | None = None
    monotony: float | None = None
    strain: float | None = None
    ramp_rate: float | None = None
    readiness: float | None = None


class Subjective(SQLModel, table=True):
    # one entry per activity (NULL activity_id = day-level entries, not constrained)
    __table_args__ = (Index("ux_subjective_activity_id", "activity_id", unique=True),)

    id: int | None = Field(default=None, primary_key=True)
    date: dt.date = Field(index=True)
    activity_id: int | None = Field(default=None, foreign_key="activity.id", ondelete="SET NULL")
    rpe: int | None = None  # 1–10
    feel: int | None = None  # 1–5
    soreness: int | None = None  # 0–3
    notes: str | None = None


class Goal(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    race_date: dt.date
    distance_m: float | None = None
    target_time_s: float | None = None
    sport: str = "run"
    active: bool = True


class PlannedWorkout(SQLModel, table=True):
    __tablename__ = "planned_workout"
    __table_args__ = (Index("ix_planned_workout_date_sport", "date", "sport"),)

    id: int | None = Field(default=None, primary_key=True)
    date: dt.date
    sport: str
    name: str
    structure: dict[str, Any] = Field(sa_column=Column(JSON))  # METRICS §10.5
    estimated_load: float | None = None
    reason: str | None = None
    status: str = "planned"  # planned | pushed | done | skipped
    garmin_workout_id: int | None = None
    completed_activity_id: int | None = Field(default=None, foreign_key="activity.id", ondelete="SET NULL")


class CurveSnapshot(SQLModel, table=True):
    __tablename__ = "curve_snapshot"
    __table_args__ = (UniqueConstraint("month", "sport"),)

    id: int | None = Field(default=None, primary_key=True)
    month: str  # "YYYY-MM"
    sport: str
    curve: dict[str, Any] = Field(sa_column=Column(JSON))  # HR bin → gap_speed


class SyncState(SQLModel, table=True):
    __tablename__ = "sync_state"

    key: str = Field(primary_key=True)
    value: str
