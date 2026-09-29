"""normalize_activity / sport_from_type_key / is_indoor_type against synthetic Garmin payloads."""

import copy
import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from training.normalize.activities import (
    ACTIVITY_FIELDS,
    is_indoor_type,
    normalize_activity,
    sport_from_type_key,
)

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"

CONTRACT_KEYS = [
    "garmin_id", "sport", "sub_sport", "name", "start_utc", "tz", "local_date", "duration_s", "moving_s",
    "distance_m", "elev_gain_m", "avg_hr", "max_hr", "avg_speed", "avg_cadence", "calories", "is_race",
    "is_indoor", "garmin_training_load", "garmin_aerobic_te", "garmin_anaerobic_te", "garmin_vo2max",
]  # fmt: skip

RUN_EXPECTED = {
    "garmin_id": 900000101,
    "sport": "run",
    "sub_sport": "running",
    "name": "anonymized",
    "start_utc": datetime(2026, 9, 20, 5, 0, tzinfo=UTC),
    "tz": "Europe/Bratislava",
    "local_date": date(2026, 9, 20),
    "duration_s": 3021.4,
    "moving_s": 2998.0,
    "distance_m": 10012.3,
    "elev_gain_m": 84.0,
    "avg_hr": 148.0,
    "max_hr": 171.0,
    "avg_speed": 3.314,
    "avg_cadence": 171.4,
    "calories": 712.0,
    "is_race": False,
    "is_indoor": False,
    "garmin_training_load": 118.6,
    "garmin_aerobic_te": 3.2,
    "garmin_anaerobic_te": 1.1,
    "garmin_vo2max": 52.0,
}


def load(name: str) -> dict[str, Any]:
    data = json.loads((SYNTHETIC / name).read_text())
    data.pop("_synthetic", None)
    return data


@pytest.fixture
def run_summary() -> dict[str, Any]:
    return load("activity_run_summary.json")


@pytest.fixture
def run_item() -> dict[str, Any]:
    return load("activity_run_list_item.json")


def test_contract_keys():
    assert list(ACTIVITY_FIELDS) == CONTRACT_KEYS


def test_run_summary_plus_list_item(run_summary, run_item):
    row = normalize_activity(run_summary, run_item)
    assert list(row) == CONTRACT_KEYS
    assert row == RUN_EXPECTED
    assert row["start_utc"].tzinfo is UTC


def test_run_summary_only(run_summary):
    row = normalize_activity(run_summary)
    assert row == RUN_EXPECTED | {"garmin_vo2max": None}  # vO2MaxValue exists only in the list item


def test_run_list_item_only(run_item):
    row = normalize_activity(None, run_item)
    # no IANA name in the list item → offset from startTimeLocal − startTimeGMT
    assert row == RUN_EXPECTED | {"tz": "+02:00"}


def test_summary_wins_and_list_fills_gaps(run_summary, run_item):
    run_summary["summaryDTO"]["averageHR"] = 150.0
    del run_summary["summaryDTO"]["calories"]
    run_summary["summaryDTO"]["maxHR"] = None
    run_item["averageHR"] = 140.0
    run_item["calories"] = 700.0
    run_item["activityName"] = "list name"
    row = normalize_activity(run_summary, run_item)
    assert row["avg_hr"] == 150.0
    assert row["calories"] == 700.0
    assert row["max_hr"] == 171.0
    assert row["name"] == "anonymized"


def test_bike_race_summary_and_list():
    summary, item = load("activity_bike_summary.json"), load("activity_bike_list_item.json")
    for row in (
        normalize_activity(summary, item),
        normalize_activity(summary),
        normalize_activity(None, item),
    ):
        assert row["sport"] == "bike"
        assert row["sub_sport"] == "road_biking"
        assert row["is_race"] is True
        assert row["is_indoor"] is False
        assert row["avg_cadence"] == 87.0
        assert row["avg_speed"] == 10.012
        assert row["garmin_aerobic_te"] == 3.9
        assert row["garmin_vo2max"] is None
        assert row["start_utc"] == datetime(2026, 9, 27, 7, 0, tzinfo=UTC)
        assert row["local_date"] == date(2026, 9, 27)


@pytest.mark.parametrize(
    ("local", "gmt", "tz", "local_date"),
    [
        ("2026-09-20 01:00:00", "2026-09-20 05:00:00", "-04:00", date(2026, 9, 20)),
        ("2026-09-20 10:30:00", "2026-09-20 05:00:00", "+05:30", date(2026, 9, 20)),
        ("2026-09-20 05:00:00", "2026-09-20 05:00:00", "+00:00", date(2026, 9, 20)),
        # 00:30 local on the 21st is still the 20th in UTC: local_date follows the local clock
        ("2026-09-21 00:30:00", "2026-09-20 22:30:00", "+02:00", date(2026, 9, 21)),
        ("2026-09-19 20:00:00", "2026-09-20 01:00:00", "-05:00", date(2026, 9, 19)),
    ],
)
def test_tz_offset_fallback_and_local_date(run_item, local, gmt, tz, local_date):
    run_item["startTimeLocal"], run_item["startTimeGMT"] = local, gmt
    row = normalize_activity(None, run_item)
    assert row["tz"] == tz
    assert row["local_date"] == local_date
    assert row["start_utc"] == datetime.fromisoformat(gmt).replace(tzinfo=UTC)


def test_iana_zone_preferred_over_offset(run_summary, run_item):
    run_summary["timeZoneUnitDTO"] = {"unitKey": "America/New_York"}  # no timeZone → unitKey
    assert normalize_activity(run_summary, run_item)["tz"] == "America/New_York"
    del run_summary["timeZoneUnitDTO"]
    assert normalize_activity(run_summary, run_item)["tz"] == "+02:00"


def test_start_from_begin_timestamp(run_item):
    del run_item["startTimeGMT"]
    row = normalize_activity(None, run_item)
    assert row["start_utc"] == datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    assert row["tz"] is None  # no GMT string to compare the local time with
    assert row["local_date"] == date(2026, 9, 20)


def test_local_date_falls_back_to_utc_date(run_item):
    del run_item["startTimeLocal"]
    row = normalize_activity(None, run_item)
    assert row["local_date"] == date(2026, 9, 20)
    assert row["tz"] is None


def test_aware_gmt_string_is_converted(run_summary):
    run_summary["summaryDTO"]["startTimeGMT"] = "2026-09-20T07:00:00+02:00"
    assert normalize_activity(run_summary)["start_utc"] == datetime(2026, 9, 20, 5, 0, tzinfo=UTC)


def test_minimal_list_item_gives_nones():
    row = normalize_activity(None, {"activityId": 5, "startTimeGMT": "2026-01-02 03:04:05"})
    assert list(row) == CONTRACT_KEYS
    assert row["garmin_id"] == 5
    assert row["sport"] == "other"
    assert row["sub_sport"] is None
    assert row["is_race"] is False and row["is_indoor"] is False
    assert row["local_date"] == date(2026, 1, 2)
    unknown = [k for k in CONTRACT_KEYS if k not in ("garmin_id", "sport", "start_utc", "local_date")]
    unknown = [k for k in unknown if k not in ("is_race", "is_indoor")]
    assert {k: row[k] for k in unknown} == dict.fromkeys(unknown)


def test_garbage_values_become_none(run_summary):
    dto = run_summary["summaryDTO"]
    dto["averageHR"], dto["distance"], dto["calories"] = "148", True, float("nan")
    row = normalize_activity(run_summary)
    assert row["avg_hr"] is None and row["distance_m"] is None and row["calories"] is None


def test_non_numeric_summary_value_falls_back_to_list(run_summary, run_item):
    run_summary["summaryDTO"]["averageHR"] = "n/a"
    assert normalize_activity(run_summary, run_item)["avg_hr"] == 148.0


@pytest.mark.parametrize(
    ("summary", "item"),
    [
        (None, None),
        ({}, {}),
        ({"summaryDTO": {"startTimeGMT": "2026-09-20T05:00:00.0"}}, None),  # no id
        ({"activityId": 1, "summaryDTO": {}}, None),  # no start time
        (None, {"activityId": 1, "startTimeGMT": "not a time"}),
    ],
)
def test_missing_id_or_start_raises(summary, item):
    with pytest.raises(ValueError):
        normalize_activity(summary, item)


def test_inputs_not_mutated(run_summary, run_item):
    before = copy.deepcopy((run_summary, run_item))
    normalize_activity(run_summary, run_item)
    assert (run_summary, run_item) == before


@pytest.mark.parametrize(
    ("type_key", "sport"),
    [
        ("running", "run"),
        ("trail_running", "run"),
        ("treadmill_running", "run"),
        ("track_running", "run"),
        ("virtual_run", "run"),
        ("cycling", "bike"),
        ("road_biking", "bike"),
        ("indoor_cycling", "bike"),
        ("virtual_ride", "bike"),
        ("gravel_cycling", "bike"),
        ("mountain_biking", "bike"),
        ("e_bike_mountain", "bike"),
        ("Road_Biking", "bike"),
        ("motorcycling", "other"),
        ("walking", "other"),
        ("hiking", "other"),
        ("lap_swimming", "other"),
        ("strength_training", "other"),
        ("multi_sport", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_sport_from_type_key(type_key, sport):
    assert sport_from_type_key(type_key) == sport


@pytest.mark.parametrize(
    ("type_key", "indoor"),
    [
        ("treadmill_running", True),
        ("indoor_cycling", True),
        ("virtual_ride", True),
        ("virtual_run", True),
        ("indoor_running", True),
        ("running", False),
        ("trail_running", False),
        ("road_biking", False),
        ("strength_training", False),
        (None, False),
    ],
)
def test_is_indoor_type(type_key, indoor):
    assert is_indoor_type(type_key) is indoor


def test_indoor_flag_in_row(run_item):
    run_item["activityType"] = {"typeKey": "treadmill_running"}
    row = normalize_activity(None, run_item)
    assert row["sport"] == "run" and row["is_indoor"] is True
