"""services/settings.py: settings DTO, historical thresholds, athlete updates."""

import datetime as dt
from itertools import pairwise

import pytest
from sqlalchemy import func, select
from sqlmodel import Session

from training import pipeline
from training.db import repo
from training.db.models import DailyLoad, Threshold
from training.db.session import make_engine, migrate
from training.services import settings as svc
from training.services.dto import AthleteIn, ThresholdIn
from training.services.errors import InvalidInputError

from .seeding import BIKE_ID, BIKE_LTHR, HIKE_ID, RUN_ID, RUN_LTHR, RUN_SPEED, TODAY, metric_of, seeded_db


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def empty(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = make_engine(path)
    with Session(engine) as s:
        yield s
    engine.dispose()


def n_thresholds(session: Session) -> int:
    return session.execute(select(func.count()).select_from(Threshold)).scalar_one()


# --- get_settings -------------------------------------------------------------------------------------------


def test_settings_of_the_seeded_athlete(session):
    dto = svc.get_settings(session, today=TODAY)
    a = dto.athlete
    assert a is not None and (a.sex, a.max_hr, a.rest_hr_override, a.rest_hr_current) == (
        "male",
        190.0,
        50.0,
        50.0,
    )
    assert a.birth_year is None and a.weight_kg is None and a.run_bike_split is None
    assert [(t.sport, t.valid_from) for t in dto.thresholds] == [
        ("bike", dt.date(2026, 1, 1)),
        ("run", dt.date(2026, 1, 1)),
    ]
    assert dto.current["run"] is not None and dto.current["run"].lthr == RUN_LTHR
    assert dto.current["bike"] is not None and dto.current["bike"].lthr == BIKE_LTHR
    assert dto.thresholds[1].zones == {"hr": [0.68, 0.84, 0.95, 1.05], "pace": [0.78, 0.88, 0.95, 1.05]}


def test_zone_bounds_are_absolute_bpm_and_m_per_s(session):
    dto = svc.get_settings(session, today=TODAY)
    run = dto.hr_zones["run"]
    assert [z.zone for z in run] == [1, 2, 3, 4, 5]
    assert run[0].lower is None and run[0].upper == pytest.approx(0.68 * RUN_LTHR)
    assert (run[3].lower, run[3].upper) == (pytest.approx(0.95 * RUN_LTHR), pytest.approx(1.05 * RUN_LTHR))
    assert run[4].lower == pytest.approx(1.05 * RUN_LTHR) and run[4].upper is None
    assert all(a.upper == b.lower for a, b in pairwise(run))  # contiguous
    assert dto.hr_zones["bike"][1].lower == pytest.approx(0.68 * BIKE_LTHR)
    assert dto.pace_zones is not None
    assert dto.pace_zones[0].upper == pytest.approx(0.78 * RUN_SPEED) and dto.pace_zones[
        4
    ].lower == pytest.approx(1.05 * RUN_SPEED)


def test_settings_current_thresholds_depend_on_today(session):
    pipeline.set_threshold(
        session, sport="run", valid_from=dt.date(2026, 9, 1), lthr=175.0, threshold_speed=3.6, end=TODAY
    )
    now = svc.get_settings(session, today=TODAY)
    assert now.current["run"].lthr == 175.0 and now.hr_zones["run"][3].lower == pytest.approx(0.95 * 175.0)
    assert now.pace_zones[3].lower == pytest.approx(0.95 * 3.6)
    assert [t.lthr for t in now.thresholds if t.sport == "run"] == [
        RUN_LTHR,
        175.0,
    ]  # full history, ascending
    before = svc.get_settings(session, today=dt.date(2026, 8, 15))
    assert before.current["run"].lthr == RUN_LTHR
    ancient = svc.get_settings(session, today=dt.date(2025, 6, 1))
    assert (
        ancient.current == {"run": None, "bike": None}
        and ancient.hr_zones == {}
        and ancient.pace_zones is None
    )


def test_settings_of_an_empty_database(empty):
    dto = svc.get_settings(empty, today=TODAY)
    assert dto.athlete is None and dto.thresholds == []
    assert dto.current == {"run": None, "bike": None} and dto.hr_zones == {} and dto.pace_zones is None


def test_bike_only_thresholds_give_no_pace_zones(empty):
    svc.add_threshold(
        empty, ThresholdIn(sport="bike", valid_from=dt.date(2026, 1, 1), lthr=160.0), today=TODAY
    )
    dto = svc.get_settings(empty, today=TODAY)
    assert list(dto.hr_zones) == ["bike"] and dto.pace_zones is None and dto.current["run"] is None


def test_rest_hr_current_is_the_28_day_median_without_an_override(empty):
    pipeline.set_athlete(empty, sex="female")
    for i, rhr in enumerate([50.0, 52.0, 60.0]):
        repo.upsert_wellness(empty, {"date": TODAY - dt.timedelta(days=i), "rhr": rhr})
    repo.upsert_wellness(empty, {"date": TODAY - dt.timedelta(days=40), "rhr": 99.0})  # outside the window
    empty.commit()
    a = svc.get_settings(empty, today=TODAY).athlete
    assert a is not None and a.rest_hr_override is None and a.rest_hr_current == 52.0


# --- add_threshold ------------------------------------------------------------------------------------------


def test_add_threshold_changes_only_activities_from_valid_from_on(session):
    bikes = [BIKE_ID + w for w in range(8)]
    runs = [RUN_ID + w for w in range(8)]
    before = {g: metric_of(session, g).load_primary for g in bikes + runs}
    dto = svc.add_threshold(
        session, ThresholdIn(sport="bike", valid_from=dt.date(2026, 9, 1), lthr=BIKE_LTHR + 15), today=TODAY
    )
    assert (dto.sport, dto.valid_from, dto.lthr, dto.threshold_speed, dto.source) == (
        "bike",
        dt.date(2026, 9, 1),
        BIKE_LTHR + 15,
        None,
        "manual",
    )
    after = {g: metric_of(session, g).load_primary for g in bikes + runs}
    for g in bikes[:5] + runs:  # Wednesdays up to 2026-08-26, and every run
        assert after[g] == before[g], g
    for g in bikes[5:]:  # 2026-09-02, 09-09, 09-16
        assert after[g] < before[g], g
        assert metric_of(session, g).threshold_id_used == dto.id
    assert metric_of(session, bikes[4]).threshold_id_used != dto.id


def test_add_threshold_for_run_with_pace_and_replace_of_the_same_date(session):
    data = ThresholdIn(sport="run", valid_from=dt.date(2026, 9, 1), lthr=172.0, threshold_speed=3.4)
    first = svc.add_threshold(session, data, today=TODAY)
    assert first.threshold_speed == 3.4 and first.zones["hr"] == [0.68, 0.84, 0.95, 1.05]
    count = n_thresholds(session)
    second = svc.add_threshold(session, data.model_copy(update={"lthr": 174.0}), today=TODAY)
    assert (
        second.id == first.id and second.lthr == 174.0 and n_thresholds(session) == count
    )  # replaced, not added


def test_add_threshold_extends_the_pmc_to_today(session):
    svc.add_threshold(
        session,
        ThresholdIn(sport="run", valid_from=dt.date(2026, 9, 1), lthr=172.0),
        today=dt.date(2026, 9, 30),
    )
    last = session.execute(select(DailyLoad.date).order_by(DailyLoad.date.desc())).scalars().first()
    assert last == dt.date(2026, 9, 30)


@pytest.mark.parametrize(("lthr", "speed"), [(40.0, None), (230.0, None), (170.0, 0.5), (170.0, 7.0)])
def test_add_threshold_accepts_the_bounds_of_the_plausible_range(empty, lthr, speed):
    dto = svc.add_threshold(
        empty,
        ThresholdIn(sport="run", valid_from=dt.date(2026, 1, 1), lthr=lthr, threshold_speed=speed),
        today=TODAY,
    )
    assert dto.lthr == lthr and dto.threshold_speed == speed


@pytest.mark.parametrize(
    "data",
    [
        {"sport": "swim", "lthr": 160.0},
        {"sport": "other", "lthr": 160.0},
        {"sport": "bike", "lthr": 160.0, "threshold_speed": 3.0},
        {"sport": "run", "lthr": 39.0},
        {"sport": "run", "lthr": 231.0},
        {"sport": "run", "lthr": 170.0, "threshold_speed": 0.2},
        {"sport": "run", "lthr": 170.0, "threshold_speed": 9.0},
        {"sport": "run", "lthr": 170.0, "threshold_speed": float("inf")},
    ],
)
def test_add_threshold_rejects_bad_input_and_writes_nothing(session, data):
    count = n_thresholds(session)
    with pytest.raises(InvalidInputError):
        svc.add_threshold(session, ThresholdIn(valid_from=dt.date(2026, 9, 1), **data), today=TODAY)
    assert n_thresholds(session) == count


# --- update_athlete -----------------------------------------------------------------------------------------


def test_update_athlete_is_a_partial_update(session):
    dto = svc.update_athlete(session, AthleteIn(weight_kg=71.5, birth_year=1990), today=TODAY)
    assert (dto.weight_kg, dto.birth_year) == (71.5, 1990)
    assert (dto.sex, dto.max_hr, dto.rest_hr_override) == ("male", 190.0, 50.0)  # untouched
    assert svc.get_settings(session, today=TODAY).athlete == dto


def test_update_athlete_recomputes_only_for_trimp_inputs(session, monkeypatch):
    calls: list[dict] = []
    real = pipeline.recompute
    monkeypatch.setattr(pipeline, "recompute", lambda s, **kw: calls.append(kw) or real(s, **kw))
    svc.update_athlete(session, AthleteIn(weight_kg=70.0, run_bike_split=0.6), today=TODAY)
    assert calls == []
    svc.update_athlete(session, AthleteIn(max_hr=200.0), today=TODAY)
    assert calls == [{"renormalize": False, "end": TODAY}]


def test_update_athlete_changes_trimp_norm_of_existing_activities(session):
    """The hike (0.7 × LTHR) is not at the reference intensity, so its TRIMP_norm depends on max/rest HR."""
    before = metric_of(session, HIKE_ID).trimp_norm
    assert before is not None
    svc.update_athlete(session, AthleteIn(max_hr=205.0), today=TODAY)
    after = metric_of(session, HIKE_ID).trimp_norm
    assert after is not None and after != pytest.approx(before)
    svc.update_athlete(session, AthleteIn(rest_hr_override=60.0), today=TODAY)
    assert metric_of(session, HIKE_ID).trimp_norm != pytest.approx(after)


def test_update_athlete_creates_the_row_and_reports_rest_hr(empty):
    repo.upsert_wellness(empty, {"date": TODAY, "rhr": 47.0})
    empty.commit()
    dto = svc.update_athlete(empty, AthleteIn(sex="female"), today=TODAY)
    assert dto.sex == "female" and dto.rest_hr_current == 47.0 and dto.max_hr is None


@pytest.mark.parametrize("data", [{}, {"sex": "x"}, {"birth_year": 1899}, {"birth_year": TODAY.year + 1}])
def test_update_athlete_rejects_bad_input(session, data):
    with pytest.raises(InvalidInputError):
        svc.update_athlete(session, AthleteIn(**data), today=TODAY)


def test_empty_update_does_not_create_an_athlete_row(empty):
    with pytest.raises(InvalidInputError):
        svc.update_athlete(empty, AthleteIn(), today=TODAY)
    assert pipeline.get_athlete(empty) is None


def test_clear_rest_hr_override_returns_to_median(session):
    """Settings UI gap: AthleteIn null means "unchanged", so clearing needs an explicit flag."""
    import datetime as _dt

    from training.db import repo as _repo
    from training.services.dto import AthleteIn as _AthleteIn
    from training.services.settings import update_athlete as _update

    today = _dt.date(2026, 9, 29)
    _repo.upsert_wellness(session, {"date": today, "rhr": 51.0})
    session.commit()
    assert _update(session, _AthleteIn(rest_hr_override=44.0), today=today).rest_hr_current == 44.0
    dto = _update(session, _AthleteIn(clear_rest_hr_override=True), today=today)
    assert dto.rest_hr_override is None and dto.rest_hr_current == 51.0


def test_athlete_save_recomputes_only_on_metric_relevant_changes(session, monkeypatch):
    """Review phase 3 W1: the form resends sex/max_hr unchanged – that must not trigger a full recompute."""
    import datetime as _dt

    from training import pipeline as _pipeline
    from training.services.dto import AthleteIn as _AthleteIn
    from training.services.settings import update_athlete as _update

    today = _dt.date(2026, 9, 29)
    calls: list[int] = []
    real = _pipeline.recompute
    monkeypatch.setattr(_pipeline, "recompute", lambda *a, **k: calls.append(1) or real(*a, **k))
    _update(session, _AthleteIn(sex="female", max_hr=183.0), today=today)  # differs from the seeded athlete
    assert len(calls) == 1
    _update(session, _AthleteIn(sex="female", max_hr=183.0, weight_kg=71.0), today=today)
    assert len(calls) == 1  # unchanged sex/max_hr, only weight
    _update(session, _AthleteIn(max_hr=184.0), today=today)
    assert len(calls) == 2


def test_clear_rest_hr_override_on_empty_db_creates_nothing(tmp_path):
    import datetime as _dt

    import pytest as _pytest
    from sqlmodel import Session as _Session

    from training.db.session import make_engine as _make_engine, migrate as _migrate

    _migrate(tmp_path / "empty.db")
    session = _Session(_make_engine(tmp_path / "empty.db"))

    from training import pipeline as _pipeline
    from training.services.dto import AthleteIn as _AthleteIn
    from training.services.errors import InvalidInputError as _Invalid
    from training.services.settings import update_athlete as _update

    with _pytest.raises(_Invalid):
        _update(session, _AthleteIn(clear_rest_hr_override=True), today=_dt.date(2026, 9, 29))
    assert _pipeline.get_athlete(session) is None
