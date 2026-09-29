"""activity_metrics end to end – METRICS §0–§3, primary load selection §2.4."""

import json
import math
from pathlib import Path

import numpy as np
import pytest

from tests.synthetic import constant, hilly, intervals, with_hr_dropout, with_pause, without_gps
from training.metrics.activity import ActivityMetrics, AthleteParams, ThresholdParams, activity_metrics
from training.metrics.gap import minetti_cost
from training.metrics.load import rtss
from training.metrics.preprocess import preprocess
from training.normalize.streams import empty_streams, normalize_streams

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"

LTHR, TS = 170.0, 3.2
REST, MAX = 50.0, 190.0  # HRr at LTHR = 120 / 140
RUN = ThresholdParams(lthr=LTHR, threshold_speed=TS)
ATHLETE = AthleteParams(sex="male", max_hr=MAX, rest_hr=REST)
Z4_ONLY = {"1": 0, "2": 0, "3": 0, "4": 3600, "5": 0}
ZERO = {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


def run(df, *, sport="run", is_indoor=False, threshold=RUN, athlete=ATHLETE) -> ActivityMetrics:
    return activity_metrics(df, sport=sport, is_indoor=is_indoor, threshold=threshold, athlete=athlete)


def test_outdoor_run_at_threshold_uses_rtss():
    m = run(constant(3600, hr=LTHR, speed=TS))
    assert m.moving_s == 3600
    assert m.hr_coverage == 1.0
    assert m.low_confidence is False
    assert m.hrtss == pytest.approx(100.0, abs=1e-9)
    assert m.if_hr == pytest.approx(1.0, abs=1e-12)
    assert m.trimp_norm == pytest.approx(100.0, abs=1e-9)
    assert m.rtss == pytest.approx(100.0, abs=1e-9)
    assert m.if_pace == pytest.approx(1.0, abs=1e-12)
    assert m.load_method == "rtss"
    assert m.load_primary == m.rtss
    assert m.time_in_hr_zone == Z4_ONLY
    assert m.time_in_pace_zone == Z4_ONLY


def test_values_are_plain_python_types():
    m = run(constant(3600, hr=LTHR, speed=TS))
    for name in ("hr_coverage", "hrtss", "if_hr", "trimp_norm", "rtss", "if_pace", "load_primary"):
        assert type(getattr(m, name)) is float, name
    assert type(m.moving_s) is int
    assert type(m.low_confidence) is bool
    assert all(type(v) is int for v in m.time_in_hr_zone.values())
    assert all(type(v) is int for v in m.time_in_pace_zone.values())


def test_run_without_threshold_speed_falls_back_to_hrtss():
    m = run(constant(3600, hr=LTHR, speed=TS), threshold=ThresholdParams(lthr=LTHR))
    assert m.rtss is None and m.if_pace is None
    assert m.load_method == "hrtss"
    assert m.load_primary == pytest.approx(100.0, abs=1e-9)
    assert m.time_in_pace_zone is None
    assert m.time_in_hr_zone == Z4_ONLY


def test_indoor_run_has_no_rtss():
    m = run(constant(3600, hr=LTHR, speed=TS), is_indoor=True)
    assert m.rtss is None and m.if_pace is None
    assert m.load_method == "hrtss"
    assert m.load_primary == pytest.approx(100.0, abs=1e-9)
    assert m.time_in_pace_zone == Z4_ONLY  # pace zones only need a speed (§1)


def test_run_without_gps_has_no_rtss():
    m = run(without_gps(constant(3600, hr=LTHR, speed=TS)))
    assert m.rtss is None
    assert m.load_method == "hrtss"


def test_run_with_sparse_speed_has_no_rtss():
    df = constant(3600, hr=LTHR, speed=TS)
    df.loc[:360, "speed"] = np.nan  # 361 of 3600 without speed → 89.97 % < 90 %
    assert run(df).load_method == "hrtss"
    df = constant(3600, hr=LTHR, speed=TS)
    df.loc[:359, "speed"] = np.nan  # exactly 90 % with speed
    assert run(df).load_method == "rtss"


def test_short_run_without_30_windows_falls_back_to_hrtss():
    m = run(constant(58, hr=LTHR, speed=TS))
    assert m.rtss is None and m.load_method == "hrtss"
    assert m.load_primary == pytest.approx(58 / 36, abs=1e-12)


@pytest.mark.parametrize("sport", ["bike", "other"])
def test_bike_and_other_use_hrtss_even_with_threshold_speed(sport):
    m = run(constant(3600, hr=LTHR, speed=8.0), sport=sport)
    assert m.rtss is None and m.if_pace is None
    assert m.time_in_pace_zone is None
    assert m.load_method == "hrtss"
    assert m.load_primary == pytest.approx(100.0, abs=1e-9)
    assert m.time_in_hr_zone == Z4_ONLY


def test_no_threshold_record_all_threshold_metrics_null():
    m = run(constant(3600, hr=LTHR, speed=TS), threshold=ThresholdParams())
    assert m.moving_s == 3600 and m.hr_coverage == 1.0 and m.low_confidence is False
    for name in ("hrtss", "if_hr", "trimp_norm", "rtss", "if_pace", "load_primary", "load_method"):
        assert getattr(m, name) is None, name
    assert m.time_in_hr_zone is None and m.time_in_pace_zone is None


def test_threshold_speed_without_lthr_still_gives_rtss():
    m = run(constant(3600, hr=LTHR, speed=TS), threshold=ThresholdParams(threshold_speed=TS))
    assert m.hrtss is None and m.if_hr is None and m.trimp_norm is None and m.time_in_hr_zone is None
    assert m.load_method == "rtss"
    assert m.load_primary == pytest.approx(100.0, abs=1e-9)


def test_run_without_hr_keeps_rtss_and_flags_low_confidence():
    m = run(constant(3600, hr=np.nan, speed=TS))
    assert m.hr_coverage == 0.0 and m.low_confidence is True
    assert m.hrtss == 0.0 and m.if_hr == 0.0  # NaN HR contributes 0 (§2.1)
    assert m.trimp_norm == 0.0
    assert m.time_in_hr_zone == ZERO
    assert m.load_method == "rtss"
    assert m.load_primary == pytest.approx(100.0, abs=1e-9)


def test_bike_without_hr_primary_is_zero_hrtss_flagged():
    m = run(constant(3600, hr=np.nan, speed=8.0), sport="bike")
    assert m.low_confidence is True
    assert m.load_method == "hrtss" and m.load_primary == 0.0


def test_low_confidence_never_substitutes():
    df = with_hr_dropout(constant(3600, hr=LTHR, speed=TS), 0, 1800)  # 50 % coverage
    m = run(df)
    assert m.low_confidence is True and m.hr_coverage == 0.5
    assert m.hrtss == pytest.approx(50.0, abs=1e-9)
    assert m.if_hr == pytest.approx(math.sqrt(0.5), abs=1e-12)
    assert m.load_method == "rtss" and m.load_primary == pytest.approx(100.0, abs=1e-9)
    m = run(df, sport="bike")
    assert m.load_method == "hrtss" and m.load_primary == pytest.approx(50.0, abs=1e-9)


def test_pause_is_excluded_from_everything():
    df = with_pause(constant(4200, hr=LTHR, speed=TS), 1800, 600, hr=200.0)
    m = run(df)
    assert m.moving_s == 3600
    assert m.hrtss == pytest.approx(100.0, abs=1e-9)
    assert m.trimp_norm == pytest.approx(100.0, abs=1e-9)
    assert m.time_in_hr_zone == Z4_ONLY
    # rTSS: the trailing windows run over kept samples, so the pause does not break the constant speed.
    assert m.rtss == pytest.approx(100.0, abs=1e-9)


def test_hilly_run_rtss_uses_gap():
    df = hilly(3600, speed=2.5, grade=0.10, hr=LTHR)
    m = run(df, threshold=ThresholdParams(lthr=LTHR, threshold_speed=2.5))
    pre = preprocess(df, "run")
    expected = rtss(pre.samples["gap_speed"].to_numpy(), 3600, 2.5)
    assert expected is not None
    assert m.rtss == pytest.approx(expected[0], abs=1e-9)
    assert m.if_pace == pytest.approx(expected[1], abs=1e-12)
    # Almost all of it at +10 %: IF_pace ≈ C(0.10) / 3.6 = 1.6578 (the 7-sample ends pull it down slightly).
    ratio = minetti_cost(np.array([0.10]))[0] / 3.6
    assert m.if_pace == pytest.approx(ratio, rel=1e-3)
    assert m.rtss == pytest.approx(100 * ratio**2, rel=2e-3)
    assert m.hrtss == pytest.approx(100.0, abs=1e-9)  # hrTSS is not grade-adjusted


def test_hilly_bike_is_not_grade_adjusted():
    df = hilly(3600, speed=8.0, grade=0.05, hr=LTHR)
    m = run(df, sport="bike")
    assert m.load_method == "hrtss" and m.load_primary == pytest.approx(100.0, abs=1e-9)


def test_intervals_run_zones():
    m = run(intervals(), threshold=ThresholdParams(lthr=200.0, threshold_speed=4.0))
    assert m.hrtss == pytest.approx(83.25, abs=1e-9)
    assert m.time_in_hr_zone == {"1": 0, "2": 1800, "3": 0, "4": 1800, "5": 0}
    # speed 4.0 → s = 1.0 (Z4), 2.0 → s = 0.5 (Z1)
    assert m.time_in_pace_zone == {"1": 1800, "2": 0, "3": 0, "4": 1800, "5": 0}
    assert m.load_method == "rtss"


def test_custom_zones_from_threshold_record():
    zones = {"hr": [0.5, 0.6, 0.7, 0.8], "pace": [0.5, 0.6, 0.7, 0.8]}
    m = run(constant(3600, hr=LTHR, speed=TS), threshold=ThresholdParams(LTHR, TS, zones))
    assert m.time_in_hr_zone == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 3600}
    assert m.time_in_pace_zone == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 3600}


@pytest.mark.parametrize(
    "athlete",
    [
        AthleteParams(),
        AthleteParams(sex=None, max_hr=MAX, rest_hr=REST),
        AthleteParams(sex="male", max_hr=None, rest_hr=REST),
        AthleteParams(sex="male", max_hr=MAX, rest_hr=None),
        AthleteParams(sex="male", max_hr=REST, rest_hr=REST),  # max_hr ≤ rest_hr
        AthleteParams(sex="male", max_hr=MAX, rest_hr=LTHR),  # lthr ≤ rest_hr → TRIMP_ref = 0
        AthleteParams(sex="unknown", max_hr=MAX, rest_hr=REST),
    ],
)
def test_trimp_norm_null_without_complete_athlete(athlete):
    m = run(constant(3600, hr=LTHR, speed=TS), athlete=athlete)
    assert m.trimp_norm is None
    assert m.hrtss == pytest.approx(100.0, abs=1e-9)


def test_trimp_norm_female():
    m = run(constant(1800, hr=LTHR, speed=TS), athlete=AthleteParams("female", MAX, REST))
    assert m.trimp_norm == pytest.approx(50.0, abs=1e-9)


def test_empty_stream():
    m = run(empty_streams())
    assert m.moving_s == 0 and m.hr_coverage == 0.0 and m.low_confidence is True
    assert m.hrtss == 0.0
    assert m.if_hr is None  # moving_s = 0
    assert m.rtss is None
    assert m.load_method == "hrtss" and m.load_primary == 0.0
    assert m.time_in_hr_zone == ZERO


def test_invalid_sport_rejected():
    with pytest.raises(ValueError):
        run(constant(10), sport="swim")


def test_normalized_fixture_feeds_activity_metrics():
    details = json.loads((FIXTURES / "activity_run_details.json").read_text())
    streams = normalize_streams(details)
    m = run(streams, threshold=ThresholdParams(lthr=150.0, threshold_speed=3.0))
    # §0.2: t = 0 plus 141 s of timer time (sumDuration ends at 141) are running; t = 111..129 are paused.
    assert m.moving_s == int(streams["moving"].sum()) == 142
    # The 15 s gap 77 → 92 is not filled (§0.1): t = 78..91 have neither HR nor speed → 128 / 142.
    assert m.hr_coverage == pytest.approx(128 / 142)
    assert m.low_confidence is False
    assert m.hrtss is not None and m.hrtss > 0
    assert m.if_hr is not None and 0 < m.if_hr < 1.2
    assert m.trimp_norm is not None and m.trimp_norm > 0
    assert sum(m.time_in_hr_zone.values()) == 128
    assert sum(m.time_in_pace_zone.values()) == 128
    # 128 / 142 = 90.1 % of the kept samples have a speed (≥ 90 %) and there is a distance → usable GPS.
    assert m.load_method == "rtss"
    assert m.load_primary == m.rtss
    assert m.if_pace is not None and m.if_pace > 1.0  # uphill (+0.05 m/s of climb at 3 m/s) → GAP > speed
