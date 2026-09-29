"""Wellness baselines and sleep debt (METRICS §8, §9 sleep_debt_7; phase 5 clarifications).

Synthetic date-indexed frames with hand-computed answers. Tolerance 1e-9 throughout.
"""

import math
from collections.abc import Sequence
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from training.analysis.wellness import (
    BASELINE_DAYS,
    BASELINE_FIELDS,
    MIN_BASELINE_VALUES,
    baselines,
    sleep_debt_7,
    with_baselines,
)

TOL = 1e-9
D0 = date(2026, 3, 2)
H = 3600.0


def days(offsets: Sequence[int], start: date = D0) -> list[date]:
    return [start + timedelta(days=int(o)) for o in offsets]


def daily(values: Sequence[float | None], start: date = D0) -> list[date]:
    return days(range(len(values)), start)


def frame(offsets: Sequence[int], **columns: Sequence[float | None]) -> pd.DataFrame:
    """Wellness frame indexed by `datetime.date` (D0 + offset), columns float with NaN for None."""
    data = {k: [np.nan if v is None else v for v in vals] for k, vals in columns.items()}
    return pd.DataFrame(data, index=pd.Index(days(offsets), name="date"), dtype=float)


def series(offsets: Sequence[int], values: Sequence[float | None]) -> pd.Series:
    return pd.Series(
        [np.nan if v is None else v for v in values], index=pd.Index(days(offsets), name="date"), dtype=float
    )


def value_at(s: pd.Series, offset: int) -> float:
    return float(s.loc[D0 + timedelta(days=offset)])


def assert_nan(x: float) -> None:
    assert math.isnan(x), f"expected NaN, got {x}"


# ---------------------------------------------------------------------------------------------------------
# constants and shape


def test_constants() -> None:
    assert BASELINE_FIELDS == ("rhr", "sleep_s", "sleep_score", "body_battery_wake")
    assert BASELINE_DAYS == 28
    assert MIN_BASELINE_VALUES == 7


def test_output_columns_and_index_with_missing_input_columns() -> None:
    # Only rhr given; the other fields count as all-NaN. Sparse, unsorted index is kept as is.
    wellness = frame([5, 0, 40], rhr=[50.0, 51.0, 52.0])
    out = baselines(wellness)
    expected_cols = [f"{f}_{s}" for f in BASELINE_FIELDS for s in ("median28", "mad28")]
    assert sorted(out.columns) == sorted(expected_cols)
    assert list(out.index) == list(wellness.index)
    for f in ("sleep_s", "sleep_score", "body_battery_wake"):
        assert out[f"{f}_median28"].isna().all()
        assert out[f"{f}_mad28"].isna().all()


def test_empty_input() -> None:
    out = baselines(pd.DataFrame(index=pd.Index([], name="date")))
    assert len(out) == 0
    assert len(out.columns) == 2 * len(BASELINE_FIELDS)


# ---------------------------------------------------------------------------------------------------------
# baselines – window D−28 … D−1


def test_baseline_excludes_current_day() -> None:
    # Days 0..27 rhr = 50, day 28 rhr = 80 → day 28's baseline is 50 / MAD 0 (its own value is excluded).
    rhr = [50.0] * 28 + [80.0, 50.0]
    out = baselines(frame(range(30), rhr=rhr))
    assert value_at(out["rhr_median28"], 28) == pytest.approx(50.0, abs=TOL)
    assert value_at(out["rhr_mad28"], 28) == pytest.approx(0.0, abs=TOL)
    # Day 29: window 1..28 = 27 × 50 and one 80 → median 50; |dev| = 27 × 0, one 30 → MAD 0.
    assert value_at(out["rhr_median28"], 29) == pytest.approx(50.0, abs=TOL)


def test_baseline_window_is_exactly_28_days() -> None:
    # value_i = i for days 0..29. Day 29: window = days 1..28 → values 1..28 → median 14.5.
    # |x − 14.5| = 0.5, 0.5, 1.5, 1.5, …, 13.5, 13.5 → median = (6.5 + 7.5) / 2 = 7.0.
    vals = [float(i) for i in range(30)]
    out = baselines(frame(range(30), sleep_score=vals))
    assert value_at(out["sleep_score_median28"], 29) == pytest.approx(14.5, abs=TOL)
    assert value_at(out["sleep_score_mad28"], 29) == pytest.approx(7.0, abs=TOL)
    # Day 28: window = days 0..27 → median 13.5.
    assert value_at(out["sleep_score_median28"], 28) == pytest.approx(13.5, abs=TOL)


def test_fewer_than_seven_values_is_null() -> None:
    vals = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0]
    out = baselines(frame(range(8), body_battery_wake=vals))
    med = out["body_battery_wake_median28"]
    for d in range(7):  # day d has d prior values (0..6) → null
        assert_nan(value_at(med, d))
        assert_nan(value_at(out["body_battery_wake_mad28"], d))
    # Day 7: 7 prior values 10..70 → median 40; |dev| = 30,20,10,0,10,20,30 → MAD 20.
    assert value_at(med, 7) == pytest.approx(40.0, abs=TOL)
    assert value_at(out["body_battery_wake_mad28"], 7) == pytest.approx(20.0, abs=TOL)


def test_nan_values_do_not_count_as_valid() -> None:
    # 10 days in window but only 6 valid (4 NaN) → null.
    vals: list[float | None] = [50.0, None, 51.0, None, 52.0, None, 53.0, None, 54.0, 55.0, 60.0]
    out = baselines(frame(range(11), rhr=vals))
    assert_nan(value_at(out["rhr_median28"], 10))


def test_gaps_in_index_use_calendar_days() -> None:
    # Values i on days 0..9, then rows on day 30 and day 35 only (sparse index).
    offsets = [*range(10), 30, 35]
    vals = [float(i) for i in range(10)] + [99.0, 99.0]
    out = baselines(frame(offsets, rhr=vals))
    # Day 30: window = days 2..29 → valid values 2..9 (8 values) → median 5.5;
    # |x − 5.5| = 3.5, 2.5, 1.5, 0.5, 0.5, 1.5, 2.5, 3.5 → MAD 2.0. (A row-based window would give 4.5.)
    assert value_at(out["rhr_median28"], 30) == pytest.approx(5.5, abs=TOL)
    assert value_at(out["rhr_mad28"], 30) == pytest.approx(2.0, abs=TOL)
    # Day 35: window = days 7..34 → values 7, 8, 9, 99 (4 values) → null.
    assert_nan(value_at(out["rhr_median28"], 35))


def test_mad_hand_computed_is_raw() -> None:
    # Window values (days 0..6): 1, 2, 3, 4, 100, 6, 7 → sorted 1,2,3,4,6,7,100 → median 4.
    # |x − 4| = 3, 2, 1, 0, 96, 2, 3 → sorted 0,1,2,2,3,3,96 → MAD 2 (raw, no 1.4826 scaling).
    vals = [1.0, 2.0, 3.0, 4.0, 100.0, 6.0, 7.0, 0.0]
    out = baselines(frame(range(8), sleep_s=vals))
    assert value_at(out["sleep_s_median28"], 7) == pytest.approx(4.0, abs=TOL)
    assert value_at(out["sleep_s_mad28"], 7) == pytest.approx(2.0, abs=TOL)


def test_accepts_nullable_and_object_columns() -> None:
    idx = pd.Index(daily([0] * 8), name="date")
    wellness = pd.DataFrame(
        {"rhr": pd.array([50, 51, 52, 53, 54, 55, 56, None], dtype="Int64")},
        index=idx,
    )
    out = baselines(wellness)
    assert value_at(out["rhr_median28"], 7) == pytest.approx(53.0, abs=TOL)


def test_duplicate_dates_raise() -> None:
    wellness = frame([0, 0], rhr=[50.0, 51.0])
    with pytest.raises(ValueError):
        baselines(wellness)


# ---------------------------------------------------------------------------------------------------------
# sleep_debt_7 – METRICS §9


def test_sleep_debt_full_week_null_median_uses_8h() -> None:
    # 7 nights of 7 h, median null → each term 8 h − 7 h = 1 h → 7 h = 25200 s on day 6; days 0..4 null.
    sleep = series(range(7), [7 * H] * 7)
    median = series(range(7), [None] * 7)
    out = sleep_debt_7(sleep, median)
    assert list(out.index) == list(sleep.index)
    assert value_at(out, 6) == pytest.approx(7 * H, abs=TOL)
    for d in range(4):
        assert_nan(value_at(out, d))
    # Day 4: nights 0..4 valid (5 of 7 calendar nights; D−6, D−5 lie before the data) → 5 h · 7/5 = 7 h.
    assert value_at(out, 4) == pytest.approx(7 * H, abs=TOL)


def test_sleep_debt_uses_max_of_8h_and_nightly_median() -> None:
    # median 9 h → term 9 h − 7 h = 2 h; median 7 h → floor 8 h → 1 h. Surplus offsets: 9 h slept, 8 h floor.
    sleep = series(range(7), [7 * H, 7 * H, 7 * H, 7 * H, 7 * H, 7 * H, 9 * H])
    median = series(range(7), [9 * H, 9 * H, 9 * H, 7 * H, 7 * H, None, None])
    # terms: 2, 2, 2, 1, 1, 1, −1 → 8 h
    out = sleep_debt_7(sleep, median)
    assert value_at(out, 6) == pytest.approx(8 * H, abs=TOL)


def test_sleep_debt_scaling_with_six_and_five_valid_nights() -> None:
    # Terms (8 h floor, null median): 0, 600, 1200, 1800, 2400, 3000 s on nights 0..5, night 6 missing.
    sleep6 = series(range(7), [8 * H - t for t in (0, 600, 1200, 1800, 2400, 3000)] + [None])
    med = series(range(7), [None] * 7)
    # Day 6: 6 valid → 9000 · 7/6 = 10500.
    assert value_at(sleep_debt_7(sleep6, med), 6) == pytest.approx(10500.0, abs=TOL)
    # Remove night 2 too (1200): 5 valid → 7800 · 7/5 = 10920.
    sleep5 = sleep6.copy()
    sleep5.iloc[2] = np.nan
    assert value_at(sleep_debt_7(sleep5, med), 6) == pytest.approx(10920.0, abs=TOL)
    # Remove night 4 as well: 4 valid → null.
    sleep4 = sleep5.copy()
    sleep4.iloc[4] = np.nan
    assert_nan(value_at(sleep_debt_7(sleep4, med), 6))


def test_sleep_debt_calendar_nights_with_sparse_index() -> None:
    # Rows only on days 0, 1, 2, 3, 4, 8 (days 5–7 absent from the index).
    sleep = series([0, 1, 2, 3, 4, 8], [7 * H] * 6)
    med = series([0, 1, 2, 3, 4, 8], [None] * 6)
    out = sleep_debt_7(sleep, med)
    assert list(out.index) == list(sleep.index)
    # Day 4: nights 0..4 → 5 valid → 5 h · 7/5 = 7 h.
    assert value_at(out, 4) == pytest.approx(7 * H, abs=TOL)
    # Day 8: calendar nights 2..8 → valid 2, 3, 4, 8 = 4 → null (a row-based window would have 7 rows).
    assert_nan(value_at(out, 8))


def test_sleep_debt_excludes_night_d_minus_7() -> None:
    # Night 0 has a huge deficit; day 7's window is nights 1..7 (7 × 1 h), so night 0 must not count.
    sleep = series(range(8), [0.0] + [7 * H] * 7)
    med = series(range(8), [None] * 8)
    assert value_at(sleep_debt_7(sleep, med), 7) == pytest.approx(7 * H, abs=TOL)


def test_sleep_debt_median_aligned_by_date() -> None:
    # The median series has a different (longer, shuffled) index; values are matched per date.
    sleep = series(range(7), [7 * H] * 7)
    med = series([6, 5, 4, 3, 2, 1, 0, 20], [9 * H] * 8)
    assert value_at(sleep_debt_7(sleep, med), 6) == pytest.approx(14 * H, abs=TOL)


# ---------------------------------------------------------------------------------------------------------
# with_baselines


def test_with_baselines_adds_columns_and_sleep_debt() -> None:
    # 36 days: sleep 7 h on days 0..27, then 6 h on 28..35; extra column preserved.
    n = 36
    sleep = [7 * H] * 28 + [6 * H] * 8
    wellness = frame(range(n), sleep_s=sleep, steps=[1000.0] * n)
    out = with_baselines(wellness)
    assert list(out.index) == list(wellness.index)
    assert (out["steps"] == 1000.0).all()
    for f in BASELINE_FIELDS:
        assert f"{f}_median28" in out.columns
        assert f"{f}_mad28" in out.columns
    assert "sleep_debt_7" in out.columns
    # Day 35: nights 29..35 slept 6 h. Baselines: day 29 window 1..28 → median 7 h (27 × 7 h, 1 × 6 h);
    # day d in 29..35 has (d − 28) nights of 6 h among 28 → median 7 h while < 14 → each term 8 h − 6 h = 2 h.
    assert value_at(out["sleep_s_median28"], 35) == pytest.approx(7 * H, abs=TOL)
    assert value_at(out["sleep_debt_7"], 35) == pytest.approx(14 * H, abs=TOL)


def test_with_baselines_without_sleep_column() -> None:
    out = with_baselines(frame(range(3), rhr=[50.0, 51.0, 52.0]))
    assert out["sleep_debt_7"].isna().all()
    assert (out["rhr"] == [50.0, 51.0, 52.0]).all()
