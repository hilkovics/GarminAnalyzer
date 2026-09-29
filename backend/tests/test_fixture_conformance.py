"""Sanity of the normalizers against REAL recorded Garmin fixtures (backend/tests/fixtures/*.json).

The files are written by scripts/record_fixtures.py (top level of backend/tests/fixtures/ only):
`activities_list.json`, `activity_NN_<typeKey>_{summary,details}.json`,
`wellness_<date>_{sleep,user_summary,rhr,stress}.json` and `range_<start>_<end>_body_battery.json`.
Every test is parametrized per file / day so a failure names it, and skips while no real fixtures exist.
These checks lock in the Garmin key paths the normalizers had to guess (see STATUS.md "Known issues").
The check functions are also run against the synthetic fixtures so they cannot rot unnoticed.
"""

import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import pandas as pd
import pytest

from training.normalize.activities import ACTIVITY_FIELDS, SPORTS, normalize_activity
from training.normalize.streams import STREAM_COLUMNS, normalize_streams
from training.normalize.wellness import WELLNESS_COLUMNS, normalize_wellness

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC = FIXTURES / "synthetic"
HR_RANGE = (30.0, 250.0)
MAX_AVG_SPEED = {"run": 7.0, "bike": 25.0, "other": 30.0}  # m/s; catches km/h or pace mix-ups
_WELLNESS_NAME = re.compile(r"^wellness_(\d{4}-\d{2}-\d{2})_(sleep|user_summary|rhr|stress)\.json$")
_NO_FIXTURES = "no real Garmin fixtures – run scripts/record_fixtures.py locally and commit them"


def _load(path: Path) -> Any:
    data = json.loads(path.read_text())
    if isinstance(data, dict) and data.get("_synthetic") is True and path.parent == FIXTURES:
        pytest.skip(f"{path.name} is synthetic")
    return data


def _params(values: list[Any], ids: list[str]) -> list[Any]:
    if not values:
        return [pytest.param(None, marks=pytest.mark.skip(reason=_NO_FIXTURES), id="no-real-fixtures")]
    return [pytest.param(v, id=i) for v, i in zip(values, ids, strict=True)]


SUMMARY_FILES = sorted(FIXTURES.glob("activity_*_summary.json"))
DETAIL_FILES = sorted(FIXTURES.glob("activity_*_details.json"))
LIST_FILE = FIXTURES / "activities_list.json"
BB_FILES = sorted(FIXTURES.glob("range_*_body_battery.json"))
WELLNESS_DAYS = sorted(
    {m.group(1) for p in FIXTURES.glob("wellness_*.json") if (m := _WELLNESS_NAME.match(p.name))}
)


def _list_items() -> dict[int, dict[str, Any]]:
    if not LIST_FILE.exists():
        return {}
    items = _load(LIST_FILE)
    return {i["activityId"]: i for i in items if isinstance(i, dict) and "activityId" in i}


def _wellness_payloads(day: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    for kind in ("sleep", "user_summary", "rhr", "stress"):
        path = FIXTURES / f"wellness_{day}_{kind}.json"
        if path.exists():
            kwargs[kind] = _load(path)
    entries: list[Any] = []
    for path in BB_FILES:  # get_body_battery ranges: lists of per-date entries
        data = _load(path)
        entries.extend(data if isinstance(data, list) else [data])
    if entries:
        kwargs["body_battery"] = entries
    return kwargs


# ------------------------------------------------------------------------------------------ checks


def _is_utc(value: Any) -> bool:
    return isinstance(value, datetime) and value.utcoffset() == timedelta(0)


def check_activity_row(row: dict[str, Any]) -> None:
    assert list(row) == list(ACTIVITY_FIELDS)
    assert isinstance(row["garmin_id"], int) and row["garmin_id"] > 0
    assert _is_utc(row["start_utc"]), row["start_utc"]
    assert isinstance(row["local_date"], date)
    assert abs((row["local_date"] - row["start_utc"].date()).days) <= 1
    assert row["sport"] in SPORTS
    assert isinstance(row["sub_sport"], str) and row["sub_sport"], "activityType.typeKey missing"
    assert row["tz"], "neither timeZoneUnitDTO nor a local/GMT start pair"
    assert isinstance(row["is_race"], bool) and isinstance(row["is_indoor"], bool)
    assert row["duration_s"] is not None and row["duration_s"] > 0, "duration missing"
    for key in ("moving_s", "distance_m", "elev_gain_m", "calories", "avg_cadence"):
        assert row[key] is None or row[key] >= 0, key
    for key in ("avg_hr", "max_hr"):
        assert row[key] is None or HR_RANGE[0] <= row[key] <= HR_RANGE[1], (key, row[key])
    if row["avg_hr"] is not None and row["max_hr"] is not None:
        assert row["avg_hr"] <= row["max_hr"]
    if row["avg_speed"] is not None:
        assert 0 <= row["avg_speed"] <= MAX_AVG_SPEED[row["sport"]], row["avg_speed"]
    for key in ("garmin_aerobic_te", "garmin_anaerobic_te"):
        assert row[key] is None or 0 <= row[key] <= 5, (key, row[key])
    assert row["garmin_vo2max"] is None or 20 <= row["garmin_vo2max"] <= 95


def check_streams(df: pd.DataFrame, *, outdoor: bool, activity: dict[str, Any] | None = None) -> None:
    assert list(df.columns) == STREAM_COLUMNS
    if outdoor:
        assert not df.empty, "no streams for an outdoor activity"
    if df.empty:
        return
    t = df["t"].to_numpy()
    assert t[0] == 0 and (np.diff(t) == 1).all(), "t must be a 1 s grid starting at 0"
    assert df["moving"].dtype == bool
    hr = df["hr"].dropna()
    assert hr.between(*HR_RANGE).all(), f"hr outside {HR_RANGE}: {hr[~hr.between(*HR_RANGE)].head().tolist()}"
    assert (df["speed"].dropna() >= 0).all()
    assert df["lat"].dropna().between(-90, 90).all() and df["lon"].dropna().between(-180, 180).all()
    dist = df["distance"].dropna().to_numpy()
    assert (np.diff(dist) >= -1.0).all(), "sumDistance is not cumulative"
    if outdoor:
        assert df["speed"].notna().any(), "no speed (directSpeed / sumDistance) for an outdoor activity"
    if activity is None:
        return
    duration = activity.get("duration_s")
    if duration:  # Garmin `duration` is timer time → the moving flag must add up to it (METRICS §0.2)
        moving = int(df["moving"].sum())
        assert abs(moving - duration) <= max(60.0, 0.05 * duration), (moving, duration)
    distance = activity.get("distance_m")
    if outdoor and distance and len(dist):
        assert abs(dist[-1] - distance) <= max(50.0, 0.03 * distance), (dist[-1], distance)


def check_wellness_row(row: dict[str, Any], day: date) -> None:
    assert list(row) == WELLNESS_COLUMNS
    assert row["date"] == day
    start, end = row["sleep_start"], row["sleep_end"]
    for value in (start, end):
        assert value is None or _is_utc(value), value
    if start is not None and end is not None:
        assert start < end <= start + timedelta(hours=20)
        noon = datetime(day.year, day.month, day.day, 12, tzinfo=UTC)
        assert abs(end - noon) <= timedelta(hours=36), "sleep end far from its calendar day (GMT key?)"
    if row["sleep_s"] is not None:
        assert 0 <= row["sleep_s"] <= 16 * 3600
        stages = [row[k] for k in ("deep_s", "light_s", "rem_s")]
        if row["sleep_s"] > 0 and all(s is not None for s in stages):
            assert abs(sum(stages) - row["sleep_s"]) <= 900, (stages, row["sleep_s"])
    assert row["sleep_score"] is None or 0 <= row["sleep_score"] <= 100
    assert row["rhr"] is None or 25 <= row["rhr"] <= 120, row["rhr"]
    for key in ("body_battery_wake", "body_battery_min", "stress_avg"):
        assert row[key] is None or 0 <= row[key] <= 100, (key, row[key])
    assert row["steps"] is None or row["steps"] >= 0
    assert row["weight_kg"] is None


# ------------------------------------------------------------------------------------ real fixtures


@pytest.mark.parametrize("path", _params(SUMMARY_FILES, [p.name for p in SUMMARY_FILES]))
def test_real_activity_summary(path: Path) -> None:
    summary = _load(path)
    item = _list_items().get(summary.get("activityId"))
    row = normalize_activity(summary, item)
    check_activity_row(row)
    assert row["garmin_id"] == summary["activityId"]
    alone = normalize_activity(summary)
    assert alone["start_utc"] == row["start_utc"] and alone["sport"] == row["sport"]


@pytest.mark.parametrize("path", _params([LIST_FILE] if LIST_FILE.exists() else [], [LIST_FILE.name]))
def test_real_activity_list_items(path: Path) -> None:
    items = _load(path)
    assert isinstance(items, list) and items
    summaries = {s.get("activityId"): s for s in (_load(p) for p in SUMMARY_FILES)}
    for item in items:
        row = normalize_activity(None, item)
        check_activity_row(row)
        summary = summaries.get(item["activityId"])
        if summary is None:
            continue
        full = normalize_activity(summary)
        for key in ("garmin_id", "sport", "sub_sport", "start_utc", "local_date", "is_race", "is_indoor"):
            assert row[key] == full[key], (item["activityId"], key, row[key], full[key])
        try:
            zone_offset = full["start_utc"].astimezone(ZoneInfo(full["tz"])).utcoffset()
        except (ZoneInfoNotFoundError, ValueError, TypeError):
            continue
        sign = -1 if row["tz"].startswith("-") else 1
        hours, minutes = (int(x) for x in row["tz"][1:].split(":"))
        assert zone_offset == sign * timedelta(hours=hours, minutes=minutes), (full["tz"], row["tz"])


@pytest.mark.parametrize("path", _params(DETAIL_FILES, [p.name for p in DETAIL_FILES]))
def test_real_activity_streams(path: Path) -> None:
    details = _load(path)
    summary_path = path.with_name(path.name.replace("_details.json", "_summary.json"))
    summary = _load(summary_path) if summary_path.exists() else None
    item = _list_items().get(details.get("activityId"))
    activity = normalize_activity(summary, item) if (summary or item) else None
    outdoor = activity is not None and not activity["is_indoor"] and bool(activity["distance_m"])
    check_streams(normalize_streams(details), outdoor=outdoor, activity=activity)


@pytest.mark.parametrize("day", _params(WELLNESS_DAYS, [f"wellness_{d}" for d in WELLNESS_DAYS]))
def test_real_wellness_day(day: str) -> None:
    d = date.fromisoformat(day)
    check_wellness_row(normalize_wellness(d, **_wellness_payloads(day)), d)


def test_real_wellness_has_data() -> None:
    if not WELLNESS_DAYS:
        pytest.skip(_NO_FIXTURES)
    rows = [normalize_wellness(date.fromisoformat(d), **_wellness_payloads(d)) for d in WELLNESS_DAYS]
    assert any((r["sleep_s"] or 0) > 0 for r in rows), "no day with sleep_s > 0"
    for key in ("sleep_start", "rhr", "stress_avg", "steps"):
        assert any(r[key] is not None for r in rows), f"{key} is None on every day"
    if BB_FILES:
        assert any(r["body_battery_min"] is not None for r in rows), "body battery array never parsed"


# ----------------------------------------------------------------- self-test of the check functions


def _synthetic(name: str) -> Any:
    data = json.loads((SYNTHETIC / name).read_text())
    data.pop("_synthetic", None)
    return data


def test_checks_accept_synthetic_fixtures() -> None:
    for sport in ("run", "bike"):
        row = normalize_activity(
            _synthetic(f"activity_{sport}_summary.json"), _synthetic(f"activity_{sport}_list_item.json")
        )
        check_activity_row(row)
    check_streams(normalize_streams(_synthetic("activity_run_details.json")), outdoor=True)
    day = date(2026, 9, 28)
    wellness = normalize_wellness(
        day,
        sleep=_synthetic("wellness_sleep.json"),
        user_summary=_synthetic("wellness_user_summary.json"),
        rhr=_synthetic("wellness_rhr.json"),
        stress=_synthetic("wellness_stress.json"),
        body_battery=_synthetic("wellness_body_battery.json")["entries"],
    )
    check_wellness_row(wellness, day)


def test_checks_reject_bad_values() -> None:
    row = normalize_activity(_synthetic("activity_run_summary.json"))
    with pytest.raises(AssertionError):
        check_activity_row(row | {"avg_speed": 12.0})  # km/h instead of m/s
    with pytest.raises(AssertionError):
        check_activity_row(row | {"start_utc": row["start_utc"].replace(tzinfo=None)})
    df = normalize_streams(_synthetic("activity_run_details.json"))
    with pytest.raises(AssertionError):
        check_streams(df.assign(hr=df["hr"] * 3), outdoor=True)
    with pytest.raises(AssertionError):
        check_streams(df, outdoor=True, activity={"duration_s": 3021.4, "distance_m": None})
    with pytest.raises(AssertionError):
        check_streams(df.iloc[0:0], outdoor=True)
    wellness = normalize_wellness(date(2026, 9, 28), sleep=_synthetic("wellness_sleep.json"))
    with pytest.raises(AssertionError):
        check_wellness_row(wellness, date(2026, 9, 25))
