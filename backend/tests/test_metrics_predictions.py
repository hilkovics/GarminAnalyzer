"""Race predictions – METRICS §7.

# METRICS §7
- Riegel: `T2 = T1 · (D2/D1)^1.06` for 5 km, 10 km, 21.0975 km, 42.195 km.
- Daniels VDOT: with `v` in m/min and `t` in minutes: `VO2 = −4.60 + 0.182258·v + 0.000104·v²`,
  `pct = 0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)`, `VDOT = VO2 / pct`.
  Equivalent race time for distance D: solve `t` such that `VDOT(D/t, t) == VDOT` (bisection).
Show both; flag when the reference effort is older than 60 days.
Clarified 2026-09-29 (phase 4, proposed): candidates from the trailing 90 days (if none: all-time); the
reference is the candidate with the highest VDOT. Distances whose reference distance is under 1/4 of the
target are still predicted (flagged `extrapolated`).
Tests: 10 km in 40:00 → VDOT ≈ 51.94 (± 0.05); equivalent half marathon ≈ 1:28:33 (± 10 s).
"""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from training.metrics.predictions import (
    RACE_DISTANCES,
    Prediction,
    Reference,
    is_stale,
    pick_reference,
    predict,
    riegel,
    vdot,
    vdot_race_time,
)

TODAY = date(2026, 9, 29)


def days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def test_race_distances():
    assert RACE_DISTANCES == {"5k": 5000.0, "10k": 10000.0, "half": 21097.5, "marathon": 42195.0}
    assert list(RACE_DISTANCES) == ["5k", "10k", "half", "marathon"]


# ---------------------------------------------------------------- VDOT


def test_vdot_10k_in_40_minutes():
    assert vdot(10000.0, 2400.0) == pytest.approx(51.94, abs=0.05)


def test_vdot_formula_by_hand():
    v, t = 250.0, 40.0  # m/min, min
    vo2 = -4.60 + 0.182258 * v + 0.000104 * v**2
    pct = 0.8 + 0.1894393 * math.exp(-0.012778 * t) + 0.2989558 * math.exp(-0.1932605 * t)
    assert vdot(10000.0, 2400.0) == pytest.approx(vo2 / pct, rel=1e-12)


def test_equivalent_half_marathon():
    t = vdot_race_time(vdot(10000.0, 2400.0), 21097.5)
    assert t == pytest.approx(1 * 3600 + 28 * 60 + 33, abs=10)


@pytest.mark.parametrize(
    ("distance", "time"), [(5000.0, 1200.0), (10000.0, 2400.0), (21097.5, 5400.0), (42195.0, 10800.0)]
)
def test_bisection_round_trip(distance: float, time: float):
    assert vdot_race_time(vdot(distance, time), distance) == pytest.approx(time, abs=1e-3)


def test_race_time_monotone_in_vdot():
    assert vdot_race_time(60.0, 10000.0) < vdot_race_time(50.0, 10000.0)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError):
        vdot(0.0, 100.0)
    with pytest.raises(ValueError):
        vdot(1000.0, 0.0)
    with pytest.raises(ValueError):
        vdot_race_time(0.0, 10000.0)
    with pytest.raises(ValueError):
        vdot_race_time(50.0, -1.0)


# ---------------------------------------------------------------- Riegel


def test_riegel_exponent_exact():
    assert riegel(2400.0, 10000.0, 21097.5) == 2400.0 * (21097.5 / 10000.0) ** 1.06
    assert riegel(1000.0, 1000.0, 2000.0) == pytest.approx(1000.0 * 2**1.06, rel=1e-15)
    assert riegel(1234.0, 5000.0, 5000.0) == 1234.0


# ---------------------------------------------------------------- pick_reference


def candidates(rows: list[tuple[int, float, float, str]]) -> pd.DataFrame:
    """rows: (days ago, distance_m, time_s, source)."""
    return pd.DataFrame(
        {
            "local_date": [days_ago(r[0]) for r in rows],
            "distance_m": [r[1] for r in rows],
            "time_s": [r[2] for r in rows],
            "source": [r[3] for r in rows],
        },
        columns=["local_date", "distance_m", "time_s", "source"],
    )


def test_pick_highest_vdot_in_90_days():
    df = candidates(
        [
            (10, 10000.0, 2400.0, "race"),  # VDOT ≈ 51.94
            (5, 7000.0, 1800.0, "effort"),  # 7 km in 30:00 → VDOT ≈ 46.9
            (89, 5000.0, 1140.0, "effort"),  # 5 km in 19:00 → VDOT ≈ 52.9 (edge, in)
            (90, 5000.0, 1000.0, "race"),  # much faster but outside the window
        ]
    )
    ref = pick_reference(df, today=TODAY)
    assert isinstance(ref, Reference)
    assert ref.distance_m == 5000.0
    assert ref.time_s == 1140.0
    assert ref.local_date == days_ago(89)
    assert ref.source == "effort"
    assert ref.vdot == pytest.approx(vdot(5000.0, 1140.0))


def test_pick_falls_back_to_all_time():
    df = candidates([(200, 10000.0, 2400.0, "race"), (400, 10000.0, 2300.0, "race")])
    ref = pick_reference(df, today=TODAY)
    assert ref is not None
    assert ref.time_s == 2300.0
    assert ref.local_date == days_ago(400)


def test_pick_skips_invalid_rows():
    df = candidates([(1, np.nan, 1800.0, "effort"), (2, 0.0, 1800.0, "effort"), (3, 10000.0, 2400.0, "race")])
    ref = pick_reference(df, today=TODAY)
    assert ref is not None and ref.distance_m == 10000.0


def test_pick_ignores_future_dates():
    df = candidates([(-1, 5000.0, 1000.0, "race"), (3, 10000.0, 2400.0, "race")])
    ref = pick_reference(df, today=TODAY)
    assert ref is not None and ref.distance_m == 10000.0


def test_pick_accepts_timestamp_dates():
    df = candidates([(3, 10000.0, 2400.0, "race")])
    df["local_date"] = pd.to_datetime(df["local_date"])
    ref = pick_reference(df, today=TODAY)
    assert ref is not None and ref.local_date == days_ago(3)
    assert type(ref.local_date) is date


def test_pick_none_without_candidates():
    assert pick_reference(candidates([]), today=TODAY) is None
    assert pick_reference(candidates([(1, np.nan, np.nan, "effort")]), today=TODAY) is None


# ---------------------------------------------------------------- predict


def ref_10k() -> Reference:
    return Reference(
        distance_m=10000.0, time_s=2400.0, local_date=days_ago(3), source="race", vdot=vdot(10000.0, 2400.0)
    )


def test_predict_all_distances_in_order():
    preds = predict(ref_10k())
    assert [p.name for p in preds] == ["5k", "10k", "half", "marathon"]
    assert all(isinstance(p, Prediction) for p in preds)
    by = {p.name: p for p in preds}
    assert by["half"].distance_m == 21097.5
    assert by["half"].daniels_s == pytest.approx(5313, abs=10)
    assert by["half"].riegel_s == riegel(2400.0, 10000.0, 21097.5)
    assert by["10k"].riegel_s == pytest.approx(2400.0)
    assert by["10k"].daniels_s == pytest.approx(2400.0, abs=1e-3)
    assert by["5k"].riegel_s == pytest.approx(2400.0 * 0.5**1.06)


def test_extrapolated_flag():
    by = {p.name: p for p in predict(ref_10k())}
    # 10000 ≥ 21097.5 / 4 = 5274.4, but 10000 < 42195 / 4 = 10548.75
    assert [by[n].extrapolated for n in ("5k", "10k", "half", "marathon")] == [False, False, False, True]
    ref5 = Reference(5000.0, 1200.0, days_ago(3), "effort", vdot(5000.0, 1200.0))
    by = {p.name: p for p in predict(ref5)}
    # 5000 < 21097.5 / 4 = 5274.4 and < 42195 / 4 = 10548.75
    assert [by[n].extrapolated for n in ("5k", "10k", "half", "marathon")] == [False, False, True, True]


def test_extrapolated_exactly_quarter_is_not():
    d = 42195.0 / 4
    ref = Reference(d, 2700.0, days_ago(3), "effort", vdot(d, 2700.0))
    by = {p.name: p for p in predict(ref)}
    assert by["marathon"].extrapolated is False


# ---------------------------------------------------------------- stale


def test_stale_60_vs_61_days():
    base = ref_10k()
    ref60 = Reference(base.distance_m, base.time_s, days_ago(60), base.source, base.vdot)
    ref61 = Reference(base.distance_m, base.time_s, days_ago(61), base.source, base.vdot)
    assert is_stale(ref60, TODAY) is False
    assert is_stale(ref61, TODAY) is True
    assert is_stale(base, TODAY) is False
