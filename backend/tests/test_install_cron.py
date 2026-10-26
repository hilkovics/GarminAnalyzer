"""scripts/install_cron.sh with a fake `crontab` on PATH: install, idempotent replace, custom time, remove."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "install_cron.sh"
pytestmark = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="needs bash")


@pytest.fixture
def env(tmp_path):
    table = tmp_path / "crontab.txt"
    table.write_text("0 1 * * * echo other-job\n", encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "crontab"  # `crontab -l` prints the table, `crontab -` replaces it
    fake.write_text(
        f'#!/usr/bin/env bash\nif [[ "$1" == "-l" ]]; then cat "{table}"; else cat > "{table}"; fi\n'
    )
    fake.chmod(0o755)
    uv = bin_dir / "uv"
    uv.write_text("#!/usr/bin/env bash\n")
    uv.chmod(0o755)
    return {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}, table


def run(env, *args):
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True, check=False)


def test_install_replace_and_remove(env):
    environ, table = env
    assert run(environ).returncode == 0
    lines = table.read_text().splitlines()
    assert lines[0] == "0 1 * * * echo other-job"
    assert len(lines) == 2 and lines[1].startswith("0 9 * * * cd ") and "training morning" in lines[1]
    assert run(environ, "05:45").returncode == 0  # replaced, not duplicated
    lines = table.read_text().splitlines()
    assert len(lines) == 2 and lines[1].startswith("45 5 * * * ")
    assert run(environ, "--remove").returncode == 0
    assert table.read_text().splitlines() == ["0 1 * * * echo other-job"]


def test_bad_time_is_rejected(env):
    environ, table = env
    result = run(environ, "25:00")
    assert result.returncode == 2 and "HH:MM" in result.stderr
    assert table.read_text().splitlines() == ["0 1 * * * echo other-job"]
