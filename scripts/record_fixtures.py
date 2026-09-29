"""Record anonymized Garmin Connect JSON fixtures into backend/tests/fixtures/.

Run locally after `uv run training login`:

    uv run python scripts/record_fixtures.py            # last 6 activities + last 14 days of wellness

Downloads the most recent activities (summary, details, splits/laps, HR time in zones) – topping up with an
outdoor run with elevation gain and a bike ride if the latest ones contain none – plus daily sleep, RHR,
stress and user summary, a body-battery range, training status, max metrics (VO2max) and Garmin's
lactate threshold. Every payload goes through `training.garmin.anonymize` (random GPS offset that is never
saved, ids remapped, PII removed) and then `find_leaks` (real name / profile id / start coordinates) before
it touches the disk; a detected leak aborts the recording. Calls are rate-limited via GarminClient.
"""

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from typing import Any

import typer

from training.config import get_settings
from training.garmin.anonymize import IdMap, anonymize, find_leaks, random_offset
from training.garmin.client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
)

log = logging.getLogger("record_fixtures")

FIXTURE_PREFIXES = ("activity_", "activities_", "wellness_", "range_", "manifest")
INDOOR_MARKERS = ("treadmill", "indoor", "virtual")
BIKE_MARKERS = ("cycling", "biking", "ride")


def type_key(activity: dict[str, Any]) -> str:
    return str((activity.get("activityType") or {}).get("typeKey") or "other")


def sport_of(activity: dict[str, Any]) -> str:
    """Coarse sport ('run' | 'bike' | 'other') from `activityType.typeKey`."""
    key = type_key(activity)
    if "running" in key:
        return "run"
    if any(m in key for m in BIKE_MARKERS):
        return "bike"
    return "other"


def is_hilly_outdoor_run(activity: dict[str, Any], min_gain_m: float) -> bool:
    key = type_key(activity)
    gain = activity.get("elevationGain") or 0.0
    return sport_of(activity) == "run" and not any(m in key for m in INDOOR_MARKERS) and gain >= min_gain_m


def select_activities(items: list[dict[str, Any]], n: int, min_gain_m: float = 20.0) -> list[dict[str, Any]]:
    """Latest `n` activities, topped up with one hilly outdoor run and one bike ride if missing."""
    chosen = list(items[:n])
    rest = items[n:]
    wanted: list[Callable[[dict[str, Any]], bool]] = [
        lambda a: is_hilly_outdoor_run(a, min_gain_m),
        lambda a: sport_of(a) == "bike",
    ]
    for pred in wanted:
        if not any(pred(a) for a in chosen):
            extra = next((a for a in rest if pred(a)), None)
            if extra is not None:
                chosen.append(extra)
    return chosen


class LeakError(RuntimeError):
    """An anonymized payload still contains a known real value; nothing was written for it."""


class Recorder:
    """Fetches, anonymizes, leak-checks and writes fixtures; per-call failures are recorded, not fatal."""

    def __init__(
        self,
        client: GarminClient,
        out_dir: Path,
        offset: tuple[float, float],
        *,
        sensitive: list[str] | None = None,
        real_points: list[tuple[float, float]] | None = None,
    ) -> None:
        self.client = client
        self.out_dir = out_dir
        self.offset = offset
        self.ids = IdMap()
        self.sensitive = sensitive or []
        self.real_points = real_points or []
        self.files: list[str] = []
        self.errors: list[dict[str, str]] = []

    def fetch(self, filename: str, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            payload = self.client.call(method, *args, **kwargs)
        except GarminConnectAuthenticationError:
            raise
        except (GarminConnectConnectionError, ValueError) as exc:
            log.warning("%s failed: %s", method, type(exc).__name__)
            self.errors.append({"file": filename, "method": method, "error": type(exc).__name__})
            return None
        self.write(filename, payload)
        return payload

    def write(self, filename: str, payload: Any) -> None:
        clean = anonymize(payload, self.offset, self.ids)
        leaks = find_leaks(clean, strings=self.sensitive, points=self.real_points)
        if leaks:
            raise LeakError(f"{filename}: {', '.join(leaks)} after anonymization – not written")
        (self.out_dir / filename).write_text(json.dumps(clean, indent=1, ensure_ascii=False) + "\n")
        self.files.append(filename)


def _sensitive_values(client: Any) -> list[str]:
    """Real identifiers of the logged-in user, used only in memory for the leak scan."""
    api = getattr(client, "api", None)
    values = [getattr(api, attr, None) for attr in ("full_name", "display_name", "profile_id")]
    return [str(v) for v in values if v]


def _start_points(activities: list[dict[str, Any]]) -> list[tuple[float, float]]:
    return [
        (float(a["startLatitude"]), float(a["startLongitude"]))
        for a in activities
        if isinstance(a.get("startLatitude"), int | float)
        and isinstance(a.get("startLongitude"), int | float)
    ]


def record(
    client: GarminClient,
    out_dir: Path,
    *,
    today: date,
    n_activities: int = 6,
    search: int = 60,
    days: int = 14,
    maxchart: int = 20000,
    offset: tuple[float, float] | None = None,
    clean: bool = True,
) -> dict[str, Any]:
    """Record all fixtures. Returns the manifest (also written as manifest.json)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    if clean:
        for old in out_dir.glob("*.json"):
            if old.name.startswith(FIXTURE_PREFIXES):
                old.unlink()
    items = client.call("get_activities", 0, search) or []
    selected = select_activities(items, n_activities)
    rec = Recorder(
        client,
        out_dir,
        offset or random_offset(),
        sensitive=_sensitive_values(client),
        real_points=_start_points(items),
    )
    rec.write("activities_list.json", selected)
    for i, act in enumerate(selected, start=1):
        aid = act["activityId"]
        stem = f"activity_{i:02d}_{type_key(act)}"
        rec.fetch(f"{stem}_summary.json", "get_activity", aid)
        rec.fetch(f"{stem}_details.json", "get_activity_details", aid, maxchart=maxchart)
        rec.fetch(f"{stem}_splits.json", "get_activity_splits", aid)
        rec.fetch(f"{stem}_hr_zones.json", "get_activity_hr_in_timezones", aid)

    start = today - timedelta(days=days - 1)
    for k in range(days):
        d = (start + timedelta(days=k)).isoformat()
        rec.fetch(f"wellness_{d}_sleep.json", "get_sleep_data", d)
        rec.fetch(f"wellness_{d}_rhr.json", "get_rhr_day", d)
        rec.fetch(f"wellness_{d}_stress.json", "get_stress_data", d)
        rec.fetch(f"wellness_{d}_user_summary.json", "get_user_summary", d)
    s, e = start.isoformat(), today.isoformat()
    rec.fetch(f"range_{s}_{e}_body_battery.json", "get_body_battery", s, e)
    rec.fetch(f"range_{s}_{e}_max_metrics.json", "get_max_metrics_range", s, e)
    rec.fetch(f"wellness_{e}_training_status.json", "get_training_status", e)
    rec.fetch("wellness_latest_lactate_threshold.json", "get_lactate_threshold", latest=True)

    sports = [sport_of(a) for a in selected]
    manifest = {
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "garminconnect_version": _pkg_version("garminconnect"),
        "activities": [
            {"n": i, "type_key": type_key(a), "sport": sp, "elevation_gain_m": a.get("elevationGain")}
            for i, (a, sp) in enumerate(zip(selected, sports, strict=True), start=1)
        ],
        "has_hilly_run": any(is_hilly_outdoor_run(a, 20.0) for a in selected),
        "has_bike": "bike" in sports,
        "files": sorted(rec.files),
        "errors": rec.errors,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except Exception:
        return "unknown"


def main(
    activities: int = typer.Option(6, help="Number of most recent activities."),
    search: int = typer.Option(
        60, help="How many recent activities to search for a hilly run / bike top-up."
    ),
    days: int = typer.Option(14, help="Days of wellness data (ending today)."),
    maxchart: int = typer.Option(20000, help="maxChartSize for activity details (≈ samples kept)."),
    out: Path | None = typer.Option(None, help="Output directory (default: backend/tests/fixtures)."),
    clean: bool = typer.Option(True, help="Delete previously recorded fixture files first."),
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    for name in ("garminconnect", "urllib3", "curl_cffi"):
        logging.getLogger(name).setLevel(logging.WARNING)
    settings = get_settings()
    try:
        client = GarminClient.from_settings(settings)
    except GarminConnectAuthenticationError as exc:
        typer.echo(f"Not logged in: {exc}", err=True)
        raise typer.Exit(1) from None
    out_dir = out or settings.fixtures_dir
    try:
        manifest = record(
            client, out_dir, today=date.today(), n_activities=activities, search=search, days=days,
            maxchart=maxchart, clean=clean,
        )  # fmt: skip
    except LeakError as exc:
        typer.echo(f"ABORTED – possible privacy leak: {exc}", err=True)
        typer.echo(
            "Files written so far passed the check. Do not commit until the anonymizer is fixed.", err=True
        )
        raise typer.Exit(2) from None
    typer.echo(f"Wrote {len(manifest['files'])} files to {out_dir}")
    typer.echo(f"Activities: {', '.join(a['type_key'] for a in manifest['activities'])}")
    if not manifest["has_hilly_run"]:
        typer.echo(
            "WARNING: no outdoor run with ≥ 20 m elevation gain found – use --search to look further back."
        )
    if not manifest["has_bike"]:
        typer.echo("WARNING: no bike ride found – use --search to look further back.")
    if manifest["errors"]:
        typer.echo(f"{len(manifest['errors'])} calls failed – see manifest.json")


app = typer.Typer(pretty_exceptions_show_locals=False, add_completion=False)
app.command()(main)

if __name__ == "__main__":
    app()
