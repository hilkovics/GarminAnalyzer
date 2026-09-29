"""Phase-6 DTOs (goal, season, week plan, planned workouts, daily decision – METRICS §10); re-exported by
`services.dto`. Internal units only (seconds, TSS-equivalent points); h:mm and "min Z4" are presentation."""

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

# --- goal ---------------------------------------------------------------------------------------------------


class GoalIn(BaseModel):
    """PUT /plan/goal body: the race the season is built towards. Replaces the active goal."""

    race_date: dt.date = Field(description="not in the past")
    distance_m: float | None = Field(default=None, gt=0, description="metres, e.g. 10000")
    target_time_s: float | None = Field(default=None, gt=0, description="seconds")
    sport: str = Field(default="run", description='"run" | "bike"')
    active: bool = Field(default=True, description="false stores the goal without using it (all others off)")


class GoalDTO(BaseModel):
    id: int
    race_date: dt.date
    distance_m: float | None = Field(description="metres")
    target_time_s: float | None = Field(description="seconds")
    sport: str = Field(description='"run" | "bike"')
    active: bool


# --- season -------------------------------------------------------------------------------------------------


class SeasonWeekDTO(BaseModel):
    """One ISO week of the season plan (METRICS §10.1–§10.2). Loads are TSS-equivalent points."""

    monday: dt.date
    phase: str = Field(description='"base" | "build" | "peak" | "taper"')
    recovery: bool
    days_to_race: int | None = Field(description="days from this Monday to the race; null without a goal")
    ctl_start: float = Field(description="CTL of the day before the Monday (projected for future weeks)")
    target_load: float
    run_target: float
    bike_target: float
    is_current: bool = Field(description="the week containing today")
    is_race_week: bool = Field(description="the week containing the goal's race date")


class SeasonDTO(BaseModel):
    """GET /plan/season – this week and the projected weeks after it (up to the race week + 1)."""

    today: dt.date
    goal: GoalDTO | None
    current_phase: str
    weeks: list[SeasonWeekDTO]


# --- planned workouts ---------------------------------------------------------------------------------------


class WorkoutStepDTO(BaseModel):
    """One plain step of a workout, flattened for display; steps of a repeat share `group` and `repeat`."""

    type: str = Field(description='"warmup" | "work" | "recovery" | "cooldown" | "steady"')
    duration_s: int = Field(description="seconds of one round (not multiplied by `repeat`)")
    target_kind: str = Field(description='"hr_zone" | "pace_range" | "open"')
    zone: int = Field(description="1–5: HR zone, pace zone, or the effort zone of an open step")
    low_mps: float | None = Field(default=None, description="pace_range lower speed bound, m/s")
    high_mps: float | None = Field(default=None, description="pace_range upper speed bound, m/s")
    repeat: int | None = Field(description="repeat count when the step is inside a repeat, else null")
    group: int | None = Field(description="index of the repeat block (0, 1, …), else null")


class PlannedWorkoutDTO(BaseModel):
    """A planned workout (METRICS §10.5); `sport = "rest"` is a rest day with no steps."""

    id: int
    date: dt.date
    sport: str = Field(description='"run" | "bike" | "rest"')
    name: str
    key: str = Field(description="§10.7 library key, empty when unknown")
    slot: str | None = Field(description='weekday role filled: "easy" | "long" | "q1" | "q2"')
    status: str = Field(description='"planned" | "pushed" | "done" | "skipped"')
    missed: bool = Field(description="planned/pushed and its date is before today")
    estimated_load: float | None = Field(description="§10.6, TSS-equivalent points")
    duration_s: int = Field(description="total planned seconds, repeats multiplied")
    reason: str | None = Field(description="one-line Slovak reason of the decision")
    completed_activity_id: int | None
    actual_load: float | None = Field(description="load of the completed activity (its primary load)")
    steps: list[WorkoutStepDTO]
    structure: dict[str, Any] = Field(description="the raw §10.5 JSON")


class WeekDayDTO(BaseModel):
    date: dt.date
    weekday: str = Field(description='"mon" … "sun"')
    role: str = Field(description='template role: "rest" | "easy" | "long" | "q1" | "q2"')
    planned: PlannedWorkoutDTO | None
    actual_load: float = Field(description="load_total of the day (all activities)")
    activities: int = Field(description="number of activities on the day")


class WeekPlanDTO(BaseModel):
    """GET /plan/week – the ISO week containing the requested date: targets, planned vs done per day."""

    monday: dt.date
    phase: str
    recovery: bool
    target_load: float
    run_target: float
    bike_target: float
    done_load: float = Field(description="Σ load_total of the week's days")
    remaining_load: float = Field(description="max(0, target_load − done_load)")
    days: list[WeekDayDTO] = Field(description="Monday … Sunday")


class DailyDecisionDTO(BaseModel):
    """GET /plan/today – the day's planned workout with the inputs the decision used (METRICS §10.4)."""

    date: dt.date
    workout: PlannedWorkoutDTO
    reason: str | None
    rule: int | None = Field(description="§10.4 rule that decided (1–4); null when an existing plan was kept")
    readiness: float | None = Field(description="persisted readiness of the day, 0–100")
    readiness_band: str | None = Field(description='"green" | "yellow" | "red"')
    acwr: float | None = Field(description="ACWR[D−1], the last complete day (rule input)")
    tsb: float | None = Field(description="TSB[D] (rule input)")
    created: bool = Field(description="true: decided just now; false: an existing plan was returned")


class StatusIn(BaseModel):
    """POST /plan/{id}/status body."""

    status: str = Field(description='"done" | "skipped" | "planned" (undo)')


class PreferredDayDTO(BaseModel):
    """A weekday of the template: role and an optional explicit sport (METRICS §10.3)."""

    role: str = Field(description='"rest" | "easy" | "long" | "q1" | "q2"')
    sport: str | None = Field(default=None, description='"run" | "bike" | null = decided by the coach')
