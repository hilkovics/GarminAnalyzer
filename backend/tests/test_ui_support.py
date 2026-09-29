"""Plumbing for the Streamlit UI tests: importing `ui-streamlit/`, dummy DB session, faked services, AppTest.

The UI lives in `ui-streamlit/` (a directory with a hyphen, so it is not importable as a package). The pages
import `_db`, `components` and `sections` as top-level modules, exactly as `streamlit run ui-streamlit/app.py`
does, so the tests put that directory on `sys.path`. No database is used: `_db.session` is replaced by a dummy
context manager and every service function is monkeypatched (see `test_ui_samples.py` for the sample DTOs).
"""

import datetime as dt
import importlib
import json
import sys
import types
from contextlib import contextmanager
from pathlib import Path

from streamlit.testing.v1 import AppTest

UI_DIR = Path(__file__).resolve().parents[2] / "ui-streamlit"
TODAY = dt.date(2026, 9, 29)
MONDAY = dt.date(2026, 9, 28)


# --- plumbing -----------------------------------------------------------------------------------------------


@contextmanager
def dummy_session():
    yield object()


def ui_module(name: str):
    """Import a module of `ui-streamlit/` (`_db`, `components.format`, …) as the pages do."""
    if str(UI_DIR) not in sys.path:
        sys.path.insert(0, str(UI_DIR))
    return importlib.import_module(name)


def setup_ui(monkeypatch) -> None:
    """Make `ui-streamlit/` importable, replace the DB session by a dummy and freeze "today"."""
    db = ui_module("_db")
    monkeypatch.setattr(db, "session", dummy_session)
    monkeypatch.setattr(db, "today", lambda: TODAY)


_FAKE_SERVICE_MODULES: dict[str, types.ModuleType] = {}


def patch_service(monkeypatch, name: str, **functions):
    """Replace functions of `training.services.<name>`; a module that does not exist yet is faked.

    Pages call services through the module attribute, so patching the attribute is enough. A faked module
    stays installed for the whole test session (pages bind it at their first import, so a fresh fake per test
    would be invisible to them); only its patched attributes are restored after each test.
    """
    package = importlib.import_module("training.services")
    try:
        module = importlib.import_module(f"training.services.{name}")
    except ImportError:
        module = _FAKE_SERVICE_MODULES.setdefault(name, types.ModuleType(f"training.services.{name}"))
        sys.modules[f"training.services.{name}"] = module
        setattr(package, name, module)
    for fn_name, fn in functions.items():
        monkeypatch.setattr(module, fn_name, fn, raising=False)
    return module


def run_page(name: str, *, query: dict[str, str] | None = None) -> AppTest:
    """Run `ui-streamlit/views/<name>.py` and return the AppTest (already run once)."""
    at = AppTest.from_file(str(UI_DIR / "views" / f"{name}.py"), default_timeout=20)
    for key, value in (query or {}).items():
        at.query_params[key] = value
    return at.run()


def figures(at: AppTest) -> list[dict]:
    """The Plotly figures rendered by the page, as `{"data": [...], "layout": {...}}` dicts, in page order."""
    return [json.loads(el.proto.spec) for el in at.get("plotly_chart")]


def trace_names(figure: dict) -> list[str | None]:
    return [t.get("name") for t in figure["data"]]


def texts(at: AppTest) -> str:
    """All rendered text (titles, captions, markdown, metrics, alerts) joined for substring assertions."""
    parts: list[str] = []
    for group in (
        at.title,
        at.header,
        at.subheader,
        at.markdown,
        at.caption,
        at.info,
        at.warning,
        at.error,
        at.success,
    ):
        parts += [str(el.value) for el in group]
    for metric in at.metric:
        parts += [str(metric.label), str(metric.value)]
    return "\n".join(parts).replace("**", "")  # drop markdown bold markers
