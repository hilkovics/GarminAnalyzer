"""Health of the automatic morning run (PLAN phase 8): reads the `morning_runs` sync_state entry.

`training morning` appends one JSON object per run (newest first, at most 30). The reader tolerates a missing
key and any malformed content: unreadable runs or steps are dropped, it never raises. Local times use the
system local zone (`training.localtime`), the same zone the Streamlit page displays.
"""

import datetime as dt
import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlmodel import Session

from training import localtime
from training.db import repo
from training.db.state_keys import MORNING_RUNS
from training.services.dto import MorningRunDTO, MorningStepDTO

log = logging.getLogger(__name__)

MAX_RUNS = 30  # the writer keeps this many
RECENT_RUNS = 10  # shown in diagnostics and scanned for errors
STALE_AFTER = dt.timedelta(hours=36)  # PLAN phase 8: red when no successful run for 36 h


def load_morning_runs(session: Session) -> list[MorningRunDTO]:
    """Stored runs, newest first (by start time), at most `MAX_RUNS`; [] when missing or unreadable."""
    try:
        raw = repo.get_state_json(session, MORNING_RUNS)
    except json.JSONDecodeError:
        log.warning("sync_state %s is not valid JSON; ignoring", MORNING_RUNS)
        return []
    if not isinstance(raw, list):
        if raw is not None:
            log.warning("sync_state %s is not a list; ignoring", MORNING_RUNS)
        return []
    runs = [run for entry in raw[:MAX_RUNS] if (run := _parse_run(entry)) is not None]
    return sorted(runs, key=lambda r: r.started_at, reverse=True)


def last_successful_run(runs: list[MorningRunDTO]) -> dt.datetime | None:
    """`finished_at` (else `started_at`) of the newest run with ok = true."""
    for run in runs:  # newest first
        if run.ok:
            return run.finished_at or run.started_at
    return None


def is_stale(runs: list[MorningRunDTO], now: dt.datetime) -> bool:
    """Runs exist, but none succeeded within the last 36 h. No runs at all is "never ran", not stale."""
    if not runs:
        return False
    last_ok = last_successful_run(runs)
    return last_ok is None or now - last_ok >= STALE_AFTER


def last_errors(runs: list[MorningRunDTO], limit: int = RECENT_RUNS) -> list[str]:
    """Failed-step messages of the newest `limit` runs, newest first, prefixed with the local start time."""
    out = []
    for run in runs[:limit]:
        for step in run.steps:
            if step.status == "failed":
                out.append(f"{local_stamp(run.started_at)} – {step.name}: {step.message or '(bez správy)'}")
    return out


def local_stamp(moment: dt.datetime) -> str:
    """ "23. 10. 2026 6:01" in the system local zone."""
    local = localtime.to_local(moment)
    return f"{local.day}. {local.month}. {local.year} {local.hour}:{local.minute:02d}"


def _parse_run(entry: Any) -> MorningRunDTO | None:
    if not isinstance(entry, dict):
        return None
    steps = [step for raw in _as_list(entry.get("steps")) if (step := _parse_step(raw)) is not None]
    try:
        run = MorningRunDTO.model_validate({**entry, "steps": []})
    except ValidationError:
        return None
    run.steps = steps
    run.started_at = _aware(run.started_at)
    run.finished_at = _aware(run.finished_at) if run.finished_at else None
    return run


def _parse_step(entry: Any) -> MorningStepDTO | None:
    try:
        return MorningStepDTO.model_validate(entry)
    except ValidationError:
        return None


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _aware(moment: dt.datetime) -> dt.datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=dt.UTC)
