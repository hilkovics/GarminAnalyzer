"""`training` command line (Typer). Commands are thin wrappers; logic lives in the core packages.

Phase 0: `login`, `whoami` (auth.py). Phase 1: `sync`, `backfill`, `db-stats` (ingest.py).
Phase 2: `recompute`, `threshold`, `athlete`, `diagnostics` (metrics.py).
Phase 3: `api`, `export-openapi` (api.py). Phase 4: `propose-thresholds` (progress.py).
Unit conversions (pace ↔ m/s) happen here, never in the core.
"""

from training.cli import api, auth, ingest, metrics, progress  # noqa: F401  (register commands)
from training.cli._app import app

__all__ = ["app"]

if __name__ == "__main__":
    app()
