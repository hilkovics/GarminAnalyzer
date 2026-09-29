"""AppTest runs of the Aktivity page (list, filters, paging, detail, subjective form); services faked."""

import datetime as dt
from types import SimpleNamespace

import pytest
import streamlit as st

from tests.test_ui_samples import sample_detail, sample_list, sample_streams
from tests.test_ui_support import figures, patch_service, run_page, setup_ui, texts, trace_names
from training.services.dto import SubjectiveDTO, SubjectiveIn
from training.services.errors import NotFoundError, ServiceError


@pytest.fixture(autouse=True)
def ui(monkeypatch):
    setup_ui(monkeypatch)


class Calls:
    """Records the arguments of the patched activity services."""

    def __init__(self):
        self.list: list[dict] = []
        self.detail: list[int] = []
        self.streams: list[dict] = []
        self.saved: list[tuple[int, SubjectiveIn]] = []


def patch_activities(
    monkeypatch,
    *,
    listing=None,
    details=None,
    streams=None,
    list_error=None,
    streams_error=None,
    save_error=None,
) -> Calls:
    calls = Calls()
    details = details or {1: sample_detail(1), 2: sample_detail(2, sport="bike")}

    def list_activities(session, *, date_from=None, date_to=None, sport=None, page=1, page_size=50):
        calls.list.append(
            {"date_from": date_from, "date_to": date_to, "sport": sport, "page": page, "page_size": page_size}
        )
        if list_error:
            raise list_error
        if listing is not None:  # the fake honours the requested page like the real service
            return listing.model_copy(update={"page": page})
        return sample_list(3, page=page, page_size=page_size)

    def get_activity(session, activity_id):
        calls.detail.append(activity_id)
        if activity_id not in details:
            raise NotFoundError(f"activity {activity_id}")
        return details[activity_id]

    def get_streams(session, activity_id, fields=None, points=1500):
        calls.streams.append({"activity_id": activity_id, "fields": fields, "points": points})
        if streams_error:
            raise streams_error
        return streams or sample_streams(activity_id, fields=fields)

    def save_subjective(session, activity_id, data):
        calls.saved.append((activity_id, data))
        if save_error:
            raise save_error
        return SubjectiveDTO(id=1, date=dt.date(2026, 9, 19), activity_id=activity_id, **data.model_dump())

    patch_service(
        monkeypatch,
        "activities",
        list_activities=list_activities,
        get_activity=get_activity,
        get_streams=get_streams,
        save_subjective=save_subjective,
    )
    return calls


def button(at, label):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button {label!r}; have {[b.label for b in at.button]}"
    return matches[0]


# --- list ---------------------------------------------------------------------------------------------------


def test_list_table_formats_units_and_marks_unknown_or_low_confidence_load(monkeypatch):
    calls = patch_activities(monkeypatch)
    at = run_page("aktivity")
    assert not at.exception
    assert calls.list == [{"date_from": None, "date_to": None, "sport": None, "page": 1, "page_size": 25}]
    table = at.dataframe[0].value
    assert list(table.columns) == [
        "Dátum",
        "Šport",
        "Názov",
        "Trvanie",
        "Vzdialenosť",
        "Tempo / rýchlosť",
        "Záťaž",
    ]
    first, bike, unknown = (table.iloc[i] for i in range(3))
    assert first["Dátum"] == "19. 09. 2026"
    assert (first["Šport"], first["Názov"], first["Trvanie"]) == ("Beh", "Ranný beh 1", "1:02")
    assert (first["Vzdialenosť"], first["Tempo / rýchlosť"], first["Záťaž"]) == (
        "12.35 km",
        "5:00/km",
        "87 (hrtss)",
    )
    assert (bike["Šport"], bike["Tempo / rýchlosť"], bike["Záťaž"]) == (
        "Bicykel",
        "28.8 km/h",
        "⚠ 87 (hrtss)",
    )
    assert unknown["Záťaž"] == "⚠ neznáma"
    assert not at.get("plotly_chart")  # no detail until an activity is chosen
    assert "Strana 1 z 1 · 3 aktivít" in texts(at)


def test_filters_are_passed_to_the_service_and_reset_paging(monkeypatch):
    calls = patch_activities(monkeypatch, listing=sample_list(3, total=60))
    at = run_page("aktivity")
    button(at, "Staršie ›").click().run()
    assert calls.list[-1]["page"] == 2
    at.selectbox(key="aktivity_sport").select("Beh").run()
    at.date_input(key="aktivity_from").set_value(dt.date(2026, 8, 1)).run()
    at.date_input(key="aktivity_to").set_value(dt.date(2026, 9, 1)).run()
    assert not at.exception
    assert calls.list[-1] == {
        "date_from": dt.date(2026, 8, 1),
        "date_to": dt.date(2026, 9, 1),
        "sport": "run",
        "page": 1,  # changing a filter goes back to the first page
        "page_size": 25,
    }


def test_inverted_date_range_is_rejected_without_calling_the_service(monkeypatch):
    calls = patch_activities(monkeypatch)
    at = run_page("aktivity")
    n_before = len(calls.list)
    at.date_input(key="aktivity_from").set_value(dt.date(2026, 9, 10))
    at.date_input(key="aktivity_to").set_value(dt.date(2026, 9, 1)).run()
    assert "neskôr ako" in at.error[0].value
    assert len(calls.list) == n_before


def test_paging_buttons(monkeypatch):
    calls = patch_activities(monkeypatch, listing=sample_list(3, total=60))
    at = run_page("aktivity")
    assert "Strana 1 z 3 · 60 aktivít" in texts(at)
    assert button(at, "‹ Novšie").disabled
    button(at, "Staršie ›").click().run()
    assert calls.list[-1]["page"] == 2
    assert "Strana 2 z 3" in texts(at)
    button(at, "Staršie ›").click().run()
    assert "Strana 3 z 3" in texts(at)
    assert button(at, "Staršie ›").disabled
    button(at, "‹ Novšie").click().run()
    assert calls.list[-1]["page"] == 2


def test_empty_result_and_service_error(monkeypatch):
    patch_activities(monkeypatch, listing=sample_list(0))
    at = run_page("aktivity")
    assert not at.exception
    assert at.info[0].value == "Žiadne aktivity pre zvolený filter."
    assert not at.dataframe

    patch_activities(monkeypatch, list_error=ServiceError("DB je zamknutá"))
    at = run_page("aktivity")
    assert not at.exception
    assert at.error[0].value == "DB je zamknutá"


# --- detail -------------------------------------------------------------------------------------------------


def test_detail_via_query_param_renders_every_section(monkeypatch):
    calls = patch_activities(monkeypatch)
    at = run_page("aktivity", query={"activity": "1"})
    assert not at.exception
    assert calls.detail == [1]
    assert calls.streams == [
        {"activity_id": 1, "fields": ["hr", "speed", "gap_speed", "alt"], "points": 1500}
    ]
    text = texts(at)
    assert "Ranný beh 1 · 19. 09. 2026" in text
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Trvanie"] == "1:02:05"
    assert metrics["Vzdialenosť"] == "12.35 km"
    assert metrics["Tempo"] == "5:00/km"
    assert metrics["Priem. tep"] == "148 bpm"
    assert metrics["Prevýšenie"] == "85 m"
    # load breakdown hrTSS / rTSS / TRIMP
    assert (metrics["hrTSS"], metrics["rTSS"], metrics["TRIMP (norm.)"]) == ("87", "82", "90")
    assert (metrics["IF (tep)"], metrics["IF (tempo)"]) == ("0.86", "0.84")
    assert "Primárna záťaž: 87 (hrtss)" in text
    assert "Garmin training load: 120" in text

    charts = figures(at)
    assert len(charts) == 3
    chart, hr_zones, pace_zones = charts
    assert trace_names(chart) == ["Tep", "Tempo", "GAP", "Výška"]
    assert hr_zones["data"][0]["y"][1].endswith("130–150 bpm")
    assert "/km" in pace_zones["data"][0]["y"][1]
    assert "Prah platný od 01. 01. 2026: LTHR 170 bpm, prahové tempo 4:10/km." in text

    laps = at.dataframe[1].value  # [0] is the activity table
    assert list(laps["Kolo"]) == [1, 2]
    assert list(laps["Trvanie"]) == ["5:00", "5:00"]
    assert list(laps["Tempo"]) == ["5:00/km", "5:00/km"]


def test_detail_bike_requests_no_gap_and_has_no_pace_zones(monkeypatch):
    calls = patch_activities(monkeypatch)
    at = run_page("aktivity", query={"activity": "2"})
    assert not at.exception
    assert calls.streams[0]["fields"] == ["hr", "speed", "alt"]
    metrics = {m.label: m.value for m in at.metric}
    assert "Rýchlosť" in metrics and "Tempo" not in metrics
    chart, zones = figures(at)  # a single zones chart: no pace zones for a ride
    assert trace_names(chart) == ["Tep", "Rýchlosť", "Výška"]
    assert all("bpm" in label or "Z" in label for label in zones["data"][0]["y"])


def test_detail_via_table_selection(monkeypatch):
    calls = patch_activities(monkeypatch)
    real_dataframe = st.dataframe

    def selecting_dataframe(*args, **kwargs):
        real_dataframe(*args, **kwargs)
        return SimpleNamespace(selection=SimpleNamespace(rows=[1]))

    monkeypatch.setattr(st, "dataframe", selecting_dataframe)
    at = run_page("aktivity")
    assert not at.exception
    assert calls.detail == [2]  # the second row of the list is activity id 2


def test_unknown_activity_is_a_message_not_a_crash(monkeypatch):
    patch_activities(monkeypatch)
    at = run_page("aktivity", query={"activity": "999"})
    assert not at.exception
    assert at.error[0].value == "Aktivita 999 neexistuje."
    assert at.dataframe  # the list is still shown


def test_garbage_activity_param_is_ignored(monkeypatch):
    calls = patch_activities(monkeypatch)
    at = run_page("aktivity", query={"activity": "abc"})
    assert not at.exception
    assert calls.detail == []


def test_detail_survives_missing_streams(monkeypatch):
    patch_activities(monkeypatch, streams_error=ServiceError("stream chýba"))
    at = run_page("aktivity", query={"activity": "1"})
    assert not at.exception
    assert any("Priebeh nie je k dispozícii: stream chýba" in i.value for i in at.info)
    assert len(figures(at)) == 2  # the zone charts are still drawn


def test_detail_without_threshold_or_load(monkeypatch):
    detail = sample_detail(
        1, load_primary=None, load_method=None, hrtss=None, rtss=None, low_confidence=True, hr_coverage=0.4
    )
    detail = detail.model_copy(update={"threshold": None, "hr_zones": [], "pace_zones": None, "laps": []})
    patch_activities(monkeypatch, details={1: detail})
    at = run_page("aktivity", query={"activity": "1"})
    assert not at.exception
    text = texts(at)
    assert "K dátumu aktivity nie je platný žiadny prah" in text
    assert "Nízka spoľahlivosť záťaže (pokrytie tepu 40 %)" in text
    assert "Záťaž tejto aktivity je neznáma" in text
    assert "Primárna záťaž: ⚠ neznáma" in text
    assert "Aktivita nemá žiadne kolá." in text
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["hrTSS"] == "–"


# --- subjective form ----------------------------------------------------------------------------------------


def test_subjective_form_is_prefilled_and_saves(monkeypatch):
    calls = patch_activities(monkeypatch)
    at = run_page("aktivity", query={"activity": "1"})
    assert at.selectbox(key="rpe_1").value == 6
    assert at.selectbox(key="feel_1").value == 4
    assert at.selectbox(key="soreness_1").value == 1
    assert at.text_area(key="notes_1").value == "fajn"

    at.selectbox(key="rpe_1").select(8)
    at.selectbox(key="feel_1").select(3)
    at.selectbox(key="soreness_1").select(2)
    at.text_area(key="notes_1").set_value("  ťažké nohy  ")
    button(at, "Uložiť hodnotenie").click().run()
    assert not at.exception
    assert calls.saved == [(1, SubjectiveIn(rpe=8, feel=3, soreness=2, notes="ťažké nohy"))]
    assert any(s.value == "Hodnotenie uložené." for s in at.success)


def test_subjective_form_empty_values_become_none(monkeypatch):
    calls = patch_activities(monkeypatch, details={1: sample_detail(1, subjective=False)})
    at = run_page("aktivity", query={"activity": "1"})
    assert at.selectbox(key="rpe_1").value is None
    button(at, "Uložiť hodnotenie").click().run()
    assert calls.saved == [(1, SubjectiveIn(rpe=None, feel=None, soreness=None, notes=None))]


def test_subjective_form_shows_service_error(monkeypatch):
    calls = patch_activities(monkeypatch, save_error=ServiceError("Aktivita už neexistuje"))
    at = run_page("aktivity", query={"activity": "1"})
    button(at, "Uložiť hodnotenie").click().run()
    assert not at.exception
    assert len(calls.saved) == 1
    assert any(e.value == "Aktivita už neexistuje" for e in at.error)
    assert not at.success
