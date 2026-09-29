"""/api/progress endpoints: the DTO of the service, serialized 1:1, and 422 on invalid parameters."""

import pytest
from sqlmodel import Session

from training.db.session import make_engine, migrate
from training.services import progress as svc

from .progress_seeding import EASY_DAYS, progress_db
from .seeding import TODAY, make_client


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(progress_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def client(engine):
    return make_client(engine)


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def as_json(dto) -> dict | list:
    if isinstance(dto, list):
        return [d.model_dump(mode="json") for d in dto]
    return dto.model_dump(mode="json")


def test_ef_is_the_service_dto(client, session):
    response = client.get("/api/progress/ef")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_ef_series(session, today=TODAY))
    body = response.json()
    assert (body["metric"], body["sport"], body["unit"]) == ("ef", "run", "m/min/bpm")
    assert [p["local_date"] for p in body["points"]] == [d.isoformat() for d in EASY_DAYS]
    assert len(body["trend"]) == 180


@pytest.mark.parametrize(
    "query",
    ["sport=bike&days=30", "metric=decoupling_pct&days=90", "metric=pace_at_ref_hr_day&sport=run"],
)
def test_ef_parameters(client, session, query):
    params = dict(part.split("=") for part in query.split("&"))
    kwargs = {k: (int(v) if k == "days" else v) for k, v in params.items()}
    response = client.get(f"/api/progress/ef?{query}")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_ef_series(session, today=TODAY, **kwargs))


@pytest.mark.parametrize(
    "query",
    ["metric=nope", "sport=other", "sport=swim", "days=0", "days=abc", "days=99999", "days=-3"],
)
def test_ef_invalid_parameters_are_422(client, query):
    response = client.get(f"/api/progress/ef?{query}")
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)


def test_speed_hr_curve(client, session):
    response = client.get("/api/progress/speed-hr-curve")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_speed_hr_curves(session, months=6, today=TODAY))
    body = response.json()
    assert [c["month"] for c in body] == ["2026-07", "2026-08", "2026-09"]
    assert set(body[-1]) == {"month", "sport", "bins", "ref_hr", "pace_at_ref_hr"}
    assert set(body[-1]["bins"][0]) == {"hr_bin", "gap_speed", "count"}
    assert [c["month"] for c in client.get("/api/progress/speed-hr-curve?months=1").json()] == ["2026-09"]


@pytest.mark.parametrize("query", ["months=0", "months=abc", "months=1000", "months=-1"])
def test_speed_hr_curve_invalid_parameters_are_422(client, query):
    assert client.get(f"/api/progress/speed-hr-curve?{query}").status_code == 422


@pytest.mark.parametrize("range_", ["90d", "all"])
def test_best_efforts(client, session, range_):
    response = client.get(f"/api/progress/best-efforts?range={range_}")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_best_efforts(session, sport="run", range=range_, today=TODAY))
    body = response.json()
    assert body["range"] == range_ and body["efforts"]
    assert set(body["efforts"][0]) == {"kind", "window_s", "value", "local_date", "activity_id", "distance_m"}


def test_best_efforts_default_range_and_bike(client, session):
    assert client.get("/api/progress/best-efforts").json()["range"] == "90d"
    bike = client.get("/api/progress/best-efforts?sport=bike&range=all")
    assert bike.status_code == 200
    assert bike.json() == as_json(svc.get_best_efforts(session, sport="bike", range="all", today=TODAY))


@pytest.mark.parametrize("query", ["range=30d", "range=", "sport=other", "sport=swim"])
def test_best_efforts_invalid_parameters_are_422(client, query):
    assert client.get(f"/api/progress/best-efforts?{query}").status_code == 422


def test_predictions(client, session):
    response = client.get("/api/progress/predictions")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_predictions(session, today=TODAY))
    body = response.json()
    assert body["reference"]["source"] == "race" and body["stale"] is False
    assert [p["name"] for p in body["predictions"]] == ["5k", "10k", "half", "marathon"]


def test_threshold_proposals(client, session):
    response = client.get("/api/progress/threshold-proposals")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_threshold_proposals(session, today=TODAY))
    body = response.json()
    assert [(p["sport"], p["field"]) for p in body] == [
        ("run", "threshold_speed"),
        ("run", "lthr"),
        ("bike", "lthr"),
    ]
    assert set(body[0]) == {
        "sport", "field", "current", "estimate", "change", "propose", "basis",
        "garmin_lthr", "garmin_lt_speed", "garmin_vo2max",
    }  # fmt: skip


def test_empty_database_gives_empty_but_valid_bodies(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = make_engine(path)
    client = make_client(engine)
    try:
        assert client.get("/api/progress/ef").json()["points"] == []
        assert client.get("/api/progress/speed-hr-curve").json() == []
        assert client.get("/api/progress/best-efforts").json()["efforts"] == []
        assert client.get("/api/progress/predictions").json() == {
            "reference": None,
            "stale": False,
            "predictions": [],
        }
        assert client.get("/api/progress/threshold-proposals").json() == []
    finally:
        engine.dispose()


def test_put_threshold_accepts_the_proposal_source(client):
    body = {
        "sport": "run",
        "valid_from": "2026-09-16",
        "lthr": 168,
        "threshold_speed": 3.5,
        "source": "proposal",
    }
    response = client.put("/api/settings/thresholds", json=body)
    assert response.status_code == 200 and response.json()["source"] == "proposal"
    body["source"] = "magic"
    assert client.put("/api/settings/thresholds", json=body).status_code == 422
    del body["source"]
    assert client.put("/api/settings/thresholds", json=body).json()["source"] == "manual"
