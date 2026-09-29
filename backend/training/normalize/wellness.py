"""Sleep / RHR / Body Battery / stress / daily summary JSON → `daily_wellness` rows (PLAN §4, phase 1).

Sources (one calendar day each, except body battery which may be a date range):

- `sleep` = `get_sleep_data(date)`: `dailySleepDTO{sleepTimeSeconds, deep/light/rem/awakeSleepSeconds,
  sleepStartTimestampGMT, sleepEndTimestampGMT (epoch ms), sleepScores.overall.value}` and a top-level
  `restingHeartRate`. Only the *GMT* timestamps are used; the *Local* ones are double-offset on some
  accounts.
- `rhr` = `get_rhr_day(date)`: `allMetrics.metricsMap.WELLNESS_RESTING_HEART_RATE[{calendarDate, value}]`.
- `user_summary` = `get_user_summary(date)`: `totalSteps, restingHeartRate, averageStressLevel,
  bodyBatteryLowestValue, bodyBatteryAtWakeTime`.
- `stress` = `get_stress_data(date)`: `avgStressLevel`; negative values (−1 / −2) mean "no data".
- `body_battery` = `get_body_battery(start, end)`: list of `{date, bodyBatteryValuesArray,
  bodyBatteryValueDescriptorDTOList[{bodyBatteryValueDescriptorIndex, bodyBatteryValueDescriptorKey}]}`;
  array columns are mapped by descriptor key. Only when the descriptor list is missing entirely are the
  columns assumed to be [timestamp, level] (the documented Garmin default); verify with real fixtures.

Every field is nullable and missing or malformed keys never raise. `sleep_start` / `sleep_end` are
timezone-aware UTC datetimes. `weight_kg` is not fetched in phase 1 and is always None.
Pure functions, no I/O.
"""

import logging
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

log = logging.getLogger(__name__)

WELLNESS_COLUMNS = [
    "date",
    "sleep_start",
    "sleep_end",
    "sleep_s",
    "deep_s",
    "light_s",
    "rem_s",
    "awake_s",
    "sleep_score",
    "rhr",
    "body_battery_wake",
    "body_battery_min",
    "stress_avg",
    "steps",
    "weight_kg",
]

BB_WAKE_WINDOW = timedelta(minutes=60)
_BB_DESCRIPTOR_LISTS = ("bodyBatteryValueDescriptorDTOList", "bodyBatteryValueDescriptorsDTOList")
_BB_DEFAULT_COLUMNS = {"timestamp": 0, "bodyBatteryLevel": 1}  # used only when descriptors are missing


def normalize_wellness(
    day: date,
    *,
    sleep: dict | None = None,
    user_summary: dict | None = None,
    rhr: dict | None = None,
    stress: dict | None = None,
    body_battery: list | dict | None = None,
) -> dict:
    """One `daily_wellness` row dict with exactly `WELLNESS_COLUMNS`; a day without data is all None."""
    sleep_d = _as_dict(sleep)
    dto = _as_dict(sleep_d.get("dailySleepDTO"))
    summary = _as_dict(user_summary)

    sleep_start = epoch_ms_to_utc(dto.get("sleepStartTimestampGMT"))
    sleep_end = epoch_ms_to_utc(dto.get("sleepEndTimestampGMT"))

    rhr_value = _positive_int(
        _first(
            _rhr_from_payload(rhr, day),
            _positive_int(summary.get("restingHeartRate")),
            _positive_int(sleep_d.get("restingHeartRate")),
            _positive_int(dto.get("restingHeartRate")),
        )
    )

    stress_avg = _stress_value(_as_dict(stress).get("avgStressLevel"))
    if stress_avg is None:
        stress_avg = _stress_value(summary.get("averageStressLevel"))

    levels = body_battery_samples(body_battery, day)
    bb_wake = _non_negative_int(summary.get("bodyBatteryAtWakeTime"))
    if bb_wake is None:
        bb_wake = _level_after(levels, sleep_end)
    bb_min = min((lvl for _, lvl in levels), default=None)
    if bb_min is None:
        bb_min = _non_negative_int(summary.get("bodyBatteryLowestValue"))

    return {
        "date": day,
        "sleep_start": sleep_start,
        "sleep_end": sleep_end,
        "sleep_s": _non_negative_int(dto.get("sleepTimeSeconds")),
        "deep_s": _non_negative_int(dto.get("deepSleepSeconds")),
        "light_s": _non_negative_int(dto.get("lightSleepSeconds")),
        "rem_s": _non_negative_int(dto.get("remSleepSeconds")),
        "awake_s": _non_negative_int(dto.get("awakeSleepSeconds")),
        "sleep_score": _non_negative_int(_get(dto, "sleepScores", "overall", "value")),
        "rhr": rhr_value,
        "body_battery_wake": bb_wake,
        "body_battery_min": bb_min,
        "stress_avg": stress_avg,
        "steps": _non_negative_int(summary.get("totalSteps")),
        "weight_kg": None,
    }


def epoch_ms_to_utc(value: Any) -> datetime | None:
    """Epoch milliseconds (GMT) → aware UTC datetime; None for missing or non-numeric values."""
    ms = _as_float(value)
    if ms is None or ms <= 0:
        return None
    try:
        return datetime.fromtimestamp(ms / 1000.0, tz=UTC)
    except (OverflowError, OSError, ValueError):
        log.warning("epoch timestamp out of range: %r", value)
        return None


def body_battery_samples(body_battery: list | dict | None, day: date) -> list[tuple[float, int]]:
    """(epoch ms, level) pairs of `day`'s body-battery entry, sorted by time.

    A range response holds one entry per `date`; a single entry without a `date` is accepted as is.
    Columns come from the descriptor list (either spelling); without descriptors [timestamp, level] is
    assumed. Samples with a missing timestamp or level are skipped.
    """
    entry = _bb_entry(body_battery, day)
    if entry is None:
        return []
    columns = _bb_columns(entry)
    ts_i, lvl_i = columns.get("timestamp"), columns.get("bodyBatteryLevel")
    if ts_i is None or lvl_i is None:
        log.warning("body battery %s: descriptors without timestamp/bodyBatteryLevel", day)
        return []
    out: list[tuple[float, int]] = []
    for row in entry.get("bodyBatteryValuesArray") or []:
        if not isinstance(row, Sequence) or isinstance(row, str) or max(ts_i, lvl_i) >= len(row):
            continue
        ts, level = _as_float(row[ts_i]), _non_negative_int(row[lvl_i])
        if ts is not None and level is not None:
            out.append((ts, level))
    out.sort(key=lambda p: p[0])
    return out


def _bb_entry(body_battery: list | dict | None, day: date) -> Mapping[str, Any] | None:
    entries = [body_battery] if isinstance(body_battery, Mapping) else body_battery
    if not isinstance(entries, list):
        return None
    entries = [e for e in entries if isinstance(e, Mapping)]
    iso = day.isoformat()
    for entry in entries:
        if entry.get("date") == iso:
            return entry
    if len(entries) == 1 and entries[0].get("date") is None:
        return entries[0]
    return None


def _bb_columns(entry: Mapping[str, Any]) -> dict[str, int]:
    descriptors = next(
        (entry[k] for k in _BB_DESCRIPTOR_LISTS if isinstance(entry.get(k), list) and entry[k]), None
    )
    if descriptors is None:
        return dict(_BB_DEFAULT_COLUMNS)
    columns: dict[str, int] = {}
    for d in descriptors:
        if not isinstance(d, Mapping):
            continue
        key, index = d.get("bodyBatteryValueDescriptorKey"), d.get("bodyBatteryValueDescriptorIndex")
        if isinstance(key, str) and isinstance(index, int) and not isinstance(index, bool) and index >= 0:
            columns.setdefault(key, index)
    return columns


def _level_after(levels: list[tuple[float, int]], sleep_end: datetime | None) -> int | None:
    """Level of the first sample at/after `sleep_end`, within BB_WAKE_WINDOW."""
    if sleep_end is None:
        return None
    start_ms = sleep_end.timestamp() * 1000.0
    end_ms = start_ms + BB_WAKE_WINDOW.total_seconds() * 1000.0
    return next((lvl for ts, lvl in levels if start_ms <= ts <= end_ms), None)


def _rhr_from_payload(rhr: Any, day: date) -> int | None:
    """`WELLNESS_RESTING_HEART_RATE` value for `day` (a lone entry without a calendarDate is accepted)."""
    entries = _get(_as_dict(rhr), "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE")
    if not isinstance(entries, list):
        return None
    entries = [e for e in entries if isinstance(e, Mapping)]
    iso = day.isoformat()
    for entry in entries:
        if entry.get("calendarDate") == iso:
            return _positive_int(entry.get("value"))
    undated = [e for e in entries if e.get("calendarDate") is None]
    if len(entries) == 1 and undated:
        return _positive_int(undated[0].get("value"))
    return None


def _stress_value(value: Any) -> int | None:
    """Garmin stress 0–100; negative values (−1 / −2) mean "no data"."""
    return _non_negative_int(value)


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


def _non_negative_int(value: Any) -> int | None:
    number = _as_float(value)
    if number is None or number < 0:
        return None
    return round(number)


def _positive_int(value: Any) -> int | None:
    number = _non_negative_int(value)
    return number if number else None
