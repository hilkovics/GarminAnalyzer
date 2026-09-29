"""`training propose-thresholds` on the phase-4 scenario DB and on an empty one."""

import pytest
from typer.testing import CliRunner

from training import cli
from training.cli import progress as cli_progress
from training.config import get_settings

from .progress_seeding import progress_db
from .seeding import TODAY

runner = CliRunner()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("TRAINING_GARMIN_TOKENS", str(tmp_path / "tokens"))
    monkeypatch.setattr(cli_progress, "_today", lambda: TODAY)
    get_settings.cache_clear()
    yield monkeypatch, tmp_path
    get_settings.cache_clear()


def test_prints_the_proposals_with_paces_as_m_ss(env):
    monkeypatch, tmp_path = env
    monkeypatch.setenv("TRAINING_DB_PATH", str(progress_db(tmp_path)))
    get_settings.cache_clear()
    result = runner.invoke(cli.app, ["propose-thresholds"], terminal_width=200)
    assert result.exit_code == 0, result.output
    out = result.output
    assert "threshold" in out and "LTHR" in out and "+0.0%" in out
    assert "4:46/km" in out  # current 3.5 m/s = 1000 / 3.5 = 285.7 s → 4:46
    assert "140 bpm" in out and "-30 bpm" in out  # run LTHR estimate vs current 170
    assert "170 bpm" in out and "+5 bpm" in out  # bike estimate vs current 165
    assert "Garmin: lactate-threshold HR 171 " in out and "LT pace 4:38/km" in out  # 3.6 m/s = 277.8 s
    assert "VO2max 52.4" in out
    assert "Nastavenia" in out


def test_says_so_without_proposals(env):
    monkeypatch, tmp_path = env
    monkeypatch.setenv("TRAINING_DB_PATH", str(tmp_path / "db" / "empty.db"))
    get_settings.cache_clear()
    result = runner.invoke(cli.app, ["propose-thresholds"])
    assert result.exit_code == 0, result.output
    assert "No proposals yet" in result.output
