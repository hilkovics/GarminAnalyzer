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
- `training/garmin/client.py`:
  - `login_interactive`: `--force` moves the old tokens aside and restores them if the login fails.
  - `connect`: tokens only.
  - `GarminClient.call`: keeps 0.7 s between the end of one request and the start of the next, and backs off
    exponentially on 429, 5xx and network errors. 401, 404, other 4xx and parse errors fail fast.
    garminconnect's own retry layer is disabled (`retry_attempts=0`).
- CLI: `uv run training login [--email] [--force]` (password prompt hidden, MFA prompt, never echoed) and
  `uv run training whoami`.
- `scripts/record_fixtures.py` records these into `backend/tests/fixtures/`:
  - the last 6 activities (summary, details, splits, HR zones), topped up with a hilly outdoor run and a
    bike ride if the latest 6 have none;
  - 14 days of sleep, RHR, stress and user summary;
  - body battery and max-metrics ranges, training status and the latest lactate threshold;
  - a `manifest.json`.
  Everything is anonymized by `training/garmin/anonymize.py` before writing. On top of that, each file is scanned for your
  real name, display name, profile id and real start coordinates (`find_leaks`). A hit aborts the run
  (exit code 2) before that file is written.
- FastAPI app stub with `/api/health`.
- Tests (66):
  - the anonymizer: rotation preserves distances to 0.1 mm; a realistic `geoPolylineDTO` with min/max lat/lon;
    unpaired coordinates are dropped; case-insensitive PII keys; numeric serials; id remapping across files,
    including multisport `parentId`/`childIds`; `find_leaks` reports key paths and avoids substring false
    positives;
  - client spacing/backoff, with errors produced by garminconnect's real error decorator;
  - CLI login/whoami/`--force` with a mocked client (the password never appears in output or in the token file);
  - record_fixtures against a fake client that checks each call against the real `garminconnect.Garmin`
    signatures, plus the leak guard;
  - core never imports Streamlit/FastAPI, and settings.
- Spec review, round 1 (2026-09-29), found 3 Blockers, all fixed:
  - GPS bounding-box keys `minLat`/`maxLat`/`minLon`/`maxLon` were not shifted;
  - case variants such as `userInfoDto.fullname`, and `userId`, were not scrubbed;
  - the retry classifier retried every error, because 0.3.x puts no `.response` on its exceptions.
  Warnings fixed:
  - duplicate library retries;
  - token file patterns missing from `.gitignore`;
  - activity/device ids and serials were not remapped;
  - tests could overwrite real tokens through `TRAINING_GARMIN_TOKENS`;
  - `--force` logged the user out when the new login failed.
- Spec review, round 2 (2026-09-29): no Blockers. Warnings fixed:
  - A constant lat/lon offset could be undone, since real distances reveal the real latitude through cos φ. It is
    replaced by a random rigid rotation of the sphere (see Decisions).
  - Numeric serial numbers were not scrubbed.
  - `find_leaks` matched substrings of keys and words ("run" matched `running`), and its findings did not say
    where the hit was.
  - The `training` CLI did not explicitly hide traceback locals. A test now checks it.
- Spec review, round 3 (2026-09-29), found 1 Blocker, fixed: rotating the `minLat`/`maxLon` bounding-box corners
  let the real pole be solved for, recovering the latitude exactly. Real-frame extrema and north-relative values
  (heading, bearing, course, direction) are now dropped. Duplicate or string coordinates, `*Long` and
  `UPPER_SNAKE` keys are hardened as well.
  When checking real fixtures, confirm that no other bearing- or extremum-like fields exist.

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
- The GPS rotation keeps a route's shape (rotated on the globe, never mirrored) and its absolute altitude, and the
  timezone name in the summaries is left as is. Distances are exact on a sphere, but Garmin measures on the WGS84
  ellipsoid, so a latitude-dependent distance error of about 0.1–0.4 % remains (below the watch's own noise). Matching the altitude profile against a global elevation model is
  theoretically possible but expensive. If it matters, trim the first/last ~300 m of each activity before committing.
- Leak guard false positives: two fractional physiological values in one object that happen to lie within 0.05°
  of your real start latitude *and* longitude (e.g. stress percentages 48.13 / 17.12) abort the run. The same
  happens on every re-run. The error names the file and the JSON key path, never the values, so a false
  positive is easy to recognise; if it happens, tell Claude which path it names.
- `get_lactate_threshold(latest=True)` makes 2 HTTP requests inside one `GarminClient.call`, so the 0.7 s spacing
  only applies around the pair.
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
- 2026-09-29 **Fixture anonymization: random rigid rotation of the sphere** per recording, never saved.
  It moves every real start point at least 10° (≈ 1100 km) and preserves every distance exactly.
  - A constant offset was rejected: the spec reviewer recovered the latitude shift to about 1 km from `sumDistance`
    via cos φ.
  - Latitude and longitude are rotated as pairs, including detail-metric columns and bounding boxes. Unpaired
    values are dropped.
  - PLAN.md phase 0 was updated first.
  - Owner names and ids, location and activity names (Garmin's default name contains the town), descriptions and
    serials are replaced.
- 2026-09-29 `record_fixtures` requests details with `maxchart=20000`, so activities up to about 5.5 h keep 1 Hz resolution.
- 2026-09-29 `httpx2` added as a dev dependency because Starlette's TestClient requires it. `requests`, which garminconnect
  already brings in, is now declared explicitly because `garmin/client.py` uses its exception types.
- 2026-09-29 Fake ids in fixtures start at 900000001 and are consistent across all files of one recording.
- To decide in phase 1: compute grade/gap_speed in `normalize/` or leave them NULL until phase 2.
