"""Anonymize recorded Garmin JSON before it is written to backend/tests/fixtures/.

GPS: every latitude/longitude is shifted by one constant offset per recording, so shapes, distances and
grades stay realistic while the real location is hidden. The offset is random (`random_offset`) and never
written anywhere – a fixed offset in source code would make the shift reversible. Covered forms:
- plain keys (`lat`, `lon`, `latitude`, `longitude`, `startLatitude`, `endLongitude`, …) at any depth,
- `activityDetailMetrics[].metrics[i]` where `metricDescriptors[].key` names a lat/lon metric
  (e.g. `directLatitude`) – mapped by descriptor key, never by position.

Personal identifiers (owner names, profile ids and images, location and activity names – Garmin's
default activity name contains the town) are replaced by placeholders. Pure functions, no I/O.
"""

import random
import re
from typing import Any

_LAT_RE = re.compile(r"^(lat|latitude)$|latitude$", re.IGNORECASE)
_LON_RE = re.compile(r"^(lon|lng|long|longitude)$|longitude$", re.IGNORECASE)

PII_STRING_KEYS = frozenset(
    {
        "ownerDisplayName",
        "ownerFullName",
        "ownerProfileImageUrlSmall",
        "ownerProfileImageUrlMedium",
        "ownerProfileImageUrlLarge",
        "displayName",
        "fullName",
        "userName",
        "locationName",
        "activityName",
        "profileImageUrlLarge",
        "profileImageUrlMedium",
        "profileImageUrlSmall",
    }
)
PII_NUMERIC_KEYS = frozenset({"userProfileId", "userProfilePK", "userProfilePk", "ownerId", "profileId"})
PLACEHOLDER = "anonymized"


def random_offset(rng: random.Random | None = None) -> tuple[float, float]:
    """Random (Δlat, Δlon) in degrees, each 0.5–2.0 in magnitude with a random sign."""
    rng = rng or random.SystemRandom()

    def one() -> float:
        return rng.choice((-1.0, 1.0)) * rng.uniform(0.5, 2.0)

    return one(), one()


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _coord_offset(key: str, offset: tuple[float, float]) -> float | None:
    if _LAT_RE.search(key):
        return offset[0]
    if _LON_RE.search(key):
        return offset[1]
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
            delta = _coord_offset(key, offset)
            if delta is not None:
                shifts[idx] = delta
    for row in rows:
        metrics = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(metrics, list):
            continue
        for idx, delta in shifts.items():
            if idx < len(metrics) and _is_number(metrics[idx]):
                metrics[idx] = metrics[idx] + delta


def _walk(obj: Any, offset: tuple[float, float]) -> Any:
    if isinstance(obj, list):
        return [_walk(v, offset) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out: dict[str, Any] = {}
    for key, value in obj.items():
        if key in PII_STRING_KEYS and isinstance(value, str):
            out[key] = PLACEHOLDER
            continue
        if key in PII_NUMERIC_KEYS and _is_number(value):
            out[key] = 0
            continue
        delta = _coord_offset(key, offset)
        if delta is not None and _is_number(value):
            out[key] = value + delta
        else:
            out[key] = _walk(value, offset)
    _shift_detail_metrics(out, offset)
    return out


def anonymize(payload: Any, offset: tuple[float, float]) -> Any:
    """Return a deep copy of `payload` with GPS shifted by `offset` (Δlat, Δlon) and PII replaced."""
    return _walk(payload, offset)
