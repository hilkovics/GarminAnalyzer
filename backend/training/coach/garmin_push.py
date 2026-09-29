"""§10.5 workout → Garmin Connect workout JSON – METRICS §10.8 (phase 7). Pure; no I/O.

The shape is exactly what `garminconnect.workout` (0.3.x) builders emit (`RunningWorkout(...).to_dict()`),
written as plain dicts so the typed builders' pydantic models stay out of the core:

- sport run → `running` (1), bike → `cycling` (2);
- step type warmup → warmup (1), cooldown → cooldown (2), work / steady → interval (3),
  recovery → recovery (4); repeat → `RepeatGroupDTO` with `numberOfIterations` (end condition
  `iterations`, 7);
- every executable step ends on time (condition 2, `endConditionValue = duration_s`);
- targets: `hr_zone` → `heart.rate.zone` (4) with `zoneNumber`; `open` → `no.target` (1) with the effort
  zone in the step description; `pace_range` → `pace.zone` (6) with `targetValueOne/Two` in m/s (slower
  bound first) when both bounds are known, else `no.target`;
- `stepOrder` is unique across the whole workout (a repeat group takes one number, then its children).
"""

import datetime as dt
from typing import Any

from training.coach.workout import (
    HrZoneTarget,
    OpenTarget,
    PaceRangeTarget,
    RepeatStep,
    Step,
    Workout,
    total_duration_s,
)

SPORTS: dict[str, dict[str, Any]] = {
    "run": {"sportTypeId": 1, "sportTypeKey": "running", "displayOrder": 1},
    "bike": {"sportTypeId": 2, "sportTypeKey": "cycling", "displayOrder": 2},
}
STEP_TYPES: dict[str, dict[str, Any]] = {
    "warmup": {"stepTypeId": 1, "stepTypeKey": "warmup", "displayOrder": 1},
    "cooldown": {"stepTypeId": 2, "stepTypeKey": "cooldown", "displayOrder": 2},
    "work": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "steady": {"stepTypeId": 3, "stepTypeKey": "interval", "displayOrder": 3},
    "recovery": {"stepTypeId": 4, "stepTypeKey": "recovery", "displayOrder": 4},
}
REPEAT_TYPE = {"stepTypeId": 6, "stepTypeKey": "repeat", "displayOrder": 6}
TIME_CONDITION = {"conditionTypeId": 2, "conditionTypeKey": "time", "displayOrder": 2, "displayable": True}
ITERATIONS_CONDITION = {
    "conditionTypeId": 7,
    "conditionTypeKey": "iterations",
    "displayOrder": 7,
    "displayable": False,
}
HR_ZONE_TARGET = {"workoutTargetTypeId": 4, "workoutTargetTypeKey": "heart.rate.zone", "displayOrder": 1}
NO_TARGET = {"workoutTargetTypeId": 1, "workoutTargetTypeKey": "no.target", "displayOrder": 1}
PACE_TARGET = {"workoutTargetTypeId": 6, "workoutTargetTypeKey": "pace.zone", "displayOrder": 6}
MAX_NAME = 80  # Garmin Connect truncates long workout names


class PushError(ValueError):
    """A workout that cannot be pushed (rest day, unsupported sport)."""


def workout_name(workout: Workout, day: dt.date) -> str:
    """`"<planned name> (<date>)"` (METRICS §10.8 clarified), trimmed to Garmin's name length."""
    suffix = f" ({day.isoformat()})"
    return workout.name[: MAX_NAME - len(suffix)] + suffix


def _executable(step: Step, order: int) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "ExecutableStepDTO",
        "stepOrder": order,
        "stepType": dict(STEP_TYPES[step.type]),
        "endCondition": dict(TIME_CONDITION),
        "endConditionValue": float(step.duration_s),
    }
    target = step.target
    if isinstance(target, HrZoneTarget):
        out["targetType"] = dict(HR_ZONE_TARGET)
        out["zoneNumber"] = target.zone
    elif isinstance(target, PaceRangeTarget) and target.low_mps and target.high_mps:
        slow, fast = sorted((target.low_mps, target.high_mps))
        out["targetType"] = dict(PACE_TARGET)
        out["targetValueOne"], out["targetValueTwo"] = slow, fast
    else:
        out["targetType"] = dict(NO_TARGET)
        if isinstance(target, OpenTarget):
            out["description"] = f"Úsilie zóna {target.effort_zone}"
        elif isinstance(target, PaceRangeTarget):
            out["description"] = f"Tempová zóna {target.zone}"
    return out


def _steps(steps: list[Step | RepeatStep], start: int) -> tuple[list[dict[str, Any]], int]:
    """Garmin steps and the next free `stepOrder`."""
    out: list[dict[str, Any]] = []
    order = start
    for step in steps:
        if isinstance(step, RepeatStep):
            group_order = order
            children, order = _steps(list(step.steps), order + 1)
            out.append(
                {
                    "type": "RepeatGroupDTO",
                    "stepOrder": group_order,
                    "stepType": dict(REPEAT_TYPE),
                    "numberOfIterations": step.count,
                    "workoutSteps": children,
                    "endCondition": dict(ITERATIONS_CONDITION),
                    "endConditionValue": float(step.count),
                    "smartRepeat": False,
                }
            )
        else:
            out.append(_executable(step, order))
            order += 1
    return out, order


def to_garmin_payload(workout: Workout, day: dt.date, description: str | None = None) -> dict[str, Any]:
    """METRICS §10.8: the Garmin Connect workout JSON for `workout` planned on `day`."""
    if workout.sport not in SPORTS:
        raise PushError(f"{workout.sport} workouts are not pushed to Garmin")
    sport = SPORTS[workout.sport]
    steps, _ = _steps(list(workout.steps), 1)
    payload: dict[str, Any] = {
        "workoutName": workout_name(workout, day),
        "sportType": dict(sport),
        "estimatedDurationInSecs": total_duration_s(workout),
        "workoutSegments": [{"segmentOrder": 1, "sportType": dict(sport), "workoutSteps": steps}],
        "author": {},
    }
    if description:
        payload["description"] = description[:512]
    return payload
