#!/usr/bin/env bash
# One-time (and repeatable) setup of the whole app on an Android phone – docs/ANDROID.md.
#
# Run it in Termux (from F-Droid) inside the cloned repository:
#   bash ~/GarminAnalyzer/scripts/android/setup.sh
#
# What it does:
#   1. Termux packages: proot-distro (a Debian userland, so the normal Linux wheels of numpy/pandas/scipy and
#      Garmin's curl_cffi work unchanged), cronie (the 09:00 run), termux-api (wake lock, opening the browser);
#   2. Debian with curl/git/tzdata and uv; `uv sync` of the app (the repo and the Garmin token folder stay in
#      Termux's home and are bound into Debian at /root/GarminAnalyzer and /root/.garminconnect – no path inside
#      the Debian rootfs is used, so proot-distro versions with different layouts work);
#   3. imports data/training.db and garmin_tokens.json from Download/GarminAnalyzer (exported on the PC with
#      scripts/export_for_phone.ps1) – never overwrites a database that is already on the phone;
#   4. the `garmin` command (`garmin morning`, `garmin sync`, …), the app server (`garmin-server start|stop`),
#      home-screen shortcuts for Termux:Widget, a Termux:Boot script, and the cron line
#      `0 9-13 * * * garmin morning --once-per-day` (a complete run makes the repeats no-ops).
# Idempotent: re-running updates the scripts and dependencies and keeps your data.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
TOKENS_DIR="$HOME/.garminconnect"  # bound into Debian at /root/.garminconnect
BIND=(--bind "$REPO:/root/GarminAnalyzer" --bind "$TOKENS_DIR:/root/.garminconnect")
BIN="$HOME/.local/bin"
TAG="# garminanalyzer-morning"
IMPORT_DIR="${GA_IMPORT_DIR:-$HOME/storage/downloads/GarminAnalyzer}"

say() { printf '\n== %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ "$PREFIX" == *com.termux* || -n "${GA_ALLOW_NON_TERMUX:-}" ]] || fail "Run this in Termux on the phone (docs/ANDROID.md)."
[[ "$REPO" == "$HOME/GarminAnalyzer" || -n "${GA_ALLOW_NON_TERMUX:-}" ]] ||
  fail "Clone the repository to ~/GarminAnalyzer (it is bound into Debian at /root/GarminAnalyzer)."

# --- 1. Termux packages -----------------------------------------------------------------------------------
say "1/5 Termux packages"
pkg install -y proot-distro cronie termux-api procps curl
[[ -d "$HOME/storage" ]] || termux-setup-storage || true  # access to Download (asks for permission once)

# --- 2. Debian + uv + the app -----------------------------------------------------------------------------
say "2/5 Debian, uv and the app (the first run downloads ~400 MB)"
mkdir -p "$TOKENS_DIR" && chmod 700 "$TOKENS_DIR"
proot-distro login debian -- true >/dev/null 2>&1 || proot-distro install debian
in_debian() {
  proot-distro login debian "${BIND[@]}" -- bash -lc "$1"
}
in_debian 'export DEBIAN_FRONTEND=noninteractive
apt-get update -q && apt-get install -y -q curl ca-certificates git tzdata
[ -x "$HOME/.local/bin/uv" ] || curl -LsSf https://astral.sh/uv/install.sh | sh
cd /root/GarminAnalyzer && UV_LINK_MODE=copy "$HOME/.local/bin/uv" sync --frozen --no-dev'

# --- 3. data and Garmin login -----------------------------------------------------------------------------
say "3/5 Data and Garmin login"
mkdir -p "$REPO/data/logs"
if [[ -f "$REPO/data/training.db" ]]; then
  echo "ok: data/training.db is already on the phone (kept)"
elif [[ -f "$IMPORT_DIR/training.db" ]]; then
  cp "$IMPORT_DIR/training.db" "$REPO/data/training.db"
  echo "imported: training.db from $IMPORT_DIR"
else
  echo "note: no database – copy it from the PC (scripts/export_for_phone.ps1) to Download/GarminAnalyzer"
  echo "      and run this script again, or start empty: garmin login && garmin backfill --months 24"
fi
tokens="$TOKENS_DIR/garmin_tokens.json"
if [[ -f "$tokens" ]]; then
  echo "ok: Garmin tokens"
elif [[ -f "$IMPORT_DIR/garmin_tokens.json" ]]; then
  cp "$IMPORT_DIR/garmin_tokens.json" "$tokens"
  chmod 600 "$tokens"
  rm -f "$IMPORT_DIR/garmin_tokens.json"  # a login token does not belong in the shared Download folder
  echo "imported: Garmin tokens (removed from Download)"
else
  echo "note: no Garmin tokens – run: garmin login"
fi

# --- 4. commands, shortcuts, boot -------------------------------------------------------------------------
say "4/5 Commands and home-screen shortcuts"
mkdir -p "$BIN" "$HOME/.shortcuts/tasks" "$HOME/.termux/boot"
cat > "$BIN/garmin" <<EOF
#!$PREFIX/bin/bash
# garmin <training command> – runs \`uv run training …\` inside Debian (docs/ANDROID.md)
zone="\$(getprop persist.sys.timezone 2>/dev/null)"
zone="\${zone:-Europe/Bratislava}"  # Debian does not see Android's time zone; the app needs local time
exec proot-distro login debian --bind "$REPO:/root/GarminAnalyzer" --bind "$TOKENS_DIR:/root/.garminconnect" -- \\
  bash -lc "export TZ='\$zone'; cd /root/GarminAnalyzer && exec \\\$HOME/.local/bin/uv run --frozen --no-dev training \\"\\\$@\\"" garmin "\$@"
EOF
cat > "$BIN/garmin-server" <<EOF
#!$PREFIX/bin/bash
# garmin-server start|stop|restart|status – the app on http://127.0.0.1:8000 (open it in Chrome).
# The server runs under proot, so it is found by its command line, not by a PID file.
PATTERN="training api --host 127.0.0.1 --port 8000"
running() { pgrep -f "\$PATTERN" >/dev/null; }
start() {
  running && { echo "already running"; return; }
  nohup "$BIN/garmin" api --host 127.0.0.1 --port 8000 >> "$REPO/data/logs/server.out" 2>&1 &
  echo "started – http://127.0.0.1:8000"
}
stop() { pkill -f "\$PATTERN" && echo "stopped" || echo "not running"; }
case "\${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop; sleep 2; start ;;
  status) running && echo "running" || echo "stopped" ;;
  *) echo "usage: garmin-server start|stop|restart|status"; exit 2 ;;
esac
EOF
cat > "$HOME/.shortcuts/Ranny beh" <<EOF
#!$PREFIX/bin/bash
# Termux:Widget: the whole morning run now (sync, plan, push to Garmin, Telegram)
"$BIN/garmin" morning
echo; read -r -p "Hotovo – Enter zavrie okno." _
EOF
cat > "$HOME/.shortcuts/tasks/Otvorit appku" <<EOF
#!$PREFIX/bin/bash
# Termux:Widget (no window): start the app if needed and open it in the browser
"$BIN/garmin-server" start >/dev/null
for _ in \$(seq 1 60); do curl -fs http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; sleep 1; done
termux-open-url http://127.0.0.1:8000
EOF
cat > "$HOME/.shortcuts/Aktualizovat" <<EOF
#!$PREFIX/bin/bash
# Termux:Widget: update the app (git pull), its dependencies and restart the server
cd "$REPO" && git pull --ff-only && "$BIN/garmin" --help >/dev/null && "$BIN/garmin-server" restart
echo; read -r -p "Hotovo – Enter zavrie okno." _
EOF
cat > "$HOME/.termux/boot/garminanalyzer" <<EOF
#!$PREFIX/bin/bash
# Termux:Boot: keep the phone able to run the 09:00 job, start cron and the app server
termux-wake-lock
pgrep -x crond >/dev/null || crond
"$BIN/garmin-server" start
EOF
chmod 700 "$BIN/garmin" "$BIN/garmin-server" "$HOME/.shortcuts/Ranny beh" "$HOME/.shortcuts/tasks/Otvorit appku" \
  "$HOME/.shortcuts/Aktualizovat" "$HOME/.termux/boot/garminanalyzer"
echo "ok: garmin, garmin-server, shortcuts (Ranny beh, Otvorit appku, Aktualizovat), boot script"

# --- 5. the daily run -------------------------------------------------------------------------------------
say "5/5 Daily run at 09:00 (repeats hourly until 13:00 if needed)"
line="0 9-13 * * * $BIN/garmin morning --once-per-day >> $REPO/data/logs/cron.out 2>&1 $TAG"
{ crontab -l 2>/dev/null | grep -v -F "$TAG" || true; echo "$line"; } | crontab -
pgrep -x crond >/dev/null || crond
termux-wake-lock || true
"$BIN/garmin-server" start

echo ""
echo "Done. Next (docs/ANDROID.md):"
echo "  - Termux:Boot and Termux:Widget from F-Droid; open Termux:Boot once; add the Termux widget to the home screen"
echo "  - Settings > Apps > Termux > Battery > Unrestricted (else Android may skip the 09:00 run)"
echo "  - Chrome: http://127.0.0.1:8000 > menu > Add to home screen"
[[ -f "$tokens" ]] || echo "  - garmin login   (one time, with your Garmin password and MFA code)"
