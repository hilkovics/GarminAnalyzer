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
