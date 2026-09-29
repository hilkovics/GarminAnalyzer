"""services/sync.py (`run_sync`): the CLI sync as a service, garminconnect mocked at the client boundary."""

import datetime as dt

import pytest
import requests
from sqlalchemy import func, select
from sqlmodel import Session

from training import pipeline
from training.config import Settings
from training.db.models import Activity, ActivityMetric
from training.db.session import make_engine, migrate
from training.garmin import client as garmin_client
from training.garmin.client import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from training.services import sync as svc
from training.services.errors import InvalidInputError, NotFoundError, ServiceError

from .test_sync import FakeGarmin, make_activity

TODAY = dt.date(2026, 9, 29)
SECRET = "secret-token-value"


@pytest.fixture
def session(tmp_path):
    path = tmp_path / "training.db"
    migrate(path)
    engine = make_engine(path)
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        db_path=tmp_path / "training.db",
        garmin_tokens=tmp_path / "tokens",
        rate_limit_s=0.0,
        max_retries=1,  # a failing endpoint is raised at once, no backoff sleeps
    )


@pytest.fixture
def api(monkeypatch):
    fake = FakeGarmin(
        [
            make_activity(1001, TODAY - dt.timedelta(days=2)),
            make_activity(1002, TODAY - dt.timedelta(days=1), "road_biking", "Ride"),
        ]
    )
    monkeypatch.setattr(garmin_client, "connect", lambda tokens_dir: fake)
    return fake


def n(session: Session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_run_sync_fetches_computes_metrics_and_builds_the_pmc(session, settings, api):
    pipeline.set_threshold(session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=150.0)
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=150.0)
    dto = svc.run_sync(session, settings=settings, today=TODAY)
    assert (dto.activities_new, dto.activities_updated, dto.activities_pending, dto.activities_failed) == (
        2,
        0,
        0,
        0,
    )
    assert dto.wellness_days >= 1 and dto.errors == []
    assert dto.metrics_computed == 2 and dto.pmc_days >= 3
    assert n(session, Activity) == 2 and n(session, ActivityMetric) == 2
    load = session.execute(select(ActivityMetric.load_primary)).scalars().all()
    assert all(v is not None and v > 0 for v in load)  # 60 s at 140 bpm with LTHR 150


def test_run_sync_twice_is_idempotent(session, settings, api):
    svc.run_sync(session, settings=settings, today=TODAY)
    again = svc.run_sync(session, settings=settings, today=TODAY)
    assert (again.activities_new, again.activities_unchanged) == (0, 2)
    assert again.metrics_computed == 0 and n(session, Activity) == 2


def test_run_sync_reports_endpoint_errors_without_failing(session, settings, api):
    api.fail["get_activity_splits"] = GarminConnectConnectionError  # 503 after the (single) attempt
    dto = svc.run_sync(session, settings=settings, today=TODAY)
    assert dto.activities_pending == 2 and dto.errors
    assert all("GarminConnectConnectionError" in e for e in dto.errors if "splits" in e)


def test_missing_or_rejected_login_is_a_service_error_without_details(session, settings, monkeypatch):
    def rejected(tokens_dir):
        raise GarminConnectAuthenticationError(f"token {SECRET} expired at {tokens_dir}")

    monkeypatch.setattr(garmin_client, "connect", rejected)
    with pytest.raises(ServiceError) as info:
        svc.run_sync(session, settings=settings, today=TODAY)
    assert str(info.value) == svc.AUTH_MESSAGE
    assert SECRET not in str(info.value) and str(settings.tokens_dir) not in str(info.value)
    assert not isinstance(info.value, NotFoundError | InvalidInputError)  # → HTTP 502, not 404 / 422


def test_rate_limit_is_a_service_error(session, settings, api):
    api.fail["activity_search"] = GarminConnectTooManyRequestsError
    with pytest.raises(ServiceError) as info:
        svc.run_sync(session, settings=settings, today=TODAY)
    assert str(info.value) == svc.RATE_LIMIT_MESSAGE


@pytest.mark.parametrize(
    "failure", [GarminConnectConnectionError, requests.ConnectionError, requests.Timeout]
)
def test_network_failures_are_a_service_error(session, settings, api, failure):
    api.fail["activity_search"] = failure
    with pytest.raises(ServiceError) as info:
        svc.run_sync(session, settings=settings, today=TODAY)
    assert str(info.value) == svc.NETWORK_MESSAGE


def test_unreachable_garmin_at_login_is_a_service_error(session, settings, monkeypatch):
    def unreachable(tokens_dir):
        raise requests.ConnectionError(f"dns failure for host, key={SECRET}")

    monkeypatch.setattr(garmin_client, "connect", unreachable)
    with pytest.raises(ServiceError) as info:
        svc.run_sync(session, settings=settings, today=TODAY)
    assert str(info.value) == svc.NETWORK_MESSAGE and SECRET not in str(info.value)


def test_a_failed_run_keeps_what_was_fetched_and_the_next_run_completes_it(session, settings, api):
    api.fail["get_sleep_data"] = GarminConnectTooManyRequestsError  # activities are stored, wellness aborts
    with pytest.raises(ServiceError):
        svc.run_sync(session, settings=settings, today=TODAY)
    assert n(session, Activity) == 2  # committed as it arrived
    api.fail.clear()
    dto = svc.run_sync(session, settings=settings, today=TODAY)
    assert dto.metrics_computed == 2  # the "metrics needed" markers survived the failed run
    assert n(session, ActivityMetric) == 2


def test_run_sync_plans_today(session, settings, api):
    from training.db.models import PlannedWorkout

    svc.run_sync(session, settings=settings, today=TODAY)
    rows = session.execute(select(PlannedWorkout).where(PlannedWorkout.date == TODAY)).scalars().all()
    assert len(rows) == 1  # nightly coach step (PLAN phase 6)


def test_a_planning_failure_never_fails_the_sync(session, settings, api, monkeypatch):
    from training import planning

    def broken(s, today):
        s.execute(select(func.count()).select_from(Activity))
        raise RuntimeError("coach bug")

    monkeypatch.setattr(planning, "nightly", broken)
    dto = svc.run_sync(session, settings=settings, today=TODAY)
    assert dto.activities_new == 2
    assert n(session, Activity) == 2  # the session is still usable after the rollback
