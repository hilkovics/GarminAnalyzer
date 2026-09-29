"""Best efforts and trailing best-per-window curves – METRICS §6.2.

# METRICS §6.2
Windows `W ∈ {60, 300, 600, 1200, 1800, 3600} s`. For each activity and W: max over all positions of the
mean of `gap_speed` (run) or `speed` (bike, W ≥ 300 only) over a contiguous window of moving samples
(no pause inside). Also HR best efforts: max rolling-mean HR over `{1200, 1800, 3600} s`.
Curves: best per W over trailing 90 days and all-time.
Clarified 2026-09-29 (phase 4, proposed): "contiguous" = consecutive kept samples whose `t` increases by
exactly 1 (no pause, no gap); every sample in the window must have a valid value (a NaN breaks the window).
The effort's distance is the cumulative-distance difference across the window (null if unavailable).
HR efforts for all sports. Trailing 90 days = `local_date` in [today − 89, today].
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import constant, with_pause
from training.metrics.efforts import (
    BIKE_MIN_WINDOW,
    EFFORT_WINDOWS,
    HR_EFFORT_WINDOWS,
    Effort,
    best_efforts,
    best_per_window,
)
from training.metrics.preprocess import SAMPLE_COLUMNS, Preprocessed, preprocess

TODAY = date(2026, 9, 29)


def prep_from(
    t: np.ndarray | None = None,
    *,
    n: int | None = None,
    hr: float | np.ndarray = np.nan,
    speed: float | np.ndarray = np.nan,
    gap: float | np.ndarray | None = None,
    distance: np.ndarray | None = None,
) -> Preprocessed:
    """Kept samples built directly (no §0 preprocessing, exact `t` gaps / NaNs); gap = speed and
    distance = cumsum(speed) (NaN adds 0) by default."""
    if t is None:
        t = np.arange(n, dtype=np.int64)
    t = np.asarray(t, dtype=np.int64)
    size = len(t)

    def full(v: float | np.ndarray) -> np.ndarray:
        return np.broadcast_to(np.asarray(v, dtype=float), (size,)).copy()

    speed_a = full(speed)
    gap_a = speed_a.copy() if gap is None else full(gap)
    dist_a = np.cumsum(np.nan_to_num(speed_a)) if distance is None else full(distance)
    samples = pd.DataFrame(
        {
            "t": t,
            "hr": full(hr),
            "speed": speed_a,
            "alt": np.full(size, 100.0),
            "grade": np.full(size, np.nan),
            "distance": dist_a,
            "gap_speed": gap_a,
            "is_slow": np.zeros(size, dtype=bool),
        },
        columns=list(SAMPLE_COLUMNS),
    )
    hr_cov = float(np.count_nonzero(~np.isnan(full(hr))) / size) if size else 0.0
    return Preprocessed(samples=samples, moving_s=size, hr_coverage=hr_cov, low_confidence=hr_cov < 0.7)


def by_key(efforts: list[Effort]) -> dict[tuple[str, int], Effort]:
    keys = [(e.kind, e.window_s) for e in efforts]
    assert len(keys) == len(set(keys)), "one effort per (kind, window)"
    return dict(zip(keys, efforts, strict=True))


# ---------------------------------------------------------------- constants


def test_window_constants():
    assert EFFORT_WINDOWS == (60, 300, 600, 1200, 1800, 3600)
    assert HR_EFFORT_WINDOWS == (1200, 1800, 3600)
    assert BIKE_MIN_WINDOW == 300


# ---------------------------------------------------------------- run gap_speed efforts


def fast_block_run() -> Preprocessed:
    """3600 s at gap 3.0 m/s with a 300 s block at 4.0 m/s for t in [1000, 1300)."""
    gap = np.full(3600, 3.0)
    gap[1000:1300] = 4.0
    return prep_from(n=3600, speed=gap, hr=150.0)


def test_known_fastest_300s_block():
    eff = by_key(best_efforts(fast_block_run(), "run"))
    e = eff[("gap_speed", 300)]
    assert e.value == pytest.approx(4.0)
    assert e.start_t == 1000
    assert e.window_s == 300


def test_every_run_window_value():
    eff = by_key(best_efforts(fast_block_run(), "run"))
    expected = {
        60: 4.0,
        300: 4.0,
        600: (300 * 4 + 300 * 3) / 600,
        1200: (300 * 4 + 900 * 3) / 1200,
        1800: (300 * 4 + 1500 * 3) / 1800,
        3600: (300 * 4 + 3300 * 3) / 3600,
    }
    for w, v in expected.items():
        assert eff[("gap_speed", w)].value == pytest.approx(v), w
    assert eff[("gap_speed", 60)].start_t == 1000  # first maximal position
    assert eff[("gap_speed", 600)].start_t == 700  # earliest window containing the whole block
    assert eff[("gap_speed", 3600)].start_t == 0


def test_run_kinds_are_gap_speed_and_hr_in_order():
    efforts = best_efforts(fast_block_run(), "run")
    assert all(isinstance(e, Effort) for e in efforts)
    expected = [("gap_speed", w) for w in EFFORT_WINDOWS] + [("hr", w) for w in HR_EFFORT_WINDOWS]
    assert [(e.kind, e.window_s) for e in efforts] == expected


def test_run_uses_gap_speed_not_speed():
    pre = prep_from(n=600, speed=3.0, gap=3.5)
    eff = by_key(best_efforts(pre, "run"))
    assert eff[("gap_speed", 600)].value == pytest.approx(3.5)


def test_distance_is_cumulative_difference_across_window():
    # distance[i] = 4.0 · i + 7 (arbitrary offset); window of 300 samples starting at 1000.
    gap = np.full(3600, 3.0)
    gap[1000:1300] = 4.0
    dist = np.arange(3600) * 10.0 + 7.0
    eff = by_key(best_efforts(prep_from(n=3600, speed=gap, distance=dist), "run"))
    e = eff[("gap_speed", 300)]
    assert e.distance_m == pytest.approx(dist[1299] - dist[1000])  # = 2990 m
    assert e.distance_m == pytest.approx(2990.0)


def test_distance_from_speed_integration():
    # default distance = cumsum(speed): d[1299] − d[1000] = Σ speed[1001..1299] = 299 · 4.
    eff = by_key(best_efforts(fast_block_run(), "run"))
    assert eff[("gap_speed", 300)].distance_m == pytest.approx(299 * 4.0)


def test_distance_none_when_unavailable():
    pre = prep_from(n=700, speed=3.0, distance=np.full(700, np.nan))
    for e in best_efforts(pre, "run"):
        assert e.distance_m is None


def test_distance_none_when_an_end_is_nan():
    dist = np.arange(600, dtype=float)
    dist[599] = np.nan
    eff = by_key(best_efforts(prep_from(n=600, speed=3.0, distance=dist), "run"))
    assert eff[("gap_speed", 600)].distance_m is None
    assert eff[("gap_speed", 300)].distance_m is not None  # the first 300-window is fine


def test_pause_breaks_window():
    # 700 kept samples, but t jumps by 10 s after 350 samples → no contiguous 600 s window.
    t = np.concatenate([np.arange(350), np.arange(360, 710)])
    eff = by_key(best_efforts(prep_from(t, speed=4.0), "run"))
    assert ("gap_speed", 600) not in eff
    assert eff[("gap_speed", 300)].value == pytest.approx(4.0)


def test_exact_t_contiguity_single_missing_second_breaks():
    # t increases by 2 once: 300 + 300 samples, no 600 window even though 600 samples exist.
    t = np.concatenate([np.arange(300), np.arange(301, 601)])
    eff = by_key(best_efforts(prep_from(t, speed=4.0), "run"))
    assert ("gap_speed", 600) not in eff
    assert eff[("gap_speed", 300)].start_t == 0
    # the second stretch starts at t = 301 and has exactly 300 samples
    faster = np.concatenate([np.full(300, 3.0), np.full(300, 5.0)])
    eff = by_key(best_efforts(prep_from(t, speed=faster), "run"))
    assert eff[("gap_speed", 300)].value == pytest.approx(5.0)
    assert eff[("gap_speed", 300)].start_t == 301


def test_contiguous_600_exactly():
    eff = by_key(best_efforts(prep_from(np.arange(600), speed=4.0), "run"))
    assert eff[("gap_speed", 600)].value == pytest.approx(4.0)
    assert ("gap_speed", 1200) not in eff


def test_nan_breaks_window():
    gap = np.full(700, 4.0)
    gap[350] = np.nan
    eff = by_key(best_efforts(prep_from(n=700, speed=gap), "run"))
    assert ("gap_speed", 600) not in eff
    assert eff[("gap_speed", 300)].value == pytest.approx(4.0)
    gap = np.full(60, 4.0)
    gap[0] = np.nan  # only 59 valid samples: a NaN before a stretch must not count into it
    assert [e for e in best_efforts(prep_from(n=60, speed=gap), "run") if e.kind == "gap_speed"] == []


def test_nan_excluded_even_if_it_would_lower_mean():
    # a slow 60 s block with one NaN: the fastest valid 60 s window avoids it
    gap = np.concatenate([np.full(60, 5.0), np.full(60, 3.0)])
    gap[30] = np.nan
    eff = by_key(best_efforts(prep_from(n=120, speed=gap), "run"))
    e = eff[("gap_speed", 60)]
    assert e.start_t == 31
    assert e.value == pytest.approx((29 * 5.0 + 31 * 3.0) / 60)


def test_slow_samples_count():
    # walking samples are moving samples – §6.2 does not exclude them
    gap = np.full(300, 0.5)
    eff = by_key(best_efforts(prep_from(n=300, speed=gap), "run"))
    assert eff[("gap_speed", 300)].value == pytest.approx(0.5)


def test_too_short_or_empty_activity_has_no_effort():
    assert [e for e in best_efforts(prep_from(n=59, speed=4.0), "run") if e.kind == "gap_speed"] == []
    assert best_efforts(prep_from(np.array([], dtype=np.int64)), "run") == []


def test_unknown_sport_raises():
    with pytest.raises(ValueError):
        best_efforts(prep_from(n=60, speed=3.0), "swim")


# ---------------------------------------------------------------- bike and other


def test_bike_uses_speed_and_skips_windows_below_300():
    pre = prep_from(n=3600, speed=8.0, gap=99.0, hr=140.0)
    eff = by_key(best_efforts(pre, "bike"))
    speed_windows = {w for (k, w) in eff if k == "speed"}
    assert speed_windows == {300, 600, 1200, 1800, 3600}
    assert 60 not in speed_windows
    assert all(k in {"speed", "hr"} for (k, _) in eff)
    assert eff[("speed", 300)].value == pytest.approx(8.0)
    assert eff[("speed", 300)].distance_m == pytest.approx(299 * 8.0)


def test_other_has_only_hr_efforts():
    pre = prep_from(n=3600, speed=3.0, hr=130.0)
    eff = best_efforts(pre, "other")
    assert {(e.kind, e.window_s) for e in eff} == {("hr", w) for w in HR_EFFORT_WINDOWS}


# ---------------------------------------------------------------- HR efforts


def test_hr_efforts_values_no_lag_and_no_distance():
    hr = np.full(4000, 140.0)
    hr[2000:3200] = 170.0  # 1200 s block
    pre = prep_from(n=4000, speed=3.0, hr=hr)
    for sport in ("run", "bike", "other"):
        eff = by_key(best_efforts(pre, sport))
        e = eff[("hr", 1200)]
        assert e.value == pytest.approx(170.0)
        assert e.start_t == 2000  # raw HR, no §0.6 lag
        assert e.distance_m is None
        assert eff[("hr", 1800)].value == pytest.approx((1200 * 170 + 600 * 140) / 1800)
        assert eff[("hr", 3600)].value == pytest.approx((1200 * 170 + 2400 * 140) / 3600)


def test_hr_nan_breaks_hr_window():
    hr = np.full(1300, 150.0)
    hr[650] = np.nan
    eff = by_key(best_efforts(prep_from(n=1300, speed=3.0, hr=hr), "run"))
    assert ("hr", 1200) not in eff
    assert ("gap_speed", 1200) in eff  # speed windows are independent of HR validity


def test_no_hr_no_hr_efforts():
    eff = best_efforts(prep_from(n=3600, speed=3.0), "run")
    assert all(e.kind == "gap_speed" for e in eff)


def test_through_preprocess_with_pause():
    # 1300 s at 3.2 m/s, timer stopped for [600, 700) → 1200 kept samples, split 600 | 600.
    pre = preprocess(with_pause(constant(1300, hr=160.0, speed=3.2), 600, 100), "run")
    eff = by_key(best_efforts(pre, "run"))
    assert eff[("gap_speed", 600)].value == pytest.approx(3.2)
    assert ("gap_speed", 1200) not in eff
    assert ("hr", 1200) not in eff


# ---------------------------------------------------------------- best_per_window


def efforts_frame(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["local_date", "kind", "window_s", "value", "activity_id"])


def test_best_per_window_90_day_edges():
    df = efforts_frame(
        [
            (TODAY - timedelta(days=89), "gap_speed", 300, 5.0, 1),  # in (edge)
            (TODAY - timedelta(days=90), "gap_speed", 300, 6.0, 2),  # out (edge)
            (TODAY - timedelta(days=10), "gap_speed", 300, 4.0, 3),
            (TODAY, "gap_speed", 600, 3.9, 4),  # today is in
            (TODAY - timedelta(days=5), "hr", 1200, 171.0, 3),
        ]
    )
    out = best_per_window(df, today=TODAY)
    assert list(out.columns) == ["kind", "window_s", "value", "local_date", "activity_id"]
    rows = {(r.kind, r.window_s): r for r in out.itertuples()}
    assert set(rows) == {("gap_speed", 300), ("gap_speed", 600), ("hr", 1200)}
    assert rows[("gap_speed", 300)].value == 5.0
    assert rows[("gap_speed", 300)].local_date == TODAY - timedelta(days=89)
    assert rows[("gap_speed", 300)].activity_id == 1
    assert rows[("gap_speed", 600)].local_date == TODAY
    assert rows[("hr", 1200)].value == 171.0


def test_best_per_window_all_time():
    df = efforts_frame(
        [
            (TODAY - timedelta(days=89), "gap_speed", 300, 5.0, 1),
            (TODAY - timedelta(days=900), "gap_speed", 300, 6.0, 2),
        ]
    )
    out = best_per_window(df, today=TODAY, days=None)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["value"] == 6.0
    assert row["local_date"] == TODAY - timedelta(days=900)
    assert row["activity_id"] == 2


def test_best_per_window_custom_days():
    df = efforts_frame(
        [
            (TODAY - timedelta(days=27), "gap_speed", 60, 5.0, 1),
            (TODAY - timedelta(days=28), "gap_speed", 60, 6.0, 2),
        ]
    )
    assert best_per_window(df, today=TODAY, days=28).iloc[0]["value"] == 5.0


def test_best_per_window_excludes_future_dates():
    df = efforts_frame(
        [
            (TODAY + timedelta(days=1), "gap_speed", 60, 9.0, 1),
            (TODAY, "gap_speed", 60, 5.0, 2),
        ]
    )
    assert best_per_window(df, today=TODAY).iloc[0]["value"] == 5.0
    assert best_per_window(df, today=TODAY, days=None).iloc[0]["value"] == 5.0


def test_best_per_window_tie_takes_earliest():
    df = efforts_frame(
        [
            (TODAY - timedelta(days=3), "gap_speed", 60, 5.0, 7),
            (TODAY - timedelta(days=30), "gap_speed", 60, 5.0, 8),
        ]
    )
    row = best_per_window(df, today=TODAY).iloc[0]
    assert row["local_date"] == TODAY - timedelta(days=30)
    assert row["activity_id"] == 8


def test_best_per_window_without_activity_id_and_timestamp_dates():
    df = pd.DataFrame(
        {
            "local_date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "kind": ["speed", "speed"],
            "window_s": [300, 300],
            "value": [9.0, 10.0],
        }
    )
    out = best_per_window(df, today=TODAY)
    assert len(out) == 1
    assert out.iloc[0]["value"] == 10.0
    assert out.iloc[0]["local_date"] == date(2026, 9, 2)
    assert out.iloc[0]["activity_id"] is None


def test_best_per_window_empty():
    out = best_per_window(efforts_frame([]), today=TODAY)
    assert out.empty
    assert list(out.columns) == ["kind", "window_s", "value", "local_date", "activity_id"]
    out = best_per_window(efforts_frame([(TODAY - timedelta(days=200), "hr", 1200, 170.0, 1)]), today=TODAY)
    assert out.empty


def test_best_per_window_ignores_nan_values():
    df = efforts_frame(
        [
            (TODAY, "gap_speed", 60, np.nan, 1),
            (TODAY - timedelta(days=1), "gap_speed", 60, 4.0, 2),
        ]
    )
    assert best_per_window(df, today=TODAY).iloc[0]["value"] == 4.0
