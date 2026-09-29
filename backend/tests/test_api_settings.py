"""/api/settings endpoints. PLAN phase 3 acceptance: a new threshold changes only later activities."""

import datetime as dt

import pytest
from sqlmodel import Session

from training.db.session import make_engine, migrate
from training.services import settings as svc

from .seeding import BIKE_ID, BIKE_LTHR, RUN_ID, RUN_LTHR, TODAY, make_client, seeded_db


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


def loads(client, sport: str) -> dict[int, float | None]:
    items = client.get("/api/activities", params={"sport": sport, "page_size": 100}).json()["items"]
    return {i["garmin_id"]: i["load_primary"] for i in items}


def test_get_settings_is_the_service_dto(client, session):
    response = client.get("/api/settings")
    assert response.status_code == 200
    assert response.json() == svc.get_settings(session, today=TODAY).model_dump(mode="json")
    body = response.json()
    assert body["athlete"]["max_hr"] == 190.0 and body["athlete"]["rest_hr_current"] == 50.0
    assert [t["sport"] for t in body["thresholds"]] == ["bike", "run"]
    assert body["current"]["run"]["lthr"] == RUN_LTHR and body["current"]["bike"]["lthr"] == BIKE_LTHR
    assert body["hr_zones"]["run"][3]["lower"] == pytest.approx(0.95 * RUN_LTHR)
    assert body["pace_zones"][0]["lower"] is None


def test_get_settings_of_an_empty_database(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = make_engine(path)
    body = make_client(engine).get("/api/settings").json()
    assert body == {"athlete": None, "thresholds": [], "current": {"run": None, "bike": None},
                    "hr_zones": {}, "pace_zones": None}  # fmt: skip
    engine.dispose()


def test_put_threshold_changes_only_activities_from_valid_from_on(client):
    """A new LTHR from 2026-09-01 changes the bike rides of 09-02, 09-09, 09-16 – nothing before, no runs."""
    bikes_before, runs_before = loads(client, "bike"), loads(client, "run")
    response = client.put(
        "/api/settings/thresholds", json={"sport": "bike", "valid_from": "2026-09-01", "lthr": BIKE_LTHR + 10}
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["sport"], body["valid_from"], body["lthr"], body["source"]) == (
        "bike", "2026-09-01", BIKE_LTHR + 10, "manual"
    )  # fmt: skip
    assert body["zones"]["hr"] == [0.68, 0.84, 0.95, 1.05] and body["threshold_speed"] is None

    bikes_after, runs_after = loads(client, "bike"), loads(client, "run")
    assert runs_after == runs_before
    changed = sorted(g for g in bikes_before if bikes_after[g] != bikes_before[g])
    assert changed == [BIKE_ID + 5, BIKE_ID + 6, BIKE_ID + 7]
    assert all(bikes_after[g] < bikes_before[g] for g in changed)  # same HR, higher LTHR → less load

    settings = client.get("/api/settings").json()
    assert [t["valid_from"] for t in settings["thresholds"] if t["sport"] == "bike"] == [
        "2026-01-01",
        "2026-09-01",
    ]
    assert settings["current"]["bike"]["lthr"] == BIKE_LTHR + 10
    assert settings["hr_zones"]["bike"][3]["lower"] == pytest.approx(0.95 * (BIKE_LTHR + 10))
    assert client.get("/api/fitness/pmc").json()["latest"]["load_bike"] == pytest.approx(
        loads(client, "bike")[BIKE_ID + 7]
    )


def test_put_run_threshold_with_pace_changes_the_pace_zones(client):
    response = client.put(
        "/api/settings/thresholds",
        json={"sport": "run", "valid_from": "2026-09-10", "lthr": 172, "threshold_speed": 3.7},
    )
    assert response.status_code == 200 and response.json()["threshold_speed"] == 3.7
    settings = client.get("/api/settings").json()
    assert settings["pace_zones"][3]["lower"] == pytest.approx(0.95 * 3.7)
    runs = loads(client, "run")
    assert runs[RUN_ID + 7] != pytest.approx(100 / 3, abs=0.5)  # 09-14 run now judged against 3.7 m/s
    assert runs[RUN_ID + 6] == pytest.approx(100 / 3, abs=0.01)  # 09-07 run is unchanged


@pytest.mark.parametrize(
    "body",
    [
        {"sport": "swim", "valid_from": "2026-09-01", "lthr": 160},
        {"sport": "bike", "valid_from": "2026-09-01", "lthr": 160, "threshold_speed": 3.0},
        {"sport": "run", "valid_from": "2026-09-01", "lthr": 300},
        {"sport": "run", "valid_from": "2026-09-01", "lthr": 170, "threshold_speed": 12},
        {"sport": "run", "valid_from": "2026-09-01", "lthr": 0},  # body validation (gt=0)
        {"sport": "run", "valid_from": "someday", "lthr": 170},
        {"sport": "run", "lthr": 170},
    ],
)
def test_put_threshold_rejects_bad_bodies_with_422(client, body):
    before = client.get("/api/settings").json()
    response = client.put("/api/settings/thresholds", json=body)
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)
    assert client.get("/api/settings").json() == before


def test_put_athlete_partial_update_and_recompute(client):
    response = client.put(
        "/api/settings/athlete", json={"weight_kg": 72.0, "birth_year": 1988, "run_bike_split": 0.6}
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["weight_kg"], body["birth_year"], body["run_bike_split"]) == (72.0, 1988, 0.6)
    assert (body["sex"], body["max_hr"], body["rest_hr_override"]) == ("male", 190.0, 50.0)
    assert client.get("/api/settings").json()["athlete"] == body

    trimp_before = client.get("/api/activities", params={"sport": "other"}).json()["items"][0]["trimp_norm"]
    update = client.put("/api/settings/athlete", json={"max_hr": 205, "sex": "female"})
    assert update.status_code == 200 and update.json()["max_hr"] == 205.0 and update.json()["sex"] == "female"
    trimp_after = client.get("/api/activities", params={"sport": "other"}).json()["items"][0]["trimp_norm"]
    assert trimp_after != pytest.approx(trimp_before)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"sex": "robot"},
        {"birth_year": 1800},
        {"max_hr": -1},
        {"max_hr": 0},
        {"run_bike_split": 1.5},
        {"weight_kg": "heavy"},
    ],
)
def test_put_athlete_rejects_bad_bodies_with_422(client, body):
    before = client.get("/api/settings").json()["athlete"]
    response = client.put("/api/settings/athlete", json=body)
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)
    assert client.get("/api/settings").json()["athlete"] == before


def test_settings_follow_the_today_dependency(engine):
    old = make_client(engine, today=dt.date(2025, 12, 1)).get("/api/settings").json()
    assert old["current"] == {"run": None, "bike": None} and len(old["thresholds"]) == 2
