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
    target_load: float = Field(description="training target T_train = max(0, T − commute_load) (§10.2)")
    run_target: float
    bike_target: float
    commute_load: float = Field(0.0, description="expected weekly commute load C (§2.6, §10.2)")
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
    provisional: bool = Field(
        default=False, description="decided before the day's sync; the sync's nightly step decides it again"
    )
    garmin_workout_id: int | None = Field(
        default=None, description="set once pushed (§10.8); kept by a regeneration so a re-push updates it"
    )
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
    actual_load: float = Field(description="training load of the day (load_total without commutes, §2.6)")
    activities: int = Field(description="number of activities on the day, commutes excluded")
    commute_load: float = Field(0.0, description="load of the day's commutes (fatigue, not training; §2.6)")


class FitnessSlotDTO(BaseModel):
    """One item of the §11.1 week menu."""

    slot: str = Field(description='"k" quality | "d" longer run | "e" easy run')
    label: str = Field(description="Slovak name of the item")
    minutes: int = Field(description="§11.3 planned length (a longer run on the weekend may be longer)")
    weekday_minutes: int = Field(description="§11.3 length on a weekday (≤ 60 min for the longer run)")
    done_date: dt.date | None = Field(description="day it was done (a done plan, or an unplanned run for Ľ)")


class FitnessWeekDTO(BaseModel):
    """The coach "Kondícia" week (METRICS §11.3) inside its 12-week block."""

    block_start: dt.date
    week_no: int = Field(description="1 … block_weeks")
    block_weeks: int
    base_s: float = Field(description="weekly base running time, seconds")
    target_s: float = Field(description="this week's running time T, seconds (recovery weeks 0.7 × base)")
    run_s: float = Field(description="non-commute running time done this week, seconds")
    brake: str | None = Field(description='null | "hold" | "cut" (§11.3 brakes from last week)')
    recovery: bool
    test: bool = Field(description="test week: the quality session is the check run")
    menu: list[FitnessSlotDTO] = Field(description="K, D, Ľ")


class WeekPlanDTO(BaseModel):
    """GET /plan/week – the ISO week containing the requested date: targets, planned vs done per day."""

    monday: dt.date
    phase: str
    recovery: bool
    target_load: float = Field(description="training target T_train = max(0, T − commute_load) (§10.2)")
    run_target: float
    bike_target: float
    commute_load: float = Field(0.0, description="expected weekly commute load C (§2.6, §10.2)")
    done_load: float = Field(description="Σ training load of the week's days (commutes excluded, §2.6)")
    remaining_load: float = Field(description="max(0, target_load − done_load)")
    days: list[WeekDayDTO] = Field(description="Monday … Sunday")
    mode: str = Field("race", description='"fitness" (§11, no active race goal) | "race" (§10)')
    fitness: FitnessWeekDTO | None = Field(
        None, description="§11 week in fitness mode; null before the first block or for a future week"
    )


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
    mode: str = Field("race", description='"fitness" (§11) | "race" (§10)')
    waiting_sleep: bool = Field(
        False, description="§11.2: provisional until the night's sleep arrives, decided by 12:00"
    )


class StatusIn(BaseModel):
    """POST /plan/{id}/status body."""

    status: str = Field(description='"done" | "skipped" | "planned" (undo)')


class PreferredDayDTO(BaseModel):
    """A weekday of the template: role and an optional explicit sport (METRICS §10.3)."""

    role: str = Field(description='"rest" | "easy" | "long" | "q1" | "q2"')
    sport: str | None = Field(default=None, description='"run" | "bike" | null = decided by the coach')


class PushResultDTO(BaseModel):
    """POST /plan/{id}/push and `training push-today` (METRICS §10.8)."""

    planned_id: int
    action: str = Field(description='"uploaded" | "updated" | "deleted" | "skipped" | "dry_run"')
    garmin_workout_id: int | None = None
    scheduled_date: dt.date | None = None
    payload: dict[str, Any] | None = Field(default=None, description="the Garmin workout JSON (dry run only)")
    notes: list[str] = Field(default_factory=list)
