#!/usr/bin/env bash
# Install (or remove) the daily `training morning` run in the user's crontab – Linux / macOS (PLAN phase 8).
#
#   scripts/install_cron.sh            # daily at 09:00
#   scripts/install_cron.sh 05:45      # another time (HH:MM, local)
#   scripts/install_cron.sh --remove
#
# Idempotent: the line is tagged and replaced, never duplicated. Output goes to data/logs/cron.out; the
# structured log is data/logs/training.log. Run `uv run training login` once before (tokens in ~/.garminconnect).
set -euo pipefail

TAG="# training-morning (GarminAnalyzer)"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

current="$(crontab -l 2>/dev/null | grep -v -F "$TAG" || true)"

if [[ "${1:-}" == "--remove" ]]; then
  printf '%s\n' "$current" | sed '/^$/d' | crontab -
  echo "Removed the training-morning cron entry."
  exit 0
fi

at="${1:-09:00}"
if [[ ! "$at" =~ ^([01]?[0-9]|2[0-3]):([0-5][0-9])$ ]]; then
  echo "Time must be HH:MM, got '$at'." >&2
  exit 2
fi
hour=$((10#${BASH_REMATCH[1]}))
minute=$((10#${BASH_REMATCH[2]}))

UV="$(command -v uv || true)"
if [[ -z "$UV" ]]; then
  echo "uv not found on PATH – install it first (https://docs.astral.sh/uv/)." >&2
  exit 1
fi

mkdir -p "$REPO/data/logs"
# cron treats an unescaped % as a newline: escape it in the paths
REPO_CRON="${REPO//%/\\%}"
UV_CRON="${UV//%/\\%}"
line="$minute $hour * * * cd \"$REPO_CRON\" && \"$UV_CRON\" run training morning >> \"$REPO_CRON/data/logs/cron.out\" 2>&1 $TAG"
{ printf '%s\n' "$current" | sed '/^$/d'; echo "$line"; } | crontab -
echo "Installed: training morning daily at $(printf '%02d:%02d' "$hour" "$minute") (local time)."
echo "Check with: crontab -l"
