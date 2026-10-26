"""scripts/android/setup.sh with fake Termux tools on PATH (no phone, no network, no Debian).

The fake `proot-distro login … -- CMD ARGS…` behaves like proot-distro: every word after `--` is wrapped in
single quotes and the joined string runs in a login shell (`su -l root -c`), here `bash -c` with a fake Debian
home. For the generated `garmin` wrapper it runs for real (with a fake `uv`), so the quoting, the time zone
and the argument passing are exercised; the repository bind mount is emulated by rewriting
/root/GarminAnalyzer.
"""

import os
import shutil
import sqlite3
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
    fake(
        debian_home / ".local" / "bin",
        "uv",
        f'echo "uv TZ=$TZ LINK=$UV_LINK_MODE PWD=$PWD ARGS:$*" >> "{calls}"',
    )
    prefix = tmp_path / "usr"  # Termux's $PREFIX: the generated scripts put $PREFIX/bin first on PATH
    bin_dir = prefix / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "bash").symlink_to(shutil.which("bash"))
    crontab_file = tmp_path / "crontab.txt"
    for name in ("pkg", "termux-setup-storage", "termux-wake-lock", "crond", "termux-open-url", "git"):
        fake(bin_dir, name, f'echo "{name} $*" >> "{calls}"')
    fake(bin_dir, "pgrep", '[ -n "$FAKE_RUNNING" ] && [[ "$*" == *"$FAKE_RUNNING"* ]]')
    fake(bin_dir, "pkill", f'echo "pkill $*" >> "{calls}"')
    fake(bin_dir, "getprop", "echo Europe/Prague")
    fake(bin_dir, "curl", "exit 0")
    fake(  # sqlite3 DB SQL: the count query, or .backup 'target'
        bin_dir,
        "sqlite3",
        f"""exec "{sys.executable}" - "$@" <<'PY'
import sqlite3, sys
args = sys.argv[1:]
if args[0] == "-cmd":
    args = args[2:]
db, sql = args
con = sqlite3.connect(db)
if sql.startswith(".backup"):
    con.backup(sqlite3.connect(sql.split("'")[1]))
else:
    print(con.execute(sql).fetchone()[0])
PY""",
    )
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
  joined=""; for word in "$@"; do joined="$joined '$word'"; done
  case "$joined" in
    *" training "*) cd /; HOME="{debian_home}" exec bash -c "${{joined//"/root/GarminAnalyzer"/{repo}}}" ;;
  esac
  echo "  debian-cmd: $*" >> "{calls}"
fi""",
    )
    downloads = tmp_path / "Download"
    downloads.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "PREFIX": str(prefix),
        "GA_ALLOW_NON_TERMUX": "1",
        "GA_DOWNLOADS": str(downloads),
        "PATH": f"{bin_dir}{os.pathsep}/usr/bin{os.pathsep}/bin",
    }
    return home, repo, calls, crontab_file, env, downloads


def run_setup(phone):
    _, repo, _, _, env, _ = phone
    return subprocess.run(
        ["bash", str(repo / "scripts" / "android" / "setup.sh")], env=env, capture_output=True, text=True
    )


def make_db(path: Path, rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE raw_garmin (id INTEGER)")
    con.executemany("INSERT INTO raw_garmin VALUES (?)", [(i,) for i in range(rows)])
    con.commit()
    con.close()


def rows(path: Path) -> int:
    return sqlite3.connect(path).execute("SELECT count(*) FROM raw_garmin").fetchone()[0]


def test_setup_installs_syncs_writes_commands_and_the_cron_line(phone):
    home, repo, calls, crontab_file, _, downloads = phone
    make_db(downloads / "GarminAnalyzer" / "training.db", 3)
    result = run_setup(phone)
    assert result.returncode == 0, result.stderr
    log = calls.read_text()
    assert "pkg install -y proot-distro cronie termux-api procps curl sqlite" in log
    assert (
        "sync --frozen --no-dev --extra ai" in log
        and "apt-get install -y -q curl ca-certificates git tzdata" in log
    )
    assert (
        f"opt {repo}:/root/GarminAnalyzer" in log and f"opt {home}/.garminconnect:/root/.garminconnect" in log
    )
    for path in (
        ".local/bin/garmin",
        ".local/bin/garmin-server",
        ".local/bin/garmin-backup",
        ".shortcuts/Ranny beh",
        ".shortcuts/Otvorit appku",
        ".shortcuts/Aktualizovat",
        ".shortcuts/Zaloha",
        ".termux/boot/garminanalyzer",
    ):
        assert os.access(home / path, os.X_OK), path
    assert "setup.sh" in (home / ".shortcuts/Aktualizovat").read_text()  # updates also refresh the scripts
    assert (
        f'[ ! -f "{repo}/data/training.db" ]' in (home / ".shortcuts/Otvorit appku").read_text()
    )  # no empty DB
    cron = crontab_file.read_text().splitlines()
    assert cron == [
        f"0 9-13 * * * {home}/.local/bin/garmin morning --once-per-day >> {repo}/data/logs/cron.out 2>&1 "
        "# garminanalyzer-morning"
    ]
    assert "crond" in log and "termux-wake-lock" in log
    assert "garmin login" in result.stdout and "no .env" in result.stdout
    run_setup(phone)  # idempotent: one cron line
    assert len(crontab_file.read_text().splitlines()) == 1


def test_the_garmin_wrapper_passes_arguments_time_zone_and_link_mode(phone):
    home, repo, calls, _, env, downloads = phone
    make_db(downloads / "training.db", 1)
    assert run_setup(phone).returncode == 0
    calls.write_text("")
    fakes = env["PATH"].split(os.pathsep)[0]
    bare = {"HOME": env["HOME"], "PATH": f"{fakes}{os.pathsep}/usr/bin"}  # cron's bare environment
    result = subprocess.run(
        [str(home / ".local/bin/garmin"), "morning", "--once-per-day", "a b"],
        env=bare,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    line = next(x for x in calls.read_text().splitlines() if x.startswith("uv ") and " morning " in x)
    assert "TZ=Europe/Prague" in line and "LINK=copy" in line and f"PWD={repo}" in line
    assert line.endswith("ARGS:run --frozen --no-dev --extra ai training morning --once-per-day a b")


def test_imports_into_a_missing_or_empty_db_never_over_one_with_data(phone):
    home, repo, calls, _, _, downloads = phone
    db = repo / "data" / "training.db"
    make_db(db, 0)  # an empty database the app created before the import
    make_db(downloads / "Quick Share" / "training.db", 5)
    (downloads / "garmin_tokens.json").write_text("{}")
    (downloads / "Quick Share" / "garmin_tokens.json").write_text("{}")  # a second copy of the secret
    (downloads / "GarminAnalyzer").mkdir()
    (downloads / "GarminAnalyzer" / "env.txt").write_text("TRAINING_TELEGRAM_TOKEN=x\n")
    result = run_setup(phone)
    assert result.returncode == 0, result.stderr
    [bak] = db.parent.glob("training.db.bak-*")
    assert rows(db) == 5 and rows(bak) == 0
    assert (downloads / "Quick Share" / "training.db.imported").exists()  # not imported again later
    assert "pkill -f training api" in calls.read_text()  # the server was stopped for the swap, then restarted
    tokens = home / ".garminconnect" / "garmin_tokens.json"
    assert tokens.exists() and oct(tokens.stat().st_mode)[-3:] == "600"
    assert not list(downloads.rglob("garmin_tokens.json"))  # every copy of the secret left shared storage
    settings = repo / ".env"
    assert (
        settings.read_text() == "TRAINING_TELEGRAM_TOKEN=x\n" and oct(settings.stat().st_mode)[-3:] == "600"
    )
    assert not list(downloads.rglob("env.txt"))
    make_db(downloads / "GarminAnalyzer" / "training.db", 9)
    (downloads / "garmin_tokens.json").write_text('{"new": 1}')
    result = run_setup(phone)
    assert rows(db) == 5 and "has data (5 Garmin responses) – kept" in result.stdout  # the phone's data wins
    assert tokens.read_text() == '{"new": 1}' and not (downloads / "garmin_tokens.json").exists()


def test_import_fails_closed_and_can_be_forced(phone):
    _, repo, _, _, env, downloads = phone
    db = repo / "data" / "training.db"
    db.parent.mkdir(parents=True)
    db.write_bytes(b"not a database")  # unreadable: never treated as empty
    make_db(downloads / "training.db", 5)
    result = run_setup(phone)
    assert "could not read the phone's database" in result.stdout and db.read_bytes() == b"not a database"
    db.unlink()
    make_db(db, 2)
    forced = subprocess.run(
        ["bash", str(repo / "scripts" / "android" / "setup.sh")],
        env={**env, "GA_FORCE_IMPORT": "1"},
        capture_output=True,
        text=True,
    )
    assert forced.returncode == 0 and rows(db) == 5
    assert [rows(b) for b in db.parent.glob("training.db.bak-*")] == [2]


def test_no_import_while_a_morning_run_is_in_progress(phone):
    _, repo, _, _, env, downloads = phone
    db = repo / "data" / "training.db"
    make_db(db, 0)
    make_db(downloads / "training.db", 5)
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "android" / "setup.sh")],
        env={**env, "FAKE_RUNNING": "training morning"},
        capture_output=True,
        text=True,
    )
    assert "a morning run is in progress" in result.stdout and rows(db) == 0
    assert (downloads / "training.db").exists()  # still there for the next run


def test_without_a_database_no_server_and_no_cron(phone):
    _, repo, calls, crontab_file, _, _ = phone
    result = run_setup(phone)
    assert result.returncode == 0, result.stderr
    assert "skipped: no database yet" in result.stdout and not crontab_file.exists()
    assert not (repo / "data" / "training.db").exists() and "uv " not in calls.read_text()


def test_backup_and_server_control(phone):
    home, _, calls, _, env, downloads = phone
    make_db(downloads / "training.db", 4)
    assert run_setup(phone).returncode == 0
    out = subprocess.run([str(home / ".local/bin/garmin-backup")], env=env, capture_output=True, text=True)
    copy = next(downloads.glob("training-*.db"))
    assert out.returncode == 0 and rows(copy) == 4
    server = str(home / ".local/bin/garmin-server")
    assert subprocess.run([server, "stop"], env=env, capture_output=True, text=True).returncode == 0
    assert "pkill -f training api --host 127.0.0.1 --port 8000" in calls.read_text()
    assert (
        subprocess.run([server, "status"], env=env, capture_output=True, text=True).stdout.strip()
        == "stopped"
    )
    assert subprocess.run([server, "bogus"], env=env, capture_output=True, text=True).returncode == 2


def test_refuses_outside_termux(phone):
    _, repo, _, _, env, _ = phone
    env = {k: v for k, v in env.items() if k != "GA_ALLOW_NON_TERMUX"}
    result = subprocess.run(
        ["bash", str(repo / "scripts" / "android" / "setup.sh")], env=env, capture_output=True, text=True
    )
    assert result.returncode == 1 and "Termux" in result.stderr
