"""`training api` (serve the FastAPI app) and `training export-openapi` (docs/openapi.json + docs/API.md)."""

from pathlib import Path

import typer

from training.cli._app import app, console
from training.config import PROJECT_ROOT


@app.command("api")
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (keep it local: no auth)."),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Serve the FastAPI app (interactive docs at /docs)."""
    import uvicorn

    uvicorn.run("training.api.main:app", host=host, port=port)


@app.command("export-openapi")
def export_openapi(
    out_dir: Path = typer.Option(
        PROJECT_ROOT / "docs", "--out-dir", help="Where openapi.json and API.md go."
    ),
) -> None:
    """Write docs/openapi.json and docs/API.md from the FastAPI app."""
    from training.api.export import build_spec, render_api_md, render_openapi_json

    spec = build_spec()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "openapi.json").write_text(render_openapi_json(spec))
    (out_dir / "API.md").write_text(render_api_md(spec))
    console.print(f"Wrote {out_dir / 'openapi.json'} and {out_dir / 'API.md'} ({len(spec['paths'])} paths)")
