"""/api/plan endpoints: the service DTOs serialized 1:1, plus 404/422 paths."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training.db.models import PlannedWorkout
from training.db.session import make_engine, migrate
from training.services import plan as svc
from training.services.dto import GoalIn

from .seeding import TODAY, make_client, seeded_db

DAY = dt.timedelta(days=1)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine):
    return make_client(engine)


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def test_today_creates_the_plan_once(client, session):
    first = client.get("/api/plan/today")
    assert first.status_code == 200
    body = first.json()
    assert body["created"] is True and body["date"] == TODAY.isoformat()
    assert {"workout", "reason", "rule", "readiness", "readiness_band", "acwr", "tsb"} <= set(body)
    assert {"id", "steps", "structure", "missed", "estimated_load", "duration_s"} <= set(body["workout"])
    second = client.get("/api/plan/today").json()
    assert second["created"] is False and second["workout"] == body["workout"]
    assert len(session.execute(select(PlannedWorkout)).all()) == 1
    assert client.get(f"/api/plan/{body['workout']['id']}").json() == body["workout"]


def test_regenerate_with_sport(client):
    client.get("/api/plan/today")
    response = client.post("/api/plan/today/regenerate?sport=bike")
    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True and body["workout"]["sport"] in ("bike", "rest")
    assert client.get("/api/plan/today").json()["workout"]["id"] == body["workout"]["id"]
    assert client.post("/api/plan/today/regenerate").status_code == 200


def test_regenerate_invalid_sport_and_done_workout_are_422(client):
    assert client.post("/api/plan/today/regenerate?sport=swim").status_code == 422
    plan_id = client.get("/api/plan/today").json()["workout"]["id"]
    client.post(f"/api/plan/{plan_id}/status", json={"status": "done"})
    response = client.post("/api/plan/today/regenerate")
    assert response.status_code == 422 and "done or skipped" in response.json()["detail"]


def test_status_done_skipped_planned(client):
    plan_id = client.get("/api/plan/today").json()["workout"]["id"]
    for status in ("done", "skipped", "planned"):
        response = client.post(f"/api/plan/{plan_id}/status", json={"status": status})
        assert response.status_code == 200 and response.json()["status"] == status


def test_status_errors(client):
    assert client.post("/api/plan/9999/status", json={"status": "done"}).status_code == 404
    assert client.get("/api/plan/9999").status_code == 404
    plan_id = client.get("/api/plan/today").json()["workout"]["id"]
    assert client.post(f"/api/plan/{plan_id}/status", json={"status": "pushed"}).status_code == 422
    assert client.post(f"/api/plan/{plan_id}/status", json={}).status_code == 422
    assert client.get("/api/plan/abc").status_code == 422


def test_goal_crud(client):
    assert client.get("/api/plan/goal").json() is None
    race = (TODAY + 70 * DAY).isoformat()
    put = client.put("/api/plan/goal", json={"race_date": race, "distance_m": 10000, "target_time_s": 2400})
    assert put.status_code == 200 and put.json()["sport"] == "run" and put.json()["active"] is True
    assert client.get("/api/plan/goal").json() == put.json()
    assert client.get("/api/plan/season").json()["goal"] == put.json()
    assert client.delete("/api/plan/goal").status_code == 204
    assert client.get("/api/plan/goal").json() is None


@pytest.mark.parametrize(
    "body",
    [
        {"race_date": (TODAY - DAY).isoformat()},
        {"race_date": TODAY.isoformat(), "sport": "swim"},
        {"race_date": TODAY.isoformat(), "distance_m": -5},
        {"distance_m": 5000},
    ],
)
def test_goal_validation_is_422(client, body):
    response = client.put("/api/plan/goal", json=body)
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)


def test_week_and_season_are_the_service_dtos(client, session):
    week = client.get("/api/plan/week")
    assert week.status_code == 200
    assert week.json() == svc.get_week(session, TODAY, today=TODAY).model_dump(mode="json")
    past = client.get(f"/api/plan/week?date={TODAY - 14 * DAY}").json()
    assert past["monday"] == (TODAY - 14 * DAY - 2 * DAY).isoformat()
    svc.set_goal(session, GoalIn(race_date=TODAY + 50 * DAY), today=TODAY)
    season = client.get("/api/plan/season")
    assert season.json() == svc.get_season(session, TODAY).model_dump(mode="json")
    assert season.json()["weeks"][0]["is_current"] is True
    assert client.get("/api/plan/week?date=nope").status_code == 422


def test_empty_database(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = make_engine(path)
    client = make_client(engine)
    assert client.get("/api/plan/today").status_code == 200
    assert client.get("/api/plan/week").status_code == 200
    assert client.get("/api/plan/season").json()["goal"] is None
    assert client.get("/api/plan/goal").json() is None
    engine.dispose()


def test_athlete_preferred_days_round_trip(client):
    body = {"preferred_days": {"mon": {"role": "long", "sport": "bike"}}}
    response = client.put("/api/settings/athlete", json=body)
    assert response.status_code == 200
    days = response.json()["preferred_days"]
    assert days["mon"] == {"role": "long", "sport": "bike"} and days["tue"] == {"role": "q1", "sport": None}
    assert client.get("/api/settings").json()["athlete"]["preferred_days"] == days
    bad = client.put("/api/settings/athlete", json={"preferred_days": {"mon": {"role": "x"}}})
    assert bad.status_code == 422
