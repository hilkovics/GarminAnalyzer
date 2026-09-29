"""Hand-built sample DTOs for the Streamlit UI tests (the contract is `training/services/dto.py`)."""

import datetime as dt

from tests.test_ui_support import MONDAY, TODAY
from training.services.dto import (
    ActivityDetailDTO,
    ActivityListDTO,
    ActivitySummaryDTO,
    AthleteDTO,
    DashboardDTO,
    DiagnosticsDTO,
    LapDTO,
    LoadDivergenceDTO,
    LoadSanityDTO,
    PmcDTO,
    PmcPointDTO,
    PolarizationDTO,
    SettingsDTO,
    StreamsDTO,
    SubjectiveDTO,
    SyncResultDTO,
    ThresholdDTO,
    WeeklyDTO,
    ZoneBoundDTO,
    ZoneTimeDTO,
)

# --- fitness ------------------------------------------------------------------------------------------------


def pmc_point(day: dt.date, index: int, *, warming_up: bool = False, **overrides) -> PmcPointDTO:
    values = {
        "date": day,
        "load_total": 60.0 + (index % 5) * 10,
        "load_run": 40.0,
        "load_bike": 20.0 + (index % 5) * 10,
        "ctl": 40.0 + index * 0.2,
        "atl": 45.0 + (index % 7),
        "tsb": -5.0 + (index % 4),
        "acwr": 1.1,
        "acwr_band": "optimal",
        "monotony": 1.4,
        "strain": 420.0,
        "ramp_rate": 2.5,
        "ramp_warning": False,
        "warming_up": warming_up,
    }
    return PmcPointDTO(**{**values, **overrides})


def sample_pmc(days: int = 120, *, end: dt.date = TODAY, **latest_overrides) -> PmcDTO:
    start = end - dt.timedelta(days=days - 1)
    points = [
        pmc_point(
            start + dt.timedelta(days=i), i, warming_up=i < 90, **(latest_overrides if i == days - 1 else {})
        )
        for i in range(days)
    ]
    return PmcDTO(
        points=points,
        series_start=start,
        warming_up_until=start + dt.timedelta(days=89),
        latest=points[-1],
    )


def weekly_row(
    week_start: dt.date, sport: str, *, load=100.0, duration_s=18000.0, distance_m=42000.0
) -> WeeklyDTO:
    iso = week_start.isocalendar()
    return WeeklyDTO(
        week_start=week_start,
        iso_year=iso.year,
        iso_week=iso.week,
        sport=sport,
        n_activities=3,
        load=load,
        duration_s=duration_s,
        distance_m=distance_m,
        elev_gain_m=300.0,
        time_in_zone={"1": 600.0, "2": 3600.0, "3": 300.0, "4": 200.0, "5": 0.0},
        polarization=PolarizationDTO(low=0.8, mid=0.1, high=0.1),
    )


def sample_weekly(weeks: int = 4, *, end_monday: dt.date = MONDAY) -> list[WeeklyDTO]:
    rows = []
    for i in range(weeks):
        monday = end_monday - dt.timedelta(weeks=weeks - 1 - i)
        rows += [
            weekly_row(monday, "run", load=200.0 + i * 10, duration_s=14400.0, distance_m=30000.0),
            weekly_row(monday, "bike", load=150.0, duration_s=10800.0, distance_m=60000.0),
            weekly_row(monday, "all", load=350.0 + i * 10, duration_s=25200.0, distance_m=90000.0),
        ]
    return rows


def sample_dashboard(*, sync_stale: bool = False, last_sync: dt.date | None = TODAY, **latest_overrides):
    pmc = sample_pmc(42, **latest_overrides)
    return DashboardDTO(
        today=TODAY,
        week_start=MONDAY,
        this_week=[
            weekly_row(MONDAY, "run", load=220.0, duration_s=13500.0, distance_m=31000.0),
            weekly_row(MONDAY, "bike", load=90.0, duration_s=5400.0, distance_m=41000.0),
            weekly_row(MONDAY, "all", load=310.0, duration_s=18900.0, distance_m=72000.0),
        ],
        last4_avg=[
            weekly_row(MONDAY, "run", load=205.0, duration_s=12600.0, distance_m=28000.0),
            weekly_row(MONDAY, "bike", load=140.0, duration_s=9000.0, distance_m=52000.0),
            weekly_row(MONDAY, "all", load=345.0, duration_s=21600.0, distance_m=80000.0),
        ],
        pmc=pmc,
        latest=pmc.latest,
        last_sync=last_sync,
        sync_stale=sync_stale,
    )


# --- activities ---------------------------------------------------------------------------------------------


def sample_summary(activity_id: int = 1, sport: str = "run", **overrides) -> ActivitySummaryDTO:
    values = {
        "id": activity_id,
        "garmin_id": 900000000 + activity_id,
        "sport": sport,
        "sub_sport": None,
        "name": f"Ranný beh {activity_id}",
        "local_date": dt.date(2026, 9, 20) - dt.timedelta(days=activity_id),
        "start_utc": dt.datetime(2026, 9, 20, 5, 30, tzinfo=dt.UTC),
        "tz": "Europe/Bratislava",
        "duration_s": 3725.0,
        "moving_s": 3700.0,
        "distance_m": 12345.0,
        "elev_gain_m": 85.0,
        "avg_hr": 148.0,
        "max_hr": 171.0,
        "avg_speed": 3.3333333,  # 5:00 /km
        "is_race": False,
        "is_indoor": False,
        "load_primary": 87.4,
        "load_method": "hrtss",
        "hrtss": 87.4,
        "rtss": 82.0,
        "trimp_norm": 90.2,
        "if_hr": 0.86,
        "if_pace": 0.84,
        "hr_coverage": 0.99,
        "low_confidence": False,
        "garmin_training_load": 120.0,
    }
    return ActivitySummaryDTO(**{**values, **overrides})


def sample_list(
    n: int = 3, *, total: int | None = None, page: int = 1, page_size: int = 25
) -> ActivityListDTO:
    items = [sample_summary(i + 1) for i in range(n)]
    if n >= 2:
        items[1] = sample_summary(2, "bike", avg_speed=8.0, name="Večerná jazda", low_confidence=True)
    if n >= 3:
        items[2] = sample_summary(
            3, load_primary=None, load_method=None, hrtss=None, rtss=None, name="Bez tepu"
        )
    return ActivityListDTO(items=items, total=n if total is None else total, page=page, page_size=page_size)


def zone_times(kind: str = "hr") -> list[ZoneTimeDTO]:
    if kind == "hr":
        bounds = [(None, 130.0), (130.0, 150.0), (150.0, 162.0), (162.0, 175.0), (175.0, None)]
    else:  # m/s, slowest first
        bounds = [(None, 2.5), (2.5, 3.0), (3.0, 3.4), (3.4, 3.9), (3.9, None)]
    seconds = [600, 1800, 900, 300, 60]
    return [
        ZoneTimeDTO(zone=i + 1, seconds=s, share=s / sum(seconds), lower=lo, upper=hi)
        for i, (s, (lo, hi)) in enumerate(zip(seconds, bounds, strict=True))
    ]


def sample_threshold(threshold_id: int = 1, sport: str = "run", **overrides) -> ThresholdDTO:
    values = {
        "id": threshold_id,
        "sport": sport,
        "valid_from": dt.date(2026, 1, 1),
        "lthr": 170.0,
        "threshold_speed": 4.0 if sport == "run" else None,
        "zones": {"hr": [0.68, 0.84, 0.95, 1.05]},
        "source": "manual",
    }
    return ThresholdDTO(**{**values, **overrides})


def sample_detail(activity_id: int = 1, *, sport: str = "run", subjective: bool = True, **summary_overrides):
    laps = [
        LapDTO(
            index=i,
            duration_s=300.0,
            distance_m=1000.0,
            avg_hr=140.0 + i,
            max_hr=150.0,
            avg_speed=3.3333,
            elev_gain_m=5.0,
        )
        for i in (1, 2)
    ]
    return ActivityDetailDTO(
        summary=sample_summary(activity_id, sport, **summary_overrides),
        laps=laps,
        hr_zones=zone_times("hr"),
        pace_zones=zone_times("pace") if sport == "run" else None,
        threshold=sample_threshold(sport=sport),
        subjective=(
            SubjectiveDTO(
                id=1,
                date=dt.date(2026, 9, 19),
                activity_id=activity_id,
                rpe=6,
                feel=4,
                soreness=1,
                notes="fajn",
            )
            if subjective
            else None
        ),
    )


def sample_streams(activity_id: int = 1, points: int = 60, *, fields: list[str] | None = None) -> StreamsDTO:
    t = list(range(0, points * 10, 10))
    full = {
        "hr": [130.0 + (i % 30) for i in range(points)],
        "speed": [3.3 if i % 20 else 0.0 for i in range(points)],
        "gap_speed": [3.4] * points,
        "alt": [200.0 + i * 0.3 for i in range(points)],
    }
    keep = fields if fields is not None else list(full)
    return StreamsDTO(
        activity_id=activity_id,
        points=points,
        source_points=points * 10,
        t=t,
        series={k: v for k, v in full.items() if k in keep},
    )


# --- settings / diagnostics ---------------------------------------------------------------------------------


def sample_athlete(**overrides) -> AthleteDTO:
    values = {
        "sex": "male",
        "birth_year": 1990,
        "max_hr": 190.0,
        "rest_hr_override": None,
        "rest_hr_current": 48.0,
        "weight_kg": 72.5,
        "run_bike_split": 0.7,
    }
    return AthleteDTO(**{**values, **overrides})


def bounds(kind: str) -> list[ZoneBoundDTO]:
    return [ZoneBoundDTO(zone=z.zone, lower=z.lower, upper=z.upper) for z in zone_times(kind)]


def sample_settings() -> SettingsDTO:
    run = sample_threshold(1, "run")
    older = sample_threshold(2, "run", valid_from=dt.date(2025, 1, 1), lthr=165.0, threshold_speed=3.8)
    bike = sample_threshold(3, "bike", lthr=160.0)
    return SettingsDTO(
        athlete=sample_athlete(),
        thresholds=[older, run, bike],
        current={"run": run, "bike": bike},
        hr_zones={"run": bounds("hr"), "bike": bounds("hr")},
        pace_zones=bounds("pace"),
    )


def sample_diagnostics(**overrides) -> DiagnosticsDTO:
    values = {
        "last_activity_sync": dt.date(2026, 9, 28),
        "last_wellness_date": dt.date(2026, 9, 28),
        "backfill_cursor": dt.date(2024, 9, 1),
        "pending_activities": 2,
        "pending_wellness_days": 1,
        "failed_activities": [900000123],
        "failed_wellness_days": [dt.date(2026, 8, 3)],
        "activities": 320,
        "activities_with_metrics": 318,
        "activities_without_threshold": 4,
        "activities_without_load": 6,
        "low_confidence_share": 0.125,
        "load_sanity": LoadSanityDTO(r=0.87, n=300, status="good"),
        "hrtss_rtss_divergent": [
            LoadDivergenceDTO(
                garmin_id=900000777,
                local_date=dt.date(2026, 7, 4),
                sport="run",
                hrtss=100.0,
                rtss=150.0,
                diff_pct=50.0,
            )
        ],
    }
    return DiagnosticsDTO(**{**values, **overrides})


def sample_sync_result(**overrides) -> SyncResultDTO:
    values = {
        "activities_new": 3,
        "activities_updated": 1,
        "activities_unchanged": 40,
        "activities_pending": 0,
        "activities_failed": 0,
        "wellness_days": 2,
        "metrics_computed": 4,
        "pmc_days": 700,
        "errors": [],
    }
    return SyncResultDTO(**{**values, **overrides})
