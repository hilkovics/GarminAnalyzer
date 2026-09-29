"""AppTest runs of the Progres page (faked services, incl. empty-data states) and of the proposal actions in
Nastavenia."""

import pytest
import streamlit as st

from tests.test_ui_pages_settings import patch_settings
from tests.test_ui_progres_samples import (
    empty_series,
    sample_curves,
    sample_efforts,
    sample_predictions,
    sample_proposals,
    sample_series,
)
from tests.test_ui_support import TODAY, figures, patch_service, run_page, setup_ui, texts, trace_names
from training.services.dto import BestEffortsDTO, PredictionsDTO
from training.services.errors import InvalidInputError, ServiceError


@pytest.fixture(autouse=True)
def ui(monkeypatch):
    setup_ui(monkeypatch)


class Calls:
    def __init__(self):
        self.series: list[dict] = []
        self.efforts: list[dict] = []
        self.applied: list[dict] = []


def patch_progress(
    monkeypatch,
    *,
    series=None,
    curves=None,
    efforts=None,
    predictions=None,
    proposals=None,
    error: Exception | None = None,
    apply_error: Exception | None = None,
) -> Calls:
    calls = Calls()

    def get_ef_series(session, *, sport="run", days=180, today, metric="ef"):
        assert today == TODAY
        if error:
            raise error
        calls.series.append({"sport": sport, "days": days, "metric": metric})
        if series is not None:
            return series(metric, sport)
        caveat = "Bike EF depends on terrain and wind" if sport == "bike" and metric == "ef" else None
        return sample_series(metric, sport=sport, caveat=caveat)

    def get_speed_hr_curves(session, *, months=6, today):
        assert months == 6
        return sample_curves() if curves is None else curves

    def get_best_efforts(session, *, sport="run", range="90d", today):
        calls.efforts.append({"sport": sport, "range": range})
        return sample_efforts(range, sport) if efforts is None else efforts(range, sport)

    def get_predictions(session, *, today):
        return sample_predictions() if predictions is None else predictions

    def get_threshold_proposals(session, *, today):
        return sample_proposals() if proposals is None else proposals

    def apply_proposal(session, *, sport, field, today):
        calls.applied.append({"sport": sport, "field": field, "today": today})
        if apply_error:
            raise apply_error

    patch_service(
        monkeypatch,
        "progress",
        get_ef_series=get_ef_series,
        get_speed_hr_curves=get_speed_hr_curves,
        get_best_efforts=get_best_efforts,
        get_predictions=get_predictions,
        get_threshold_proposals=get_threshold_proposals,
        apply_proposal=apply_proposal,
    )
    return calls


def button(at, label):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button {label!r}; have {[b.label for b in at.button]}"
    return matches[0]


# --- full data ----------------------------------------------------------------------------------------------


def test_progres_renders_every_section(monkeypatch):
    calls = patch_progress(monkeypatch)
    at = run_page("progres")
    assert not at.exception
    assert at.title[0].value == "Progres"
    headers = [s.value for s in at.subheader]
    assert headers == [
        "Efektivita (EF) – trend",
        "Aeróbny decoupling",
        "Krivka rýchlosť–tep (posledných 6 mesiacov)",
        "Tempo pri referenčnom tepe (80 % LTHR)",
        "Najlepšie úseky: 90 dní vs celá história",
        "Predikcie pretekov",
        "Návrhy prahov",
    ]
    ef, decoupling, curves, pace_ref, best, hr = figures(at)
    assert trace_names(ef) == ["EF (steady-state)", "Medián 28 dní"]
    assert trace_names(decoupling) == ["Decoupling", "Medián 28 dní"]
    assert len(decoupling["layout"]["shapes"]) == 2  # the 5 % and 10 % band lines
    assert sorted(s["y0"] for s in decoupling["layout"]["shapes"]) == [5.0, 10.0]
    assert trace_names(curves) == ["2026-07", "2026-08", "2026-09"]
    assert curves["layout"]["yaxis"]["autorange"] == "reversed"  # pace: faster on top
    assert curves["data"][0]["x"] == [130, 135, 140, 145, 150]
    assert curves["data"][0]["y"][0] == pytest.approx(1000 / 2.8)  # s/km, not m/s
    assert trace_names(pace_ref) == ["Tempo pri referenčnom tepe", "Medián 28 dní"]
    assert pace_ref["layout"]["yaxis"]["autorange"] == "reversed"
    assert trace_names(best) == ["Posledných 90 dní", "Celá história"]
    assert best["data"][0]["x"] == ["1 min", "5 min", "10 min", "20 min", "30 min", "60 min"]
    assert best["layout"]["yaxis"]["autorange"] == "reversed"
    assert trace_names(hr) == ["Posledných 90 dní", "Celá história"]
    assert hr["data"][0]["x"] == ["20 min", "30 min", "60 min"]
    assert "yaxis" not in hr["layout"] or hr["layout"]["yaxis"].get("autorange") != "reversed"

    assert {c["metric"] for c in calls.series} == {"ef", "decoupling_pct", "pace_at_ref_hr_day"}
    assert [c["sport"] for c in calls.series if c["metric"] == "pace_at_ref_hr_day"] == ["run"]
    assert {c["days"] for c in calls.series} == {180}
    assert {c["range"] for c in calls.efforts} == {"90d", "all"}
    assert not at.warning and not at.error


def test_predictions_table_uses_hms_and_marks_extrapolation(monkeypatch):
    patch_progress(monkeypatch)
    at = run_page("progres")
    text = texts(at)
    assert "Referencia: 10.00 km za 0:40:00 (4:00/km), 19. 09. 2026, pretek · VDOT 51.9" in text
    table = next(d.value for d in at.dataframe if "Riegel" in d.value.columns)
    assert list(table["Vzdialenosť"]) == ["5 km", "10 km", "Polmaratón", "Maratón"]
    assert list(table["Riegel"]) == ["0:19:10", "0:40:00", "1:27:45", "3:03:20"]
    assert list(table["Daniels (VDOT)"]) == ["0:19:15", "0:40:00", "1:28:33", "3:07:30"]
    assert list(table["Poznámka"])[:3] == ["", "", ""]
    assert "extrapolované" in table["Poznámka"].iloc[3]
    assert not [w for w in at.warning if "60 dní" in w.value]


def test_stale_reference_is_flagged(monkeypatch):
    patch_progress(monkeypatch, predictions=sample_predictions(stale=True))
    at = run_page("progres")
    assert any("starší ako 60 dní" in w.value for w in at.warning)


def test_proposals_table_and_the_button_to_settings(monkeypatch):
    patch_progress(monkeypatch)
    at = run_page("progres")
    table = next(d.value for d in at.dataframe if "Navrhnúť" in d.value.columns)
    assert list(table["Šport"]) == ["Beh", "Beh", "Bicykel"]
    assert list(table["Prah"]) == ["Prahové tempo", "LTHR", "LTHR"]
    assert list(table["Aktuálne"]) == ["4:46/km", "170 bpm", "165 bpm"]
    assert list(table["Odhad"]) == ["4:30/km", "174 bpm", "166 bpm"]
    assert list(table["Zmena"]) == ["+5.7 %", "+4 bpm", "+1 bpm"]
    assert list(table["Navrhnúť"]) == ["áno", "áno", "nie"]
    assert table["Garmin"].iloc[0] == "LT tempo 4:38/km · VO2max 52"
    assert table["Garmin"].iloc[1] == "LT tep 171 bpm · VO2max 52"
    assert table["Garmin"].iloc[2] == "–"
    assert button(at, "Použiť návrh v Nastaveniach")


def test_button_leads_to_settings(monkeypatch):
    patch_progress(monkeypatch)
    jumps = []
    monkeypatch.setattr(st, "switch_page", lambda page: jumps.append(page))
    at = run_page("progres")
    button(at, "Použiť návrh v Nastaveniach").click().run()
    assert jumps == ["views/nastavenia.py"]


def test_no_button_when_nothing_is_proposed(monkeypatch):
    patch_progress(monkeypatch, proposals=sample_proposals(propose=False))
    at = run_page("progres")
    assert not [b for b in at.button if b.label == "Použiť návrh v Nastaveniach"]


# --- controls -----------------------------------------------------------------------------------------------


def test_bike_shows_the_caveat_and_hides_run_only_sections(monkeypatch):
    calls = patch_progress(monkeypatch)
    at = run_page("progres")
    at.radio(key="progress_sport").set_value("bike").run()
    assert not at.exception
    assert any("terénu a vetra" in w.value for w in at.warning)
    headers = [s.value for s in at.subheader]
    assert "Krivka rýchlosť–tep (posledných 6 mesiacov)" not in headers
    assert "Predikcie pretekov" not in headers
    assert "Návrhy prahov" in headers  # proposals cover the bike LTHR too
    assert len(figures(at)) == 4  # EF, decoupling, best efforts, HR efforts
    best = figures(at)[2]
    assert best["layout"]["yaxis"]["title"]["text"] == "Rýchlosť (km/h)"
    assert {"sport": "bike", "range": "all"} in calls.efforts
    assert any("len pre beh" in c.value for c in at.caption)


def test_range_radio_passes_days_to_the_service(monkeypatch):
    calls = patch_progress(monkeypatch)
    at = run_page("progres")
    at.radio(key="progress_range").set_value("1 rok").run()
    assert {c["days"] for c in calls.series[-3:]} == {365}


# --- empty and error states ---------------------------------------------------------------------------------


def test_empty_data_states(monkeypatch):
    patch_progress(
        monkeypatch,
        series=lambda metric, sport: empty_series(metric, sport),
        curves=[],
        efforts=lambda range_, sport: BestEffortsDTO(sport=sport, range=range_, efforts=[]),
        predictions=PredictionsDTO(reference=None, stale=False, predictions=[]),
        proposals=[],
    )
    at = run_page("progres")
    assert not at.exception
    annotations = [f["layout"]["annotations"][0]["text"] for f in figures(at)]
    assert len(annotations) == 6 and all(annotations)
    assert "Zatiaľ žiadne steady-state aktivity s EF." in annotations
    assert any("krivka rýchlosť–tep" in a for a in annotations)
    text = texts(at)
    assert "Zatiaľ žiadny referenčný výkon" in text
    assert "Zatiaľ žiadne návrhy prahov" in text
    assert not at.button


def test_service_error_is_shown_and_stops_the_page(monkeypatch):
    patch_progress(monkeypatch, error=InvalidInputError("days must be between 1 and 3650"))
    at = run_page("progres")
    assert not at.exception
    assert "days must be between 1 and 3650" in at.error[0].value
    assert not figures(at)


# --- Nastavenia: apply a proposal ---------------------------------------------------------------------------


def test_settings_lists_proposals_and_applies_one_from_today(monkeypatch):
    patch_settings(monkeypatch)
    calls = patch_progress(monkeypatch)
    at = run_page("nastavenia")
    assert not at.exception
    assert "Návrhy prahov z posledných 90 dní" in texts(at)
    labels = [b.label for b in at.button if b.label.startswith("Použiť:")]
    assert labels == [
        "Použiť: Beh – Prahové tempo 4:30/km od dnes",
        "Použiť: Beh – LTHR 174 bpm od dnes",
    ]  # the bike proposal is not proposed → no button
    button(at, labels[1]).click().run()
    assert calls.applied == [{"sport": "run", "field": "lthr", "today": TODAY}]
    assert not at.exception and not at.error
    assert "Návrh prahu (Beh, LTHR) uložený od dnes." in [s.value for s in at.success]


def test_settings_shows_the_service_error_of_an_apply(monkeypatch):
    patch_settings(monkeypatch)
    calls = patch_progress(monkeypatch, apply_error=ServiceError("nothing to apply"))
    at = run_page("nastavenia")
    button(at, "Použiť: Beh – LTHR 174 bpm od dnes").click().run()
    assert calls.applied
    assert [e.value for e in at.error] == ["nothing to apply"]
    assert not at.success


def test_settings_without_proposals_has_no_apply_buttons(monkeypatch):
    patch_settings(monkeypatch)
    patch_progress(monkeypatch, proposals=[])
    at = run_page("nastavenia")
    assert not [b for b in at.button if b.label.startswith("Použiť:")]
    assert "Zatiaľ žiadne návrhy prahov" in texts(at)
