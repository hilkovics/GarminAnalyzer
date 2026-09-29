"""Formatting helpers and badge mapping of the Streamlit components (pure functions, edge cases)."""

import datetime as dt
import math

import pytest

from tests.test_ui_support import ui_module


@pytest.fixture(scope="module")
def fmt():
    return ui_module("components.format")


@pytest.fixture(scope="module")
def badges():
    return ui_module("components.badges")


@pytest.mark.parametrize(
    ("speed", "expected"),
    [
        (1000 / 300, "5:00/km"),
        (1000 / 250, "4:10/km"),
        (1000 / 359.6, "6:00/km"),  # rounds up across the minute boundary
        (1000 / 3600, "60:00/km"),
        (0.0, "–"),
        (-1.0, "–"),
        (None, "–"),
        (float("nan"), "–"),
    ],
)
def test_fmt_pace(fmt, speed, expected):
    assert fmt.fmt_pace(speed) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00"),
        (29, "0:00"),
        (30, "0:01"),
        (3600, "1:00"),
        (5400, "1:30"),
        (3599, "1:00"),
        (36000 + 5 * 60, "10:05"),
        (None, "–"),
        (-5, "–"),
    ],
)
def test_fmt_duration(fmt, seconds, expected):
    assert fmt.fmt_duration(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(59, "0:59"), (300, "5:00"), (3599.6, "1:00:00"), (3725, "1:02:05"), (None, "–")],
)
def test_fmt_duration_hms(fmt, seconds, expected):
    assert fmt.fmt_duration_hms(seconds) == expected


def test_fmt_distance_and_speed(fmt):
    assert fmt.fmt_km(12345) == "12.3 km"
    assert fmt.fmt_km(12345, 2) == "12.35 km"
    assert fmt.fmt_km(0) == "0.0 km"
    assert fmt.fmt_km(None) == "–"
    assert fmt.fmt_speed_kmh(8.0) == "28.8 km/h"
    assert fmt.fmt_speed_kmh(None) == "–"
    assert fmt.fmt_speed(8.0, "bike") == "28.8 km/h"
    assert fmt.fmt_speed(1000 / 300, "run") == "5:00/km"
    assert fmt.fmt_speed(1000 / 300, None) == "5:00/km"
    assert fmt.fmt_hours(5400) == "1.5 h"
    assert fmt.fmt_hours(None) == "–"


def test_fmt_numbers_and_dates(fmt):
    assert fmt.fmt_num(None) == "–"
    assert fmt.fmt_num(math.nan) == "–"
    assert fmt.fmt_num(48.26, 1) == "48.3"
    assert fmt.fmt_num(148.4, 0, "bpm") == "148 bpm"
    assert fmt.fmt_signed(-4.04) == "-4.0"
    assert fmt.fmt_signed(2.5) == "+2.5"
    assert fmt.fmt_signed(None) == "–"
    assert fmt.fmt_pct(0.125) == "12 %"
    assert fmt.fmt_pct(0.125, 1) == "12.5 %"
    assert fmt.fmt_pct(None) == "–"
    assert fmt.fmt_date(dt.date(2026, 9, 5)) == "05. 09. 2026"
    assert fmt.fmt_date(None) == "–"
    assert fmt.sport_label("run") == "Beh"
    assert fmt.sport_label("all") == "Spolu"
    assert fmt.sport_label("swim") == "swim"
    assert fmt.sport_label(None) == "–"


def test_fmt_load_marks_unknown_and_low_confidence(fmt):
    assert fmt.fmt_load(87.4, "hrtss") == "87 (hrtss)"
    assert fmt.fmt_load(87.4) == "87"
    assert fmt.fmt_load(0.0, "hrtss") == "0 (hrtss)"  # a known zero is not "unknown"
    assert fmt.fmt_load(None) == "⚠ neznáma"
    assert fmt.fmt_load(None, "hrtss", low_confidence=True) == "⚠ neznáma"
    assert fmt.fmt_load(87.4, "hrtss", low_confidence=True) == "⚠ 87 (hrtss)"


def test_fmt_zone_range(fmt):
    assert fmt.fmt_zone_range(130, 150) == "130–150 bpm"
    assert fmt.fmt_zone_range(None, 130) == "< 130 bpm"
    assert fmt.fmt_zone_range(175, None) == "> 175 bpm"
    assert fmt.fmt_zone_range(None, None) == "–"
    # pace bounds are m/s; the range reads slow-fast
    assert fmt.fmt_zone_range(1000 / 330, 1000 / 290, "pace") == "5:30–4:50/km"
    assert fmt.fmt_zone_range(None, 1000 / 330, "pace") == "pomalšie ako 5:30/km"
    assert fmt.fmt_zone_range(1000 / 250, None, "pace") == "rýchlejšie ako 4:10/km"
    assert fmt.fmt_zone_range(None, None, "pace") == "–"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("4:10", 250), (" 5:00 ", 300), ("4:10/km", 250), ("04:05", 245), ("2:00", 120), ("15:00", 900)],
)
def test_parse_pace_valid(fmt, text, seconds):
    assert fmt.parse_pace(text) == pytest.approx(1000.0 / seconds)


@pytest.mark.parametrize(
    "text", ["", "4", "4:1x", "4:60", "a:10", "4:10:00", "-4:10", "1:59", "15:01", "4,10"]
)
def test_parse_pace_invalid(fmt, text):
    with pytest.raises(ValueError, match=r"\S"):
        fmt.parse_pace(text)


def test_parse_pace_round_trips_through_fmt_pace(fmt):
    assert fmt.fmt_pace(fmt.parse_pace("4:10")) == "4:10/km"


def test_acwr_badge_bands(badges):
    assert badges.acwr_badge("optimal").color == "green"
    assert badges.acwr_badge("under").color == "blue"
    assert badges.acwr_badge("caution").color == "orange"
    assert badges.acwr_badge("danger").color == "red"
    unknown = badges.acwr_badge(None)
    assert (unknown.text, unknown.color) == ("–", "gray")
    assert badges.acwr_badge("nonsense") == unknown
    assert badges.acwr_badge("optimal").markdown == ":green-badge[optimum]"


def test_load_sanity_badge(badges):
    assert badges.load_sanity_badge("good").color == "green"
    assert badges.load_sanity_badge("fair").color == "orange"
    assert badges.load_sanity_badge("warning").color == "red"
    assert badges.load_sanity_badge("insufficient").color == "gray"
    assert badges.load_sanity_badge(None).color == "gray"
