"""services/morning_runs.py + the health fields of get_diagnostics / get_dashboard (PLAN phase 8)."""

import datetime as dt
import json
import time

import pytest
from sqlmodel import Session

from training.db import repo
from training.db.session import make_engine
from training.db.state_keys import MORNING_RUNS
from training.services import diagnostics, fitness, morning_runs

from .seeding import TODAY, seeded_db

UTC = dt.UTC
NOW = dt.datetime(2026, 10, 23, 8, 0, tzinfo=UTC)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(seeded_db(tmp_path))
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture(autouse=True)
def prague_zone():
    """`astimezone()` follows the process zone; pin it so the local-time assertions are deterministic."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("TZ", "Europe/Bratislava")
        time.tzset()
        yield
    time.tzset()


def step(name: str, status: str = "ok", message: str = "", duration_s: float = 1.0) -> dict:
    return {"name": name, "status": status, "message": message, "duration_s": duration_s}


def run(started: dt.datetime, *, ok: bool = True, failed: str | None = None, message: str = "boom") -> dict:
    steps = [step(n) for n in ("sync", "plan", "push", "telegram")]
    if failed:
        steps = [step(s["name"], "failed", message) if s["name"] == failed else s for s in steps]
    return {
        "started_at": started.isoformat(),
        "finished_at": (started + dt.timedelta(seconds=75)).isoformat(),
        "ok": ok and failed is None,
        "steps": steps,
    }


def store(session, value) -> None:
    repo.set_state(session, MORNING_RUNS, value if isinstance(value, str) else json.dumps(value))
    session.commit()


# --- missing / malformed ------------------------------------------------------------------------------------


def test_missing_key_is_no_runs(session):
    assert morning_runs.load_morning_runs(session) == []
    d = diagnostics.get_diagnostics(session)
    assert d.recent_runs == [] and d.last_errors == []
    dash = fitness.get_dashboard(session, today=TODAY, now=NOW)
    assert (dash.last_successful_run, dash.last_run_ok, dash.morning_run_stale) == (None, None, False)


@pytest.mark.parametrize(
    "garbage",
    ["not json {", '{"a": 1}', '"text"', '[1, null, "x"]', "[]", "42"],
)
def test_malformed_state_never_crashes(session, garbage):
    store(session, garbage)
    assert morning_runs.load_morning_runs(session) == []
    assert diagnostics.get_diagnostics(session).recent_runs == []
    assert fitness.get_dashboard(session, today=TODAY, now=NOW).last_run_ok is None


def test_bad_entries_and_steps_are_dropped_good_ones_kept(session):
    good = run(NOW - dt.timedelta(hours=2))
    good["steps"] += [{"name": "weird", "status": "ok"}, "junk", {"name": "sync", "status": "maybe"}]
    store(
        session,
        [
            {"started_at": "yesterday-ish", "ok": True, "steps": []},
            {"started_at": NOW.isoformat()},  # no "ok"
            good,
            {**run(NOW - dt.timedelta(days=1)), "steps": "nope"},
        ],
    )
    runs = morning_runs.load_morning_runs(session)
    assert len(runs) == 2
    assert [s.name for s in runs[0].steps] == ["sync", "plan", "push", "telegram"]  # bad steps dropped
    assert runs[1].steps == []


def test_naive_timestamps_are_taken_as_utc_and_unfinished_runs_have_no_duration(session):
    store(session, [{"started_at": "2026-10-23T04:00:01", "ok": True, "steps": []}])
    (r,) = morning_runs.load_morning_runs(session)
    assert r.started_at == dt.datetime(2026, 10, 23, 4, 0, 1, tzinfo=UTC)
    assert r.finished_at is None and r.duration_s is None
    assert morning_runs.last_successful_run([r]) == r.started_at  # falls back to the start


# --- ok / failed mix ----------------------------------------------------------------------------------------


def mixed_runs() -> list[dict]:
    """Newest first: failed (push), ok, failed (sync) + failed (telegram message), ok."""
    return [
        run(NOW - dt.timedelta(hours=1), failed="push", message="Garmin 502"),
        run(NOW - dt.timedelta(days=1, hours=1)),
        run(dt.datetime(2026, 10, 21, 4, 0, tzinfo=UTC), failed="sync", message="login zlyhal"),
        run(NOW - dt.timedelta(days=3)),
    ]


def test_diagnostics_lists_runs_and_errors_with_local_time(session):
    store(session, mixed_runs())
    d = diagnostics.get_diagnostics(session)
    assert [r.ok for r in d.recent_runs] == [False, True, False, True]
    assert d.recent_runs[0].duration_s == 75.0
    # 2026-10-23 07:00 UTC is 09:00 CEST; 2026-10-21 04:00 UTC is 06:00 CEST
    assert d.last_errors == [
        "23. 10. 2026 9:00 – push: Garmin 502",
        "21. 10. 2026 6:00 – sync: login zlyhal",
    ]


def test_diagnostics_caps_runs_at_10_and_errors_at_the_last_10_runs(session):
    runs = [run(NOW - dt.timedelta(days=i), failed="sync", message=f"e{i}") for i in range(30)]
    store(session, runs)
    d = diagnostics.get_diagnostics(session)
    assert len(d.recent_runs) == 10
    assert [e.rsplit(": ", 1)[1] for e in d.last_errors] == [f"e{i}" for i in range(10)]


def test_runs_are_sorted_newest_first_even_if_stored_oldest_first(session):
    store(session, list(reversed(mixed_runs())))
    runs = morning_runs.load_morning_runs(session)
    assert [r.started_at for r in runs] == sorted((r.started_at for r in runs), reverse=True)


def test_dashboard_last_successful_run_and_outcome(session):
    store(session, mixed_runs())
    dash = fitness.get_dashboard(session, today=TODAY, now=NOW)
    assert dash.last_run_ok is False  # the newest run failed
    assert dash.last_successful_run == NOW - dt.timedelta(days=1, hours=1) + dt.timedelta(seconds=75)
    assert dash.morning_run_stale is False  # 23 h ago


def test_dashboard_only_failed_runs_is_stale_without_a_success(session):
    store(session, [run(NOW - dt.timedelta(hours=2), failed="sync")])
    dash = fitness.get_dashboard(session, today=TODAY, now=NOW)
    assert (dash.last_successful_run, dash.last_run_ok, dash.morning_run_stale) == (None, False, True)


@pytest.mark.parametrize(("age_h", "stale"), [(35, False), (36, True), (50, True)])
def test_morning_run_stale_after_36_hours(session, age_h, stale):
    finished = NOW - dt.timedelta(hours=age_h)
    store(session, [run(finished - dt.timedelta(seconds=75))])
    dash = fitness.get_dashboard(session, today=TODAY, now=NOW)
    assert dash.last_run_ok is True and dash.last_successful_run == finished
    assert dash.morning_run_stale is stale


def test_dashboard_now_defaults_to_the_wall_clock(session):
    store(session, [run(dt.datetime.now(UTC) - dt.timedelta(hours=1))])
    dash = fitness.get_dashboard(session, today=TODAY)
    assert dash.morning_run_stale is False and dash.last_run_ok is True
