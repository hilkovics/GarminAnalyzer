"""Workout schema and estimated load – METRICS §10.5–§10.6."""

import copy

import pytest
from pydantic import ValidationError

from training.coach.workout import (
    ZONE_IF,
    HrZoneTarget,
    OpenTarget,
    PaceRangeTarget,
    RepeatStep,
    Step,
    Workout,
    estimated_load,
    from_structure,
    rest_workout,
    step_zone,
    to_structure,
    total_duration_s,
)

# METRICS §10.5 – the example, verbatim.
EXAMPLE = {
    "sport": "run",
    "name": "Threshold 5x6",
    "steps": [
        {"type": "warmup", "duration_s": 900, "target": {"kind": "hr_zone", "zone": 2}},
        {
            "type": "repeat",
            "count": 5,
            "steps": [
                {"type": "work", "duration_s": 360, "target": {"kind": "hr_zone", "zone": 4}},
                {"type": "recovery", "duration_s": 120, "target": {"kind": "hr_zone", "zone": 1}},
            ],
        },
        {"type": "cooldown", "duration_s": 600, "target": {"kind": "hr_zone", "zone": 1}},
    ],
}


def _steady(duration_s: int, zone: int) -> Step:
    return Step(type="steady", duration_s=duration_s, target=HrZoneTarget(zone=zone))


# ---------------------------------------------------------------- §10.5 schema


def test_example_round_trips_exactly() -> None:
    w = from_structure(copy.deepcopy(EXAMPLE))
    assert w.sport == "run"
    assert w.key == ""
    assert w.slot is None and w.param is None
    assert isinstance(w.steps[1], RepeatStep)
    assert isinstance(w.steps[1].steps[0].target, HrZoneTarget)
    assert to_structure(w) == EXAMPLE
    assert from_structure(to_structure(w)) == w


def test_extra_keys_round_trip() -> None:
    d = copy.deepcopy(EXAMPLE) | {"key": "threshold", "slot": "q1", "param": 5}
    w = from_structure(d)
    assert (w.key, w.slot, w.param) == ("threshold", "q1", 5)
    assert to_structure(w) == d


def test_all_target_kinds_parse_by_discriminator() -> None:
    d = {
        "sport": "run",
        "name": "mix",
        "steps": [
            {"type": "steady", "duration_s": 60, "target": {"kind": "hr_zone", "zone": 3}},
            {"type": "work", "duration_s": 60, "target": {"kind": "pace_range", "zone": 4, "low_mps": 4.0}},
            {"type": "work", "duration_s": 20, "target": {"kind": "open", "effort_zone": 5}},
        ],
    }
    w = from_structure(d)
    kinds = [type(s.target) for s in w.steps]
    assert kinds == [HrZoneTarget, PaceRangeTarget, OpenTarget]
    # None-valued high_mps is dropped on dump
    assert to_structure(w) == d


@pytest.mark.parametrize("zone", [0, 6])
def test_zone_out_of_range_rejected(zone: int) -> None:
    with pytest.raises(ValidationError):
        HrZoneTarget(zone=zone)
    with pytest.raises(ValidationError):
        PaceRangeTarget(zone=zone)
    with pytest.raises(ValidationError):
        OpenTarget(effort_zone=zone)


@pytest.mark.parametrize("duration", [0, -5])
def test_non_positive_duration_rejected(duration: int) -> None:
    with pytest.raises(ValidationError):
        _steady(duration, 2)


def test_repeat_count_at_least_one() -> None:
    with pytest.raises(ValidationError):
        RepeatStep(type="repeat", count=0, steps=[_steady(60, 2)])


def test_nested_repeat_rejected() -> None:
    d = copy.deepcopy(EXAMPLE)
    d["steps"][1]["steps"].append({"type": "repeat", "count": 2, "steps": [EXAMPLE["steps"][0]]})
    with pytest.raises(ValidationError):
        from_structure(d)


def test_unknown_step_type_and_target_kind_rejected() -> None:
    d = copy.deepcopy(EXAMPLE)
    d["steps"][0]["type"] = "sprint"
    with pytest.raises(ValidationError):
        from_structure(d)
    d = copy.deepcopy(EXAMPLE)
    d["steps"][0]["target"] = {"kind": "power", "zone": 2}
    with pytest.raises(ValidationError):
        from_structure(d)


def test_bike_pace_range_rejected_top_level_and_in_repeat() -> None:
    pace = Step(type="work", duration_s=300, target=PaceRangeTarget(zone=4))
    with pytest.raises(ValidationError, match="pace_range"):
        Workout(sport="bike", name="x", key="x", steps=[pace])
    with pytest.raises(ValidationError, match="pace_range"):
        Workout(sport="bike", name="x", key="x", steps=[RepeatStep(type="repeat", count=2, steps=[pace])])
    # the same step is fine for a run
    assert Workout(sport="run", name="x", key="x", steps=[pace]).sport == "run"


def test_rest_has_no_steps_and_run_bike_need_steps() -> None:
    with pytest.raises(ValidationError):
        Workout(sport="rest", name="x", key="rest", steps=[_steady(60, 1)])
    for sport in ("run", "bike"):
        with pytest.raises(ValidationError):
            Workout(sport=sport, name="x", key="x", steps=[])
    with pytest.raises(ValidationError):
        Workout(sport="other", name="x", key="x", steps=[_steady(60, 1)])


def test_rest_workout() -> None:
    w = rest_workout()
    assert (w.sport, w.key, w.name, w.steps) == ("rest", "rest", "Voľno", [])
    assert rest_workout("Voľno – nízka pripravenosť").name == "Voľno – nízka pripravenosť"
    assert estimated_load(w) == 0.0
    assert total_duration_s(w) == 0
    assert from_structure(to_structure(w)) == w


# ---------------------------------------------------------------- §10.6 load


def test_zone_if_table() -> None:
    assert ZONE_IF == {1: 0.50, 2: 0.65, 3: 0.83, 4: 0.98, 5: 1.10}


def test_step_zone_per_target_kind() -> None:
    assert step_zone(_steady(60, 3)) == 3
    assert step_zone(Step(type="work", duration_s=60, target=PaceRangeTarget(zone=4))) == 4
    assert step_zone(Step(type="work", duration_s=60, target=OpenTarget(effort_zone=5))) == 5


def test_one_hour_z4() -> None:
    w = Workout(sport="run", name="x", key="x", steps=[_steady(3600, 4)])
    assert estimated_load(w) == pytest.approx(3600 * 0.98**2 / 36)
    assert estimated_load(w) == pytest.approx(96.04)


@pytest.mark.parametrize("zone", [1, 2, 3, 4, 5])
def test_one_hour_per_zone_is_100_if_squared(zone: int) -> None:
    w = Workout(sport="bike", name="x", key="x", steps=[_steady(3600, zone)])
    assert estimated_load(w) == pytest.approx(100 * ZONE_IF[zone] ** 2)


def test_example_by_hand() -> None:
    # 900 s Z2 + 5 × (360 s Z4 + 120 s Z1) + 600 s Z1
    expected = (900 * 0.65**2 + 5 * (360 * 0.98**2 + 120 * 0.50**2) + 600 * 0.50**2) / 36
    assert expected == pytest.approx(66.915833, abs=1e-6)
    w = from_structure(EXAMPLE)
    assert estimated_load(w) == pytest.approx(expected)
    assert total_duration_s(w) == 900 + 5 * 480 + 600


def test_open_and_pace_range_use_zone_if() -> None:
    w_open = Workout(
        sport="run",
        name="x",
        key="x",
        steps=[Step(type="work", duration_s=20, target=OpenTarget(effort_zone=5))],
    )
    w_pace = Workout(
        sport="run",
        name="x",
        key="x",
        steps=[Step(type="work", duration_s=20, target=PaceRangeTarget(zone=5, low_mps=5.0, high_mps=5.5))],
    )
    assert estimated_load(w_open) == pytest.approx(20 * 1.21 / 36)
    assert estimated_load(w_pace) == estimated_load(w_open)


def test_repeat_multiplies() -> None:
    once = Workout(sport="run", name="x", key="x", steps=[_steady(120, 4), _steady(60, 1)])
    rep = Workout(
        sport="run",
        name="x",
        key="x",
        steps=[RepeatStep(type="repeat", count=7, steps=[_steady(120, 4), _steady(60, 1)])],
    )
    assert estimated_load(rep) == pytest.approx(7 * estimated_load(once))
    assert total_duration_s(rep) == 7 * 180
