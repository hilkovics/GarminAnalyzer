"""/api/activities endpoints: same DTOs as the services, error mapping, validation."""

import datetime as dt

import pytest
from sqlmodel import Session

from training.db.session import make_engine
from training.services import activities as svc

from .seeding import BIKE_ID, RUN_ID, aid, make_client, seeded_db


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


def as_json(dto) -> dict:
    return dto.model_dump(mode="json")


# --- list ---------------------------------------------------------------------------------------------------


def test_list_returns_the_service_dto(client, session):
    response = client.get("/api/activities")
    assert response.status_code == 200
    assert response.json() == as_json(svc.list_activities(session))
    assert response.json()["total"] == 17 and response.json()["items"][0]["garmin_id"] == BIKE_ID + 7


def test_list_query_parameters_map_to_the_service(client, session):
    query = {"from": "2026-08-01", "to": "2026-08-10", "sport": "run", "page": 1, "page_size": 1}
    response = client.get("/api/activities", params=query)
    assert response.status_code == 200
    expected = svc.list_activities(
        session, date_from=dt.date(2026, 8, 1), date_to=dt.date(2026, 8, 10), sport="run", page=1, page_size=1
    )
    assert response.json() == as_json(expected)
    assert response.json()["total"] == 2 and len(response.json()["items"]) == 1
    page2 = client.get("/api/activities", params={**query, "page": 2}).json()
    assert page2["items"][0]["garmin_id"] != response.json()["items"][0]["garmin_id"]


@pytest.mark.parametrize(
    "params",
    [
        {"sport": "swim"},
        {"page": 0},
        {"page_size": 0},
        {"page_size": 100000},
        {"from": "yesterday"},
        {"page": "x"},
    ],
)
def test_list_bad_parameters_are_422_with_a_string_detail(client, params):
    response = client.get("/api/activities", params=params)
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str) and response.json()["detail"]


# --- detail -------------------------------------------------------------------------------------------------


def test_detail_returns_the_service_dto(client, session):
    activity_id = aid(session, RUN_ID)
    response = client.get(f"/api/activities/{activity_id}")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_activity(session, activity_id))
    body = response.json()
    assert body["summary"]["garmin_id"] == RUN_ID and body["threshold"]["sport"] == "run"
    assert len(body["hr_zones"]) == 5 and len(body["pace_zones"]) == 5 and body["laps"] == []


def test_detail_of_unknown_activity_is_404(client):
    response = client.get("/api/activities/123456")
    assert response.status_code == 404
    assert "123456" in response.json()["detail"]


def test_detail_with_a_non_numeric_id_is_422(client):
    assert client.get("/api/activities/abc").status_code == 422


# --- streams ------------------------------------------------------------------------------------------------


def test_streams_default_and_explicit_fields(client, session):
    activity_id = aid(session, RUN_ID)
    default = client.get(f"/api/activities/{activity_id}/streams")
    assert default.status_code == 200
    assert default.json() == as_json(svc.get_streams(session, activity_id))
    assert list(default.json()["series"]) == ["hr", "speed", "alt"]

    explicit = client.get(
        f"/api/activities/{activity_id}/streams", params={"fields": "hr,gap_speed, grade", "points": 100}
    )
    assert explicit.status_code == 200
    assert explicit.json() == as_json(
        svc.get_streams(session, activity_id, ["hr", "gap_speed", "grade"], 100)
    )
    body = explicit.json()
    assert (
        body["points"] <= 100
        and body["source_points"] == 1200
        and list(body["series"]) == ["hr", "gap_speed", "grade"]
    )


def test_streams_errors(client, session):
    activity_id = aid(session, RUN_ID)
    bad_field = client.get(f"/api/activities/{activity_id}/streams", params={"fields": "hr,watts"})
    assert bad_field.status_code == 422 and "watts" in bad_field.json()["detail"]
    for points in (2, 2001, "many"):
        r = client.get(f"/api/activities/{activity_id}/streams", params={"points": points})
        assert r.status_code == 422, points
    assert client.get("/api/activities/123456/streams").status_code == 404


# --- subjective ---------------------------------------------------------------------------------------------


def test_subjective_upsert_round_trip(client, session):
    activity_id = aid(session, RUN_ID + 2)
    first = client.post(
        f"/api/activities/{activity_id}/subjective",
        json={"rpe": 7, "feel": 3, "soreness": 2, "notes": "heavy legs"},
    )
    assert first.status_code == 200
    body = first.json()
    assert body["activity_id"] == activity_id and body["date"] == "2026-08-10" and body["rpe"] == 7
    assert body["notes"] == "heavy legs" and isinstance(body["id"], int)

    second = client.post(f"/api/activities/{activity_id}/subjective", json={"rpe": 4})
    assert second.json()["id"] == body["id"] and second.json()["notes"] is None  # one row per activity
    detail = client.get(f"/api/activities/{activity_id}").json()
    assert detail["subjective"] == second.json()
    assert client.get(f"/api/activities/{aid(session, RUN_ID)}").json()["subjective"] is None


def test_subjective_errors(client, session):
    assert client.post("/api/activities/123456/subjective", json={"rpe": 5}).status_code == 404
    activity_id = aid(session, RUN_ID)
    for body in (
        {"rpe": 11},
        {"rpe": 0},
        {"feel": 6},
        {"soreness": 4},
        {"notes": "x" * 2001},
        {"rpe": "hard"},
    ):
        r = client.post(f"/api/activities/{activity_id}/subjective", json=body)
        assert r.status_code == 422, body
        assert isinstance(r.json()["detail"], str)
    assert client.get(f"/api/activities/{activity_id}").json()["subjective"] is None  # nothing was stored
