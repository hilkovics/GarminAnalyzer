#!/usr/bin/env bash
# One-time (and repeatable) setup of the whole app on an Android phone – docs/ANDROID.md.
#
# Run it in Termux (from F-Droid) inside the cloned repository:
#   bash ~/GarminAnalyzer/scripts/android/setup.sh
#
# What it does:
#   1. Termux packages: proot-distro (a Debian userland, so the normal Linux wheels of numpy/pandas/scipy and
#      Garmin's curl_cffi work unchanged), cronie (the 09:00 run), termux-api (wake lock, opening the browser),
#      sqlite (safe backups and the import check);
#   2. Debian with curl/git/tzdata and uv; `uv sync` of the app with the AI extra (the repo and the Garmin token
#      folder stay in Termux's home and are bound into Debian at /root/GarminAnalyzer and /root/.garminconnect –
#      no path inside the Debian rootfs is used, so proot-distro versions with different layouts work);
#   3. imports training.db, garmin_tokens.json and .env exported on the PC (scripts/export_for_phone.ps1) from
#      Download/GarminAnalyzer, Download or Download/Quick Share. A database is imported while the phone has none
#      or only an empty one (no Garmin data yet; the old file is kept as .bak) – a phone database with data is
#      never overwritten. The token file and .env (secrets) are moved out of Download;
#   4. the `garmin` command (`garmin morning`, `garmin sync`, …), `garmin-server start|stop`, `garmin-backup`,
#      home-screen shortcuts for Termux:Widget, a Termux:Boot script;
#   5. the cron line `0 9-13 * * * garmin morning --once-per-day` (a complete run makes the repeats no-ops) and
#      the app server – only once a database is on the phone (else it would create an empty one).
# Idempotent: re-running updates the scripts and dependencies and keeps your data ("Aktualizovat" re-runs it).
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
PREFIX="${PREFIX:-/data/data/com.termux/files/usr}"
TOKENS_DIR="$HOME/.garminconnect"  # bound into Debian at /root/.garminconnect
BIND=(--bind "$REPO:/root/GarminAnalyzer" --bind "$TOKENS_DIR:/root/.garminconnect")
BIN="$HOME/.local/bin"
TAG="# garminanalyzer-morning"
DOWNLOADS="${GA_DOWNLOADS:-$HOME/storage/downloads}"
IMPORT_DIRS=("$DOWNLOADS/GarminAnalyzer" "$DOWNLOADS" "$DOWNLOADS/Quick Share")
DB="$REPO/data/training.db"

say() { printf '\n== %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
find_import() {  # the first Download location that has file $1
  local dir
  for dir in "${IMPORT_DIRS[@]}"; do
    [[ -f "$dir/$1" ]] && { printf '%s\n' "$dir/$1"; return 0; }
  done
  return 1
}
db_rows() {  # stored Garmin responses in database $1, or "error" (fails closed: an unreadable DB is never "empty")
  local out
  if out="$(sqlite3 -cmd '.timeout 5000' "$1" 'SELECT count(*) FROM raw_garmin' 2>/dev/null)" && [[ "$out" =~ ^[0-9]+$ ]]; then
    printf '%s\n' "$out"
  else
    echo error
  fi
}
remove_everywhere() {  # a secret: delete every copy from the shared Download locations
  local dir
  for dir in "${IMPORT_DIRS[@]}"; do rm -f "$dir/$1"; done
}

[[ "$PREFIX" == *com.termux* || -n "${GA_ALLOW_NON_TERMUX:-}" ]] || fail "Run this in Termux on the phone (docs/ANDROID.md)."
[[ "$REPO" == "$HOME/GarminAnalyzer" || -n "${GA_ALLOW_NON_TERMUX:-}" ]] ||
  fail "Clone the repository to ~/GarminAnalyzer (it is bound into Debian at /root/GarminAnalyzer)."

# --- 1. Termux packages -----------------------------------------------------------------------------------
say "1/5 Termux packages"
pkg install -y proot-distro cronie termux-api procps curl sqlite
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
cd /root/GarminAnalyzer && UV_LINK_MODE=copy "$HOME/.local/bin/uv" sync --frozen --no-dev --extra ai'

# --- 3. data, Garmin login, settings ----------------------------------------------------------------------
say "3/5 Data, Garmin login and settings"
mkdir -p "$REPO/data/logs"
imported=0
replace_db() {  # $1 = the PC export; the phone's current DB (empty, or forced) is kept as a timestamped .bak
  if pgrep -f "training morning" >/dev/null; then
    echo "skipped the import: a morning run is in progress – run this script again in a few minutes"
    return
  fi
  [[ -x "$BIN/garmin-server" ]] && "$BIN/garmin-server" stop >/dev/null  # nothing may hold the old file open
  if [[ -f "$DB" ]]; then
    local bak="$DB.bak-$(date +%Y%m%d-%H%M%S)"
    mv "$DB" "$bak"
    for side in -wal -shm; do [[ -f "$DB$side" ]] && mv "$DB$side" "$bak$side"; done
    echo "kept the previous database as $(basename "$bak")"
  fi
  cp "$1" "$DB"
  mv "$1" "$1.imported"  # never evaluated again by later runs (Aktualizovat)
  imported=1
  echo "imported: training.db from $1 (renamed there to training.db.imported)"
}
if src="$(find_import training.db)"; then
  if [[ ! -f "$DB" ]]; then
    replace_db "$src"
  else
    count="$(db_rows "$DB")"
    if [[ "$count" == error ]]; then
      echo "skipped the import: could not read the phone's database (busy or damaged) – nothing was changed"
    elif [[ "$count" == 0 || -n "${GA_FORCE_IMPORT:-}" ]]; then
      replace_db "$src"
    else
      echo "ok: the phone's database has data ($count Garmin responses) – kept, ignored $src"
      echo "    (to replace it with the PC export anyway: GA_FORCE_IMPORT=1 bash scripts/android/setup.sh)"
    fi
  fi
elif [[ -f "$DB" ]]; then
  echo "ok: data/training.db is on the phone"
else
  echo "note: no database – copy training.db from the PC (scripts/export_for_phone.ps1) to Download/GarminAnalyzer"
  echo "      and run this script again, or start empty: garmin login && garmin backfill --months 24"
fi
tokens="$TOKENS_DIR/garmin_tokens.json"
if src="$(find_import garmin_tokens.json)"; then
  cp "$src" "$tokens" && chmod 600 "$tokens" && remove_everywhere garmin_tokens.json  # not in shared storage
  echo "imported: Garmin login (moved out of Download)"
elif [[ -f "$tokens" ]]; then
  echo "ok: Garmin login"
else
  echo "note: no Garmin login – run: garmin login"
fi
if src="$(find_import env.txt)" || src="$(find_import .env)"; then
  cp "$src" "$REPO/.env" && chmod 600 "$REPO/.env" && remove_everywhere env.txt && remove_everywhere .env
  echo "imported: settings (.env with the Telegram and AI keys, moved out of Download)"
elif [[ -f "$REPO/.env" ]]; then
  echo "ok: settings (.env)"
else
  echo "note: no .env – Telegram messages stay off until you add TRAINING_TELEGRAM_TOKEN and"
  echo "      TRAINING_TELEGRAM_CHAT_ID to ~/GarminAnalyzer/.env (docs/ANDROID.md)"
fi

# --- 4. commands, shortcuts, boot -------------------------------------------------------------------------
say "4/5 Commands and home-screen shortcuts"
mkdir -p "$BIN" "$HOME/.shortcuts" "$HOME/.termux/boot"
rm -f "$HOME/.shortcuts/tasks/Otvorit appku"  # older versions ran it in the background (Android blocks the browser)
cat > "$BIN/garmin" <<EOF
#!$PREFIX/bin/bash
# garmin <training command> – runs \`uv run training …\` inside Debian (docs/ANDROID.md).
# cron and Termux:Boot start with a bare environment: pin PATH; Debian does not see Android's time zone.
export PATH="$PREFIX/bin:/system/bin:\$PATH"
zone="\$(getprop persist.sys.timezone 2>/dev/null)"
exec proot-distro login debian --bind "$REPO:/root/GarminAnalyzer" --bind "$TOKENS_DIR:/root/.garminconnect" -- \\
  env "TZ=\${zone:-Europe/Bratislava}" UV_LINK_MODE=copy \\
  bash -c 'cd /root/GarminAnalyzer && exec "\$HOME/.local/bin/uv" run --frozen --no-dev --extra ai training "\$@"' \\
  garmin "\$@"
EOF
cat > "$BIN/garmin-server" <<EOF
#!$PREFIX/bin/bash
# garmin-server start|stop|restart|status – the app on http://127.0.0.1:8000 (open it in Chrome).
# The server runs under proot, so it is found by its command line, not by a PID file.
export PATH="$PREFIX/bin:/system/bin:\$PATH"
PATTERN="training api --host 127.0.0.1 --port 8000"
running() { pgrep -f "\$PATTERN" >/dev/null; }
start() {
  running && { echo "already running"; return; }
  nohup "$BIN/garmin" api --host 127.0.0.1 --port 8000 >> "$REPO/data/logs/server.out" 2>&1 &
  echo "started – http://127.0.0.1:8000"
}
stop() {
  pkill -f "\$PATTERN" || { echo "not running"; return 0; }
  for _ in \$(seq 1 20); do running || break; sleep 0.5; done
  echo "stopped"
}
case "\${1:-start}" in
  start) start ;;
  stop) stop ;;
  restart) stop; start ;;
  status) running && echo "running" || echo "stopped" ;;
  *) echo "usage: garmin-server start|stop|restart|status"; exit 2 ;;
esac
EOF
cat > "$BIN/garmin-backup" <<EOF
#!$PREFIX/bin/bash
# garmin-backup – a consistent copy of the database into Download (SQLite backup API: safe while the app runs)
export PATH="$PREFIX/bin:/system/bin:\$PATH"
target="$DOWNLOADS/training-\$(date +%F).db"
sqlite3 "$DB" ".backup '\$target'" && echo "backup: \$target"
EOF
cat > "$HOME/.shortcuts/Ranny beh" <<EOF
#!$PREFIX/bin/bash
# Termux:Widget: the whole morning run now (sync, plan, push to Garmin, Telegram)
"$BIN/garmin" morning
echo; read -r -p "Hotovo – Enter zavrie okno." _
EOF
cat > "$HOME/.shortcuts/Otvorit appku" <<EOF
#!$PREFIX/bin/bash
# Termux:Widget: start the app if needed and open it (in the foreground: Android lets it start the browser)
if [ ! -f "$DB" ]; then  # the server would create an empty database before the PC data is imported
  echo "Najprv dokonci instalaciu: databaza este nie je v mobile (docs/ANDROID.md, krok 3-4)."
  read -r -p "Enter zavrie okno." _; exit 1
fi
"$BIN/garmin-server" start >/dev/null
for _ in \$(seq 1 90); do curl -fs http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break; sleep 1; done
termux-open-url http://127.0.0.1:8000
EOF
cat > "$HOME/.shortcuts/Aktualizovat" <<EOF
#!$PREFIX/bin/bash
# Termux:Widget: update the app (git pull), re-run this setup (dependencies, scripts, cron), restart the app
cd "$REPO" && git pull --ff-only && bash "$REPO/scripts/android/setup.sh" && "$BIN/garmin-server" restart
echo; read -r -p "Hotovo – Enter zavrie okno." _
EOF
cat > "$HOME/.shortcuts/Zaloha" <<EOF
#!$PREFIX/bin/bash
# Termux:Widget: back up the database into Download
"$BIN/garmin-backup"
echo; read -r -p "Hotovo – Enter zavrie okno." _
EOF
cat > "$HOME/.termux/boot/garminanalyzer" <<EOF
#!$PREFIX/bin/bash
# Termux:Boot: keep the phone able to run the 09:00 job, start cron and the app server
export PATH="$PREFIX/bin:/system/bin:\$PATH"
termux-wake-lock
pgrep -x crond >/dev/null || crond
[ -f "$DB" ] && "$BIN/garmin-server" start
EOF
chmod 700 "$BIN/garmin" "$BIN/garmin-server" "$BIN/garmin-backup" "$HOME/.shortcuts/Ranny beh" \
  "$HOME/.shortcuts/Otvorit appku" "$HOME/.shortcuts/Aktualizovat" "$HOME/.shortcuts/Zaloha" \
  "$HOME/.termux/boot/garminanalyzer"
echo "ok: garmin, garmin-server, garmin-backup, shortcuts (Ranny beh, Otvorit appku, Aktualizovat, Zaloha), boot"

# --- 5. the daily run and the server ----------------------------------------------------------------------
say "5/5 Daily run at 09:00 (repeats hourly until 13:00 if needed)"
if [[ ! -f "$DB" ]]; then
  echo "skipped: no database yet – run this script again after copying training.db (or after garmin backfill)"
  exit 0
fi
line="0 9-13 * * * $BIN/garmin morning --once-per-day >> $REPO/data/logs/cron.out 2>&1 $TAG"
{ crontab -l 2>/dev/null | grep -v -F "$TAG" || true; echo "$line"; } | crontab -
pgrep -x crond >/dev/null || crond
termux-wake-lock || true
if [[ "$imported" == 1 ]]; then "$BIN/garmin-server" restart; else "$BIN/garmin-server" start; fi

echo ""
echo "Done. Next (docs/ANDROID.md):"
echo "  - Termux:Boot and Termux:Widget from F-Droid; open Termux:Boot once; add the Termux widget to the home screen"
echo "  - Settings > Apps > Termux > Battery > Unrestricted (else Android may skip the 09:00 run)"
echo "  - Chrome: http://127.0.0.1:8000 > menu > Add to home screen"
[[ -f "$tokens" ]] || echo "  - garmin login   (one time, with your Garmin password and MFA code)"
