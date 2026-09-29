"""A DB with wellness rows and a planted sleep → EF correlation (phase 5 service / API tests).

No streams: activities, metrics, wellness and `daily_load` rows are inserted directly and readiness is
persisted through `compute_readiness`, so the DB is cheap to build (once per test run).

- wellness for every day 2026-06-01 … 2026-09-16 (`TODAY`): sleep 6–9 h (uniform), sleep score, RHR ≈ 50,
  Body Battery, sleep stages; every 9th day has no sleep score (Sleep falls back to `sleep_s`);
- `daily_load` on the same days with random load / ATL / TSB (independent of sleep);
- a steady run on every day but every 5th (≈ 86 days) with EF = 1.5 + 0.15 · z(sleep_s of that night) +
  small noise, i.e. a planted lag-0 correlation of sleep duration with run EF;
- 10 bike rides with EF (n < 30 → insufficient data).
"""

import atexit
import datetime as dt
import shutil
import tempfile
from pathlib import Path

import numpy as np
from sqlmodel import Session

from training.db import repo
from training.db.models import Activity, ActivityMetric, DailyLoad
from training.db.session import make_engine, migrate
from training.pipeline_wellness import compute_readiness

from .seeding import TODAY

FIRST_DAY = dt.date(2026, 6, 1)
N_DAYS = (TODAY - FIRST_DAY).days + 1
HOUR = 3600.0


def seed_wellness(session: Session) -> None:
    rng = np.random.default_rng(7)
    sleep = rng.uniform(6 * HOUR, 9 * HOUR, N_DAYS)
    z = (sleep - sleep.mean()) / sleep.std()
    for i in range(N_DAYS):
        day = FIRST_DAY + dt.timedelta(days=i)
        s = float(sleep[i])
        repo.upsert_wellness(
            session,
            {
                "date": day,
                "sleep_s": s,
                "deep_s": 0.2 * s,
                "light_s": 0.5 * s,
                "rem_s": 0.25 * s,
                "awake_s": 0.05 * s,
                "sleep_score": None if i % 9 == 8 else float(rng.uniform(60, 95)),
                "rhr": float(50 + rng.normal(0, 1.5)),
                "body_battery_wake": float(rng.uniform(40, 90)),
                "body_battery_min": 10.0,
                "stress_avg": 30.0,
                "steps": 8000,
            },
        )
        session.add(
            DailyLoad(
                date=day,
                load_total=float(rng.uniform(0, 100)),
                atl=float(rng.uniform(30, 70)),
                ctl=50.0,
                tsb=float(rng.uniform(-15, 15)),
            )
        )
    session.commit()
    run_id = 1000
    for i in range(N_DAYS):
        if i % 5 == 4:
            continue
        run_id += 1
        _activity(
            session,
            run_id,
            FIRST_DAY + dt.timedelta(days=i),
            "run",
            1.5 + 0.15 * float(z[i]) + float(rng.normal(0, 0.03)),
        )
    for i in range(10):
        _activity(
            session,
            2000 + i,
            FIRST_DAY + dt.timedelta(days=5 * i + 2),
            "bike",
            1.0 + float(rng.normal(0, 0.05)),
        )
    session.commit()
    compute_readiness(session)


def _activity(session: Session, garmin_id: int, day: dt.date, sport: str, ef: float) -> None:
    activity = Activity(
        garmin_id=garmin_id,
        sport=sport,
        start_utc=dt.datetime.combine(day, dt.time(6), tzinfo=dt.UTC),
        local_date=day,
        moving_s=3000.0,
    )
    session.add(activity)
    session.flush()
    assert activity.id is not None
    session.add(
        ActivityMetric(
            activity_id=activity.id,
            load_method="hrTSS",
            if_hr=0.8,
            steady_state=True,
            ef=ef,
            decoupling_pct=2.0,
        )
    )


_template: Path | None = None


def wellness_db(tmp_path: Path) -> Path:
    """A private copy of the wellness scenario DB (built once per test run)."""
    global _template
    if _template is None:
        directory = Path(tempfile.mkdtemp(prefix="training-wellness-seed-"))
        atexit.register(shutil.rmtree, directory, ignore_errors=True)
        _template = directory / "template.db"
        migrate(_template)
        engine = make_engine(_template)
        with Session(engine) as session:
            seed_wellness(session)
        with engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        engine.dispose()
    target = tmp_path / "training.db"
    shutil.copy(_template, target)
    return target
