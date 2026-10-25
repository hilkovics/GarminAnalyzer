"""`training morning` (PLAN phase 8): sync → metrics → plan → push to Garmin → Telegram, logged + recorded.

- Every step runs in its own try: a failure is recorded and the run continues where that still makes sense:
  a failed sync leaves today's plan provisional (§10.4), so it is not pushed – a pushed plan is never
  re-decided – but the Telegram message still goes out. The run is `ok` only when no step failed.
- Safe to run twice: sync, planning and push are idempotent (an unchanged push sends nothing), and the
  Telegram message is sent once per local day (`TELEGRAM_SENT_DATE`; `force_telegram` overrides).
- Each run is stored (newest first, ≤ 30) under `MORNING_RUNS` in `sync_state` for the Dashboard health line
  and the diagnostics page. Step messages are short and fixed: service errors carry fixed texts, anything
  unexpected is recorded by exception class only (never a message that could echo a token).
- `RunLock` keeps a cron run and a manual run from overlapping; a lock older than `STALE_LOCK` is taken over.
"""

import datetime as dt
import logging
import os
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from sqlmodel import Session

from training import planning
from training.config import Settings
from training.db import repo
from training.db.state_keys import MORNING_RUNS, TELEGRAM_SENT_DATE
from training.services import notify, plan_push, sync as sync_service
from training.services.errors import ServiceError

log = logging.getLogger(__name__)

KEEP_RUNS = 30
LOCK_FILE = "morning.lock"
STALE_LOCK = dt.timedelta(hours=3)
EXIT_FAILED = 1
EXIT_LOCKED = 3


@dataclass
class StepResult:
    name: str  # "sync" | "plan" | "push" | "telegram"
    status: str  # "ok" | "failed" | "skipped"
    message: str
    duration_s: float = 0.0


@dataclass
class MorningRun:
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(step.status != "failed" for step in self.steps)

    def step(self, name: str) -> StepResult | None:
        return next((s for s in self.steps if s.name == name), None)

    def to_json(self) -> dict:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": (self.finished_at or self.started_at).isoformat(),
            "ok": self.ok,
            "steps": [asdict(s) for s in self.steps],
        }


# --- steps ------------------------------------------------------------------------------------------------


def _sync(session: Session, settings: Settings, today: dt.date, run: MorningRun) -> tuple[str, str]:
    result = sync_service.run_sync(session, settings=settings, today=today)  # + metrics + nightly plan
    message = (
        f"{result.activities_new} nových, {result.activities_updated} upravených aktivít, "
        f"{result.wellness_days} wellness dní"
    )
    if result.errors:  # transient endpoint failures: resumed by the next run, not a failed morning
        message += f"; {len(result.errors)} volaní zlyhalo (zopakuje sa)"
    return "ok", message


def _plan(session: Session, settings: Settings, today: dt.date, run: MorningRun) -> tuple[str, str]:
    row = planning.nightly(session, today)
    note = " (predbežný – dnešný sync neprebehol)" if planning.is_provisional(row) else ""
    return "ok", f"{row.name}{note}"


def _push(session: Session, settings: Settings, today: dt.date, run: MorningRun) -> tuple[str, str]:
    sync_step, plan_step = run.step("sync"), run.step("plan")
    if sync_step is None or sync_step.status != "ok":
        return "skipped", "sync neprebehol – predbežný plán sa do Garminu neposiela"
    if plan_step is None or plan_step.status != "ok":
        return "skipped", "bez plánu na dnes"
    results = plan_push.push_day(session, today, settings=settings)
    if not results:
        return "skipped", "nič na odoslanie"
    return "ok", ", ".join(r.action for r in results)


def _telegram(
    session: Session, settings: Settings, today: dt.date, run: MorningRun, *, force: bool
) -> tuple[str, str]:
    if not notify.is_configured(settings):
        return "skipped", "Telegram nie je nastavený"
    if not force and repo.get_state(session, TELEGRAM_SENT_DATE) == today.isoformat():
        return "skipped", "dnes už odoslané"
    if not notify.send_morning(session, today, settings):
        return "failed", "správa neodoslaná (pozri log)"
    repo.set_state(session, TELEGRAM_SENT_DATE, today.isoformat())
    session.commit()
    return "ok", "odoslané"


StepFn = Callable[[Session, Settings, dt.date, MorningRun], tuple[str, str]]


def _run_step(
    name: str, fn: StepFn, session: Session, settings: Settings, today: dt.date, run: MorningRun
) -> None:
    start = time.monotonic()
    try:
        status, message = fn(session, settings, today, run)
    except ServiceError as exc:  # fixed, user-facing texts – safe to record
        session.rollback()
        status, message = "failed", str(exc)
    except Exception as exc:
        session.rollback()
        log.exception("morning step %s failed", name)
        status, message = "failed", f"neočakávaná chyba ({type(exc).__name__}), podrobnosti v logu"
    step = StepResult(name, status, message, round(time.monotonic() - start, 1))
    run.steps.append(step)
    level = logging.WARNING if status == "failed" else logging.INFO
    log.log(
        level,
        "%s: %s – %s",
        name,
        status,
        message,
        extra={"step": name, "status": status, "duration_s": step.duration_s},
    )


def run_morning(
    session: Session,
    settings: Settings,
    today: dt.date,
    *,
    push: bool = True,
    telegram: bool = True,
    force_telegram: bool = False,
    now: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC),
) -> MorningRun:
    """One morning run; recorded in `MORNING_RUNS`. Never raises for a failing step."""
    run = MorningRun(started_at=now())
    _run_step("sync", _sync, session, settings, today, run)
    _run_step("plan", _plan, session, settings, today, run)
    if push:
        _run_step("push", _push, session, settings, today, run)
    else:
        run.steps.append(StepResult("push", "skipped", "vypnuté (--no-push)"))
    if telegram:
        _run_step(
            "telegram",
            lambda s, c, d, r: _telegram(s, c, d, r, force=force_telegram),
            session,
            settings,
            today,
            run,
        )
    else:
        run.steps.append(StepResult("telegram", "skipped", "vypnuté (--no-telegram)"))
    run.finished_at = now()
    record_run(session, run)
    log.log(
        logging.INFO if run.ok else logging.WARNING,
        "morning run %s",
        "ok" if run.ok else "failed",
        extra={"run_ok": run.ok},
    )
    return run


def record_run(session: Session, run: MorningRun) -> None:
    """Prepend the run to `MORNING_RUNS` (≤ `KEEP_RUNS`); a malformed stored value is replaced."""
    try:
        session.rollback()  # a step may have left the session dirty; the record must land regardless
        stored = repo.get_state_json(session, MORNING_RUNS)
    except Exception:  # unreadable JSON
        stored = None
    runs = stored if isinstance(stored, list) else []
    repo.set_state_json(session, MORNING_RUNS, [run.to_json(), *runs][:KEEP_RUNS])
    session.commit()


# --- lock and schedule --------------------------------------------------------------------------------------


class AlreadyRunning(RuntimeError):
    pass


class RunLock:
    """Exclusive lock file (`O_CREAT | O_EXCL`), cross-platform; a stale lock is taken over."""

    def __init__(self, path: Path, *, stale_after: dt.timedelta = STALE_LOCK) -> None:
        self.path = path
        self.stale_after = stale_after

    def __enter__(self) -> "RunLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                age = time.time() - self.path.stat().st_mtime
                if age < self.stale_after.total_seconds():
                    raise AlreadyRunning(f"another morning run holds {self.path.name}") from None
                log.warning("taking over a stale lock (%.0f min old)", age / 60)
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(f"{os.getpid()} {dt.datetime.now(dt.UTC).isoformat()}\n")
            return self
        raise AlreadyRunning(f"cannot take {self.path.name}")

    def __exit__(self, *exc: object) -> None:
        self.path.unlink(missing_ok=True)


def next_run_at(now: dt.datetime, at: dt.time) -> dt.datetime:
    """The next local `at` strictly after `now` (naive local datetimes, as in the container's TZ)."""
    candidate = dt.datetime.combine(now.date(), at)
    return candidate if candidate > now else candidate + dt.timedelta(days=1)


def parse_time(text: str) -> dt.time:
    """ "HH:MM" → time; ValueError with a clear message otherwise."""
    try:
        hours, minutes = (int(part) for part in text.split(":"))
        return dt.time(hours, minutes)
    except (ValueError, TypeError):
        raise ValueError(f"time must be HH:MM, got {text!r}") from None
