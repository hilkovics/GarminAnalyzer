"""Serve the built React app (`frontend/dist`, PLAN phase 9) from FastAPI: one process, one port.

Files of `dist/` are returned as they are; any other path that is not under `/api`, `/docs`, `/redoc` or
`/openapi.json` gets `index.html`, so client-side routes (`/plan`, `/aktivity/12`) survive a reload. The app
shell, the service worker and the manifest are never cached by the browser; hashed assets are immutable.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse

NO_CACHE = {"Cache-Control": "no-cache"}
IMMUTABLE = {"Cache-Control": "public, max-age=31536000, immutable"}
RESERVED = ("api/", "docs", "redoc", "openapi.json")


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    """Register the catch-all route serving `dist`; False (nothing registered) without `dist/index.html`."""
    root = dist.resolve()
    index = root / "index.html"
    if not index.is_file():
        return False

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith(RESERVED):
            raise HTTPException(status_code=404, detail="Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            headers = IMMUTABLE if candidate.parent.name == "assets" else NO_CACHE
            return FileResponse(candidate, headers=headers)
        if Path(path).suffix and not path.endswith(".html"):  # a missing file, not a client-side route
            raise HTTPException(status_code=404, detail="Not Found")
        return FileResponse(index, headers=NO_CACHE)

    return True
