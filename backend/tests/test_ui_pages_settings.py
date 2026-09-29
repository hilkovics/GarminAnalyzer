"""AppTest runs of the Nastavenia page (athlete, thresholds, zone preview, diagnostics, sync now)."""

import datetime as dt

import pytest

from tests.test_ui_samples import sample_athlete, sample_diagnostics, sample_settings, sample_sync_result
from tests.test_ui_support import TODAY, patch_service, run_page, setup_ui, texts
from training.config import Settings
from training.services.dto import (
    AthleteIn,
    LoadSanityDTO,
    SettingsDTO,
    ThresholdIn,
)
from training.services.errors import InvalidInputError, ServiceError


@pytest.fixture(autouse=True)
def ui(monkeypatch):
    setup_ui(monkeypatch)


class Calls:
    def __init__(self):
        self.athlete: list[AthleteIn] = []
        self.threshold: list[ThresholdIn] = []
        self.sync: list[dict] = []


def patch_settings(
    monkeypatch,
    cfg=None,
    *,
    diagnostics=None,
    sync_result=None,
    settings_error=None,
    threshold_error=None,
    sync_error=None,
) -> Calls:
    calls = Calls()

    def get_settings(session, *, today):
        assert today == TODAY
        if settings_error:
            raise settings_error
        return cfg or sample_settings()

    def update_athlete(session, data, *, today):
        calls.athlete.append(data)
        return sample_athlete()

    def add_threshold(session, data, *, today):
        calls.threshold.append(data)
        if threshold_error:
            raise threshold_error
        return sample_settings().thresholds[0]

    def run_sync(session, *, settings, today):
        calls.sync.append({"settings": settings, "today": today})
        if sync_error:
            raise sync_error
        return sync_result or sample_sync_result()

    patch_service(
        monkeypatch,
        "settings",
        get_settings=get_settings,
        update_athlete=update_athlete,
        add_threshold=add_threshold,
    )
    patch_service(monkeypatch, "sync", run_sync=run_sync)
    patch_service(monkeypatch, "progress", get_threshold_proposals=lambda session, *, today: [])
    patch_service(
        monkeypatch, "diagnostics", get_diagnostics=lambda session: diagnostics or sample_diagnostics()
    )
    return calls


def button(at, label):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button {label!r}; have {[b.label for b in at.button]}"
    return matches[0]


def frames(at):
    return [d.value for d in at.dataframe]


# --- rendering ----------------------------------------------------------------------------------------------


def test_settings_page_shows_history_zones_and_athlete(monkeypatch):
    patch_settings(monkeypatch)
    at = run_page("nastavenia")
    assert not at.exception
    assert at.title[0].value == "Nastavenia"
    text = texts(at)
    assert "Pokojový tep použitý dnes: 48 bpm" in text

    history, hr_run, hr_bike, pace = frames(at)[:4]
    assert list(history["Šport"]) == ["Beh", "Beh", "Bicykel"]
    assert list(history["Platný od"]) == ["01. 01. 2025", "01. 01. 2026", "01. 01. 2026"]
    assert list(history["LTHR (bpm)"]) == ["165", "170", "160"]
    assert list(history["Prahové tempo"]) == ["4:23/km", "4:10/km", "–"]
    assert list(history["Platí dnes"]) == ["", "áno", "áno"]

    assert list(hr_run["Rozsah"]) == ["< 130 bpm", "130–150 bpm", "150–162 bpm", "162–175 bpm", "> 175 bpm"]
    assert list(hr_bike["Zóna"]) == ["Z1", "Z2", "Z3", "Z4", "Z5"]
    assert pace["Rozsah"].iloc[0] == "pomalšie ako 6:40/km"  # 2.5 m/s
    assert pace["Rozsah"].iloc[1] == "6:40–5:33/km"  # 2.5–3.0 m/s
    assert pace["Rozsah"].iloc[4] == "rýchlejšie ako 4:16/km"  # 3.9 m/s

    assert at.selectbox[0].value == "male"
    assert at.number_input[0].value == 1990
    assert at.number_input[1].value == 72.5
    assert at.number_input[2].value == 190.0
    assert at.number_input[3].value is None  # no manual resting HR
    assert at.number_input[4].value == 70.0  # 0.7 shown as percent


def test_settings_page_on_a_fresh_install(monkeypatch):
    fresh = SettingsDTO(
        athlete=None, thresholds=[], current={"run": None, "bike": None}, hr_zones={}, pace_zones=None
    )
    patch_settings(
        monkeypatch,
        fresh,
        diagnostics=sample_diagnostics(
            last_activity_sync=None,
            last_wellness_date=None,
            backfill_cursor=None,
            pending_activities=0,
            pending_wellness_days=0,
            failed_activities=[],
            failed_wellness_days=[],
            activities=0,
            activities_with_metrics=0,
            low_confidence_share=None,
            load_sanity=LoadSanityDTO(r=None, n=0, status="insufficient"),
            hrtss_rtss_divergent=[],
        ),
    )
    at = run_page("nastavenia")
    assert not at.exception
    text = texts(at)
    assert "Zatiaľ nie je zadaný žiadny prah" in text
    assert "Bez platného prahu sa zóny nedajú zobraziť." in text
    assert ":gray-badge[málo dát]" in text
    assert at.selectbox[0].value is None
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Pearson r"] == "–"
    assert metrics["Posledný sync aktivít"] == "–"


def test_settings_service_error_is_a_message(monkeypatch):
    patch_settings(monkeypatch, settings_error=ServiceError("Nastavenia sa nedajú načítať"))
    at = run_page("nastavenia")
    assert not at.exception
    assert at.error[0].value == "Nastavenia sa nedajú načítať"


# --- athlete form -------------------------------------------------------------------------------------------


def test_athlete_form_saves_and_confirms_after_rerun(monkeypatch):
    calls = patch_settings(monkeypatch)
    at = run_page("nastavenia")
    at.number_input[2].set_value(195.0)  # max HR
    at.number_input[3].set_value(50.0)  # manual resting HR
    at.number_input[4].set_value(60.0)  # 60 % running
    button(at, "Uložiť atléta").click().run()
    assert not at.exception
    assert calls.athlete == [
        AthleteIn(
            sex="male",
            birth_year=1990,
            max_hr=195.0,
            rest_hr_override=50.0,
            weight_kg=72.5,
            run_bike_split=0.6,
        )
    ]
    assert any(s.value == "Údaje atléta uložené." for s in at.success)


def test_athlete_form_empty_fields_are_sent_as_none(monkeypatch):
    fresh = SettingsDTO(athlete=None, thresholds=[], current={}, hr_zones={}, pace_zones=None)
    calls = patch_settings(monkeypatch, fresh)
    at = run_page("nastavenia")
    button(at, "Uložiť atléta").click().run()
    assert calls.athlete == [AthleteIn()]


# --- threshold form -----------------------------------------------------------------------------------------


def fill_threshold(at, *, sport="run", lthr=172.0, pace="4:05", valid_from=dt.date(2026, 9, 1)):
    at.selectbox[1].select(sport)
    if lthr is not None:
        at.number_input[5].set_value(lthr)
    at.text_input[0].set_value(pace)
    at.date_input[0].set_value(valid_from)


def test_add_threshold_parses_pace_in_the_ui_layer(monkeypatch):
    calls = patch_settings(monkeypatch)
    at = run_page("nastavenia")
    fill_threshold(at)
    button(at, "Pridať prah").click().run()
    assert not at.exception
    assert len(calls.threshold) == 1
    data = calls.threshold[0]
    assert (data.sport, data.valid_from, data.lthr) == ("run", dt.date(2026, 9, 1), 172.0)
    assert data.threshold_speed == pytest.approx(1000 / 245)  # 4:05 /km in m/s
    assert any("Prah (Beh, od 01. 09. 2026) uložený." in s.value for s in at.success)


def test_add_threshold_run_without_pace_and_bike(monkeypatch):
    calls = patch_settings(monkeypatch)
    at = run_page("nastavenia")
    fill_threshold(at, sport="run", pace="")
    button(at, "Pridať prah").click().run()
    at = run_page("nastavenia")
    fill_threshold(at, sport="bike", lthr=161.0, pace="")
    button(at, "Pridať prah").click().run()
    assert [(t.sport, t.lthr, t.threshold_speed) for t in calls.threshold] == [
        ("run", 172.0, None),
        ("bike", 161.0, None),
    ]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"pace": "abc"}, "Tempo zadaj ako m:ss"),
        ({"pace": "4:75"}, "Sekundy musia byť"),
        ({"pace": "1:00"}, "Tempo musí byť medzi"),
        ({"lthr": None}, "Zadaj LTHR."),
    ],
)
def test_add_threshold_validation_errors_do_not_call_the_service(monkeypatch, kwargs, message):
    calls = patch_settings(monkeypatch)
    at = run_page("nastavenia")
    fill_threshold(at, **kwargs)
    button(at, "Pridať prah").click().run()
    assert not at.exception
    assert message in at.error[0].value
    assert calls.threshold == []


def test_bike_threshold_ignores_prefilled_pace(monkeypatch):
    """Review phase 3: the pace field is prefilled with today's run pace; for bike it is simply ignored."""
    calls = patch_settings(monkeypatch)
    at = run_page("nastavenia")
    fill_threshold(at, sport="bike", pace="4:10")
    button(at, "Pridať prah").click().run()
    assert not at.exception
    assert [(t.sport, t.threshold_speed) for t in calls.threshold] == [("bike", None)]


def test_add_threshold_service_error_is_shown(monkeypatch):
    patch_settings(monkeypatch, threshold_error=InvalidInputError("Prah pre tento dátum už existuje"))
    at = run_page("nastavenia")
    fill_threshold(at)
    button(at, "Pridať prah").click().run()
    assert not at.exception
    assert at.error[0].value == "Prah pre tento dátum už existuje"
    assert not at.success


# --- diagnostics --------------------------------------------------------------------------------------------


def test_diagnostics_section(monkeypatch):
    patch_settings(monkeypatch)
    at = run_page("nastavenia")
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Posledný sync aktivít"] == "28. 09. 2026"
    assert metrics["Čakajúce"] == "2 akt. / 1 dní"
    assert (metrics["Aktivity"], metrics["S metrikami"], metrics["Bez prahu"], metrics["Bez záťaže"]) == (
        "320",
        "318",
        "4",
        "6",
    )
    assert metrics["Nízka spoľahlivosť"] == "12 %"
    assert metrics["Pearson r"] == "0.87"
    text = texts(at)
    assert ":green-badge[dobrá zhoda] · n = 300 aktivít" in text
    assert any("900000123" in w.value for w in at.warning)
    assert any("03. 08. 2026" in w.value for w in at.warning)
    divergent = frames(at)[-1]
    assert list(divergent["Garmin id"]) == [900000777]
    assert (divergent["hrTSS"].iloc[0], divergent["rTSS"].iloc[0], divergent["Rozdiel (%)"].iloc[0]) == (
        "100",
        "150",
        "50",
    )


def test_diagnostics_load_sanity_colours(monkeypatch):
    for status, r, badge in (("warning", 0.55, ":red-badge["), ("fair", 0.75, ":orange-badge[")):
        patch_settings(
            monkeypatch, diagnostics=sample_diagnostics(load_sanity=LoadSanityDTO(r=r, n=30, status=status))
        )
        at = run_page("nastavenia")
        assert badge in texts(at)


def test_diagnostics_without_divergences(monkeypatch):
    patch_settings(
        monkeypatch,
        diagnostics=sample_diagnostics(
            hrtss_rtss_divergent=[], failed_activities=[], failed_wellness_days=[]
        ),
    )
    at = run_page("nastavenia")
    assert "Žiadne." in texts(at)
    assert not at.warning


# --- sync now -----------------------------------------------------------------------------------------------


def test_sync_button_runs_the_service_and_shows_the_result(monkeypatch):
    calls = patch_settings(monkeypatch)
    at = run_page("nastavenia")
    assert calls.sync == []  # nothing runs until the button is pressed
    button(at, "Spustiť sync teraz").click().run()
    assert not at.exception
    assert len(calls.sync) == 1
    assert isinstance(calls.sync[0]["settings"], Settings)
    assert calls.sync[0]["today"] == TODAY
    assert any(s.value == "Sync dokončený." for s in at.success)
    metrics = {m.label: m.value for m in at.metric}
    assert (metrics["Nové aktivity"], metrics["Aktualizované"], metrics["Nezmenené"]) == ("3", "1", "40")
    assert (metrics["Prepočítané metriky"], metrics["Dni PMC"], metrics["Wellness dni"]) == ("4", "700", "2")


def test_sync_result_with_errors_is_a_warning(monkeypatch):
    patch_settings(monkeypatch, sync_result=sample_sync_result(errors=["wellness 2026-09-27: HTTP 500"]))
    at = run_page("nastavenia")
    button(at, "Spustiť sync teraz").click().run()
    assert not at.exception
    assert any(w.value == "Sync dokončený s chybami." for w in at.warning)
    assert any("HTTP 500" in w.value for w in at.warning)
    assert not at.success


def test_sync_service_error_message_is_shown(monkeypatch):
    patch_settings(
        monkeypatch, sync_error=ServiceError("Garmin odmietol prihlásenie – spusti `training login`")
    )
    at = run_page("nastavenia")
    button(at, "Spustiť sync teraz").click().run()
    assert not at.exception
    assert at.error[0].value == "Sync zlyhal: Garmin odmietol prihlásenie – spusti `training login`"
    assert not at.success
