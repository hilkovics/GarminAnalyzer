"""scripts/android/setup.sh with fake Termux tools on PATH (no phone, no network, no Debian).

The fake `proot-distro login … -- bash -lc CMD …` runs CMD for real when it is the generated `garmin` wrapper
(with a fake `uv` in a fake Debian home), so quoting, the time zone and argument passing are exercised.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "android" / "setup.sh"
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs bash")


def fake(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n")
    path.chmod(0o755)


@pytest.fixture
def phone(tmp_path):
    home = tmp_path / "home"
    repo = home / "GarminAnalyzer"
    (repo / "scripts" / "android").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts" / "android" / "setup.sh")
    debian_home = tmp_path / "debian-root"
    (debian_home / ".local" / "bin").mkdir(parents=True)
    calls = tmp_path / "calls.txt"
    fake(debian_home / ".local" / "bin", "uv", f'echo "uv TZ=$TZ PWD=$PWD ARGS:$*" >> "{calls}"')
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    crontab_file = tmp_path / "crontab.txt"
    for name in ("pkg", "termux-setup-storage", "termux-wake-lock", "crond", "termux-open-url", "git"):
        fake(bin_dir, name, f'echo "{name} $*" >> "{calls}"')
    fake(bin_dir, "pgrep", "exit 1")
    fake(bin_dir, "pkill", f'echo "pkill $*" >> "{calls}"')
    fake(bin_dir, "getprop", "echo Europe/Prague")
    fake(bin_dir, "curl", "exit 0")
    fake(
        bin_dir,
        "crontab",
        f'if [ "$1" = "-l" ]; then cat "{crontab_file}" 2>/dev/null; else cat > "{crontab_file}"; fi',
    )
    fake(
        bin_dir,
        "proot-distro",
        f"""echo "proot-distro $1" >> "{calls}"
if [ "$1" = login ]; then
  shift 2
  while [ "$1" != "--" ]; do echo "  opt $1" >> "{calls}"; shift; done
  shift
  [ "$1" = true ] && exit 0
  case "$3" in *training*)  # emulate the bind mount of the repository
    cmd="${{3//"/root/GarminAnalyzer"/{repo}}}"; shift 3; HOME="{debian_home}" exec bash -c "$cmd" "$@" ;;
  esac
  echo "  debian-cmd: $3" >> "{calls}"
fi""",
    )
    env = {
        **os.environ,
        "HOME": str(home),
        "PREFIX": "/usr",
        "GA_ALLOW_NON_TERMUX": "1",
        "GA_IMPORT_DIR": str(tmp_path / "Download" / "GarminAnalyzer"),
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
    }
    return home, repo, calls, crontab_file, env, tmp_path


def run_setup(phone):
    _, repo, _, _, env, _ = phone
    return subprocess.run(
        ["bash", str(repo / "scripts" / "android" / "setup.sh")], env=env, capture_output=True, text=True
    )


def test_setup_installs_syncs_writes_commands_and_the_cron_line(phone):
    home, repo, calls, crontab_file, _, _ = phone
    result = run_setup(phone)
    assert result.returncode == 0, result.stderr
    log = calls.read_text()
    assert "pkg install -y proot-distro cronie termux-api procps curl" in log
    assert (
        'uv" sync --frozen --no-dev' in log and "apt-get install -y -q curl ca-certificates git tzdata" in log
    )
    assert (
        f"opt {repo}:/root/GarminAnalyzer" in log and f"opt {home}/.garminconnect:/root/.garminconnect" in log
    )
    for path in (
        ".local/bin/garmin",
        ".local/bin/garmin-server",
        ".shortcuts/Ranny beh",
        ".shortcuts/tasks/Otvorit appku",
        ".shortcuts/Aktualizovat",
        ".termux/boot/garminanalyzer",
    ):
        assert os.access(home / path, os.X_OK), path
    cron = crontab_file.read_text().splitlines()
    assert cron == [
        f"0 9-13 * * * {home}/.local/bin/garmin morning --once-per-day >> {repo}/data/logs/cron.out 2>&1 "
        "# garminanalyzer-morning"
    ]
    assert "crond" in log and "termux-wake-lock" in log
    assert "garmin login" in result.stdout  # no tokens yet
    run_setup(phone)  # idempotent: one cron line
    assert len(crontab_file.read_text().splitlines()) == 1


def test_the_garmin_wrapper_passes_arguments_and_the_phone_time_zone(phone):
    home, _, calls, _, env, _ = phone
    assert run_setup(phone).returncode == 0
    calls.write_text("")
    result = subprocess.run(
        [str(home / ".local/bin/garmin"), "morning", "--once-per-day", "a b"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    line = next(x for x in calls.read_text().splitlines() if x.startswith("uv ") and " morning " in x)
    assert "TZ=Europe/Prague" in line and line.split()[2] == f"PWD={home / 'GarminAnalyzer'}"
    assert line.endswith("ARGS:run --frozen --no-dev training morning --once-per-day a b")


def test_data_and_tokens_are_imported_once_and_never_overwritten(phone):
    home, repo, _, _, _, tmp = phone
    download = tmp / "Download" / "GarminAnalyzer"
    download.mkdir(parents=True)
    (download / "training.db").write_bytes(b"phone-db")
    (download / "garmin_tokens.json").write_text("{}")
    result = run_setup(phone)
    assert result.returncode == 0, result.stderr
    assert (repo / "data" / "training.db").read_bytes() == b"phone-db"
    tokens = home / ".garminconnect" / "garmin_tokens.json"
    assert tokens.exists() and oct(tokens.stat().st_mode)[-3:] == "600"
    assert not (download / "garmin_tokens.json").exists()  # removed from the shared folder
    (download / "training.db").write_bytes(b"newer-pc-db")
    run_setup(phone)
    assert (repo / "data" / "training.db").read_bytes() == b"phone-db"  # the phone's data wins


def test_refuses_outside_termux(phone):
    _, repo, _, _, env, _ = phone
    env = {k: v for k, v in env.items() if k != "GA_ALLOW_NON_TERMUX"}
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "android" / "setup.sh")], env=env, capture_output=True, text=True
    )
    assert result.returncode == 1 and "Termux" in result.stderr


def test_server_control_finds_the_server_by_its_command_line(phone):
    home, _, calls, _, env, _ = phone
    assert run_setup(phone).returncode == 0
    server = str(home / ".local/bin/garmin-server")
    stop = subprocess.run([server, "stop"], env=env, capture_output=True, text=True)
    assert "pkill -f training api --host 127.0.0.1 --port 8000" in calls.read_text() and stop.returncode == 0
    assert (
        subprocess.run([server, "status"], env=env, capture_output=True, text=True).stdout.strip()
        == "stopped"
    )
    assert subprocess.run([server, "bogus"], env=env, capture_output=True, text=True).returncode == 2
