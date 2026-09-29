"""AppTest runs of the Spánok page on real (seeded and empty) databases through the real services."""

import datetime as dt
from contextlib import contextmanager

import pytest
import streamlit as st
from sqlmodel import Session

from tests.test_ui_support import TODAY, figures, run_page, setup_ui, texts, trace_names, ui_module
from training.db.session import make_engine, migrate
from training.services import sleep as svc
from training.services.errors import InvalidInputError

from .wellness_seeding import wellness_db

N_BOOT = 60


@pytest.fixture(autouse=True)
def ui(monkeypatch):
    setup_ui(monkeypatch)
    st.cache_data.clear()
    svc.clear_cache()
    real = svc.get_correlations
    monkeypatch.setattr(svc, "get_correlations", lambda s, sport=None, n_boot=N_BOOT: real(s, sport, n_boot))
    yield
    st.cache_data.clear()
    svc.clear_cache()


def use_db(monkeypatch, path):
    engine = make_engine(path)

    @contextmanager
    def session():
        with Session(engine) as s:
            yield s

    monkeypatch.setattr(ui_module("_db"), "session", session)
    monkeypatch.setattr(ui_module("_db"), "today", lambda: TODAY_DB)
    return engine


TODAY_DB = dt.date(2026, 9, 16)  # the day the wellness scenario ends on
assert TODAY != TODAY_DB


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    engine = use_db(monkeypatch, wellness_db(tmp_path))
    yield engine
    engine.dispose()


@pytest.fixture
def empty(monkeypatch, tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = use_db(monkeypatch, path)
    yield engine
    engine.dispose()


def test_page_renders_every_section_on_a_seeded_db(seeded):
    at = run_page("spanok")
    assert not at.exception
    assert at.title[0].value == "Spánok"
    assert [s.value for s in at.subheader] == [
        "Pripravenosť dnes",
        "Dĺžka a fázy spánku",
        "Skóre spánku",
        "Pokojový tep",
        "Spánkový dlh (7 nocí)",
        "Zistenia",
    ]
    gauge, stages, score, rhr, debt = figures(at)
    assert gauge["data"][0]["type"] == "indicator"
    assert 0 <= gauge["data"][0]["value"] <= 100 and gauge["data"][0]["value"] == int(
        gauge["data"][0]["value"]
    )
    assert (
        trace_names(stages) == ["Hlboký", "Ľahký", "REM", "Bdelý"] and stages["layout"]["barmode"] == "stack"
    )
    assert len(stages["data"][0]["x"]) == 90  # default range
    assert trace_names(score) == [None, "± MAD", "Medián 28 dní", "Skóre spánku"]
    assert trace_names(rhr) == [None, "± MAD", "Medián 28 dní", "Pokojový tep"]
    assert trace_names(debt) == ["Spánkový dlh (7 nocí)"]
    assert not at.error and not at.exception

    table = next(d.value for d in at.dataframe if "Zložka" in d.value.columns)
    assert list(table["Zložka"]) == ["Pokojový tep", "Spánok", "Body Battery", "Forma (TSB)"]
    assert "bpm" in table["Hodnota"].iloc[0]
    assert "%" in table["Váha"].iloc[0]


def test_findings_are_sorted_and_show_the_caveat_and_insufficient_data(seeded):
    at = run_page("spanok")
    text = texts(at)
    assert "Korelácia nie je kauzalita" in text
    assert "Keď spíš dlhšie (noc pred tréningom), tvoj EF pri behu je vyšší – silná súvislosť." in text
    assert any("n = " in c.value and "parciálne ρ = +" in c.value for c in at.caption)
    labels = [e.label for e in at.expander]
    assert any(label.startswith("Nedostatok dát (n < 30)") for label in labels)
    assert any(label.startswith("Ďalšie zistenia") for label in labels)


def test_range_and_sport_controls(seeded):
    at = run_page("spanok")
    at.radio(key="sleep_range").set_value("30 dní").run()
    assert not at.exception
    assert len(figures(at)[1]["data"][0]["x"]) == 30
    at.radio(key="sleep_sport").set_value("bike").run()
    assert not at.exception
    text = texts(at)
    assert "Zatiaľ žiadne zistenia" in text  # bike: 10 qualifying days
    assert "na bicykli" in " ".join(c.value for c in at.caption)  # the insufficient pairs are listed


def test_correlations_are_cached_between_reruns(seeded, monkeypatch):
    calls = []
    real = svc.correlations
    monkeypatch.setattr(svc, "correlations", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    at = run_page("spanok")
    at.radio(key="sleep_range").set_value("30 dní").run()
    assert calls == ["run"]  # the rerun reuses the service cache (same inputs)


def test_empty_database_renders_without_exceptions(empty):
    at = run_page("spanok")
    assert not at.exception and not at.error
    assert at.title[0].value == "Spánok"
    gauge, *others = figures(at)
    assert gauge["layout"]["annotations"][0]["text"] == "Pripravenosť dnes nie je k dispozícii."
    assert all(f["layout"]["annotations"][0]["text"] for f in others)
    text = texts(at)
    assert "Na tento deň nie je dosť wellness dát" in text
    assert "Zatiaľ žiadne zistenia" in text and "Korelácia nie je kauzalita" in text


def test_service_error_is_shown_and_stops_the_page(seeded, monkeypatch):
    def boom(session, day):
        raise InvalidInputError("zle")

    monkeypatch.setattr(svc, "get_readiness", boom)
    at = run_page("spanok")
    assert not at.exception
    assert at.error[0].value == "zle" and not figures(at)
