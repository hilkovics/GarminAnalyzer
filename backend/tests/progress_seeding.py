"""The seeded scenario of `seeding.py` plus phase-4 data (steady runs / rides, a race, Garmin raw values).

Extras on top of the eight weeks of 1200 s runs (LTHR 170 bpm, 3.5 m/s flat, threshold 3.5 m/s):
- two 3000 s "easy" runs at 140 bpm (0.82 · LTHR → steady state) and 3.5 m/s on 2026-09-01 and 2026-09-11:
  EF = 3.5 · 60 / 140 = 1.5, decoupling 0, ref HR 136 bpm falls in their band → pace at ref HR 3.5 m/s;
- one 3000 s ride at 132 bpm (0.8 · 165) and 8 m/s on 2026-09-09 (steady, EF = 8 · 60 / 132);
- one 3000 s hard ride at 170 bpm on 2026-09-13 (not steady; the bike LTHR proposal comes from it);
- a 10 km race in 40:00 on 2026-08-30 (VDOT ≈ 51.94), no stream needed;
- raw Garmin lactate-threshold and max-metrics payloads.
"""

import atexit
import datetime as dt
import shutil
import tempfile
from pathlib import Path

from sqlmodel import Session

from training import pipeline
from training.db import raw_kinds, repo
from training.db.models import Activity
from training.db.session import make_engine, migrate

from .seeding import BIKE_LTHR, TODAY, add_activity, seed_scenario

EASY_DAYS = (dt.date(2026, 9, 1), dt.date(2026, 9, 11))
RIDE_DAY = dt.date(2026, 9, 9)
RACE_DAY = dt.date(2026, 8, 30)
HARD_RIDE_HR = 170.0  # 1.03 · bike LTHR: the top hrTSS/h ride, the only one that qualifies for §6.3
EASY_HR, EASY_EF = 140.0, 3.5 * 60.0 / 140.0
RIDE_EF = 8.0 * 60.0 / (0.8 * BIKE_LTHR)

LACTATE = {"speed_and_heart_rate": {"calendarDate": "2026-09-15", "heartRate": 171, "speed": 0.36}}
MAX_METRICS = [{"generic": {"vo2MaxPreciseValue": 52.4, "vo2MaxValue": 52}}]


def seed_progress(session: Session) -> None:
    seed_scenario(session)
    for i, day in enumerate(EASY_DAYS):
        add_activity(session, 500 + i, day, sport="run", hr=EASY_HR, seconds=3000, hour=7)
    add_activity(session, 600, RIDE_DAY, sport="bike", hr=BIKE_LTHR * 0.8, seconds=3000)
    add_activity(session, 601, dt.date(2026, 9, 13), sport="bike", hr=HARD_RIDE_HR, seconds=3000)
    race = add_activity(session, 700, RACE_DAY, sport="run", seconds=600, name="Race")
    activity = session.get(Activity, race)
    assert activity is not None
    activity.is_race, activity.distance_m, activity.duration_s = True, 10000.0, 2400.0
    session.add(activity)
    repo.store_raw(session, raw_kinds.LACTATE_THRESHOLD, "2026-09-15", LACTATE)
    repo.store_raw(session, raw_kinds.MAX_METRICS, "2026-09-15", MAX_METRICS)
    session.commit()
    pipeline.recompute(session, renormalize=False, end=TODAY)


_template: Path | None = None


def progress_db(tmp_path: Path) -> Path:
    """A private copy of the phase-4 scenario DB (built once per test run)."""
    global _template
    if _template is None:
        directory = Path(tempfile.mkdtemp(prefix="training-progress-seed-"))
        atexit.register(shutil.rmtree, directory, ignore_errors=True)
        _template = directory / "template.db"
        migrate(_template)
        engine = make_engine(_template)
        with Session(engine) as session:
            seed_progress(session)
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        engine.dispose()
    target = tmp_path / "training.db"
    shutil.copy(_template, target)
    return target
