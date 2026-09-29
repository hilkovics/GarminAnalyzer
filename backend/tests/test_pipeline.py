"""training.pipeline: DB ↔ metrics wiring, historical thresholds, PMC persistence, diagnostics. Offline."""

import datetime as dt

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from training import pipeline
from training.db import repo
from training.db.models import Activity, ActivityMetric, DailyLoad
from training.services.diagnostics import get_diagnostics

UTC = dt.UTC
LTHR = 170.0


def add_activity(
    session,
    garmin_id: int,
    day: dt.date,
    *,
    sport: str = "bike",
    hr: float = LTHR,
    seconds: int = 3600,
    garmin_load: float | None = None,
    is_indoor: bool = False,
) -> int:
    """Constant-HR activity with a full 1 Hz stream (all samples moving)."""
    aid = repo.upsert_activity(
        session,
        {
            "garmin_id": garmin_id,
            "sport": sport,
            "sub_sport": {"bike": "road_biking", "run": "running", "other": "hiking"}[sport],
            "start_utc": dt.datetime.combine(day, dt.time(6), tzinfo=UTC),
            "local_date": day,
            "duration_s": float(seconds),
            "is_race": False,
            "is_indoor": is_indoor,
            "garmin_training_load": garmin_load,
        },
    )
    t = np.arange(seconds)
    repo.replace_streams(
        session,
        aid,
        pd.DataFrame(
            {
                "t": t,
                "hr": np.full(seconds, hr),
                "speed": np.full(seconds, 8.0 if sport == "bike" else 3.0),
                "alt": np.full(seconds, 150.0),
                "distance": t * (8.0 if sport == "bike" else 3.0),
                "moving": np.ones(seconds, dtype=bool),
            }
        ),
    )
    session.commit()
    return aid


def metric(session, aid: int) -> ActivityMetric:
    session.expire_all()
    return session.get(ActivityMetric, aid)


def test_one_hour_at_lthr_is_100_points_and_pmc_is_persisted(session):
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    aid = add_activity(session, 1, dt.date(2026, 9, 1))
    result = pipeline.recompute(session, renormalize=False, end=dt.date(2026, 9, 10))
    assert result.errors == [] and result.metrics_computed == 1
    m = metric(session, aid)
    assert m.load_method == "hrtss"
    assert m.load_primary == pytest.approx(100.0, abs=1e-6)
    assert m.threshold_id_used is not None
    days = session.exec(select(DailyLoad).order_by(DailyLoad.date)).scalars().all()
    assert [d.date for d in days] == [dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(10)]
    assert days[0].load_total == pytest.approx(100.0) and days[1].load_total == 0.0
    assert days[0].ctl == pytest.approx(100 / 42) and days[0].tsb == 0.0


def test_thresholds_are_resolved_by_activity_date(session):
    """CLAUDE.md rule 7 / PLAN phase 3 acceptance: a new LTHR changes only activities from its date."""
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    early = add_activity(session, 1, dt.date(2026, 3, 1))
    late = add_activity(session, 2, dt.date(2026, 6, 1))
    pipeline.recompute(session, renormalize=False)
    early_before = metric(session, early).load_primary

    result = pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 5, 1), lthr=LTHR + 10)
    assert result.metrics_computed == 1  # only the activity on/after 2026-05-01
    assert metric(session, early).load_primary == early_before
    assert metric(session, late).load_primary < early_before  # same HR, higher LTHR → less load


def test_other_sport_uses_run_threshold_and_missing_threshold_gives_null_load(session):
    hike = add_activity(session, 3, dt.date(2026, 4, 1), sport="other")
    pipeline.recompute(session, renormalize=False)
    assert metric(session, hike).load_primary is None and metric(session, hike).threshold_id_used is None
    pipeline.set_threshold(session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    assert metric(session, hike).load_primary == pytest.approx(100.0, abs=1e-6)


def test_rest_hr_is_28_day_median_unless_overridden(session):
    day = dt.date(2026, 5, 28)
    for i, rhr in enumerate([50, 52, 48, 70]):  # the 70 is 30 days before → outside the window
        d = day - dt.timedelta(days=30 if rhr == 70 else i)
        repo.upsert_wellness(session, {"date": d, "rhr": float(rhr)})
    session.commit()
    assert pipeline.rest_hr_for(session, None, day) == 50.0
    athlete = pipeline.set_athlete(session, rest_hr_override=44.0)
    assert pipeline.rest_hr_for(session, athlete, day) == 44.0


def test_update_after_sync_and_diagnostics(session):
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    for i, (hr, garmin) in enumerate(
        [(LTHR, 150.0), (0.9 * LTHR, 110.0), (0.8 * LTHR, 80.0), (0.7 * LTHR, 55.0)]
    ):
        add_activity(session, 10 + i, dt.date(2026, 9, 1 + i), hr=hr, garmin_load=garmin)
    result = pipeline.update_after_sync(session, [10, 11, 12, 13], today=dt.date(2026, 9, 5))
    assert result.metrics_computed == 4 and result.daily_load_days == 5
    d = get_diagnostics(session)
    assert d.activities == d.activities_with_metrics == 4
    assert d.load_sanity.n == 4 and d.load_sanity.r > 0.95 and d.load_sanity.status == "good"
    assert d.activities_without_threshold == 0


def test_recompute_from_raw_matches_incremental(session):
    """Full `recompute` (re-normalize raw → metrics → PMC) reproduces what sync + update produced."""
    from training.garmin.client import GarminClient
    from training.garmin.sync import sync

    from .test_sync import TODAY, FakeGarmin, make_activity

    api = FakeGarmin(
        [make_activity(1001, TODAY - dt.timedelta(days=2)), make_activity(1002, TODAY, "road_biking")]
    )
    pipeline.set_threshold(
        session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=150.0, threshold_speed=3.2
    )
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=155.0)
    result = sync(session, GarminClient(api, rate_limit_s=0, sleep=lambda s: None), TODAY)
    pipeline.update_after_sync(session, result.affected, today=TODAY)
    before = {
        r.activity_id: (r.load_primary, r.load_method) for r in session.exec(select(ActivityMetric)).scalars()
    }
    pipeline.recompute(session, end=TODAY)
    session.expire_all()
    after = {
        r.activity_id: (r.load_primary, r.load_method) for r in session.exec(select(ActivityMetric)).scalars()
    }
    assert after == before and len(after) == 2
    assert session.execute(select(Activity.sport).order_by(Activity.garmin_id)).scalars().all() == [
        "run",
        "bike",
    ]


def test_interrupted_ingest_is_caught_up_by_the_next_run(session):
    """Review phase 2, blocker: activities normalized by a run that never reached the metric step
    (Ctrl+C / 429) get their metrics on the next run, although they are "unchanged" by then."""
    from training.garmin.backfill import backfill
    from training.garmin.client import GarminClient

    from .test_sync import TODAY, FakeGarmin, make_activity

    pipeline.set_threshold(session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=150.0)
    api = FakeGarmin([make_activity(2001, dt.date(2026, 8, 5)), make_activity(2002, dt.date(2026, 9, 2))])
    client = GarminClient(api, rate_limit_s=0, sleep=lambda s: None)
    backfill(session, client, 2, TODAY)  # the CLI would now call update_after_sync – simulate that it died
    assert session.exec(select(ActivityMetric)).scalars().all() == []

    result = pipeline.update_after_sync(session, [], today=TODAY)  # next run: nothing new was fetched
    assert result.metrics_computed == 2
    assert repo.get_state_json(session, "metrics_dirty_activities") == []
    assert pipeline.update_after_sync(session, [], today=TODAY).metrics_computed == 0  # markers cleared


def test_pmc_series_end_and_readiness_are_stable_across_entry_points(session):
    """Review phase 2, warning 1: every entry point extends the series to `end`; readiness (phase 5) is
    recomputed by each of them from wellness + TSB (METRICS §8)."""
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    add_activity(session, 1, dt.date(2026, 9, 1))
    today = dt.date(2026, 9, 10)
    repo.upsert_wellness(session, {"date": today, "sleep_score": 80.0})
    session.commit()
    pipeline.update_after_sync(session, [1], today=today)
    tsb = session.get(DailyLoad, today).tsb
    assert session.get(DailyLoad, today).readiness == pytest.approx(
        (0.3 * 80 + 0.2 * max(0.0, min(100.0, 50 + 2 * tsb))) / 0.5
    )
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 8, 1), lthr=LTHR + 5, end=today)
    pipeline.recompute(session, renormalize=False, end=today)
    session.expire_all()
    days = session.exec(select(DailyLoad).order_by(DailyLoad.date)).scalars().all()
    assert days[-1].date == today and len(days) == 10
    row = session.get(DailyLoad, today)
    assert row.readiness == pytest.approx((0.3 * 80 + 0.2 * max(0.0, min(100.0, 50 + 2 * row.tsb))) / 0.5)
    assert session.get(DailyLoad, dt.date(2026, 9, 9)).readiness is None  # no wellness that day


def test_old_wellness_change_recomputes_the_following_28_days(session):
    """Review phase 2, warning 2: RHR of day W feeds TRIMP of activities on W..W+27."""
    pipeline.set_athlete(session, sex="male", max_hr=190.0)
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    inside = add_activity(session, 1, dt.date(2026, 3, 20), hr=0.8 * LTHR)
    outside = add_activity(session, 2, dt.date(2026, 5, 1), hr=0.8 * LTHR)
    repo.upsert_wellness(session, {"date": dt.date(2026, 3, 10), "rhr": 50.0})
    session.commit()
    pipeline.recompute(session, renormalize=False)
    before_inside, before_outside = metric(session, inside).trimp_norm, metric(session, outside).trimp_norm
    assert before_inside is not None and before_outside is None  # no RHR within 28 days of 2026-05-01

    repo.upsert_wellness(session, {"date": dt.date(2026, 3, 10), "rhr": 40.0})  # backfilled/corrected value
    repo.set_state_json(session, "metrics_dirty_wellness_days", ["2026-03-10"])
    session.commit()
    result = pipeline.update_after_sync(session, [], today=dt.date(2026, 5, 2))
    assert result.metrics_computed == 1  # only the activity inside 2026-03-10 … 2026-04-06
    assert metric(session, inside).trimp_norm != before_inside


def test_series_ends_at_last_sync_without_explicit_end(session):
    """Review phase 2 round 2, blocker: any entry point (no `end`) keeps rest days up to the last sync."""
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    add_activity(session, 1, dt.date(2026, 9, 1))
    repo.set_state(session, "last_activity_sync", "2026-09-10")
    session.commit()
    pipeline.recompute(session, renormalize=False)
    last = session.exec(select(DailyLoad).order_by(DailyLoad.date.desc())).scalars().first()
    assert last.date == dt.date(2026, 9, 10)


def test_real_ctrl_c_mid_backfill_is_caught_up(session):
    from training.garmin.backfill import backfill
    from training.garmin.client import GarminClient

    from .test_sync import TODAY, FakeGarmin, make_activity

    pipeline.set_threshold(session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=150.0)
    api = FakeGarmin([make_activity(2001, dt.date(2026, 8, 5)), make_activity(2002, dt.date(2026, 9, 2))])
    client = GarminClient(api, rate_limit_s=0, sleep=lambda s: None)
    api.fail = {"get_sleep_data": KeyboardInterrupt}  # dies inside the August month, after its activities
    with pytest.raises(KeyboardInterrupt):
        backfill(session, client, 2, TODAY)
    session.rollback()
    api.fail = {}
    backfill(session, client, 2, TODAY)
    pipeline.update_after_sync(session, [], today=TODAY)
    ids = {r.activity_id for r in session.exec(select(ActivityMetric)).scalars()}
    assert len(ids) == 2


def test_failed_metric_keeps_its_marker(session, monkeypatch):
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    add_activity(session, 1, dt.date(2026, 9, 1))
    add_activity(session, 2, dt.date(2026, 9, 2))
    pipeline.recompute(session, renormalize=False)
    repo.set_state_json(session, "metrics_dirty_activities", [1, 2])
    session.commit()
    real = pipeline.compute_activity_metrics
    broken_id = session.execute(select(Activity.id).where(Activity.garmin_id == 2)).scalar_one()

    def flaky(s, activity_id):
        if activity_id == broken_id:
            raise RuntimeError("boom")
        return real(s, activity_id)

    monkeypatch.setattr(pipeline, "compute_activity_metrics", flaky)
    result = pipeline.update_after_sync(session, [], today=dt.date(2026, 9, 3))
    assert len(result.errors) == 1
    assert repo.get_state_json(session, "metrics_dirty_activities") == [2]


@pytest.mark.parametrize(("offset", "recomputed"), [(-1, False), (0, True), (27, True), (28, False)])
def test_wellness_window_edges(session, offset, recomputed):
    """Dirty wellness day W → activities on W..W+27 (inverse of rest_hr_for's day−27..day)."""
    w = dt.date(2026, 3, 10)
    pipeline.set_threshold(session, sport="bike", valid_from=dt.date(2026, 1, 1), lthr=LTHR)
    add_activity(session, 1, w + dt.timedelta(days=offset))
    pipeline.recompute(session, renormalize=False)
    repo.set_state_json(session, "metrics_dirty_wellness_days", [w.isoformat()])
    session.commit()
    result = pipeline.update_after_sync(session, [], today=w + dt.timedelta(days=40))
    assert result.metrics_computed == (1 if recomputed else 0)
