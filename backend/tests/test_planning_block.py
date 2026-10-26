"""Block progress glue and API (METRICS §11.4) on the seeded DB: baseline, weeks, check runs, summary."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training import pipeline, planning_block as pb, planning_fitness as pf
from training.coach import block_progress as bp, fitness
from training.coach.workout import to_structure
from training.db import repo
from training.db.models import Activity, ActivityMetric, BestEffort, CoachBlock, PlannedWorkout
from training.db.session import make_engine
from training.db.state_keys import LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE
from training.metrics.predictions import vdot
from training.services import coach_block as svc
from training.services.errors import NotFoundError

from .seeding import TODAY, add_activity, make_client, seeded_db

pytestmark = pytest.mark.fitness_coach

MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        repo.set_state(s, LAST_ACTIVITY_SYNC, TODAY.isoformat())
        repo.set_state(s, LAST_WELLNESS_DATE, TODAY.isoformat())
        s.commit()
        yield s


def done(session, day, slot, key, activity_id=None):
    workout = fitness.check_run() if key == pf.CHECK_KEY else fitness.easy_run(30)
    structure = to_structure(workout) | {"slot": slot, "key": key}
    session.add(
        PlannedWorkout(
            date=day,
            sport="run",
            name=key,
            status="done",
            structure=structure,
            completed_activity_id=activity_id,
        )
    )
    session.commit()


def test_baseline_is_the_day_before_the_block_and_stored(session):
    pf.ensure_week(session, MONDAY)
    block = session.execute(select(CoachBlock)).scalar_one()
    base = pb.baseline(session, block)
    assert base.day == MONDAY - dt.timedelta(days=1)
    assert base == pb.snapshot_on(session, MONDAY - dt.timedelta(days=1))
    assert base.vdot is not None and base.reference_date is not None  # the seeded 20-min runs
    assert bp.from_json(block.baseline) == base
    assert block.baseline["final"] is True  # the block's Monday sync has run
    block.baseline = bp.to_json(bp.Snapshot(base.day)) | {"final": True}  # a final value wins until a refresh
    assert pb.baseline(session, block) == bp.Snapshot(base.day)
    assert pb.refresh_baselines(session) == 1 and pb.baseline(session, block) == base


def test_progress_weeks_check_run_and_summary(session):
    pf.ensure_week(session, MONDAY)
    run = add_activity(session, 9500, MONDAY + dt.timedelta(days=1), seconds=3300, speed=4.0)
    pipeline.recompute(session, renormalize=False, end=TODAY)  # metrics and best efforts of the new run
    done(session, MONDAY + dt.timedelta(days=1), "k", pf.CHECK_KEY, run)
    block = session.execute(select(CoachBlock)).scalar_one()
    result = pb.progress(session, block, TODAY)
    [week] = result.weeks
    assert (week.week_no, week.items_done, week.value.day) == (1, 2, TODAY)  # K + the Monday run as Ľ
    assert week.run_s == 1200 + 3300
    [check] = result.check_runs
    effort = session.execute(
        select(BestEffort).where(
            BestEffort.activity_id == run, BestEffort.kind == "gap_speed", BestEffort.window_s == 1800
        )
    ).scalar_one()
    assert check.distance_m == effort.distance_m == pytest.approx(7200, rel=0.01)
    assert check.vdot == pytest.approx(vdot(effort.distance_m, 1800.0)) and check.avg_hr == pytest.approx(170)
    assert week.value.vdot >= check.vdot - 1e-9  # the check run is now the §7 reference
    s = result.summary
    assert (s.final, s.weeks, s.items_done, s.items_planned) == (False, 1, 2, 3)
    assert s.change is not None and s.change.vdot > 0
    late = pb.progress(session, block, MONDAY + dt.timedelta(weeks=12))
    assert late.summary.final


def test_service_and_api(engine, session):
    assert svc.get_block(session, today=TODAY) is not None  # creates this week's block on first use
    client = make_client(engine)
    body = client.get("/api/plan/block").json()
    assert body["start"] == MONDAY.isoformat() and body["block_weeks"] == 12
    assert body["end"] == (MONDAY + dt.timedelta(days=83)).isoformat()
    assert {"baseline", "weeks", "check_runs", "summary"} <= set(body)
    assert body["weeks"][0]["change"]["vdot"] == pytest.approx(0.0)
    assert client.get("/api/plan/blocks").json() == [
        {"start": MONDAY.isoformat(), "end": body["end"], "current": True}
    ]
    assert client.get("/api/plan/block", params={"start": "2026-01-05"}).status_code == 404
    with pytest.raises(NotFoundError):
        svc.get_block(session, today=TODAY, start=dt.date(2026, 1, 5))


def test_no_block_is_created_in_race_mode(session, monkeypatch):
    from training import planning
    from training.db.models import Goal

    monkeypatch.undo()  # the real mode_for (conftest forces race mode for unmarked tests only)
    session.add(Goal(race_date=TODAY + dt.timedelta(days=60), distance_m=10000.0, sport="run"))
    session.commit()
    assert planning.mode_for(session, TODAY) == "race"
    assert svc.get_block(session, today=TODAY) is None
    assert session.execute(select(CoachBlock)).first() is None


# --- every filter has a negative row (spec review B1) -------------------------------------------------------


def _race(session, garmin_id, day, *, commute=None, sport="run"):
    activity_id = add_activity(session, garmin_id, day, sport=sport, seconds=1500, speed=4.0, commute=commute)
    activity = session.get(Activity, activity_id)
    activity.is_race = True
    session.add(activity)
    session.commit()
    return activity_id


def test_candidates_are_non_commute_runs_up_to_the_day(session):
    friday = TODAY + dt.timedelta(days=2)
    _race(session, 9600, TODAY, commute=True)
    _race(session, 9601, TODAY, sport="bike")
    _race(session, 9602, friday)  # after `end`
    assert pb._candidates(session, TODAY).query("source == 'race'").empty
    commute_effort = add_activity(session, 9603, TODAY, seconds=1500, speed=5.0, commute=True)
    session.add(
        BestEffort(
            activity_id=commute_effort,
            sport="run",
            kind="gap_speed",
            window_s=600,
            value=5.0,
            distance_m=3000,
        )
    )
    session.commit()
    assert 3000 not in set(pb._candidates(session, TODAY)["distance_m"])
    assert len(pb._candidates(session, friday).query("source == 'race'")) == 1


def test_snapshot_runs_exclude_commutes_bikes_and_later_days(session):
    def with_ef(activity_id, ef):
        session.merge(
            ActivityMetric(activity_id=activity_id, ef=ef, steady_state=True, pace_at_ref_hr_day=2.0)
        )
        session.commit()

    with_ef(add_activity(session, 9700, TODAY, commute=True), 9.0)
    with_ef(add_activity(session, 9701, TODAY, sport="bike", commute=False), 8.0)
    with_ef(add_activity(session, 9702, TODAY + dt.timedelta(days=1)), 7.0)
    frame = pb._runs(session, TODAY, TODAY)
    assert not ({9.0, 8.0, 7.0} & set(frame["ef"].dropna()))
    with_ef(add_activity(session, 9703, TODAY), 1.5)
    assert 1.5 in set(pb._runs(session, TODAY, TODAY)["ef"])


def test_only_done_check_runs_give_results_and_weeks_stop_at_today(session):
    pf.ensure_week(session, MONDAY)
    pf.ensure_week(session, MONDAY + dt.timedelta(weeks=2))  # future rows exist (not final)
    run = add_activity(session, 9800, MONDAY + dt.timedelta(days=1), seconds=2400, speed=4.0)
    pipeline.recompute(session, renormalize=False, end=TODAY)
    done(session, MONDAY + dt.timedelta(days=1), "k", "fit_vo2", run)  # a done K that is not a check run
    session.add(
        PlannedWorkout(
            date=MONDAY + dt.timedelta(days=1),
            sport="run",
            name="check",
            status="skipped",
            structure=to_structure(fitness.check_run()) | {"slot": "k", "key": pf.CHECK_KEY},
            completed_activity_id=run,
        )
    )
    session.commit()
    block = session.execute(select(CoachBlock)).scalar_one()
    result = pb.progress(session, block, TODAY)
    assert result.check_runs == [] and [w.week_no for w in result.weeks] == [1]


def test_daily_values_stay_inside_the_window(session):
    for day, hours in ((MONDAY - dt.timedelta(days=1), 3), (MONDAY, 7), (TODAY + dt.timedelta(days=1), 3)):
        repo.upsert_wellness(session, {"date": day, "sleep_s": hours * 3600})
    session.commit()
    _, sleep = pb._daily_values(session, MONDAY, TODAY)
    assert [s for s in sleep if s is not None] == [7 * 3600]


def test_stale_reference_is_flagged_and_a_baseline_waits_for_the_monday_sync(session):
    assert bp.Snapshot(TODAY, reference_date=TODAY - dt.timedelta(days=61)).stale
    assert not bp.Snapshot(TODAY, reference_date=TODAY - dt.timedelta(days=60)).stale
    week2 = MONDAY + dt.timedelta(weeks=1)
    block = CoachBlock(start_monday=week2, base_s=5400)  # a block that starts next Monday, before its sync
    session.add(block)
    session.commit()
    first = pb.baseline(session, block)
    assert block.baseline["final"] is False
    _race(session, 9900, week2 - dt.timedelta(days=1))  # Sunday's race arrives with the Monday sync
    assert pb.baseline(session, block).vdot > (first.vdot or 0)
