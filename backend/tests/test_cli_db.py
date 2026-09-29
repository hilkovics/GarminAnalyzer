"""`training db-stats` / `training sync` wiring with a temporary DB and a fake Garmin client."""

import pytest
from typer.testing import CliRunner

from training import cli
from training.config import get_settings
from training.garmin import client as garmin_client

from .test_sync import FakeGarmin, make_activity

runner = CliRunner()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_DB_PATH", str(tmp_path / "db" / "training.db"))
    monkeypatch.setenv("TRAINING_RATE_LIMIT_S", "0")
    monkeypatch.setenv("TRAINING_GARMIN_TOKENS", str(tmp_path / "tokens"))
    monkeypatch.setenv("GARMINTOKENS", str(tmp_path / "tokens"))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


def test_db_stats_on_fresh_db(env):
    result = runner.invoke(cli.app, ["db-stats"])
    assert result.exit_code == 0, result.output
    assert "activity_stream" in result.output and "sync_state" in result.output
    assert (env / "db" / "training.db").exists()


def test_sync_command_uses_client_and_reports(env, monkeypatch):
    import datetime as dt

    api = FakeGarmin([make_activity(7, dt.date.today() - dt.timedelta(days=1))])
    monkeypatch.setattr(garmin_client, "connect", lambda tokens_dir: api)
    result = runner.invoke(cli.app, ["sync"])
    assert result.exit_code == 0, result.output
    assert "1 new" in result.output
    stats = runner.invoke(cli.app, ["db-stats"])
    assert "activity_summary" in stats.output


def test_sync_without_tokens_fails_cleanly(env):
    result = runner.invoke(cli.app, ["sync"])
    assert result.exit_code == 1
    assert "training login" in result.output


def test_backfill_command_and_network_failure_exit_cleanly(env, monkeypatch):
    import datetime as dt

    api = FakeGarmin([make_activity(8, dt.date.today())])
    monkeypatch.setattr(garmin_client, "connect", lambda tokens_dir: api)
    result = runner.invoke(cli.app, ["backfill", "--months", "1"])
    assert result.exit_code == 0, result.output
    assert "1 new" in result.output

    def unreachable(tokens_dir):
        raise garmin_client.GarminConnectConnectionError("connection reset")

    monkeypatch.setattr(garmin_client, "connect", unreachable)
    result = runner.invoke(cli.app, ["sync"])
    assert result.exit_code == 1
    assert "Could not reach Garmin Connect" in result.output


def test_sync_retry_failed_and_queue_stats(env, monkeypatch):
    api = FakeGarmin([])
    monkeypatch.setattr(garmin_client, "connect", lambda tokens_dir: api)
    result = runner.invoke(cli.app, ["sync", "--retry-failed"])
    assert result.exit_code == 0, result.output
    assert "Retrying 0 previously failed items" in result.output
    stats = runner.invoke(cli.app, ["db-stats"])
    assert "pending_activities: 0" in stats.output and "failed_wellness_days: 0" in stats.output


def test_threshold_athlete_recompute_diagnostics_commands(env):
    r = runner.invoke(cli.app, ["threshold", "add", "--sport", "run", "--lthr", "168", "--pace", "4:10",
                                "--valid-from", "2026-01-01"])  # fmt: skip
    assert r.exit_code == 0, r.output
    assert "pace 4:10/km" in r.output
    listing = runner.invoke(cli.app, ["threshold", "list"])
    assert "168" in listing.output and "4:10/km" in listing.output
    assert runner.invoke(cli.app, ["athlete", "--sex", "male", "--max-hr", "192"]).exit_code == 0
    assert runner.invoke(cli.app, ["recompute"]).exit_code == 0
    diag = runner.invoke(cli.app, ["diagnostics"])
    assert diag.exit_code == 0, diag.output
    assert "insufficient" in diag.output


def test_pace_conversion_is_presentation_only():
    from training.cli.metrics import format_pace, parse_pace

    assert parse_pace("4:00") == pytest.approx(1000 / 240)
    assert format_pace(parse_pace("4:05")) == "4:05/km"
    import typer

    for bad in ("4:75", ":30", "4", "4:5", "abc", "0:00"):
        with pytest.raises(typer.BadParameter):
            parse_pace(bad)


def test_athlete_without_options_creates_nothing(env):
    r = runner.invoke(cli.app, ["athlete"])
    assert r.exit_code == 0 and "No athlete settings yet" in r.output
    args = [
        "threshold",
        "add",
        "--sport",
        "bike",
        "--lthr",
        "160",
        "--pace",
        "4:00",
        "--valid-from",
        "2026-01-01",
    ]
    bike_pace = runner.invoke(cli.app, args)
    assert bike_pace.exit_code != 0
