"""Seed a DEMO database with synthetic activities + wellness so the UI/API can be tried without Garmin.

    TRAINING_DB_PATH=data/demo.db uv run python scripts/seed_demo.py --days 150
    TRAINING_DB_PATH=data/demo.db uv run streamlit run ui-streamlit/app.py

Refuses to touch a database that already contains activities unless --force is given. Everything is synthetic
(random but seeded); nothing is fetched from Garmin. Metrics are computed through training.pipeline.
"""

import datetime as dt
import logging

import numpy as np
import pandas as pd
import typer
from sqlalchemy import func, select
from sqlmodel import Session

from training import pipeline
from training.config import get_settings
from training.db import repo
from training.db.models import Activity, ActivityMetric
from training.db.session import get_engine
from training.db.state_keys import LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE

RUN_LTHR, BIKE_LTHR, RUN_THRESHOLD_SPEED = 168.0, 160.0, 1000 / 255  # 4:15 /km

# weekday → (sport, kind); kind picks duration and intensity
WEEK = {
    1: ("run", "easy"),
    2: ("bike", "endurance"),
    3: ("run", "tempo"),
    5: ("run", "long"),
    6: ("bike", "long"),
}
KINDS = {
    "easy": (2700, 0.80, 0.85),  # seconds, HR fraction of LTHR, speed fraction of threshold
    "tempo": (3000, 0.92, 0.95),
    "long": (5400, 0.82, 0.83),
    "endurance": (5400, 0.75, 0.0),
}


def stream(rng: np.random.Generator, sport: str, kind: str, hilly: bool) -> pd.DataFrame:
    seconds, hr_frac, speed_frac = KINDS[kind]
    seconds = int(seconds * rng.uniform(0.85, 1.15))
    t = np.arange(seconds)
    lthr = RUN_LTHR if sport == "run" else BIKE_LTHR
    warmup = np.clip(t / 600, 0, 1)
    drift = 1 + 0.03 * t / seconds
    hr = lthr * hr_frac * (0.85 + 0.15 * warmup) * drift + rng.normal(0, 2, seconds)
    base_speed = RUN_THRESHOLD_SPEED * speed_frac if sport == "run" else rng.uniform(7.0, 8.5)
    speed = np.clip(base_speed * (0.9 + 0.1 * warmup) + rng.normal(0, 0.15, seconds), 0, None)
    distance = np.cumsum(speed)
    alt = 150 + (40 * np.sin(distance / 900) if hilly else 2 * np.sin(distance / 3000))
    if rng.random() < 0.1:  # a strap dropout now and then
        start = int(rng.integers(0, seconds - 400))
        hr[start : start + 300] = np.nan
    return pd.DataFrame({"t": t, "hr": hr, "speed": speed, "alt": alt, "distance": distance, "moving": True})


def main(
    days: int = typer.Option(150, help="History length in days (ending today)."),
    seed: int = typer.Option(7, help="Random seed."),
    force: bool = typer.Option(False, help="Allow seeding a DB that already has activities."),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    settings = get_settings()
    rng = np.random.default_rng(seed)
    today = dt.date.today()
    with Session(get_engine(settings)) as session:
        existing = session.execute(select(func.count()).select_from(Activity)).scalar_one()
        if existing and not force:
            typer.echo(
                f"{settings.db_path} already has {existing} activities – use a separate TRAINING_DB_PATH."
            )
            raise typer.Exit(1)
        pipeline.set_athlete(
            session, sex="male", max_hr=190.0, birth_year=1988, weight_kg=72.0, run_bike_split=0.6
        )
        start = today - dt.timedelta(days=days - 1)
        pipeline.set_threshold(
            session, sport="run", valid_from=start, lthr=RUN_LTHR, threshold_speed=RUN_THRESHOLD_SPEED
        )
        pipeline.set_threshold(session, sport="bike", valid_from=start, lthr=BIKE_LTHR)
        garmin_id = 900_000_000
        for i in range(days):
            day = start + dt.timedelta(days=i)
            repo.upsert_wellness(
                session,
                {
                    "date": day,
                    "rhr": float(round(48 + rng.normal(0, 1.5))),
                    "sleep_s": float(rng.normal(7.2, 0.6) * 3600),
                    "sleep_score": float(np.clip(rng.normal(78, 8), 30, 100)),
                    "body_battery_wake": float(np.clip(rng.normal(72, 10), 5, 100)),
                    "stress_avg": float(np.clip(rng.normal(30, 6), 5, 90)),
                    "steps": int(rng.normal(9000, 2500)),
                },
            )
            plan = WEEK.get(day.weekday())
            if plan is None or rng.random() < 0.1 or ((i // 7) % 4 == 3 and rng.random() < 0.4):
                continue  # rest day / skipped session / lighter recovery week
            sport, kind = plan
            garmin_id += 1
            frame = stream(rng, sport, kind, hilly=rng.random() < 0.4)
            aid = repo.upsert_activity(
                session,
                {
                    "garmin_id": garmin_id,
                    "sport": sport,
                    "sub_sport": "running" if sport == "run" else "road_biking",
                    "name": f"Demo {kind} {sport}",
                    "start_utc": dt.datetime.combine(day, dt.time(6, 30), tzinfo=dt.UTC),
                    "tz": "Europe/Bratislava",
                    "local_date": day,
                    "duration_s": float(len(frame)),
                    "moving_s": float(len(frame)),
                    "distance_m": float(frame["distance"].iloc[-1]),
                    "elev_gain_m": float(frame["alt"].diff().clip(lower=0).sum()),
                    "avg_hr": float(np.nanmean(frame["hr"])),
                    "max_hr": float(np.nanmax(frame["hr"])),
                    "avg_speed": float(frame["speed"].mean()),
                    "is_race": False,
                    "is_indoor": False,
                },
            )
            repo.replace_streams(session, aid, frame)
            session.commit()
        repo.set_state(session, LAST_ACTIVITY_SYNC, today.isoformat())
        repo.set_state(session, LAST_WELLNESS_DATE, today.isoformat())
        session.commit()
        result = pipeline.recompute(session, renormalize=False, end=today)
        # plausible Garmin training load for the diagnostics correlation (§2.5)
        for activity in session.exec(select(Activity)).scalars():
            m = session.get(ActivityMetric, activity.id)
            if m is not None and m.load_primary is not None:
                activity.garmin_training_load = float(m.load_primary * 1.15 + rng.normal(0, 8))
        session.commit()
    typer.echo(
        f"Seeded {days} days: {result.metrics_computed} activities, "
        f"PMC {result.daily_load_days} days → {settings.db_path}"
    )


if __name__ == "__main__":
    typer.run(main)
