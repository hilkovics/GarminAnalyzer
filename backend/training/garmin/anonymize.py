"""Anonymize recorded Garmin JSON before it is written to backend/tests/fixtures/.

GPS: every latitude/longitude is shifted by one constant offset per recording, so shapes, distances and
grades stay realistic while the real location is hidden. The offset is random (`random_offset`) and never
written anywhere – a fixed offset in source code would make the shift reversible. A single unshifted value
would reveal the offset for the whole recording, so matching is deliberately broad:
- keys `lat`, `lon`, `lng`, `long`, `latitude`, `longitude` (any case), camelCase suffixes (`startLatitude`,
  `minLat`, `maxLon`, …) and snake_case suffixes (`start_lat`, …) at any depth,
- `activityDetailMetrics[].metrics[i]` where `metricDescriptors[].key` names a lat/lon metric
  (e.g. `directLatitude`) – mapped by descriptor key, never by position,
- encoded polyline strings (any key containing "polyline") are dropped.

Identifiers: owner/user names, free-text descriptions, location and activity names (Garmin's default name
contains the town) and device serials become placeholders; numeric ids (activity, device, user) and
all-digit dict keys (device ids in training-status maps) are remapped to stable fake ids via `IdMap`, so
references between files still match. `find_leaks` is a last-resort scan for known real values.
Pure functions, no I/O.
"""

import json
import random
import re
from collections.abc import Iterable
from typing import Any

_COORD_EXACT = {"lat": 0, "latitude": 0, "lon": 1, "lng": 1, "long": 1, "longitude": 1}
_LAT_SUFFIX = re.compile(r"(?:(?<=[a-z0-9])(?:Lat|Latitude)|_(?:lat|latitude))$")
_LON_SUFFIX = re.compile(r"(?:(?<=[a-z0-9])(?:Lon|Lng|Longitude)|_(?:lon|lng|longitude))$")
_POLYLINE = re.compile(r"polyline", re.IGNORECASE)

PII_STRING_KEYS = frozenset(
    k.casefold()
    for k in (
        "ownerDisplayName",
        "ownerFullName",
        "displayName",
        "fullName",
        "userName",
        "firstName",
        "lastName",
        "email",
        "emailAddress",
        "locationName",
        "activityName",
        "description",
        "serialNumber",
        "deviceSerialNumber",
        "userProfileFullName",
    )
)
_PROFILE_IMAGE = re.compile(r"profileimageurl", re.IGNORECASE)
ID_KEYS = frozenset(
    k.casefold()
    for k in (
        "activityId",
        "deviceId",
        "userProfileId",
        "userProfilePK",
        "ownerId",
        "profileId",
        "userId",
        "unitId",
        "primaryActivityTrackerDeviceId",
    )
)
_DIGIT_KEY = re.compile(r"^\d{6,}$")
PLACEHOLDER = "anonymized"
FAKE_ID_START = 900_000_001


class IdMap:
    """Stable real → fake id mapping shared by all files of one recording."""

    def __init__(self, start: int = FAKE_ID_START) -> None:
        self._map: dict[int, int] = {}
        self._next = start

    def __call__(self, real: int) -> int:
        if real not in self._map:
            self._map[real] = self._next
            self._next += 1
        return self._map[real]


def random_offset(rng: random.Random | None = None) -> tuple[float, float]:
    """Random (Δlat, Δlon) in degrees, each 0.5–2.0 in magnitude with a random sign."""
    rng = rng or random.SystemRandom()

    def one() -> float:
        return rng.choice((-1.0, 1.0)) * rng.uniform(0.5, 2.0)

    return one(), one()


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def coord_axis(key: str) -> int | None:
    """0 for a latitude key, 1 for a longitude key, None otherwise."""
    exact = _COORD_EXACT.get(key.casefold())
    if exact is not None:
        return exact
    if _LAT_SUFFIX.search(key):
        return 0
    if _LON_SUFFIX.search(key):
        return 1
    return None


def _shift_detail_metrics(obj: dict[str, Any], offset: tuple[float, float]) -> None:
    """Shift lat/lon columns inside `activityDetailMetrics` using `metricDescriptors` (in place)."""
    descriptors = obj.get("metricDescriptors")
    rows = obj.get("activityDetailMetrics")
    if not isinstance(descriptors, list) or not isinstance(rows, list):
        return
    shifts: dict[int, float] = {}
    for d in descriptors:
        if not isinstance(d, dict):
            continue
        key, idx = d.get("key"), d.get("metricsIndex")
        if isinstance(key, str) and isinstance(idx, int):
            axis = coord_axis(key)
            if axis is not None:
                shifts[idx] = offset[axis]
    for row in rows:
        metrics = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(metrics, list):
            continue
        for idx, delta in shifts.items():
            if idx < len(metrics) and _is_number(metrics[idx]):
                metrics[idx] = metrics[idx] + delta


def _map_id(value: Any, ids: IdMap) -> Any:
    if _is_number(value) and value:
        return ids(int(value))
    if isinstance(value, str):
        return str(ids(int(value))) if value.isdigit() else PLACEHOLDER
    return value


def _walk(obj: Any, offset: tuple[float, float], ids: IdMap) -> Any:
    if isinstance(obj, list):
        return [_walk(v, offset, ids) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out: dict[str, Any] = {}
    for key, value in obj.items():
        new_key = str(ids(int(key))) if isinstance(key, str) and _DIGIT_KEY.match(key) else key
        folded = key.casefold() if isinstance(key, str) else ""
        axis = coord_axis(key) if isinstance(key, str) else None
        if (folded in PII_STRING_KEYS or _PROFILE_IMAGE.search(folded)) and isinstance(value, str):
            out[new_key] = PLACEHOLDER
        elif folded in ID_KEYS:
            out[new_key] = _map_id(value, ids)
        elif _POLYLINE.search(folded) and isinstance(value, str):
            out[new_key] = PLACEHOLDER
        elif axis is not None and _is_number(value):
            out[new_key] = value + offset[axis]
        else:
            out[new_key] = _walk(value, offset, ids)
    _shift_detail_metrics(out, offset)
    return out


def anonymize(payload: Any, offset: tuple[float, float], ids: IdMap | None = None) -> Any:
    """Deep copy of `payload` with GPS shifted by `offset` (Δlat, Δlon), ids remapped and PII replaced."""
    return _walk(payload, offset, ids or IdMap())


def _containers(obj: Any) -> Iterable[list[float]]:
    """Yield the numeric direct children of every dict / list in `obj`."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        children = list(cur.values()) if isinstance(cur, dict) else cur if isinstance(cur, list) else []
        nums = [float(v) for v in children if _is_number(v)]
        if nums:
            yield nums
        stack.extend(v for v in children if isinstance(v, dict | list))


def find_leaks(
    payload: Any,
    *,
    strings: Iterable[str] = (),
    points: Iterable[tuple[float, float]] = (),
    tol_deg: float = 0.05,
) -> list[str]:
    """Scan an already anonymized payload for known real values; returns human-readable findings.

    - `strings`: real names / ids of the logged-in user (case-insensitive substring; digits need
      non-digit boundaries).
    - `points`: real (lat, lon) start points; a container holding a non-integer number within `tol_deg` of
      the real latitude *and* one near the real longitude is a leak (catches unknown coordinate keys).
    """
    text = json.dumps(payload, ensure_ascii=False).casefold()
    findings: list[str] = []
    for s in strings:
        s = s.strip().casefold()
        if len(s) < 3:
            continue
        pattern = rf"(?<!\d){re.escape(s)}(?!\d)" if s.isdigit() else re.escape(s)
        if re.search(pattern, text):
            findings.append("real user name/id present")
    pts = list(points)
    if pts:
        for nums in _containers(payload):
            fractional = [n for n in nums if n != int(n)]
            for lat, lon in pts:
                near_lat = any(abs(n - lat) < tol_deg for n in fractional)
                near_lon = any(abs(n - lon) < tol_deg for n in fractional)
                if near_lat and near_lon:
                    findings.append("real coordinates present")
                    break
    return sorted(set(findings))
