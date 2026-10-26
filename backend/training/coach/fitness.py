"""Coach "Kondícia" (fitness mode without a race) – METRICS §11. Pure, deterministic; no I/O.

# METRICS §11 (added 2026-10-26, approved)
- Week menu K (quality), D (longer), Ľ (easy); test weeks 6 and 12 of a block replace K by the check run.
- Colour from readiness P: green ≥ 70, yellow 45–70, red < 45, missing → yellow.
- Rules (first match): 1 red → rest; 2 hard yesterday → Ľ if open else rest; 3 green and K open → K;
  4 D open and (weekend or must) → D; 5 Ľ open and (must or rested yesterday) → Ľ; 6 K open and must →
  mild K; 7 rest. An unavailable day is rest. `must` = available days D…Sunday ≤ open items.
- Weekly time T: base grows ×1.07 a week, ×1.00 on a brake (mean readiness < 55, sleep debt > 5 h, ACWR
  > 1.3), ×0.85 if mean readiness < 45; recovery weeks 4/8/12: T = 0.7 · base. Split D 40 % / K 30 % /
  Ľ 30 %, 5-min rounding, clamps Ľ 25–60, K 35–60, D 45–100 (weekday D ≤ 60).
- K rotates threshold / VO2 / tempo / hills by `(week − 1) mod 4`; mild K = tempo Z3 15–20 min; check run
  = 15 min Z2 + 30 min open effort 4 + 10 min Z1.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

from training.coach.rules import Decision
from training.coach.workout import HrZoneTarget, OpenTarget, RepeatStep, Step, Workout, rest_workout

GREEN, YELLOW, RED = "green", "yellow", "red"
P_GREEN = 70.0
P_RED = 45.0
COLOR_SK = {GREEN: "zelená", YELLOW: "žltá", RED: "červená"}

SLOTS = ("k", "d", "e")  # quality, longer, easy (planned_workout.structure["slot"])
SLOT_SK = {"k": "kvalitný", "d": "dlhší", "e": "ľahký"}
SLOT_SHORT = {"k": "K", "d": "D", "e": "Ľ"}

BASE_MIN_S = 5400.0  # §11.3: at least 90 min a week
GROWTH = 1.07
CUT = 0.85
RECOVERY_SHARE = 0.70
BRAKE_READINESS = 55.0
CUT_READINESS = 45.0
BRAKE_SLEEP_DEBT_S = 5 * 3600.0
BRAKE_ACWR = 1.3
BLOCK_WEEKS = 12
RECOVERY_WEEKS = (4, 8, 12)
TEST_WEEKS = (6, 12)
SHARE = {"d": 0.40, "k": 0.30, "e": 0.30}
LIMITS_MIN = {"e": (25, 60), "k": (35, 60), "d": (45, 100)}
WEEKDAY_D_MAX_MIN = 60
HARD_RIDE_S = 5400  # §11.2: a ride of ≥ 90 min moving is a hard day
QUALITY_IF = 0.85
NOON_HOUR = 12  # §11.2: wait for last night's sleep until 12:00
RIDE_MIN = 75  # a user-requested ride (regenerate for "bike")


def color(readiness: float | None) -> str:
    """§11.2 day colour; a missing or NaN readiness counts as yellow."""
    if readiness is None or math.isnan(readiness):
        return YELLOW
    if readiness >= P_GREEN:
        return GREEN
    return YELLOW if readiness >= P_RED else RED


# ---------------------------------------------------------------- §11.3 weekly time


@dataclass(frozen=True)
class WeekLoad:
    """One week's §11.3 numbers: `base_s` carries the progression, `target_s` is what the week plans."""

    week_no: int
    base_s: float
    target_s: float
    brake: str | None  # None | "hold" | "cut"
    recovery: bool
    test: bool


def first_base(weekly_run_s: list[float]) -> float:
    """Block start: max(90 min, median of the 4 previous weeks' run time)."""
    values = sorted(weekly_run_s)
    if not values:
        return BASE_MIN_S
    mid = len(values) // 2
    median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2.0
    return max(BASE_MIN_S, median)


def brake(mean_readiness: float | None, sleep_debt_s: float | None, acwr: float | None) -> str | None:
    """ "cut" (×0.85), "hold" (×1.00) or None (×1.07) from the 7 days before the week.

    Missing inputs never brake."""
    if mean_readiness is not None and mean_readiness < CUT_READINESS:
        return "cut"
    if (
        (mean_readiness is not None and mean_readiness < BRAKE_READINESS)
        or (sleep_debt_s is not None and sleep_debt_s > BRAKE_SLEEP_DEBT_S)
        or (acwr is not None and acwr > BRAKE_ACWR)
    ):
        return "hold"
    return None


def week_load(
    week_no: int, previous_base_s: float | None, brake_reason: str | None, start_base_s: float
) -> WeekLoad:
    """§11.3: week 1 uses `start_base_s`; later weeks grow from the previous week's base.

    Growth ×1.07, ×1.00 on "hold", ×0.85 on "cut"."""
    if week_no == 1 or previous_base_s is None:
        base, applied = start_base_s, None
    else:
        factor = {None: GROWTH, "hold": 1.0, "cut": CUT}[brake_reason]
        base, applied = previous_base_s * factor, brake_reason
    recovery = week_no in RECOVERY_WEEKS
    target = base * RECOVERY_SHARE if recovery else base
    return WeekLoad(week_no, base, target, applied, recovery, week_no in TEST_WEEKS)


def session_minutes(target_s: float, slot: str, weekend: bool) -> int:
    """§11.3 length of one session in whole 5-minute steps (halves up), clamped."""
    minutes = target_s / 60.0 * SHARE[slot]
    rounded = 5 * math.floor(minutes / 5.0 + 0.5 + 1e-9)  # 1e-9: a float tie such as 42.4999… counts as .5
    low, high = LIMITS_MIN[slot]
    if slot == "d" and not weekend:
        high = WEEKDAY_D_MAX_MIN
    return max(low, min(high, rounded))


# ---------------------------------------------------------------- workouts


def _hr(kind: str, seconds: int, zone: int) -> Step:
    return Step(type=kind, duration_s=seconds, target=HrZoneTarget(zone=zone))  # type: ignore[arg-type]


def _open(kind: str, seconds: int, effort: int) -> Step:
    return Step(type=kind, duration_s=seconds, target=OpenTarget(effort_zone=effort))  # type: ignore[arg-type]


def _repeat(count: int, *steps: Step) -> RepeatStep:
    return RepeatStep(type="repeat", count=count, steps=list(steps))


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def easy_run(minutes: int) -> Workout:
    return Workout(
        sport="run",
        name=f"Ľahký beh {minutes} min",
        key="fit_easy",
        slot="e",
        param=minutes,
        steps=[_hr("steady", minutes * 60, 2)],
    )


def long_run(minutes: int) -> Workout:
    return Workout(
        sport="run",
        name=f"Dlhší beh {minutes} min",
        key="fit_long",
        slot="d",
        param=minutes,
        steps=[_hr("steady", minutes * 60, 2)],
    )


QUALITY_KINDS = ("threshold", "vo2", "tempo", "hills")


def quality_kind(week_no: int) -> str:
    """§11.3 rotation by block week."""
    return QUALITY_KINDS[(week_no - 1) % 4]


def quality_run(minutes: int, week_no: int) -> Workout:
    """§11.3 K: warm-up 15 (10 if K < 45) min Z2, main set from the rest, cool-down 10 min Z1."""
    warm = 15 if minutes >= 45 else 10
    main_min = minutes - warm - 10
    kind = quality_kind(week_no)
    if kind == "threshold":
        n = _clamp(main_min // 8, 3, 5)
        main: list[Step | RepeatStep] = [_repeat(n, _hr("work", 360, 4), _hr("recovery", 120, 1))]
        name = f"Prahové intervaly {n}×6 min"
    elif kind == "vo2":
        n = _clamp(main_min // 6, 5, 6)
        main = [_repeat(n, _hr("work", 180, 5), _hr("recovery", 180, 1))]
        name = f"VO2 intervaly {n}×3 min"
    elif kind == "tempo":
        tempo = _clamp(main_min - main_min % 5, 15, 25)
        main = [_hr("work", tempo * 60, 4)]
        name = f"Tempo {tempo} min"
    else:
        n = _clamp(int(main_min / 2.5), 6, 10)
        main = [_repeat(n, _open("work", 60, 5), _hr("recovery", 90, 1))]
        name = f"Kopce {n}×60 s"
    steps = [_hr("warmup", warm * 60, 2), *main, _hr("cooldown", 600, 1)]
    return Workout(sport="run", name=name, key=f"fit_{kind}", slot="k", param=minutes, steps=steps)


def mild_quality_run(minutes: int) -> Workout:
    """§11.3 mild K: tempo Z3 of 15–20 min between the K warm-up and cool-down."""
    warm = 15 if minutes >= 45 else 10
    main_min = minutes - warm - 10
    tempo = _clamp(main_min - main_min % 5, 15, 20)
    steps = [_hr("warmup", warm * 60, 2), _hr("work", tempo * 60, 3), _hr("cooldown", 600, 1)]
    return Workout(
        sport="run",
        name=f"Mierne tempo {tempo} min",
        key="fit_tempo_mild",
        slot="k",
        param=minutes,
        steps=steps,
    )


def check_run() -> Workout:
    """§11.3 check run: 15 min Z2, 30 min all-out without stopping (open effort 4), 10 min Z1."""
    steps = [_hr("warmup", 900, 2), _open("work", 1800, 4), _hr("cooldown", 600, 1)]
    return Workout(
        sport="run",
        name="Kontrolný beh – 30 min naplno, bez zastavenia, vypni auto-pauzu",
        key="fit_check",
        slot="k",
        param=30,
        steps=steps,
    )


def easy_ride() -> Workout:
    return Workout(
        sport="bike",
        name=f"Vytrvalostná jazda {RIDE_MIN} min",
        key="fit_ride",
        param=RIDE_MIN,
        steps=[_hr("steady", RIDE_MIN * 60, 2)],
    )


# ---------------------------------------------------------------- §11.2 daily decision


@dataclass(frozen=True)
class FitnessContext:
    """Inputs of §11.2 for day `day` (assembled by `planning_fitness`)."""

    day: date
    readiness: float | None
    available: frozenset[date]  # available days of this ISO week
    open_items: frozenset[str]  # subset of SLOTS still to do this week
    hard_yesterday: str | None  # Slovak description of yesterday's hard session, None if none
    ran_yesterday: bool
    week: WeekLoad
    sport_override: str | None = None


def _week_days(day: date) -> list[date]:
    monday = day - timedelta(days=day.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def must_train(ctx: FitnessContext) -> bool:
    left = [d for d in _week_days(ctx.day) if d >= ctx.day and d in ctx.available]
    return bool(ctx.open_items) and len(left) <= len(ctx.open_items)


def _menu(ctx: FitnessContext) -> str:
    return " ".join(f"{SLOT_SHORT[s]}{' –' if s in ctx.open_items else ' ✓'}" for s in SLOTS)


def _p(ctx: FitnessContext) -> str:
    if ctx.readiness is None or math.isnan(ctx.readiness):
        return "pripravenosť chýba"
    return f"pripravenosť {math.floor(ctx.readiness)} ({COLOR_SK[color(ctx.readiness)]})"


def _decision(ctx: FitnessContext, workout: Workout, rule: int, why: str) -> Decision:
    test = " Testovací týždeň." if ctx.week.test and workout.key == "fit_check" else ""
    reason = f"{why}{test} Týždeň {ctx.week.week_no}/{BLOCK_WEEKS}: {_menu(ctx)}."
    return Decision(
        workout, reason, rule, workout.slot or ("rest" if workout.sport == "rest" else "ride"), None
    )


def decide(ctx: FitnessContext) -> Decision:
    """METRICS §11.2 – the first matching rule decides; reasons are Slovak templates."""
    if ctx.sport_override == "bike":
        return _decision(ctx, easy_ride(), 0, "Na želanie jazda na bicykli v zóne 2.")
    weekend = ctx.day.weekday() >= 5
    minutes = {s: session_minutes(ctx.week.target_s, s, weekend) for s in SLOTS}
    col = color(ctx.readiness)
    must = must_train(ctx)
    open_ = ctx.open_items
    if ctx.day not in ctx.available:
        return _decision(ctx, rest_workout(), 0, "Dnes nie je tréningový deň (nastavenie preferovaných dní).")
    if col == RED:
        return _decision(ctx, rest_workout(), 1, f"Dnes voľno – {_p(ctx)}, spánok má prednosť.")
    if ctx.hard_yesterday:
        if "e" in open_:
            return _decision(
                ctx, easy_run(minutes["e"]), 2, f"Včera {ctx.hard_yesterday} – dnes ľahký beh ({_p(ctx)})."
            )
        return _decision(ctx, rest_workout(), 2, f"Včera {ctx.hard_yesterday} – dnes voľno.")
    if col == GREEN and "k" in open_:
        workout = check_run() if ctx.week.test else quality_run(minutes["k"], ctx.week.week_no)
        return _decision(ctx, workout, 3, f"Zelený deň ({_p(ctx)}) – kvalitný tréning.")
    if "d" in open_ and (weekend or must):
        why = "víkend" if weekend else "do nedele už treba odbehnúť zvyšné behy"
        return _decision(ctx, long_run(minutes["d"]), 4, f"Dlhší beh – {why} ({_p(ctx)}).")
    if "e" in open_ and (must or not ctx.ran_yesterday):
        why = "do nedele už treba odbehnúť zvyšné behy" if must else "včera bez behu"
        return _decision(ctx, easy_run(minutes["e"]), 5, f"Ľahký beh – {why} ({_p(ctx)}).")
    if "k" in open_ and must:
        return _decision(
            ctx,
            mild_quality_run(minutes["k"]),
            6,
            f"Tento týždeň ešte nebol zelený deň – miernejší kvalitný tréning ({_p(ctx)}).",
        )
    if not open_:
        why = "tento týždeň je hotový"
    elif ctx.ran_yesterday:
        why = "včera si behal, behy sa rozložia"
    else:
        why = "čaká sa na lepší deň"
    return _decision(ctx, rest_workout(), 7, f"Dnes voľno – {why} ({_p(ctx)}).")
