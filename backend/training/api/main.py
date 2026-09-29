"""FastAPI application factory (PLAN.md §5). Routers are thin: they call `training.services`, return DTOs."""

from fastapi import FastAPI
from fastapi.routing import APIRoute

from training.api.errors import register_error_handlers
from training.api.routers import activities, fitness, progress, settings, sync, wellness

API_PREFIX = "/api"


def operation_id(route: APIRoute) -> str:
    """The route function's name (`get_pmc`, `list_activities`, …): readable names for generated clients."""
    return route.name


def create_app() -> FastAPI:
    app = FastAPI(
        title="Training analytics",
        generate_unique_id_function=operation_id,
        version="0.1.0",
        description="API over the training services; the DTOs are the same ones the Streamlit UI renders.",
    )
    register_error_handlers(app)
    for module in (activities, fitness, progress, settings, sync, wellness):
        app.include_router(module.router, prefix=API_PREFIX)

    @app.get(f"{API_PREFIX}/health", tags=["health"], summary="Liveness check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
