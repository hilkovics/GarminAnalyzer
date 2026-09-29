"""Phase-4 pipeline wiring: activity_metric progress fields, best_effort rows, curve snapshots. Offline."""

import datetime as dt

import numpy as np
import pandas as pd
from sqlalchemy import select

from training import pipeline
from training.db import repo
from training.db.models import ActivityMetric, BestEffort, CurveSnapshot

UTC = dt.UTC


def add_run(session, garmin_id, day, *, seconds=3600, hr=150.0, speed=3.0):
    aid = repo.upsert_activity(
        session,
        {"garmin_id": garmin_id, "sport": "run", "sub_sport": "running", "is_race": False, "is_indoor": False,
         "start_utc": dt.datetime.combine(day, dt.time(6), tzinfo=UTC), "local_date": day,
         "duration_s": float(seconds)},
    )  # fmt: skip
    t = np.arange(seconds)
    repo.replace_streams(
        session, aid,
        pd.DataFrame({"t": t, "hr": np.full(seconds, hr), "speed": np.full(seconds, speed),
                      "alt": np.full(seconds, 100.0), "distance": t * speed, "moving": True}),
    )  # fmt: skip
    session.commit()
    return aid


def test_progress_fields_efforts_and_curves_are_persisted(session):
    pipeline.set_threshold(
        session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=190.0, threshold_speed=3.2
    )
    days = [dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(0, 20, 2)]
    ids = [add_run(session, 100 + i, d) for i, d in enumerate(days)]
    result = pipeline.recompute(session, renormalize=False, end=dt.date(2026, 9, 30))
    assert result.errors == []

    m = session.get(ActivityMetric, ids[0])
    assert m.steady_state is True  # 150 bpm = 0.79 · 190, constant
    assert m.ef == 180 / 150  # 3.0 m/s = 180 m/min at 150 bpm
    assert abs(m.decoupling_pct) < 1e-9
    efforts = session.exec(select(BestEffort).where(BestEffort.activity_id == ids[0])).scalars().all()
    assert {(e.kind, e.window_s) for e in efforts} >= {("gap_speed", 3600), ("hr", 1800)}
    assert next(e for e in efforts if (e.kind, e.window_s) == ("gap_speed", 600)).value == 3.0

    snaps = {s.month: s.curve for s in session.exec(select(CurveSnapshot)).scalars()}
    assert set(snaps) == {"2026-09"}
    assert snaps["2026-09"]["bins"] == {"150": 3.0}  # all aggregates in the 150 bin
    assert snaps["2026-09"]["ref_hr"] == 0.8 * 190


def test_threshold_change_refreshes_curve_reference(session):
    pipeline.set_threshold(session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=190.0)
    add_run(session, 1, dt.date(2026, 9, 10))
    pipeline.recompute(session, renormalize=False, end=dt.date(2026, 9, 30))
    pipeline.set_threshold(
        session, sport="run", valid_from=dt.date(2026, 9, 1), lthr=187.5, end=dt.date(2026, 9, 30)
    )
    session.expire_all()
    snap = session.exec(select(CurveSnapshot)).scalars().one()
    assert snap.curve["ref_hr"] == 0.8 * 187.5
    assert snap.curve["pace_at_ref_hr"] == 3.0  # 150 = ref bin [150, 155)


def test_month_snapshot_is_completed_after_rollover(session):
    """Review phase 4 blocker: sync 09-20, next sync in October → September's window must end 09-30."""
    pipeline.set_threshold(session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=190.0)
    first = [add_run(session, 200 + i, dt.date(2026, 8, 20) + dt.timedelta(days=3 * i)) for i in range(11)]
    pipeline.update_after_sync(session, [], today=dt.date(2026, 9, 20))
    add_run(session, 300, dt.date(2026, 10, 2))
    pipeline.update_after_sync(session, [300], today=dt.date(2026, 10, 2))
    incremental = {s.month: s.curve for s in session.exec(select(CurveSnapshot)).scalars()}
    pipeline.recompute(session, renormalize=False, end=dt.date(2026, 10, 2))
    session.expire_all()
    full = {s.month: s.curve for s in session.exec(select(CurveSnapshot)).scalars()}
    assert incremental["2026-09"] == full["2026-09"]
    assert first  # runs were seeded


def test_run_threshold_change_refreshes_months_without_runs(session):
    pipeline.set_threshold(session, sport="run", valid_from=dt.date(2026, 1, 1), lthr=190.0)
    add_run(session, 1, dt.date(2026, 7, 10))
    pipeline.recompute(session, renormalize=False, end=dt.date(2026, 9, 30))
    pipeline.set_threshold(
        session, sport="run", valid_from=dt.date(2026, 7, 1), lthr=180.0, end=dt.date(2026, 9, 30)
    )
    session.expire_all()
    refs = {s.month: s.curve["ref_hr"] for s in session.exec(select(CurveSnapshot)).scalars()}
    assert refs["2026-09"] == 0.8 * 180  # September has no runs, but its ref_hr must follow the new LTHR
