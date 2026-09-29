"""Plotly components: DTO in, figure out. Hand-built DTOs, assertions on traces, axes and shapes."""

import datetime as dt

import pytest

from tests.test_ui_samples import pmc_point, sample_pmc, sample_streams, sample_weekly, weekly_row, zone_times
from tests.test_ui_support import MONDAY, ui_module
from training.services.dto import PmcDTO, StreamsDTO

HALF_DAY = dt.timedelta(hours=12)


@pytest.fixture(scope="module")
def pmc_mod():
    return ui_module("components.pmc")


@pytest.fixture(scope="module")
def weekly_mod():
    return ui_module("components.weekly")


@pytest.fixture(scope="module")
def activity_mod():
    return ui_module("components.activity")


@pytest.fixture(scope="module")
def zones_mod():
    return ui_module("components.zones")


def trace(fig, name):
    matches = [t for t in fig.data if t.name == name]
    assert len(matches) == 1, f"expected one trace named {name!r}, got {[t.name for t in fig.data]}"
    return matches[0]


# --- pmc_chart ----------------------------------------------------------------------------------------------


def test_pmc_chart_traces(pmc_mod):
    pmc = sample_pmc(120)
    fig = pmc_mod.pmc_chart(pmc)
    assert [t.name for t in fig.data] == ["Denná záťaž", "CTL", "ATL", "TSB"]
    assert [t.type for t in fig.data] == ["bar", "scatter", "scatter", "scatter"]
    assert all(len(t.x) == 120 for t in fig.data)
    assert list(trace(fig, "CTL").y) == [p.ctl for p in pmc.points]
    assert list(trace(fig, "Denná záťaž").y) == [p.load_total for p in pmc.points]
    assert fig.layout.showlegend is True


def test_pmc_chart_has_a_single_y_axis(pmc_mod):
    fig = pmc_mod.pmc_chart(sample_pmc(120))
    assert {t.yaxis for t in fig.data} <= {None, "y"}  # everything on the default axis
    assert "yaxis2" not in fig.to_dict()["layout"]


def test_pmc_chart_warming_up_band(pmc_mod):
    pmc = sample_pmc(120)
    fig = pmc_mod.pmc_chart(pmc)
    bands = [s for s in fig.layout.shapes if s.name == "warming_up"]
    assert len(bands) == 1
    band = bands[0]
    assert band.type == "rect"
    assert (band.yref, band.y0, band.y1) == ("paper", 0, 1)  # full plot height
    assert band.layer == "below"
    assert band.x0 == dt.datetime.combine(pmc.series_start, dt.time.min) - HALF_DAY
    assert band.x1 == dt.datetime.combine(pmc.warming_up_until, dt.time.min) + HALF_DAY
    assert any("zahrievanie" in a.text for a in fig.layout.annotations)


def test_pmc_chart_band_is_clipped_to_the_plotted_points(pmc_mod):
    pmc = sample_pmc(42)  # 42 points, warming_up_until is 89 days after the start → beyond the last point
    band = next(s for s in pmc_mod.pmc_chart(pmc).layout.shapes if s.name == "warming_up")
    assert band.x1 == dt.datetime.combine(pmc.points[-1].date, dt.time.min) + HALF_DAY

    # a zoomed-in range that starts after the series start is clipped on the left as well
    zoomed = PmcDTO(
        points=pmc.points[10:],
        series_start=pmc.series_start,
        warming_up_until=pmc.warming_up_until,
        latest=pmc.latest,
    )
    band = next(s for s in pmc_mod.pmc_chart(zoomed).layout.shapes if s.name == "warming_up")
    assert band.x0 == dt.datetime.combine(zoomed.points[0].date, dt.time.min) - HALF_DAY


def test_pmc_chart_no_band_when_warm_up_is_outside_the_range(pmc_mod):
    points = [pmc_point(dt.date(2026, 1, 1) + dt.timedelta(days=i), i) for i in range(30)]
    pmc = PmcDTO(
        points=points,
        series_start=dt.date(2025, 1, 1),
        warming_up_until=dt.date(2025, 3, 31),
        latest=points[-1],
    )
    fig = pmc_mod.pmc_chart(pmc)
    assert not any(s.name == "warming_up" for s in fig.layout.shapes)
    assert len(fig.data) == 4


def test_pmc_chart_keeps_missing_values_as_gaps(pmc_mod):
    points = [pmc_point(dt.date(2026, 1, 1) + dt.timedelta(days=i), i, ctl=None, tsb=None) for i in range(5)]
    pmc = PmcDTO(points=points, series_start=None, warming_up_until=None, latest=points[-1])
    fig = pmc_mod.pmc_chart(pmc)
    assert all(v is None for v in trace(fig, "CTL").y)
    assert not any(
        s.name == "warming_up" for s in fig.layout.shapes
    )  # series_start unknown: nothing to shade


def test_pmc_chart_empty_and_compact(pmc_mod):
    empty = PmcDTO(points=[], series_start=None, warming_up_until=None, latest=None)
    fig = pmc_mod.pmc_chart(empty)
    assert len(fig.data) == 0
    assert "Zatiaľ žiadne dáta" in fig.layout.annotations[0].text
    assert (
        pmc_mod.pmc_chart(sample_pmc(42), compact=True).layout.height
        < pmc_mod.pmc_chart(sample_pmc(42)).layout.height
    )


# --- weekly_bars / week_compare_bars ------------------------------------------------------------------------


def test_weekly_bars_stack_per_sport_and_skip_all(weekly_mod):
    fig = weekly_mod.weekly_bars(sample_weekly(4), "load")
    assert [t.name for t in fig.data] == ["Beh", "Bicykel"]
    assert fig.layout.barmode == "stack"
    assert len(fig.data[0].x) == 4
    assert list(fig.data[0].x) == sorted(fig.data[0].x)
    assert list(fig.data[0].y) == [200.0, 210.0, 220.0, 230.0]
    assert fig.data[0].customdata[-1] == f"T{MONDAY.isocalendar().week}/{MONDAY.isocalendar().year}"


def test_weekly_bars_convert_units_for_display(weekly_mod):
    weeks = sample_weekly(2)
    hours = weekly_mod.weekly_bars(weeks, "duration")
    assert list(hours.data[0].y) == [4.0, 4.0]  # 14400 s
    assert list(hours.data[1].y) == [3.0, 3.0]  # 10800 s
    assert "(h)" in hours.layout.yaxis.title.text
    km = weekly_mod.weekly_bars(weeks, "distance")
    assert list(km.data[0].y) == [30.0, 30.0]
    assert "(km)" in km.layout.yaxis.title.text


def test_weekly_bars_fill_missing_sport_weeks_with_zero(weekly_mod):
    first, second = MONDAY - dt.timedelta(weeks=1), MONDAY
    weeks = [
        weekly_row(first, "run", load=100.0),
        weekly_row(second, "run", load=50.0),
        weekly_row(second, "bike", load=70.0),
    ]
    fig = weekly_mod.weekly_bars(weeks, "load")
    assert list(trace(fig, "Bicykel").y) == [0.0, 70.0]
    assert list(trace(fig, "Beh").y) == [100.0, 50.0]


def test_weekly_bars_colour_follows_the_sport(weekly_mod):
    only_bike = [weekly_row(MONDAY, "bike"), weekly_row(MONDAY, "all")]
    both = sample_weekly(1)
    assert (
        trace(weekly_mod.weekly_bars(only_bike), "Bicykel").marker.color
        == trace(weekly_mod.weekly_bars(both), "Bicykel").marker.color
    )


def test_weekly_bars_empty_and_bad_metric(weekly_mod):
    assert len(weekly_mod.weekly_bars([]).data) == 0
    assert len(weekly_mod.weekly_bars([weekly_row(MONDAY, "all")]).data) == 0
    with pytest.raises(ValueError, match="Unknown weekly metric"):
        weekly_mod.weekly_bars(sample_weekly(1), "power")


def test_week_compare_bars(weekly_mod):
    this_week = [weekly_row(MONDAY, "run", load=220.0), weekly_row(MONDAY, "all", load=220.0)]
    average = [weekly_row(MONDAY, "run", load=200.0), weekly_row(MONDAY, "bike", load=140.0)]
    fig = weekly_mod.week_compare_bars(this_week, average, "load")
    assert [t.name for t in fig.data] == ["Tento týždeň", "Ø 4 predch. týždne"]
    assert list(fig.data[0].x) == ["Beh", "Bicykel"]
    assert list(fig.data[0].y) == [220.0, 0.0]  # nothing on the bike yet this week
    assert list(fig.data[1].y) == [200.0, 140.0]
    assert fig.layout.barmode == "group"
    assert len(weekly_mod.week_compare_bars([], []).data) == 0


# --- activity_chart -----------------------------------------------------------------------------------------


def test_activity_chart_run_has_hr_pace_and_altitude_panels(activity_mod):
    streams = sample_streams(points=60)
    fig = activity_mod.activity_chart(streams, sport="run")
    assert [t.name for t in fig.data] == ["Tep", "Tempo", "GAP", "Výška"]
    assert [t.yaxis for t in fig.data] == ["y", "y2", "y2", "y3"]
    assert all(t.xaxis in {"x", "x2", "x3"} for t in fig.data)
    # one shared time axis: the upper panels are matched to the bottom one
    assert fig.layout.xaxis.matches == "x3" or fig.layout.xaxis2.matches == "x3"
    # seconds → minutes on the x-axis
    assert list(fig.data[0].x)[:3] == [0.0, 10 / 60, 20 / 60]


def test_activity_chart_pace_axis_is_reversed_and_in_seconds_per_km(activity_mod):
    fig = activity_mod.activity_chart(sample_streams(points=60), sport="run")
    pace = trace(fig, "Tempo")
    assert fig.layout.yaxis2.autorange == "reversed"
    assert pace.y[1] == pytest.approx(1000 / 3.3)
    assert pace.y[0] is None  # speed 0 (standing still) is a gap, not an infinite pace
    assert list(pace.customdata)[1] == "5:03"
    assert trace(fig, "GAP").y[0] == pytest.approx(1000 / 3.4)
    labels = fig.layout.yaxis2.ticktext
    assert labels and all(":" in label for label in labels)
    assert len(labels) == len(fig.layout.yaxis2.tickvals)
    assert fig.layout.yaxis.autorange is None  # HR panel is a normal axis


def test_activity_chart_caps_absurdly_slow_pace(activity_mod):
    streams = sample_streams(points=5)
    streams.series["speed"] = [0.5, 3.0, None, 3.0, 3.0]  # 0.5 m/s = 33:20 /km
    pace = trace(activity_mod.activity_chart(streams), "Tempo")
    assert pace.y[0] is None and pace.y[2] is None
    assert pace.y[1] == pytest.approx(1000 / 3.0)


def test_activity_chart_bike_uses_kmh_and_no_gap(activity_mod):
    streams = sample_streams(points=20)
    streams.series["speed"] = [8.0] * 20
    fig = activity_mod.activity_chart(streams, sport="bike")
    assert [t.name for t in fig.data] == ["Tep", "Rýchlosť", "Výška"]  # GAP is a running concept
    assert trace(fig, "Rýchlosť").y[0] == pytest.approx(28.8)
    assert fig.layout.yaxis2.autorange is None
    assert fig.layout.yaxis2.title.text == "km/h"


def test_activity_chart_omits_panels_without_data(activity_mod):
    hr_only = sample_streams(points=10, fields=["hr"])
    fig = activity_mod.activity_chart(hr_only)
    assert [t.name for t in fig.data] == ["Tep"]

    all_none = sample_streams(points=10, fields=["hr", "alt"])
    all_none.series["alt"] = [None] * 10
    assert [t.name for t in activity_mod.activity_chart(all_none).data] == ["Tep"]


def test_activity_chart_empty_streams(activity_mod):
    fig = activity_mod.activity_chart(StreamsDTO(activity_id=1, points=0, source_points=0, t=[], series={}))
    assert len(fig.data) == 0
    assert "nie sú k dispozícii" in fig.layout.annotations[0].text


# --- zones_bar ----------------------------------------------------------------------------------------------


def test_zones_bar_hr(zones_mod):
    zones = zone_times("hr")
    fig = zones_mod.zones_bar(zones, kind="hr")
    bar = fig.data[0]
    assert bar.orientation == "h"
    assert list(bar.x) == [z.seconds / 60 for z in zones]
    assert bar.y[0].startswith("Z1") and "< 130 bpm" in bar.y[0]
    assert "130–150 bpm" in bar.y[1]
    assert "> 175 bpm" in bar.y[4]
    assert bar.text[1] == "30:00 · 49 %"  # 1800 s of 3660 s
    assert fig.layout.yaxis.autorange == "reversed"  # Z1 on top
    assert len(set(bar.marker.color)) == 5


def test_zones_bar_pace_uses_pace_labels_and_sorts_zones(zones_mod):
    fig = zones_mod.zones_bar(list(reversed(zone_times("pace"))), kind="pace")
    labels = list(fig.data[0].y)
    assert [label[:2] for label in labels] == ["Z1", "Z2", "Z3", "Z4", "Z5"]
    assert "/km" in labels[1] and "bpm" not in labels[1]
    assert "pomalšie ako" in labels[0]


def test_zones_bar_empty(zones_mod):
    fig = zones_mod.zones_bar([])
    assert len(fig.data) == 0
    assert "Žiadne dáta o zónach" in fig.layout.annotations[0].text
