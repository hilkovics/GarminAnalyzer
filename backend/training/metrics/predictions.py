"""Riegel and Daniels VDOT race predictions – METRICS §7 (phase 4).

# METRICS §7
Reference performance = best of: activities flagged `is_race`, or best efforts with `W ≥ 600 s`,
converted to (distance, time) using the effort's actual distance.
- Riegel: `T2 = T1 · (D2/D1)^1.06` for 5 km, 10 km, 21.0975 km, 42.195 km.
- Daniels VDOT: with `v` in m/min and `t` in minutes: `VO2 = −4.60 + 0.182258·v + 0.000104·v²`,
  `pct = 0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)`, `VDOT = VO2 / pct`.
  Equivalent race time for distance D: solve `t` such that `VDOT(D/t, t) == VDOT` (bisection).
Show both; flag when the reference effort is older than 60 days.
(Clarified 2026-09-29, phase 4: candidates = run `is_race` activities and run gap_speed best efforts with
`W ≥ 600 s` and a known distance, from the trailing 90 days (if none: all-time). The reference is the
candidate with the highest VDOT; Riegel and Daniels both start from it. Distances whose reference distance
is under 1/4 of the target are still predicted (flagged `extrapolated`).
Tests: 10 km in 40:00 → VDOT ≈ 51.94 (± 0.05); equivalent half marathon ≈ 1:28:33 (± 10 s).)

Interpretation choices: candidates dated after `today` or without a positive distance/time are ignored;
VDOT ties → the most recent candidate; "older than 60 days" = `today − local_date > 60` days.
Building the candidate frame (races + efforts) is the caller's job.

Pure functions, no I/O.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

RACE_DISTANCES: dict[str, float] = {"5k": 5000.0, "10k": 10000.0, "half": 21097.5, "marathon": 42195.0}
RIEGEL_EXPONENT = 1.06  # §7
TRAILING_DAYS = 90  # §7 clarified: candidate window
STALE_DAYS = 60  # §7: flag references older than 60 days
EXTRAPOLATION_RATIO = 0.25  # §7 clarified: reference distance < 1/4 of the target → extrapolated
_BISECTION_TOL_S = 1e-7
_BISECTION_MAX_ITER = 200


@dataclass(frozen=True)
class Reference:
    """The reference performance all predictions start from (METRICS §7)."""

    distance_m: float
    time_s: float
    local_date: date
    source: str  # "race" | "effort"
    vdot: float


@dataclass(frozen=True)
class Prediction:
    """Predicted time for one race distance (METRICS §7)."""

    name: str
    distance_m: float
    riegel_s: float
    daniels_s: float
    extrapolated: bool


def vdot(distance_m: float, time_s: float) -> float:
    """METRICS §7 Daniels VDOT of a performance (`v` in m/min, `t` in min)."""
    if not (distance_m > 0 and time_s > 0):
        raise ValueError(f"distance and time must be positive, got {distance_m!r}, {time_s!r}")
    t = time_s / 60.0
    v = distance_m / t
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v**2
    pct = 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)
    return vo2 / pct


def vdot_race_time(vdot_value: float, distance_m: float) -> float:
    """METRICS §7: the time `t` (s) with `vdot(distance_m, t) == vdot_value`, by bisection.

    Bracket: 1 s (VDOT far above any human value) … `distance_m · 60` s (1 m/min, where VO2 < 0).
    """
    if not (vdot_value > 0 and distance_m > 0):
        raise ValueError(f"vdot and distance must be positive, got {vdot_value!r}, {distance_m!r}")
    lo, hi = 1.0, distance_m * 60.0
    while vdot(distance_m, lo) <= vdot_value:  # only for absurd VDOTs / tiny distances
        lo /= 2.0
    for _ in range(_BISECTION_MAX_ITER):
        mid = (lo + hi) / 2.0
        if vdot(distance_m, mid) > vdot_value:
            lo = mid
        else:
            hi = mid
        if hi - lo < _BISECTION_TOL_S:
            break
    return (lo + hi) / 2.0


def riegel(time_s: float, distance_m: float, target_m: float) -> float:
    """METRICS §7 Riegel: `T2 = T1 · (D2/D1)^1.06`."""
    return time_s * (target_m / distance_m) ** RIEGEL_EXPONENT


def pick_reference(candidates: pd.DataFrame, *, today: date) -> Reference | None:
    """METRICS §7: the candidate with the highest VDOT from the trailing 90 days, else from all time.

    `candidates` columns: `local_date, distance_m, time_s, source`. None when no valid candidate exists.
    """
    if candidates.empty:
        return None
    df = candidates.copy()
    df["local_date"] = pd.to_datetime(df["local_date"]).dt.date
    df["distance_m"] = pd.to_numeric(df["distance_m"], errors="coerce")
    df["time_s"] = pd.to_numeric(df["time_s"], errors="coerce")
    ok = (df["distance_m"] > 0) & (df["time_s"] > 0) & (df["local_date"] <= today)
    df = df[ok.astype(bool)]
    if df.empty:
        return None
    recent = df[df["local_date"] >= today - timedelta(days=TRAILING_DAYS - 1)]
    pool = recent if not recent.empty else df
    pool = pool.assign(
        vdot=[vdot(float(d), float(t)) for d, t in zip(pool["distance_m"], pool["time_s"], strict=True)]
    )
    best = pool.sort_values(["vdot", "local_date"], ascending=[False, False], kind="stable").iloc[0]
    return Reference(
        distance_m=float(best["distance_m"]),
        time_s=float(best["time_s"]),
        local_date=best["local_date"],
        source=str(best["source"]),
        vdot=float(best["vdot"]),
    )


def predict(reference: Reference) -> list[Prediction]:
    """METRICS §7: Riegel and Daniels predictions for every `RACE_DISTANCES` entry, in that order."""
    return [
        Prediction(
            name=name,
            distance_m=target,
            riegel_s=riegel(reference.time_s, reference.distance_m, target),
            daniels_s=vdot_race_time(reference.vdot, target),
            extrapolated=reference.distance_m < EXTRAPOLATION_RATIO * target,
        )
        for name, target in RACE_DISTANCES.items()
    ]


def is_stale(reference: Reference, today: date) -> bool:
    """METRICS §7: the reference is older than 60 days (60 → fresh, 61 → stale)."""
    return (today - reference.local_date).days > STALE_DAYS
