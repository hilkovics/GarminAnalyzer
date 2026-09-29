"""services/progress.py on a seeded DB (phase-4 scenario, see progress_seeding.py) and on an empty one."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training.db import raw_kinds, repo
from training.db.models import Activity, CurveSnapshot, RawGarmin, Threshold
from training.db.session import make_engine, migrate
from training.services import progress as svc
from training.services import settings as settings_svc
from training.services.dto import ThresholdIn
from training.services.errors import InvalidInputError

from .progress_seeding import EASY_DAYS, EASY_EF, RACE_DAY, RIDE_DAY, RIDE_EF, progress_db
from .seeding import TODAY


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(progress_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def empty_session(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = make_engine(path)
    with Session(engine) as s:
        yield s
    engine.dispose()


# --- EF / decoupling / pace at reference HR -----------------------------------------------------------------


def test_ef_series_has_only_steady_state_runs_and_the_28_day_median(session):
    dto = svc.get_ef_series(session, sport="run", days=180, today=TODAY)
    assert (dto.metric, dto.sport, dto.unit) == ("ef", "run", "m/min/bpm")
    assert [p.local_date for p in dto.points] == list(EASY_DAYS)
    assert all(p.steady_state is True for p in dto.points)
    assert dto.points[0].value == pytest.approx(EASY_EF, rel=1e-3)
    assert dto.caveat is None
    assert len(dto.trend) == 180 and dto.trend[-1].date == TODAY
    by_day = {t.date: t.value for t in dto.trend}
    assert by_day[dt.date(2026, 8, 31)] is None  # before the first steady run
    assert by_day[EASY_DAYS[0]] == pytest.approx(EASY_EF, rel=1e-3)
    assert by_day[TODAY] == pytest.approx(EASY_EF, rel=1e-3)  # median of two equal values


def test_ef_trend_forgets_runs_older_than_28_days(session):
    dto = svc.get_ef_series(session, days=180, today=TODAY + dt.timedelta(days=50))
    by_day = {t.date: t.value for t in dto.trend}
    assert by_day[EASY_DAYS[1] + dt.timedelta(days=27)] is not None
    assert by_day[EASY_DAYS[1] + dt.timedelta(days=28)] is None


def test_series_window_keeps_lookback_for_the_trend(session):
    """`days=10` shows only the last run, but the trend still sees the run 10 days earlier."""
    dto = svc.get_ef_series(session, days=10, today=TODAY)
    assert len(dto.trend) == 10
    assert [p.local_date for p in dto.points] == [EASY_DAYS[1]]
    assert dto.trend[0].date == TODAY - dt.timedelta(days=9)
    assert dto.trend[0].value == pytest.approx(EASY_EF, rel=1e-3)


def test_bike_ef_carries_the_terrain_caveat(session):
    dto = svc.get_ef_series(session, sport="bike", days=90, today=TODAY)
    assert [p.local_date for p in dto.points] == [RIDE_DAY]
    assert dto.points[0].value == pytest.approx(RIDE_EF, rel=1e-3)
    assert dto.caveat and "terrain" in dto.caveat
    assert svc.get_ef_series(session, sport="bike", metric="pace_at_ref_hr_day", today=TODAY).caveat is None


def test_decoupling_series_of_steady_runs(session):
    dto = svc.get_ef_series(session, metric="decoupling_pct", days=90, today=TODAY)
    assert dto.unit == "%"
    assert [p.local_date for p in dto.points] == list(EASY_DAYS)
    assert all(p.value == pytest.approx(0.0, abs=0.5) for p in dto.points)


def test_pace_at_ref_hr_series_is_in_m_per_s(session):
    dto = svc.get_ef_series(session, metric="pace_at_ref_hr_day", days=90, today=TODAY)
    assert dto.unit == "m/s"
    assert [p.local_date for p in dto.points] == list(EASY_DAYS)
    assert dto.points[0].value == pytest.approx(3.5, rel=1e-3)
    assert svc.get_ef_series(session, sport="bike", metric="pace_at_ref_hr_day", today=TODAY).points == []


@pytest.mark.parametrize("kwargs", [{"metric": "nope"}, {"sport": "other"}, {"days": 0}, {"days": 100000}])
def test_series_rejects_bad_parameters(session, kwargs):
    with pytest.raises(InvalidInputError):
        svc.get_ef_series(session, today=TODAY, **kwargs)


def test_series_on_an_empty_db_is_empty(empty_session):
    dto = svc.get_ef_series(empty_session, today=TODAY)
    assert dto.points == [] and dto.trend == []


# --- speed–HR curves ----------------------------------------------------------------------------------------


def test_curves_are_month_snapshots_oldest_first(session):
    curves = svc.get_speed_hr_curves(session, months=6, today=TODAY)
    assert [c.month for c in curves] == ["2026-07", "2026-08", "2026-09"]
    september = curves[-1]
    assert september.sport == "run"
    bins = {b.hr_bin: b for b in september.bins}
    assert 170 in bins and bins[170].gap_speed == pytest.approx(3.5, rel=1e-3) and bins[170].count >= 10
    assert 140 in bins and bins[140].gap_speed == pytest.approx(3.5, rel=1e-3)
    assert [b.hr_bin for b in september.bins] == sorted(bins)
    assert september.ref_hr == pytest.approx(136.0)  # 0.80 · LTHR 170


def test_curve_months_limit(session):
    assert [c.month for c in svc.get_speed_hr_curves(session, months=1, today=TODAY)] == ["2026-09"]
    two = svc.get_speed_hr_curves(session, months=2, today=TODAY)
    assert [c.month for c in two] == ["2026-08", "2026-09"]
    assert svc.get_speed_hr_curves(session, months=6, today=dt.date(2027, 6, 1)) == []


def test_curves_reject_bad_months(session):
    for months in (0, 1000):
        with pytest.raises(InvalidInputError):
            svc.get_speed_hr_curves(session, months=months, today=TODAY)


def test_curves_survive_malformed_snapshot_json(session):
    bad = {"bins": {"x": 3.0, "150": "fast", "155": 3.2, "160": -1.0}}
    session.add(CurveSnapshot(month="2026-06", sport="run", curve=bad))
    session.add(CurveSnapshot(month="2026-05", sport="run", curve={"bins": [1, 2]}))
    session.commit()
    curves = {c.month: c for c in svc.get_speed_hr_curves(session, months=6, today=TODAY)}
    assert [b.hr_bin for b in curves["2026-06"].bins] == [155]
    assert curves["2026-06"].bins[0].count == 0 and curves["2026-06"].ref_hr is None
    assert curves["2026-05"].bins == []


def test_curves_on_an_empty_db(empty_session):
    assert svc.get_speed_hr_curves(empty_session, today=TODAY) == []


# --- best efforts -------------------------------------------------------------------------------------------


def test_best_efforts_90_days_and_all_time(session):
    recent = svc.get_best_efforts(session, sport="run", range="90d", today=TODAY)
    assert (recent.sport, recent.range) == ("run", "90d")
    kinds = {(e.kind, e.window_s) for e in recent.efforts}
    assert {("gap_speed", 60), ("gap_speed", 1800), ("hr", 1800)} <= kinds
    assert {k[0] for k in kinds} == {"gap_speed", "hr"}
    best_1800 = next(e for e in recent.efforts if (e.kind, e.window_s) == ("gap_speed", 1800))
    assert best_1800.value == pytest.approx(3.5, rel=1e-3)
    assert best_1800.local_date == EASY_DAYS[0]  # ties → the earliest date
    assert best_1800.distance_m == pytest.approx(3.5 * 1800, rel=0.01)
    hr = next(e for e in recent.efforts if (e.kind, e.window_s) == ("hr", 1200))
    assert hr.value == pytest.approx(170.0) and hr.distance_m is None
    assert svc.get_best_efforts(session, range="all", today=TODAY).range == "all"


def test_best_efforts_window_boundaries(session):
    later = TODAY + dt.timedelta(days=100)
    assert svc.get_best_efforts(session, range="90d", today=later).efforts == []
    assert len(svc.get_best_efforts(session, range="all", today=later).efforts) > 0
    # today = 2026-09-11 + 89 days is the last day the last easy run is in the window
    edge = EASY_DAYS[1] + dt.timedelta(days=89)
    inside = svc.get_best_efforts(session, range="90d", today=edge)
    assert {e.local_date for e in inside.efforts} == {EASY_DAYS[1]} or len(inside.efforts) > 0
    outside = svc.get_best_efforts(session, range="90d", today=edge + dt.timedelta(days=1))
    assert EASY_DAYS[1] not in {e.local_date for e in outside.efforts}


def test_best_efforts_bike_has_speed_kind(session):
    dto = svc.get_best_efforts(session, sport="bike", range="all", today=TODAY)
    assert {e.kind for e in dto.efforts} == {"speed", "hr"}
    assert all(e.window_s >= 300 for e in dto.efforts if e.kind == "speed")


@pytest.mark.parametrize("kwargs", [{"range": "30d"}, {"sport": "swim"}, {"sport": "other"}])
def test_best_efforts_reject_bad_parameters(session, kwargs):
    with pytest.raises(InvalidInputError):
        svc.get_best_efforts(session, today=TODAY, **kwargs)


def test_best_efforts_on_an_empty_db(empty_session):
    assert svc.get_best_efforts(empty_session, today=TODAY).efforts == []


# --- predictions --------------------------------------------------------------------------------------------


def test_predictions_use_the_race_as_reference(session):
    dto = svc.get_predictions(session, today=TODAY)
    ref = dto.reference
    assert ref is not None and ref.source == "race" and ref.local_date == RACE_DAY
    assert (ref.distance_m, ref.time_s) == (10000.0, 2400.0)
    assert ref.vdot == pytest.approx(51.94, abs=0.05)  # METRICS §7 test value
    assert dto.stale is False
    by_name = {p.name: p for p in dto.predictions}
    assert list(by_name) == ["5k", "10k", "half", "marathon"]
    assert by_name["10k"].riegel_s == pytest.approx(2400.0)
    assert by_name["10k"].daniels_s == pytest.approx(2400.0, abs=1)
    assert by_name["half"].daniels_s == pytest.approx(88 * 60 + 33, abs=10)  # METRICS §7: ≈ 1:28:33
    assert by_name["half"].riegel_s == pytest.approx(2400.0 * (21097.5 / 10000.0) ** 1.06)
    assert [p.name for p in dto.predictions if p.extrapolated] == ["marathon"]  # 10 km < 42.2 km / 4


def test_predictions_flag_a_stale_reference(session):
    stale = svc.get_predictions(session, today=RACE_DAY + dt.timedelta(days=61))
    assert stale.reference is not None and stale.stale is True
    assert svc.get_predictions(session, today=RACE_DAY + dt.timedelta(days=60)).stale is False


def test_predictions_fall_back_to_efforts_without_a_race(session):
    for activity in session.execute(select(Activity).where(Activity.is_race.is_(True))).scalars():
        activity.is_race = False
        session.add(activity)
    session.commit()
    dto = svc.get_predictions(session, today=TODAY)
    ref = dto.reference
    assert ref is not None and ref.source == "effort"
    assert ref.time_s in (600.0, 1200.0, 1800.0, 3600.0)  # a window length
    assert ref.distance_m == pytest.approx(3.5 * ref.time_s, rel=0.01)
    marathon = next(p for p in dto.predictions if p.name == "marathon")
    assert marathon.extrapolated is True  # reference distance < 42.2 km / 4


def test_predictions_without_candidates(empty_session):
    dto = svc.get_predictions(empty_session, today=TODAY)
    assert dto.reference is None and dto.predictions == [] and dto.stale is False


# --- threshold proposals ------------------------------------------------------------------------------------


def proposal(dtos, sport, field):
    matches = [p for p in dtos if (p.sport, p.field) == (sport, field)]
    assert len(matches) == 1, [(p.sport, p.field) for p in dtos]
    return matches[0]


def test_proposals_cover_speed_and_both_lthr(session):
    dtos = svc.get_threshold_proposals(session, today=TODAY)
    assert [(p.sport, p.field) for p in dtos] == [
        ("run", "threshold_speed"),
        ("run", "lthr"),
        ("bike", "lthr"),
    ]
    speed = proposal(dtos, "run", "threshold_speed")
    assert speed.current == 3.5 and speed.estimate == pytest.approx(3.5, abs=0.01)
    assert speed.change == pytest.approx(0.0, abs=0.01) and speed.propose is False
    lthr = proposal(dtos, "run", "lthr")
    assert lthr.current == 170.0 and lthr.estimate == 140.0  # best 30 min HR of the qualifying runs
    assert lthr.change == -30.0 and lthr.propose is True
    bike = proposal(dtos, "bike", "lthr")
    assert bike.current == 165.0 and bike.estimate == 170.0 and bike.propose is True


def test_proposals_carry_garmin_values_for_run_only(session):
    dtos = svc.get_threshold_proposals(session, today=TODAY)
    speed = proposal(dtos, "run", "threshold_speed")
    assert speed.garmin_lthr == 171.0
    assert speed.garmin_lt_speed == pytest.approx(3.6)  # Garmin's 0.36 is in units of 10 m/s (guess)
    assert speed.garmin_vo2max == pytest.approx(52.4)
    bike = proposal(dtos, "bike", "lthr")
    assert (bike.garmin_lthr, bike.garmin_lt_speed, bike.garmin_vo2max) == (None, None, None)


@pytest.mark.parametrize(
    ("lactate", "max_metrics", "expected"),
    [
        (
            {"speed_and_heart_rate": {"heartRate": 168, "speed": 3.4}},
            [{"generic": {"vo2MaxValue": 50}}],
            (168.0, 3.4, 50.0),
        ),
        (
            {"speed_and_heart_rate": {"heartRate": None, "speed": "fast"}},
            {"generic": {"vo2MaxPreciseValue": 49.5}},
            (None, None, 49.5),
        ),
        (
            {"speed_and_heart_rate": {"heartRate": 500, "speed": 99}},
            [{"generic": {"vo2MaxValue": 500}}],
            (None, None, None),
        ),
        ([1, 2, 3], [], (None, None, None)),
        ({"unexpected": True}, "garbage", (None, None, None)),
        (None, None, (None, None, None)),
    ],
)
def test_garmin_values_are_defensive(session, lactate, max_metrics, expected):
    kinds = [raw_kinds.LACTATE_THRESHOLD, raw_kinds.MAX_METRICS]
    for row in session.execute(select(RawGarmin).where(RawGarmin.kind.in_(kinds))).scalars():
        session.delete(row)
    session.commit()
    repo.store_raw(session, raw_kinds.LACTATE_THRESHOLD, "2026-09-15", lactate)
    repo.store_raw(session, raw_kinds.MAX_METRICS, "2026-09-15", max_metrics)
    speed = proposal(svc.get_threshold_proposals(session, today=TODAY), "run", "threshold_speed")
    assert (speed.garmin_lthr, speed.garmin_lt_speed, speed.garmin_vo2max) == expected


def test_garmin_values_use_the_latest_payload_with_data(session):
    empty = {"speed_and_heart_rate": {}}
    repo.store_raw(session, raw_kinds.LACTATE_THRESHOLD, "2026-09-16", empty)  # newest, no values
    repo.store_raw(
        session, raw_kinds.LACTATE_THRESHOLD, "2026-09-10", {"speed_and_heart_rate": {"heartRate": 166}}
    )
    session.commit()
    speed = proposal(svc.get_threshold_proposals(session, today=TODAY), "run", "threshold_speed")
    assert speed.garmin_lthr == 171.0  # 2026-09-15 is newer than 09-10 and has data


def test_proposals_without_data(empty_session):
    assert svc.get_threshold_proposals(empty_session, today=TODAY) == []


def test_proposals_without_a_current_threshold_are_always_proposed(session):
    for row in session.execute(select(Threshold)).scalars():
        row.valid_from = dt.date(2030, 1, 1)  # nothing valid today (rows are referenced by activity metrics)
        session.add(row)
    session.commit()
    dtos = svc.get_threshold_proposals(session, today=TODAY)
    assert dtos and all(p.propose and p.current is None and p.change is None for p in dtos)


# --- apply_proposal -----------------------------------------------------------------------------------------


def stored(session, sport):
    session.expire_all()
    return session.execute(
        select(Threshold).where(Threshold.sport == sport, Threshold.valid_from == TODAY)
    ).scalar_one()


def test_apply_lthr_proposal_keeps_the_current_pace(session):
    dto = svc.apply_proposal(session, sport="run", field="lthr", today=TODAY)
    assert (dto.valid_from, dto.source, dto.lthr, dto.threshold_speed) == (TODAY, "proposal", 140.0, 3.5)
    row = stored(session, "run")
    assert (row.source, row.lthr, row.threshold_speed) == ("proposal", 140.0, 3.5)
    older = select(Threshold).where(Threshold.sport == "run", Threshold.valid_from < TODAY)
    old = session.execute(older).scalar_one()  # the history is kept
    assert old.lthr == 170.0 and old.source == "manual"


def test_apply_speed_proposal_keeps_the_current_lthr(session):
    dto = svc.apply_proposal(session, sport="run", field="threshold_speed", today=TODAY)
    assert (dto.source, dto.lthr) == ("proposal", 170.0)
    assert dto.threshold_speed == pytest.approx(3.5, abs=0.01)


def test_apply_bike_proposal(session):
    dto = svc.apply_proposal(session, sport="bike", field="lthr", today=TODAY)
    assert (dto.sport, dto.lthr, dto.threshold_speed, dto.source) == ("bike", 170.0, None, "proposal")


def test_apply_unknown_proposal_is_invalid(session, empty_session):
    with pytest.raises(InvalidInputError, match="no lthr proposal"):
        svc.apply_proposal(empty_session, sport="run", field="lthr", today=TODAY)
    with pytest.raises(InvalidInputError):
        svc.apply_proposal(session, sport="bike", field="threshold_speed", today=TODAY)


def test_apply_speed_proposal_needs_an_lthr(session):
    for row in session.execute(select(Threshold).where(Threshold.sport == "run")).scalars():
        row.lthr = None
        session.add(row)
    session.commit()
    with pytest.raises(InvalidInputError, match="LTHR"):
        svc.apply_proposal(session, sport="run", field="threshold_speed", today=TODAY)


def test_threshold_source_defaults_to_manual_and_is_validated(session):
    data = ThresholdIn(sport="run", valid_from=TODAY, lthr=171.0, threshold_speed=3.5)
    assert settings_svc.add_threshold(session, data, today=TODAY).source == "manual"
    bad = ThresholdIn(sport="run", valid_from=TODAY, lthr=171.0, source="magic")
    with pytest.raises(InvalidInputError, match="source"):
        settings_svc.add_threshold(session, bad, today=TODAY)
