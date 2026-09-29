"""Activity summary JSON → `activity` row dicts (PLAN §4, phase 1).

Two Garmin shapes are accepted and may be combined:

- `summary`: `Garmin.get_activity(id)` – nested (`activityTypeDTO`, `eventTypeDTO`, `timeZoneUnitDTO`,
  `summaryDTO{startTimeLocal "YYYY-MM-DDTHH:MM:SS.f", startTimeGMT, distance, ...}`).
- `list_item`: one element of `Garmin.get_activities(start, limit)` – flat keys (`activityType`,
  `eventType`, `startTimeLocal "YYYY-MM-DD HH:MM:SS"`, `averageRunningCadenceInStepsPerMinute`, ...).

Per field the summary value wins; the list item is the fallback. Units are kept as Garmin sends them,
which already match the internal convention (s, m, m/s, bpm). `start_utc` is a timezone-aware UTC
`datetime`; `local_date` is the local calendar date of the start (METRICS §4 groups load by it).
Pure functions, no I/O.
"""

import logging
import math
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

SPORTS = ("run", "bike", "other")

ACTIVITY_FIELDS = (
    "garmin_id",
    "sport",
    "sub_sport",
    "name",
    "start_utc",
    "tz",
    "local_date",
    "duration_s",
    "moving_s",
    "distance_m",
    "elev_gain_m",
    "avg_hr",
    "max_hr",
    "avg_speed",
    "avg_cadence",
    "calories",
    "is_race",
    "is_indoor",
    "garmin_training_load",
    "garmin_aerobic_te",
    "garmin_anaerobic_te",
    "garmin_vo2max",
)

RUN_TYPE_KEYS = frozenset(
    {
        "running",
        "trail_running",
        "treadmill_running",
        "track_running",
        "street_running",
        "indoor_running",
        "virtual_run",
        "ultra_run",
    }
)
BIKE_TYPE_KEYS = frozenset(
    {
        "cycling",
        "road_biking",
        "indoor_cycling",
        "virtual_ride",
        "gravel_cycling",
        "mountain_biking",
        "cyclocross",
        "track_cycling",
        "recumbent_cycling",
        "bmx",
        "downhill_biking",
        "enduro_mtb",
        "e_bike_fitness",
        "e_bike_mountain",
        "e_enduro_mtb",
        "hand_cycling",
        "indoor_hand_cycling",
    }
)
_BIKE_MARKERS = ("cycling", "biking", "_ride", "bike", "mtb")
_INDOOR_MARKERS = ("treadmill", "indoor", "virtual")
_MAX_TZ_OFFSET_MIN = 14 * 60


def sport_from_type_key(type_key: str | None) -> str:
    """Coarse sport for Garmin's `activityType.typeKey`: 'run' | 'bike' | 'other' (CLAUDE.md rule 10).

    Known keys are matched exactly; unknown keys fall back to substrings ("running"/"_run" → run,
    "cycling"/"biking"/"_ride"/"bike"/"mtb" → bike). Motorised types (`motorcycling`, ...) are 'other'.
    """
    if not type_key:
        return "other"
    key = type_key.strip().lower()
    if key in RUN_TYPE_KEYS:
        return "run"
    if key in BIKE_TYPE_KEYS:
        return "bike"
    if key.startswith("motor"):
        return "other"
    if "running" in key or key.endswith("_run"):
        return "run"
    if any(marker in key for marker in _BIKE_MARKERS):
        return "bike"
    return "other"


def is_indoor_type(type_key: str | None) -> bool:
    """True for treadmill / indoor / virtual types (no usable GPS, METRICS §2.3)."""
    if not type_key:
        return False
    key = type_key.lower()
    return any(marker in key for marker in _INDOOR_MARKERS)


def normalize_activity(summary: dict | None, list_item: dict | None = None) -> dict:
    """Map a Garmin activity summary and/or list item to an `activity` row dict.

    Returns exactly the keys in `ACTIVITY_FIELDS` (None when unknown). `start_utc` is an aware UTC
    datetime; `tz` is the IANA name from `timeZoneUnitDTO` when available, else the "+HH:MM" offset of
    local start − GMT start. Raises ValueError if neither source yields an activity id or a start time.
    """
    s = _as_dict(summary)
    li = _as_dict(list_item)
    if not s and not li:
        raise ValueError("normalize_activity needs a summary or a list item")
    dto = _as_dict(s.get("summaryDTO"))

    garmin_id = _as_int(_first(s.get("activityId"), li.get("activityId")))
    if garmin_id is None:
        raise ValueError("activity has no activityId")

    type_key = _as_str(
        _first(
            _get(s, "activityTypeDTO", "typeKey"),
            _get(s, "activityType", "typeKey"),
            _get(li, "activityType", "typeKey"),
        )
    )
    event_key = _as_str(
        _first(
            _get(s, "eventTypeDTO", "typeKey"),
            _get(s, "eventType", "typeKey"),
            _get(li, "eventType", "typeKey"),
        )
    )
    sport = sport_from_type_key(type_key)

    start_utc, start_local, offset = _start_times(dto, li, garmin_id)
    tz = _as_str(_first(_get(s, "timeZoneUnitDTO", "timeZone"), _get(s, "timeZoneUnitDTO", "unitKey")))
    if tz is None and offset is not None:
        tz = _format_offset(offset)
    if start_local is not None:
        local_date = start_local.date()
    else:
        local_date = start_utc.date()
        log.warning("activity %s: no local start time, using the UTC date as local_date", garmin_id)

    def num(dto_keys: tuple[str, ...], li_keys: tuple[str, ...]) -> float | None:
        candidates = [dto.get(k) for k in dto_keys] + [li.get(k) for k in li_keys]
        return _first(*(_as_float(v) for v in candidates))

    run_cad = (("averageRunCadence",), ("averageRunningCadenceInStepsPerMinute",))
    bike_cad = (("averageBikeCadence",), ("averageBikingCadenceInRevPerMinute",))
    first_cad, second_cad = (bike_cad, run_cad) if sport == "bike" else (run_cad, bike_cad)
    avg_cadence = num(*first_cad)
    if avg_cadence is None:
        avg_cadence = num(*second_cad)

    return {
        "garmin_id": garmin_id,
        "sport": sport,
        "sub_sport": type_key,
        "name": _as_str(_first(s.get("activityName"), li.get("activityName"))),
        "start_utc": start_utc,
        "tz": tz,
        "local_date": local_date,
        "duration_s": num(("duration",), ("duration",)),
        "moving_s": num(("movingDuration",), ("movingDuration",)),
        "distance_m": num(("distance",), ("distance",)),
        "elev_gain_m": num(("elevationGain",), ("elevationGain",)),
        "avg_hr": num(("averageHR",), ("averageHR",)),
        "max_hr": num(("maxHR",), ("maxHR",)),
        "avg_speed": num(("averageSpeed",), ("averageSpeed",)),
        "avg_cadence": avg_cadence,
        "calories": num(("calories",), ("calories",)),
        "is_race": (event_key or "").lower() == "race",
        "is_indoor": is_indoor_type(type_key),
        "garmin_training_load": num(("activityTrainingLoad",), ("activityTrainingLoad",)),
        "garmin_aerobic_te": num(("trainingEffect", "aerobicTrainingEffect"), ("aerobicTrainingEffect",)),
        "garmin_anaerobic_te": num(("anaerobicTrainingEffect",), ("anaerobicTrainingEffect",)),
        "garmin_vo2max": num(("vO2MaxValue",), ("vO2MaxValue",)),
    }


def _start_times(
    dto: Mapping[str, Any], li: Mapping[str, Any], garmin_id: int
) -> tuple[datetime, datetime | None, timedelta | None]:
    """(start_utc aware UTC, start_local naive wall clock, local − UTC offset); summary before list item."""
    gmt_s, local_s = _parse_gmt(dto.get("startTimeGMT")), _parse_local(dto.get("startTimeLocal"))
    gmt_l, local_l = _parse_gmt(li.get("startTimeGMT")), _parse_local(li.get("startTimeLocal"))
    start_utc = _first(gmt_s, gmt_l)
    if start_utc is None:
        begin_ms = _as_float(li.get("beginTimestamp"))  # epoch ms, list items only
        if begin_ms is not None and begin_ms > 0:
            try:
                start_utc = datetime.fromtimestamp(begin_ms / 1000, tz=UTC)
            except (OverflowError, OSError, ValueError):
                log.warning("activity %s: beginTimestamp out of range", garmin_id)
    if start_utc is None:
        raise ValueError(f"activity {garmin_id} has no start time")
    start_local = _first(local_s, local_l)

    offset = None
    for gmt, local in ((gmt_s, local_s), (gmt_l, local_l)):
        if gmt is not None and local is not None:
            minutes = round((local - gmt.replace(tzinfo=None)).total_seconds() / 60)
            if abs(minutes) <= _MAX_TZ_OFFSET_MIN:
                offset = timedelta(minutes=minutes)
                break
    return start_utc, start_local, offset


def _parse_time(value: Any) -> datetime | None:
    """Parse Garmin's "YYYY-MM-DD HH:MM:SS" (list) / "YYYY-MM-DDTHH:MM:SS.f" (summary) strings."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        log.warning("unparseable Garmin time %r", value)
        return None


def _parse_gmt(value: Any) -> datetime | None:
    """A GMT time string as an aware UTC datetime (naive strings are UTC by definition)."""
    parsed = _parse_time(value)
    if parsed is None:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _parse_local(value: Any) -> datetime | None:
    """A local time string as a naive wall-clock datetime."""
    parsed = _parse_time(value)
    return None if parsed is None else parsed.replace(tzinfo=None)


def _format_offset(offset: timedelta) -> str:
    minutes = round(offset.total_seconds() / 60)
    sign = "+" if minutes >= 0 else "-"
    hours, mins = divmod(abs(minutes), 60)
    return f"{sign}{hours:02d}:{mins:02d}"


def _as_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _get(obj: Mapping[str, Any], *path: str) -> Any:
    cur: Any = obj
    for key in path:
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(key)
    return cur


def _first(*values: Any) -> Any:
    return next((v for v in values if v is not None), None)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


def _as_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _as_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
