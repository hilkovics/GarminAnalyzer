"""Fitness coach glue (METRICS §11) on the seeded DB: weeks and blocks, menu state, yesterday, sleep wait."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training import planning, planning_fitness as pf
from training.coach import fitness
from training.coach.workout import to_structure
from training.db import repo
from training.db.models import CoachBlock, CoachWeek, DailyLoad, Goal, PlannedWorkout
from training.db.session import make_engine
from training.db.state_keys import LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE

from .seeding import TODAY, add_activity, seeded_db

pytestmark = pytest.mark.fitness_coach

MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())  # 2026-09-14


@pytest.fixture
def session(tmp_path):
    engine = make_engine(seeded_db(tmp_path))
    with Session(engine) as s:
        repo.set_state(s, LAST_ACTIVITY_SYNC, TODAY.isoformat())
        repo.set_state(s, LAST_WELLNESS_DATE, TODAY.isoformat())
        s.commit()
        yield s
    engine.dispose()


def readiness(session, day, value):
    row = session.get(DailyLoad, day)
    row.readiness = value
    session.add(row)
    session.commit()


def sleep(session, day, seconds=7 * 3600):
    repo.upsert_wellness(session, {"date": day, "sleep_s": seconds})
    session.commit()


def done(session, day, slot, key="fit_easy"):
    structure = to_structure(fitness.easy_run(30)) | {"slot": slot, "key": key}
    session.add(PlannedWorkout(date=day, sport="run", name=key, status="done", structure=structure))
    session.commit()


# --- weeks and blocks ---------------------------------------------------------------------------------------


def test_first_week_opens_a_block_with_at_least_90_minutes(session):
    week = pf.ensure_week(session, MONDAY)
    block = session.execute(select(CoachBlock)).scalar_one()
    assert block.start_monday == MONDAY and block.base_s == 5400  # 20 min a week before → the floor
    assert (week.week_no, week.target_s, week.brake) == (1, 5400, None)
    assert pf.ensure_week(session, MONDAY) is not None and len(session.execute(select(CoachWeek)).all()) == 1


def test_later_weeks_fill_the_gap_and_apply_brakes(session):
    pf.ensure_week(session, MONDAY)
    for day in (MONDAY + dt.timedelta(days=i) for i in range(7)):  # a bad week: readiness 50 → hold
        if session.get(DailyLoad, day) is None:
            session.add(DailyLoad(date=day))
        readiness(session, day, 50.0)
    week4 = pf.ensure_week(session, MONDAY + dt.timedelta(weeks=3))
    weeks = session.execute(select(CoachWeek).order_by(CoachWeek.monday)).scalars().all()
    assert [w.week_no for w in weeks] == [1, 2, 3, 4]
    assert weeks[1].brake == "hold" and weeks[1].base_s == pytest.approx(5400)
    assert weeks[2].base_s == pytest.approx(5400 * 1.07)
    assert week4.recovery and week4.target_s == pytest.approx(5400 * 1.07**2 * 0.7)


def test_a_new_block_after_twelve_weeks(session):
    pf.ensure_week(session, MONDAY)
    week13 = pf.ensure_week(session, MONDAY + dt.timedelta(weeks=12))
    assert week13.week_no == 1 and len(session.execute(select(CoachBlock)).all()) == 2


# --- §11.2 inputs -------------------------------------------------------------------------------------------


def test_open_items_count_done_slots_and_unplanned_runs(session):
    assert pf.open_items(session, MONDAY) == frozenset("kde")
    # the seeded Monday run (no plan) fills Ľ; a done K on Tuesday
    done(session, MONDAY + dt.timedelta(days=1), "k", "fit_vo2")
    assert pf.open_items(session, TODAY) == frozenset("d")


def test_hard_yesterday_from_a_done_long_run_or_a_long_ride(session):
    assert pf.hard_yesterday(session, TODAY) is None
    done(session, TODAY - dt.timedelta(days=1), "d", "fit_long")
    assert pf.hard_yesterday(session, TODAY) == "dlhší beh"
    # (the seeded Wednesday ride is at the bike LTHR: IF ≈ 1 → "náročný tréning" on Thursday)
    assert pf.hard_yesterday(session, TODAY + dt.timedelta(days=1)) == "náročný tréning"
    add_activity(
        session, 9100, TODAY + dt.timedelta(days=1), sport="bike", hr=120.0, seconds=5400, commute=False
    )
    assert pf.hard_yesterday(session, TODAY + dt.timedelta(days=2)) == "dlhá jazda na bicykli"
    add_activity(session, 9101, TODAY + dt.timedelta(days=3), sport="bike", hr=120.0, seconds=900)  # commute
    assert pf.hard_yesterday(session, TODAY + dt.timedelta(days=4)) is None


def test_available_days_from_preferred_days():
    athlete = type(
        "A", (), {"preferred_days": {"mon": "rest", "wed": {"role": "rest"}, "sat": {"role": "long"}}}
    )()
    days = pf.available_days(athlete, MONDAY)
    assert MONDAY not in days and MONDAY + dt.timedelta(days=2) not in days and len(days) == 5


# --- plan_day in fitness mode -------------------------------------------------------------------------------


def test_green_day_plans_quality_and_marks_the_mode(session, monkeypatch):
    monkeypatch.setattr(pf, "now_local", lambda: dt.datetime.combine(TODAY, dt.time(9)))
    sleep(session, TODAY)
    readiness(session, TODAY, 80.0)
    row, decision = planning.plan_day(session, TODAY)
    assert decision is not None and decision.rule == 3
    assert row.structure["slot"] == "k" and row.structure["mode"] == "fitness"
    assert row.structure["waiting_sleep"] is False and not planning.is_provisional(row)
    assert "Zelený deň (pripravenosť 80 (zelená))" in row.reason


def test_without_sleep_before_noon_the_plan_waits_and_is_redone(session, monkeypatch):
    monkeypatch.setattr(pf, "now_local", lambda: dt.datetime.combine(TODAY, dt.time(9, 5)))
    readiness(session, TODAY, 80.0)
    row, _ = planning.plan_day(session, TODAY)
    assert row.structure["waiting_sleep"] is True and planning.is_provisional(row)
    sleep(session, TODAY)  # the watch synced
    redone = planning.nightly(session, TODAY)
    assert redone.structure["waiting_sleep"] is False and not planning.is_provisional(redone)


def test_from_noon_the_decision_is_final_without_sleep(session, monkeypatch):
    monkeypatch.setattr(pf, "now_local", lambda: dt.datetime.combine(TODAY, dt.time(12, 0)))
    row, _ = planning.plan_day(session, TODAY)
    assert row.structure["waiting_sleep"] is False and not planning.is_provisional(row)


def test_a_race_goal_switches_back_to_the_race_rules(session, monkeypatch):
    monkeypatch.undo()  # drop the conftest patch too: the real mode_for decides
    assert planning.mode_for(session, TODAY) == "fitness"
    session.add(Goal(race_date=TODAY + dt.timedelta(days=60), distance_m=10000.0, sport="run"))
    session.commit()
    assert planning.mode_for(session, TODAY) == "race"


def test_red_day_rest_and_bike_override(session, monkeypatch):
    monkeypatch.setattr(pf, "now_local", lambda: dt.datetime.combine(TODAY, dt.time(10)))
    sleep(session, TODAY, 4 * 3600)
    readiness(session, TODAY, 30.0)
    row, decision = planning.plan_day(session, TODAY)
    assert row.sport == "rest" and decision.rule == 1
    row, decision = planning.plan_day(session, TODAY, sport_override="bike")
    assert row.sport == "bike" and row.structure["key"] == "fit_ride"
    assert row.structure["steps"][0]["duration_s"] == fitness.RIDE_MIN * 60


# --- services (week menu, waiting flag) ---------------------------------------------------------------------


def test_week_service_shows_the_menu_and_block(session, monkeypatch):
    from training.services import plan as svc

    monkeypatch.setattr(pf, "now_local", lambda: dt.datetime.combine(TODAY, dt.time(9)))
    done(session, MONDAY + dt.timedelta(days=1), "k", "fit_vo2")
    week = svc.get_week(session, TODAY, today=TODAY)
    assert week.mode == "fitness" and week.fitness is not None
    f = week.fitness
    assert (f.week_no, f.block_weeks, f.block_start, f.target_s) == (1, 12, MONDAY, 5400)
    menu = {m.slot: m for m in f.menu}
    assert menu["k"].done_date == MONDAY + dt.timedelta(days=1)
    assert menu["e"].done_date == MONDAY  # the seeded unplanned Monday run
    assert menu["d"].done_date is None and menu["d"].minutes == 45  # 90 min × 0.4 = 36 → clamp 45
    # a past week before the first block and a future week get no §11 row (none is created)
    assert svc.get_week(session, MONDAY - dt.timedelta(weeks=3), today=TODAY).fitness is None
    assert svc.get_week(session, MONDAY + dt.timedelta(weeks=1), today=TODAY).fitness is None
    assert len(session.execute(select(CoachWeek)).all()) == 1


def test_today_service_reports_the_sleep_wait(session, monkeypatch):
    from training.services import plan as svc

    monkeypatch.setattr(pf, "now_local", lambda: dt.datetime.combine(TODAY, dt.time(8)))
    decision = svc.get_today(session, TODAY)
    assert decision.mode == "fitness" and decision.waiting_sleep and decision.workout.provisional
