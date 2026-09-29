"""/api/plan push routes and `training push-today` (METRICS §10.8): dry run and error mapping, no network."""

import pytest
from sqlmodel import Session
from typer.testing import CliRunner

from training import cli, planning
from training.config import Settings, get_settings
from training.db.session import make_engine
from training.garmin import client as garmin_client
from training.garmin.client import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from training.services import plan_push
from training.services.errors import NotFoundError, ServiceError

from .seeding import TODAY, make_client, seeded_db


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def planned_id(engine) -> int:
    with Session(engine) as session:
        row, _ = planning.plan_day(session, TODAY, sport_override="run")
        return row.id


def test_dry_run_returns_the_payload_without_garmin(engine, planned_id, monkeypatch):
    monkeypatch.setattr(garmin_client, "connect", lambda tokens_dir: pytest.fail("no login in a dry run"))
    api = make_client(engine)
    body = api.post(f"/api/plan/{planned_id}/push", params={"dry_run": True}).json()
    assert body["action"] in ("dry_run", "skipped")
    if body["action"] == "dry_run":
        assert body["payload"]["workoutSegments"][0]["workoutSteps"]
    today = api.post("/api/plan/today/push", params={"dry_run": True}).json()
    assert [r["planned_id"] for r in today] == [planned_id]


def test_unknown_id_is_404(engine):
    assert make_client(engine).post("/api/plan/99999/push", params={"dry_run": True}).status_code == 404


class Boom:
    def __init__(self, exc):
        self.exc = exc

    def __getattr__(self, name):
        def fail(*args, **kwargs):
            raise self.exc

        return fail


@pytest.mark.parametrize(
    ("exc", "fragment"),
    [
        (GarminConnectAuthenticationError("token secret-123"), "training login"),
        (GarminConnectTooManyRequestsError("x"), "429"),
        (GarminConnectConnectionError("API Error 429 - slow down"), "429"),
        (GarminConnectConnectionError("API Error 400 - bad workout secret-123"), "rejected"),
        (GarminConnectConnectionError("API Error 503 - down"), "unreachable"),
    ],
)
def test_garmin_failures_become_short_service_errors(
    engine, planned_id, monkeypatch, tmp_path, exc, fragment
):
    monkeypatch.setattr(garmin_client, "connect", lambda tokens_dir: Boom(exc))
    settings = Settings(db_path=tmp_path / "unused.db", rate_limit_s=0, max_retries=1)
    with Session(engine) as session:
        row = planning.planned_for(session, TODAY)[0]
        if row.sport == "rest":
            pytest.skip("template gives rest today")
        with pytest.raises(ServiceError) as info:
            plan_push.push_planned(session, planned_id, settings=settings)
    assert fragment in str(info.value) and "secret-123" not in str(info.value)


def test_service_maps_missing_row(engine, tmp_path):
    settings = Settings(db_path=tmp_path / "unused.db")
    with Session(engine) as session, pytest.raises(NotFoundError):
        plan_push.push_planned(session, 99999, settings=settings, dry_run=True)


def test_cli_push_today_dry_run(engine, planned_id, monkeypatch):
    db = engine.url.database
    monkeypatch.setenv("TRAINING_DB_PATH", db)
    monkeypatch.setattr(garmin_client, "connect", lambda tokens_dir: pytest.fail("no login in a dry run"))
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["push-today", "--dry-run", "--date", TODAY.isoformat()])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert "dry_run" in result.output or "skipped" in result.output
