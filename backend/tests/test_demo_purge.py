"""Demo rows (`scripts/seed_demo.py`) in a real DB: found, listed, purged; the seeder refuses real DBs."""

import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import typer
from sqlalchemy import func, select
from sqlmodel import Session
from typer.testing import CliRunner

from training import cli, pipeline
from training.config import PROJECT_ROOT, Settings, get_settings
from training.db import demo, raw_kinds as ep, repo
from training.db.models import Activity, DailyWellness, Threshold
from training.db.session import get_engine

runner = CliRunner()
TODAY = dt.date.today()


def seed_app() -> typer.Typer:
    spec = importlib.util.spec_from_file_location("seed_demo", PROJECT_ROOT / "scripts" / "seed_demo.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = typer.Typer()
    app.command()(module.main)
    return app


@pytest.fixture
def mixed_db(monkeypatch, tmp_path) -> Path:
    """A demo seed followed by one real activity, one real wellness day and a real threshold."""
    db = tmp_path / "training.db"
    result = runner.invoke(seed_app(), ["--days", "21", "--db", str(db)])
    assert result.exit_code == 0, result.output
    real_day = TODAY - dt.timedelta(days=3)
    with Session(get_engine(Settings(db_path=db))) as session:
        repo.store_raw(session, ep.ACTIVITY_SUMMARY, "555", {"activityId": 555})
        repo.upsert_activity(
            session,
            {
                "garmin_id": 555,
                "sport": "run",
                "name": "Morning Run",
                "start_utc": dt.datetime.combine(real_day, dt.time(7), tzinfo=dt.UTC),
                "local_date": real_day,
                "duration_s": 1800.0,
            },
        )
        repo.store_raw(session, ep.SLEEP, real_day.isoformat(), {"dailySleepDTO": {}})
        pipeline.set_threshold(session, sport="run", valid_from=TODAY, lthr=172.0, threshold_speed=3.0)
        session.commit()
    monkeypatch.setenv("TRAINING_DB_PATH", str(db))
    get_settings.cache_clear()
    yield db
    get_settings.cache_clear()


def counts(db: Path) -> tuple[int, int, int]:
    with Session(get_engine(Settings(db_path=db))) as session:
        return tuple(  # type: ignore[return-value]
            session.execute(select(func.count()).select_from(model)).scalar_one()
            for model in (Activity, DailyWellness, Threshold)
        )


def test_finds_only_rows_without_garmin_data(mixed_db):
    with Session(get_engine(Settings(db_path=mixed_db))) as session:
        rows = demo.find_demo_rows(session)
        demo_activities = session.execute(select(Activity).where(Activity.garmin_id != 555)).scalars().all()
    assert sorted(rows.activity_ids) == sorted(a.id for a in demo_activities) and rows.activity_ids
    assert len(rows.wellness_dates) == 20 and TODAY - dt.timedelta(days=3) not in rows.wellness_dates
    assert len(rows.threshold_ids) == 2
    assert rows.athlete_is_demo


def test_purge_is_a_dry_run_without_yes(mixed_db):
    before = counts(mixed_db)
    result = runner.invoke(cli.app, ["purge-demo"])
    assert result.exit_code == 0, result.output
    assert "dry run" in result.output and "wellness days without Garmin data: 20" in result.output
    assert counts(mixed_db) == before


def test_purge_keeps_real_rows_and_recomputes(mixed_db):
    result = runner.invoke(cli.app, ["purge-demo", "--yes"])
    assert result.exit_code == 0, result.output
    assert "backfill --months 24 --restart" in result.output
    assert counts(mixed_db) == (1, 1, 1)
    with Session(get_engine(Settings(db_path=mixed_db))) as session:
        assert session.execute(select(Activity.garmin_id)).scalar_one() == 555
        assert session.execute(select(Threshold.lthr)).scalar_one() == 172.0
        assert demo.find_demo_rows(session).empty
    again = runner.invoke(cli.app, ["purge-demo", "--yes"])
    assert "nothing to remove" in again.output


def test_seeder_never_writes_into_a_db_with_garmin_data(mixed_db):
    before = counts(mixed_db)
    result = runner.invoke(seed_app(), ["--days", "5", "--db", str(mixed_db), "--force"])
    assert result.exit_code == 1
    assert "real Garmin data" in result.output
    assert counts(mixed_db) == before
