"""normalize_wellness against synthetic sleep / user summary / RHR / stress / body-battery payloads.

Synthetic day 2026-09-28 (Europe/Bratislava, UTC+2): sleep 20:45Z → 04:30Z, body battery sampled every
15 min at :03/:18/:33/:48 UTC, 88 at 04:33Z and 90 at 04:48Z, day minimum 19; 2026-09-27 minimum 12.
"""

import copy
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from training.normalize.wellness import WELLNESS_COLUMNS, epoch_ms_to_utc, normalize_wellness

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
DAY = date(2026, 9, 28)

CONTRACT_KEYS = [
    "date", "sleep_start", "sleep_end", "sleep_s", "deep_s", "light_s", "rem_s", "awake_s", "sleep_score",
    "rhr", "body_battery_wake", "body_battery_min", "stress_avg", "steps", "weight_kg",
]  # fmt: skip

EXPECTED = {
    "date": DAY,
    "sleep_start": datetime(2026, 9, 27, 20, 45, tzinfo=UTC),
    "sleep_end": datetime(2026, 9, 28, 4, 30, tzinfo=UTC),
    "sleep_s": 25500,
    "deep_s": 5400,
    "light_s": 13500,
    "rem_s": 6600,
    "awake_s": 2400,
    "sleep_score": 81,
    "rhr": 47,
    "body_battery_wake": 88,
    "body_battery_min": 19,
    "stress_avg": 26,
    "steps": 11873,
    "weight_kg": None,
}


def load(name: str) -> Any:
    data = json.loads((SYNTHETIC / name).read_text())
    data.pop("_synthetic", None)
    return data


@pytest.fixture
def payloads() -> dict[str, Any]:
    return {
        "sleep": load("wellness_sleep.json"),
        "user_summary": load("wellness_user_summary.json"),
        "rhr": load("wellness_rhr.json"),
        "stress": load("wellness_stress.json"),
        "body_battery": load("wellness_body_battery.json")["entries"],
    }


def ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def test_contract_keys():
    assert WELLNESS_COLUMNS == CONTRACT_KEYS


def test_full_day_mapping(payloads):
    row = normalize_wellness(DAY, **payloads)
    assert list(row) == CONTRACT_KEYS
    assert row == EXPECTED


def test_sleep_uses_gmt_timestamps_as_aware_utc(payloads):
    dto = payloads["sleep"]["dailySleepDTO"]
    dto["sleepStartTimestampLocal"] += 3_600_000  # a double-offset Local value must not leak in
    row = normalize_wellness(DAY, sleep=payloads["sleep"])
    assert row["sleep_start"] == datetime(2026, 9, 27, 20, 45, tzinfo=UTC)
    assert row["sleep_start"].tzinfo is UTC and row["sleep_end"].tzinfo is UTC
    assert row["sleep_end"] - row["sleep_start"] == timedelta(seconds=row["sleep_s"] + row["awake_s"])


def test_epoch_ms_to_utc():
    assert epoch_ms_to_utc(1_789_880_400_000) == datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    assert epoch_ms_to_utc(1_789_880_400_000.0) == datetime(2026, 9, 20, 5, 0, tzinfo=UTC)
    for bad in (None, "1790226000000", True, 0, -5, float("nan"), 1e30):
        assert epoch_ms_to_utc(bad) is None, bad


def test_rhr_precedence(payloads):
    payloads["rhr"]["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"][0]["value"] = 45.0
    payloads["user_summary"]["restingHeartRate"] = 46
    payloads["sleep"]["restingHeartRate"] = 48
    assert normalize_wellness(DAY, **payloads)["rhr"] == 45
    payloads["rhr"] = None
    assert normalize_wellness(DAY, **payloads)["rhr"] == 46
    payloads["user_summary"]["restingHeartRate"] = None
    assert normalize_wellness(DAY, **payloads)["rhr"] == 48


def test_rhr_entry_for_another_date_is_ignored(payloads):
    entries = payloads["rhr"]["allMetrics"]["metricsMap"]["WELLNESS_RESTING_HEART_RATE"]
    entries[0]["calendarDate"] = "2026-09-27"
    entries[0]["value"] = 60.0
    assert normalize_wellness(DAY, rhr=payloads["rhr"])["rhr"] is None
    entries.append({"calendarDate": "2026-09-28", "value": 44.4})
    assert normalize_wellness(DAY, rhr=payloads["rhr"])["rhr"] == 44


@pytest.mark.parametrize("no_data", [-1, -2])
def test_negative_stress_is_none_with_summary_fallback(payloads, no_data):
    payloads["stress"]["avgStressLevel"] = no_data
    assert normalize_wellness(DAY, **payloads)["stress_avg"] == 26  # user_summary.averageStressLevel
    payloads["user_summary"]["averageStressLevel"] = no_data
    assert normalize_wellness(DAY, **payloads)["stress_avg"] is None


def test_stress_payload_preferred(payloads):
    payloads["stress"]["avgStressLevel"] = 31
    assert normalize_wellness(DAY, **payloads)["stress_avg"] == 31


def test_body_battery_wake_from_array(payloads):
    del payloads["user_summary"]["bodyBatteryAtWakeTime"]
    assert normalize_wellness(DAY, **payloads)["body_battery_wake"] == 88  # sample at 04:33Z


@pytest.mark.parametrize(
    ("wake", "expected"),
    [
        (datetime(2026, 9, 28, 4, 33, tzinfo=UTC), 88),  # exactly on a sample
        (datetime(2026, 9, 28, 4, 34, tzinfo=UTC), 90),  # next sample 04:48Z
        (datetime(2026, 9, 28, 21, 49, tzinfo=UTC), None),  # after the last sample of the day
    ],
)
def test_body_battery_wake_first_sample_at_or_after_sleep_end(payloads, wake, expected):
    del payloads["user_summary"]["bodyBatteryAtWakeTime"]
    payloads["sleep"]["dailySleepDTO"]["sleepEndTimestampGMT"] = ms(wake)
    assert normalize_wellness(DAY, **payloads)["body_battery_wake"] == expected


def test_body_battery_wake_needs_sample_within_60_min(payloads):
    del payloads["user_summary"]["bodyBatteryAtWakeTime"]
    entry = payloads["body_battery"][1]
    wake = ms(datetime(2026, 9, 28, 4, 30, tzinfo=UTC))
    entry["bodyBatteryValuesArray"] = [
        r for r in entry["bodyBatteryValuesArray"] if not wake <= r[0] < wake + 3_660_000
    ]
    assert normalize_wellness(DAY, **payloads)["body_battery_wake"] is None
    entry["bodyBatteryValuesArray"].append([wake + 3_600_000, "MEASURED", 77, 2.0])  # exactly 60 min later
    assert normalize_wellness(DAY, **payloads)["body_battery_wake"] == 77


def test_body_battery_wake_without_sleep_or_array(payloads):
    del payloads["user_summary"]["bodyBatteryAtWakeTime"]
    no_sleep = normalize_wellness(
        DAY, user_summary=payloads["user_summary"], body_battery=payloads["body_battery"]
    )
    assert no_sleep["body_battery_wake"] is None
    assert normalize_wellness(DAY, sleep=payloads["sleep"])["body_battery_wake"] is None


def test_body_battery_min_prefers_array(payloads):
    payloads["user_summary"]["bodyBatteryLowestValue"] = 99
    assert normalize_wellness(DAY, **payloads)["body_battery_min"] == 19
    assert normalize_wellness(DAY, **(payloads | {"body_battery": None}))["body_battery_min"] == 99


def test_body_battery_entry_selected_by_date(payloads):
    row = normalize_wellness(date(2026, 9, 27), body_battery=payloads["body_battery"])
    assert row["body_battery_min"] == 12
    other_day = normalize_wellness(date(2026, 9, 29), body_battery=payloads["body_battery"])
    assert other_day["body_battery_min"] is None


def test_body_battery_single_dict_entry(payloads):
    entry = payloads["body_battery"][1]
    assert normalize_wellness(DAY, body_battery=entry)["body_battery_min"] == 19
    assert normalize_wellness(date(2026, 9, 27), body_battery=entry)["body_battery_min"] is None


def test_body_battery_columns_mapped_by_descriptor_not_position(payloads):
    del payloads["user_summary"]["bodyBatteryAtWakeTime"]
    reference = normalize_wellness(DAY, **payloads)
    reordered = copy.deepcopy(payloads)
    entry = reordered["body_battery"][1]
    # new layout: [version, level, timestamp, status]; descriptor list also shuffled
    entry["bodyBatteryValuesArray"] = [[v, lvl, ts, st] for ts, st, lvl, v in entry["bodyBatteryValuesArray"]]
    entry["bodyBatteryValueDescriptorDTOList"] = [
        {"bodyBatteryValueDescriptorIndex": 1, "bodyBatteryValueDescriptorKey": "bodyBatteryLevel"},
        {"bodyBatteryValueDescriptorIndex": 3, "bodyBatteryValueDescriptorKey": "bodyBatteryStatus"},
        {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "bodyBatteryVersion"},
        {"bodyBatteryValueDescriptorIndex": 2, "bodyBatteryValueDescriptorKey": "timestamp"},
    ]
    assert normalize_wellness(DAY, **reordered) == reference


def test_body_battery_without_descriptors_assumes_timestamp_level(payloads):
    del payloads["user_summary"]["bodyBatteryAtWakeTime"]
    entry = payloads["body_battery"][1]
    del entry["bodyBatteryValueDescriptorDTOList"]
    entry["bodyBatteryValuesArray"] = [[ts, lvl] for ts, _, lvl, _ in entry["bodyBatteryValuesArray"]]
    row = normalize_wellness(DAY, **payloads)
    assert row["body_battery_wake"] == 88 and row["body_battery_min"] == 19


def test_body_battery_descriptors_without_level_key(payloads):
    entry = payloads["body_battery"][1]
    entry["bodyBatteryValueDescriptorDTOList"] = [
        {"bodyBatteryValueDescriptorIndex": 0, "bodyBatteryValueDescriptorKey": "timestamp"}
    ]
    payloads["user_summary"]["bodyBatteryLowestValue"] = 21
    assert normalize_wellness(DAY, **payloads)["body_battery_min"] == 21


def test_day_without_data_is_all_none():
    row = normalize_wellness(DAY)
    assert row == {"date": DAY} | dict.fromkeys(CONTRACT_KEYS[1:])


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sleep": {"dailySleepDTO": None}},
        {"sleep": {"dailySleepDTO": {"sleepScores": {"overall": None}}}},
        {"sleep": []},
        {"rhr": {"allMetrics": None}},
        {"rhr": {"allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": None}}}},
        {"stress": {"avgStressLevel": None}},
        {"user_summary": {"totalSteps": None, "restingHeartRate": 0}},
        {"body_battery": "junk"},
        {"body_battery": [None, 3, {"date": "2026-09-28", "bodyBatteryValuesArray": [None, [1], "x"]}]},
        {"body_battery": {"date": "2026-09-28", "bodyBatteryValuesArray": None}},
    ],
)
def test_malformed_payloads_never_raise(kwargs):
    row = normalize_wellness(DAY, **kwargs)
    assert row == {"date": DAY} | dict.fromkeys(CONTRACT_KEYS[1:])


def test_inputs_not_mutated(payloads):
    before = copy.deepcopy(payloads)
    normalize_wellness(DAY, **payloads)
    assert payloads == before
