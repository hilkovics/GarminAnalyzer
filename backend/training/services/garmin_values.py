"""Garmin's own lactate-threshold and VO2max values from the stored raw payloads (next to §6.3 proposals).

The payload shapes are UNVERIFIED guesses: anything unexpected gives None, never an error.
"""

import math
from typing import Any

from sqlalchemy import select
from sqlmodel import Session

from training.db import raw_kinds
from training.db.models import RawGarmin


def number(value: Any) -> float | None:
    """A finite float or None (also for JSON of unknown shape)."""
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return None
    return float(value)


_MAX_LT_SPEED_MS = 8.0


def _latest_payloads(session: Session, kind: str, limit: int = 10) -> list[Any]:
    rows = session.execute(
        select(RawGarmin.payload)
        .where(RawGarmin.kind == kind)
        .order_by(RawGarmin.ref_key.desc(), RawGarmin.id.desc())
        .limit(limit)
    ).scalars()
    return list(rows)


def _garmin_lactate_threshold(payload: Any) -> tuple[float | None, float | None]:
    """(heart rate bpm, speed m/s) from `{"speed_and_heart_rate": {"heartRate": …, "speed": …}}`.

    Garmin reports the speed in units of 10 m/s (0.35 for 3.5 m/s) as far as we know; values that already
    look like m/s (≥ 1) are kept. Implausible values → None.
    """
    block = payload.get("speed_and_heart_rate") if isinstance(payload, dict) else None
    if not isinstance(block, dict):
        return None, None
    hr = number(block.get("heartRate"))
    speed = number(block.get("speed"))
    if hr is not None and not 60 <= hr <= 240:
        hr = None
    if speed is not None:
        speed = speed * 10.0 if 0.1 <= speed < 1.0 else speed
        if not 1.0 <= speed <= _MAX_LT_SPEED_MS:
            speed = None
    return hr, speed


def _garmin_vo2max(payload: Any) -> float | None:
    """`vo2MaxPreciseValue` (else `vo2MaxValue`) of `[{"generic": {…}}]` or `{"generic": {…}}`."""
    item = payload[0] if isinstance(payload, list) and payload else payload
    generic = item.get("generic") if isinstance(item, dict) else None
    if not isinstance(generic, dict):
        return None
    for key in ("vo2MaxPreciseValue", "vo2MaxValue"):
        value = number(generic.get(key))
        if value is not None and 10 <= value <= 100:
            return value
    return None


def garmin_values(session: Session) -> tuple[float | None, float | None, float | None]:
    """Latest available (LT heart rate, LT speed, VO2max) from the stored raw Garmin payloads."""
    lthr = speed = None
    for payload in _latest_payloads(session, raw_kinds.LACTATE_THRESHOLD):
        lthr, speed = _garmin_lactate_threshold(payload)
        if lthr is not None or speed is not None:
            break
    vo2max = next(
        (v for p in _latest_payloads(session, raw_kinds.MAX_METRICS) if (v := _garmin_vo2max(p)) is not None),
        None,
    )
    return lthr, speed, vo2max
