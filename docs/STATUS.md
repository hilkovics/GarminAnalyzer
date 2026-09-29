# STATUS

Last updated: 2026-09-29 (end of phase 0 session)

## Done

### Phase 0 – repository skeleton and Garmin login (code complete; local acceptance steps pending, see Next)
- uv project (Python 3.12) with ruff, pytest and all dependencies from PLAN.md phase 0; `uv.lock` committed.
- Docstring-only modules for every path in PLAN.md §3 (`db/`, `garmin/`, `normalize/`, `metrics/`,
  `analysis/`, `coach/`, `services/`, `api/routers/`), placeholder Streamlit app + pages, `backend/tests/synthetic.py`.
- `training/config.py`: pydantic-settings, `TRAINING_` prefix; `db_path` (default `data/training.db`),
  `garmin_tokens` (also read from `GARMINTOKENS`, default `~/.garminconnect`), `rate_limit_s` (0.7), `max_retries` (5).
- Alembic initialised (`alembic.ini` at the root, scripts in `backend/alembic/`). The DB URL comes from
  config, `render_as_batch=True` for SQLite. There are no migrations yet; the first one comes in phase 1.
- `training/garmin/client.py`: `login_interactive`, `connect` (tokens only), `GarminClient.call` with 0.7 s
  spacing and exponential backoff on 429/5xx (non-retryable: 401, 404, other 4xx).
- CLI: `uv run training login [--email] [--force]` (password prompt hidden, MFA prompt, never echoed) and
  `uv run training whoami`.
- `scripts/record_fixtures.py` records these into `backend/tests/fixtures/`:
  - the last 6 activities (summary, details, splits, HR zones), topped up with a hilly outdoor run and a
    bike ride if the latest 6 have none;
  - 14 days of sleep, RHR, stress and user summary;
  - body battery and max-metrics ranges, training status and the latest lactate threshold;
  - a `manifest.json`.
  Everything is anonymized by `training/garmin/anonymize.py` before writing.
- FastAPI app stub with `/api/health`.
- Tests (25): anonymizer, client spacing/backoff, CLI login/whoami with a mocked client (password never in
  output or token file), record_fixtures with a fake client that checks each call against the real
  `garminconnect.Garmin` signatures, core never imports Streamlit/FastAPI, settings.

## Next

1. **You, locally** (this cannot be done from a cloud session – it needs your credentials and MFA):
   ```bash
   uv sync
   uv run training login          # e-mail, password, MFA code
   uv run training whoami         # should print your name
   uv run python scripts/record_fixtures.py
   ```
   Check the summary lines: it should report a hilly run and a bike ride (otherwise re-run with
   `--search 200`). Skim one `activity_*_details.json` to confirm that no real coordinates or names are left.
   Then commit `backend/tests/fixtures/`.
2. **You, in Garmin Connect:** set HR zones based on %LTHR exactly as in METRICS §1 (Z2 from 68 %, Z3 from 84 %,
   Z4 from 95 %, Z5 above 105 %).
3. **Phase 1** – database models + migration, raw_garmin cache, normalizers (tested against the fixtures),
   sync, backfill, `db-stats`.

## Known issues / open questions

- The phase 0 acceptance criteria (login with MFA, whoami, fixtures with a hilly run and a bike) are **not verified
  yet**. They are pending step 1 above.
- These JSON key paths are unconfirmed from the library source alone and will be locked in by the fixtures in
  phase 1:
  - the detail descriptor keys (`directHeartRate`, `directSpeed`, `directElevation`, `directLatitude`, …);
  - the shape of `get_max_metrics_range`;
  - the unit of `speed` in `get_lactate_threshold`.
- `garminconnect.get_activities_by_date` pages 20 at a time without delay. Phase 1 should paginate
  through `GarminClient.call("get_activities", start, limit)` so every page is rate-limited.
- Open METRICS.md points to decide before the phase that uses them:
  - §0.6 HR-lag direction. Proposal: pair speed(t) with HR(t + 30 s).
  - §10.4 rule 1 "whichever the template has fewer of" needs a deterministic tie-break.
  - §10.6 Z1 IF 0.50 is not the table midpoint (0.30–0.55). Confirm that it is intended.

## Decisions

- 2026-09-29 **METRICS.md fixes** (approved by the user):
  - §1 zone boundaries are half-open intervals, so there are no gaps at 0.835 / 0.945.
  - §7 test value: 10 km in 40:00 gives VDOT 51.94 and a 1:28:33 half marathon (was "≈ 52.5").
  - §10.2 `weekly_target_load = 7 · (CTL_now + 6 · ramp)`. The old formula raised CTL only by ramp/6 per week.
- 2026-09-29 **Single root `pyproject.toml`** instead of `backend/pyproject.toml`. The package is built from
  `backend/training` (hatchling), so every command in CLAUDE.md runs from the repo root.
- 2026-09-29 **garminconnect 0.3.x (pinned `>=0.3.17,<0.4`)**: it no longer uses garth. Tokens are
  `garmin_tokens.json` (DI tokens, written 0600) and refreshed tokens are re-dumped automatically. Old garth tokens are
  not accepted. CLAUDE.md, PLAN.md and garmin-explorer were updated to match.
- 2026-09-29 **Fixture anonymization** uses a random GPS offset per recording that is never saved, since a fixed offset in
  the source would be reversible. Owner names and ids, location names and activity names (Garmin's default name
  contains the town) are replaced.
- 2026-09-29 `record_fixtures` requests details with `maxchart=20000`, so activities up to about 5.5 h keep 1 Hz resolution.
- 2026-09-29 `httpx2` added as a dev dependency because Starlette's TestClient requires it.
- To decide in phase 1: compute grade/gap_speed in `normalize/` or leave them NULL until phase 2.
