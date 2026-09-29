"""services/activities.py against the seeded scenario DB (tests/seeding.py)."""

import datetime as dt

import numpy as np
import pytest
from sqlmodel import Session

from training import pipeline
from training.db import repo
from training.db.session import make_engine
from training.garmin import endpoints as ep
from training.services import activities as svc
from training.services.dto import SubjectiveIn
from training.services.errors import InvalidInputError, NotFoundError

from .seeding import BIKE_ID, BIKE_LTHR, HIKE_ID, RUN_ID, RUN_LTHR, RUN_SPEED, add_activity, aid, seeded_db


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(seeded_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


# --- list ---------------------------------------------------------------------------------------------------


def test_list_is_newest_first_with_total(session):
    dto = svc.list_activities(session)
    assert dto.total == 17 and dto.page == 1 and dto.page_size == 50
    assert len(dto.items) == 17
    assert dto.items[0].garmin_id == BIKE_ID + 7 and dto.items[0].local_date == dt.date(2026, 9, 16)
    starts = [i.start_utc for i in dto.items]
    assert starts == sorted(starts, reverse=True)


def test_list_filters_by_dates_and_sport(session):
    days = svc.list_activities(session, date_from=dt.date(2026, 8, 1), date_to=dt.date(2026, 8, 10))
    assert sorted(i.garmin_id for i in days.items) == sorted([RUN_ID + 1, BIKE_ID + 1, HIKE_ID, RUN_ID + 2])
    only_from = svc.list_activities(session, date_from=dt.date(2026, 9, 14))
    assert sorted(i.garmin_id for i in only_from.items) == [RUN_ID + 7, BIKE_ID + 7]
    assert svc.list_activities(session, date_to=dt.date(2026, 7, 27)).total == 1
    assert svc.list_activities(session, sport="run").total == 8
    assert {i.sport for i in svc.list_activities(session, sport="bike").items} == {"bike"}
    assert svc.list_activities(session, sport="other").items[0].garmin_id == HIKE_ID
    assert svc.list_activities(session, sport="run", date_from=dt.date(2026, 9, 1)).total == 2
    assert svc.list_activities(session, date_from=dt.date(2026, 9, 20)).items == []


def test_list_paging_covers_everything_once(session):
    pages = [svc.list_activities(session, page=p, page_size=5) for p in (1, 2, 3, 4, 5)]
    assert [len(p.items) for p in pages] == [5, 5, 5, 2, 0]
    assert all(p.total == 17 and p.page_size == 5 for p in pages)
    ids = [i.id for p in pages for i in p.items]
    assert len(ids) == len(set(ids)) == 17


@pytest.mark.parametrize(
    "kwargs",
    [{"sport": "swim"}, {"page": 0}, {"page_size": 0}, {"page_size": svc.MAX_PAGE_SIZE + 1}],
)
def test_list_rejects_bad_arguments(session, kwargs):
    with pytest.raises(InvalidInputError):
        svc.list_activities(session, **kwargs)


def test_list_items_carry_the_metrics(session):
    run = next(i for i in svc.list_activities(session, sport="run").items if i.garmin_id == RUN_ID)
    assert run.load_method == "rtss" and run.load_primary == pytest.approx(100 / 3, abs=0.01)
    assert run.hrtss == pytest.approx(100 / 3, abs=0.01) and run.rtss is not None
    assert run.hr_coverage == 1.0 and run.low_confidence is False
    assert run.garmin_training_load == 40.0 and run.tz == "Europe/Bratislava"
    assert run.duration_s == 1200.0 and run.distance_m == pytest.approx(RUN_SPEED * 1200)
    bike = next(i for i in svc.list_activities(session, sport="bike").items if i.garmin_id == BIKE_ID)
    assert bike.load_method == "hrtss" and bike.rtss is None and bike.if_hr == pytest.approx(1.0)


def test_activity_without_metrics_lists_with_nulls(session):
    add_activity(session, 999, dt.date(2026, 9, 17))  # nothing recomputed yet
    item = svc.list_activities(session).items[0]
    assert item.garmin_id == 999 and item.load_primary is None and item.hr_coverage is None
    assert item.low_confidence is False


# --- detail -------------------------------------------------------------------------------------------------


def test_detail_hr_and_pace_zones_use_the_bounds_of_the_threshold(session):
    dto = svc.get_activity(session, aid(session, RUN_ID))
    assert dto.summary.garmin_id == RUN_ID and dto.subjective is None
    assert dto.threshold is not None and dto.threshold.lthr == RUN_LTHR
    assert dto.threshold.threshold_speed == RUN_SPEED and dto.threshold.source == "manual"
    z4 = dto.hr_zones[3]
    assert [z.zone for z in dto.hr_zones] == [1, 2, 3, 4, 5]
    assert (z4.seconds, z4.share) == (1200, 1.0)  # exactly at LTHR → Z4 (METRICS §1)
    assert z4.lower == pytest.approx(0.95 * RUN_LTHR) and z4.upper == pytest.approx(1.05 * RUN_LTHR)
    assert dto.hr_zones[0].lower is None and dto.hr_zones[4].upper is None
    assert sum(z.seconds for z in dto.hr_zones) == 1200
    assert dto.pace_zones is not None
    p4 = dto.pace_zones[3]
    assert p4.seconds == 1200
    assert p4.lower == pytest.approx(0.95 * RUN_SPEED) and p4.upper == pytest.approx(1.05 * RUN_SPEED)


def test_detail_bike_has_hr_zones_of_the_bike_threshold_and_no_pace_zones(session):
    dto = svc.get_activity(session, aid(session, BIKE_ID))
    assert dto.pace_zones is None
    assert dto.threshold is not None and dto.threshold.sport == "bike"
    assert dto.hr_zones[3].lower == pytest.approx(0.95 * BIKE_LTHR)


def test_detail_uses_the_threshold_that_was_valid_at_the_activity_date(session):
    pipeline.set_threshold(
        session, sport="bike", valid_from=dt.date(2026, 9, 1), lthr=180.0, end=dt.date(2026, 9, 16)
    )
    early = svc.get_activity(session, aid(session, BIKE_ID)).threshold
    late = svc.get_activity(session, aid(session, BIKE_ID + 7)).threshold
    assert early is not None and early.lthr == BIKE_LTHR
    assert late is not None and late.lthr == 180.0 and late.valid_from == dt.date(2026, 9, 1)


def test_detail_without_a_threshold_has_no_zones(session):
    add_activity(session, 998, dt.date(2025, 12, 31), sport="bike")  # before every valid_from
    pipeline.recompute(session, renormalize=False, end=dt.date(2026, 9, 16))
    dto = svc.get_activity(session, aid(session, 998))
    assert dto.threshold is None and dto.hr_zones == [] and dto.pace_zones is None
    assert dto.summary.load_primary is None


def test_detail_without_metrics_still_resolves_the_threshold(session):
    add_activity(session, 997, dt.date(2026, 9, 17), sport="bike")
    dto = svc.get_activity(session, aid(session, 997))
    assert dto.threshold is not None and dto.threshold.lthr == BIKE_LTHR
    assert dto.hr_zones == [] and dto.summary.load_primary is None


def test_detail_of_unknown_activity_is_not_found(session):
    with pytest.raises(NotFoundError):
        svc.get_activity(session, 123456)


def test_laps_come_from_the_raw_splits_payload_defensively(session):
    activity_id = aid(session, RUN_ID)
    assert svc.get_activity(session, activity_id).laps == []  # nothing stored
    payload = {
        "activityId": RUN_ID,
        "lapDTOs": [
            {
                "lapIndex": 1,
                "duration": 600.5,
                "distance": 2100.0,
                "averageHR": 150.0,
                "maxHR": 161,
                "averageSpeed": 3.5,
                "elevationGain": 12.0,
            },
            "garbage",
            {"duration": "n/a", "distance": True, "averageHR": float("nan"), "averageSpeed": 3.0},
        ],
    }
    repo.store_raw(session, ep.LAPS, str(RUN_ID), payload)
    session.commit()
    laps = svc.get_activity(session, activity_id).laps
    assert [lap.index for lap in laps] == [1, 2]  # 1-based, non-dict entries skipped
    assert laps[0].duration_s == 600.5 and laps[0].max_hr == 161.0 and laps[0].elev_gain_m == 12.0
    assert laps[1].duration_s is None and laps[1].distance_m is None and laps[1].avg_hr is None
    assert laps[1].avg_speed == 3.0 and laps[1].max_hr is None
    for bad in (None, [], {"lapDTOs": None}, {"other": 1}):
        repo.store_raw(session, ep.LAPS, str(RUN_ID), bad)
        assert svc.get_activity(session, activity_id).laps == []


# --- subjective ---------------------------------------------------------------------------------------------


def test_save_subjective_is_an_upsert_per_activity_dated_at_the_activity(session):
    activity_id = aid(session, RUN_ID + 3)
    first = svc.save_subjective(session, activity_id, SubjectiveIn(rpe=6, feel=4, soreness=1, notes="ok"))
    assert first.date == dt.date(2026, 8, 17) and first.activity_id == activity_id
    assert (first.rpe, first.feel, first.soreness, first.notes) == (6, 4, 1, "ok")
    second = svc.save_subjective(session, activity_id, SubjectiveIn(rpe=8))
    assert second.id == first.id  # same row
    assert (second.rpe, second.feel, second.soreness, second.notes) == (8, None, None, None)  # replaced
    detail = svc.get_activity(session, activity_id)
    assert detail.subjective == second
    other = svc.save_subjective(session, aid(session, RUN_ID + 4), SubjectiveIn(rpe=3))
    assert other.id != first.id
    assert svc.get_activity(session, aid(session, RUN_ID)).subjective is None


def test_save_subjective_for_unknown_activity_is_not_found(session):
    with pytest.raises(NotFoundError):
        svc.save_subjective(session, 123456, SubjectiveIn(rpe=5))


# --- streams ------------------------------------------------------------------------------------------------


def test_streams_default_fields_and_shape(session):
    dto = svc.get_streams(session, aid(session, RUN_ID))
    assert list(dto.series) == ["hr", "speed", "alt"]
    assert dto.source_points == 1200 and dto.points == 1200  # fewer than 1500 → nothing dropped
    assert dto.t == list(range(1200))
    assert all(len(v) == dto.points for v in dto.series.values())
    assert dto.series["hr"][0] == RUN_LTHR and dto.series["speed"][10] == RUN_SPEED
    assert dto.series["alt"][5] == 150.0


def test_streams_are_downsampled_keeping_ends_and_the_spike(session):
    hr = np.full(3000, 150.0) + 5 * np.sin(np.arange(3000) / 60)
    hr[1777] = 200.0
    activity_id = add_activity(session, 950, dt.date(2026, 9, 17), hr=hr, seconds=3000)
    dto = svc.get_streams(session, activity_id, ["hr"], points=100)
    assert dto.source_points == 3000 and 3 <= dto.points <= 100
    assert dto.t[0] == 0 and dto.t[-1] == 2999 and dto.t == sorted(set(dto.t))
    assert len(dto.series["hr"]) == dto.points
    assert dto.series["hr"][dto.t.index(1777)] == 200.0


def test_streams_share_one_time_axis_and_split_the_budget(session):
    dto = svc.get_streams(
        session, aid(session, RUN_ID), ["hr", "speed", "alt", "cadence", "distance"], points=90
    )
    assert dto.points <= 90
    assert all(len(v) == dto.points for v in dto.series.values())
    assert dto.series["distance"][-1] == pytest.approx(RUN_SPEED * 1199)


def test_derived_gap_speed_and_grade_come_from_preprocess(session):
    n = 400
    climb = 150.0 + 0.1 * np.arange(n)  # +0.1 m/s at 3.5 m/s → grade ≈ 2.86 %
    activity_id = add_activity(session, 951, dt.date(2026, 9, 17), seconds=n, alt=climb)
    dto = svc.get_streams(session, activity_id, ["speed", "gap_speed", "grade"], points=2000)
    mid = dto.t.index(200)
    assert dto.series["grade"][mid] == pytest.approx(0.1 / RUN_SPEED, abs=1e-3)
    assert dto.series["gap_speed"][mid] > dto.series["speed"][mid]  # uphill: equivalent flat pace is faster
    flat = svc.get_streams(session, aid(session, RUN_ID), ["speed", "gap_speed", "grade"])
    assert flat.series["gap_speed"][600] == pytest.approx(RUN_SPEED)  # flat run: GAP == speed
    assert flat.series["grade"][600] == pytest.approx(0.0)


def test_derived_fields_are_null_in_paused_seconds_but_the_time_axis_keeps_them(session):
    moving = np.ones(600, dtype=bool)
    moving[300:400] = False
    activity_id = add_activity(session, 952, dt.date(2026, 9, 17), seconds=600, moving=moving)
    dto = svc.get_streams(session, activity_id, ["hr", "gap_speed", "grade"], points=2000)
    assert dto.t == list(range(600)) and dto.points == 600
    at = dto.t.index(350)
    assert dto.series["hr"][at] == RUN_LTHR
    assert dto.series["gap_speed"][at] is None and dto.series["grade"][at] is None
    assert dto.series["gap_speed"][dto.t.index(100)] is not None


def test_missing_channels_are_null_and_empty_streams_are_empty(session):
    no_alt = add_activity(session, 953, dt.date(2026, 9, 17), alt=np.nan)
    dto = svc.get_streams(session, no_alt, ["alt", "hr"])
    assert set(dto.series["alt"]) == {None} and dto.series["hr"][0] == RUN_LTHR
    no_rows = add_activity(session, 954, dt.date(2026, 9, 17), seconds=10)
    repo.replace_streams(session, no_rows, pipeline.load_streams(session, no_rows).iloc[0:0])
    session.commit()
    empty = svc.get_streams(session, no_rows, ["hr", "gap_speed"])
    assert (empty.points, empty.source_points, empty.t) == (0, 0, [])
    assert empty.series == {"hr": [], "gap_speed": []}


def test_streams_validate_fields_points_and_activity(session):
    activity_id = aid(session, RUN_ID)
    with pytest.raises(InvalidInputError, match="bogus"):
        svc.get_streams(session, activity_id, ["hr", "bogus"])
    for points in (2, svc.MAX_POINTS + 1):
        with pytest.raises(InvalidInputError):
            svc.get_streams(session, activity_id, points=points)
    with pytest.raises(NotFoundError):
        svc.get_streams(session, 123456)
    assert list(svc.get_streams(session, activity_id, ["speed", "hr", "speed"]).series) == ["speed", "hr"]
    assert set(svc.STREAM_FIELDS) == {"hr", "speed", "gap_speed", "alt", "grade", "cadence", "distance"}
