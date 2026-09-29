"""Fitness services: PMC series, weekly aggregates and the dashboard (METRICS §4).

`daily_load` (written by `training.pipeline`) and `metrics.pmc` do the maths; this module selects rows,
applies the presentation flags and assembles DTOs.
"""

import datetime as dt
import math

import pandas as pd
from sqlalchemy import func, select
from sqlmodel import Session

from training.db import repo
from training.db.models import Activity, ActivityMetric, DailyLoad
from training.db.state_keys import LAST_ACTIVITY_SYNC
from training.metrics.pmc import HR_ZONES, RAMP_WARNING_ABOVE, acwr_band, weekly_aggregates
from training.services.dto import DashboardDTO, PmcDTO, PmcPointDTO, PolarizationDTO, WeeklyDTO
from training.services.errors import InvalidInputError

WARMUP_DAYS = 90  # METRICS §4: the first 90 days of the series are shaded "warming up"
DASHBOARD_PMC_DAYS = 42
PREVIOUS_WEEKS = 4
MAX_WEEKS = 260
# sync_state keeps dates, not timestamps, so "older than 36 h" (PLAN phase 8) is read as "last synced on a
# calendar day at least two days before today".
STALE_AFTER_DAYS = 2
BASE_SPORTS = ("run", "bike")  # always present in a week, zero-filled


def get_pmc(session: Session, *, date_from: dt.date | None = None, date_to: dt.date | None = None) -> PmcDTO:
    """Daily CTL/ATL/TSB/ACWR/monotony/ramp for [date_from, date_to], date ascending.

    `series_start`, `warming_up_until` and the `warming_up` flag always refer to the whole stored series,
    not to the requested range. `latest` is the last point of the returned range.
    """
    first = session.execute(select(func.min(DailyLoad.date))).scalar()
    if first is None:
        return PmcDTO(points=[], series_start=None, warming_up_until=None, latest=None)
    stmt = select(DailyLoad).order_by(DailyLoad.date)
    if date_from is not None:
        stmt = stmt.where(DailyLoad.date >= date_from)
    if date_to is not None:
        stmt = stmt.where(DailyLoad.date <= date_to)
    warming_until = first + dt.timedelta(days=WARMUP_DAYS - 1)
    points = [_point(row, warming_until) for row in session.execute(stmt).scalars()]
    return PmcDTO(
        points=points,
        series_start=first,
        warming_up_until=warming_until,
        latest=points[-1] if points else None,
    )


def get_weekly(session: Session, *, weeks: int = 12, today: dt.date) -> list[WeeklyDTO]:
    """The last `weeks` ISO weeks up to and including the week of `today`, oldest first.

    Every week has run, bike and all rows (zeros if empty), plus other when there was such an activity.
    """
    if not 1 <= weeks <= MAX_WEEKS:
        raise InvalidInputError(f"weeks must be between 1 and {MAX_WEEKS}")
    this_monday = _monday(today)
    first_monday = this_monday - dt.timedelta(weeks=weeks - 1)
    aggregated = weekly_aggregates(_activity_frame(session, first_monday, this_monday + dt.timedelta(days=6)))
    out: list[WeeklyDTO] = []
    for i in range(weeks):
        out += _week_dtos(aggregated, first_monday + dt.timedelta(weeks=i))
    return out


def get_dashboard(session: Session, *, today: dt.date) -> DashboardDTO:
    """This ISO week vs the mean of the 4 previous weeks, the last 42 days of PMC and the sync freshness.

    `last4_avg` rows are per-week means (zeros count); `n_activities` is that mean rounded to an integer, its
    `week_start` is the Monday of the oldest of the four weeks, and its polarization is that of the four weeks
    together.
    """
    monday = _monday(today)
    window_start = monday - dt.timedelta(weeks=PREVIOUS_WEEKS)
    window = _activity_frame(session, window_start, monday - dt.timedelta(days=1))
    # Collapsing the four weeks into one bucket reuses weekly_aggregates for the sums and the polarization.
    collapsed = weekly_aggregates(window.assign(local_date=window_start))
    pmc = get_pmc(session, date_from=today - dt.timedelta(days=DASHBOARD_PMC_DAYS - 1), date_to=today)
    last_sync = repo.get_state_date(session, LAST_ACTIVITY_SYNC)
    return DashboardDTO(
        today=today,
        week_start=monday,
        this_week=get_weekly(session, weeks=1, today=today),
        last4_avg=_week_dtos(collapsed, window_start, divisor=PREVIOUS_WEEKS),
        pmc=pmc,
        latest=pmc.latest,
        last_sync=last_sync,
        sync_stale=last_sync is None or (today - last_sync).days >= STALE_AFTER_DAYS,
    )


# --- helpers -----------------------------------------------------------------------------------------------


def _monday(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def _point(row: DailyLoad, warming_until: dt.date) -> PmcPointDTO:
    return PmcPointDTO(
        date=row.date,
        load_total=row.load_total,
        load_run=row.load_run,
        load_bike=row.load_bike,
        ctl=row.ctl,
        atl=row.atl,
        tsb=row.tsb,
        acwr=row.acwr,
        acwr_band=acwr_band(row.acwr),
        monotony=row.monotony,
        strain=row.strain,
        ramp_rate=row.ramp_rate,
        ramp_warning=row.ramp_rate is not None and row.ramp_rate > RAMP_WARNING_ABOVE,
        warming_up=row.date <= warming_until,
    )


def _activity_frame(session: Session, first: dt.date, last: dt.date) -> pd.DataFrame:
    """Activities with `local_date` in [first, last] as the input of `metrics.pmc.weekly_aggregates`."""
    rows = session.execute(
        select(
            Activity.local_date,
            Activity.sport,
            ActivityMetric.load_primary,
            Activity.duration_s,
            Activity.distance_m,
            Activity.elev_gain_m,
            ActivityMetric.time_in_hr_zone,
        )
        .join(ActivityMetric, ActivityMetric.activity_id == Activity.id, isouter=True)
        .where(Activity.local_date >= first, Activity.local_date <= last)
    ).all()
    columns = ["local_date", "sport", "load_primary", "duration_s", "distance_m", "elev_gain_m"]
    return pd.DataFrame(rows, columns=[*columns, "time_in_hr_zone"])


def _week_dtos(aggregated: pd.DataFrame, week_start: dt.date, divisor: int = 1) -> list[WeeklyDTO]:
    """One WeeklyDTO per sport of `week_start`: run, bike, other sports present, then all.

    `divisor` turns sums into means (the collapsed 4-week window); missing run/bike/all rows are zeros.
    """
    present = {r.sport: r for r in aggregated[aggregated["week_start"] == week_start].itertuples()}
    extra = sorted(s for s in present if s not in (*BASE_SPORTS, "all"))
    iso = week_start.isocalendar()
    out = []
    for sport in (*BASE_SPORTS, *extra, "all"):
        row = present.get(sport)
        zones = [float(getattr(row, f"tiz_{z}")) / divisor if row else 0.0 for z in HR_ZONES]
        share = None if row is None or pd.isna(row.pol_low) else row
        out.append(
            WeeklyDTO(
                week_start=week_start,
                iso_year=iso.year,
                iso_week=iso.week,
                sport=sport,
                n_activities=math.floor(row.n_activities / divisor + 0.5) if row else 0,  # half up
                load=float(row.load) / divisor if row else 0.0,
                duration_s=float(row.duration_s) / divisor if row else 0.0,
                distance_m=float(row.distance_m) / divisor if row else 0.0,
                elev_gain_m=float(row.elev_gain_m) / divisor if row else 0.0,
                time_in_zone=dict(zip(HR_ZONES, zones, strict=True)),
                polarization=(
                    PolarizationDTO(low=share.pol_low, mid=share.pol_mid, high=share.pol_high)
                    if share is not None
                    else None
                ),
            )
        )
    return out
