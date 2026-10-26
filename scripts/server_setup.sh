#!/usr/bin/env bash
# One-time (and repeatable) setup of the always-on home server – docs/SERVER.md.
#
#   scripts/server_setup.sh            # .env, build + start (app + morning run), Tailscale HTTPS
#   scripts/server_setup.sh --no-tailscale
#
# Run it in the repository directory on the server (Raspberry Pi OS / Debian / Ubuntu) as your normal user.
# Idempotent: re-running keeps .env values you changed and only (re)starts the containers.
set -euo pipefail

cd "$(dirname "$0")/.."
tailscale_step=1
[[ "${1:-}" == "--no-tailscale" ]] && tailscale_step=0

say() { printf '\n== %s\n' "$*"; }
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- Docker ---------------------------------------------------------------------------------------------
say "Docker"
command -v docker >/dev/null || fail "Docker is missing. Install it: curl -fsSL https://get.docker.com | sh && sudo usermod -aG docker \$USER, then log out and in."
docker compose version >/dev/null 2>&1 || fail "The Docker Compose plugin is missing (docker compose). Reinstall Docker with get.docker.com."
docker info >/dev/null 2>&1 || fail "Cannot talk to Docker. Is your user in the 'docker' group? (sudo usermod -aG docker \$USER, then log out and in)"
echo "ok: $(docker --version)"

# --- .env (keeps existing values) -------------------------------------------------------------------------
say ".env"
touch .env
set_default() {  # set KEY=VALUE only if KEY is not in .env yet
  grep -q "^$1=" .env || { echo "$1=$2" >> .env; echo "added $1=$2"; }
}
set_default UID "$(id -u)"
set_default GID "$(id -g)"
set_default TZ "Europe/Bratislava"
set_default MORNING_AT "09:00"
chmod 600 .env
grep -E '^(UID|GID|TZ|MORNING_AT)=' .env

# --- data and Garmin tokens -------------------------------------------------------------------------------
say "Data and Garmin login"
mkdir -p data/logs
tokens_dir="${GARMIN_TOKENS_DIR:-$HOME/.garminconnect}"
mkdir -p "$tokens_dir"
if [[ -f data/training.db ]]; then
  echo "ok: data/training.db ($(du -h data/training.db | cut -f1))"
else
  echo "note: no data/training.db yet – copy it from your PC first (scripts/move_to_server.ps1),"
  echo "      or start empty and run: docker compose exec morning training backfill --months 24"
fi
if [[ -f "$tokens_dir/garmin_tokens.json" ]]; then
  echo "ok: Garmin tokens in $tokens_dir"
else
  echo "WARNING: no Garmin tokens in $tokens_dir – copy them from your PC (scripts/move_to_server.ps1)."
  echo "         Until then the morning sync fails (the app still shows the stored data)."
fi

# --- build and start --------------------------------------------------------------------------------------
say "Build and start (the first build on a Raspberry Pi takes a few minutes)"
docker compose up -d --build
port="$(grep -E '^APP_PORT=' .env | cut -d= -f2 || true)"
port="${port:-8000}"
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$port/api/health" >/dev/null 2>&1; then break; fi
  sleep 2
done
curl -fsS "http://127.0.0.1:$port/api/health" >/dev/null || fail "The app does not answer on 127.0.0.1:$port – see: docker compose logs app"
echo "ok: app on http://127.0.0.1:$port (this server only)"
docker compose ps

# --- Tailscale (HTTPS for your PC and phone) --------------------------------------------------------------
if [[ $tailscale_step == 1 ]]; then
  say "Tailscale"
  if ! command -v tailscale >/dev/null; then
    echo "Tailscale is not installed. Install it and sign in, then run this script again:"
    echo "  curl -fsSL https://tailscale.com/install.sh | sh && sudo tailscale up"
  elif ! tailscale status >/dev/null 2>&1; then
    echo "Tailscale is installed but not signed in: sudo tailscale up   (then run this script again)"
  else
    sudo tailscale serve --bg "$port"
    host="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
    echo "ok: the app is at https://${host:-<this-server>.<your-tailnet>.ts.net}/ on every device signed in to your Tailscale"
  fi
fi

say "Done"
echo "Morning run: daily at $(grep -E '^MORNING_AT=' .env | cut -d= -f2) ($(grep -E '^TZ=' .env | cut -d= -f2)); logs: docker compose logs -f morning"
echo "Update later: git pull && docker compose up -d --build"
