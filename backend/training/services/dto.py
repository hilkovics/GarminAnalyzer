"""Pydantic DTOs shared by Streamlit and FastAPI (CLAUDE.md rule 3; PLAN §5 API contract).

Services return exactly these; FastAPI serializes them 1:1 and the React frontend (phase 9) consumes the same
shapes. Field names are snake_case. Internal units only – seconds, metres, m/s, bpm, TSS-equivalent points;
pace (min/km) and h:mm are formatted in the presentation layer, never here.
"""

import datetime as dt

from pydantic import BaseModel, Field

# coach "Kondícia" block progress DTOs live in dto_coach.py
from training.services.dto_coach import (
    BlockProgressDTO as BlockProgressDTO,
    BlockRefDTO as BlockRefDTO,
    BlockSummaryDTO as BlockSummaryDTO,
    BlockWeekDTO as BlockWeekDTO,
    CheckRunDTO as CheckRunDTO,
    FitnessChangeDTO as FitnessChangeDTO,
    FitnessSnapshotDTO as FitnessSnapshotDTO,
)

# fitness DTOs live in dto_fitness.py
from training.services.dto_fitness import (
    DashboardDTO as DashboardDTO,
    PmcDTO as PmcDTO,
    PmcPointDTO as PmcPointDTO,
    PolarizationDTO as PolarizationDTO,
    WeeklyDTO as WeeklyDTO,
)

# prediction DTOs live in dto_forecast.py
from training.services.dto_forecast import (
    ForecastDTO as ForecastDTO,
    OutlookDayDTO as OutlookDayDTO,
    SleepEffectDTO as SleepEffectDTO,
    SleepNoteDTO as SleepNoteDTO,
)

# phase-8 DTOs live in dto_health.py
from training.services.dto_health import (
    MorningRunDTO as MorningRunDTO,
    MorningStepDTO as MorningStepDTO,
)

# health page DTOs live in dto_health_trends.py
from training.services.dto_health_trends import (
    HealthMetricDTO as HealthMetricDTO,
    HealthOverviewDTO as HealthOverviewDTO,
    HealthPointDTO as HealthPointDTO,
    HealthRelationshipDTO as HealthRelationshipDTO,
    HealthRelationshipsDTO as HealthRelationshipsDTO,
    HealthSeriesDTO as HealthSeriesDTO,
    MonthValueDTO as MonthValueDTO,
    RecentChangeDTO as RecentChangeDTO,
)

# phase-6 DTOs live in dto_plan.py
from training.services.dto_plan import (
    DailyDecisionDTO as DailyDecisionDTO,
    FitnessSlotDTO as FitnessSlotDTO,
    FitnessWeekDTO as FitnessWeekDTO,
    GoalDTO as GoalDTO,
    GoalIn as GoalIn,
    PlannedWorkoutDTO as PlannedWorkoutDTO,
    PreferredDayDTO as PreferredDayDTO,
    PushResultDTO as PushResultDTO,
    SeasonDTO as SeasonDTO,
    SeasonWeekDTO as SeasonWeekDTO,
    StatusIn as StatusIn,
    WeekDayDTO as WeekDayDTO,
    WeekPlanDTO as WeekPlanDTO,
    WorkoutStepDTO as WorkoutStepDTO,
)

# phase-4 progress DTOs live in dto_progress.py
from training.services.dto_progress import (
    BestEffortDTO as BestEffortDTO,
    BestEffortsDTO as BestEffortsDTO,
    CurveBinDTO as CurveBinDTO,
    CurveDTO as CurveDTO,
    PredictionDTO as PredictionDTO,
    PredictionsDTO as PredictionsDTO,
    ProposalApplyIn as ProposalApplyIn,
    ProposalDTO as ProposalDTO,
    ProposalGapDTO as ProposalGapDTO,
    ReferenceDTO as ReferenceDTO,
    SeriesDTO as SeriesDTO,
    SeriesPointDTO as SeriesPointDTO,
    TrendPointDTO as TrendPointDTO,
)

# phase-7 DTOs live in dto_report.py
from training.services.dto_report import (
    MorningMessageDTO as MorningMessageDTO,
    ReportActivityDTO as ReportActivityDTO,
    ReportDTO as ReportDTO,
    ReportPmcDTO as ReportPmcDTO,
    ReportReadinessDTO as ReportReadinessDTO,
    WeeklyReportInputsDTO as WeeklyReportInputsDTO,
)

# phase-5 DTOs live in dto_wellness.py (file size); re-exported so callers keep importing from here
from training.services.dto_wellness import (
    BaselineDTO as BaselineDTO,
    CorrelationDTO as CorrelationDTO,
    CorrelationsDTO as CorrelationsDTO,
    ReadinessComponentDTO as ReadinessComponentDTO,
    ReadinessDTO as ReadinessDTO,
    WellnessBaselinesDTO as WellnessBaselinesDTO,
    WellnessDayDTO as WellnessDayDTO,
    WellnessDTO as WellnessDTO,
)

# --- thresholds / settings ---------------------------------------------------------------------------------


class ThresholdDTO(BaseModel):
    id: int
    sport: str = Field(description='"run" | "bike"')
    valid_from: dt.date
    lthr: float | None = Field(description="bpm")
    threshold_speed: float | None = Field(description="m/s, run only")
    zones: dict = Field(
        description='{"hr": [0.68, 0.84, 0.95, 1.05], "pace": [...]} – fractions (METRICS §1)'
    )
    source: str = Field(description='"manual" | "proposal"')


class ThresholdIn(BaseModel):
    """PUT /settings/thresholds body."""

    sport: str
    valid_from: dt.date
    lthr: float = Field(gt=0, description="bpm")
    threshold_speed: float | None = Field(default=None, gt=0, description="m/s, run only")
    source: str = Field(default="manual", description='"manual" | "proposal" (applied §6.3 proposal)')


class AthleteDTO(BaseModel):
    sex: str | None = Field(description='"male" | "female"')
    birth_year: int | None
    max_hr: float | None = Field(description="bpm")
    rest_hr_override: float | None = Field(description="bpm; null → 28-day median Garmin RHR")
    rest_hr_current: float | None = Field(description="bpm, the value used today (override or median)")
    weight_kg: float | None
    run_bike_split: float | None = Field(description="share of weekly load for running (0–1)")
    preferred_days: dict[str, PreferredDayDTO] = Field(
        default_factory=dict,
        description="role per weekday mon…sun (METRICS §10.3), defaults filled in; empty without athlete",
    )


class AthleteIn(BaseModel):
    """PUT /settings/athlete body; null fields are left unchanged."""

    sex: str | None = None
    birth_year: int | None = None
    max_hr: float | None = Field(default=None, gt=0)
    rest_hr_override: float | None = Field(default=None, gt=0)
    weight_kg: float | None = Field(default=None, gt=0)
    run_bike_split: float | None = Field(default=None, ge=0, le=1)
    preferred_days: dict[str, PreferredDayDTO] | None = Field(
        default=None,
        description="weekday (mon…sun) → role [+ sport]; missing days take the default, {} resets all",
    )
    clear_rest_hr_override: bool = Field(
        default=False, description="true → remove the manual rest HR (back to the 28-day Garmin median)"
    )


class ZoneBoundDTO(BaseModel):
    zone: int = Field(ge=1, le=5)
    lower: float | None = Field(description="bpm (HR) or m/s (pace); null = open")
    upper: float | None


class SettingsDTO(BaseModel):
    athlete: AthleteDTO | None
    thresholds: list[ThresholdDTO] = Field(description="full history, sport then valid_from ascending")
    current: dict[str, ThresholdDTO | None] = Field(description='{"run": …, "bike": …} valid today')
    hr_zones: dict[str, list[ZoneBoundDTO]] = Field(
        description="per sport, absolute bpm bounds of today's zones"
    )
    pace_zones: list[ZoneBoundDTO] | None = Field(description="run pace zones in m/s for today's threshold")


# --- activities --------------------------------------------------------------------------------------------


class ActivitySummaryDTO(BaseModel):
    id: int
    garmin_id: int
    sport: str
    sub_sport: str | None
    name: str | None
    local_date: dt.date
    start_utc: dt.datetime
    tz: str | None
    duration_s: float | None
    moving_s: float | None
    distance_m: float | None
    elev_gain_m: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_speed: float | None = Field(description="m/s")
    is_race: bool
    is_indoor: bool
    load_primary: float | None = Field(description="TSS-equivalent points (null = unknown, METRICS §2.1)")
    load_method: str | None = Field(description='"rtss" | "hrtss" | null')
    hrtss: float | None
    rtss: float | None
    trimp_norm: float | None
    if_hr: float | None
    if_pace: float | None
    hr_coverage: float | None = Field(description="0–1")
    low_confidence: bool
    garmin_training_load: float | None
    is_commute: bool = Field(False, description="METRICS §2.6: counts as fatigue, not as training")
    commute_override: bool | None = Field(
        None, description="user's choice; null = the §2.6 rule (ride < 25 min)"
    )


class CommuteIn(BaseModel):
    """PUT /activities/{id}/commute body (METRICS §2.6)."""

    commute: bool | None = Field(description="true / false = override; null = back to the rule")


class ActivityListDTO(BaseModel):
    items: list[ActivitySummaryDTO] = Field(description="newest first")
    total: int
    page: int
    page_size: int


class LapDTO(BaseModel):
    index: int = Field(description="1-based")
    duration_s: float | None
    distance_m: float | None
    avg_hr: float | None
    max_hr: float | None
    avg_speed: float | None = Field(description="m/s")
    elev_gain_m: float | None


class ZoneTimeDTO(BaseModel):
    zone: int = Field(ge=1, le=5)
    seconds: int
    share: float = Field(description="0–1 of the zone total")
    lower: float | None = Field(description="bpm or m/s bound of the threshold used; null = open")
    upper: float | None


class SubjectiveIn(BaseModel):
    """POST /activities/{id}/subjective body."""

    rpe: int | None = Field(default=None, ge=1, le=10)
    feel: int | None = Field(default=None, ge=1, le=5)
    soreness: int | None = Field(default=None, ge=0, le=3)
    notes: str | None = Field(default=None, max_length=2000)


class SubjectiveDTO(SubjectiveIn):
    id: int
    date: dt.date
    activity_id: int | None


class ActivityDetailDTO(BaseModel):
    summary: ActivitySummaryDTO
    laps: list[LapDTO]
    hr_zones: list[ZoneTimeDTO] = Field(description="empty if no threshold / no HR")
    pace_zones: list[ZoneTimeDTO] | None = Field(description="runs with a threshold speed only")
    threshold: ThresholdDTO | None = Field(description="the record valid at the activity date")
    subjective: SubjectiveDTO | None


class StreamsDTO(BaseModel):
    activity_id: int
    points: int = Field(description="number of points after LTTB downsampling")
    source_points: int = Field(description="1 Hz samples before downsampling")
    t: list[int] = Field(description="seconds since start (elapsed, pauses included)")
    series: dict[str, list[float | None]] = Field(
        description="requested: hr (bpm), speed / gap_speed (m/s), alt (m), grade, cadence, distance (m)"
    )


# --- sync / diagnostics ------------------------------------------------------------------------------------


class SyncResultDTO(BaseModel):
    activities_new: int
    activities_updated: int
    activities_unchanged: int
    activities_pending: int
    activities_failed: int
    wellness_days: int
    metrics_computed: int
    pmc_days: int
    errors: list[str]


class LoadSanityDTO(BaseModel):
    """METRICS §2.5: Pearson r between load_primary and Garmin training load."""

    r: float | None = Field(description="Pearson correlation coefficient, null if n < 3")
    n: int = Field(description="activities with both values")
    status: str = Field(description='"good" (r > 0.8) | "fair" | "warning" (r < 0.7) | "insufficient"')


class LoadDivergenceDTO(BaseModel):
    garmin_id: int
    local_date: dt.date
    sport: str
    hrtss: float = Field(description="TSS-equivalent points")
    rtss: float = Field(description="TSS-equivalent points")
    diff_pct: float = Field(description="|hrTSS − rTSS| / min(hrTSS, rTSS) · 100 (relative to the smaller)")


class DiagnosticsDTO(BaseModel):
    last_activity_sync: dt.date | None
    last_wellness_date: dt.date | None
    backfill_cursor: dt.date | None
    pending_activities: int
    pending_wellness_days: int
    failed_activities: list[int]
    failed_wellness_days: list[dt.date]
    activities: int
    activities_with_metrics: int
    activities_without_threshold: int = Field(
        description="activities with no threshold record valid at their date"
    )
    activities_without_load: int = Field(
        description="activities whose load_primary is null (no LTHR, no HR, …)"
    )
    low_confidence_share: float | None = Field(description="share of activities flagged low_confidence (0–1)")
    load_sanity: LoadSanityDTO
    hrtss_rtss_divergent: list[LoadDivergenceDTO] = Field(
        description="runs where hrTSS and rTSS differ by > 40 % of the smaller value (threshold check)"
    )
    recent_runs: list[MorningRunDTO] = Field(
        default_factory=list, description="last 10 `training morning` runs, newest first"
    )
    last_errors: list[str] = Field(
        default_factory=list,
        description="failed-step messages of those runs, newest first, prefixed with the local start time",
    )
