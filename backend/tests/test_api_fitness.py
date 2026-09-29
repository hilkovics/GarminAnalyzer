"""/api/fitness endpoints. PLAN phase 3 acceptance: GET /api/fitness/pmc returns what the UI shows."""

import datetime as dt

import pytest
from sqlmodel import Session

from training.db.session import make_engine, migrate
from training.services import fitness as svc

from .seeding import FIRST_MONDAY, TODAY, make_client, seeded_db


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


def as_json(dto) -> dict | list:
    if isinstance(dto, list):
        return [d.model_dump(mode="json") for d in dto]
    return dto.model_dump(mode="json")


def test_pmc_is_exactly_the_dto_the_ui_gets_from_the_service(client, session):
    """Streamlit calls `get_pmc(session)` directly; the API must serialize the very same object."""
    response = client.get("/api/fitness/pmc")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_pmc(session))
    body = response.json()
    assert len(body["points"]) == (TODAY - FIRST_MONDAY).days + 1
    assert body["series_start"] == "2026-07-27" and body["latest"] == body["points"][-1]
    point = body["points"][-1]
    assert set(point) == {
        "date", "load_total", "load_run", "load_bike", "ctl", "atl", "tsb", "acwr", "acwr_band",
        "monotony", "strain", "ramp_rate", "ramp_warning", "warming_up",
    }  # fmt: skip


def test_pmc_range(client, session):
    response = client.get("/api/fitness/pmc", params={"from": "2026-09-01", "to": "2026-09-10"})
    assert response.status_code == 200
    assert response.json() == as_json(
        svc.get_pmc(session, date_from=dt.date(2026, 9, 1), date_to=dt.date(2026, 9, 10))
    )
    assert [p["date"] for p in response.json()["points"]][:2] == ["2026-09-01", "2026-09-02"]
    assert len(response.json()["points"]) == 10


def test_pmc_of_an_empty_database_and_bad_dates(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = make_engine(path)
    client = make_client(engine)
    assert client.get("/api/fitness/pmc").json() == {
        "points": [], "series_start": None, "warming_up_until": None, "latest": None
    }  # fmt: skip
    for params in ({"from": "soon"}, {"to": "2026-13-01"}):
        response = client.get("/api/fitness/pmc", params=params)
        assert response.status_code == 422 and isinstance(response.json()["detail"], str)
    engine.dispose()


def test_weekly_default_and_weeks_parameter(client, session):
    default = client.get("/api/fitness/weekly")
    assert default.status_code == 200
    assert default.json() == as_json(svc.get_weekly(session, weeks=12, today=TODAY))
    assert len(default.json()) == 37
    two = client.get("/api/fitness/weekly", params={"weeks": 2})
    assert two.json() == as_json(svc.get_weekly(session, weeks=2, today=TODAY))
    assert [r["sport"] for r in two.json()] == ["run", "bike", "all"] * 2
    row = two.json()[-1]
    assert row["week_start"] == "2026-09-14" and row["n_activities"] == 2 and row["sport"] == "all"


@pytest.mark.parametrize("weeks", [0, -3, 10_000, "many"])
def test_weekly_bad_weeks_is_422(client, weeks):
    response = client.get("/api/fitness/weekly", params={"weeks": weeks})
    assert response.status_code == 422 and isinstance(response.json()["detail"], str)


def test_dashboard_is_the_service_dto_and_uses_the_today_dependency(client, session, engine):
    response = client.get("/api/fitness/dashboard")
    assert response.status_code == 200
    assert response.json() == as_json(svc.get_dashboard(session, today=TODAY))
    body = response.json()
    assert body["today"] == "2026-09-16" and body["week_start"] == "2026-09-14"
    assert len(body["pmc"]["points"]) == 42 and body["latest"] == body["pmc"]["latest"]
    assert body["last_sync"] == "2026-09-16" and body["sync_stale"] is False

    later = make_client(engine, today=dt.date(2026, 9, 21)).get("/api/fitness/dashboard").json()
    assert later["week_start"] == "2026-09-21" and later["sync_stale"] is True  # last sync 5 days ago
    assert all(row["n_activities"] == 0 for row in later["this_week"])
