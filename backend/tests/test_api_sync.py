"""/api/sync, /api/diagnostics, /api/health, error mapping and the exported OpenAPI documents."""

import datetime as dt
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session
from typer.testing import CliRunner

from training import cli
from training.api import deps
from training.api.errors import register_error_handlers
from training.api.export import build_spec, render_api_md, render_openapi_json
from training.api.main import create_app
from training.config import PROJECT_ROOT, Settings, get_settings
from training.db.session import make_engine, migrate
from training.garmin import client as garmin_client
from training.garmin.client import GarminConnectAuthenticationError, GarminConnectTooManyRequestsError
from training.services import diagnostics
from training.services.errors import InvalidInputError, NotFoundError, ServiceError

from .seeding import make_client, seeded_db
from .test_sync import FakeGarmin, make_activity

SYNC_DAY = dt.date(2026, 9, 29)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def fresh(tmp_path):
    path = tmp_path / "fresh.db"
    migrate(path)
    eng = make_engine(path)
    yield eng
    eng.dispose()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None,
        db_path=tmp_path / "training.db",
        garmin_tokens=tmp_path / "tokens",
        rate_limit_s=0.0,
        max_retries=1,
    )


def test_health(engine):
    response = make_client(engine).get("/api/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}


# --- diagnostics --------------------------------------------------------------------------------------------


def test_diagnostics_is_the_service_dto(engine):
    client = make_client(engine)
    response = client.get("/api/diagnostics")
    assert response.status_code == 200
    with Session(engine) as session:
        assert response.json() == diagnostics.get_diagnostics(session).model_dump(mode="json")
    body = response.json()
    assert body["activities"] == 17 and body["activities_with_metrics"] == 17
    assert body["activities_without_threshold"] == 0 and body["last_activity_sync"] == "2026-09-16"
    assert body["load_sanity"]["n"] == 17 and body["hrtss_rtss_divergent"] == []


def test_diagnostics_of_an_empty_database(fresh):
    body = make_client(fresh).get("/api/diagnostics").json()
    assert body["activities"] == 0 and body["load_sanity"]["status"] == "insufficient"
    assert body["last_activity_sync"] is None and body["failed_activities"] == []


# --- sync ---------------------------------------------------------------------------------------------------


def with_garmin(monkeypatch, api) -> None:
    monkeypatch.setattr(garmin_client, "connect", lambda tokens_dir: api)


def test_post_sync_returns_the_sync_result(fresh, settings, monkeypatch):
    api = FakeGarmin([make_activity(1001, SYNC_DAY - dt.timedelta(days=1))])
    with_garmin(monkeypatch, api)
    client = make_client(fresh, today=SYNC_DAY, settings=settings)
    response = client.post("/api/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["activities_new"] == 1 and body["errors"] == [] and body["metrics_computed"] == 1
    assert body["pmc_days"] >= 2 and set(body) == {
        "activities_new", "activities_updated", "activities_unchanged", "activities_pending",
        "activities_failed", "wellness_days", "metrics_computed", "pmc_days", "errors",
    }  # fmt: skip
    again = client.post("/api/sync").json()
    assert again["activities_new"] == 0 and again["activities_unchanged"] == 1
    assert client.get("/api/activities").json()["total"] == 1


def test_post_sync_rejected_login_is_502_with_a_safe_message(fresh, settings, monkeypatch):
    def rejected(tokens_dir):
        raise GarminConnectAuthenticationError("token abc123 expired")

    monkeypatch.setattr(garmin_client, "connect", rejected)
    response = make_client(fresh, today=SYNC_DAY, settings=settings).post("/api/sync")
    assert response.status_code == 502
    assert "training login" in response.json()["detail"] and "abc123" not in response.json()["detail"]


def test_post_sync_rate_limit_is_502(fresh, settings, monkeypatch):
    api = FakeGarmin([make_activity(1001, SYNC_DAY)])
    api.fail["activity_search"] = GarminConnectTooManyRequestsError
    with_garmin(monkeypatch, api)
    response = make_client(fresh, today=SYNC_DAY, settings=settings).post("/api/sync")
    assert response.status_code == 502 and "429" in response.json()["detail"]


# --- error mapping ------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("error", "status"),
    [(NotFoundError("gone"), 404), (InvalidInputError("nope"), 422), (ServiceError("upstream"), 502)],
)
def test_service_errors_map_to_http_statuses(error, status):
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/boom")
    def boom() -> None:
        raise error

    response = TestClient(app).get("/boom")
    assert response.status_code == status and response.json() == {"detail": str(error)}


# --- OpenAPI export -----------------------------------------------------------------------------------------

EXPECTED_ROUTES = {
    ("get", "/api/activities"),
    ("get", "/api/activities/{activity_id}"),
    ("get", "/api/activities/{activity_id}/streams"),
    ("post", "/api/activities/{activity_id}/subjective"),
    ("get", "/api/fitness/pmc"),
    ("get", "/api/fitness/weekly"),
    ("get", "/api/fitness/dashboard"),
    ("get", "/api/progress/ef"),
    ("get", "/api/progress/speed-hr-curve"),
    ("get", "/api/progress/best-efforts"),
    ("get", "/api/progress/predictions"),
    ("get", "/api/progress/threshold-proposals"),
    ("get", "/api/plan/today"),
    ("post", "/api/plan/today/regenerate"),
    ("get", "/api/plan/week"),
    ("get", "/api/plan/season"),
    ("get", "/api/plan/goal"),
    ("put", "/api/plan/goal"),
    ("delete", "/api/plan/goal"),
    ("get", "/api/plan/{planned_id}"),
    ("post", "/api/plan/{planned_id}/status"),
    ("get", "/api/wellness/daily"),
    ("get", "/api/wellness/readiness/today"),
    ("get", "/api/wellness/readiness/{day}"),
    ("get", "/api/wellness/correlations"),
    ("get", "/api/settings"),
    ("put", "/api/settings/thresholds"),
    ("put", "/api/settings/athlete"),
    ("get", "/api/diagnostics"),
    ("post", "/api/sync"),
    ("get", "/api/health"),
}


def test_openapi_documents_every_endpoint_with_its_dto():
    spec = build_spec()
    routes = {(m, p) for p, item in spec["paths"].items() for m in item}
    assert routes == EXPECTED_ROUTES
    schemas = spec["components"]["schemas"]
    dtos = [
        "ActivityListDTO",
        "ActivityDetailDTO",
        "StreamsDTO",
        "PmcDTO",
        "WeeklyDTO",
        "DashboardDTO",
        "SettingsDTO",
        "ThresholdDTO",
        "AthleteDTO",
        "DiagnosticsDTO",
        "SyncResultDTO",
        "SubjectiveDTO",
        "SeriesDTO",
        "CurveDTO",
        "BestEffortsDTO",
        "PredictionsDTO",
        "ProposalDTO",
        "WellnessDTO",
        "ReadinessDTO",
        "CorrelationsDTO",
        "DailyDecisionDTO",
        "WeekPlanDTO",
        "SeasonDTO",
        "GoalDTO",
        "GoalIn",
        "PlannedWorkoutDTO",
        "StatusIn",
    ]
    for name in dtos:
        assert name in schemas, name
    pmc = spec["paths"]["/api/fitness/pmc"]["get"]
    assert pmc["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/PmcDTO")
    assert {p["name"] for p in pmc["parameters"]} == {"from", "to"}


def test_operation_ids_are_the_unique_function_names():
    ids = [op["operationId"] for item in build_spec()["paths"].values() for op in item.values()]
    assert len(ids) == len(set(ids)) == len(EXPECTED_ROUTES)
    assert {"list_activities", "get_pmc", "put_threshold", "post_sync", "health"} <= set(ids)


def test_committed_docs_are_current():
    """Regenerate with `uv run training export-openapi` after changing a route or a DTO."""
    spec = build_spec()
    docs = PROJECT_ROOT / "docs"
    assert (docs / "openapi.json").read_text() == render_openapi_json(spec)
    assert (docs / "API.md").read_text() == render_api_md(spec)


def test_api_md_lists_endpoints_and_fields():
    text = render_api_md(build_spec())
    assert "| GET | `/api/fitness/pmc` | `from`?, `to`? | `PmcDTO` |" in text
    assert "| PUT | `/api/settings/thresholds` | body: `ThresholdIn` | `ThresholdDTO` |" in text
    assert "### PmcPointDTO" in text and "| `ramp_warning` |" in text
    assert "HTTPValidationError" not in text
    assert "| `series` | map<string, (number \\| null)[]> |" in text  # a nullable item type stays readable


def test_export_openapi_command_writes_both_files(tmp_path):
    result = CliRunner().invoke(cli.app, ["export-openapi", "--out-dir", str(tmp_path / "out")])
    assert result.exit_code == 0, result.output
    spec = json.loads((tmp_path / "out" / "openapi.json").read_text())
    assert spec["info"]["title"] == "Training analytics" and len(spec["paths"]) == len(
        {p for _, p in EXPECTED_ROUTES}
    )
    assert (tmp_path / "out" / "API.md").read_text().startswith("# API")


def test_api_command_is_registered_with_host_and_port_options():
    result = CliRunner().invoke(cli.app, ["api", "--help"])
    assert result.exit_code == 0 and "--host" in result.output and "--port" in result.output


def test_default_dependencies_use_the_configured_database_lazily(monkeypatch, tmp_path):
    """Without overrides the app opens (and migrates) the configured DB on first use, once – not at import."""
    db = tmp_path / "x" / "training.db"
    monkeypatch.setenv("TRAINING_DB_PATH", str(db))
    get_settings.cache_clear()
    deps._engine.cache_clear()
    try:
        client = TestClient(create_app())
        assert not db.exists()  # creating the app touches nothing
        response = client.get("/api/settings")
        assert response.status_code == 200 and response.json()["thresholds"] == []
        assert db.exists() and deps._engine() is deps._engine()
        assert deps.get_today() == dt.date.today()
        assert client.get("/api/activities").json()["total"] == 0
    finally:
        if deps._engine.cache_info().currsize:
            deps._engine().dispose()
        deps._engine.cache_clear()
        get_settings.cache_clear()
