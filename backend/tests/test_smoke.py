import importlib
import pkgutil
import re
from pathlib import Path

from fastapi.testclient import TestClient

import training
from training.api.main import create_app
from training.config import Settings


def test_every_core_module_imports_without_ui_dependencies():
    """CLAUDE.md rule 2: the core never imports Streamlit (FastAPI is allowed only under training.api)."""
    for mod in pkgutil.walk_packages(training.__path__, prefix="training."):
        module = importlib.import_module(mod.name)
        imports = [
            line
            for line in Path(module.__file__).read_text().splitlines()
            if re.match(r"\s*(import|from)\s", line)
        ]
        assert not any(re.search(r"\bstreamlit\b", line) for line in imports), mod.name
        if not mod.name.startswith("training.api"):
            assert not any(re.search(r"\bfastapi\b", line) for line in imports), mod.name


def test_settings_defaults_and_env(monkeypatch, tmp_path):
    for var in ("GARMINTOKENS", "TRAINING_GARMIN_TOKENS", "TRAINING_DB_PATH", "TRAINING_RATE_LIMIT_S"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)
    assert s.rate_limit_s == 0.7
    assert s.db_path.name == "training.db"
    assert s.tokens_dir == Path("~/.garminconnect").expanduser()

    monkeypatch.setenv("GARMINTOKENS", str(tmp_path / "tok"))
    monkeypatch.setenv("TRAINING_DB_PATH", str(tmp_path / "x.db"))
    s = Settings(_env_file=None)
    assert s.tokens_dir == tmp_path / "tok"
    assert s.db_url.endswith("/x.db")


def test_api_health():
    assert TestClient(create_app()).get("/api/health").json() == {"status": "ok"}
