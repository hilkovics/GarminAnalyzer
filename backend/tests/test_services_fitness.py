"""services/fitness.py: PMC series and flags, weekly aggregates, dashboard."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training.db import repo
from training.db.models import DailyLoad, SyncState
from training.db.session import make_engine, migrate
from training.db.state_keys import LAST_ACTIVITY_SYNC
from training.services import fitness as svc
from training.services.errors import InvalidInputError

from .seeding import FIRST_MONDAY, TODAY, add_activity, seeded_db

D0 = dt.date(2026, 1, 1)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def insert_days(session: Session, n: int, **fields: float | None) -> None:
    for i in range(n):
        session.add(DailyLoad(date=D0 + dt.timedelta(days=i), **fields))
    session.commit()


# --- PMC ----------------------------------------------------------------------------------------------------


def test_pmc_is_the_daily_load_series_ascending(session):
    dto = svc.get_pmc(session)
    rows = session.execute(select(DailyLoad).order_by(DailyLoad.date)).scalars().all()
    assert [p.date for p in dto.points] == [r.date for r in rows]
    assert len(dto.points) == (TODAY - FIRST_MONDAY).days + 1
    for p, r in zip(dto.points, rows, strict=True):
        assert (p.load_total, p.load_run, p.load_bike) == (r.load_total, r.load_run, r.load_bike)
        assert (p.ctl, p.atl, p.tsb, p.acwr) == (r.ctl, r.atl, r.tsb, r.acwr)
        assert (p.monotony, p.strain, p.ramp_rate) == (r.monotony, r.strain, r.ramp_rate)
    assert dto.latest == dto.points[-1] and dto.latest.date == TODAY
    assert dto.series_start == FIRST_MONDAY
    assert dto.warming_up_until == FIRST_MONDAY + dt.timedelta(days=89)
    first = dto.points[0]
    assert first.load_total == pytest.approx(100 / 3, abs=0.01) and first.ctl == pytest.approx(
        first.load_total / 42
    )
    assert first.tsb == 0.0 and first.acwr is None and first.acwr_band is None and first.ramp_rate is None


def test_pmc_range_filter_keeps_the_series_wide_warm_up_facts(session):
    dto = svc.get_pmc(session, date_from=dt.date(2026, 9, 1), date_to=dt.date(2026, 9, 10))
    assert [p.date for p in dto.points] == [dt.date(2026, 9, 1) + dt.timedelta(days=i) for i in range(10)]
    assert dto.latest is not None and dto.latest.date == dt.date(2026, 9, 10)
    assert dto.series_start == FIRST_MONDAY  # not the range start
    assert svc.get_pmc(session, date_from=dt.date(2026, 9, 15)).points[0].date == dt.date(2026, 9, 15)
    assert svc.get_pmc(session, date_to=dt.date(2026, 7, 28)).points[-1].date == dt.date(2026, 7, 28)
    empty = svc.get_pmc(session, date_from=dt.date(2027, 1, 1))
    assert empty.points == [] and empty.latest is None and empty.series_start == FIRST_MONDAY


def test_pmc_of_an_empty_database(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    with Session(make_engine(path)) as empty:
        dto = svc.get_pmc(empty)
    assert (
        dto.points == [] and dto.latest is None and dto.series_start is None and dto.warming_up_until is None
    )


def test_warming_up_covers_exactly_the_first_90_days(session):
    session.execute(DailyLoad.__table__.delete())
    insert_days(session, 100, load_total=50.0, ctl=40.0, atl=45.0)
    dto = svc.get_pmc(session)
    flags = [p.warming_up for p in dto.points]
    assert flags == [True] * 90 + [False] * 10
    assert dto.warming_up_until == D0 + dt.timedelta(days=89)
    assert dto.points[89].warming_up and not dto.points[90].warming_up
    late = svc.get_pmc(session, date_from=D0 + dt.timedelta(days=95))  # judged against the series start
    assert [p.warming_up for p in late.points] == [False] * 5


@pytest.mark.parametrize(
    ("acwr", "band"),
    [
        (None, None),
        (0.79, "under"),
        (0.8, "optimal"),
        (1.29, "optimal"),
        (1.3, "caution"),
        (1.5, "caution"),
        (1.51, "danger"),
    ],
)
def test_acwr_band_follows_metrics_pmc(session, acwr, band):
    session.execute(DailyLoad.__table__.delete())
    insert_days(session, 1, acwr=acwr)
    assert svc.get_pmc(session).points[0].acwr_band == band


@pytest.mark.parametrize(
    ("ramp", "warning"), [(None, False), (5.9, False), (6.0, False), (6.1, True), (-8.0, False)]
)
def test_ramp_warning_is_ramp_rate_above_six(session, ramp, warning):
    session.execute(DailyLoad.__table__.delete())
    insert_days(session, 1, ramp_rate=ramp)
    assert svc.get_pmc(session).points[0].ramp_warning is warning


# --- weekly -------------------------------------------------------------------------------------------------


def test_weekly_has_run_bike_all_for_every_week_oldest_first(session):
    rows = svc.get_weekly(session, weeks=12, today=TODAY)
    monday = TODAY - dt.timedelta(days=TODAY.weekday())
    weeks = [monday - dt.timedelta(weeks=11 - i) for i in range(12)]
    assert list(dict.fromkeys(r.week_start for r in rows)) == weeks
    for week in weeks:
        sports = [r.sport for r in rows if r.week_start == week]
        assert sports == (
            ["run", "bike", "other", "all"] if week == dt.date(2026, 8, 3) else ["run", "bike", "all"]
        )
    assert all(r.iso_week == r.week_start.isocalendar().week for r in rows)


def test_weekly_fills_empty_weeks_with_zero_rows(session):
    empty = [
        r for r in svc.get_weekly(session, weeks=12, today=TODAY) if r.week_start == dt.date(2026, 6, 29)
    ]
    assert [r.sport for r in empty] == ["run", "bike", "all"]
    for r in empty:
        assert (r.n_activities, r.load, r.duration_s, r.distance_m, r.elev_gain_m) == (0, 0.0, 0.0, 0.0, 0.0)
        assert r.time_in_zone == {"1": 0.0, "2": 0.0, "3": 0.0, "4": 0.0, "5": 0.0}
        assert r.polarization is None


def test_weekly_sums_match_the_activities(session):
    week = {
        r.sport: r
        for r in svc.get_weekly(session, weeks=12, today=TODAY)
        if r.week_start == dt.date(2026, 8, 3)
    }
    run, bike, other, total = week["run"], week["bike"], week["other"], week["all"]
    assert (run.n_activities, bike.n_activities, other.n_activities, total.n_activities) == (1, 1, 1, 3)
    assert run.load == pytest.approx(100 / 3, abs=0.01) and total.load == pytest.approx(
        run.load + bike.load + other.load
    )
    assert (run.duration_s, run.distance_m, run.elev_gain_m) == (1200.0, 4200.0, 10.0)
    assert run.time_in_zone["4"] == 1200.0 and run.time_in_zone["1"] == 0.0
    assert run.polarization is not None and (run.polarization.low, run.polarization.high) == (0.0, 1.0)
    assert other.time_in_zone["2"] == 1200.0  # hike at 0.7 × LTHR → Z2
    assert other.polarization is not None and other.polarization.low == 1.0
    assert total.time_in_zone["4"] == 2400.0 and total.time_in_zone["2"] == 1200.0
    assert total.polarization is not None and total.polarization.low == pytest.approx(1 / 3)
    assert total.polarization.high == pytest.approx(2 / 3) and total.polarization.mid == 0.0


def test_weekly_weeks_argument(session):
    one = svc.get_weekly(session, weeks=1, today=TODAY)
    assert {r.week_start for r in one} == {dt.date(2026, 9, 14)} and [r.sport for r in one] == [
        "run",
        "bike",
        "all",
    ]
    assert len(svc.get_weekly(session, weeks=2, today=TODAY)) == 6
    assert svc.get_weekly(session, weeks=1, today=dt.date(2026, 9, 20))[0].week_start == dt.date(
        2026, 9, 14
    )  # Sunday
    assert svc.get_weekly(session, weeks=1, today=dt.date(2026, 9, 21))[0].week_start == dt.date(
        2026, 9, 21
    )  # Monday
    for bad in (0, -1, svc.MAX_WEEKS + 1):
        with pytest.raises(InvalidInputError):
            svc.get_weekly(session, weeks=bad, today=TODAY)


def test_weekly_ignores_activities_of_later_weeks(session):
    add_activity(session, 960, dt.date(2026, 9, 22))
    assert {r.week_start for r in svc.get_weekly(session, weeks=12, today=TODAY)}.isdisjoint(
        {dt.date(2026, 9, 21)}
    )


# --- dashboard ----------------------------------------------------------------------------------------------


def test_dashboard_this_week_and_pmc_mini(session):
    dto = svc.get_dashboard(session, today=TODAY)
    assert dto.today == TODAY and dto.week_start == dt.date(2026, 9, 14)
    assert [(r.sport, r.n_activities) for r in dto.this_week] == [("run", 1), ("bike", 1), ("all", 2)]
    assert dto.this_week[2].load == pytest.approx(200 / 3, abs=0.01)
    assert len(dto.pmc.points) == 42 and dto.pmc.points[-1].date == TODAY
    assert dto.pmc.points[0].date == TODAY - dt.timedelta(days=41)
    assert dto.latest == dto.pmc.latest and dto.latest is not None and dto.latest.date == TODAY
    assert dto.last_sync == TODAY and dto.sync_stale is False


def test_dashboard_last4_average_over_the_four_previous_weeks(session):
    dto = svc.get_dashboard(session, today=TODAY)
    assert [r.sport for r in dto.last4_avg] == ["run", "bike", "all"]  # the hike is outside these weeks
    assert {r.week_start for r in dto.last4_avg} == {dt.date(2026, 8, 17)}
    run, bike, total = dto.last4_avg
    assert run.n_activities == 1 and run.load == pytest.approx(100 / 3, abs=0.01)
    assert total.load == pytest.approx(200 / 3, abs=0.01) and total.duration_s == 2400.0
    assert total.distance_m == pytest.approx(4200 + 8 * 1200)
    assert run.polarization is not None and run.polarization.high == 1.0
    assert bike.time_in_zone["4"] == 1200.0


def test_dashboard_average_counts_empty_weeks_as_zero(session):
    """today = Monday 2026-08-17: weeks 07-20 (empty), 07-27, 08-03, 08-10 → three of four have a run."""
    dto = svc.get_dashboard(session, today=dt.date(2026, 8, 17))
    assert [r.sport for r in dto.last4_avg] == ["run", "bike", "other", "all"]
    run, _, other, total = dto.last4_avg
    assert run.load == pytest.approx(3 * (100 / 3) / 4, abs=0.01)
    assert run.n_activities == 1  # 0.75 rounds half up
    assert other.n_activities == 0 and other.distance_m == pytest.approx(1.5 * 1200 / 4)  # 0.25 → 0
    assert total.time_in_zone["4"] == pytest.approx(6 * 1200 / 4)
    assert dto.last4_avg[0].week_start == dt.date(2026, 7, 20)
    assert dto.pmc.points[-1].date == dt.date(2026, 8, 17)  # PMC ends at `today`


def test_dashboard_average_count_rounds_half_up(session):
    """today = Monday 2026-08-10: two of the four previous weeks have a run → mean 0.5 → 1, not banker's 0."""
    dto = svc.get_dashboard(session, today=dt.date(2026, 8, 10))
    run = dto.last4_avg[0]
    assert (
        run.sport == "run"
        and run.n_activities == 1
        and run.load == pytest.approx(2 * (100 / 3) / 4, abs=0.01)
    )


def test_weekly_counts_a_sunday_activity_in_its_own_week(session):
    add_activity(session, 961, dt.date(2026, 9, 20))  # Sunday of the current week
    add_activity(session, 962, dt.date(2026, 9, 21))  # Monday of the next one
    week = {r.sport: r for r in svc.get_weekly(session, weeks=1, today=TODAY)}
    assert week["all"].n_activities == 3 and week["run"].n_activities == 2


def test_dashboard_sync_freshness_from_sync_state(session):
    def stale(last: dt.date | None) -> tuple[dt.date | None, bool]:
        if last is not None:
            repo.set_state(session, LAST_ACTIVITY_SYNC, last.isoformat())
            session.commit()
        dto = svc.get_dashboard(session, today=TODAY)
        return dto.last_sync, dto.sync_stale

    assert stale(TODAY - dt.timedelta(days=1)) == (TODAY - dt.timedelta(days=1), False)
    assert stale(TODAY - dt.timedelta(days=2)) == (TODAY - dt.timedelta(days=2), True)
    session.execute(SyncState.__table__.delete())
    session.commit()
    assert stale(None) == (None, True)


def test_dashboard_without_pmc_rows_still_reports_the_weeks(session):
    session.execute(DailyLoad.__table__.delete())
    session.commit()
    dto = svc.get_dashboard(session, today=TODAY)
    assert dto.pmc.points == [] and dto.latest is None and dto.pmc.series_start is None
    assert dto.this_week[-1].n_activities == 2
