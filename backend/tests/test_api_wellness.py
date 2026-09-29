"""/api/wellness endpoints: the DTO of the service, serialized 1:1, and 422 on invalid parameters."""

import datetime as dt

import pytest
from sqlmodel import Session

from training.db.session import make_engine
from training.services import sleep as svc

from .seeding import TODAY, make_client
from .wellness_seeding import FIRST_DAY, N_DAYS, wellness_db


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(wellness_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine):
    return make_client(engine)


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def test_daily_is_the_service_dto(client, session):
    response = client.get("/api/wellness/daily")
    assert response.status_code == 200
    assert response.json() == svc.get_wellness(session).model_dump(mode="json")
    body = response.json()
    assert len(body["days"]) == N_DAYS
    assert set(body["days"][-1]["baselines"]) == {"rhr", "sleep_s", "sleep_score", "body_battery_wake"}
    assert set(body["days"][-1]["baselines"]["rhr"]) == {"median", "mad"}


def test_daily_range(client, session):
    start, end = FIRST_DAY + dt.timedelta(days=50), FIRST_DAY + dt.timedelta(days=59)
    response = client.get(f"/api/wellness/daily?from={start}&to={end}")
    assert response.status_code == 200
    assert response.json() == svc.get_wellness(session, start, end).model_dump(mode="json")
    body = response.json()
    assert body["days"][0]["date"] == start.isoformat() and len(body["days"]) == 10
    assert body["days"][0]["baselines"]["rhr"]["median"] is not None


@pytest.mark.parametrize(
    "query", [f"from={TODAY}&to={FIRST_DAY}", "from=2000-01-01&to=2026-09-16", "from=nope"]
)
def test_daily_invalid_range_is_422(client, query):
    response = client.get(f"/api/wellness/daily?{query}")
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_readiness_today_uses_the_injected_today(client, session):
    response = client.get("/api/wellness/readiness/today")
    assert response.status_code == 200
    assert response.json() == svc.get_readiness(session, TODAY).model_dump(mode="json")
    body = response.json()
    assert body["date"] == TODAY.isoformat() and body["available"] is True
    assert body["band"] in ("green", "yellow", "red") and len(body["components"]) == 4


def test_readiness_of_a_day(client, session):
    day = FIRST_DAY + dt.timedelta(days=30)
    response = client.get(f"/api/wellness/readiness/{day}")
    assert response.status_code == 200
    assert response.json() == svc.get_readiness(session, day).model_dump(mode="json")


def test_readiness_without_data_is_200_unavailable_and_bad_date_is_422(client):
    body = client.get("/api/wellness/readiness/2020-01-01").json()
    assert body["available"] is False and body["score"] is None
    response = client.get("/api/wellness/readiness/not-a-date")
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)


def test_correlations_is_the_service_dto(client, session, monkeypatch):
    real = svc.get_correlations
    monkeypatch.setattr(svc, "get_correlations", lambda s, sport=None, n_boot=60: real(s, sport, n_boot))
    response = client.get("/api/wellness/correlations?sport=run")
    assert response.status_code == 200
    assert response.json() == real(session, "run", 60).model_dump(mode="json")
    body = response.json()
    assert body["sports"] == ["run"] and body["findings"] and body["caveat"]
    assert body["findings"][0]["sentence"].startswith("Keď ")


def test_correlations_invalid_sport_is_422(client):
    response = client.get("/api/wellness/correlations?sport=swim")
    assert response.status_code == 422 and "sport" in response.json()["detail"]
