"""Commutes (METRICS §2.6): fatigue yes, training no – the rule, pipeline exclusions, coach inputs (§10)."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training import pipeline, planning
from training.coach import season
from training.commute import COMMUTE_MAX_MOVING_S, commute_expr, is_commute
from training.db.models import Activity, ActivityMetric, BestEffort, DailyLoad, PlannedWorkout
from training.db.session import make_engine
from training.services import activities as svc
from training.services.dto import CommuteIn
from training.services.errors import NotFoundError

from .seeding import BIKE_LTHR, TODAY, add_activity, seeded_db

MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())  # 2026-09-14; the scenario run is on it
TUESDAY = MONDAY + dt.timedelta(days=1)
LAST_WEEK = MONDAY - dt.timedelta(days=6)  # Tuesday of the previous week


@pytest.fixture
def session(tmp_path):
    engine = make_engine(seeded_db(tmp_path))
    with Session(engine) as s:
        yield s
    engine.dispose()


def commute(session: Session, garmin_id: int, day: dt.date, seconds: int = 900, **kwargs) -> int:
    activity_id = add_activity(session, garmin_id, day, sport="bike", hr=BIKE_LTHR, seconds=seconds, **kwargs)
    pipeline.recompute(session, renormalize=False, end=TODAY)
    return activity_id


# --- rule -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sport", "moving", "duration", "override", "expected"),
    [
        ("bike", 1499.0, None, None, True),
        ("bike", COMMUTE_MAX_MOVING_S, None, None, False),  # strictly shorter than 25 min
        ("bike", None, 1000.0, None, True),  # total time when there is no moving time
        ("bike", None, None, None, False),
        ("run", 600.0, None, None, False),  # the rule is for rides only
        ("run", 3600.0, None, True, True),  # the override wins for any sport
        ("bike", 600.0, None, False, False),
    ],
)
def test_rule(sport, moving, duration, override, expected):
    assert is_commute(sport, moving, duration, override) is expected


def test_sql_expression_agrees_with_the_rule(session):
    commute(session, 9001, TUESDAY)
    commute(session, 9002, TUESDAY, seconds=1800)
    commute(session, 9003, TUESDAY, commute=True, seconds=1800)
    rows = session.execute(select(Activity, commute_expr())).all()
    assert rows and all(
        bool(flag) == is_commute(a.sport, a.moving_s, a.duration_s, a.commute_override) for a, flag in rows
    )
    assert sum(bool(flag) for _, flag in rows) == 2


# --- pipeline -------------------------------------------------------------------------------------------


def test_commute_load_is_fatigue_but_no_progress_values(session):
    activity_id = commute(session, 9001, TUESDAY)
    metric = session.get(ActivityMetric, activity_id)
    assert metric is not None and metric.load_primary and metric.load_primary > 0
    assert session.get(DailyLoad, TUESDAY).load_total == pytest.approx(metric.load_primary)
    assert (metric.steady_state, metric.ef, metric.decoupling_pct, metric.pace_at_ref_hr_day) == (None,) * 4
    efforts = session.execute(select(BestEffort).where(BestEffort.activity_id == activity_id)).all()
    assert efforts == []


def test_override_false_makes_a_short_ride_training(session):
    activity_id = commute(session, 9001, TUESDAY, commute=False)
    efforts = session.execute(select(BestEffort).where(BestEffort.activity_id == activity_id)).all()
    assert efforts  # best efforts like any other ride


# --- coach ----------------------------------------------------------------------------------------------


def test_week_done_load_and_active_days_leave_commutes_out(session):
    before = planning.build_context(session, TODAY)
    commute(session, 9001, TUESDAY)
    after = planning.build_context(session, TODAY)
    assert session.get(DailyLoad, TUESDAY).load_total > 0
    assert after.load_done_week == pytest.approx(before.load_done_week)
    assert after.bike_load_done_week == pytest.approx(before.bike_load_done_week)
    assert TUESDAY not in after.active_days_week
    assert after.yesterday_max_if == before.yesterday_max_if


def test_training_target_is_t_minus_the_average_commuting(session):
    activity_id = commute(session, 9001, LAST_WEEK)
    load = session.get(ActivityMetric, activity_id).load_primary
    week = planning.week_target(session, TODAY)
    total = season.weekly_target(planning._ctl_before(session, MONDAY), season.week_info(MONDAY, None))
    assert week.commute_load == pytest.approx(load * 7 / 28)
    assert week.target_load == pytest.approx(max(0.0, total - load * 7 / 28))
    assert week.run_target + week.bike_target == pytest.approx(week.target_load)


def test_run_share_ignores_commutes(session):
    before = planning.run_share_for(session, TODAY)
    commute(session, 9001, LAST_WEEK, seconds=1400)
    assert planning.run_share_for(session, TODAY) == pytest.approx(before)


def test_a_commute_never_completes_a_planned_ride(session):
    session.add(PlannedWorkout(date=TUESDAY, sport="bike", name="Endurance", status="planned", structure={}))
    session.commit()
    commute(session, 9001, TUESDAY)
    assert planning.match_completed(session, TODAY) == 0
    commute(session, 9002, TUESDAY, seconds=3600)  # a real training ride the same day
    assert planning.match_completed(session, TODAY) == 1
    row = session.execute(select(PlannedWorkout).where(PlannedWorkout.date == TUESDAY)).scalar_one()
    assert row.status == "done"
    assert session.get(Activity, row.completed_activity_id).garmin_id == 9002


# --- service / API -----------------------------------------------------------------------------------------


def test_set_commute_overrides_and_recomputes(session):
    activity_id = commute(session, 9001, TUESDAY)
    dto = svc.get_activity(session, activity_id).summary
    assert (dto.is_commute, dto.commute_override) == (True, None)

    dto = svc.set_commute(session, activity_id, CommuteIn(commute=False), today=TODAY)
    assert (dto.is_commute, dto.commute_override) == (False, False)
    assert session.execute(select(BestEffort).where(BestEffort.activity_id == activity_id)).all()

    dto = svc.set_commute(session, activity_id, CommuteIn(commute=None), today=TODAY)
    assert (dto.is_commute, dto.commute_override) == (True, None)
    assert not session.execute(select(BestEffort).where(BestEffort.activity_id == activity_id)).all()


def test_set_commute_unknown_activity(session):
    with pytest.raises(NotFoundError):
        svc.set_commute(session, 999_999, CommuteIn(commute=True), today=TODAY)
