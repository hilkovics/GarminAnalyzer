"""Schema (Alembic ↔ models), idempotent repo helpers. Uses a migrated temporary SQLite DB."""

import datetime as dt

import numpy as np
import pandas as pd
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select
from sqlmodel import SQLModel

import training.db.models  # noqa: F401
from training.db import repo
from training.db.models import Activity, ActivityStream, DailyWellness, RawGarmin

UTC = dt.UTC


def activity_row(garmin_id: int = 42, **overrides) -> dict:
    row = {
        "garmin_id": garmin_id,
        "sport": "run",
        "sub_sport": "running",
        "name": "Easy",
        "start_utc": dt.datetime(2026, 9, 20, 5, 0, tzinfo=UTC),
        "tz": "Europe/Bratislava",
        "local_date": dt.date(2026, 9, 20),
        "duration_s": 3600.0,
        "is_race": False,
        "is_indoor": False,
    }
    return row | overrides


def test_migration_matches_models(engine):
    """CLAUDE.md: never skip Alembic migrations – the migrated schema must equal the SQLModel metadata."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), SQLModel.metadata)
    assert diff == []


def test_all_plan_tables_exist(session):
    expected = {
        "athlete",
        "threshold",
        "raw_garmin",
        "activity",
        "activity_stream",
        "activity_metric",
        "best_effort",
        "daily_wellness",
        "daily_load",
        "subjective",
        "goal",
        "planned_workout",
        "curve_snapshot",
        "sync_state",
    }
    assert expected <= set(repo.table_counts(session))


def test_store_raw_is_idempotent_and_detects_changes(session):
    assert repo.store_raw(session, "sleep", "2026-09-20", {"a": 1, "b": [1, 2]}) is True
    assert (
        repo.store_raw(session, "sleep", "2026-09-20", {"b": [1, 2], "a": 1}) is False
    )  # key order irrelevant
    assert repo.store_raw(session, "sleep", "2026-09-20", {"a": 2}) is True
    session.commit()
    rows = session.exec(select(RawGarmin)).scalars().all()
    assert len(rows) == 1
    assert rows[0].payload == {"a": 2}
    assert repo.get_raw(session, "sleep", "2026-09-20") == {"a": 2}
    assert repo.get_raw(session, "sleep", "2026-09-21") is None


def test_upsert_activity_keyed_by_garmin_id(session):
    first = repo.upsert_activity(session, activity_row(name="Easy"))
    second = repo.upsert_activity(session, activity_row(name="Renamed"))
    session.commit()
    assert first == second
    rows = session.exec(select(Activity)).scalars().all()
    assert len(rows) == 1
    assert rows[0].name == "Renamed"
    assert rows[0].start_utc == dt.datetime(2026, 9, 20, 5, 0, tzinfo=UTC)  # aware UTC round-trip


def test_replace_streams_nan_to_null_and_replaces(session):
    aid = repo.upsert_activity(session, activity_row())
    frame = pd.DataFrame(
        {
            "t": [0, 1, 2],
            "hr": [140.0, np.nan, 142.0],
            "speed": [3.0, 3.1, np.nan],
            "moving": [True, True, False],
            "grade": [np.nan] * 3,
        }
    )
    assert repo.replace_streams(session, aid, frame) == 3
    assert repo.replace_streams(session, aid, frame.iloc[:2]) == 2
    session.commit()
    rows = session.exec(select(ActivityStream).order_by(ActivityStream.t)).scalars().all()
    assert [(r.t, r.hr, r.moving, r.grade) for r in rows] == [(0, 140.0, True, None), (1, None, True, None)]


def test_streams_deleted_with_activity(session):
    aid = repo.upsert_activity(session, activity_row())
    repo.replace_streams(session, aid, pd.DataFrame({"t": [0], "moving": [True]}))
    session.commit()
    session.delete(session.get(Activity, aid))
    session.commit()
    assert session.exec(select(ActivityStream)).scalars().all() == []


def test_wellness_and_state(session):
    day = dt.date(2026, 9, 20)
    repo.upsert_wellness(session, {"date": day, "sleep_s": 25000.0, "rhr": 48.0, "steps": 9000})
    repo.upsert_wellness(session, {"date": day, "sleep_s": 26000.0, "rhr": float("nan"), "steps": 9500})
    repo.set_state(session, "last_wellness_date", "2026-09-20")
    repo.set_state(session, "last_wellness_date", "2026-09-21")
    session.commit()
    rows = session.exec(select(DailyWellness)).scalars().all()
    assert [(r.sleep_s, r.rhr, r.steps) for r in rows] == [(26000.0, None, 9500)]
    assert repo.wellness_dates(session, day, day) == {day}
    assert repo.get_state_date(session, "last_wellness_date") == dt.date(2026, 9, 21)
    assert repo.get_state(session, "missing") is None
