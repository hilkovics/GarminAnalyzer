"""METRICS §10.8: §10.5 workouts → Garmin Connect JSON, and the push flow (fake Garmin, no network)."""

import datetime as dt

import pytest
from sqlmodel import Session

from training import planning, push
from training.coach import library
from training.coach.garmin_push import PushError, to_garmin_payload
from training.coach.workout import HrZoneTarget, PaceRangeTarget, Step, Workout, rest_workout, to_structure
from training.db.models import PlannedWorkout
from training.db.session import make_engine
from training.garmin.client import GarminClient, GarminConnectConnectionError, GarminConnectNotFoundError

from .seeding import TODAY, seeded_db

DAY = dt.date(2026, 9, 30)
HR = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 1}
TIME = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
RUNNING = {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1}


def _step(order: int, type_id: int, key: str, seconds: float, zone: int) -> dict:
    return {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": {"stepTypeId": type_id, "stepTypeKey": key, "displayOrder": type_id},
        "endCondition": TIME,
        "endConditionValue": seconds,
        "targetType": HR,
        "zoneNumber": zone,
    }


def test_threshold_payload_matches_the_garminconnect_builders():
    """The JSON `garminconnect.workout` 0.3 builders emit for WU 15 Z2, 5× (6 Z4 / 2 Z1), CD 10 Z1."""
    workout = library.build("run", "threshold", 5)
    payload = to_garmin_payload(workout, DAY)
    assert payload == {
        "workoutName": f"{workout.name} (2026-09-30)",
        "sportType": RUNNING,
        "estimatedDurationInSecs": 3900,
        "workoutSegments": [
            {
                "segmentOrder": 1,
                "sportType": RUNNING,
                "workoutSteps": [
                    _step(1, 1, "warmup", 900.0, 2),
                    {
                        "type": "RepeatGroupDTO",
                        "stepOrder": 2,
                        "stepType": {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6},
                        "numberOfIterations": 5,
                        "workoutSteps": [
                            _step(3, 3, "interval", 360.0, 4),
                            _step(4, 4, "recovery", 120.0, 1),
                        ],
                        "endCondition": {
                            "conditionTypeId": 7,
                            "conditionTypeKey": "iterations",
                            "displayOrder": 7,
                            "displayable": False,
                        },
                        "endConditionValue": 5.0,
                        "smartRepeat": False,
                    },
                    _step(5, 2, "cooldown", 600.0, 1),
                ],
            }
        ],
        "author": {},
    }


def test_bike_open_steady_and_pace_targets():
    bike = to_garmin_payload(library.build("bike", "spin_ups", 60), DAY, "dôvod")
    assert bike["sportType"]["sportTypeKey"] == "cycling" and bike["description"] == "dôvod"
    flat = [s for s in bike["workoutSegments"][0]["workoutSteps"]]
    flat += [c for s in flat if s["type"] == "RepeatGroupDTO" for c in s["workoutSteps"]]
    opens = [s for s in flat if s.get("targetType", {}).get("workoutTargetTypeKey") == "no.target"]
    assert opens and all("Úsilie zóna 5" in s["description"] for s in opens)
    orders = [s["stepOrder"] for s in flat]
    assert len(orders) == len(set(orders))  # unique across the workout

    paced = Workout(
        sport="run",
        name="Tempo",
        steps=[
            Step(type="steady", duration_s=600, target=PaceRangeTarget(zone=3, low_mps=3.6, high_mps=3.3)),
            Step(type="work", duration_s=60, target=PaceRangeTarget(zone=4)),
            Step(type="recovery", duration_s=60, target=HrZoneTarget(zone=1)),
        ],
    )
    steps = to_garmin_payload(paced, DAY)["workoutSegments"][0]["workoutSteps"]
    assert steps[0]["stepType"]["stepTypeKey"] == "interval"
    assert steps[0]["targetType"]["workoutTargetTypeKey"] == "pace.zone"
    assert (steps[0]["targetValueOne"], steps[0]["targetValueTwo"]) == (3.3, 3.6)  # slower bound first
    assert steps[1]["targetType"]["workoutTargetTypeKey"] == "no.target"  # no bounds → no target


def test_rest_is_not_a_garmin_workout():
    with pytest.raises(PushError):
        to_garmin_payload(rest_workout(), DAY)


def test_long_names_are_trimmed():
    workout = library.build("run", "easy", 40).model_copy(update={"name": "x" * 200})
    assert len(to_garmin_payload(workout, DAY)["workoutName"]) == 80


# --- push flow -------------------------------------------------------------------------------------------


class FakeGarminApi:
    def __init__(self):
        self.calls: list[tuple] = []
        self.fail: dict[str, Exception] = {}
        self.next_id = 1000

    def _record(self, name, *args):
        self.calls.append((name, *args))
        if name in self.fail:
            raise self.fail.pop(name)

    def upload_workout(self, payload):
        self._record("upload_workout", payload["workoutName"])
        self.next_id += 1
        return {"workoutId": self.next_id, "workoutName": payload["workoutName"]}

    def update_workout(self, workout_id, payload):
        self._record("update_workout", workout_id)
        return {}

    def delete_workout(self, workout_id):
        self._record("delete_workout", workout_id)
        return {}

    def schedule_workout(self, workout_id, date_str):
        self._record("schedule_workout", workout_id, date_str)
        return {"workoutScheduleId": 5000 + workout_id, "workout": {"workoutId": workout_id}}

    def unschedule_workout(self, schedule_id):
        self._record("unschedule_workout", schedule_id)
        return {}


@pytest.fixture
def session(tmp_path):
    engine = make_engine(seeded_db(tmp_path))
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture
def api():
    return FakeGarminApi()


@pytest.fixture
def client(api):
    return GarminClient(api, rate_limit_s=0, sleep=lambda s: None)


def _planned(session, day=TODAY, key="threshold", param=5, sport="run") -> PlannedWorkout:
    workout = library.build(sport, key, param)
    row = PlannedWorkout(
        date=day,
        sport=sport,
        name=workout.name,
        structure=to_structure(workout),
        reason="test",
        status="planned",
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def test_first_push_uploads_schedules_and_marks_pushed(session, client, api):
    row = _planned(session)
    result = push.push_planned(session, client, row.id)
    assert result.action == "uploaded" and result.garmin_workout_id == 1001
    assert [c[0] for c in api.calls] == ["upload_workout", "schedule_workout"]
    assert api.calls[1][1:] == (1001, TODAY.isoformat())
    session.refresh(row)
    assert row.status == "pushed" and row.garmin_workout_id == 1001
    assert row.structure["garmin"] == {"schedule_id": 6001, "scheduled_date": TODAY.isoformat()}


def test_repush_updates_in_place_without_a_duplicate(session, client, api):
    row = _planned(session)
    push.push_planned(session, client, row.id)
    api.calls.clear()
    again = push.push_planned(session, client, row.id)
    assert again.action == "updated" and again.garmin_workout_id == 1001
    assert api.calls == [("update_workout", 1001)]  # same date → no second calendar entry


def test_date_change_moves_the_schedule(session, client, api):
    row = _planned(session)
    push.push_planned(session, client, row.id)
    row.date = TODAY + dt.timedelta(days=1)
    session.add(row)
    session.commit()
    api.calls.clear()
    push.push_planned(session, client, row.id)
    assert [c[0] for c in api.calls] == ["update_workout", "unschedule_workout", "schedule_workout"]
    assert api.calls[1] == ("unschedule_workout", 6001)


def test_regenerated_plan_inherits_the_garmin_ids(session, client, api):
    row, _ = planning.plan_day(session, TODAY, sport_override="run")
    if row.sport == "rest":
        pytest.skip("template gives rest today")
    push.push_planned(session, client, row.id)
    new, _ = planning.plan_day(session, TODAY, sport_override="bike")
    assert new.id != row.id and new.garmin_workout_id == 1001
    api.calls.clear()
    result = push.push_planned(session, client, new.id)
    if new.sport == "rest":
        assert result.action == "deleted" and api.calls == [("delete_workout", 1001)]
    else:
        assert result.action == "updated" and api.calls == [("update_workout", 1001)]


def test_rest_day_deletes_a_pushed_workout(session, client, api):
    row = _planned(session)
    push.push_planned(session, client, row.id)
    row.structure = {**to_structure(rest_workout()), "garmin": row.structure["garmin"]}
    row.sport = "rest"
    session.add(row)
    session.commit()
    api.calls.clear()
    assert push.push_planned(session, client, row.id).action == "deleted"
    session.refresh(row)
    assert row.garmin_workout_id is None and api.calls == [("delete_workout", 1001)]
    assert push.push_planned(session, client, row.id).action == "skipped"


def test_upload_is_never_retried(session, client, api):
    """A 5xx after a POST that may have succeeded must not be retried into a duplicate (§10.8 clarified)."""
    api.fail["upload_workout"] = GarminConnectConnectionError("API Error 503 - unavailable")
    row = _planned(session)
    with pytest.raises(GarminConnectConnectionError):
        push.push_planned(session, client, row.id)
    assert [c[0] for c in api.calls] == ["upload_workout"]
    session.refresh(row)
    assert row.garmin_workout_id is None and row.status == "planned"


def test_failed_schedule_is_retried_by_updating(session, client, api):
    api.fail["schedule_workout"] = GarminConnectNotFoundError("API Error 404")
    row = _planned(session)
    with pytest.raises(GarminConnectNotFoundError):
        push.push_planned(session, client, row.id)
    session.refresh(row)
    assert row.garmin_workout_id == 1001 and row.status == "planned"  # id kept before scheduling
    api.calls.clear()
    assert push.push_planned(session, client, row.id).action == "updated"
    assert [c[0] for c in api.calls] == ["update_workout", "schedule_workout"]


def test_old_schedule_already_gone_is_fine(session, client, api):
    row = _planned(session)
    push.push_planned(session, client, row.id)
    row.date = TODAY + dt.timedelta(days=2)
    session.add(row)
    session.commit()
    api.fail["unschedule_workout"] = GarminConnectNotFoundError("API Error 404")
    result = push.push_planned(session, client, row.id)
    assert result.notes == ["the old schedule was already gone"]


def test_dry_run_makes_no_calls(session, api):
    row = _planned(session)
    result = push.push_planned(session, None, row.id, dry_run=True)
    assert result.action == "dry_run" and result.payload["workoutName"].endswith(f"({TODAY.isoformat()})")
    assert api.calls == []


def test_done_and_skipped_are_not_pushed(session, client):
    row = _planned(session)
    row.status = "done"
    session.add(row)
    session.commit()
    with pytest.raises(planning.PlanError):
        push.push_planned(session, client, row.id)
    with pytest.raises(LookupError):
        push.push_planned(session, client, 99999)


def test_push_day(session, client, api):
    _planned(session)
    _planned(session, day=TODAY + dt.timedelta(days=1))
    results = push.push_day(session, client, TODAY)
    assert [r.action for r in results] == ["uploaded"]
