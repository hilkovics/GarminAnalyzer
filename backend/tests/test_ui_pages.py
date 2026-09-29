"""AppTest runs of Dashboard, Fitness, the placeholders and app.py with monkeypatched services (no DB)."""

import datetime as dt

import pytest
from streamlit.testing.v1 import AppTest

from tests.test_ui_progres_samples import (
    sample_curves,
    sample_efforts,
    sample_predictions,
    sample_proposals,
    sample_series,
)
from tests.test_ui_samples import (
    sample_dashboard,
    sample_diagnostics,
    sample_list,
    sample_pmc,
    sample_settings,
    sample_sync_result,
    sample_weekly,
)
from tests.test_ui_support import (
    TODAY,
    UI_DIR,
    figures,
    patch_service,
    run_page,
    setup_ui,
    texts,
    trace_names,
)
from training.services.dto import DashboardDTO, PmcDTO
from training.services.errors import ServiceError


@pytest.fixture(autouse=True)
def ui(monkeypatch):
    setup_ui(monkeypatch)


def patch_dashboard(monkeypatch, dashboard=None, *, error: Exception | None = None):
    def get_dashboard(session, *, today):
        assert today == TODAY
        if error:
            raise error
        return dashboard or sample_dashboard()

    patch_service(monkeypatch, "fitness", get_dashboard=get_dashboard)


# --- Dashboard ----------------------------------------------------------------------------------------------


def test_dashboard_renders_form_week_table_and_charts(monkeypatch):
    patch_dashboard(monkeypatch)
    at = run_page("dashboard")
    assert not at.exception
    text = texts(at)
    assert "Dashboard" in text
    assert "Posledný sync: 29. 09. 2026" in text
    assert not at.error  # a fresh sync raises no warning
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["CTL (kondícia)"] == "48.2"
    assert metrics["ATL (únava)"] == "51.0"
    assert metrics["TSB (sviežosť)"] == "-4.0"
    assert metrics["ACWR"] == "1.10"
    assert metrics["Nárast CTL / týždeň"] == "+2.5"
    assert ":green-badge[optimum]" in text

    table = at.dataframe[0].value
    assert list(table["Šport"]) == ["Beh", "Bicykel", "Spolu"]
    run = table.iloc[0]
    assert (run["Záťaž"], run["Záťaž Ø 4 t"]) == ("220", "205")
    assert (run["Čas"], run["Čas Ø 4 t"]) == ("3:45", "3:30")
    assert (run["Vzdialenosť"], run["Vzdialenosť Ø 4 t"]) == ("31.0 km", "28.0 km")

    compare, mini_pmc = figures(at)
    assert trace_names(compare) == ["Tento týždeň", "Ø 4 predch. týždne"]
    assert trace_names(mini_pmc) == ["Denná záťaž", "CTL", "ATL", "TSB"]
    assert len(mini_pmc["data"][1]["x"]) == 42


def test_dashboard_metric_switch_converts_units(monkeypatch):
    patch_dashboard(monkeypatch)
    at = run_page("dashboard")
    at.radio(key="dashboard_metric").set_value("duration").run()
    assert not at.exception
    compare = figures(at)[0]
    assert compare["data"][0]["y"] == [3.75, 1.5]  # run and bike hours this week
    at.radio(key="dashboard_metric").set_value("distance").run()
    assert figures(at)[0]["data"][0]["y"] == [31.0, 41.0]


def test_dashboard_stale_sync_shows_red_warning(monkeypatch):
    patch_dashboard(monkeypatch, sample_dashboard(sync_stale=True, last_sync=dt.date(2026, 9, 26)))
    at = run_page("dashboard")
    assert not at.exception
    assert len(at.error) == 1
    assert "starší ako 36 hodín" in at.error[0].value
    assert "26. 09. 2026" in at.error[0].value


def test_dashboard_never_synced(monkeypatch):
    patch_dashboard(monkeypatch, sample_dashboard(sync_stale=True, last_sync=None))
    at = run_page("dashboard")
    assert not at.exception
    assert "Posledný sync: žiadny" in at.error[0].value


def test_dashboard_flags_danger_and_ramp_warning(monkeypatch):
    patch_dashboard(
        monkeypatch, sample_dashboard(acwr=1.7, acwr_band="danger", ramp_rate=8.0, ramp_warning=True)
    )
    at = run_page("dashboard")
    text = texts(at)
    assert ":red-badge[riziko]" in text
    assert ":red-badge[príliš rýchly nárast]" in text


def test_dashboard_without_any_data(monkeypatch):
    empty = DashboardDTO(
        today=TODAY,
        week_start=dt.date(2026, 9, 28),
        this_week=[],
        last4_avg=[],
        pmc=PmcDTO(points=[], series_start=None, warming_up_until=None, latest=None),
        latest=None,
        last_sync=None,
        sync_stale=True,
    )
    patch_dashboard(monkeypatch, empty)
    at = run_page("dashboard")
    assert not at.exception
    text = texts(at)
    assert "Zatiaľ žiadne metriky" in text
    assert "Tento týždeň zatiaľ žiadna aktivita" in text


def test_dashboard_shows_service_error_message(monkeypatch):
    patch_dashboard(monkeypatch, error=ServiceError("Databáza nie je pripravená"))
    at = run_page("dashboard")
    assert not at.exception
    assert at.error[0].value == "Databáza nie je pripravená"
    assert not at.metric  # nothing else rendered after st.stop()


# --- Fitness ------------------------------------------------------------------------------------------------


def patch_fitness(monkeypatch, pmc=None, *, error: Exception | None = None):
    calls: dict[str, list] = {"pmc": [], "weekly": []}

    def get_pmc(session, *, date_from=None, date_to=None):
        calls["pmc"].append((date_from, date_to))
        if error:
            raise error
        return pmc or sample_pmc(200)

    def get_weekly(session, *, weeks=12, today):
        calls["weekly"].append((weeks, today))
        return sample_weekly(4)

    patch_service(monkeypatch, "fitness", get_pmc=get_pmc, get_weekly=get_weekly)
    return calls


def test_fitness_renders_pmc_with_warming_up_band_and_weekly_bars(monkeypatch):
    calls = patch_fitness(monkeypatch)
    at = run_page("fitness")
    assert not at.exception
    assert calls["pmc"] == [
        (TODAY - dt.timedelta(days=364), None)
    ]  # default range: 1 year = 365 days incl. today
    assert calls["weekly"] == [(12, TODAY)]
    pmc_fig, weekly_fig = figures(at)
    assert trace_names(pmc_fig) == ["Denná záťaž", "CTL", "ATL", "TSB"]
    assert [s["name"] for s in pmc_fig["layout"]["shapes"] if s.get("name")] == ["warming_up"]
    assert trace_names(weekly_fig) == ["Beh", "Bicykel"]
    text = texts(at)
    assert "Sivé pásmo = zahrievanie do" in text
    assert "Záťaž po týždňoch (12 týždňov)" in text


def test_fitness_latest_point_flags(monkeypatch):
    patch_fitness(monkeypatch)
    at = run_page("fitness")
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["ACWR"] == "1.10"
    assert metrics["Monotónnosť"] == "1.40"
    assert metrics["Strain"] == "420"
    assert metrics["Nárast CTL / týždeň"] == "+2.5"
    assert ":green-badge[optimum]" in texts(at)
    assert not at.warning  # no ramp warning, and 200 days > 90 days warming-up


def test_fitness_ramp_warning_and_caution_band(monkeypatch):
    patch_fitness(
        monkeypatch, sample_pmc(200, acwr=1.4, acwr_band="caution", ramp_rate=7.2, ramp_warning=True)
    )
    at = run_page("fitness")
    assert ":orange-badge[pozor]" in texts(at)
    assert any("rýchlejšie ako 6" in w.value for w in at.warning)


def test_fitness_controls_change_the_service_calls(monkeypatch):
    calls = patch_fitness(monkeypatch)
    at = run_page("fitness")
    at.radio(key="fitness_range").set_value("Všetko").run()
    at.slider(key="fitness_weeks").set_value(52).run()
    at.radio(key="fitness_metric").set_value("distance").run()
    assert not at.exception
    assert calls["pmc"][-1] == (None, None)
    assert calls["weekly"][-1] == (52, TODAY)
    weekly_fig = figures(at)[1]
    assert weekly_fig["data"][0]["y"] == [30.0] * 4  # km
    assert "Vzdialenosť po týždňoch (52 týždňov)" in texts(at)


def test_fitness_warming_up_series_is_flagged(monkeypatch):
    patch_fitness(monkeypatch, sample_pmc(60))
    at = run_page("fitness")
    assert any("prvých 90 dňoch" in c.value for c in at.caption)


def test_fitness_without_data(monkeypatch):
    empty = PmcDTO(points=[], series_start=None, warming_up_until=None, latest=None)
    patch_fitness(monkeypatch, empty)
    at = run_page("fitness")
    assert not at.exception
    assert "Zatiaľ žiadne metriky" in texts(at)


def test_fitness_shows_service_error_message(monkeypatch):
    patch_fitness(monkeypatch, error=ServiceError("PMC zlyhalo"))
    at = run_page("fitness")
    assert not at.exception
    assert at.error[0].value == "PMC zlyhalo"


# --- placeholders and navigation ----------------------------------------------------------------------------


@pytest.mark.parametrize(("page", "title", "phase"), [("spanok", "Spánok", 5), ("plan", "Plán", 6)])
def test_placeholder_pages(page, title, phase):
    at = run_page(page)
    assert not at.exception
    assert at.title[0].value == title
    assert at.info[0].value == f"Pribudne vo fáze {phase}."


def test_app_navigation_runs_the_default_page(monkeypatch):
    patch_dashboard(monkeypatch)
    at = AppTest.from_file(str(UI_DIR / "app.py"), default_timeout=20).run()
    assert not at.exception
    assert at.title[0].value == "Dashboard"
    assert {m.label for m in at.metric} >= {"CTL (kondícia)", "ACWR"}


def test_app_navigation_reaches_every_page(monkeypatch):
    patch_service(
        monkeypatch,
        "fitness",
        get_dashboard=lambda session, *, today: sample_dashboard(),
        get_pmc=lambda session, **kwargs: sample_pmc(100),
        get_weekly=lambda session, **kwargs: sample_weekly(4),
    )
    patch_service(monkeypatch, "activities", list_activities=lambda session, **kwargs: sample_list(3))
    patch_service(monkeypatch, "settings", get_settings=lambda session, *, today: sample_settings())
    patch_service(monkeypatch, "diagnostics", get_diagnostics=lambda session: sample_diagnostics())
    patch_service(monkeypatch, "sync", run_sync=lambda session, **kwargs: sample_sync_result())
    patch_service(
        monkeypatch,
        "progress",
        get_ef_series=lambda session, *, metric="ef", sport="run", **kwargs: sample_series(
            metric, sport=sport
        ),
        get_speed_hr_curves=lambda session, **kwargs: sample_curves(),
        get_best_efforts=lambda session, *, range="90d", sport="run", **kwargs: sample_efforts(range, sport),
        get_predictions=lambda session, **kwargs: sample_predictions(),
        get_threshold_proposals=lambda session, **kwargs: sample_proposals(),
    )
    at = AppTest.from_file(str(UI_DIR / "app.py"), default_timeout=20).run()
    for page, title in {
        "views/aktivity.py": "Aktivity",
        "views/fitness.py": "Fitness",
        "views/progres.py": "Progres",
        "views/spanok.py": "Spánok",
        "views/plan.py": "Plán",
        "views/nastavenia.py": "Nastavenia",
        "views/dashboard.py": "Dashboard",
    }.items():
        at.switch_page(page).run()
        assert not at.exception, page
        assert at.title[0].value == title
