# Training Analytics App – project guide for Claude Code

Personal training analytics for a runner/cyclist using a Garmin Forerunner 945 with a chest HR strap
(no power meter). Goal: replace TrainingPeaks + Strava premium metrics, add sleep/performance
correlation and a rule-based coach that pushes workouts back to Garmin.

Read `docs/PLAN.md` (phases, acceptance criteria) and `docs/METRICS.md` (formulas – the single
source of truth) before starting any phase. Keep `docs/STATUS.md` updated at the end of every session.

## Stack

- Python 3.12, managed with `uv`. Backend package: `backend/training/`.
- SQLite via SQLModel/SQLAlchemy, migrations with Alembic. DB file: `data/training.db` (gitignored).
- Garmin data: `garminconnect` library (unofficial Garmin Connect client, uses `garth` tokens).
  Everything is JSON from Garmin Connect – **no FIT files, no manual exports**.
- Metrics: pandas, numpy, scipy, statsmodels. Pure functions, no I/O.
- API: FastAPI (`backend/training/api/`). UI v1: Streamlit (`ui-streamlit/`). UI v2 (later): React + Vite + TS (`frontend/`).
- CLI: Typer (`uv run training <command>`).
- Lint/format: ruff. Tests: pytest.

## Commands

```bash
uv sync                                  # install
uv run training login                    # one-time Garmin login (interactive, MFA prompt), stores tokens in ~/.garminconnect
uv run training sync                     # incremental sync (activities + wellness), then recompute affected days
uv run training backfill --months 24     # first-run history download (resumable)
uv run training recompute                # recompute all metrics from stored raw JSON (no network)
uv run training api                      # FastAPI on :8000
uv run streamlit run ui-streamlit/app.py # Streamlit UI on :8501
uv run pytest -q                         # tests
uv run ruff check . && uv run ruff format .
```

## Architecture rules (non-negotiable)

1. **Layering:** `garmin/` (fetch) → `raw_garmin` table (JSON cache) → `normalize/` → typed tables →
   `metrics/` + `analysis/` (pure functions over pandas) → `services/` (Pydantic DTOs) → UI/API.
2. **`training/` core never imports Streamlit, FastAPI or anything UI-related.** Streamlit pages and
   FastAPI routers are thin: they call `services/*` and render/serialize. Business logic in a page or router is a bug.
3. **Services return Pydantic models** (`training/services/dto.py`). FastAPI serializes them 1:1; the React
   frontend will consume exactly these shapes. Never return raw dicts or DataFrames from a service.
4. **Every Garmin response is stored verbatim** in `raw_garmin` before normalization, so metrics can be
   recomputed forever without hitting the network. `recompute` must work fully offline.
5. **Sync is idempotent and resumable.** Re-running `sync` never duplicates rows; interrupted `backfill` continues from its cursor.
6. **Formulas live only in `docs/METRICS.md`.** Implement exactly what is written there. If a formula
   seems wrong, change the doc first (and say so), then the code. Never silently "improve" constants.
7. **Thresholds are historical.** LTHR / threshold pace have `valid_from` dates; a metric always uses the
   threshold valid at the activity date.
8. **Never store the Garmin password.** Only `garth` tokens in `~/.garminconnect` (path via `GARMINTOKENS`).
   Never print tokens or credentials to logs.
9. **Rate-limit Garmin calls** (default 0.7 s sleep between requests, exponential backoff on 429/5xx).
10. **Sport-aware everything.** Thresholds, zones and load methods are per sport (`run`, `bike`, `other`).

## Testing rules

- Every function in `metrics/` and `analysis/` has tests. Use **synthetic streams with known answers**
  (e.g. 60 min at exactly LTHR → hrTSS == 100 ± 1; flat run → GAP == speed) plus the recorded fixtures.
- Recorded Garmin JSON fixtures live in `backend/tests/fixtures/` (created by `scripts/record_fixtures.py`,
  GPS anonymized). Normalizers are tested against them.
- No network in tests. Mock `garminconnect` at the client boundary (`training/garmin/client.py`).
- Run `uv run pytest -q` before declaring any task done.

## Conventions

- Units internally: seconds, metres, m/s, bpm, local dates as `date`, timestamps as UTC `datetime` with
  the activity's timezone stored separately. Convert to pace (min/km) only in the presentation layer.
- Load unit: "TSS-equivalent points" (1 h at threshold = 100) for all methods (hrTSS, TRIMP_norm, rTSS).
- Naming: `snake_case`, type hints everywhere, docstrings that reference the METRICS.md section (e.g. `# METRICS §2.1`).
- Small, focused modules. No file over ~400 lines.
- Logging via `logging`, never `print` (except CLI output through Typer/rich).
- Config via `training/config.py` (pydantic-settings), env vars prefixed `TRAINING_`.

## Do not

- Do not parse FIT files or add Strava integration unless explicitly asked.
- Do not add a power-based metric; there is no power meter.
- Do not add background threads inside Streamlit for syncing; syncing is a CLI/cron job.
- Do not introduce new heavy dependencies without asking (e.g. no Airflow, no Postgres, no Celery).
- Do not skip Alembic migrations when changing models.

## Working style for each session

1. Read `docs/STATUS.md` to see what is done and what is next.
2. Work on exactly one phase (or one numbered task) from `docs/PLAN.md`.
3. Tests first for metric code; then implementation; then wire into services/UI.
4. Finish by: running tests + ruff, updating `docs/STATUS.md`, proposing a commit message.

## Delegation (subagents in .claude/agents/)

The main session is the orchestrator. Delegate rather than doing everything inline:

- `metrics-implementer` (Opus, test-first) – any formula work in metrics/ or analysis/.
- `ui-page-builder` (Sonnet) – services/DTOs, FastAPI routers, Streamlit pages, Plotly components, later React pages.
- `garmin-explorer` (Sonnet, read-only) – before touching garmin/ or normalize/: exact method names and JSON shapes.
- `test-runner` (Haiku) – every test run; only failures come back.
- `spec-reviewer` (Opus, read-only, has memory) – before every commit; fix Blockers, then re-run.

Parallelize only tasks that touch different directories (e.g. metrics/ vs services/, or different UI pages);
use `isolation: worktree` for parallel implementers and merge in the main session. Keep the orchestrator's
context for planning, integration and decisions – not for reading library source or test logs.
