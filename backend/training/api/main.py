"""FastAPI application factory (PLAN.md §5). Routers are thin: they call `training.services`, return DTOs."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from training.api.errors import register_error_handlers
from training.api.frontend import mount_frontend
from training.api.routers import activities, fitness, plan, progress, reports, settings, sync, wellness

API_PREFIX = "/api"


def operation_id(route: APIRoute) -> str:
    """The route function's name (`get_pmc`, `list_activities`, …): readable names for generated clients."""
    return route.name


def create_app(*, frontend_dist: Path | None = None, cors_origins: list[str] | None = None) -> FastAPI:
    """The API under /api; with `frontend_dist` (default from settings) also the React app at /."""
    from training.config import get_settings

    config = get_settings()
    if frontend_dist is None and config.serve_frontend:
        frontend_dist = config.frontend_dist
    app = FastAPI(
        title="Training analytics",
        generate_unique_id_function=operation_id,
        version="0.1.0",
        description="API over the training services; the DTOs are the same ones the Streamlit UI renders.",
    )
    register_error_handlers(app)
    origins = config.cors_origins if cors_origins is None else cors_origins
    if origins:
        app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"])
    for module in (activities, fitness, plan, progress, reports, settings, sync, wellness):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get(f"{API_PREFIX}/health", tags=["health"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    if frontend_dist is not None:
        mount_frontend(app, frontend_dist)  # last: its catch-all route must not shadow /api or /docs
    return app


app = create_app()
