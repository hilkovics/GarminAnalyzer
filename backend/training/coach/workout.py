"""Workout structure schema and estimated load – METRICS §10.5–10.6 (phase 6).

# METRICS §10.5
A workout is sport-agnostic JSON: `{"sport", "name", "steps": [...]}`; a step is
`{"type", "duration_s", "target"}` or `{"type": "repeat", "count", "steps": [...]}`.
Targets: `hr_zone` (1–5), `pace_range` (run, from §1 pace zones), `open`. Bike uses `hr_zone` only.

# METRICS §10.6
`estimated_load = Σ_steps duration_s · IF_zone² / 36`, IF_zone: Z1 0.50, Z2 0.65, Z3 0.83, Z4 0.98, Z5 1.10.
Clarified 2026-09-29 (phase 6): repeats multiply their inner steps; `open` steps carry an `effort_zone`
(1–5) used only for the load; `pace_range` steps carry their pace zone and use the same zone IF.

Extensions of the §10.5 JSON (all optional when parsing): `key` (the §10.7 library key, "" when unknown),
`slot` (the §10.3 weekday role), `param` (the §10.4 rule 4 integer parameter). Repeats do not nest.
`sport = "rest"` is a rest day: no steps, load 0 (§10.4 clarification). Pure functions, no I/O.
"""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, model_validator

# METRICS §10.6 – zone IF (Z1 0.50 kept as written, see the 2026-09-29 clarification).
ZONE_IF: dict[int, float] = {1: 0.50, 2: 0.65, 3: 0.83, 4: 0.98, 5: 1.10}

ZoneNumber = Annotated[int, Field(ge=1, le=5)]


class HrZoneTarget(BaseModel):
    """Heart-rate zone target (§1 HR zones)."""

    kind: Literal["hr_zone"] = "hr_zone"
    zone: ZoneNumber


class PaceRangeTarget(BaseModel):
    """Run pace-zone target (§1 pace zones); optional speed bounds in m/s filled from the threshold."""

    kind: Literal["pace_range"] = "pace_range"
    zone: ZoneNumber
    low_mps: Annotated[float, Field(gt=0)] | None = None
    high_mps: Annotated[float, Field(gt=0)] | None = None


class OpenTarget(BaseModel):
    """No device target; `effort_zone` is the intended intensity, used only for §10.6."""

    kind: Literal["open"] = "open"
    effort_zone: ZoneNumber


Target = Annotated[HrZoneTarget | PaceRangeTarget | OpenTarget, Field(discriminator="kind")]


class Step(BaseModel):
    """A single timed step (§10.5)."""

    type: Literal["warmup", "work", "recovery", "cooldown", "steady"]
    duration_s: Annotated[int, Field(gt=0)]
    target: Target


class RepeatStep(BaseModel):
    """`count` × the inner steps (§10.5); inner steps are plain steps (no nested repeats)."""

    type: Literal["repeat"] = "repeat"
    count: Annotated[int, Field(ge=1)]
    steps: Annotated[list[Step], Field(min_length=1)]


AnyStep = Annotated[Step | RepeatStep, Field(discriminator="type")]


class Workout(BaseModel):
    """A planned workout (§10.5) plus the optional library `key`, weekday `slot` and `param`."""

    sport: Literal["run", "bike", "rest"]
    name: str
    key: str = ""
    slot: str | None = None
    param: int | None = None
    steps: list[AnyStep] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_sport_rules(self) -> "Workout":
        if self.sport == "rest":
            if self.steps:
                raise ValueError("a rest workout has no steps")
            return self
        if not self.steps:
            raise ValueError(f"a {self.sport} workout needs at least one step")
        if self.sport == "bike" and any(isinstance(s.target, PaceRangeTarget) for s in _leaf_steps(self)):
            raise ValueError("bike workouts use hr_zone (or open) targets only, not pace_range")
        return self


def _leaf_steps(workout: Workout) -> list[Step]:
    """The distinct plain steps (repeat bodies listed once, not multiplied)."""
    out: list[Step] = []
    for s in workout.steps:
        out.extend(s.steps if isinstance(s, RepeatStep) else [s])
    return out


def _weighted_steps(workout: Workout) -> list[tuple[Step, int]]:
    """Plain steps with their multiplicity (repeat count, 1 for top-level steps)."""
    out: list[tuple[Step, int]] = []
    for s in workout.steps:
        if isinstance(s, RepeatStep):
            out.extend((inner, s.count) for inner in s.steps)
        else:
            out.append((s, 1))
    return out


def step_zone(step: Step) -> int:
    """Zone of a plain step for §10.6: hr_zone/pace_range → `zone`, open → `effort_zone`."""
    target = step.target
    if isinstance(target, OpenTarget):
        return target.effort_zone
    return target.zone


def estimated_load(workout: Workout) -> float:
    """METRICS §10.6: `Σ duration_s · IF_zone² / 36` over all steps, repeats multiplied; rest → 0."""
    return sum(n * s.duration_s * ZONE_IF[step_zone(s)] ** 2 for s, n in _weighted_steps(workout)) / 36.0


def total_duration_s(workout: Workout) -> int:
    """Total planned duration in seconds, repeats multiplied; rest → 0."""
    return sum(n * s.duration_s for s, n in _weighted_steps(workout))


def to_structure(workout: Workout) -> dict[str, Any]:
    """The §10.5 JSON (JSON-mode dump, None values excluded; an empty `key` is omitted too)."""
    d = workout.model_dump(mode="json", exclude_none=True)
    if not d.get("key"):
        d.pop("key", None)
    return d


def from_structure(d: dict[str, Any]) -> Workout:
    """Parse §10.5 JSON (extra keys `key`/`slot`/`param` optional); raises pydantic.ValidationError."""
    return Workout.model_validate(d)


def rest_workout(reason_name: str = "Voľno") -> Workout:
    """A rest day as a planned workout: sport "rest", key "rest", no steps (§10.4 clarification)."""
    return Workout(sport="rest", name=reason_name, key="rest", steps=[])
