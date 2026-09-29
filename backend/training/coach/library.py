"""Workout library as data – METRICS §10.7 (phase 6), parameter fitting per §10.4 rule 4.

# METRICS §10.7 (clarified 2026-09-29, phase 6)
Quality sessions have warm-up 15 min Z2 and cool-down 10 min Z1. Parameter (range, step):
- run: easy total 40–75 min; long total 90–150 (Peak 75–110; Build: last 20 min Z3); tempo main 20–40 min
  Z4; threshold 4–6 × (6 min Z4 / 2 min Z1); VO2 5–8 × (3 min Z5 / 2 min Z1); hill repeats 8–12 × (75 s
  open effort 5 / 120 s Z1); progression total 45–75 min (last 20 min: 10 Z3 + 10 Z4); strides: easy
  30–50 min Z2 + 6 × (20 s open effort 5 / 60 s Z1); race-pace 3–5 × (8 min at race zone / 3 min Z1),
  short race-pace 2–3 reps; short intervals 8–12 × (1 min Z5 / 1 min Z1); recovery 40 min Z1 (fixed).
- bike: recovery spin 45 min Z1 (fixed); endurance 90–180 min; long ride 120–240 min (Z2, 3 × 10 min Z3
  spread over the middle); sweet spot 2–3 × (20 min Z3 / 5 min Z1); over-unders 3 × [4 × (2 min Z4 /
  1 min Z3)] with 5 min Z1 between sets (fixed); bike VO2 5–8 × (3 min Z5 / 3 min Z1); race-pace / short
  race-pace / short intervals as run; spin-ups: endurance 60–90 min + 6 × (20 s open effort 5 / 60 s Z1);
  recovery 40 min Z1.
- Race zone from the goal: run ≤ 5 km Z5, ≤ 21.1 km Z4, longer Z3; bike Z4 if `target_time_s ≤ 2 h`,
  else Z3; no goal → Z4.
# METRICS §10.4 rule 4: one integer parameter per workout (minutes in 5-min steps, or reps); the value
whose `estimated_load` (§10.6) is closest to the target wins, ties → the smaller.

Implementation choices (not fixed by the spec):
- "Quality" = tempo, threshold, VO2, hills, race-pace (both), short intervals, sweet spot, over-unders.
  Easy/long/progression/recovery are "total" or fixed durations; strides/spin-ups are "easy X min + 6 ×
  (20 s / 60 s)" exactly as written, so neither gets an extra warm-up/cool-down.
- Fixed workouts carry their only value as `param_min == param_max` (recovery 40 min, recovery spin
  45 min, over-unders 3 sets), so every shipped entry has a parameter as §10.4 rule 4 says.
- Long ride: the three 10-min Z3 blocks split the Z2 time into four equal parts
  (Z2 a, Z3 10, Z2 a, Z3 10, Z2 a, Z3 10, Z2 a with a = (T − 30) / 4 min, whole seconds for any T).
- All targets are `hr_zone` (or `open` for short efforts); speed bounds of `pace_range` need a threshold
  and are the caller's business. Pure functions, no I/O.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from training.coach.workout import (
    HrZoneTarget,
    OpenTarget,
    RepeatStep,
    Step,
    Workout,
    estimated_load,
)

WARMUP_S = 15 * 60  # §10.7 clarification: warm-up 15 min Z2
COOLDOWN_S = 10 * 60  # §10.7 clarification: cool-down 10 min Z1
_TIE_EPS = 1e-9  # load differences below this count as a tie (float noise), → the smaller param

StepKind = Literal["warmup", "work", "recovery", "cooldown", "steady"]


@dataclass(frozen=True)
class LibraryEntry:
    """One §10.7 workout: Slovak display `name` and its integer parameter range (None: no parameter)."""

    sport: str
    key: str
    name: str
    param_min: int | None
    param_max: int | None
    param_step: int | None
    param_unit: Literal["min", "reps"] | None


def _e(sport: str, key: str, name: str, lo: int, hi: int, unit: Literal["min", "reps"]) -> LibraryEntry:
    return LibraryEntry(sport, key, name, lo, hi, 5 if unit == "min" else 1, unit)


LIBRARY: dict[tuple[str, str], LibraryEntry] = {
    (e.sport, e.key): e
    for e in (
        _e("run", "easy", "Ľahký beh", 40, 75, "min"),
        _e("run", "long", "Dlhý beh", 90, 150, "min"),
        _e("run", "long_build", "Dlhý beh", 90, 150, "min"),
        _e("run", "long_peak", "Dlhý beh", 75, 110, "min"),
        _e("run", "tempo", "Tempo", 20, 40, "min"),
        _e("run", "threshold", "Prahové intervaly", 4, 6, "reps"),
        _e("run", "vo2", "VO2 intervaly", 5, 8, "reps"),
        _e("run", "hills", "Kopce", 8, 12, "reps"),
        _e("run", "progression", "Progresívny beh", 45, 75, "min"),
        _e("run", "strides", "Rovinky", 30, 50, "min"),
        _e("run", "race_pace", "Závodné tempo", 3, 5, "reps"),
        _e("run", "race_pace_short", "Závodné tempo", 2, 3, "reps"),
        _e("run", "short_intervals", "Krátke intervaly", 8, 12, "reps"),
        _e("run", "recovery", "Regenerácia", 40, 40, "min"),
        _e("bike", "recovery_spin", "Regeneračné točenie", 45, 45, "min"),
        _e("bike", "endurance", "Vytrvalostná jazda", 90, 180, "min"),
        _e("bike", "long_ride", "Dlhá jazda", 120, 240, "min"),
        _e("bike", "sweet_spot", "Sweet spot", 2, 3, "reps"),
        _e("bike", "over_unders", "Over-unders", 3, 3, "reps"),
        _e("bike", "vo2", "VO2 intervaly", 5, 8, "reps"),
        _e("bike", "race_pace", "Závodné tempo", 3, 5, "reps"),
        _e("bike", "race_pace_short", "Závodné tempo", 2, 3, "reps"),
        _e("bike", "short_intervals", "Krátke intervaly", 8, 12, "reps"),
        _e("bike", "spin_ups", "Spin-ups", 60, 90, "min"),
        _e("bike", "recovery", "Regenerácia", 40, 40, "min"),
    )
}


# ---------------------------------------------------------------- step helpers


def _hr(kind: StepKind, seconds: int, zone: int) -> Step:
    return Step(type=kind, duration_s=seconds, target=HrZoneTarget(zone=zone))


def _open(kind: StepKind, seconds: int, effort_zone: int) -> Step:
    return Step(type=kind, duration_s=seconds, target=OpenTarget(effort_zone=effort_zone))


def _repeat(count: int, *steps: Step) -> RepeatStep:
    return RepeatStep(type="repeat", count=count, steps=list(steps))


def _quality(*main: Step | RepeatStep) -> list[Step | RepeatStep]:
    """Warm-up 15 min Z2 + main set + cool-down 10 min Z1 (§10.7 clarification)."""
    return [_hr("warmup", WARMUP_S, 2), *main, _hr("cooldown", COOLDOWN_S, 1)]


def _intervals(reps: int, work_s: int, work_zone: int, rec_s: int) -> list[Step | RepeatStep]:
    """Quality session of `reps` × (work at `work_zone` / recovery Z1)."""
    return _quality(_repeat(reps, _hr("work", work_s, work_zone), _hr("recovery", rec_s, 1)))


def _efforts(easy_min: int) -> list[Step | RepeatStep]:
    """Strides / spin-ups: easy Z2 + 6 × (20 s open effort 5 / 60 s Z1) (§10.7)."""
    return [_hr("steady", easy_min * 60, 2), _repeat(6, _open("work", 20, 5), _hr("recovery", 60, 1))]


# ---------------------------------------------------------------- builders: param → (name suffix, steps)

_Built = tuple[str, list[Step | RepeatStep]]


def _easy(p: int, _rz: int) -> _Built:
    return f"{p} min", [_hr("steady", p * 60, 2)]


def _long_build(p: int, _rz: int) -> _Built:
    return f"{p} min (posledných 20 min Z3)", [_hr("steady", (p - 20) * 60, 2), _hr("work", 20 * 60, 3)]


def _tempo(p: int, _rz: int) -> _Built:
    return f"{p} min", _quality(_hr("work", p * 60, 4))


def _threshold(p: int, _rz: int) -> _Built:
    return f"{p}×6 min", _intervals(p, 360, 4, 120)


def _run_vo2(p: int, _rz: int) -> _Built:
    return f"{p}×3 min", _intervals(p, 180, 5, 120)


def _bike_vo2(p: int, _rz: int) -> _Built:
    return f"{p}×3 min", _intervals(p, 180, 5, 180)


def _hills(p: int, _rz: int) -> _Built:
    return f"{p}×75 s", _quality(_repeat(p, _open("work", 75, 5), _hr("recovery", 120, 1)))


def _progression(p: int, _rz: int) -> _Built:
    steps: list[Step | RepeatStep] = [
        _hr("steady", (p - 20) * 60, 2),
        _hr("work", 600, 3),
        _hr("work", 600, 4),
    ]
    return f"{p} min", steps


def _strides(p: int, _rz: int) -> _Built:
    return f"{p} min + 6×20 s", _efforts(p)


def _race_pace(p: int, rz: int) -> _Built:
    return f"{p}×8 min", _intervals(p, 480, rz, 180)


def _short_intervals(p: int, _rz: int) -> _Built:
    return f"{p}×1 min", _intervals(p, 60, 5, 60)


def _recovery(p: int, _rz: int) -> _Built:
    return f"{p} min", [_hr("steady", p * 60, 1)]


def _long_ride(p: int, _rz: int) -> _Built:
    gap = _hr("steady", (p - 30) * 60 // 4, 2)  # (p − 30) · 60 is always divisible by 4
    block = _hr("work", 600, 3)
    return f"{p} min (3×10 min Z3)", [gap, block, gap, block, gap, block, gap]


def _sweet_spot(p: int, _rz: int) -> _Built:
    return f"{p}×20 min", _intervals(p, 1200, 3, 300)


def _over_unders(p: int, _rz: int) -> _Built:
    main: list[Step | RepeatStep] = []
    for i in range(p):
        if i:
            main.append(_hr("recovery", 300, 1))
        main.append(_repeat(4, _hr("work", 120, 4), _hr("work", 60, 3)))
    return f"{p}×12 min", _quality(*main)


def _over_unders_fixed(p: int | None, rz: int) -> _Built:
    return _over_unders(3 if p is None else p, rz)


# (param, race_zone) → (name suffix, steps); only over-unders accepts param None (see tests)
_BUILDERS: dict[tuple[str, str], Callable[..., _Built]] = {
    ("run", "easy"): _easy,
    ("run", "long"): _easy,
    ("run", "long_build"): _long_build,
    ("run", "long_peak"): _easy,
    ("run", "tempo"): _tempo,
    ("run", "threshold"): _threshold,
    ("run", "vo2"): _run_vo2,
    ("run", "hills"): _hills,
    ("run", "progression"): _progression,
    ("run", "strides"): _strides,
    ("run", "race_pace"): _race_pace,
    ("run", "race_pace_short"): _race_pace,
    ("run", "short_intervals"): _short_intervals,
    ("run", "recovery"): _recovery,
    ("bike", "recovery_spin"): _recovery,
    ("bike", "endurance"): _easy,
    ("bike", "long_ride"): _long_ride,
    ("bike", "sweet_spot"): _sweet_spot,
    ("bike", "over_unders"): _over_unders_fixed,
    ("bike", "vo2"): _bike_vo2,
    ("bike", "race_pace"): _race_pace,
    ("bike", "race_pace_short"): _race_pace,
    ("bike", "short_intervals"): _short_intervals,
    ("bike", "spin_ups"): _strides,
    ("bike", "recovery"): _recovery,
}


# ---------------------------------------------------------------- public API


def entry(sport: str, key: str) -> LibraryEntry:
    """The §10.7 library entry; KeyError listing the valid keys of the sport otherwise."""
    try:
        return LIBRARY[(sport, key)]
    except KeyError:
        valid = sorted(k for s, k in LIBRARY if s == sport)
        if not valid:
            sports = sorted({s for s, _ in LIBRARY})
            raise KeyError(f"no workout library for sport {sport!r}; sports: {', '.join(sports)}") from None
        raise KeyError(f"unknown {sport} workout {key!r}; valid keys: {', '.join(valid)}") from None


def param_values(sport: str, key: str) -> list[int]:
    """All admissible parameter values in ascending order ([] when the workout has no parameter)."""
    e = entry(sport, key)
    if e.param_min is None or e.param_max is None or e.param_step is None:
        return []
    return list(range(e.param_min, e.param_max + 1, e.param_step))


def build(sport: str, key: str, param: int | None = None, *, race_zone: int = 4) -> Workout:
    """Build the §10.7 workout `key` for `sport` with `param` (None → `param_min`).

    `race_zone` (1–5, see `race_zone()`) is the work zone of the race-pace sessions. Raises ValueError on an
    out-of-range / off-step parameter, a parameter for a workout without one, or an invalid race zone.
    """
    e = entry(sport, key)
    if not 1 <= race_zone <= 5:
        raise ValueError(f"race_zone must be 1–5, got {race_zone}")
    values = param_values(sport, key)
    if not values:
        if param is not None:
            raise ValueError(f"{sport} workout {key!r} takes no parameter, got {param}")
    else:
        if param is None:
            param = values[0]
        if param not in values:
            raise ValueError(
                f"{sport} workout {key!r}: param {param} not in {e.param_min}–{e.param_max} "
                f"(step {e.param_step} {e.param_unit})"
            )
    suffix, steps = _BUILDERS[(sport, key)](param, race_zone)
    return Workout(
        sport=sport,  # type: ignore[arg-type]  # library sports are run/bike
        name=f"{e.name} {suffix}",
        key=key,
        param=param,
        steps=steps,
    )


def fit_param(sport: str, key: str, target_load: float, *, race_zone: int = 4) -> int | None:
    """§10.4 rule 4: the parameter whose `estimated_load` is closest to `target_load` (ties → smaller).

    None for a workout without a parameter.
    """
    best: int | None = None
    best_diff = float("inf")
    for p in param_values(sport, key):  # ascending, so a tie keeps the smaller value
        diff = abs(estimated_load(build(sport, key, p, race_zone=race_zone)) - target_load)
        if diff < best_diff - _TIE_EPS:
            best, best_diff = p, diff
    return best


def race_zone(goal_sport: str | None, distance_m: float | None, target_time_s: float | None) -> int:
    """Work zone of race-pace sessions from the goal (§10.7 clarification).

    run: distance ≤ 5 km → 5, ≤ 21.1 km → 4, longer → 3; bike: `target_time_s` ≤ 2 h → 4, else 3.
    No goal → 4. A goal lacking the deciding value (run without distance, bike without target time) or of
    another sport also falls back to 4.
    """
    if goal_sport == "run" and distance_m is not None:
        if distance_m <= 5000.0:
            return 5
        return 4 if distance_m <= 21100.0 else 3
    if goal_sport == "bike" and target_time_s is not None:
        return 4 if target_time_s <= 7200.0 else 3
    return 4
