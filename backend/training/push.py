"""Phase-7 glue: push planned workouts to Garmin Connect (METRICS §10.8). The only network is `GarminClient`.

- First push: upload (one attempt – a retried POST could duplicate), store `garmin_workout_id` at once, then
  schedule on the planned date (also one attempt). Before each POST a marker (`upload_pending` /
  `schedule_pending`) is saved; if a response is lost, the next push finds the workout by its unique name or
  the calendar entry by workout + date instead of posting again.
- Re-push: update in place (PUT keeps the id and its calendar entry); nothing is sent when the payload and
  date are unchanged (cron-safe). A date change moves the calendar entry. A workout deleted in Garmin Connect
  (404) is uploaded again.
- A rest day with a Garmin workout (a regeneration to rest) deletes it. Done / skipped workouts are not
  pushed.
The Garmin ids live in `planned_workout.garmin_workout_id` and `structure["garmin"]`
(`{"schedule_id", "scheduled_date", "payload_hash"}` plus the pending markers).
"""

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from training import planning
from training.coach.garmin_push import PushError, to_garmin_payload
from training.db.models import PlannedWorkout
from training.garmin.client import GarminClient, GarminConnectNotFoundError

log = logging.getLogger(__name__)

PUSHABLE = ("planned", "pushed")


@dataclass
class PushResult:
    planned_id: int
    action: str  # "uploaded" | "updated" | "unchanged" | "deleted" | "skipped" | "dry_run"
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
    if workout.sport == "rest":
        return _push_rest(session, client, row, dry_run)

    payload = to_garmin_payload(workout, row.date, row.reason)
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    day = row.date.isoformat()
    if dry_run:
        return PushResult(planned_id, "dry_run", row.garmin_workout_id, row.date, payload)
    api = _client(client)
    garmin, workout_id, notes = _garmin_state(row), row.garmin_workout_id, []

    if workout_id is None and garmin.get("upload_pending"):  # a previous upload's response was lost
        workout_id = _find_workout(api, str(garmin["upload_pending"]))  # by the name it was uploaded with
        if workout_id is not None:
            notes.append("recovered the workout of an interrupted upload")
            garmin.pop("upload_pending", None)
            _save(session, row, garmin, garmin_workout_id=workout_id)
    action = "updated"
    if workout_id is not None:
        if garmin.get("payload_hash") == digest and garmin.get("scheduled_date") == day:
            if row.status != "pushed":
                _save(session, row, garmin, status="pushed")
            return PushResult(planned_id, "unchanged", workout_id, row.date, notes=notes)
        try:
            api.update_workout(workout_id, payload)
        except GarminConnectNotFoundError:  # deleted in Garmin Connect: upload a fresh one (no duplicate)
            notes.append("the workout was deleted in Garmin Connect – uploaded again")
            workout_id, garmin = None, {}
            _save(session, row, garmin, garmin_workout_id=None)
    if workout_id is None:
        _save(session, row, {**garmin, "upload_pending": payload["workoutName"]})  # before the POST
        workout_id = _int(api.upload_workout(payload), "workoutId")
        if workout_id is None:  # the marker stays: the next push looks the workout up by name
            raise PushError("Garmin upload response without a workoutId")
        garmin.pop("upload_pending", None)
        _save(session, row, garmin, garmin_workout_id=workout_id)  # before scheduling: never upload twice
        action = "uploaded"

    if garmin.get("scheduled_date") != day:
        garmin = _schedule(session, row, api, workout_id, garmin, notes)
    _save(session, row, {**garmin, "payload_hash": digest}, status="pushed")
    return PushResult(planned_id, action, workout_id, row.date, notes=notes)


def _push_rest(
    session: Session, client: GarminClient | None, row: PlannedWorkout, dry_run: bool
) -> PushResult:
    """A rest day that still has a Garmin workout (a regeneration to rest): delete it."""
    workout_id = row.garmin_workout_id
    pending = _garmin_state(row).get("upload_pending")
    if workout_id is None and pending and not dry_run:  # an interrupted upload may have created it
        workout_id = _find_workout(_client(client), str(pending))
        if workout_id is None:
            _save(session, row, {})
    if workout_id is None:
        return PushResult(row.id, "skipped", notes=["rest day – nothing to push"])
    if dry_run:
        return PushResult(row.id, "dry_run", workout_id, notes=["would delete the Garmin workout"])
    notes = ["rest day – Garmin workout deleted"]
    try:
        _client(client).delete_workout(workout_id)
    except GarminConnectNotFoundError:
        notes = ["rest day – the Garmin workout was already gone"]
    _save(session, row, {}, garmin_workout_id=None)
    return PushResult(row.id, "deleted", notes=notes)


def _schedule(
    session: Session,
    row: PlannedWorkout,
    api: GarminClient,
    workout_id: int,
    garmin: dict[str, Any],
    notes: list[str],
) -> dict[str, Any]:
    """Move the calendar entry to `row.date` without ever creating two entries (METRICS §10.8)."""
    day = row.date.isoformat()
    old_date = garmin.get("scheduled_date")
    if not old_date and garmin.get("schedule_pending") not in (None, day):
        old_date = garmin["schedule_pending"]  # a lost schedule call for another date may have succeeded
    old_id = garmin.get("schedule_id")
    if old_id is None and old_date:
        old_id = _find_schedule(api, workout_id, dt.date.fromisoformat(old_date))
    if old_id is not None:
        try:
            api.unschedule_workout(int(old_id))
        except GarminConnectNotFoundError:
            notes.append("the old schedule was already gone")
    schedule_id = None
    if garmin.get("schedule_pending") == day:  # a previous schedule call may have succeeded
        schedule_id = _find_schedule(api, workout_id, row.date)
    if schedule_id is None:
        _save(session, row, {"schedule_pending": day})  # before the POST
        response = api.schedule_workout(workout_id, row.date)
        schedule_id = _schedule_id(response) or _find_schedule(api, workout_id, row.date)
        if schedule_id is None:
            log.warning("Garmin schedule response without a schedule id (keys: %s)", _keys(response))
    return {"schedule_id": schedule_id, "scheduled_date": day}


def _int(response: Any, key: str) -> int | None:
    value = response.get(key) if isinstance(response, dict) else None
    return int(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _find_workout(api: GarminClient, name: str) -> int | None:
    """The newest account workout with exactly this name (names carry the date, so they are unique)."""
    for item in api.workouts():
        if isinstance(item, dict) and item.get("workoutName") == name:
            found = _int(item, "workoutId")
            if found is not None:
                return found
    return None


def _find_schedule(api: GarminClient, workout_id: int, day: dt.date) -> int | None:
    """The calendar entry of `workout_id` on `day` (calendarItems keys unverified – see STATUS)."""
    for item in api.calendar(day.year, day.month):
        if (
            isinstance(item, dict)
            and item.get("itemType") == "workout"
            and item.get("date") == day.isoformat()
            and _int(item, "workoutId") == workout_id
        ):
            return _int(item, "id")
    return None


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
