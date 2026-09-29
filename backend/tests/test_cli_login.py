"""CLI login/whoami with garminconnect mocked at the client boundary (no network)."""

import json
from pathlib import Path
from typing import ClassVar

import pytest
from typer.testing import CliRunner

from training import cli
from training.config import get_settings
from training.garmin import client as garmin_client

SECRET = "hunter2-secret"


class FakeTokenClient:
    def dump(self, path: str) -> None:
        file = garmin_client.token_file(Path(path))
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(json.dumps({"di_token": "t"}))


class FakeGarmin:
    instances: ClassVar[list["FakeGarmin"]] = []
    fail_with: ClassVar[Exception | None] = None

    def __init__(self, email=None, password=None, prompt_mfa=None, **_):
        self.email, self.password, self.prompt_mfa = email, password, prompt_mfa
        self.client = FakeTokenClient()
        self.display_name = "abc-123"
        FakeGarmin.instances.append(self)

    def login(self, tokenstore=None):
        if FakeGarmin.fail_with:
            raise FakeGarmin.fail_with
        if self.password is None and not garmin_client.token_file(Path(tokenstore)).exists():
            raise garmin_client.GarminConnectAuthenticationError("Username and password are required")
        if self.password is not None:
            assert self.prompt_mfa() == "123456"
        self.password = None
        return None, None

    def get_full_name(self):
        return "Test Athlete"


@pytest.fixture
def env(monkeypatch, tmp_path):
    # both variables: TRAINING_GARMIN_TOKENS wins if exported, and must never point at real tokens here
    monkeypatch.setenv("GARMINTOKENS", str(tmp_path / "tokens"))
    monkeypatch.setenv("TRAINING_GARMIN_TOKENS", str(tmp_path / "tokens"))
    get_settings.cache_clear()
    monkeypatch.setattr(garmin_client, "Garmin", FakeGarmin)
    FakeGarmin.instances.clear()
    FakeGarmin.fail_with = None
    yield tmp_path / "tokens"
    get_settings.cache_clear()


runner = CliRunner()


def test_login_stores_tokens_and_never_echoes_password(env):
    result = runner.invoke(cli.app, ["login"], input=f"me@example.com\n{SECRET}\n123456\n")
    assert result.exit_code == 0, result.output
    assert "Logged in as Test Athlete" in result.output
    assert SECRET not in result.output
    token = env / "garmin_tokens.json"
    assert token.exists()
    assert SECRET not in token.read_text()


def test_login_skips_credentials_when_tokens_valid(env):
    runner.invoke(cli.app, ["login"], input=f"me@example.com\n{SECRET}\n123456\n")
    result = runner.invoke(cli.app, ["login"])
    assert result.exit_code == 0, result.output
    assert "Already logged in" in result.output


def test_login_auth_failure_exits_nonzero(env):
    FakeGarmin.fail_with = garmin_client.GarminConnectAuthenticationError("bad credentials")
    result = runner.invoke(cli.app, ["login"], input=f"me@example.com\n{SECRET}\n")
    assert result.exit_code == 1
    assert SECRET not in result.output


def test_whoami_requires_tokens(env):
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 1
    assert "training login" in result.output


def test_whoami_prints_name(env):
    runner.invoke(cli.app, ["login"], input=f"me@example.com\n{SECRET}\n123456\n")
    result = runner.invoke(cli.app, ["whoami"])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "Test Athlete"


def test_force_login_failure_keeps_previous_tokens(env):
    runner.invoke(cli.app, ["login"], input=f"me@example.com\n{SECRET}\n123456\n")
    before = (env / "garmin_tokens.json").read_text()
    FakeGarmin.fail_with = garmin_client.GarminConnectAuthenticationError("bad credentials")
    result = runner.invoke(cli.app, ["login", "--force"], input=f"me@example.com\n{SECRET}\n")
    assert result.exit_code == 1
    assert (env / "garmin_tokens.json").read_text() == before
    assert not (env / "garmin_tokens.json.bak").exists()


def test_force_login_success_replaces_tokens(env):
    runner.invoke(cli.app, ["login"], input=f"me@example.com\n{SECRET}\n123456\n")
    result = runner.invoke(cli.app, ["login", "--force"], input=f"me@example.com\n{SECRET}\n123456\n")
    assert result.exit_code == 0, result.output
    assert "Logged in as" in result.output
    assert not (env / "garmin_tokens.json.bak").exists()


def test_token_write_failure_is_reported_without_traceback(env, monkeypatch):
    def broken_dump(self, path):
        raise OSError("read-only")

    monkeypatch.setattr(FakeTokenClient, "dump", broken_dump)
    result = runner.invoke(cli.app, ["login"], input=f"me@example.com\n{SECRET}\n123456\n")
    assert result.exit_code == 1
    assert "Could not store tokens" in result.output
    assert SECRET not in result.output
