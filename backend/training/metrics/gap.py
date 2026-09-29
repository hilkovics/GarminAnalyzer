"""Grade-adjusted pace (Minetti cost of running) – METRICS §3 (phase 2).

# METRICS §3
Metabolic cost of running (Minetti et al. 2002), `i` = grade (fraction):
    C(i) = 155.4·i⁵ − 30.4·i⁴ − 43.3·i³ + 46.3·i² + 19.5·i + 3.6   (J/kg/m),   C(0) = 3.6
    gap_speed_i = speed_i · C(grade_i) / C(0).   Where grade is NaN use gap_speed = speed.
Changed 2026-09-29 (approved by the user): `gap_speed` is clamped to the run speed range of §0.4
(`0–7 m/s`), so an altitude/GPS glitch at the ±0.30 grade clamp (C(0.30)/C(0) ≈ 3.5) cannot inflate NGS/rTSS.

The grade is already clamped to ±0.30 by §0.5 (`metrics/preprocess.py`); C(i) is positive on that range.
The upper speed limit is the §0.4 constant `preprocess.MAX_SPEED["run"]`, passed in by the caller (this
module is a leaf: `preprocess` imports it, so it cannot import `preprocess` back).
Pure functions, no I/O.
"""

import numpy as np

# METRICS §3 polynomial coefficients, highest power first (for np.polyval).
MINETTI_COEFFS: tuple[float, ...] = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)
C0 = 3.6  # C(0), J/kg/m


def minetti_cost(grade: np.ndarray) -> np.ndarray:
    """METRICS §3 `C(i)` in J/kg/m for each grade (fraction); NaN stays NaN."""
    return np.polyval(MINETTI_COEFFS, np.asarray(grade, dtype=float))


def gap_speed(speed: np.ndarray, grade: np.ndarray, *, max_speed: float) -> np.ndarray:
    """METRICS §3 `gap_speed = speed · C(grade) / C(0)`, clamped to `[0, max_speed]`; NaN grade → speed
    (also clamped), NaN speed → NaN.

    `max_speed` is the §0.4 run limit (`preprocess.MAX_SPEED["run"]`, 7 m/s). The cost ratio is formed
    first, so a flat sample (C(0) / C(0) = 1) inside the range returns the speed bit for bit.
    """
    speed = np.asarray(speed, dtype=float)
    grade = np.asarray(grade, dtype=float)
    if speed.shape != grade.shape:
        raise ValueError(f"speed {speed.shape} and grade {grade.shape} differ in shape")
    ratio = minetti_cost(grade) / C0
    gap = np.where(np.isnan(grade), speed, speed * ratio)
    return np.clip(gap, 0.0, max_speed)  # NaN stays NaN
