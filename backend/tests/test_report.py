"""Weekly AI report: prompt, fake-client generation, storage, API and Dashboard (no network)."""

import datetime as dt
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest
from sqlmodel import Session

from training.api import deps
from training.coach import llm
from training.config import Settings
from training.db.session import make_engine
from training.services import report as svc
from training.services.errors import InvalidInputError, ServiceError

from .seeding import TODAY, make_client, seeded_db
from .wellness_seeding import wellness_db

KEY = "sk-ant-SECRET-KEY-123"


@pytest.fixture(scope="module")
def module_inputs(tmp_path_factory):
    engine = make_engine(wellness_db(tmp_path_factory.mktemp("report")))
    with Session(engine) as session:
        yield svc.weekly_inputs(session, TODAY)
    engine.dispose()


def block(text: str, type_: str = "text"):
    return SimpleNamespace(type=type_, text=text)


def response(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=list(blocks))


class FakeClient:
    def __init__(self, answer=None, error: Exception | None = None):
        self.answer, self.error, self.kwargs = answer, error, None
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.answer


def factory(client):
    return lambda key: client


def api_error(cls, status: int):
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls(f"boom {KEY}", response=httpx.Response(status, request=request), body=None)


# --- prompt -------------------------------------------------------------------------------------------------


def test_inputs_collect_seven_days_and_top_findings(module_inputs):
    inputs = module_inputs
    assert inputs.today == TODAY
    first, last = svc.reviewed_week(TODAY)  # Mon of the week of TODAY − 1 … min(Sun, TODAY)
    assert first.weekday() == 0 and last <= TODAY
    assert [r.date for r in inputs.readiness] == [
        first + dt.timedelta(days=i) for i in range((last - first).days + 1)
    ]
    assert all(first <= a.date <= last for a in inputs.activities)
    assert inputs.activities
    assert inputs.this_week.monday == first
    assert len(inputs.findings) <= 3
    assert inputs.pmc_now is not None and inputs.pmc_week_ago is not None
    assert inputs.next_week.monday == inputs.this_week.monday + dt.timedelta(days=7)


def test_prompt_contains_dto_numbers_and_slovak_rules(module_inputs):
    inputs = module_inputs
    system, user = llm.build_weekly_prompt(inputs)
    assert "po slovensky" in system and "250 slovami" in system
    assert "lekárske rady" in system and "nikdy nemeň" in system and "chýba" in system
    assert system.count("## ") == 3
    now = inputs.pmc_now
    assert f"CTL {now.ctl:.1f}" in user and f"ATL {now.atl:.1f}" in user
    assert f"{inputs.this_week.target_load:.0f}" in user
    assert str(inputs.activities[0].date) in user
    for finding in inputs.findings:
        assert finding.sentence in user and f"ρ = {finding.headline_rho:.2f}" in user
    assert "Cieľ: chýba" in user  # no goal in the seeded DB
    assert KEY not in system + user


def test_prompt_says_missing_for_absent_data(module_inputs):
    empty = module_inputs.model_copy(
        update={"activities": [], "pmc_now": None, "pmc_week_ago": None, "findings": []}
    )
    _, user = llm.build_weekly_prompt(empty)
    assert (
        "žiadne aktivity" in user
        and "koniec hodnoteného týždňa: chýba" in user
        and "chýba (málo dát)" in user
    )


# --- generation ---------------------------------------------------------------------------------------------


def test_call_shape_and_text_join(module_inputs):
    client = FakeClient(response(block("Ahoj "), block("x", "thinking"), block("svet")))
    text = llm.generate_weekly_report(
        module_inputs, api_key=KEY, model="claude-opus-5-5", client_factory=factory(client)
    ).text
    assert text == "Ahoj svet"
    kw = client.kwargs
    assert kw["model"] == "claude-opus-5-5" and kw["max_tokens"] == 4000
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["fallbacks"] == "default"
    assert kw["output_config"] == {"effort": "medium"}
    assert kw["messages"][0]["role"] == "user" and KEY not in kw["system"] + kw["messages"][0]["content"]


def test_refusal_is_a_report_error(module_inputs):
    client = FakeClient(response(block("no"), stop_reason="refusal"))
    with pytest.raises(llm.ReportError, match="refused"):
        llm.generate_weekly_report(module_inputs, api_key=KEY, model="m", client_factory=factory(client))


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (api_error(anthropic.AuthenticationError, 401), "invalid key"),
        (api_error(anthropic.RateLimitError, 429), "rate limit"),
        (api_error(anthropic.InternalServerError, 500), "HTTP 500"),
        (anthropic.APIConnectionError(request=httpx.Request("POST", "https://x")), "connection"),
    ],
)
def test_api_errors_become_report_errors_without_the_key(module_inputs, error, message):
    client = FakeClient(error=error)
    with pytest.raises(llm.ReportError, match=message) as info:
        llm.generate_weekly_report(module_inputs, api_key=KEY, model="m", client_factory=factory(client))
    assert KEY not in str(info.value)


def test_empty_answer_is_a_report_error(module_inputs):
    client = FakeClient(response(block("   ")))
    with pytest.raises(llm.ReportError, match="no text"):
        llm.generate_weekly_report(module_inputs, api_key=KEY, model="m", client_factory=factory(client))


# --- service ------------------------------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def settings(tmp_path, key: str | None = KEY) -> Settings:
    return Settings(anthropic_api_key=key, reports_dir=tmp_path / "reports", _env_file=None)


def test_report_is_written_and_read_back(session, tmp_path):
    cfg = settings(tmp_path)
    assert svc.latest_report(cfg) is None
    client = FakeClient(response(block("## Uplynulý týždeň\nDobre.")))
    created = svc.create_weekly_report(session, TODAY, cfg, client_factory=factory(client))
    path = cfg.reports_dir / "2026-W38.md"
    assert created.week == "2026-W38" and path.exists()
    assert KEY not in path.read_text()
    assert path.read_text().startswith("---\nweek: 2026-W38\n")
    assert svc.latest_report(cfg) == created
    assert created.model == "claude-opus-5-5" and "Dobre." in created.markdown


def test_latest_is_the_newest_week(session, tmp_path):
    cfg = settings(tmp_path)
    for day, text in ((dt.date(2026, 9, 9), "starý"), (TODAY, "nový")):
        svc.create_weekly_report(session, day, cfg, client_factory=factory(FakeClient(response(block(text)))))
    assert svc.latest_report(cfg).markdown.endswith("nový")


def test_missing_key_is_invalid_input(session, tmp_path):
    with pytest.raises(InvalidInputError, match="TRAINING_ANTHROPIC_API_KEY"):
        svc.create_weekly_report(session, TODAY, settings(tmp_path, key=None))
    assert not (tmp_path / "reports").exists()


def test_llm_failure_is_a_service_error_and_stores_nothing(session, tmp_path):
    client = FakeClient(error=api_error(anthropic.AuthenticationError, 401))
    with pytest.raises(ServiceError) as info:
        svc.create_weekly_report(session, TODAY, settings(tmp_path), client_factory=factory(client))
    assert KEY not in str(info.value) and not list((tmp_path / "reports").glob("*"))


def test_malformed_files_are_skipped(tmp_path):
    cfg = settings(tmp_path)
    cfg.reports_dir.mkdir()
    (cfg.reports_dir / "2026-W40.md").write_text("no header")
    assert svc.latest_report(cfg) is None


# --- API ----------------------------------------------------------------------------------------------------


def test_api_latest_404_then_report(engine, tmp_path):
    cfg = settings(tmp_path)
    client = make_client(engine, settings=cfg)
    assert client.get("/api/reports/latest").status_code == 404
    with Session(engine) as s:
        expected = svc.create_weekly_report(
            s, TODAY, cfg, client_factory=factory(FakeClient(response(block("Text"))))
        )
    body = client.get("/api/reports/latest").json()
    assert body == expected.model_dump(mode="json")


def test_api_weekly_without_key_is_422(engine, tmp_path):
    client = make_client(engine, settings=settings(tmp_path, key=None))
    reply = client.post("/api/reports/weekly")
    assert reply.status_code == 422 and "TRAINING_ANTHROPIC_API_KEY" in reply.json()["detail"]


def test_api_weekly_generates(engine, tmp_path, monkeypatch):
    cfg = settings(tmp_path)
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: FakeClient(response(block("Z API"))))
    client = make_client(engine, settings=cfg)
    reply = client.post("/api/reports/weekly")
    assert reply.status_code == 200 and reply.json()["markdown"] == "Z API"
    assert (cfg.reports_dir / "2026-W38.md").exists()
    assert deps.get_config  # dependency exists for overrides


def test_api_weekly_upstream_failure_is_502(engine, tmp_path, monkeypatch):
    err = api_error(anthropic.AuthenticationError, 401)
    monkeypatch.setattr(anthropic, "Anthropic", lambda api_key: FakeClient(error=err))
    reply = make_client(engine, settings=settings(tmp_path)).post("/api/reports/weekly")
    assert reply.status_code == 502 and KEY not in reply.text


# --- review phase 7 follow-ups ---------------------------------------------------------------------------


def test_the_answering_model_is_recorded(module_inputs):
    answer = response(block("Text."))
    answer.model = "claude-opus-4-8"  # a server-side fallback answered
    generated = llm.generate_weekly_report(
        module_inputs, api_key=KEY, model="claude-opus-5-5", client_factory=factory(FakeClient(answer))
    )
    assert generated.model == "claude-opus-4-8" and generated.text == "Text."


def test_a_cut_off_report_is_an_error(module_inputs):
    client = FakeClient(response(block("Uplynulý týž"), stop_reason="max_tokens"))
    with pytest.raises(llm.ReportError, match="cut off"):
        llm.generate_weekly_report(module_inputs, api_key=KEY, model="m", client_factory=factory(client))


def test_missing_optional_extra_is_a_report_error(module_inputs, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def no_anthropic(name, *args, **kwargs):
        if name == "anthropic":
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_anthropic)
    with pytest.raises(llm.ReportError, match="uv sync --extra ai"):
        llm.generate_weekly_report(module_inputs, api_key=KEY, model="m")


@pytest.mark.parametrize(
    ("day", "label"),
    [
        (dt.date(2026, 9, 27), "2026-W39"),  # Sunday evening → the week that ends today
        (dt.date(2026, 9, 28), "2026-W39"),  # Monday morning → the week that just ended
        (dt.date(2026, 9, 30), "2026-W40"),
    ],
)
def test_week_label_names_the_week_that_just_ended(day, label):
    assert llm.week_label(day) == label


def test_a_broken_report_file_is_skipped(tmp_path):
    from training.config import Settings

    (tmp_path / "2026-W40.md").write_bytes(b"\xff\xfe broken")
    assert svc.latest_report(Settings(db_path=tmp_path / "x.db", reports_dir=tmp_path)) is None


@pytest.mark.parametrize(
    ("today", "first", "last"),
    [
        (dt.date(2026, 9, 27), dt.date(2026, 9, 21), dt.date(2026, 9, 27)),  # Sunday evening
        (dt.date(2026, 9, 28), dt.date(2026, 9, 21), dt.date(2026, 9, 27)),  # Monday morning: same week
        (dt.date(2026, 9, 30), dt.date(2026, 9, 28), dt.date(2026, 9, 30)),  # mid-week: clipped to today
    ],
)
def test_reviewed_week_matches_the_label(today, first, last):
    assert svc.reviewed_week(today) == (first, last)
    assert llm.week_label(today) == llm.week_label(last + dt.timedelta(days=1))
