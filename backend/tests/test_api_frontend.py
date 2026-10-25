"""Phase 9: FastAPI serves the React build (`frontend/dist`) on the API's port; CORS for the dev server;
the committed build matches its sources (users run the app without Node)."""

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from training.api.main import create_app
from training.config import PROJECT_ROOT

FRONTEND = PROJECT_ROOT / "frontend"


@pytest.fixture
def dist(tmp_path) -> Path:
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
    (root / "assets" / "app-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (root / "manifest.webmanifest").write_text("{}", encoding="utf-8")
    (tmp_path / "secret.txt").write_text("nope", encoding="utf-8")
    return root


@pytest.fixture
def client(dist) -> TestClient:
    return TestClient(create_app(frontend_dist=dist, cors_origins=["http://localhost:5173"]))


def test_client_side_routes_get_the_app_shell(client):
    for path in ("/", "/plan", "/aktivity/12", "/nastavenia"):
        response = client.get(path)
        assert response.status_code == 200 and "id=root" in response.text, path
        assert response.headers["cache-control"] == "no-cache"


def test_assets_are_files_and_immutable(client):
    response = client.get("/assets/app-abc123.js")
    assert response.status_code == 200 and response.text == "console.log(1)"
    assert "immutable" in response.headers["cache-control"]
    assert client.get("/manifest.webmanifest").headers["cache-control"] == "no-cache"
    assert client.get("/assets/missing.js").status_code == 404


def test_api_and_docs_are_not_shadowed(client):
    assert client.get("/api/health").json() == {"status": "ok"}
    missing = client.get("/api/does-not-exist")
    assert missing.status_code == 404 and missing.headers["content-type"].startswith("application/json")
    assert client.get("/openapi.json").json()["info"]["title"] == "Training analytics"
    assert "swagger" in client.get("/docs").text.lower()


def test_no_file_outside_dist(client):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%2fsecret.txt"):
        response = client.get(path)
        assert "nope" not in response.text, path


def test_cors_allows_only_the_dev_origin(client):
    ok = client.get("/api/health", headers={"Origin": "http://localhost:5173"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    other = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_without_a_build_only_the_api(tmp_path):
    client = TestClient(create_app(frontend_dist=tmp_path / "missing"))
    assert client.get("/").status_code == 404
    assert client.get("/api/health").status_code == 200


# --- the committed build is current (same algorithm as frontend/scripts/stamp.mjs) -------------------------

INPUTS = ("src", "public", "index.html", "vite.config.ts", "package-lock.json")


def _files(path: str) -> list[str]:
    full = FRONTEND / path
    if full.is_dir():
        return [f for name in sorted(p.name for p in full.iterdir()) for f in _files(f"{path}/{name}")]
    return [path]


def source_hash() -> str:
    digest = hashlib.sha256()
    for file in (f for name in INPUTS for f in _files(name)):
        if ".test." in file or "/test/" in file:
            continue
        digest.update(file.encode())
        digest.update(b"\0")
        digest.update((FRONTEND / file).read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def test_committed_build_matches_its_sources():
    stamp = FRONTEND / "dist" / ".source-hash"
    assert stamp.is_file(), "frontend/dist is missing – run `npm run build` in frontend/"
    assert stamp.read_text(encoding="utf-8").strip() == source_hash(), (
        "frontend/dist is older than frontend/src – run `npm run build` in frontend/ and commit dist/"
    )
