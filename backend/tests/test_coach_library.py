"""Workout library – METRICS §10.7 (with §10.4 rule 4 parameter fitting)."""

import dataclasses
from itertools import pairwise

import pytest

from training.coach import library
from training.coach.library import (
    LIBRARY,
    LibraryEntry,
    build,
    entry,
    fit_param,
    param_values,
    race_zone,
)
from training.coach.workout import (
    HrZoneTarget,
    OpenTarget,
    RepeatStep,
    Step,
    estimated_load,
    from_structure,
    step_zone,
    to_structure,
    total_duration_s,
)

RUN_KEYS = {
    "easy", "long", "long_build", "long_peak", "tempo", "threshold", "vo2", "hills", "progression",
    "strides", "race_pace", "race_pace_short", "short_intervals", "recovery",
}  # fmt: skip
BIKE_KEYS = {
    "recovery_spin", "endurance", "long_ride", "sweet_spot", "over_unders", "vo2", "race_pace",
    "race_pace_short", "short_intervals", "spin_ups", "recovery",
}  # fmt: skip
TOTAL_KEYS = [
    ("run", "easy"), ("run", "long"), ("run", "long_build"), ("run", "long_peak"), ("run", "progression"),
    ("bike", "endurance"), ("bike", "long_ride"),
]  # fmt: skip
# (sport, key) → (min, max, step, unit), exactly the clarified §10.7 ranges
EXPECTED_RANGES = {
    ("run", "easy"): (40, 75, 5, "min"),
    ("run", "long"): (90, 150, 5, "min"),
    ("run", "long_build"): (90, 150, 5, "min"),
    ("run", "long_peak"): (75, 110, 5, "min"),
    ("run", "tempo"): (20, 40, 5, "min"),
    ("run", "threshold"): (4, 6, 1, "reps"),
    ("run", "vo2"): (5, 8, 1, "reps"),
    ("run", "hills"): (8, 12, 1, "reps"),
    ("run", "progression"): (45, 75, 5, "min"),
    ("run", "strides"): (30, 50, 5, "min"),
    ("run", "race_pace"): (3, 5, 1, "reps"),
    ("run", "race_pace_short"): (2, 3, 1, "reps"),
    ("run", "short_intervals"): (8, 12, 1, "reps"),
    ("run", "recovery"): (40, 40, 5, "min"),
    ("bike", "recovery_spin"): (45, 45, 5, "min"),
    ("bike", "endurance"): (90, 180, 5, "min"),
    ("bike", "long_ride"): (120, 240, 5, "min"),
    ("bike", "sweet_spot"): (2, 3, 1, "reps"),
    ("bike", "over_unders"): (3, 3, 1, "reps"),
    ("bike", "vo2"): (5, 8, 1, "reps"),
    ("bike", "race_pace"): (3, 5, 1, "reps"),
    ("bike", "race_pace_short"): (2, 3, 1, "reps"),
    ("bike", "short_intervals"): (8, 12, 1, "reps"),
    ("bike", "spin_ups"): (60, 90, 5, "min"),
    ("bike", "recovery"): (40, 40, 5, "min"),
}
ALL = sorted(LIBRARY)


def _flat(w) -> list[Step]:
    out: list[Step] = []
    for s in w.steps:
        out.extend(s.steps * s.count if isinstance(s, RepeatStep) else [s])
    return out


def _zone_seconds(w) -> dict[int, int]:
    acc: dict[int, int] = {}
    for s in _flat(w):
        acc[step_zone(s)] = acc.get(step_zone(s), 0) + s.duration_s
    return acc


# ---------------------------------------------------------------- catalogue


def test_keys_per_sport() -> None:
    assert {k for s, k in LIBRARY if s == "run"} == RUN_KEYS
    assert {k for s, k in LIBRARY if s == "bike"} == BIKE_KEYS
    assert set(LIBRARY) == set(EXPECTED_RANGES)


@pytest.mark.parametrize("sk", ALL)
def test_ranges_exactly_as_clarified(sk: tuple[str, str]) -> None:
    e = LIBRARY[sk]
    assert isinstance(e, LibraryEntry)
    assert (e.sport, e.key) == sk
    assert (e.param_min, e.param_max, e.param_step, e.param_unit) == EXPECTED_RANGES[sk]
    assert entry(*sk) is e
    lo, hi, step, _ = EXPECTED_RANGES[sk]
    assert param_values(*sk) == list(range(lo, hi + 1, step))


def test_entry_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        entry("run", "easy").name = "x"  # type: ignore[misc]


def test_slovak_names() -> None:
    names = {sk: e.name for sk, e in LIBRARY.items()}
    assert names[("run", "easy")] == "Ľahký beh"
    assert names[("run", "long")] == "Dlhý beh"
    assert names[("run", "tempo")] == "Tempo"
    assert names[("run", "threshold")] == "Prahové intervaly"
    assert names[("run", "vo2")] == names[("bike", "vo2")] == "VO2 intervaly"
    assert names[("run", "hills")] == "Kopce"
    assert names[("run", "progression")] == "Progresívny beh"
    assert names[("run", "strides")] == "Rovinky"
    assert names[("run", "race_pace")] == "Závodné tempo"
    assert names[("run", "short_intervals")] == "Krátke intervaly"
    assert names[("run", "recovery")] == names[("bike", "recovery")] == "Regenerácia"
    assert names[("bike", "endurance")] == "Vytrvalostná jazda"
    assert names[("bike", "long_ride")] == "Dlhá jazda"
    assert names[("bike", "sweet_spot")] == "Sweet spot"
    assert names[("bike", "over_unders")] == "Over-unders"
    assert names[("bike", "spin_ups")] == "Spin-ups"
    assert names[("bike", "recovery_spin")] == "Regeneračné točenie"


def test_unknown_key_lists_valid_keys() -> None:
    with pytest.raises(KeyError, match="threshold"):
        entry("run", "nope")
    with pytest.raises(KeyError, match="sweet_spot"):
        build("bike", "tempo")
    with pytest.raises(KeyError):
        entry("rest", "rest")


# ---------------------------------------------------------------- build


@pytest.mark.parametrize("sk", ALL)
def test_builds_at_min_and_max_and_round_trips(sk: tuple[str, str]) -> None:
    e = LIBRARY[sk]
    for p in {e.param_min, e.param_max}:
        w = build(*sk, p)
        assert (w.sport, w.key, w.param, w.slot) == (sk[0], sk[1], p, None)
        assert w.name.startswith(e.name)
        assert str(p) in w.name
        assert from_structure(to_structure(w)) == w
        assert estimated_load(w) > 0
    assert build(*sk).param == e.param_min


@pytest.mark.parametrize("sk", ALL)
@pytest.mark.parametrize("race", [3, 4, 5])
def test_every_value_round_trips(sk: tuple[str, str], race: int) -> None:
    for p in param_values(*sk):
        w = build(*sk, p, race_zone=race)
        assert from_structure(to_structure(w)) == w


@pytest.mark.parametrize("sk", TOTAL_KEYS)
def test_total_duration_equals_param(sk: tuple[str, str]) -> None:
    for p in param_values(*sk):
        assert total_duration_s(build(*sk, p)) == p * 60


@pytest.mark.parametrize("sk", [sk for sk in ALL if EXPECTED_RANGES[sk][0] < EXPECTED_RANGES[sk][1]])
def test_load_strictly_increasing_in_param(sk: tuple[str, str]) -> None:
    loads = [estimated_load(build(*sk, p)) for p in param_values(*sk)]
    assert all(b > a for a, b in pairwise(loads))


@pytest.mark.parametrize("sk", ALL)
def test_bike_is_hr_or_open_only(sk: tuple[str, str]) -> None:
    for s in _flat(build(*sk)):
        assert isinstance(s.target, HrZoneTarget | OpenTarget)


def test_out_of_range_or_off_step_raises() -> None:
    for bad in (3, 7):
        with pytest.raises(ValueError, match="threshold"):
            build("run", "threshold", bad)
    with pytest.raises(ValueError):
        build("run", "easy", 42)  # off the 5-min step
    with pytest.raises(ValueError):
        build("run", "easy", 80)
    with pytest.raises(ValueError):
        build("bike", "recovery_spin", 50)
    with pytest.raises(ValueError):
        build("run", "race_pace", 4, race_zone=6)


def test_threshold_structure_and_hand_load() -> None:
    w = build("run", "threshold", 5)
    assert w.name == "Prahové intervaly 5×6 min"
    assert to_structure(w)["steps"] == [
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
    ]
    expected = (900 * 0.65**2 + 5 * (360 * 0.98**2 + 120 * 0.50**2) + 600 * 0.50**2) / 36
    assert estimated_load(w) == pytest.approx(expected)
    assert estimated_load(w) == pytest.approx(66.915833, abs=1e-6)


QUALITY = [
    ("run", "tempo"), ("run", "threshold"), ("run", "vo2"), ("run", "hills"), ("run", "race_pace"),
    ("run", "race_pace_short"), ("run", "short_intervals"), ("bike", "sweet_spot"), ("bike", "over_unders"),
    ("bike", "vo2"), ("bike", "race_pace"), ("bike", "race_pace_short"), ("bike", "short_intervals"),
]  # fmt: skip


@pytest.mark.parametrize("sk", QUALITY)
def test_quality_warmup_and_cooldown(sk: tuple[str, str]) -> None:
    w = build(*sk)
    first, last = w.steps[0], w.steps[-1]
    assert (first.type, first.duration_s, step_zone(first)) == ("warmup", 900, 2)
    assert (last.type, last.duration_s, step_zone(last)) == ("cooldown", 600, 1)


@pytest.mark.parametrize("sk", [sk for sk in ALL if sk not in QUALITY])
def test_non_quality_has_no_warmup(sk: tuple[str, str]) -> None:
    assert all(s.type not in ("warmup", "cooldown") for s in build(*sk).steps)


def test_zone_contents() -> None:
    assert _zone_seconds(build("run", "easy", 50)) == {2: 3000}
    assert _zone_seconds(build("run", "long", 120)) == {2: 7200}
    assert _zone_seconds(build("run", "long_peak", 80)) == {2: 4800}
    assert _zone_seconds(build("run", "tempo", 30)) == {2: 900, 4: 1800, 1: 600}
    assert _zone_seconds(build("run", "vo2", 6)) == {2: 900, 5: 6 * 180, 1: 6 * 120 + 600}
    assert _zone_seconds(build("run", "hills", 10)) == {2: 900, 5: 750, 1: 1200 + 600}
    assert _zone_seconds(build("run", "short_intervals", 10)) == {2: 900, 5: 600, 1: 600 + 600}
    assert _zone_seconds(build("run", "recovery")) == {1: 2400}
    assert _zone_seconds(build("bike", "recovery_spin")) == {1: 2700}
    assert _zone_seconds(build("bike", "recovery")) == {1: 2400}
    assert _zone_seconds(build("bike", "endurance", 120)) == {2: 7200}
    assert _zone_seconds(build("bike", "sweet_spot", 3)) == {2: 900, 3: 3600, 1: 900 + 600}
    assert _zone_seconds(build("bike", "vo2", 5)) == {2: 900, 5: 900, 1: 900 + 600}
    assert _zone_seconds(build("run", "strides", 40)) == {2: 2400, 5: 120, 1: 360}
    assert _zone_seconds(build("bike", "spin_ups", 60)) == {2: 3600, 5: 120, 1: 360}


def test_hills_and_strides_use_open_effort() -> None:
    hard = [s for s in _flat(build("run", "hills", 8)) if s.type == "work"]
    assert len(hard) == 8
    assert all(s.duration_s == 75 and s.target == OpenTarget(effort_zone=5) for s in hard)
    fast = [s for s in _flat(build("run", "strides", 30)) if s.type == "work"]
    assert len(fast) == 6
    assert all(s.duration_s == 20 and s.target == OpenTarget(effort_zone=5) for s in fast)


def test_long_build_last_20_min_z3() -> None:
    w = build("run", "long_build", 100)
    assert w.steps[-1].duration_s == 1200 and step_zone(w.steps[-1]) == 3
    assert _zone_seconds(w) == {2: 4800, 3: 1200}
    assert "Dlhý beh 100 min" in w.name


def test_progression_last_20_min() -> None:
    w = build("run", "progression", 60)
    assert [(s.duration_s, step_zone(s)) for s in w.steps] == [(2400, 2), (600, 3), (600, 4)]


def test_long_ride_three_z3_blocks_in_the_middle() -> None:
    w = build("bike", "long_ride", 150)
    assert [step_zone(s) for s in w.steps] == [2, 3, 2, 3, 2, 3, 2]
    z3 = [s.duration_s for s in w.steps if step_zone(s) == 3]
    z2 = [s.duration_s for s in w.steps if step_zone(s) == 2]
    assert z3 == [600, 600, 600]
    assert len(set(z2)) == 1  # equal Z2 gaps: blocks evenly spread, first/last Z2 as warm-up/cool-down
    assert z2[0] == (150 - 30) * 60 // 4


def test_over_unders_structure() -> None:
    w = build("bike", "over_unders")
    assert w.name == "Over-unders 3×12 min"
    sets = [s for s in w.steps if isinstance(s, RepeatStep)]
    assert len(sets) == 3
    for s in sets:
        assert s.count == 4
        assert [(x.duration_s, step_zone(x)) for x in s.steps] == [(120, 4), (60, 3)]
    between = [s for s in w.steps if isinstance(s, Step) and s.type == "recovery"]
    assert [(s.duration_s, step_zone(s)) for s in between] == [(300, 1), (300, 1)]
    assert total_duration_s(w) == 900 + 3 * 720 + 2 * 300 + 600


@pytest.mark.parametrize("sport", ["run", "bike"])
@pytest.mark.parametrize("zone", [3, 4, 5])
def test_race_pace_uses_race_zone(sport: str, zone: int) -> None:
    for key, reps in (("race_pace", 4), ("race_pace_short", 2)):
        w = build(sport, key, reps, race_zone=zone)
        assert _zone_seconds(w) == {2: 900, zone: reps * 480, 1: reps * 180 + 600}
    assert build(sport, "race_pace").steps[1].steps[0].target.zone == 4  # default race zone


def test_names_include_param() -> None:
    assert build("run", "easy", 50).name == "Ľahký beh 50 min"
    assert build("run", "vo2", 6).name == "VO2 intervaly 6×3 min"
    assert build("bike", "sweet_spot", 2).name == "Sweet spot 2×20 min"
    assert build("run", "race_pace", 4).name == "Závodné tempo 4×8 min"


# ---------------------------------------------------------------- fit_param


def test_fit_param_picks_closest() -> None:
    loads = {p: estimated_load(build("run", "threshold", p)) for p in param_values("run", "threshold")}
    assert fit_param("run", "threshold", loads[5]) == 5
    assert fit_param("run", "threshold", loads[5] + 0.1) == 5
    assert fit_param("run", "threshold", 0.0) == 4
    assert fit_param("run", "threshold", 1e6) == 6
    assert fit_param("run", "easy", estimated_load(build("run", "easy", 60)) + 0.5) == 60
    assert fit_param("bike", "recovery_spin", 500.0) == 45


def test_fit_param_tie_goes_to_smaller() -> None:
    # easy: 5 min Z2 = 300·0.4225/36 points per step; the exact midpoint between 50 and 55 min is a tie
    mid = (estimated_load(build("run", "easy", 50)) + estimated_load(build("run", "easy", 55))) / 2
    assert fit_param("run", "easy", mid) == 50
    mid = (estimated_load(build("run", "vo2", 6)) + estimated_load(build("run", "vo2", 7))) / 2
    assert fit_param("run", "vo2", mid) == 6


def test_fit_param_respects_race_zone() -> None:
    target = estimated_load(build("run", "race_pace", 4, race_zone=5))
    assert fit_param("run", "race_pace", target, race_zone=5) == 4
    assert fit_param("run", "race_pace", target, race_zone=3) == 5


def test_fit_param_none_without_parameter(monkeypatch: pytest.MonkeyPatch) -> None:
    # No shipped entry lacks a parameter (§10.4 rule 4); the branch is exercised with a patched entry.
    patched = dict(LIBRARY)
    patched[("bike", "over_unders")] = dataclasses.replace(
        LIBRARY[("bike", "over_unders")], param_min=None, param_max=None, param_step=None, param_unit=None
    )
    monkeypatch.setattr(library, "LIBRARY", patched)
    assert fit_param("bike", "over_unders", 80.0) is None
    assert param_values("bike", "over_unders") == []
    assert build("bike", "over_unders").param is None
    with pytest.raises(ValueError):
        build("bike", "over_unders", 3)


# ---------------------------------------------------------------- race zone


@pytest.mark.parametrize(
    ("sport", "dist", "time", "zone"),
    [
        (None, None, None, 4),
        ("run", 3000.0, None, 5),
        ("run", 5000.0, 1200.0, 5),
        ("run", 5001.0, None, 4),
        ("run", 10000.0, 2400.0, 4),
        ("run", 21097.5, None, 4),
        ("run", 21100.0, None, 4),
        ("run", 21101.0, None, 3),
        ("run", 42195.0, 10800.0, 3),
        ("run", None, 3600.0, 4),
        ("bike", 40000.0, 3600.0, 4),
        ("bike", 60000.0, 7200.0, 4),
        ("bike", 90000.0, 7201.0, 3),
        ("bike", 180000.0, 18000.0, 3),
        ("bike", 40000.0, None, 4),
        ("other", 5000.0, 1200.0, 4),
    ],
)
def test_race_zone(sport: str | None, dist: float | None, time: float | None, zone: int) -> None:
    assert race_zone(sport, dist, time) == zone
