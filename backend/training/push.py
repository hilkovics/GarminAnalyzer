"""Phase-7 glue: push planned workouts to Garmin Connect (METRICS §10.8). The only network is `GarminClient`.

- First push: upload (one attempt, a retried POST could duplicate), store `garmin_workout_id` at once (so a
  failed schedule is retried by updating, never by uploading again), then schedule on the planned date.
- Re-push: update in place (PUT keeps the id and its calendar entry); schedule again only when the date
  changed, removing the old schedule first.
- A rest day with a Garmin workout (a regeneration to rest) deletes it. Done / skipped workouts are not
  pushed.
The Garmin ids live in `planned_workout.garmin_workout_id` and `structure["garmin"]`
(`{"schedule_id", "scheduled_date"}`).
"""

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from training import planning
from training.coach.garmin_push import to_garmin_payload
from training.db.models import PlannedWorkout
from training.garmin.client import GarminClient, GarminConnectNotFoundError

log = logging.getLogger(__name__)

PUSHABLE = ("planned", "pushed")


@dataclass
class PushResult:
    planned_id: int
    action: str  # "uploaded" | "updated" | "deleted" | "skipped" | "dry_run"
    garmin_workout_id: int | None = None
    scheduled_date: dt.date | None = None
    payload: dict[str, Any] | None = None
    notes: list[str] = field(default_factory=list)


def _garmin_state(row: PlannedWorkout) -> dict[str, Any]:
    return dict((row.structure or {}).get("garmin") or {})


def _save(session: Session, row: PlannedWorkout, garmin: dict[str, Any], **columns: Any) -> None:
    row.structure = {**(row.structure or {}), "garmin": garmin}  # a new dict: JSON columns track assignment
    for key, value in columns.items():
        setattr(row, key, value)
    session.add(row)
    session.commit()


def _schedule_id(response: Any) -> int | None:
    """The scheduled-workout id from Garmin's schedule response (`workoutScheduleId`; unverified key)."""
    if isinstance(response, dict):
        for key in ("workoutScheduleId", "scheduledWorkoutId", "id"):
            value = response.get(key)
            if isinstance(value, int | float) and not isinstance(value, bool):
                return int(value)
    return None


def push_planned(
    session: Session, client: GarminClient | None, planned_id: int, *, dry_run: bool = False
) -> PushResult:
    """Push one planned workout (METRICS §10.8 clarified). `client` may be None only for `dry_run`."""
    row = session.get(PlannedWorkout, planned_id)
    if row is None:
        raise LookupError(f"planned workout {planned_id} not found")
    if row.status not in PUSHABLE:
        raise planning.PlanError(f"a {row.status} workout is not pushed")
    workout = planning.workout_of(row)
    garmin = _garmin_state(row)
    workout_id = row.garmin_workout_id
    if workout.sport == "rest":
        if workout_id is None:
            return PushResult(planned_id, "skipped", notes=["rest day – nothing to push"])
        if dry_run:
            return PushResult(planned_id, "dry_run", workout_id, notes=["would delete the Garmin workout"])
        _client(client).delete_workout(workout_id)
        _save(session, row, {}, garmin_workout_id=None)
        return PushResult(planned_id, "deleted", notes=["rest day – Garmin workout deleted"])

    payload = to_garmin_payload(workout, row.date, row.reason)
    if dry_run:
        return PushResult(planned_id, "dry_run", workout_id, row.date, payload)
    api = _client(client)
    if workout_id is not None:
        api.update_workout(workout_id, payload)
        action = "updated"
    else:
        created = api.upload_workout(payload)
        workout_id = int(created["workoutId"])
        _save(session, row, garmin, garmin_workout_id=workout_id)  # before scheduling: never upload twice
        action = "uploaded"

    notes: list[str] = []
    if garmin.get("scheduled_date") != row.date.isoformat():
        if garmin.get("schedule_id") is not None:
            try:
                api.unschedule_workout(int(garmin["schedule_id"]))
            except GarminConnectNotFoundError:
                notes.append("the old schedule was already gone")
        response = api.schedule_workout(workout_id, row.date)
        garmin = {"schedule_id": _schedule_id(response), "scheduled_date": row.date.isoformat()}
        if garmin["schedule_id"] is None:
            log.warning("Garmin schedule response without a schedule id (keys: %s)", _keys(response))
    _save(session, row, garmin, status="pushed")
    return PushResult(planned_id, action, workout_id, row.date, notes=notes)


def push_day(
    session: Session, client: GarminClient | None, day: dt.date, *, dry_run: bool = False
) -> list[PushResult]:
    """`training push-today`: every pushable planned workout of `day` (planned or re-pushed)."""
    return [
        push_planned(session, client, row.id, dry_run=dry_run)
        for row in planning.planned_for(session, day)
        if row.status in PUSHABLE and row.id is not None
    ]


def _client(client: GarminClient | None) -> GarminClient:
    if client is None:
        raise ValueError("a Garmin client is required unless dry_run is set")
    return client


def _keys(response: Any) -> list[str]:
    return sorted(response) if isinstance(response, dict) else [type(response).__name__]
