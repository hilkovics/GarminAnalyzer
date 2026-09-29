"""Plotly components of the Progres page and the new format helpers: DTO in, figure out."""

import pytest

from tests.test_ui_progres_samples import (
    empty_series,
    sample_curves,
    sample_efforts,
    sample_series,
)
from tests.test_ui_support import ui_module
from training.services.dto import BestEffortsDTO


@pytest.fixture(scope="module")
def progress_mod():
    return ui_module("components.progress")


@pytest.fixture(scope="module")
def efforts_mod():
    return ui_module("components.efforts")


@pytest.fixture(scope="module")
def fmt():
    return ui_module("components.format")


def test_ef_chart_points_and_trend_line(progress_mod):
    series = sample_series("ef")
    fig = progress_mod.ef_chart(series)
    points, trend = fig.data
    assert points.mode == "markers" and list(points.y) == [p.value for p in series.points]
    assert trend.mode == "lines" and trend.connectgaps is False
    assert trend.y[:3] == (None, None, None) and trend.y[3] == pytest.approx(1.55)  # gaps stay gaps


def test_ef_chart_without_trend_only_has_points(progress_mod):
    assert len(progress_mod.ef_chart(sample_series("ef", trend=False)).data) == 1


def test_decoupling_chart_has_the_two_band_lines(progress_mod):
    fig = progress_mod.decoupling_chart(sample_series("decoupling_pct"))
    assert sorted(s.y0 for s in fig.layout.shapes) == [5.0, 10.0]


def test_pace_ref_chart_converts_m_per_s_to_s_per_km(progress_mod):
    fig = progress_mod.pace_ref_chart(sample_series("pace_at_ref_hr_day"))
    assert fig.data[0].y[0] == pytest.approx(1000.0 / 3.5)
    assert fig.layout.yaxis.autorange == "reversed"
    assert fig.layout.yaxis.ticktext[0].count(":") == 1  # m:ss labels


def test_empty_series_give_a_message_figure(progress_mod):
    for build, metric in (
        (progress_mod.ef_chart, "ef"),
        (progress_mod.decoupling_chart, "decoupling_pct"),
        (progress_mod.pace_ref_chart, "pace_at_ref_hr_day"),
    ):
        fig = build(empty_series(metric))
        assert not fig.data and fig.layout.annotations[0].text.startswith("Zatiaľ")


def test_series_with_only_null_values_is_empty(progress_mod):
    series = sample_series("ef")
    for p in series.points:
        p.value = None
    assert not progress_mod.ef_chart(series).data


def test_curves_chart_orders_lines_and_marks_the_reference_hr(efforts_mod):
    fig = efforts_mod.curves_chart(sample_curves())
    assert [t.name for t in fig.data] == ["2026-07", "2026-08", "2026-09"]
    assert fig.data[-1].line.width > fig.data[0].line.width  # newest month is emphasised
    assert fig.data[0].line.color != fig.data[-1].line.color
    assert fig.layout.yaxis.autorange == "reversed"
    assert any(s.x0 == 136.0 for s in fig.layout.shapes)


def test_curves_chart_skips_months_without_bins(efforts_mod):
    curves = sample_curves()
    curves[1].bins = []
    assert [t.name for t in efforts_mod.curves_chart(curves).data] == ["2026-07", "2026-09"]
    assert not efforts_mod.curves_chart([]).data


def test_best_efforts_chart_run_is_pace_and_bike_is_kmh(efforts_mod):
    run = efforts_mod.best_efforts_chart(sample_efforts("90d"), sample_efforts("all"))
    assert [t.name for t in run.data] == ["Posledných 90 dní", "Celá história"]
    assert run.data[0].y[0] == pytest.approx(1000.0 / 5.0)
    assert run.layout.yaxis.autorange == "reversed"
    bike = efforts_mod.best_efforts_chart(sample_efforts("90d", "bike"), sample_efforts("all", "bike"))
    assert bike.data[0].y[0] == pytest.approx(5.0 * 3.6)
    assert bike.layout.yaxis.autorange != "reversed"


def test_best_efforts_chart_tolerates_missing_windows(efforts_mod):
    recent = sample_efforts("90d")
    recent.efforts = [e for e in recent.efforts if e.window_s != 300]
    fig = efforts_mod.best_efforts_chart(recent, sample_efforts("all"))
    assert fig.data[0].y[1] is None and fig.data[1].y[1] is not None
    assert list(fig.data[0].x) == list(fig.data[1].x)


def test_effort_charts_empty(efforts_mod):
    empty = BestEffortsDTO(sport="run", range="90d", efforts=[])
    assert not efforts_mod.best_efforts_chart(empty, empty).data
    assert not efforts_mod.hr_efforts_chart(empty, empty).data
    only_pace = sample_efforts("90d")
    only_pace.efforts = [e for e in only_pace.efforts if e.kind != "hr"]
    assert not efforts_mod.hr_efforts_chart(only_pace, only_pace).data


def test_hr_efforts_chart(efforts_mod):
    fig = efforts_mod.hr_efforts_chart(sample_efforts("90d"), sample_efforts("all"))
    assert list(fig.data[0].x) == ["20 min", "30 min", "60 min"]
    assert list(fig.data[0].y) == [165.0, 162.0, 159.0]


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(60, "1 min"), (1800, "30 min"), (3600, "60 min"), (45, "45 s"), (None, "–"), (0, "–")],
)
def test_fmt_window(fmt, seconds, expected):
    assert fmt.fmt_window(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(2400, "0:40:00"), (5313, "1:28:33"), (11250, "3:07:30"), (59.6, "0:01:00"), (None, "–"), (-1, "–")],
)
def test_fmt_time_hms(fmt, seconds, expected):
    assert fmt.fmt_time_hms(seconds) == expected


def test_pace_axis_ticks(fmt):
    axis = ui_module("components.pace_axis")
    assert axis.pace_s(4.0) == 250.0
    assert axis.pace_s(None) is None and axis.pace_s(0.0) is None
    assert axis.pace_s(1000 / 1200) is None  # slower than the 15:00/km cap
