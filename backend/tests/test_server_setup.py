"""scripts/server_setup.sh with fake `docker`, `curl` and `tailscale` on PATH (no daemon, no network)."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "server_setup.sh"
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs bash")


def fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def server(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "server_setup.sh")
    home = tmp_path / "home"
    home.mkdir()
    calls = tmp_path / "calls.txt"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake(bin_dir, "docker", f'echo "docker $*" >> "{calls}"')
    fake(bin_dir, "curl", f'echo "curl $*" >> "{calls}"')
    fake(bin_dir, "sudo", f'echo "sudo $*" >> "{calls}"')
    env = {**os.environ, "HOME": str(home), "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin"}
    return repo, home, calls, bin_dir, env


def run(server, *args):
    repo, _, _, _, env = server
    script = repo / "scripts" / "server_setup.sh"
    return subprocess.run(["bash", str(script), *args], env=env, capture_output=True, text=True, check=False)


def test_first_run_writes_env_builds_and_explains_missing_pieces(server):
    repo, home, calls, _, _ = server
    result = run(server)
    assert result.returncode == 0, result.stderr
    env = dict(line.split("=", 1) for line in (repo / ".env").read_text().splitlines())
    assert env["MORNING_AT"] == "09:00" and env["TZ"] == "Europe/Bratislava"
    assert env["UID"] == str(os.getuid()) and env["GID"] == str(os.getgid())
    assert oct((repo / ".env").stat().st_mode & 0o777) == "0o600"
    log = calls.read_text()
    assert "docker compose up -d --build" in log and "curl -fsS http://127.0.0.1:8000/api/health" in log
    assert "no Garmin tokens" in result.stdout and "Tailscale is not installed" in result.stdout
    assert (home / ".garminconnect").is_dir() and (repo / "data" / "logs").is_dir()


def test_rerun_keeps_user_values_and_serves_through_tailscale(server):
    repo, home, calls, bin_dir, _ = server
    (repo / ".env").write_text("MORNING_AT=07:30\nTRAINING_TELEGRAM_TOKEN=secret\n")
    (home / ".garminconnect").mkdir()
    (home / ".garminconnect" / "garmin_tokens.json").write_text("{}")
    fake(
        bin_dir,
        "tailscale",
        'if [[ "$1" == status && "$2" == --json ]]; then '
        'echo \'{"Self": {"DNSName": "trening.tail1.ts.net."}}\'; fi',
    )
    result = run(server)
    assert result.returncode == 0, result.stderr
    lines = (repo / ".env").read_text().splitlines()
    assert lines.count("MORNING_AT=07:30") == 1 and not any(line == "MORNING_AT=09:00" for line in lines)
    assert "TRAINING_TELEGRAM_TOKEN=secret" in lines
    assert "sudo tailscale serve --bg 8000" in calls.read_text()
    assert "https://trening.tail1.ts.net/" in result.stdout and "ok: Garmin tokens" in result.stdout
    assert run(server).returncode == 0
    assert (repo / ".env").read_text().count("UID=") == 1  # idempotent


def test_missing_docker_stops_with_the_install_hint(server):
    repo, _, _, bin_dir, env = server
    (bin_dir / "docker").unlink()
    env = {**env, "PATH": str(bin_dir)}  # no system docker either
    script = repo / "scripts" / "server_setup.sh"
    result = subprocess.run(["/bin/bash", str(script)], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == 1 and "get.docker.com" in result.stderr
