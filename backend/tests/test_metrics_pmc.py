"""PMC: daily load, CTL/ATL/TSB, ACWR, monotony/strain, ramp rate, weekly aggregates (METRICS §4).

Every expected value is hand-computed; the derivation is in the comments (exact fractions where the
numbers are not round). Tolerance 1e-9 throughout.
"""

import math
from datetime import date
from fractions import Fraction

import numpy as np
import pandas as pd
import pytest

from training.metrics.pmc import (
    DAILY_LOAD_COLUMNS,
    PMC_COLUMNS,
    WEEKLY_COLUMNS,
    acwr_band,
    daily_load_series,
    pmc,
    weekly_aggregates,
)

TOL = 1e-9
D0 = date(2026, 3, 2)  # a Monday; the first synced day of every synthetic series below


def load_series(loads: list[float], start: date = D0) -> pd.Series:
    index = pd.date_range(start, periods=len(loads), freq="D", name="date")
    return pd.Series(loads, index=index, dtype=float, name="load_total")


def assert_close(actual: pd.Series, expected: list[float | None]) -> None:
    """Element-wise |a − e| ≤ 1e-9; `None` means the value must be NaN."""
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual.to_numpy(dtype=float), expected, strict=True)):
        if e is None:
            assert math.isnan(a), f"day {i}: expected NaN, got {a}"
        else:
            assert a == pytest.approx(e, abs=TOL), f"day {i}: expected {e}, got {a}"


# ---------------------------------------------------------------------------------------------------------
# CTL / ATL / TSB – the hand-computed 10-day series (PLAN phase 2)
# ---------------------------------------------------------------------------------------------------------
# METRICS §4, with CTL[−1] = ATL[−1] = 0 (clarified 2026-09-29):
#   CTL[d] = CTL[d−1] + (L[d] − CTL[d−1]) / 42 = (41·CTL[d−1] + L[d]) / 42
#   ATL[d] = ATL[d−1] + (L[d] − ATL[d−1]) / 7  = (6·ATL[d−1] + L[d]) / 7
#   TSB[d] = CTL[d−1] − ATL[d−1]
#
#   d  L    CTL                                  ATL                            TSB
#   0  100  100/42 = 50/21                       100/7                          0 − 0 = 0
#   1    0  41·(50/21)/42 = 1025/441             6·(100/7)/7 = 600/49           50/21 − 100/7 = −250/21
#   2   50  (41·1025/441 + 50)/42 = 64075/18522  (6·600/49 + 50)/7 = 6050/343   1025/441 − 600/49
#                                                                               = −4375/441
#   3   80  (41·64075/18522 + 80)/42             (6·6050/343 + 80)/7            64075/18522 − 6050/343
#   …   (same recurrence; decimals of the exact fractions below)
TEN_DAY_LOADS = [100.0, 0.0, 50.0, 80.0, 0.0, 120.0, 60.0, 0.0, 90.0, 40.0]
TEN_DAY_CTL = [
    2.380952380952381,  # 50/21
    2.324263038548753,  # 1025/441
    3.4593996328690206,  # 64075/18522
    5.281794879705473,
    5.156037858760104,
    7.890417909742006,
    9.13112224522434,
    8.913714572718998,
    10.84434041622569,
    11.538522787267935,
]
TEN_DAY_ATL = [
    14.285714285714286,  # 100/7
    12.244897959183673,  # 600/49
    17.638483965014576,  # 6050/343
    26.547271970012496,
    22.754804545724994,
    36.64697532490714,
    39.98312170706326,
    34.2712471774828,
    42.23249758069954,
    41.91356935488532,
]
TEN_DAY_TSB = [
    0.0,  # first day: CTL[−1] − ATL[−1] = 0
    -11.904761904761905,  # −250/21
    -9.920634920634921,  # −4375/441
    -14.179084332145557,
    -21.265477090307023,
    -17.59876668696489,
    -28.756557415165133,
    -30.851999461838922,
    -25.357532604763797,
    -31.38815716447385,
]
# ramp_rate[d] = CTL[d] − CTL[d−7], NaN for d < 7:
#   d7: 8.913714572718998 − 2.380952380952381 = 6.532762191766617  (> 6 → warning)
#   d8: 10.84434041622569 − 2.324263038548753 = 8.520077377676937
#   d9: 11.538522787267935 − 3.4593996328690206 = 8.079123154398914
TEN_DAY_RAMP: list[float | None] = [None] * 7 + [6.532762191766617, 8.520077377676937, 8.079123154398914]


def closed_form(loads: list[float], tau: int) -> list[Fraction]:
    """EWMA as an explicit convolution: X[d] = Σ_{k≤d} L[k] · (1/τ) · ((τ−1)/τ)^(d−k) (exact)."""
    q = Fraction(tau - 1, tau)
    return [
        sum((Fraction(loads[k]) / tau * q ** (d - k) for k in range(d + 1)), Fraction(0))
        for d in range(len(loads))
    ]


def test_ten_day_series_ctl_atl_tsb() -> None:
    out = pmc(load_series(TEN_DAY_LOADS))
    assert list(out.columns) == list(PMC_COLUMNS)
    assert_close(out["ctl"], TEN_DAY_CTL)
    assert_close(out["atl"], TEN_DAY_ATL)
    assert_close(out["tsb"], TEN_DAY_TSB)
    assert out["tsb"].iloc[0] == 0.0


def test_ten_day_table_matches_exact_closed_form() -> None:
    # Guards the literal table above against typos: same numbers from the convolution form in Fractions.
    ctl = closed_form(TEN_DAY_LOADS, 42)
    atl = closed_form(TEN_DAY_LOADS, 7)
    assert ctl[0] == Fraction(50, 21) and ctl[1] == Fraction(1025, 441) and ctl[2] == Fraction(64075, 18522)
    assert atl[0] == Fraction(100, 7) and atl[1] == Fraction(600, 49) and atl[2] == Fraction(6050, 343)
    tsb = [Fraction(0)] + [ctl[d - 1] - atl[d - 1] for d in range(1, 10)]
    assert tsb[1] == Fraction(-250, 21) and tsb[2] == Fraction(-4375, 441)
    for d in range(10):
        assert float(ctl[d]) == pytest.approx(TEN_DAY_CTL[d], abs=TOL)
        assert float(atl[d]) == pytest.approx(TEN_DAY_ATL[d], abs=TOL)
        assert float(tsb[d]) == pytest.approx(TEN_DAY_TSB[d], abs=TOL)
    for d in range(7, 10):
        assert float(ctl[d] - ctl[d - 7]) == pytest.approx(TEN_DAY_RAMP[d], abs=TOL)


def test_ten_day_series_windows_need_full_history() -> None:
    out = pmc(load_series(TEN_DAY_LOADS))
    # ACWR needs 28 days (chronic window), monotony/strain need the 28-day training-day count → all NaN.
    assert out["acwr"].isna().all()
    assert out["monotony"].isna().all()
    assert out["strain"].isna().all()
    assert all(band is None for band in out["acwr_band"])
    assert_close(out["ramp_rate"], TEN_DAY_RAMP)
    assert out["ramp_warning"].tolist() == [False] * 7 + [True, True, True]
    assert out["ramp_warning"].dtype == bool


def test_first_day_tsb_is_zero_and_single_day_series() -> None:
    out = pmc(load_series([250.0]))
    assert out["ctl"].iloc[0] == pytest.approx(250 / 42, abs=TOL)
    assert out["atl"].iloc[0] == pytest.approx(250 / 7, abs=TOL)
    assert out["tsb"].iloc[0] == 0.0
    assert math.isnan(out["ramp_rate"].iloc[0])
    assert not out["ramp_warning"].iloc[0]


# ---------------------------------------------------------------------------------------------------------
# ramp_rate / ramp_warning on a constant series
# ---------------------------------------------------------------------------------------------------------
# Constant load L from day 0, q = 41/42: CTL[d] = L·(1 − q^(d+1)), so
#   ramp[d] = CTL[d] − CTL[d−7] = L·(q^(d−6) − q^(d+1)) = L · q^(d−6) · (1 − q^7).
#   L = 40: ramp[7] = 40·q·(1 − q^7)  = 6.061097453838367  (> 6 → warning)
#           ramp[8] = 40·q²·(1 − q^7) = 5.9167856096993585 (≤ 6 → no warning), decreasing afterwards.
# Constant load also gives acute = chronic = 40 → ACWR 1.0 (d ≥ 27) and std7 = 0 → monotony NaN.


def test_ramp_rate_constant_load_crosses_threshold() -> None:
    out = pmc(load_series([40.0] * 35))
    q = 41 / 42
    expected: list[float | None] = [None] * 7 + [40 * q ** (d - 6) * (1 - q**7) for d in range(7, 35)]
    assert_close(out["ramp_rate"], expected)
    assert out["ramp_rate"].iloc[7] == pytest.approx(6.061097453838367, abs=TOL)
    assert out["ramp_rate"].iloc[8] == pytest.approx(5.9167856096993585, abs=TOL)
    assert out["ramp_warning"].tolist() == [False] * 7 + [True] + [False] * 27
    assert_close(out["acwr"], [None] * 27 + [1.0] * 8)
    assert out["acwr_band"].tolist() == [None] * 27 + ["optimal"] * 8
    assert out["monotony"].isna().all()  # std7 == 0 every day
    assert out["strain"].isna().all()


def test_ramp_warning_is_strictly_greater_than_six() -> None:
    # Loads chosen so every CTL is exact in binary floating point:
    #   CTL[0] = 0 + (42 − 0)/42 = 1;  CTL[1..6] = 1 + (1 − 1)/42 = 1;  CTL[7] = 1 + (253 − 1)/42 = 1 + 6 = 7
    #   → ramp[7] = 7 − 1 = 6.0 exactly → not > 6 → no warning.
    at_six = pmc(load_series([42.0] + [1.0] * 6 + [253.0]))
    assert at_six["ctl"].tolist() == [1.0] * 7 + [7.0]
    assert at_six["ramp_rate"].iloc[7] == 6.0
    assert not at_six["ramp_warning"].iloc[7]
    # One more point on day 7: CTL[7] = 1 + 253/42 → ramp = 253/42 = 6.0238… → warning.
    above = pmc(load_series([42.0] + [1.0] * 6 + [254.0]))
    assert above["ramp_rate"].iloc[7] == pytest.approx(253 / 42, abs=TOL)
    assert above["ramp_warning"].iloc[7]


# ---------------------------------------------------------------------------------------------------------
# ACWR, monotony, strain – 42-day block series with every band
# ---------------------------------------------------------------------------------------------------------
# Weeks 1–4 (days 0–27): P = [60, 0, 60, 0, 60, 0, 100] (sum 280, mean 40)
# Week 5  (days 28–34): Q = 2·P = [120, 0, 120, 0, 120, 0, 200] (sum 560, mean 80)
# Week 6  (days 35–41): rest, all 0.
# acute = sum(L[d−6..d]) / 7, chronic = sum(L[d−27..d]) / 28, ACWR = acute / chronic = 4 · S7 / S28.
P = [60.0, 0.0, 60.0, 0.0, 60.0, 0.0, 100.0]
Q = [2 * x for x in P]
BLOCKS = P * 4 + Q + [0.0] * 7

# monotony = mean7 / std7 with the population std (ddof = 0):
#   window P: deviations 20, −40, 20, −40, 20, −40, 60 → Σ² = 9600 → std = √(9600/7)
#             monotony = 40 / √(9600/7) = √(7/6)  (ddof = 1 would give 40 / √(9600/6) = 1.0 exactly)
#   window Q = 2·P: monotony is scale-invariant → √(7/6)
#   d30 window [0, 60, 0, 100, 120, 0, 120]: S7 = 400, Σx² = 42400
#             var = 42400/7 − (400/7)² = 136800/49 → monotony = (400/7) / (√136800/7) = 400/√136800
#   d32 window [0, 100, 120, 0, 120, 0, 120]: S7 = 460, Σx² = 53200
#             var = 53200/7 − (460/7)² = 160800/49 → monotony = 460/√160800
#   d35 window [0, 120, 0, 120, 0, 200, 0]: S7 = 440, Σx² = 68800
#             var = 68800/7 − (440/7)² = 288000/49 → monotony = 440/√288000
#   d40 window [200, 0, 0, 0, 0, 0, 0]: S7 = 200, Σx² = 40000
#             var = 40000/7 − (200/7)² = 240000/49 → monotony = 200/√240000 = 1/√6
# strain = sum7 · monotony. Every checkpoint from d27 on has ≥ 4 training days in its 28-day window.
BLOCK_CHECKPOINTS = {
    # d: (ACWR, band, monotony, strain); None = NaN
    26: (None, None, None, None),  # only 27 days of history
    # d27: S7 = 280, S28 = 1120 → 4·280/1120 = 1.0
    27: (1.0, "optimal", math.sqrt(7 / 6), 280 * math.sqrt(7 / 6)),
    # d30: S7 = 0+60+0+100 + 120+0+120 = 400; S28 = days 3..30 = (1120 − 120) + 240 = 1240 → 1600/1240 = 40/31
    30: (40 / 31, "optimal", 400 / math.sqrt(136800), 400 * 400 / math.sqrt(136800)),
    # d32: S7 = 0+100 + 120+0+120+0+120 = 460; S28 = (1120 − 180) + 360 = 1300 → 1840/1300 = 92/65
    32: (92 / 65, "caution", 460 / math.sqrt(160800), 460 * 460 / math.sqrt(160800)),
    # d34: S7 = 560; S28 = 280·3 + 560 = 1400 → 2240/1400 = 1.6
    34: (1.6, "danger", math.sqrt(7 / 6), 560 * math.sqrt(7 / 6)),
    # d35: S7 = 560 − 120 + 0 = 440; S28 = 1400 − 60 + 0 = 1340 → 1760/1340 = 88/67 = 1.3134…
    35: (88 / 67, "caution", 440 / math.sqrt(288000), 440 * 440 / math.sqrt(288000)),
    # d40: S7 = 200 (day 34); S28 = days 13..40 = (840 − 180) + 560 = 1220 → 800/1220 = 40/61
    40: (40 / 61, "under", 1 / math.sqrt(6), 200 / math.sqrt(6)),
    # d41: S7 = 0; S28 = days 14..41 = 280 + 280 + 560 = 1120 → ACWR 0 → under; rest week → std7 = 0 → NaN
    41: (0.0, "under", None, None),
}


@pytest.mark.parametrize("day", sorted(BLOCK_CHECKPOINTS))
def test_block_series_acwr_monotony_strain(day: int) -> None:
    out = pmc(load_series(BLOCKS))
    acwr, band, monotony, strain = BLOCK_CHECKPOINTS[day]
    row = out.iloc[day]
    for name, expected in (("acwr", acwr), ("monotony", monotony), ("strain", strain)):
        if expected is None:
            assert math.isnan(row[name]), f"{name} on day {day}"
        else:
            assert row[name] == pytest.approx(expected, abs=TOL), f"{name} on day {day}"
    assert row["acwr_band"] == band


def test_block_series_full_window_nan_rules() -> None:
    out = pmc(load_series(BLOCKS))
    # acute is available from day 6, but ACWR needs the 28-day chronic window → NaN on days 0..26.
    assert out["acwr"].iloc[:27].isna().all()
    assert out["acwr"].iloc[27:].notna().all()
    # mean7/std7 exist from day 6, but the 28-day training-day count only from day 27.
    assert out["monotony"].iloc[:27].isna().all()
    assert out["strain"].iloc[:27].isna().all()
    assert out["monotony"].iloc[27:35].notna().all()


def test_monotony_uses_population_std() -> None:
    out = pmc(load_series(BLOCKS))
    assert out["monotony"].iloc[27] == pytest.approx(1.0801234497346435, abs=TOL)  # √(7/6)
    assert out["monotony"].iloc[27] != pytest.approx(1.0, abs=1e-3)  # what ddof = 1 would give


# ---------------------------------------------------------------------------------------------------------
# monotony: training-day count and std7 == 0
# ---------------------------------------------------------------------------------------------------------
# days 0–6: 50 each (7 training days); days 7–29: 0; day 30: 80, 31: 0, 32: 40, 33: 0, 34: 60, 35: 30.
SPARSE = [50.0] * 7 + [0.0] * 23 + [80.0, 0.0, 40.0, 0.0, 60.0, 30.0]


def test_monotony_training_day_rules() -> None:
    out = pmc(load_series(SPARSE))
    # d10: window 4..10 = [50, 50, 50, 0, 0, 0, 0] has std7 ≠ 0, but < 28 days of history → NaN.
    assert math.isnan(out["monotony"].iloc[10])
    # d27: 28-day window 0..27 has 7 training days, but the last 7 days are all 0 → std7 == 0 → NaN.
    assert math.isnan(out["monotony"].iloc[27])
    assert math.isnan(out["strain"].iloc[27])
    # d34: training days in 7..34 = {30, 32, 34} → 3 < 4 → NaN (std7 of [0, 0, 80, 0, 40, 0, 60] ≠ 0).
    assert math.isnan(out["monotony"].iloc[34])
    assert math.isnan(out["strain"].iloc[34])
    # …while ACWR on d34 is defined: S7 = 180, S28 = 180 → chronic 6.43 ≥ 5 → 4·180/180 = 4.0 → danger.
    assert out["acwr"].iloc[34] == pytest.approx(4.0, abs=TOL)
    assert out["acwr_band"].iloc[34] == "danger"
    # d35: training days in 8..35 = {30, 32, 34, 35} → 4 → defined.
    #   window 29..35 = [0, 80, 0, 40, 0, 60, 30]: S7 = 210, mean 30, Σx² = 12500
    #   var = 12500/7 − 30² = 6200/7 → monotony = 30 / √(6200/7); strain = 210 · monotony
    monotony = 30 / math.sqrt(6200 / 7)
    assert out["monotony"].iloc[35] == pytest.approx(monotony, abs=TOL)
    assert out["monotony"].iloc[35] == pytest.approx(1.0080322575483707, abs=TOL)
    assert out["strain"].iloc[35] == pytest.approx(210 * monotony, abs=TOL)


def test_monotony_nan_for_constant_window_despite_float_residue() -> None:
    # 28 days of 33.3: 28 training days, the last 7 loads are identical → std7 == 0 → NaN.
    # (A naive float std of seven 33.3 values is ~7e-15, which would give a monotony of ~5e15.)
    out = pmc(load_series([33.3] * 28))
    assert math.isnan(out["monotony"].iloc[27])
    assert math.isnan(out["strain"].iloc[27])
    assert out["acwr"].iloc[27] == pytest.approx(1.0, abs=TOL)


# ---------------------------------------------------------------------------------------------------------
# ACWR: chronic < 5 and exact band edges
# ---------------------------------------------------------------------------------------------------------
# 28 days, L[0] = x, L[21] = y, rest 0. On d27: acute = y/7, chronic = (x + y)/28.


def edge_series(x: float, y: float) -> pd.Series:
    return load_series([x] + [0.0] * 20 + [y] + [0.0] * 6)


def test_acwr_nan_when_chronic_below_five() -> None:
    below = pmc(edge_series(0.0, 139.0)).iloc[27]  # chronic = 139/28 = 4.96… < 5
    assert math.isnan(below["acwr"])
    assert below["acwr_band"] is None
    at = pmc(edge_series(0.0, 140.0)).iloc[27]  # chronic = 140/28 = 5.0 exactly → defined; 20/5 = 4
    assert at["acwr"] == pytest.approx(4.0, abs=TOL)
    assert at["acwr_band"] == "danger"


@pytest.mark.parametrize(
    ("x", "y", "acwr", "band"),
    [
        # chronic = 560/28 = 20 exactly; acute = y/7
        (449.0, 111.0, 111 / 140, "under"),  # 0.7928…
        (448.0, 112.0, 0.8, "optimal"),  # 16/20: lower edge belongs to optimal
        (379.0, 181.0, 181 / 140, "optimal"),  # 1.2928…
        (378.0, 182.0, 1.3, "caution"),  # 26/20: 1.3 belongs to caution
        (350.0, 210.0, 1.5, "caution"),  # 30/20: 1.5 still caution
        (349.0, 211.0, 211 / 140, "danger"),  # 1.5071…
    ],
)
def test_acwr_band_edges_in_series(x: float, y: float, acwr: float, band: str) -> None:
    row = pmc(edge_series(x, y)).iloc[27]
    assert row["acwr"] == pytest.approx(acwr, abs=TOL)
    assert row["acwr_band"] == band


@pytest.mark.parametrize(
    ("value", "band"),
    [
        (0.0, "under"),
        (0.7999999999, "under"),
        (0.8, "optimal"),
        (1.0, "optimal"),
        (1.2999999999, "optimal"),
        (1.3, "caution"),
        (1.4, "caution"),
        (1.5, "caution"),
        (1.5000000001, "danger"),
        (4.0, "danger"),
        (float("nan"), None),
        (None, None),
    ],
)
def test_acwr_band_helper(value: float | None, band: str | None) -> None:
    assert acwr_band(value) == band


# ---------------------------------------------------------------------------------------------------------
# pmc input contract
# ---------------------------------------------------------------------------------------------------------


def test_pmc_keeps_a_date_object_index() -> None:
    days = [date(2026, 3, 30), date(2026, 3, 31), date(2026, 4, 1)]
    out = pmc(pd.Series([100.0, 0.0, 50.0], index=days))
    assert list(out.index) == days
    assert_close(out["ctl"], TEN_DAY_CTL[:3])
    assert_close(out["tsb"], TEN_DAY_TSB[:3])


def test_pmc_rejects_gaps_and_nan() -> None:
    gap = pd.Series([10.0, 20.0], index=pd.to_datetime(["2026-03-02", "2026-03-04"]))
    with pytest.raises(ValueError, match="consecutive"):
        pmc(gap)
    with pytest.raises(ValueError, match="NaN"):
        pmc(load_series([10.0, float("nan"), 5.0]))


def test_pmc_empty_series() -> None:
    out = pmc(pd.Series([], index=pd.DatetimeIndex([]), dtype=float))
    assert out.empty
    assert list(out.columns) == list(PMC_COLUMNS)


def test_pmc_band_values_are_none_not_nan() -> None:
    out = pmc(load_series(BLOCKS))
    assert out["acwr_band"].dtype == object
    assert out["acwr_band"].iloc[0] is None


# ---------------------------------------------------------------------------------------------------------
# daily_load_series
# ---------------------------------------------------------------------------------------------------------


def activities(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["local_date", "sport", "load_primary"])


def test_daily_load_series_sums_splits_and_fills_rest_days() -> None:
    acts = activities(
        [
            (date(2026, 3, 1), "run", 999.0),  # before start → ignored
            (date(2026, 3, 2), "run", 50.0),
            (date(2026, 3, 2), "run", 25.0),  # second run on the same day
            (date(2026, 3, 2), "bike", 30.5),
            (date(2026, 3, 2), "other", 20.0),  # total only
            (date(2026, 3, 4), "run", None),  # null load → 0
            (date(2026, 3, 4), "bike", 40.0),
            (date(2026, 3, 5), "bike", float("nan")),  # null load → 0
            (date(2026, 3, 8), "run", 999.0),  # after end → ignored
        ]
    )
    out = daily_load_series(acts, date(2026, 3, 2), date(2026, 3, 7))
    assert isinstance(out.index, pd.DatetimeIndex)
    assert [d.date() for d in out.index] == [date(2026, 3, d) for d in range(2, 8)]
    assert list(out.columns) == list(DAILY_LOAD_COLUMNS)
    assert all(out[c].dtype == np.float64 for c in out.columns)
    # 03-02: total 50 + 25 + 30.5 + 20 = 125.5, run 75, bike 30.5; 03-04: total 40 (run null), bike 40.
    assert out["load_total"].tolist() == [125.5, 0.0, 40.0, 0.0, 0.0, 0.0]
    assert out["load_run"].tolist() == [75.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert out["load_bike"].tolist() == [30.5, 0.0, 40.0, 0.0, 0.0, 0.0]


def test_daily_load_series_empty_and_single_day() -> None:
    empty = daily_load_series(activities([]), date(2026, 3, 2), date(2026, 3, 4))
    assert len(empty) == 3
    assert (empty.to_numpy() == 0.0).all()
    one = daily_load_series(
        activities([(date(2026, 3, 2), "bike", 12.0)]), date(2026, 3, 2), date(2026, 3, 2)
    )
    assert one.to_dict("list") == {"load_total": [12.0], "load_run": [0.0], "load_bike": [12.0]}


def test_daily_load_series_feeds_pmc() -> None:
    acts = activities([(date(2026, 3, 2), "run", 100.0), (date(2026, 3, 4), "bike", 50.0)])
    daily = daily_load_series(acts, date(2026, 3, 2), date(2026, 3, 4))
    out = pmc(daily["load_total"])
    assert_close(out["ctl"], TEN_DAY_CTL[:3])  # loads 100, 0, 50 = start of the 10-day series
    assert out.index.equals(daily.index)


# ---------------------------------------------------------------------------------------------------------
# weekly_aggregates
# ---------------------------------------------------------------------------------------------------------


def tiz(z1: int, z2: int, z3: int, z4: int, z5: int) -> dict[str, int]:
    return {"1": z1, "2": z2, "3": z3, "4": z4, "5": z5}


WEEK_ROWS = [
    # 2025-12-28 is a Sunday → ISO 2025-W52 (Monday 2025-12-22)
    (date(2025, 12, 28), "run", 60.0, 3600.0, 12000.0, 100.0, tiz(600, 2400, 300, 200, 100)),
    # 2025-12-29 is a Monday → ISO 2026-W01, which runs to Sunday 2026-01-04
    (date(2025, 12, 29), "run", 50.0, 3000.0, 10000.0, 50.0, tiz(1000, 1000, 500, 300, 200)),
    (date(2026, 1, 1), "bike", 80.0, 7200.0, 60000.0, 500.0, tiz(3600, 2400, 1200, 0, 0)),
    (date(2026, 1, 4), "run", None, 1800.0, 5000.0, None, None),
    (date(2026, 1, 4), "other", 20.0, 1200.0, None, None, tiz(0, 0, 0, 0, 0)),
    # 2026-01-05 is a Monday → ISO 2026-W02
    (date(2026, 1, 5), "other", 10.0, 900.0, None, None, None),
]
WEEK_COLUMNS_IN = [
    "local_date",
    "sport",
    "load_primary",
    "duration_s",
    "distance_m",
    "elev_gain_m",
    "time_in_hr_zone",
]

# Per row: (week_start, iso_year, iso_week, sport), (n, load, duration_s, distance_m, elev_gain_m),
# (tiz_1..tiz_5), (pol_low, pol_mid, pol_high) with pol = (Z1+Z2, Z3, Z4+Z5) / Σ zones, None if Σ is 0.
W52, W01, W02 = date(2025, 12, 22), date(2025, 12, 29), date(2026, 1, 5)
NO_ZONES = (0, 0, 0, 0, 0)
NO_SHARES = (None, None, None)
EXPECTED_WEEKS = [
    # W52: 3000/3600, 300/3600, 300/3600
    (
        (W52, 2025, 52, "run"),
        (1, 60.0, 3600.0, 12000.0, 100.0),
        (600, 2400, 300, 200, 100),
        (5 / 6, 1 / 12, 1 / 12),
    ),
    (
        (W52, 2025, 52, "all"),
        (1, 60.0, 3600.0, 12000.0, 100.0),
        (600, 2400, 300, 200, 100),
        (5 / 6, 1 / 12, 1 / 12),
    ),
    # W01 run: 2 runs, one with null load / elevation / zones → 2000/3000, 500/3000, 500/3000
    (
        (W01, 2026, 1, "run"),
        (2, 50.0, 4800.0, 15000.0, 50.0),
        (1000, 1000, 500, 300, 200),
        (2 / 3, 1 / 6, 1 / 6),
    ),
    # W01 bike: 6000/7200, 1200/7200, 0
    (
        (W01, 2026, 1, "bike"),
        (1, 80.0, 7200.0, 60000.0, 500.0),
        (3600, 2400, 1200, 0, 0),
        (5 / 6, 1 / 6, 0.0),
    ),
    # W01 other: all zones 0 → no polarization; null distance / elevation → 0
    ((W01, 2026, 1, "other"), (1, 20.0, 1200.0, 0.0, 0.0), NO_ZONES, NO_SHARES),
    # W01 all: zones 4600, 3400, 1700, 300, 200 (Σ 10200) → 8000/10200, 1700/10200, 500/10200
    (
        (W01, 2026, 1, "all"),
        (4, 150.0, 13200.0, 75000.0, 550.0),
        (4600, 3400, 1700, 300, 200),
        (40 / 51, 1 / 6, 5 / 102),
    ),
    # W02: one "other" without zones
    ((W02, 2026, 2, "other"), (1, 10.0, 900.0, 0.0, 0.0), NO_ZONES, NO_SHARES),
    ((W02, 2026, 2, "all"), (1, 10.0, 900.0, 0.0, 0.0), NO_ZONES, NO_SHARES),
]


def test_weekly_aggregates_iso_weeks_sports_and_polarization() -> None:
    out = weekly_aggregates(pd.DataFrame(WEEK_ROWS, columns=WEEK_COLUMNS_IN))
    assert list(out.columns) == list(WEEKLY_COLUMNS)
    assert len(out) == len(EXPECTED_WEEKS)
    for (_, row), (key, totals, zones, shares) in zip(out.iterrows(), EXPECTED_WEEKS, strict=True):
        week_start, iso_year, iso_week, sport = key
        n, load, duration, distance, elev = totals
        assert row["week_start"] == week_start and type(row["week_start"]) is date
        assert (row["iso_year"], row["iso_week"], row["sport"]) == (iso_year, iso_week, sport)
        assert row["n_activities"] == n
        assert row["load"] == pytest.approx(load, abs=TOL)
        assert row["duration_s"] == pytest.approx(duration, abs=TOL)
        assert row["distance_m"] == pytest.approx(distance, abs=TOL)
        assert row["elev_gain_m"] == pytest.approx(elev, abs=TOL)
        assert [row[f"tiz_{z}"] for z in range(1, 6)] == pytest.approx(list(zones), abs=TOL)
        for name, share in zip(("pol_low", "pol_mid", "pol_high"), shares, strict=True):
            if share is None:
                assert row[name] is None, f"{name} {week_start} {sport}"
            else:
                assert row[name] == pytest.approx(share, abs=TOL), f"{name} {week_start} {sport}"


def test_weekly_aggregates_shares_sum_to_one() -> None:
    out = weekly_aggregates(pd.DataFrame(WEEK_ROWS, columns=WEEK_COLUMNS_IN))
    with_zones = out[out["pol_low"].notna()]
    total = with_zones["pol_low"] + with_zones["pol_mid"] + with_zones["pol_high"]
    assert total.to_numpy(dtype=float) == pytest.approx([1.0] * len(with_zones), abs=TOL)


@pytest.mark.parametrize(
    ("day", "week_start", "iso_year", "iso_week"),
    [
        (date(2025, 12, 29), date(2025, 12, 29), 2026, 1),  # Monday belongs to next ISO year
        (date(2026, 1, 4), date(2025, 12, 29), 2026, 1),  # Sunday closes the week
        (date(2024, 12, 31), date(2024, 12, 30), 2025, 1),
        (date(2021, 1, 3), date(2020, 12, 28), 2020, 53),  # Sunday in January still in week 53
        (date(2026, 3, 2), date(2026, 3, 2), 2026, 10),
    ],
)
def test_weekly_aggregates_iso_week_of_date(
    day: date, week_start: date, iso_year: int, iso_week: int
) -> None:
    row = (day, "run", 10.0, 600.0, 2000.0, 5.0, None)
    out = weekly_aggregates(pd.DataFrame([row], columns=WEEK_COLUMNS_IN))
    assert out["sport"].tolist() == ["run", "all"]
    assert out["week_start"].tolist() == [week_start, week_start]
    assert out["iso_year"].tolist() == [iso_year, iso_year]
    assert out["iso_week"].tolist() == [iso_week, iso_week]


def test_weekly_aggregates_empty() -> None:
    out = weekly_aggregates(pd.DataFrame([], columns=WEEK_COLUMNS_IN))
    assert out.empty
    assert list(out.columns) == list(WEEKLY_COLUMNS)
