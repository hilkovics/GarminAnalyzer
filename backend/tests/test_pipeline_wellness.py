"""training.pipeline_wellness: readiness persisted into daily_load after the PMC (METRICS §8). Offline."""

import datetime as dt

import pytest
from sqlalchemy import select

from training import pipeline
from training.db import repo
from training.db.models import DailyLoad
from training.pipeline_wellness import correlation_activities, wellness_frame

START = dt.date(2026, 6, 1)


def _wellness(session, day: dt.date, **values) -> None:
    repo.upsert_wellness(session, {"date": day, **values})
    session.commit()


def _readiness(session) -> dict[dt.date, float | None]:
    return {r.date: r.readiness for r in session.execute(select(DailyLoad)).scalars()}


def test_readiness_for_every_wellness_day_and_null_elsewhere(session):
    for i in range(40):
        _wellness(session, START + dt.timedelta(days=i), rhr=50.0, sleep_score=80.0, body_battery_wake=70.0)
    last = START + dt.timedelta(days=45)  # 6 trailing days without wellness
    pipeline.recompute(session, renormalize=False, end=last)
    scores = _readiness(session)
    assert len(scores) == 46
    for i in range(40):
        assert scores[START + dt.timedelta(days=i)] is not None
    for i in range(40, 46):
        assert scores[START + dt.timedelta(days=i)] is None
    # no training → TSB 0 → form 50; no RHR baseline for the first 7 days → sleep/BB/form only
    assert scores[START] == pytest.approx((0.3 * 80 + 0.2 * 70 + 0.2 * 50) / 0.7)
    # from day 7 on the RHR baseline exists: rhr == median → RHR score 100
    assert scores[START + dt.timedelta(days=10)] == pytest.approx(0.3 * 100 + 0.3 * 80 + 0.2 * 70 + 0.2 * 50)


def test_readiness_updates_after_sync_when_wellness_changes(session):
    for i in range(20):
        _wellness(session, START + dt.timedelta(days=i), rhr=50.0, sleep_score=80.0)
    today = START + dt.timedelta(days=19)
    pipeline.update_after_sync(session, today=today)
    before = _readiness(session)[today]
    _wellness(session, today, rhr=58.0, sleep_score=80.0)  # +8 bpm → RHR score 0
    pipeline.update_after_sync(session, today=today)
    after = _readiness(session)[today]
    assert after < before
    assert after == pytest.approx((0.3 * 0 + 0.3 * 80 + 0.2 * 50) / 0.8)


def test_frames_on_empty_db(session):
    assert wellness_frame(session).empty
    assert correlation_activities(session).empty
    assert pipeline.recompute(session, renormalize=False).daily_load_days == 0
