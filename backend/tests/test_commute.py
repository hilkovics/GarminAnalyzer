"""Commutes (METRICS §2.6): fatigue yes, training no – the rule, pipeline exclusions, coach inputs (§10)."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training import pipeline, pipeline_wellness, planning
from training.coach import season
from training.commute import COMMUTE_MAX_MOVING_S, commute_expr, is_commute
from training.db.models import Activity, ActivityMetric, BestEffort, CurveSnapshot, DailyLoad, PlannedWorkout
from training.db.session import make_engine
from training.services import activities as svc, plan as plan_svc, progress as progress_svc
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


def test_indoor_ride_is_never_a_commute_by_the_rule():
    assert is_commute("bike", 600.0, None, None, is_indoor=True) is False
    assert is_commute("bike", 600.0, None, True, is_indoor=True) is True  # the override still wins


def test_sql_expression_agrees_with_the_rule(session):
    commute(session, 9001, TUESDAY)
    commute(session, 9002, TUESDAY, seconds=1800)
    commute(session, 9003, TUESDAY, commute=True, seconds=1800)
    indoor = session.get(Activity, commute(session, 9004, TUESDAY))
    indoor.is_indoor = True
    session.add(indoor)
    session.commit()
    rows = session.execute(select(Activity, commute_expr())).all()
    assert rows and all(
        bool(flag) == is_commute(a.sport, a.moving_s, a.duration_s, a.commute_override, a.is_indoor)
        for a, flag in rows
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


def test_reclassifying_a_matched_ride_as_commute_reopens_the_workout(session):
    session.add(PlannedWorkout(date=TUESDAY, sport="bike", name="Endurance", status="planned", structure={}))
    session.commit()
    activity_id = commute(session, 9001, TUESDAY, commute=False)  # a short training ride
    assert planning.match_completed(session, TODAY) == 1
    svc.set_commute(session, activity_id, CommuteIn(commute=True), today=TODAY)
    row = session.execute(select(PlannedWorkout).where(PlannedWorkout.date == TUESDAY)).scalar_one()
    assert (row.status, row.completed_activity_id) == ("planned", None)


def test_last_run_becoming_a_commute_empties_its_curve_months(session):
    runs = session.execute(select(Activity).where(Activity.sport == "run")).scalars().all()
    for run in runs:
        run.commute_override = True
        session.add(run)
    session.commit()
    svc.set_commute(session, runs[-1].id, CommuteIn(commute=True), today=TODAY)
    month = f"{runs[-1].local_date:%Y-%m}"
    snapshot = session.execute(
        select(CurveSnapshot).where(CurveSnapshot.month == month, CurveSnapshot.sport == "run")
    ).scalar_one()
    assert snapshot.curve["bins"] == {} and snapshot.curve["pace_at_ref_hr"] is None


# --- remaining exclusions (review: one test per filter) ---------------------------------------------------


def test_proposal_frame_and_correlation_days_leave_commutes_out(session):
    activity_id = commute(session, 9001, TUESDAY)
    assert activity_id not in set(progress_svc._activity_frame(session, "bike")["activity_id"])
    assert activity_id not in set(pipeline_wellness.correlation_activities(session)["activity_id"])
    training_id = commute(session, 9002, TUESDAY, commute=False)
    assert training_id in set(progress_svc._activity_frame(session, "bike")["activity_id"])
    assert training_id in set(pipeline_wellness.correlation_activities(session)["activity_id"])


def test_week_view_shows_training_and_commute_load_apart(session):
    activity_id = commute(session, 9001, TUESDAY)
    load = session.get(ActivityMetric, activity_id).load_primary
    week = plan_svc.get_week(session, TODAY, today=TODAY)
    tuesday = next(d for d in week.days if d.date == TUESDAY)
    assert (tuesday.activities, tuesday.actual_load) == (0, 0.0)
    assert tuesday.commute_load == pytest.approx(load)
    assert week.done_load == pytest.approx(sum(d.actual_load for d in week.days))


def test_season_projection_keeps_t_and_targets_subtract_c():
    monday = dt.date(2026, 9, 14)
    plain = season.season_plan(monday, 3, 50.0, None, 0.5)
    commuting = season.season_plan(monday, 3, 50.0, None, 0.5, commute_load=40.0)
    assert [w.ctl_start for w in commuting] == pytest.approx([w.ctl_start for w in plain])
    for a, b in zip(plain, commuting, strict=True):
        assert b.target_load == pytest.approx(max(0.0, a.target_load - 40.0))
        assert b.run_target + b.bike_target == pytest.approx(b.target_load)
        assert b.commute_load == 40.0


def test_taper_target_subtracts_c_once():
    race = dt.date(2026, 10, 1)  # Thursday: the week of 2026-09-28 has d = 3 → taper
    monday = dt.date(2026, 9, 28)
    plain = season.season_plan(monday, 1, 50.0, race, 0.5, pre_taper_target=400.0)
    commuting = season.season_plan(monday, 1, 50.0, race, 0.5, pre_taper_target=400.0, commute_load=30.0)
    assert plain[0].phase == "taper"
    assert commuting[0].target_load == pytest.approx(max(0.0, plain[0].target_load - 30.0))
    assert plain[0].target_load == pytest.approx(200.0)
