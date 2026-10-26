"""training morning (PLAN phase 8): step chain, idempotency, run log, lock, schedule, exit codes. Offline."""

import datetime as dt
import json
import logging
import os
import time

import pytest
from sqlmodel import Session
from typer.testing import CliRunner

from training import cli, log_redaction, morning
from training.config import Settings, get_settings
from training.db import repo
from training.db.session import make_engine
from training.db.state_keys import LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE, MORNING_RUNS
from training.services import notify, plan_push, sync as sync_service
from training.services.dto import PushResultDTO, SyncResultDTO
from training.services.errors import ServiceError

from .seeding import TODAY, seeded_db

SECRET = "123456789:AAE-SECRET_token"


def _sync_ok(session, *, settings, today):
    repo.set_state(session, LAST_ACTIVITY_SYNC, today.isoformat())  # what a real sync leaves behind
    repo.set_state(session, LAST_WELLNESS_DATE, today.isoformat())
    session.commit()
    return SyncResultDTO(
        activities_new=1,
        activities_updated=0,
        activities_unchanged=5,
        activities_pending=0,
        activities_failed=0,
        wellness_days=2,
        metrics_computed=1,
        pmc_days=10,
        errors=[],
    )


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def settings(tmp_path):
    return Settings(db_path=tmp_path / "training.db", log_dir=tmp_path / "logs", rate_limit_s=0)


@pytest.fixture
def fakes(monkeypatch):
    calls = {"push": 0, "telegram": 0}

    def push_day(session, day, *, settings, dry_run=False):
        calls["push"] += 1
        return [PushResultDTO(planned_id=1, action="uploaded" if calls["push"] == 1 else "unchanged")]

    def send(session, today, settings):
        calls["telegram"] += 1
        return True

    monkeypatch.setattr(sync_service, "run_sync", _sync_ok)
    monkeypatch.setattr(plan_push, "push_day", push_day)
    monkeypatch.setattr(notify, "is_configured", lambda settings: True)
    monkeypatch.setattr(notify, "send_morning", send)
    return calls


def _statuses(run):
    return {s.name: s.status for s in run.steps}


def test_a_full_run_and_a_second_run_the_same_day(engine, settings, fakes):
    with Session(engine) as session:
        first = morning.run_morning(session, settings, TODAY)
        assert first.ok and _statuses(first) == {"sync": "ok", "plan": "ok", "push": "ok", "telegram": "ok"}
        second = morning.run_morning(session, settings, TODAY)
        assert second.ok
        assert second.step("push").message == "unchanged"  # the push sends nothing new
        assert second.step("telegram").status == "skipped"  # the message goes out once a day
        assert fakes == {"push": 2, "telegram": 1}
        runs = repo.get_state_json(session, MORNING_RUNS)
    assert [r["ok"] for r in runs] == [True, True]
    assert [s["name"] for s in runs[0]["steps"]] == ["sync", "plan", "push", "telegram"]
    assert runs[0]["started_at"] >= runs[1]["started_at"]  # newest first


def test_a_failed_sync_plans_provisionally_and_does_not_push(engine, settings, fakes, monkeypatch):
    def boom(session, *, settings, today):
        raise ServiceError("Garmin is rate-limiting requests (429). Progress is saved; try again in a while.")

    monkeypatch.setattr(sync_service, "run_sync", boom)
    with Session(engine) as session:
        repo.set_state(session, LAST_WELLNESS_DATE, (TODAY - dt.timedelta(days=1)).isoformat())
        session.commit()
        run = morning.run_morning(session, settings, TODAY)
    assert not run.ok
    assert _statuses(run) == {"sync": "failed", "plan": "ok", "push": "skipped", "telegram": "ok"}
    assert "429" in run.step("sync").message
    assert "predbežný" in run.step("plan").message
    assert fakes["push"] == 0 and fakes["telegram"] == 1


def test_an_unexpected_error_is_recorded_by_class_only(engine, settings, fakes, monkeypatch):
    def boom(session, day, *, settings, dry_run=False):
        raise RuntimeError(f"https://api.example/bot{SECRET}/x")

    monkeypatch.setattr(plan_push, "push_day", boom)
    with Session(engine) as session:
        run = morning.run_morning(session, settings, TODAY)
        stored = json.dumps(repo.get_state_json(session, MORNING_RUNS))
    assert run.step("push").status == "failed" and "RuntimeError" in run.step("push").message
    assert SECRET not in stored and run.step("telegram").status == "ok"  # later steps still run


def test_switches_and_unconfigured_telegram(engine, settings, fakes, monkeypatch):
    monkeypatch.setattr(notify, "is_configured", lambda settings: False)
    with Session(engine) as session:
        run = morning.run_morning(session, settings, TODAY, push=False)
    assert run.ok and run.step("push").message.startswith("vypnuté")
    assert run.step("telegram").status == "skipped" and fakes["push"] == 0


def test_a_failed_telegram_fails_the_run_and_is_retried(engine, settings, fakes, monkeypatch):
    monkeypatch.setattr(notify, "send_morning", lambda session, today, settings: False)
    with Session(engine) as session:
        assert not morning.run_morning(session, settings, TODAY).ok
        monkeypatch.setattr(notify, "send_morning", lambda session, today, settings: True)
        assert morning.run_morning(session, settings, TODAY).step("telegram").status == "ok"


def test_run_log_is_capped_and_survives_garbage(engine, settings, fakes):
    with Session(engine) as session:
        repo.set_state(session, MORNING_RUNS, "{not json")
        session.commit()
        morning.run_morning(session, settings, TODAY)  # malformed value replaced, no crash
        for _ in range(morning.KEEP_RUNS + 2):
            morning.record_run(session, morning.MorningRun(started_at=dt.datetime.now(dt.UTC)))
        assert len(repo.get_state_json(session, MORNING_RUNS)) == morning.KEEP_RUNS


def test_run_lock(tmp_path):
    path = tmp_path / "logs" / morning.LOCK_FILE
    with morning.RunLock(path):
        assert path.exists()
        with pytest.raises(morning.AlreadyRunning), morning.RunLock(path):
            pass
    assert not path.exists()
    path.parent.mkdir(exist_ok=True)
    path.write_text("999 old\n", encoding="utf-8")
    old = time.time() - 4 * 3600
    os.utime(path, (old, old))
    with morning.RunLock(path):  # a stale lock (crashed run) is taken over
        pass


def test_schedule_helpers():
    at = dt.time(6, 0)
    assert morning.next_run_at(dt.datetime(2026, 10, 25, 5, 59), at) == dt.datetime(2026, 10, 25, 6, 0)
    assert morning.next_run_at(dt.datetime(2026, 10, 25, 6, 0), at) == dt.datetime(2026, 10, 26, 6, 0)
    assert morning.parse_time("6:30") == dt.time(6, 30)
    with pytest.raises(ValueError, match="HH:MM"):
        morning.parse_time("six")


def test_json_log_file_is_structured_and_redacted(tmp_path):
    path = log_redaction.add_file_handler(tmp_path)
    assert log_redaction.add_file_handler(tmp_path) == path  # idempotent
    logger = logging.getLogger("training.morning")
    old = logger.level
    logger.setLevel(logging.INFO)
    try:
        logger.info(
            "push: failed – bot%s", SECRET, extra={"step": "push", "status": "failed", "duration_s": 1.5}
        )
    finally:
        logger.setLevel(old)
        root = logging.getLogger()
        for handler in [h for h in root.handlers if getattr(h, "baseFilename", "") == str(path.resolve())]:
            root.removeHandler(handler)
            handler.close()
    line = json.loads(path.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert line["step"] == "push" and line["status"] == "failed" and line["duration_s"] == 1.5
    assert SECRET not in json.dumps(line) and "bot<redacted>" in line["msg"]


@pytest.mark.parametrize(("ok", "code"), [(True, 0), (False, morning.EXIT_FAILED)])
def test_cli_exit_codes(engine, tmp_path, monkeypatch, fakes, ok, code):
    monkeypatch.setenv("TRAINING_DB_PATH", engine.url.database)
    monkeypatch.setenv("TRAINING_LOG_DIR", str(tmp_path / "logs"))
    if not ok:
        monkeypatch.setattr(notify, "send_morning", lambda session, today, settings: False)
    get_settings.cache_clear()
    try:
        result = CliRunner().invoke(cli.app, ["morning"])
    finally:
        get_settings.cache_clear()
        root = logging.getLogger()
        for handler in [h for h in root.handlers if "training.log" in getattr(h, "baseFilename", "")]:
            root.removeHandler(handler)
            handler.close()
    assert result.exit_code == code, result.output
    assert "sync" in result.output and "telegram" in result.output


def test_cli_reports_a_held_lock(engine, tmp_path, monkeypatch, fakes):
    monkeypatch.setenv("TRAINING_DB_PATH", engine.url.database)
    monkeypatch.setenv("TRAINING_LOG_DIR", str(tmp_path / "logs"))
    get_settings.cache_clear()
    try:
        with morning.RunLock(tmp_path / "logs" / morning.LOCK_FILE):
            result = CliRunner().invoke(cli.app, ["morning"])
    finally:
        get_settings.cache_clear()
        root = logging.getLogger()
        for handler in [h for h in root.handlers if "training.log" in getattr(h, "baseFilename", "")]:
            root.removeHandler(handler)
            handler.close()
    assert result.exit_code == morning.EXIT_LOCKED


# --- review phase 8 follow-ups ----------------------------------------------------------------------------


class FakeClock:
    """A naive local wall clock that `sleep` advances; `jump_at` moves it like a DST change."""

    def __init__(self, start: dt.datetime, jumps: dict[dt.datetime, dt.timedelta] | None = None):
        self.now, self.jumps, self.slept = start, dict(jumps or {}), []

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        before = self.now
        self.now += dt.timedelta(seconds=seconds)
        for at, shift in list(self.jumps.items()):
            if before < at <= self.now:
                self.now += shift
                del self.jumps[at]


def test_daily_loop_runs_once_at_six_across_the_autumn_dst_change():
    # 25. 10. 2026 03:00 CEST → 02:00 CET: the wall clock goes back one hour during the night
    clock = FakeClock(
        dt.datetime(2026, 10, 24, 6, 1), {dt.datetime(2026, 10, 25, 3, 0): dt.timedelta(hours=-1)}
    )
    ran = []
    morning.daily_loop(
        lambda: ran.append(clock.now),
        dt.time(6, 0),
        ran_today=lambda day: True,
        now=lambda: clock.now,
        sleep=clock.sleep,
        max_runs=2,
    )
    assert ran == [dt.datetime(2026, 10, 25, 6, 0), dt.datetime(2026, 10, 26, 6, 0)]
    assert max(clock.slept) <= morning.CHUNK_S


def test_daily_loop_catches_up_and_survives_a_crash():
    clock = FakeClock(dt.datetime(2026, 10, 25, 9, 30))
    calls = []

    def run_once():
        calls.append(clock.now)
        if len(calls) == 1:
            raise RuntimeError("database is locked")

    morning.daily_loop(
        run_once,
        dt.time(6, 0),
        ran_today=lambda day: False,
        now=lambda: clock.now,
        sleep=clock.sleep,
        max_runs=3,
    )
    assert calls == [
        dt.datetime(2026, 10, 25, 9, 30),
        dt.datetime(2026, 10, 25, 10, 30),
        dt.datetime(2026, 10, 26, 6, 0),
    ]  # catch-up (crashed), one retry an hour later (ok), then the next day


def test_daily_loop_retries_a_failed_run_hourly_but_not_past_midnight():
    clock = FakeClock(dt.datetime(2026, 10, 25, 8, 59))
    calls = []

    def run_once():
        calls.append(clock.now)
        return morning.EXIT_FAILED  # e.g. Garmin unreachable all day

    morning.daily_loop(
        run_once,
        dt.time(9, 0),
        ran_today=lambda day: True,
        now=lambda: clock.now,
        sleep=clock.sleep,
        max_runs=1 + morning.MAX_RETRIES + 1,
    )
    day1 = [dt.datetime(2026, 10, 25, 9 + h, 0) for h in range(morning.MAX_RETRIES + 1)]
    assert calls == [*day1, dt.datetime(2026, 10, 26, 9, 0)]  # 4 retries, then tomorrow as usual

    late = FakeClock(dt.datetime(2026, 10, 25, 22, 30))
    late_calls = []
    morning.daily_loop(
        lambda: late_calls.append(late.now) or morning.EXIT_FAILED,
        dt.time(22, 0),
        ran_today=lambda day: False,
        now=lambda: late.now,
        sleep=late.sleep,
        max_runs=3,
    )
    assert late_calls[:2] == [dt.datetime(2026, 10, 25, 22, 30), dt.datetime(2026, 10, 25, 23, 30)]
    assert late_calls[2] == dt.datetime(2026, 10, 26, 22, 0)  # no retry at 00:30 – the next day starts fresh


def test_daily_loop_does_not_retry_a_successful_run():
    clock = FakeClock(dt.datetime(2026, 10, 25, 8, 59))
    calls = []
    morning.daily_loop(
        lambda: calls.append(clock.now) or 0,
        dt.time(9, 0),
        ran_today=lambda day: True,
        now=lambda: clock.now,
        sleep=clock.sleep,
        max_runs=2,
    )
    assert calls == [dt.datetime(2026, 10, 25, 9, 0), dt.datetime(2026, 10, 26, 9, 0)]


def test_ran_on_reads_the_run_log(engine, settings, fakes):
    with Session(engine) as session:
        assert not morning.ran_on(session, TODAY)
        morning.run_morning(
            session, settings, TODAY, now=lambda: dt.datetime.combine(TODAY, dt.time(10), dt.UTC)
        )
        assert morning.ran_on(session, TODAY)


def test_a_provisional_plan_is_not_pushed_and_telegram_is_resent(engine, settings, fakes, monkeypatch):
    """Review phase 8 W4/W5: sync ok but today's data still missing → no push, Telegram again later."""

    def sync_without_wellness(session, *, settings, today):
        result = _sync_ok(session, settings=settings, today=today)
        repo.set_state(session, LAST_WELLNESS_DATE, (today - dt.timedelta(days=1)).isoformat())
        session.commit()
        return result

    monkeypatch.setattr(sync_service, "run_sync", sync_without_wellness)
    with Session(engine) as session:
        first = morning.run_morning(session, settings, TODAY)
        assert first.step("push").status == "skipped" and "predbežný" in first.step("push").message
        assert "predbežným" in first.step("telegram").message
        monkeypatch.setattr(sync_service, "run_sync", _sync_ok)
        planning_row = morning.planning.planned_for(session, TODAY)[0]
        planning_row.structure = {**planning_row.structure, "provisional": False}
        session.add(planning_row)
        session.commit()
        second = morning.run_morning(session, settings, TODAY)
    assert second.step("telegram").status == "ok" and fakes["telegram"] == 2


def test_lock_released_by_its_owner_only_and_dead_holders_are_taken_over(tmp_path):
    path = tmp_path / morning.LOCK_FILE
    lock = morning.RunLock(path)
    with lock:
        path.write_text("12345 someone-else\n", encoding="utf-8")  # taken over meanwhile
    assert path.exists()  # not deleted: it is not ours any more
    if os.name == "posix":
        path.write_text("999999999 crashed\n", encoding="utf-8")  # fresh lock, but the PID is gone
        with morning.RunLock(path):
            pass


# --- METRICS §11.2: waiting for last night's sleep --------------------------------------------------------


@pytest.mark.fitness_coach
def test_the_fitness_plan_waits_for_sleep_then_completes(engine, settings, fakes, monkeypatch):
    from training import planning_fitness

    monkeypatch.setattr(planning_fitness, "now_local", lambda: dt.datetime.combine(TODAY, dt.time(9, 0)))
    at_nine = lambda: dt.datetime.combine(TODAY, dt.time(7, 0), dt.UTC)  # noqa: E731 – 09:00 CEST
    with Session(engine) as session:
        waiting = morning.run_morning(session, settings, TODAY, now=at_nine)
        assert waiting.waiting and not waiting.failed and not waiting.ok
        assert _statuses(waiting) == {
            "sync": "ok",
            "plan": "waiting",
            "push": "skipped",
            "telegram": "skipped",
        }
        assert "spánok" in waiting.step("plan").message and fakes == {"push": 0, "telegram": 0}
        assert not morning.ran_ok_on(session, TODAY)
        stored = repo.get_state_json(session, MORNING_RUNS)[0]
        assert stored["ok"] is True and stored["waiting"] is True  # not an error on the health views

        repo.upsert_wellness(session, {"date": TODAY, "sleep_s": 6.5 * 3600})  # the watch synced
        session.commit()
        done = morning.run_morning(session, settings, TODAY, now=at_nine)
    assert done.ok and _statuses(done)["plan"] == "ok" and fakes == {"push": 1, "telegram": 1}
    with Session(engine) as session:
        assert morning.ran_ok_on(session, TODAY)


@pytest.mark.fitness_coach
def test_once_per_day_skips_after_a_complete_run_and_exit_codes(engine, settings, fakes, monkeypatch):
    from training import planning_fitness

    today = dt.date.today()  # the CLI plans the real today
    monkeypatch.setattr(planning_fitness, "now_local", lambda: dt.datetime.combine(today, dt.time(9, 0)))
    monkeypatch.setenv("TRAINING_DB_PATH", str(settings.db_path))
    monkeypatch.setenv("TRAINING_LOG_DIR", str(settings.log_dir))
    get_settings.cache_clear()
    try:
        runner = CliRunner()
        first = runner.invoke(cli.app, ["morning", "--once-per-day"])
        assert first.exit_code == morning.EXIT_WAITING, first.output
        with Session(engine) as session:
            repo.upsert_wellness(session, {"date": today, "sleep_s": 7 * 3600})
            session.commit()
        second = runner.invoke(cli.app, ["morning", "--once-per-day"])
        assert second.exit_code == 0 and "Morning run OK" in second.output, second.output
        third = runner.invoke(cli.app, ["morning", "--once-per-day"])
        assert third.exit_code == 0 and "already completed" in third.output
    finally:
        get_settings.cache_clear()
