"""Weekly template: a role per weekday, per-phase transforms, slot → workout key – METRICS §10.3 (phase 6).

Pure, deterministic functions; no I/O. Workout keys are plain strings naming §10.7 library entries.

# METRICS §10.3 (clarified 2026-09-29, phase 6): a week has a role per weekday: `rest`, `easy`, `long`,
# `q1`, `q2`. Athlete `preferred_days` (`{"mon": "rest" | {"role": "long", "sport": "bike"}, …}`) overrides
# the default `mon rest, tue q1, wed easy, thu q2, fri easy, sat long, sun easy`. Per phase:
# - Base: `q2` → easy. Build: as is. Peak: the easy day right before `long` (else the last easy day) → rest.
#   Taper: `long` → easy.
# - Slot → workout: run – Base `q1` rotates tempo / hill repeats / progression by `k % 3`; Build `q1`
#   threshold intervals, `q2` VO2 intervals (even `k`) or hill repeats (odd `k`); Peak `q1` race-pace, `q2`
#   short intervals; Taper `q1` short race-pace, `q2` strides; `easy` easy run; `long` long run (Peak:
#   shorter range). Bike – `easy` endurance, `long` long ride, Base `q1` sweet spot, Build `q1` over-unders,
#   `q2` bike VO2 intervals, Peak `q1` race-pace, `q2` short intervals, Taper `q1` short race-pace, `q2`
#   spin-ups.
# - Sport: explicit `preferred_days` sport; else `q1`/`q2`/`long` use the goal sport (run without a goal);
#   `easy` uses the sport with the larger remaining weekly target (run on a tie).

Custom layouts (documented behaviour, not spelled out in METRICS):
- Roles are never deduplicated: two `q1` days are both `q1` and get the same workout key for the week.
- Peak turns exactly one easy day into rest: the easy day directly before the first `long` day whose
  predecessor (inside Mon–Sun, no wrap-around) is easy; else the last easy day of the week; with no easy day
  nothing changes. A week without `long` therefore loses its last easy day.
- Taper turns every `long` day into easy; a week without `long` is unchanged.
- An explicit sport survives the transforms (a bike `long` becomes a bike `easy` in the taper); a slot that
  becomes rest loses its sport.
"""

from collections.abc import Mapping
from dataclasses import dataclass, replace

ROLES = ("rest", "easy", "long", "q1", "q2")
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DEFAULT_ROLES = {
    "mon": "rest",
    "tue": "q1",
    "wed": "easy",
    "thu": "q2",
    "fri": "easy",
    "sat": "long",
    "sun": "easy",
}
PHASES = ("base", "build", "peak", "taper")
SPORTS = ("run", "bike")

_BASE_Q1_RUN = ("tempo", "hills", "progression")  # rotated by k % 3
_RUN_LONG = {"base": "long", "build": "long_build", "peak": "long_peak"}
_RUN_Q1 = {"build": "threshold", "peak": "race_pace", "taper": "race_pace_short"}
_RUN_Q2 = {"peak": "short_intervals", "taper": "strides"}
_BIKE_Q1 = {"base": "sweet_spot", "build": "over_unders", "peak": "race_pace", "taper": "race_pace_short"}
_BIKE_Q2 = {"build": "vo2", "peak": "short_intervals", "taper": "spin_ups"}


@dataclass(frozen=True)
class DaySlot:
    """One weekday of the template (METRICS §10.3). `sport` None means "decide later" (`slot_sport`)."""

    weekday: str
    role: str
    sport: str | None


def _parse_value(day: str, value: object) -> DaySlot:
    if isinstance(value, DaySlot):
        if value.weekday != day:
            raise ValueError(f"preferred_days[{day!r}] is a DaySlot for weekday {value.weekday!r}")
        role, sport = value.role, value.sport
    elif isinstance(value, str):
        role, sport = value, None
    elif isinstance(value, Mapping):
        unknown = set(value) - {"role", "sport"}
        if unknown:
            raise ValueError(f"preferred_days[{day!r}] has unknown key(s) {sorted(map(str, unknown))}")
        if "role" not in value:
            raise ValueError(f"preferred_days[{day!r}] needs a 'role' (one of {ROLES})")
        role, sport = value["role"], value.get("sport")
    else:
        raise ValueError(
            f"preferred_days[{day!r}] must be a role string or {{'role': ..., 'sport': ...}}, "
            f"got {type(value).__name__}"
        )
    if role not in ROLES:
        raise ValueError(f"preferred_days[{day!r}]: unknown role {role!r}; expected one of {ROLES}")
    if sport is not None and sport not in SPORTS:
        raise ValueError(f"preferred_days[{day!r}]: unknown sport {sport!r}; expected {SPORTS} or null")
    if role == "rest" and sport is not None:
        raise ValueError(f"preferred_days[{day!r}]: a rest day cannot have a sport ({sport!r})")
    return DaySlot(day, role, sport)


def parse_preferred_days(raw: Mapping | None) -> dict[str, DaySlot]:
    """Athlete `preferred_days` → a `DaySlot` per weekday, Mon–Sun order (METRICS §10.3).

    Values are a role string or `{"role": ..., "sport": "run" | "bike" | None}` (a `DaySlot` is accepted
    too, so parsing is idempotent). Missing days take `DEFAULT_ROLES` with sport None. Unknown weekdays
    (keys must be exactly `WEEKDAYS`), roles, sports or keys raise ValueError.
    """
    if raw is None:
        raw = {}
    if not isinstance(raw, Mapping):
        raise ValueError(f"preferred_days must be a dict keyed by weekday, got {type(raw).__name__}")
    bad = [k for k in raw if k not in WEEKDAYS]
    if bad:
        raise ValueError(f"preferred_days: unknown weekday key(s) {bad!r}; expected {WEEKDAYS}")
    return {day: _parse_value(day, raw.get(day, DEFAULT_ROLES[day])) for day in WEEKDAYS}


def _peak_rest_day(slots: dict[str, DaySlot]) -> str | None:
    """The easy day that Peak turns into rest (see the module docstring), or None."""
    for i, day in enumerate(WEEKDAYS):
        if slots[day].role == "long" and i > 0 and slots[WEEKDAYS[i - 1]].role == "easy":
            return WEEKDAYS[i - 1]
    easy = [day for day in WEEKDAYS if slots[day].role == "easy"]
    return easy[-1] if easy else None


def week_roles(phase: str, preferred_days: Mapping | None) -> dict[str, DaySlot]:
    """The week's slots after the per-phase transform (METRICS §10.3).

    Base: every `q2` → easy. Build: unchanged. Peak: one easy day → rest (`_peak_rest_day`). Taper: every
    `long` → easy. `preferred_days` is the raw athlete dict (or already parsed slots).
    """
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; expected one of {PHASES}")
    slots = parse_preferred_days(preferred_days)
    if phase == "base":
        return {d: replace(s, role="easy") if s.role == "q2" else s for d, s in slots.items()}
    if phase == "taper":
        return {d: replace(s, role="easy") if s.role == "long" else s for d, s in slots.items()}
    if phase == "peak":
        rest_day = _peak_rest_day(slots)
        if rest_day is not None:
            slots[rest_day] = DaySlot(rest_day, "rest", None)
    return slots


def rest_quota(roles: Mapping[str, DaySlot | str]) -> int:
    """Number of rest days in the week's template (used by §10.4 rule 1)."""
    return sum(1 for s in roles.values() if (s.role if isinstance(s, DaySlot) else s) == "rest")


def _run_key(phase: str, role: str, k: int) -> str:
    if role == "easy" or (phase == "taper" and role == "long") or (phase == "base" and role == "q2"):
        return "easy"
    if role == "long":
        return _RUN_LONG[phase]
    if role == "q1":
        return _BASE_Q1_RUN[k % 3] if phase == "base" else _RUN_Q1[phase]
    if phase == "build":  # q2
        return "vo2" if k % 2 == 0 else "hills"
    return _RUN_Q2[phase]


def _bike_key(phase: str, role: str) -> str:
    if role == "easy" or (phase == "taper" and role == "long") or (phase == "base" and role == "q2"):
        return "endurance"
    if role == "long":
        return "long_ride"
    return _BIKE_Q1[phase] if role == "q1" else _BIKE_Q2[phase]


def workout_key(sport: str, phase: str, role: str, cycle_k: int) -> str | None:
    """§10.7 workout key for a slot (METRICS §10.3); None for rest. `cycle_k` = `WeekInfo.cycle_k`.

    Base `q2` and Taper `long` do not occur after `week_roles`; if asked anyway they map like the easy
    slot they are turned into (run "easy", bike "endurance").
    """
    if sport not in SPORTS:
        raise ValueError(f"unknown sport {sport!r}; the workout library has {SPORTS}")
    if phase not in PHASES:
        raise ValueError(f"unknown phase {phase!r}; expected one of {PHASES}")
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    if role == "rest":
        return None
    return _run_key(phase, role, cycle_k) if sport == "run" else _bike_key(phase, role)


def slot_sport(slot: DaySlot, goal_sport: str | None, remaining_run: float, remaining_bike: float) -> str:
    """Sport of a slot (METRICS §10.3 clarified).

    Explicit slot sport wins. Else `q1`/`q2`/`long` use the goal sport (run without a goal, and run for a
    goal sport outside the run/bike library); `easy` uses the sport with the larger remaining weekly target
    (run on a tie). A rest slot returns "rest" (the §10.4 rest output sport).
    """
    if slot.role == "rest":
        return "rest"
    if slot.sport is not None:
        return slot.sport
    if slot.role == "easy":
        return "bike" if remaining_bike > remaining_run else "run"
    return goal_sport if goal_sport in SPORTS else "run"
