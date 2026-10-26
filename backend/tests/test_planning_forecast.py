"""Predictions glue, service, API and Telegram line (METRICS §11.5) on the seeded DB."""

import datetime as dt

import pytest
from sqlmodel import Session

from training import planning_forecast as pfc
from training.coach import fitness, forecast as fc
from training.coach.workout import to_structure
from training.db import repo
from training.db.models import Athlete, DailyLoad, PlannedWorkout
from training.db.session import make_engine
from training.services import forecast as svc, notify

from .seeding import TODAY, make_client, seeded_db


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def good_weeks(session, weekday_offset=1):
    """8 weeks of good wellness on the weekday of TODAY + `weekday_offset`."""
    day = TODAY + dt.timedelta(days=weekday_offset)
    for k in range(1, 9):
        repo.upsert_wellness(
            session,
            {
                "date": day - dt.timedelta(weeks=k),
                "rhr": 48.0,
                "sleep_score": 90.0,
                "body_battery_wake": 90.0,
            },
        )
    other = {"rhr": 50.0, "sleep_score": 40.0, "body_battery_wake": 30.0}  # poor nights on the other days
    for k in range(1, 57):  # (also a 28-day RHR baseline of 50 for today)
        if (TODAY - dt.timedelta(days=k)).weekday() != day.weekday():
            repo.upsert_wellness(session, {"date": TODAY - dt.timedelta(days=k), **other})
    session.commit()


def test_outlook_uses_typical_weekdays_and_marks_the_best_day(session):
    good_weeks(session)
    result = pfc.outlook(session, TODAY)
    assert [d.day for d in result.days] == [TODAY + dt.timedelta(days=i) for i in range(1, 8)]
    thursday = result.days[0]
    assert thursday.typical["rhr"] == 48.0 and thursday.readiness is not None and thursday.readiness >= 70
    assert result.best == [thursday.day]
    assert all(d.readiness is None or d.readiness < 70 for d in result.days[1:])


def test_rest_days_are_never_best(session):
    good_weeks(session)
    athlete = session.get(Athlete, 1) or Athlete()
    athlete.preferred_days = {"thu": "rest"}
    session.add(athlete)
    session.commit()
    result = pfc.outlook(session, TODAY)
    assert result.best == [] and (TODAY + dt.timedelta(days=1)) not in result.available


def test_todays_pending_plan_counts_as_load(session):
    base = pfc._load_today(session, TODAY)
    workout = fitness.easy_run(40)
    session.add(
        PlannedWorkout(
            date=TODAY,
            sport="run",
            name="x",
            status="planned",
            structure=to_structure(workout),
            estimated_load=30.0,
        )
    )
    session.add(PlannedWorkout(date=TODAY, sport="run", name="y", status="done", estimated_load=99.0))
    session.commit()
    assert pfc._load_today(session, TODAY) == pytest.approx(base + 30.0)
    stored = session.get(DailyLoad, TODAY)
    assert base == pytest.approx(stored.load_total or 0.0)


def test_service_api_and_telegram_note(engine, session, monkeypatch):
    effect = pfc.sleep_effect(session)
    assert effect.status == fc.INSUFFICIENT  # the seeded runs have no pace at reference HR
    body = make_client(engine).get("/api/plan/forecast").json()
    assert body["sleep_effect"]["status"] == "insufficient" and body["sleep_effect"]["min_n"] == 30
    assert body["note"] is None and len(body["days"]) == 7
    assert {"readiness", "band", "load", "tsb", "sleep_s", "rhr", "available", "best"} <= set(body["days"][0])

    reliable = fc.SleepEffect(fc.RELIABLE, 50, 0.05, 0.02, 0.08, 7 * 3600.0, 3.0)
    monkeypatch.setattr(pfc, "sleep_effect", lambda session: reliable)
    repo.upsert_wellness(session, {"date": TODAY, "sleep_s": 5 * 3600.0})
    session.commit()
    dto = svc.get_forecast(session, TODAY)
    assert dto.note is not None and dto.note.delta_s_per_km == 11
    good_weeks(session)
    text = notify.morning_message(session, TODAY).text
    assert dto.note.text in text and "Výhľad: najlepšie dni na kvalitný tréning – št 17. 9." in text


def test_ctl_atl_and_today_load_wiring_and_a_sync_gap(session):
    yesterday = session.get(DailyLoad, TODAY - dt.timedelta(days=1))
    yesterday.ctl, yesterday.atl = 60.0, 40.0
    session.add(yesterday)
    session.commit()
    load = pfc._load_today(session, TODAY)
    first = pfc.outlook(session, TODAY).days[0]
    ctl, atl = 60 + (load - 60) / 42, 40 + (load - 40) / 7
    assert first.tsb == pytest.approx(ctl - atl)
    # a sync gap: today − 1 and today − 2 missing, the last stored day is today − 3
    for back in (1, 2):
        session.delete(session.get(DailyLoad, TODAY - dt.timedelta(days=back)))
    last = session.get(DailyLoad, TODAY - dt.timedelta(days=3))
    last.ctl, last.atl = 60.0, 40.0
    session.add(last)
    session.commit()
    ctl, atl = fc.carry_forward(60.0, 40.0, 2)
    ctl, atl = ctl + (load - ctl) / 42, atl + (load - atl) / 7
    assert pfc.outlook(session, TODAY).days[0].tsb == pytest.approx(ctl - atl)


def test_pushed_counts_rest_does_not(session):
    base = pfc._load_today(session, TODAY)
    session.add(PlannedWorkout(date=TODAY, sport="run", name="p", status="pushed", estimated_load=20.0))
    session.add(PlannedWorkout(date=TODAY, sport="rest", name="r", status="planned", estimated_load=50.0))
    session.commit()
    assert pfc._load_today(session, TODAY) == pytest.approx(base + 20.0)


def test_today_baselines(session):
    good_weeks(session)
    rhr, sleep = pfc._today_baselines(session, TODAY)
    assert rhr == 50.0 and sleep is None  # the 28 days before today: RHR 50 on most days, no sleep_s
    for k in range(1, 29):
        repo.upsert_wellness(session, {"date": TODAY - dt.timedelta(days=k), "sleep_s": 7 * 3600.0})
    session.commit()
    assert pfc._today_baselines(session, TODAY)[1] == 7 * 3600.0


def test_a_forecast_error_never_drops_the_morning_message(session, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("bootstrap failed")

    monkeypatch.setattr(svc, "get_forecast", boom)
    text = notify.morning_message(session, TODAY).text
    assert text.startswith("Dobré ráno") and "Výhľad" not in text
