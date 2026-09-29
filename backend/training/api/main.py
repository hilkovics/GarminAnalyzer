"""FastAPI application factory. Routers are added from phase 3 (PLAN.md §5)."""

from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Training analytics", version="0.1.0")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
