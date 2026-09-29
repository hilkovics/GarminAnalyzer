"""Weekly template: roles per weekday, phase transforms, slot → workout key, slot sport (METRICS §10.3)."""

import pytest

from training.coach.template import (
    DEFAULT_ROLES,
    ROLES,
    WEEKDAYS,
    DaySlot,
    parse_preferred_days,
    rest_quota,
    slot_sport,
    week_roles,
    workout_key,
)


def roles_of(slots: dict[str, DaySlot]) -> tuple[str, ...]:
    assert tuple(slots) == WEEKDAYS
    return tuple(slots[d].role for d in WEEKDAYS)


# ---------------------------------------------------------------------------------------------------------
# constants, parse_preferred_days
# ---------------------------------------------------------------------------------------------------------


def test_constants() -> None:
    assert ROLES == ("rest", "easy", "long", "q1", "q2")
    assert WEEKDAYS == ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    assert DEFAULT_ROLES == {
        "mon": "rest",
        "tue": "q1",
        "wed": "easy",
        "thu": "q2",
        "fri": "easy",
        "sat": "long",
        "sun": "easy",
    }


@pytest.mark.parametrize("raw", [None, {}])
def test_parse_defaults(raw: dict | None) -> None:
    slots = parse_preferred_days(raw)
    assert roles_of(slots) == ("rest", "q1", "easy", "q2", "easy", "long", "easy")
    assert all(s.sport is None for s in slots.values())
    assert slots["sat"] == DaySlot("sat", "long", None)


def test_parse_overrides_and_order() -> None:
    raw = {"sun": {"role": "long", "sport": "bike"}, "sat": "easy", "wed": {"role": "q1"}, "fri": "rest"}
    slots = parse_preferred_days(raw)
    assert roles_of(slots) == ("rest", "q1", "q1", "q2", "rest", "easy", "long")
    assert slots["sun"] == DaySlot("sun", "long", "bike")
    assert slots["wed"] == DaySlot("wed", "q1", None)
    assert slots["mon"] == DaySlot("mon", "rest", None)  # missing → default


def test_parse_accepts_dayslots_and_explicit_null_sport() -> None:
    raw = {"tue": DaySlot("tue", "q1", "run"), "wed": {"role": "easy", "sport": None}}
    slots = parse_preferred_days(raw)
    assert slots["tue"] == DaySlot("tue", "q1", "run")
    assert slots["wed"] == DaySlot("wed", "easy", None)
    assert parse_preferred_days(slots) == slots  # idempotent


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ([("mon", "rest")], "dict"),
        ({"monday": "rest"}, "weekday"),
        ({"Mon": "rest"}, "weekday"),
        ({"mon": "sleep"}, "role"),
        ({"mon": 3}, "role string or"),
        ({"mon": {"sport": "run"}}, "role"),
        ({"mon": {"role": "tempo"}}, "role"),
        ({"mon": {"role": "easy", "sport": "swim"}}, "sport"),
        ({"mon": {"role": "easy", "sport": "other"}}, "sport"),
        ({"mon": {"role": "easy", "extra": 1}}, "unknown key"),
        ({"mon": {"role": "rest", "sport": "run"}}, "rest"),
        ({"mon": DaySlot("tue", "rest", None)}, "weekday"),
    ],
)
def test_parse_errors(raw: object, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        parse_preferred_days(raw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------------------------------------
# week_roles – per-phase transforms
# ---------------------------------------------------------------------------------------------------------


def test_week_roles_default_per_phase() -> None:
    assert roles_of(week_roles("base", None)) == ("rest", "q1", "easy", "easy", "easy", "long", "easy")
    assert roles_of(week_roles("build", None)) == ("rest", "q1", "easy", "q2", "easy", "long", "easy")
    # the easy day right before long (fri) → rest
    assert roles_of(week_roles("peak", None)) == ("rest", "q1", "easy", "q2", "rest", "long", "easy")
    assert roles_of(week_roles("taper", None)) == ("rest", "q1", "easy", "q2", "easy", "easy", "easy")


def test_week_roles_keep_explicit_sport_and_clear_it_on_rest() -> None:
    raw = {"thu": {"role": "q2", "sport": "bike"}, "fri": {"role": "easy", "sport": "bike"}}
    raw |= {"sat": {"role": "long", "sport": "bike"}}
    base = week_roles("base", raw)
    assert base["thu"] == DaySlot("thu", "easy", "bike")
    peak = week_roles("peak", raw)
    assert peak["fri"] == DaySlot("fri", "rest", None)
    taper = week_roles("taper", raw)
    assert taper["sat"] == DaySlot("sat", "easy", "bike")


def test_peak_falls_back_to_the_last_easy_day() -> None:
    # the day before long is q1 → the last easy day of the week (sun) becomes rest
    raw = {"fri": "q1", "tue": "easy"}
    assert roles_of(week_roles("peak", raw)) == ("rest", "easy", "easy", "q2", "q1", "long", "rest")
    # long on Monday: no day before it inside the week → last easy day
    raw = {"mon": "long", "sat": "rest"}
    assert roles_of(week_roles("peak", raw)) == ("long", "q1", "easy", "q2", "easy", "rest", "rest")


def test_custom_layout_without_long_day() -> None:
    raw = {"sat": "easy"}
    assert roles_of(week_roles("peak", raw)) == ("rest", "q1", "easy", "q2", "easy", "easy", "rest")
    assert roles_of(week_roles("taper", raw)) == ("rest", "q1", "easy", "q2", "easy", "easy", "easy")


def test_custom_layout_two_q1_and_two_long_days() -> None:
    raw = {"thu": "q1", "sun": "long", "fri": "easy", "wed": "easy"}
    assert roles_of(week_roles("base", raw)) == ("rest", "q1", "easy", "q1", "easy", "long", "long")
    # two long days: only the easy day before the first long (fri) becomes rest; exactly one extra rest
    assert roles_of(week_roles("peak", raw)) == ("rest", "q1", "easy", "q1", "rest", "long", "long")
    assert roles_of(week_roles("taper", raw)) == ("rest", "q1", "easy", "q1", "easy", "easy", "easy")


def test_peak_without_any_easy_day_is_unchanged() -> None:
    raw = {"wed": "q2", "fri": "long", "sun": "rest"}  # rest q1 q2 q2 long long rest
    assert roles_of(week_roles("peak", raw)) == ("rest", "q1", "q2", "q2", "long", "long", "rest")


def test_week_roles_rejects_unknown_phase() -> None:
    with pytest.raises(ValueError, match="phase"):
        week_roles("recovery", None)


def test_rest_quota() -> None:
    assert rest_quota(week_roles("build", None)) == 1
    assert rest_quota(week_roles("peak", None)) == 2
    assert rest_quota(parse_preferred_days(dict.fromkeys(WEEKDAYS, "rest"))) == 7


# ---------------------------------------------------------------------------------------------------------
# workout_key
# ---------------------------------------------------------------------------------------------------------


def test_rest_has_no_workout() -> None:
    for sport in ("run", "bike"):
        for phase in ("base", "build", "peak", "taper"):
            assert workout_key(sport, phase, "rest", 5) is None


def test_run_keys() -> None:
    assert [workout_key("run", "base", "q1", k) for k in range(7)] == [
        "tempo",
        "hills",
        "progression",
        "tempo",
        "hills",
        "progression",
        "tempo",
    ]
    assert [workout_key("run", "build", "q2", k) for k in range(4)] == ["vo2", "hills", "vo2", "hills"]
    assert workout_key("run", "build", "q1", 7) == "threshold"
    assert workout_key("run", "peak", "q1", 7) == "race_pace"
    assert workout_key("run", "peak", "q2", 7) == "short_intervals"
    assert workout_key("run", "taper", "q1", 7) == "race_pace_short"
    assert workout_key("run", "taper", "q2", 7) == "strides"
    for phase in ("base", "build", "peak", "taper"):
        assert workout_key("run", phase, "easy", 3) == "easy"
    assert workout_key("run", "base", "long", 0) == "long"
    assert workout_key("run", "build", "long", 0) == "long_build"
    assert workout_key("run", "peak", "long", 0) == "long_peak"


def test_bike_keys() -> None:
    for phase in ("base", "build", "peak", "taper"):
        assert workout_key("bike", phase, "easy", 1) == "endurance"
    for phase in ("base", "build", "peak"):
        assert workout_key("bike", phase, "long", 1) == "long_ride"
    assert [workout_key("bike", "base", "q1", k) for k in range(3)] == ["sweet_spot"] * 3
    assert workout_key("bike", "build", "q1", 0) == "over_unders"
    assert [workout_key("bike", "build", "q2", k) for k in range(2)] == ["vo2", "vo2"]
    assert workout_key("bike", "peak", "q1", 0) == "race_pace"
    assert workout_key("bike", "peak", "q2", 0) == "short_intervals"
    assert workout_key("bike", "taper", "q1", 0) == "race_pace_short"
    assert workout_key("bike", "taper", "q2", 0) == "spin_ups"


def test_transformed_away_slots_map_like_their_transform() -> None:
    # week_roles never yields Base q2 or Taper long; if asked anyway, they map like the easy they become
    assert workout_key("run", "base", "q2", 0) == "easy"
    assert workout_key("bike", "base", "q2", 0) == "endurance"
    assert workout_key("run", "taper", "long", 0) == "easy"
    assert workout_key("bike", "taper", "long", 0) == "endurance"


def test_negative_cycle_k_rotates_without_gaps() -> None:
    assert workout_key("run", "base", "q1", -1) == "progression"  # −1 % 3 == 2
    assert workout_key("run", "build", "q2", -1) == "hills"  # odd


@pytest.mark.parametrize(
    ("args", "match"),
    [
        (("other", "base", "easy", 0), "sport"),
        (("run", "recovery", "easy", 0), "phase"),
        (("run", "base", "tempo", 0), "role"),
    ],
)
def test_workout_key_errors(args: tuple, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        workout_key(*args)


def test_every_default_week_maps_to_known_keys() -> None:
    run_keys = {
        "easy", "long", "long_build", "long_peak", "tempo", "threshold", "vo2", "hills", "progression",
        "strides", "race_pace", "race_pace_short", "short_intervals",
    }  # fmt: skip
    bike_keys = {
        "endurance", "long_ride", "sweet_spot", "over_unders", "vo2", "race_pace", "race_pace_short",
        "short_intervals", "spin_ups",
    }  # fmt: skip
    seen_run: set[str] = set()
    seen_bike: set[str] = set()
    for phase in ("base", "build", "peak", "taper"):
        for k in range(6):
            for slot in week_roles(phase, None).values():
                seen_run.add(workout_key("run", phase, slot.role, k) or "rest")
                seen_bike.add(workout_key("bike", phase, slot.role, k) or "rest")
    assert seen_run - {"rest"} == run_keys
    assert seen_bike - {"rest"} == bike_keys


# ---------------------------------------------------------------------------------------------------------
# slot_sport
# ---------------------------------------------------------------------------------------------------------


def test_slot_sport_explicit_wins() -> None:
    assert slot_sport(DaySlot("sat", "long", "bike"), "run", 500.0, 0.0) == "bike"
    assert slot_sport(DaySlot("wed", "easy", "run"), None, 0.0, 500.0) == "run"


@pytest.mark.parametrize("role", ["q1", "q2", "long"])
def test_slot_sport_quality_and_long_use_the_goal_sport(role: str) -> None:
    slot = DaySlot("tue", role, None)
    assert slot_sport(slot, "bike", 900.0, 0.0) == "bike"
    assert slot_sport(slot, "run", 0.0, 900.0) == "run"
    assert slot_sport(slot, None, 0.0, 900.0) == "run"  # no goal → run
    assert slot_sport(slot, "other", 0.0, 900.0) == "run"  # no library for "other" → run


def test_slot_sport_easy_uses_the_larger_remaining_target() -> None:
    slot = DaySlot("wed", "easy", None)
    assert slot_sport(slot, "run", 100.0, 250.0) == "bike"
    assert slot_sport(slot, "bike", 250.0, 100.0) == "run"
    assert slot_sport(slot, "bike", 100.0, 100.0) == "run"  # tie → run
    assert slot_sport(slot, None, 0.0, 0.0) == "run"


def test_slot_sport_rest() -> None:
    assert slot_sport(DaySlot("mon", "rest", None), "bike", 0.0, 500.0) == "rest"
