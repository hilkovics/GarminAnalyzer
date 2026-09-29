"""Telegram morning message: content on the seeded DB, sending with a mocked HTTP layer (no network)."""

import logging

import pytest
import requests
from sqlmodel import Session
from typer.testing import CliRunner

from training.cli import app
from training.config import Settings
from training.db.session import make_engine
from training.services import notify

from .seeding import TODAY, seeded_db

TOKEN = "123456:SECRET-TOKEN-VALUE"


@pytest.fixture
def session(tmp_path):
    engine = make_engine(seeded_db(tmp_path))
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture(autouse=True)
def no_delay(monkeypatch):
    monkeypatch.setattr(notify, "RETRY_DELAY_S", 0.0)


def configured() -> Settings:
    return Settings(telegram_token=TOKEN, telegram_chat_id="42", _env_file=None)


class FakeResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code


class FakeHttp:
    """Answers with the queued statuses / exceptions and records every call."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[dict] = []

    def post(self, url, json=None, timeout=None):
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(answer)


def test_message_content_on_the_seeded_db(session):
    message = notify.morning_message(session, TODAY)
    lines = message.text.splitlines()
    assert len(lines) <= 12
    assert lines[0].startswith("Dobré ráno")
    assert any(line.startswith("Pripravenosť:") for line in lines)
    assert any(line.startswith("Dnes: ") and message.workout_name in line for line in lines)
    assert any(line.startswith("Prečo: ") for line in lines)
    assert any(line.startswith("Včera: záťaž ") and "TSB" in line for line in lines)
    assert message.yesterday_load is not None and message.tsb is not None


def test_step_summary_groups_repeats():
    from training.services.dto import WorkoutStepDTO

    def step(type_, minutes, zone, group=None, repeat=None):
        return WorkoutStepDTO(
            type=type_, duration_s=minutes * 60, target_kind="hr_zone", zone=zone, repeat=repeat, group=group
        )

    steps = [
        step("warmup", 15, 2),
        step("work", 6, 4, 0, 5),
        step("recovery", 2, 1, 0, 5),
        step("cooldown", 10, 1),
    ]
    assert (
        notify.step_summary(steps) == "Rozcvička 15 min Z2; 5× (6 min Z4 / 2 min Z1); Vychladenie 10 min Z1"
    )


def test_not_configured_makes_no_call(session):
    http = FakeHttp()
    assert notify.send_morning(session, TODAY, Settings(_env_file=None), http=http) is False
    assert http.calls == []


def test_success_posts_chat_id_and_text(session):
    http = FakeHttp(200)
    assert notify.send_morning(session, TODAY, configured(), http=http) is True
    (call,) = http.calls
    assert call["url"] == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert call["timeout"] == 10
    assert call["json"]["chat_id"] == "42"
    assert call["json"]["text"] == notify.morning_message(session, TODAY).text


def test_server_error_is_retried_once(session):
    http = FakeHttp(500, 200)
    assert notify.send_morning(session, TODAY, configured(), http=http) is True
    assert len(http.calls) == 2


def test_two_server_errors_give_false(session):
    http = FakeHttp(502, 500)
    assert notify.send_morning(session, TODAY, configured(), http=http) is False
    assert len(http.calls) == 2


def test_client_error_is_not_retried(session):
    http = FakeHttp(401)
    assert notify.send_morning(session, TODAY, configured(), http=http) is False
    assert len(http.calls) == 1


def test_timeout_gives_false_without_exception(session):
    http = FakeHttp(
        requests.Timeout(f"https://api.telegram.org/bot{TOKEN}/sendMessage"), requests.Timeout("x")
    )
    assert notify.send_morning(session, TODAY, configured(), http=http) is False


def test_token_never_reaches_logs(session, caplog):
    caplog.set_level(logging.DEBUG)
    leaky = requests.ConnectionError(f"HTTPSConnectionPool: /bot{TOKEN}/sendMessage")
    for answers in ((leaky, leaky), (500, 500), (401,), (RuntimeError(TOKEN),)):
        notify.send_morning(session, TODAY, configured(), http=FakeHttp(*answers))
    assert caplog.records
    assert TOKEN not in caplog.text and "SECRET" not in caplog.text
    assert "api.telegram.org" not in caplog.text
    assert TOKEN not in repr(configured())


def test_cli_dry_run_prints_message_and_never_sends(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAINING_DB_PATH", str(seeded_db(tmp_path)))
    monkeypatch.setenv("TRAINING_TELEGRAM_TOKEN", TOKEN)
    monkeypatch.setenv("TRAINING_TELEGRAM_CHAT_ID", "42")
    monkeypatch.setattr("training.cli.notify.dt", _FrozenDt)
    monkeypatch.setattr(
        notify.requests, "post", lambda *a, **k: pytest.fail("dry run must not touch the network")
    )
    from training.config import get_settings

    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["telegram-morning", "--dry-run"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0, result.output
    assert "Pripravenosť:" in result.output and TOKEN not in result.output


def test_cli_without_configuration_does_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAINING_DB_PATH", str(seeded_db(tmp_path)))
    monkeypatch.delenv("TRAINING_TELEGRAM_TOKEN", raising=False)
    monkeypatch.delenv("TRAINING_TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.setattr(notify.requests, "post", lambda *a, **k: pytest.fail("no network"))
    from training.config import get_settings

    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(app, ["telegram-morning"])
    finally:
        get_settings.cache_clear()
    assert result.exit_code == 0 and "not configured" in result.output


class _FrozenDt:
    """`dt` stand-in for the CLI module: `date.today()` is the seeded TODAY."""

    import datetime as _real

    class date(_real.date):
        @classmethod
        def today(cls):
            return TODAY
