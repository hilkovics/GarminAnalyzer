"""Anonymize recorded Garmin JSON before it is written to backend/tests/fixtures/.

GPS: all coordinates of one recording are moved by the same random rigid rotation of the sphere
(`random_rotation`), which is never written anywhere. A rotation preserves every great-circle distance
exactly, so distance, speed and grade fields stay consistent and reveal nothing. A constant lat/lon offset
would not be safe: east–west distances scale with cos φ, so real distances give away the real latitude.
Because a rotation mixes latitude and longitude, coordinates are transformed as (lat, lon) pairs:
- sibling keys with the same stem in one object (`startLatitude`/`startLongitude`, `lat`/`lon`,
  `minLat`/`minLon` + `maxLat`/`maxLon` bounding boxes, `start_lat`/`start_lon`),
- `activityDetailMetrics[].metrics[i]` columns paired via `metricDescriptors[].key` (e.g. `directLatitude` /
  `directLongitude`) – mapped by descriptor key, never by position.
An unpaired coordinate value is dropped (set to null); encoded polyline strings are replaced.

Identifiers: owner/user names, free-text descriptions, location and activity names (Garmin's default name
contains the town) and device serials become placeholders; numeric ids (activity, parent/child activity,
device, user) and all-digit dict keys (device ids in training-status maps) are remapped to stable fake ids
via `IdMap`, so references between files still match. `find_leaks` is a last-resort scan for known real
values. Pure functions, no I/O.
"""

import math
import random
import re
from collections.abc import Iterable
from typing import Any

Rotation = tuple[tuple[float, float, float], tuple[float, float, float], tuple[float, float, float]]

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
        "userProfileFullName",
    )
)
SERIAL_KEYS = frozenset(k.casefold() for k in ("serialNumber", "deviceSerialNumber", "unitSerialNumber"))
_PROFILE_IMAGE = re.compile(r"profileimageurl", re.IGNORECASE)
ID_KEYS = frozenset(
    k.casefold()
    for k in (
        "activityId",
        "parentId",
        "parentActivityId",
        "childIds",
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


# --- sphere rotation -------------------------------------------------------------------------------------


def _to_vec(lat: float, lon: float) -> tuple[float, float, float]:
    phi, lam = math.radians(lat), math.radians(lon)
    return (math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi))


def rotate_point(rot: Rotation, lat: float, lon: float) -> tuple[float, float]:
    """Apply `rot` to a (lat, lon) point in degrees."""
    v = _to_vec(lat, lon)
    x, y, z = (sum(r[i] * v[i] for i in range(3)) for r in rot)
    return math.degrees(math.asin(max(-1.0, min(1.0, z)))), math.degrees(math.atan2(y, x))


def axis_angle_rotation(axis: tuple[float, float, float], angle_deg: float) -> Rotation:
    """Rotation matrix (Rodrigues) about `axis` by `angle_deg`."""
    n = math.sqrt(sum(a * a for a in axis))
    x, y, z = (a / n for a in axis)
    c, s = math.cos(math.radians(angle_deg)), math.sin(math.radians(angle_deg))
    t = 1 - c
    return (
        (t * x * x + c, t * x * y - s * z, t * x * z + s * y),
        (t * x * y + s * z, t * y * y + c, t * y * z - s * x),
        (t * x * z - s * y, t * y * z + s * x, t * z * z + c),
    )


def angular_distance_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    va, vb = _to_vec(*a), _to_vec(*b)
    dot = max(-1.0, min(1.0, sum(p * q for p, q in zip(va, vb, strict=True))))
    return math.degrees(math.acos(dot))


def random_rotation(
    points: Iterable[tuple[float, float]] = (),
    rng: random.Random | None = None,
    *,
    min_move_deg: float = 10.0,
    max_abs_lat: float = 55.0,
    max_abs_lon: float = 150.0,
) -> Rotation:
    """Uniformly random rotation that moves every real `point` ≥ `min_move_deg` (≈ 1100 km) away and lands
    it at a moderate latitude, away from the antimeridian (so no track wraps around ±180°). If activities are
    spread so widely that the placement bounds can't be met, only the minimum move is enforced."""
    rng = rng or random.SystemRandom()
    pts = list(points)
    for attempt in range(20_000):
        axis = (rng.gauss(0, 1), rng.gauss(0, 1), rng.gauss(0, 1))
        rot = axis_angle_rotation(axis, rng.uniform(30.0, 180.0))
        moved = [rotate_point(rot, *p) for p in pts]
        bounded = attempt < 10_000
        if all(
            angular_distance_deg(p, m) >= min_move_deg
            and (not bounded or (abs(m[0]) <= max_abs_lat and abs(m[1]) <= max_abs_lon))
            for p, m in zip(pts, moved, strict=True)
        ):
            return rot
    raise RuntimeError("could not find a rotation that moves every point far enough")


# --- key classification ----------------------------------------------------------------------------------


def _coord_key(key: str) -> tuple[int, str] | None:
    """(axis, stem) for a coordinate key – axis 0 = latitude, 1 = longitude – else None."""
    exact = _COORD_EXACT.get(key.casefold())
    if exact is not None:
        return exact, ""
    for axis, pattern in ((0, _LAT_SUFFIX), (1, _LON_SUFFIX)):
        m = pattern.search(key)
        if m:
            return axis, key[: m.start()].casefold()
    return None


def coord_axis(key: str) -> int | None:
    """0 for a latitude key, 1 for a longitude key, None otherwise."""
    found = _coord_key(key)
    return found[0] if found else None


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


# --- transformation --------------------------------------------------------------------------------------


def _rotate_pairs(out: dict[str, Any], coord_keys: dict[str, dict[int, str]], rot: Rotation) -> None:
    """Rotate paired coordinate fields of one object in place; drop unpaired ones."""
    rotated: dict[str, tuple[float, float]] = {}
    for stem, axes in coord_keys.items():
        lat_key, lon_key = axes.get(0), axes.get(1)
        lat = out.get(lat_key) if lat_key else None
        lon = out.get(lon_key) if lon_key else None
        if _is_number(lat) and _is_number(lon):
            rotated[stem] = rotate_point(rot, lat, lon)
            out[lat_key], out[lon_key] = rotated[stem]
        else:
            for key in axes.values():
                if _is_number(out.get(key)):
                    out[key] = None
    if "min" in rotated and "max" in rotated:  # bounding box: recompute from both rotated corners
        (a_lat, a_lon), (b_lat, b_lon) = rotated["min"], rotated["max"]
        axes_min, axes_max = coord_keys["min"], coord_keys["max"]
        out[axes_min[0]], out[axes_max[0]] = min(a_lat, b_lat), max(a_lat, b_lat)
        out[axes_min[1]], out[axes_max[1]] = min(a_lon, b_lon), max(a_lon, b_lon)


def _rotate_detail_metrics(obj: dict[str, Any], rot: Rotation) -> None:
    """Rotate lat/lon columns inside `activityDetailMetrics`, paired via `metricDescriptors` (in place)."""
    descriptors = obj.get("metricDescriptors")
    rows = obj.get("activityDetailMetrics")
    if not isinstance(descriptors, list) or not isinstance(rows, list):
        return
    columns: dict[str, dict[int, int]] = {}
    for d in descriptors:
        if isinstance(d, dict) and isinstance(d.get("key"), str) and isinstance(d.get("metricsIndex"), int):
            found = _coord_key(d["key"])
            if found:
                columns.setdefault(found[1], {})[found[0]] = d["metricsIndex"]
    for row in rows:
        metrics = row.get("metrics") if isinstance(row, dict) else None
        if not isinstance(metrics, list):
            continue
        for axes in columns.values():
            i_lat, i_lon = axes.get(0), axes.get(1)
            lat = metrics[i_lat] if i_lat is not None and i_lat < len(metrics) else None
            lon = metrics[i_lon] if i_lon is not None and i_lon < len(metrics) else None
            if _is_number(lat) and _is_number(lon):
                metrics[i_lat], metrics[i_lon] = rotate_point(rot, lat, lon)
            else:
                for i in axes.values():
                    if i < len(metrics) and _is_number(metrics[i]):
                        metrics[i] = None


def _map_id(value: Any, ids: IdMap) -> Any:
    if isinstance(value, list):
        return [_map_id(v, ids) for v in value]
    if _is_number(value) and value:
        return ids(int(value))
    if isinstance(value, str):
        return str(ids(int(value))) if value.isdigit() else PLACEHOLDER
    return value


def _walk(obj: Any, rot: Rotation, ids: IdMap) -> Any:
    if isinstance(obj, list):
        return [_walk(v, rot, ids) for v in obj]
    if not isinstance(obj, dict):
        return obj
    out: dict[str, Any] = {}
    coord_keys: dict[str, dict[int, str]] = {}
    for key, value in obj.items():
        new_key = str(ids(int(key))) if isinstance(key, str) and _DIGIT_KEY.match(key) else key
        folded = key.casefold() if isinstance(key, str) else ""
        coord = _coord_key(key) if isinstance(key, str) else None
        is_pii = (folded in PII_STRING_KEYS or _PROFILE_IMAGE.search(folded)) and isinstance(value, str)
        is_serial = folded in SERIAL_KEYS and value is not None  # serials may be numeric
        if is_pii or is_serial:
            out[new_key] = PLACEHOLDER
        elif folded in ID_KEYS:
            out[new_key] = _map_id(value, ids)
        elif _POLYLINE.search(folded) and isinstance(value, str):
            out[new_key] = PLACEHOLDER
        elif coord is not None and (_is_number(value) or value is None):
            out[new_key] = value
            coord_keys.setdefault(coord[1], {})[coord[0]] = new_key
        else:
            out[new_key] = _walk(value, rot, ids)
    _rotate_pairs(out, coord_keys, rot)
    _rotate_detail_metrics(out, rot)
    return out


def anonymize(payload: Any, rotation: Rotation, ids: IdMap | None = None) -> Any:
    """Deep copy of `payload` with GPS rotated by `rotation`, ids remapped and PII replaced."""
    return _walk(payload, rotation, ids or IdMap())


# --- leak scan -------------------------------------------------------------------------------------------


def _needles(strings: Iterable[str]) -> list[tuple[re.Pattern[str], int | None]]:
    out = []
    for s in strings:
        s = s.strip().casefold()
        if len(s) < 3:
            continue
        boundary = r"(?<!\d){}(?!\d)" if s.isdigit() else r"(?<!\w){}(?!\w)"
        out.append((re.compile(boundary.format(re.escape(s))), int(s) if s.isdigit() else None))
    return out


def find_leaks(
    payload: Any,
    *,
    strings: Iterable[str] = (),
    points: Iterable[tuple[float, float]] = (),
    tol_deg: float = 0.05,
) -> list[str]:
    """Scan an already anonymized payload for known real values; returns findings with JSON key paths.

    Findings contain only fixed text and key paths (digit keys are already fake ids), never the values.
    - `strings`: real names / ids of the logged-in user, matched against string *values* on word
      boundaries (digits: on digit boundaries, and numeric values equal to the id).
    - `points`: real (lat, lon) start points; an object/array holding a non-integer number within `tol_deg`
      of the real latitude *and* one near the real longitude is a leak (catches unknown coordinate keys).
    """
    needles = _needles(strings)
    pts = list(points)
    findings: set[str] = set()
    stack: list[tuple[str, Any]] = [("$", payload)]
    while stack:
        path, cur = stack.pop()
        if isinstance(cur, dict):
            items = [(f"{path}.{k}", v) for k, v in cur.items()]
        elif isinstance(cur, list):
            items = [(f"{path}[{i}]", v) for i, v in enumerate(cur)]
        else:
            continue
        fractional = [float(v) for _, v in items if _is_number(v) and v != int(v)]
        for lat, lon in pts:
            if any(abs(n - lat) < tol_deg for n in fractional) and any(
                abs(n - lon) < tol_deg for n in fractional
            ):
                findings.add(f"real coordinates at {path}")
                break
        for child_path, value in items:
            if isinstance(value, dict | list):
                stack.append((child_path, value))
            elif isinstance(value, str):
                text = value.casefold()
                if any(p.search(text) for p, _ in needles):
                    findings.add(f"real user name/id at {child_path}")
            elif _is_number(value) and any(n is not None and value == n for _, n in needles):
                findings.add(f"real user name/id at {child_path}")
    return sorted(findings)
