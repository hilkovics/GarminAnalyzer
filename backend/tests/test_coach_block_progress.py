"""Block progress (METRICS §11.4) with known answers: snapshots, check runs, summary (pure, no DB)."""

from datetime import date, timedelta

import pandas as pd
import pytest

from training.coach import block_progress as bp
from training.metrics.predictions import vdot, vdot_race_time

DAY = date(2026, 11, 1)


def runs(*rows):
    return pd.DataFrame(rows, columns=["local_date", "ef", "steady_state", "pace_at_ref_hr_day"])


def candidates(*rows):
    return pd.DataFrame(rows, columns=["local_date", "distance_m", "time_s", "source"])


NO_CANDIDATES = candidates()


def test_snapshot_medians_over_28_days_and_ef_from_steady_runs():
    frame = runs(
        (DAY - timedelta(days=28), 9.0, True, 9.0),  # outside the window
        (DAY - timedelta(days=27), 1.5, True, 3.0),
        (DAY - timedelta(days=10), 1.7, False, 3.2),  # EF of a non-steady run is ignored
        (DAY, 1.9, True, None),
        (DAY + timedelta(days=1), 5.0, True, 5.0),  # after the day
    )
    s = bp.snapshot(DAY, frame, NO_CANDIDATES)
    assert s.pace_at_ref_hr == pytest.approx(3.1) and s.ef == pytest.approx(1.7)
    assert (s.vdot, s.t5k_s, s.t10k_s, s.reference_date) == (None, None, None, None)


def test_snapshot_without_runs_is_empty():
    assert bp.snapshot(DAY, runs(), NO_CANDIDATES) == bp.Snapshot(DAY)


def test_snapshot_predictions_from_the_reference_as_of_the_day():
    cands = candidates(
        (DAY - timedelta(days=10), 10000.0, 2400.0, "race"),
        (DAY + timedelta(days=1), 10000.0, 2000.0, "race"),  # later: not known yet
    )
    s = bp.snapshot(DAY, runs(), cands)
    assert s.vdot == pytest.approx(51.94, abs=0.05) and s.t10k_s == pytest.approx(2400, abs=1)
    assert s.t5k_s == pytest.approx(vdot_race_time(s.vdot, 5000.0))
    assert s.reference_date == DAY - timedelta(days=10)


def test_change_signs():
    base = bp.Snapshot(DAY, 3.0, 1.5, 50.0, 1200.0, 2500.0)
    now = bp.Snapshot(DAY, 3.1, 1.6, 51.0, 1180.0, None)
    c = bp.change(base, now)
    assert c.pace_at_ref_hr == pytest.approx(0.1) and c.ef == pytest.approx(0.1)
    assert (c.vdot, c.t5k_s, c.t10k_s) == (1.0, -20.0, None)


def test_check_run_result():
    r = bp.check_run_result(DAY, 7, 7000.0, 171.4)
    assert r is not None and r.vdot == pytest.approx(vdot(7000.0, 1800.0))
    assert r.t5k_s == pytest.approx(vdot_race_time(r.vdot, 5000.0)) and r.t5k_s < 1800 * 5000 / 7000
    assert bp.check_run_result(DAY, 7, None, 170.0) is None
    assert bp.check_run_result(DAY, 7, float("nan"), 170.0) is None


def week(no, items, brake=None, value=None):
    return bp.WeekRecord(
        monday=DAY + timedelta(weeks=no - 1),
        week_no=no,
        target_s=6000.0,
        run_s=5000.0,
        items_done=items,
        brake=brake,
        recovery=False,
        test=False,
        mean_readiness=None,
        mean_sleep_s=None,
        value=value or bp.Snapshot(DAY),
    )


def test_summary():
    base = bp.Snapshot(DAY, 3.0, None, 50.0, 1200.0, 2500.0)
    last = bp.Snapshot(DAY, 3.2, None, 52.0, 1150.0, 2400.0)
    s = bp.summarize(
        [week(1, 3), week(2, 2, "hold"), week(3, 1, value=last)],
        base,
        final=False,
        readiness=[80.0, 60.0, None, 70.0, float("nan")],
        sleep_s=[7 * 3600, None, 6 * 3600],
    )
    assert (s.weeks, s.items_done, s.items_planned, s.brake_weeks) == (3, 6, 9, 1)
    assert (s.run_s, s.target_s) == (15000.0, 18000.0)
    assert s.mean_readiness == pytest.approx(70.0) and s.green_share == pytest.approx(2 / 3)
    assert s.mean_sleep_s == pytest.approx(6.5 * 3600)
    assert s.change is not None and s.change.t5k_s == -50.0 and s.change.ef is None
    empty = bp.summarize([], None, final=False, readiness=[], sleep_s=[])
    assert (empty.mean_readiness, empty.green_share, empty.change) == (None, None, None)


def test_baseline_json_roundtrip_and_garbage():
    value = bp.Snapshot(DAY, 3.0, None, 50.0, 1200.0, 2500.0, DAY - timedelta(days=3))
    assert bp.from_json(bp.to_json(value)) == value
    assert bp.from_json(None) is None and bp.from_json({"day": "x"}) is None
    assert bp.from_json({"day": "2026-11-01", "reference_date": "bad"}) is None
