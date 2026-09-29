"""Seeded databases and API clients for the service and API tests (Phase 3).

`seed_scenario` builds eight ISO weeks of synthetic training on a migrated temp DB through
`training.db.repo` and `training.pipeline`, so the services see exactly what a real sync leaves behind:

- run thresholds LTHR 170 bpm / 3.5 m/s and a bike threshold LTHR 165 bpm, both valid from 2026-01-01;
- athlete: male, max HR 190, rest HR override 50;
- every week (Monday 2026-07-27 … 2026-09-14): a run on Monday (garmin id 200 + week, 1200 s at LTHR,
  3.5 m/s) and a bike ride on Wednesday (300 + week, 1200 s at the bike LTHR) – both ≈ 33.3 points;
- one hike ("other", id 400) on Saturday 2026-08-08, and `TODAY` is Wednesday 2026-09-16.
"""

import atexit
import datetime as dt
import shutil
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlmodel import Session

from training import pipeline
from training.api import deps
from training.api.main import create_app
from training.config import Settings
from training.db import repo
from training.db.models import Activity, ActivityMetric
from training.db.session import make_engine, migrate
from training.db.state_keys import LAST_ACTIVITY_SYNC

UTC = dt.UTC
TODAY = dt.date(2026, 9, 16)  # Wednesday
FIRST_MONDAY = dt.date(2026, 7, 27)
RUN_LTHR, BIKE_LTHR, RUN_SPEED = 170.0, 165.0, 3.5
WEEKS = 8
RUN_ID, BIKE_ID, HIKE_ID = 200, 300, 400  # + week index for run and bike


def add_activity(
    session: Session,
    garmin_id: int,
    day: dt.date,
    *,
    sport: str = "run",
    hr: float | np.ndarray = RUN_LTHR,
    seconds: int = 1200,
    speed: float | None = None,
    alt: float | np.ndarray = 150.0,
    moving: np.ndarray | None = None,
    name: str | None = None,
    hour: int = 6,
) -> int:
    """One activity with a full 1 Hz stream (all samples running unless `moving` says otherwise)."""
    speed = speed if speed is not None else {"run": RUN_SPEED, "bike": 8.0, "other": 1.5}[sport]
    t = np.arange(seconds)
    running = np.ones(seconds, dtype=bool) if moving is None else moving
    v = np.where(running, speed, 0.0)
    activity_id = repo.upsert_activity(
        session,
        {
            "garmin_id": garmin_id,
            "sport": sport,
            "sub_sport": {"run": "running", "bike": "road_biking", "other": "hiking"}[sport],
            "name": name or f"{sport} {garmin_id}",
            "start_utc": dt.datetime.combine(day, dt.time(hour), tzinfo=UTC),
            "tz": "Europe/Bratislava",
            "local_date": day,
            "duration_s": float(seconds),
            "moving_s": float(running.sum()),
            "distance_m": float(v.sum()),
            "elev_gain_m": 10.0,
            "avg_hr": 150.0,
            "max_hr": 170.0,
            "avg_speed": speed,
            "is_race": False,
            "is_indoor": False,
            "garmin_training_load": 40.0,
        },
    )
    repo.replace_streams(
        session,
        activity_id,
        pd.DataFrame(
            {
                "t": t,
                "hr": np.broadcast_to(np.asarray(hr, dtype=float), (seconds,)),
                "speed": v,
                "alt": np.broadcast_to(np.asarray(alt, dtype=float), (seconds,)),
                "cadence": np.full(seconds, 80.0),
                "distance": np.cumsum(v) - v,
                "moving": running,
            }
        ),
    )
    session.commit()
    return activity_id


def seed_scenario(session: Session) -> None:
    pipeline.set_threshold(
        session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=RUN_LTHR, threshold_speed=RUN_SPEED
    )
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=BIKE_LTHR)
    pipeline.set_athlete(session, sex="male", max_hr=190.0, rest_hr_override=50.0)
    for week in range(WEEKS):
        monday = FIRST_MONDAY + dt.timedelta(weeks=week)
        add_activity(session, RUN_ID + week, monday, sport="run")
        add_activity(session, BIKE_ID + week, monday + dt.timedelta(days=2), sport="bike", hr=BIKE_LTHR)
    add_activity(session, HIKE_ID, dt.date(2026, 8, 8), sport="other", hr=0.7 * RUN_LTHR)
    repo.set_state(session, LAST_ACTIVITY_SYNC, TODAY.isoformat())
    session.commit()
    pipeline.recompute(session, renormalize=False, end=TODAY)


_template: Path | None = None


def seeded_db(tmp_path: Path) -> Path:
    """A private copy of the seeded scenario DB in `tmp_path` (the scenario is built once per test run)."""
    global _template
    if _template is None:
        directory = Path(tempfile.mkdtemp(prefix="training-seed-"))
        atexit.register(shutil.rmtree, directory, ignore_errors=True)
        _template = directory / "template.db"
        migrate(_template)
        engine = make_engine(_template)
        with Session(engine) as session:
            seed_scenario(session)
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        engine.dispose()
    target = tmp_path / "training.db"
    shutil.copy(_template, target)
    return target


def aid(session: Session, garmin_id: int) -> int:
    """Internal activity id of a garmin id."""
    found = repo.activity_id_for(session, garmin_id)
    assert found is not None
    return found


def metric_of(session: Session, garmin_id: int) -> ActivityMetric:
    session.expire_all()
    row = session.get(ActivityMetric, aid(session, garmin_id))
    assert row is not None
    return row


def activity_of(session: Session, garmin_id: int) -> Activity:
    row = session.get(Activity, aid(session, garmin_id))
    assert row is not None
    return row


def make_client(engine: Engine, *, today: dt.date = TODAY, settings: Settings | None = None) -> TestClient:
    """TestClient of a fresh app whose session, `today` and (optionally) settings are overridden."""
    app = create_app()

    def session_override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[deps.get_session] = session_override
    app.dependency_overrides[deps.get_today] = lambda: today
    if settings is not None:
        app.dependency_overrides[deps.get_config] = lambda: settings
    return TestClient(app)
