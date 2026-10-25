"""AppTest runs of the morning-run health: the Dashboard status line and the Nastavenia "Ranné behy" table."""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from tests.test_ui_pages import patch_dashboard
from tests.test_ui_pages_settings import frames, patch_settings
from tests.test_ui_samples import sample_dashboard, sample_diagnostics, sample_run
from tests.test_ui_support import run_page, setup_ui, texts
from training import localtime

UTC = dt.UTC
# 2026-10-23 04:01:30 UTC is 6:01:30 in Europe/Bratislava (CEST)
FINISHED = dt.datetime(2026, 10, 23, 4, 1, 30, tzinfo=UTC)


@pytest.fixture(autouse=True)
def ui(monkeypatch):
    setup_ui(monkeypatch)
    with pytest.MonkeyPatch.context() as mp:  # no time.tzset: it does not exist on Windows
        mp.setattr(localtime, "local_zone", lambda: ZoneInfo("Europe/Bratislava"))
        yield


def health(**fields) -> dict:
    return {"last_successful_run": FINISHED, "last_run_ok": True, "morning_run_stale": False, **fields}


def dashboard_at(monkeypatch, **fields):
    patch_dashboard(monkeypatch, sample_dashboard(health=health(**fields)))
    at = run_page("dashboard")
    assert not at.exception
    return at


# --- Dashboard ----------------------------------------------------------------------------------------------


def test_dashboard_without_morning_runs_shows_only_a_caption(monkeypatch):
    patch_dashboard(monkeypatch, sample_dashboard())
    at = run_page("dashboard")
    assert not at.exception
    assert not at.error
    assert "Automatický ranný beh zatiaľ nebežal – návod v docs/OPERATIONS.md." in [
        c.value for c in at.caption
    ]


def test_dashboard_ok_run_is_a_caption_in_local_time(monkeypatch):
    at = dashboard_at(monkeypatch)
    assert not at.error
    assert "Posledný úspešný ranný beh: 23. 10. 2026, 6:01" in [c.value for c in at.caption]


def test_dashboard_failed_run_is_red(monkeypatch):
    at = dashboard_at(monkeypatch, last_run_ok=False)
    assert [e.value for e in at.error] == [
        "Posledný ranný beh zlyhal – pozri Nastavenia → Sync a diagnostika"
    ]


def test_dashboard_failed_run_without_any_success_is_red(monkeypatch):
    at = dashboard_at(monkeypatch, last_run_ok=False, last_successful_run=None, morning_run_stale=True)
    assert len(at.error) == 1 and "zlyhal" in at.error[0].value


def test_dashboard_stale_morning_run_is_red_with_its_time(monkeypatch):
    at = dashboard_at(monkeypatch, morning_run_stale=True)
    assert len(at.error) == 1
    assert "starší ako 36 hodín" in at.error[0].value and "23. 10. 2026, 6:01" in at.error[0].value


def test_dashboard_stale_sync_and_stale_morning_run_are_two_messages(monkeypatch):
    patch_dashboard(
        monkeypatch,
        sample_dashboard(
            sync_stale=True, last_sync=dt.date(2026, 9, 26), health=health(morning_run_stale=True)
        ),
    )
    at = run_page("dashboard")
    assert not at.exception
    assert len(at.error) == 2


# --- Nastavenia ---------------------------------------------------------------------------------------------


def runs_table(at):
    tables = [f for f in frames(at) if "Začiatok" in f.columns]
    assert len(tables) == 1
    return tables[0]


def test_nastavenia_table_of_morning_runs_and_errors(monkeypatch):
    runs = [
        sample_run(dt.datetime(2026, 10, 23, 4, 0, 1, tzinfo=UTC), failed="push"),
        sample_run(dt.datetime(2026, 10, 22, 4, 0, 1, tzinfo=UTC)),
        sample_run(
            dt.datetime(2026, 10, 21, 4, 0, 1, tzinfo=UTC),
            steps=[{"name": "sync", "status": "ok", "message": "", "duration_s": 3.0}],
            finished_at=dt.datetime(2026, 10, 21, 4, 3, 5, tzinfo=UTC),
        ),
    ]
    patch_settings(
        monkeypatch,
        diagnostics=sample_diagnostics(
            recent_runs=runs, last_errors=["23. 10. 2026 6:00 – push: Garmin odmietol prihlásenie"]
        ),
    )
    at = run_page("nastavenia")
    assert not at.exception
    table = runs_table(at)
    assert list(table.columns) == ["Začiatok", "Trvanie", "Výsledok", "Sync", "Plán", "Garmin", "Telegram"]
    assert list(table["Začiatok"]) == ["23. 10. 2026 6:00", "22. 10. 2026 6:00", "21. 10. 2026 6:00"]
    assert list(table["Trvanie"]) == ["1:02", "1:02", "3:04"]
    assert list(table["Výsledok"]) == ["Chyba", "OK", "OK"]
    assert list(table["Garmin"]) == ["✗", "✓", "–"]  # failed, ok, step missing
    assert list(table["Telegram"]) == ["–", "✓", "–"]  # skipped after the failure, ok, missing
    assert list(table["Sync"]) == ["✓", "✓", "✓"] and list(table["Plán"]) == ["✓", "✓", "–"]
    assert [w.value for w in at.warning if "push:" in w.value] == [
        "23. 10. 2026 6:00 – push: Garmin odmietol prihlásenie"
    ]
    assert "Žiadne chyby." not in [c.value for c in at.caption]


def test_nastavenia_without_runs_or_errors(monkeypatch):
    patch_settings(monkeypatch, diagnostics=sample_diagnostics(failed_activities=[], failed_wellness_days=[]))
    at = run_page("nastavenia")
    assert not at.exception
    assert all("Začiatok" not in f.columns for f in frames(at))
    captions = [c.value for c in at.caption]
    assert "Žiadne chyby." in captions
    assert "Automatický ranný beh zatiaľ nebežal – návod v docs/OPERATIONS.md." in captions
    assert not at.warning
    assert "Ranné behy" in texts(at)
