"""Daily decision rules – METRICS §10.4 (phase 6). Pure, deterministic; no I/O, no LLM.

# METRICS §10.4
1. If `readiness < 45` **or** `ACWR > 1.5` **or** `TSB < −30` → **rest or 30–40 min Z1**.
2. Else if `monotony > 2.0` → prefer a session type not done in the last 7 days.
3. Else pick the next unfulfilled template slot for today's preferred sport; if a quality session was done
   yesterday, pick easy/long instead.
4. Scale duration so that `estimated_load` (§10.6) fills the remaining `weekly_target_load` across remaining
   sessions.
5. Output: structured workout (§10.5) + one-line reason string (deterministic, template-based).
Clarified 2026-09-29 (phase 6, proposed) – binding:
- Inputs for day `D`: `readiness[D]`, `TSB[D]`, `ACWR[D−1]`, `monotony[D−1]`. A null input never triggers
  its condition (the reason says the value is missing).
- Rule 1: **rest** if the week's rest quota is not yet used (days `Mon … D−1` without any activity < the
  template's rest days), else **40 min Z1** (recovery, today's sport).
- Rule 2: "session type" = the §10.7 workout key. If today's workout key was done in `D−7 … D−1`, take the
  first key of this week's remaining non-rest slots (order long, q1, q2, easy) that was not; if none, keep
  today's.
- Rule 3: today's role gives the slot (rest → rest). If today is `easy` and an earlier `q1`/`q2`/`long` slot
  of this week is unfulfilled, take the earliest of them. A quality (`q1`/`q2`) choice becomes `easy` if
  yesterday had a done quality workout or an activity with IF ≥ 0.85.
- Rule 4: `remaining = weekly_target − Σ load_total[Mon … D−1]` (≥ 0); weights long 2.0, q1/q2 1.25,
  easy 1.0 over today's and the remaining non-rest days of the week; today's target =
  `remaining · w_today / Σ w`; the parameter whose `estimated_load` is closest wins (ties → the smaller).
- Rest output = `sport = "rest"`, no steps, `estimated_load = 0`. Reasons are Slovak fixed templates.

Implementation decisions (not spelled out in METRICS):
- Precedence: rule 1, then a template rest day → rest (rule 3), then rule 2 if `monotony > 2.0` (it picks
  the key starting from today's template role; rule 3's make-up / downgrade logic does not run), else rule 3.
  Rule 4 scales whatever rule 2 or 3 chose.
- Rule 1 on a template rest day always gives rest, even when the quota is used (a planned rest day never
  turns into a recovery session).
- Rule 1 recovery sport: `sport_override`, else today's slot sport, else the goal sport, else run.
- `sport_override` replaces the sport of every non-rest slot (today's and, for rule 2, the other days').
- A "session type" is the pair (sport, key): a bike tempo does not block a run tempo (library keys are
  namespaced by sport).
- Rule 3 "fulfilled" counts: the n-th earlier `q1` day is fulfilled when ≥ n done sessions of slot `q1` lie in
  `Mon … D−1`. A moved slot keeps its own day's sport (explicit, else goal sport); a downgraded slot is
  today's day as `easy` (explicit sport kept, else the larger remaining target).
- "Done quality yesterday" = a DoneSession on `D−1` with slot `q1`/`q2`.
- `workout.slot` is the template role filled (`easy`/`long`/`q1`/`q2`); None for rest and rule-1 recovery,
  so a done recovery never fulfils a slot. `Decision.slot` additionally uses "rest" / "recovery".
- NaN inputs count as missing. Numbers in reasons: readiness/TSB/IF/ACWR/monotony up to 1–2 decimals with
  trailing zeros stripped, loads and percentages rounded to integers.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import NamedTuple

from training.coach import library
from training.coach.season import WeekInfo, monday
from training.coach.template import SPORTS, WEEKDAYS, DaySlot, rest_quota, slot_sport, workout_key
from training.coach.workout import Workout, estimated_load, rest_workout, total_duration_s

READINESS_RED = 45
ACWR_DANGER = 1.5
TSB_FLOOR = -30
MONOTONY_HIGH = 2.0
QUALITY_IF = 0.85
SLOT_WEIGHTS = {"long": 2.0, "q1": 1.25, "q2": 1.25, "easy": 1.0}
RULE2_ORDER = ("long", "q1", "q2", "easy")

QUALITY_SLOTS = ("q1", "q2")
RECOVERY_KEY = "recovery"

_ROLE_SK = {"long": "dlhý tréning", "q1": "kvalitný tréning 1", "q2": "kvalitný tréning 2", "easy": "ľahký"}
_DAY_SK = dict(zip(WEEKDAYS, ("po", "ut", "st", "št", "pi", "so", "ne"), strict=True))


@dataclass(frozen=True)
class DoneSession:
    """A planned workout with status "done" (§10.4 "sessions already completed")."""

    date: date
    sport: str
    key: str  # §10.7 workout key
    slot: str | None  # role it filled: "easy" | "long" | "q1" | "q2" | None (e.g. rule-1 recovery)


@dataclass(frozen=True)
class DayContext:
    """All §10.4 inputs for day `day` (assembled by the DB glue; see the clarification for the days used)."""

    day: date
    info: WeekInfo
    roles: Mapping[str, DaySlot]
    weekly_target: float
    run_target: float
    bike_target: float
    load_done_week: float
    run_load_done_week: float
    bike_load_done_week: float
    active_days_week: frozenset[date]
    done: tuple[DoneSession, ...]
    yesterday_max_if: float | None
    readiness: float | None
    tsb: float | None
    acwr_prev: float | None
    monotony_prev: float | None
    goal_sport: str | None
    race_zone: int
    sport_override: str | None = None


@dataclass(frozen=True)
class Decision:
    """The day's workout, a one-line Slovak reason, the deciding rule, the slot used and the rule-4 target."""

    workout: Workout
    reason: str
    rule: int
    slot: str
    target_load: float | None


class _Choice(NamedTuple):
    role: str
    sport: str
    key: str
    head: str  # reason prefix ("" for a plain rule-3 pick)


# ---------------------------------------------------------------- formatting


def _num(value: float | None) -> float | None:
    """None for a missing or NaN input."""
    return None if value is None or math.isnan(value) else float(value)


def _fmt(x: float, decimals: int) -> str:
    """Fixed decimals with trailing zeros stripped: 38.0 → "38", 1.60 → "1.6", -32.4 → "-32.4"."""
    s = f"{x:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def _missing_note(ctx: DayContext) -> str:
    names = [
        name
        for name, value in (
            ("pripravenosť", ctx.readiness),
            ("ACWR", ctx.acwr_prev),
            ("TSB", ctx.tsb),
            ("monotónnosť", ctx.monotony_prev),
        )
        if _num(value) is None
    ]
    return f" Chýba: {', '.join(names)}." if names else ""


def _phase_label(info: WeekInfo) -> str:
    label = info.phase.capitalize()
    return f"{label} (regeneračný týždeň)" if info.recovery else label


def _name(sport: str, key: str) -> str:
    return library.entry(sport, key).name


# ---------------------------------------------------------------- week helpers


def _week(ctx: DayContext) -> list[tuple[date, DaySlot]]:
    mon = monday(ctx.day)
    return [(mon + timedelta(days=i), ctx.roles[wd]) for i, wd in enumerate(WEEKDAYS)]


def _today_slot(ctx: DayContext) -> DaySlot:
    return ctx.roles[WEEKDAYS[ctx.day.weekday()]]


def _sport_for(ctx: DayContext, slot: DaySlot) -> str:
    """§10.3 slot sport with the week's remaining run/bike targets; `sport_override` wins (not for rest)."""
    if slot.role == "rest":
        return "rest"
    if ctx.sport_override is not None:
        return ctx.sport_override
    remaining_run = max(0.0, ctx.run_target - ctx.run_load_done_week)
    remaining_bike = max(0.0, ctx.bike_target - ctx.bike_load_done_week)
    return slot_sport(slot, ctx.goal_sport, remaining_run, remaining_bike)


def _key(ctx: DayContext, sport: str, role: str) -> str:
    key = workout_key(sport, ctx.info.phase, role, ctx.info.cycle_k)
    assert key is not None  # role is never rest here
    return key


def _rest(ctx: DayContext, rule: int, reason: str) -> Decision:
    return Decision(rest_workout(), reason + _missing_note(ctx), rule, "rest", None)


# ---------------------------------------------------------------- rule 1


def _rule1_triggers(ctx: DayContext) -> list[str]:
    readiness, acwr, tsb = _num(ctx.readiness), _num(ctx.acwr_prev), _num(ctx.tsb)
    out = []
    if readiness is not None and readiness < READINESS_RED:
        out.append(f"Pripravenosť {_fmt(readiness, 1)} < {READINESS_RED}")
    if acwr is not None and acwr > ACWR_DANGER:
        out.append(f"ACWR {_fmt(acwr, 2)} > {_fmt(ACWR_DANGER, 2)}")
    if tsb is not None and tsb < TSB_FLOOR:
        out.append(f"TSB {_fmt(tsb, 1)} < {TSB_FLOOR}")
    return out


def _rule1(ctx: DayContext, today: DaySlot, triggers: list[str]) -> Decision:
    head = ", ".join(triggers)
    if today.role == "rest":
        return _rest(ctx, 1, f"{head} → voľno (podľa plánu deň voľna).")
    mon = monday(ctx.day)
    rested = sum(
        1 for i in range((ctx.day - mon).days) if mon + timedelta(days=i) not in ctx.active_days_week
    )
    if rested < rest_quota(ctx.roles):
        return _rest(ctx, 1, f"{head} → voľno (týždenná kvóta voľna ešte nevyčerpaná).")
    sport = _sport_for(ctx, today)
    if sport not in SPORTS:  # defensive: today's slot gave no library sport
        sport = ctx.goal_sport if ctx.goal_sport in SPORTS else "run"
    workout = library.build(sport, RECOVERY_KEY, race_zone=ctx.race_zone)
    minutes = total_duration_s(workout) // 60
    reason = f"{head} → regenerácia {minutes} min Z1 (týždenná kvóta voľna vyčerpaná)."
    return Decision(workout, reason + _missing_note(ctx), 1, "recovery", None)


# ---------------------------------------------------------------- rule 2


def _rule2(ctx: DayContext, today: DaySlot, monotony: float) -> _Choice:
    sport = _sport_for(ctx, today)
    key = _key(ctx, sport, today.role)
    recent = {(s.sport, s.key) for s in ctx.done if ctx.day - timedelta(days=7) <= s.date < ctx.day}
    head = f"Monotónnosť {_fmt(monotony, 2)} > {MONOTONY_HIGH:.1f}"
    name = _name(sport, key)
    if (sport, key) not in recent:
        kept = f"{head}, tréning {name} v posledných 7 dňoch nebol → bez zmeny."
        return _Choice(today.role, sport, key, kept)
    remaining = [slot for d, slot in _week(ctx) if d >= ctx.day and slot.role != "rest"]
    for role in RULE2_ORDER:
        for slot in (s for s in remaining if s.role == role):
            alt_sport = _sport_for(ctx, slot)
            alt_key = _key(ctx, alt_sport, role)
            if (alt_sport, alt_key) not in recent:
                alt = _name(alt_sport, alt_key)
                why = f"(tréning {name} bol v posledných 7 dňoch)"
                return _Choice(role, alt_sport, alt_key, f"{head} → {alt} namiesto {name} {why}.")
    return _Choice(
        today.role, sport, key, f"{head}, všetky typy tréningov týždňa boli v posledných 7 dňoch → {name}."
    )


# ---------------------------------------------------------------- rule 3


def _earliest_missed(ctx: DayContext) -> tuple[date, DaySlot] | None:
    """The earliest `q1`/`q2`/`long` day of `Mon … D−1` not matched by a done session of that slot."""
    mon = monday(ctx.day)
    credit: dict[str, int] = {}
    for s in ctx.done:
        if mon <= s.date < ctx.day and s.slot is not None:
            credit[s.slot] = credit.get(s.slot, 0) + 1
    for d, slot in _week(ctx):
        if d >= ctx.day or slot.role not in ("q1", "q2", "long"):
            continue
        if credit.get(slot.role, 0) > 0:
            credit[slot.role] -= 1
        else:
            return d, slot
    return None


def _yesterday_quality(ctx: DayContext) -> str | None:
    """Reason head when yesterday was a quality day (done q1/q2 or IF ≥ 0.85), else None."""
    yesterday = ctx.day - timedelta(days=1)
    max_if = _num(ctx.yesterday_max_if)
    if max_if is not None and max_if >= QUALITY_IF:
        return f"Včera kvalitný tréning (IF {_fmt(max_if, 2)} ≥ {_fmt(QUALITY_IF, 2)}) → ľahký deň."
    if any(s.date == yesterday and s.slot in QUALITY_SLOTS for s in ctx.done):
        return "Včera kvalitný tréning → ľahký deň."
    return None


def _rule3(ctx: DayContext, today: DaySlot) -> _Choice:
    source, head = today, ""
    if today.role == "easy":
        missed = _earliest_missed(ctx)
        if missed is not None:
            missed_day, source = missed
            head = f"Vynechaný {_ROLE_SK[source.role]} ({_DAY_SK[WEEKDAYS[missed_day.weekday()]]}) → dnes."
    if source.role in QUALITY_SLOTS:
        downgrade = _yesterday_quality(ctx)
        if downgrade is not None:
            source = replace(today, role="easy")
            head = downgrade
    sport = _sport_for(ctx, source)
    return _Choice(source.role, sport, _key(ctx, sport, source.role), head)


# ---------------------------------------------------------------- rule 4


def _day_target(ctx: DayContext, role: str) -> float:
    """`remaining · w_today / Σ w` over today's final slot and the non-rest days after `D`."""
    remaining = max(0.0, ctx.weekly_target - ctx.load_done_week)
    w_today = SLOT_WEIGHTS[role]
    w_total = w_today + sum(SLOT_WEIGHTS[s.role] for d, s in _week(ctx) if d > ctx.day and s.role != "rest")
    return remaining * w_today / w_total


def _scaled(ctx: DayContext, choice: _Choice, rule: int) -> Decision:
    target = _day_target(ctx, choice.role)
    param = library.fit_param(choice.sport, choice.key, target, race_zone=ctx.race_zone)
    workout = library.build(choice.sport, choice.key, param, race_zone=ctx.race_zone)
    workout = workout.model_copy(update={"slot": choice.role})
    pct = round(100.0 * ctx.load_done_week / ctx.weekly_target) if ctx.weekly_target > 0 else 100
    body = (
        f"{_phase_label(ctx.info)}, týždeň {pct} % splnený: {workout.name}, "
        f"odhad {estimated_load(workout):.0f} bodov (cieľ dňa {target:.0f})."
    )
    reason = f"{choice.head} {body}" if choice.head else body
    return Decision(workout, reason + _missing_note(ctx), rule, choice.role, target)


# ---------------------------------------------------------------- entry point


def decide(ctx: DayContext) -> Decision:
    """METRICS §10.4: the day's decision (rule 1 → template rest → rule 2 → rule 3, then rule 4 scaling)."""
    if ctx.sport_override is not None and ctx.sport_override not in SPORTS:
        raise ValueError(f"sport_override must be one of {SPORTS} or None, got {ctx.sport_override!r}")
    today = _today_slot(ctx)
    triggers = _rule1_triggers(ctx)
    if triggers:
        return _rule1(ctx, today, triggers)
    if today.role == "rest":
        return _rest(ctx, 3, f"{_phase_label(ctx.info)}: podľa plánu deň voľna.")
    monotony = _num(ctx.monotony_prev)
    if monotony is not None and monotony > MONOTONY_HIGH:
        return _scaled(ctx, _rule2(ctx, today, monotony), 2)
    return _scaled(ctx, _rule3(ctx, today), 3)
