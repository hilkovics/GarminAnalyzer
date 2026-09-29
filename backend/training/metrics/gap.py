"""Grade-adjusted pace (Minetti cost of running) – METRICS §3 (phase 2).

# METRICS §3
Metabolic cost of running (Minetti et al. 2002), `i` = grade (fraction):
    C(i) = 155.4·i⁵ − 30.4·i⁴ − 43.3·i³ + 46.3·i² + 19.5·i + 3.6   (J/kg/m),   C(0) = 3.6
    gap_speed_i = speed_i · C(grade_i) / C(0).   Where grade is NaN use gap_speed = speed.

The grade is already clamped to ±0.30 by §0.5 (`metrics/preprocess.py`); C(i) is positive on that range.
Pure functions, no I/O.
"""

import numpy as np

# METRICS §3 polynomial coefficients, highest power first (for np.polyval).
MINETTI_COEFFS: tuple[float, ...] = (155.4, -30.4, -43.3, 46.3, 19.5, 3.6)
C0 = 3.6  # C(0), J/kg/m


def minetti_cost(grade: np.ndarray) -> np.ndarray:
    """METRICS §3 `C(i)` in J/kg/m for each grade (fraction); NaN stays NaN."""
    return np.polyval(MINETTI_COEFFS, np.asarray(grade, dtype=float))


def gap_speed(speed: np.ndarray, grade: np.ndarray) -> np.ndarray:
    """METRICS §3 `gap_speed = speed · C(grade) / C(0)`; NaN grade → speed, NaN speed → NaN.

    The cost ratio is formed first, so a flat sample (C(0) / C(0) = 1) returns the speed bit for bit.
    """
    speed = np.asarray(speed, dtype=float)
    grade = np.asarray(grade, dtype=float)
    if speed.shape != grade.shape:
        raise ValueError(f"speed {speed.shape} and grade {grade.shape} differ in shape")
    ratio = minetti_cost(grade) / C0
    return np.where(np.isnan(grade), speed, speed * ratio)
