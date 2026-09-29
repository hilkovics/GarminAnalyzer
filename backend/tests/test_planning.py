"""training.planning: coach glue – context from the DB, persisted plans, matching, status (METRICS §10)."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training import planning
from training.db.models import DailyLoad, Goal, PlannedWorkout
from training.db.session import make_engine

from .seeding import RUN_ID, TODAY, add_activity, seeded_db


@pytest.fixture
def session(tmp_path):
    engine = make_engine(seeded_db(tmp_path))
    with Session(engine) as s:
        yield s
    engine.dispose()


def _set_day(session, day: dt.date, **values) -> None:
    row = session.get(DailyLoad, day)
    for key, value in values.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()


def test_nightly_plans_today_once(session):
    row = planning.nightly(session, TODAY)
    assert row.date == TODAY and row.status == "planned" and row.reason
    again = planning.nightly(session, TODAY)
    assert again.id == row.id
    assert len(planning.planned_for(session, TODAY)) == 1


def test_context_reads_the_db(session):
    ctx = planning.build_context(session, TODAY)
    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    assert ctx.info.monday == monday
    assert ctx.info.phase == "base" and ctx.goal_sport is None  # no goal → the no-goal cycle
    assert ctx.load_done_week > 0  # Monday run of the seeded week
    assert monday in ctx.active_days_week
    assert ctx.tsb == pytest.approx(session.get(DailyLoad, TODAY).tsb)
    assert ctx.weekly_target > 0


def test_low_readiness_gives_rest_or_recovery(session):
    _set_day(session, TODAY, readiness=30.0)
    row, decision = planning.plan_day(session, TODAY)
    assert decision is not None and decision.rule == 1
    assert row.sport == "rest" or planning.workout_of(row).key == "recovery"
    assert "30" in row.reason


def test_decision_changes_with_readiness(session):
    _set_day(session, TODAY, readiness=85.0)
    good, _ = planning.plan_day(session, TODAY)
    _set_day(session, TODAY, readiness=30.0)
    bad, _ = planning.plan_day(session, TODAY, force=True)
    assert (good.name, good.estimated_load) != (bad.name, bad.estimated_load)
    assert len(planning.planned_for(session, TODAY)) == 1  # replaced, not duplicated


def test_goal_sets_the_phase(session):
    session.add(Goal(race_date=TODAY + dt.timedelta(days=40), distance_m=10000.0, sport="run"))
    session.commit()
    assert planning.build_context(session, TODAY).info.phase == "build"


def test_sport_override_and_validation(session):
    row, _ = planning.plan_day(session, TODAY, sport_override="bike")
    assert row.sport in ("bike", "rest")
    with pytest.raises(planning.PlanError):
        planning.plan_day(session, TODAY, sport_override="swim")


def test_match_completed_by_date_and_sport(session):
    row, _ = planning.plan_day(session, TODAY, sport_override="run", force=True)
    if row.sport == "rest":
        pytest.skip("template gives rest today")
    assert planning.match_completed(session, TODAY) == 0
    activity_id = add_activity(session, RUN_ID + 99, TODAY, sport=row.sport)
    assert planning.match_completed(session, TODAY) == 1
    session.refresh(row)
    assert row.status == "done" and row.completed_activity_id == activity_id


def test_done_workout_is_not_replaced(session):
    row, _ = planning.plan_day(session, TODAY)
    planning.set_status(session, row.id, "done")
    with pytest.raises(planning.PlanError):
        planning.plan_day(session, TODAY, force=True)
    kept, decision = planning.plan_day(session, TODAY)  # no force: the existing row is returned
    assert kept.id == row.id and decision is None


def test_set_status(session):
    row, _ = planning.plan_day(session, TODAY)
    assert planning.set_status(session, row.id, "skipped").status == "skipped"
    assert planning.set_status(session, row.id, "planned").status == "planned"
    with pytest.raises(planning.PlanError):
        planning.set_status(session, row.id, "pushed")
    with pytest.raises(LookupError):
        planning.set_status(session, 99999, "done")


def test_season_weeks_projection(session):
    session.add(Goal(race_date=TODAY + dt.timedelta(days=16 * 7), distance_m=21097.5, sport="run"))
    session.commit()
    weeks = planning.season_weeks(session, TODAY, 17)
    assert [w.phase for w in weeks][0] == "base" and weeks[-2].phase == "taper"
    assert all(w.target_load >= 0 for w in weeks)


def test_rest_rows_are_never_matched(session):
    session.add(PlannedWorkout(date=TODAY, sport="rest", name="Voľno", structure={"sport": "rest", "name": "Voľno"}))
    session.commit()
    add_activity(session, RUN_ID + 98, TODAY, sport="run")
    planning.match_completed(session, TODAY)
    rows = session.execute(select(PlannedWorkout).where(PlannedWorkout.sport == "rest")).scalars().all()
    assert all(r.status == "planned" for r in rows)
