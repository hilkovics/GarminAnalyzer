# STATUS

Last updated: 2026-09-29 (phase 3 session)

## Done

### Phase 3 – services, API and Streamlit UI v1 (code complete; check against your real DB pending)
- `services/dto.py` holds the fixed DTO contract (PLAN §5), written by the orchestrator first, so that two
  ui-page-builder subagents could work in parallel worktrees.
- Services (`activities`, `fitness`, `settings`, `sync`, `diagnostics`, `lttb`, `mappers`) return DTOs only.
  - Streams are LTTB-downsampled; `gap_speed` / `grade` come from `metrics.preprocess`.
  - The dashboard compares this week with the mean of the previous four.
  - `run_sync` turns auth, 429 and network errors into user-facing `ServiceError`s.
- FastAPI app (`training api`), prefix `/api`, with every endpoint of PLAN §5 used through phase 3.
  - Errors map as NotFound → 404, InvalidInput → 422, ServiceError → 502.
  - operationIds are function names, for the phase-9 codegen.
  - `training export-openapi` writes `docs/openapi.json` and `docs/API.md`. A test fails if they are stale.
- Streamlit UI (Slovak, `uv run streamlit run ui-streamlit/app.py`):
  - `views/`: Dashboard, Aktivity (list and detail with streams chart, laps, zones, load breakdown, RPE form),
    Fitness (PMC with the 90-day warming-up band, weekly bars), Nastavenia (athlete, threshold history and
    form, zone preview, diagnostics, "Spustiť sync teraz").
  - `sections/` and `components/` hold the Plotly figures: DTO in, figure out.
  - Progres, Spánok and Plán are placeholders.
- `scripts/seed_demo.py` builds a synthetic 150-day demo DB, so the UI and API can be tried without Garmin.
- **Visual check:** every page and settings tab was rendered in headless Chromium against the demo DB, with no
  exceptions. The dashboard, activity detail, PMC band, zone tables and diagnostics (r = 0.92) look right.
  `GET /api/fitness/pmc` returns the service DTO (tested), plus 404 paths and stream downsampling (195 points
  from 6022).
  Fixed after the check:
  - `/dashboard` URL → the default page is served at `/`;
  - the speed metric was truncated;
  - the rest-HR override couldn't be cleared (`AthleteIn.clear_rest_hr_override`).
- Spec review of phase 3 (2026-09-29) found no Blockers. Warnings fixed:
  - Saving the athlete recomputed all metrics even for a weight change. Now it recomputes only when sex, max HR
    or rest HR actually change; the write is atomic and the page shows a spinner.
  - The run-threshold form now prefills today's pace (a missing pace would silently switch runs to hrTSS), and
    pace is ignored for bike.
  - `subjective` is one row per activity: a unique index (migration `0002`), with the same ordering for read
    and upsert.
  Nits fixed:
  - the Fitness range covers exactly N days;
  - the LTTB budget reserves the forced end points;
  - clearing the rest HR on an empty DB no longer creates a row;
  - unexpected sync errors show a generic message instead of a traceback;
  - raw kinds moved to `db/raw_kinds.py`, which also resolves the old db → garmin dependency.
- Tests: 798 passed, 5 skipped. They cover services on a seeded DB, every API endpoint including 404/422, and
  every page through AppTest with faked services.
  They also check that PUT /settings/thresholds changes only activities from `valid_from` on.

### Phase 2 – load metrics and PMC (code complete; real-data report pending, see Next)
- `metrics/` (pure, test-first by two metrics-implementer subagents in parallel worktrees):
  - `preprocess.py` implements METRICS §0.3–§0.6: HR validity, coverage and low_confidence; speed clamp and slow
    flag; 5-sample median altitude; 10 s centred grade; `lag_hr` helper for phase 4.
  - `zones.py` implements §1: half-open HR and pace zones, time in zone, default zone JSON.
  - `gap.py` implements §3 (Minetti cost, GAP).
  - `load.py` implements §2: hrTSS through the IF table, TRIMP and TRIMP_norm, NGS and rTSS, usable-GPS check,
    and the §2.5 `load_sanity`.
  - `activity.py` runs the above for one activity, including §2.4 primary selection.
  - `pmc.py` implements §4: daily load series, CTL/ATL/TSB, ACWR with bands, monotony, strain, ramp and warning,
    and weekly ISO aggregates with polarization.
- `training/pipeline.py` connects the DB to the metrics:
  - thresholds are resolved by activity date, and `other` uses the run threshold;
  - rest HR is the athlete override, else the 28-day median RHR;
  - it upserts `activity_metric` and recomputes `daily_load` for the whole series (keeping `readiness`);
  - `recompute`, `update_after_sync` (affected activities, plus the last 28 days when wellness changed) and
    `set_threshold` (only activities from `valid_from` on) are the entry points.
- `services/diagnostics.py` returns `DiagnosticsDTO` with:
  - sync state, pending and failed queues;
  - the §2.5 Pearson r against Garmin training load;
  - the low-confidence share, and runs where hrTSS and rTSS differ by more than 40 %.
- CLI (now a `training/cli/` package):
  - `recompute [--since] [--metrics-only]`;
  - `threshold add --sport --lthr [--pace m:ss] --valid-from` and `threshold list`;
  - `athlete --sex --max-hr --rest-hr …`;
  - `diagnostics`.
  `sync` and `backfill` recompute metrics for what they changed.
- Tests: 470 passed, 5 skipped. They include:
  - hrTSS exactly 100 for 1 h at LTHR (and 56.25 at r = 0.83), TRIMP_norm = 100, rTSS = 100 at threshold speed,
    and GAP of 4.1446 at +10 %;
  - every zone edge, and a hand-computed 10-day PMC checked against exact fractions;
  - every ACWR band;
  - historical thresholds, where a new LTHR changes only later activities;
  - a full `recompute` from raw that equals the incremental result, plus the CLI commands.
  The PMC tests were mutation-checked: 17 deliberate code changes, all caught.
- Spec review of phase 2 (2026-09-29): every constant and clarification matches METRICS. It found 1 Blocker,
  fixed: an interrupted sync/backfill left normalized activities without metrics, which silently dropped them
  from the PMC.
  - "Metrics needed" markers (`metrics_dirty_activities` / `metrics_dirty_wellness_days`) are now written with
    the typed rows and cleared only after `update_after_sync` has computed them. It also picks up any
    activity without an `activity_metric` row.
  Warnings fixed:
  - the PMC series now ends at the latest of the data, the last sync dates and an explicit `end`, and
    `readiness` is kept. Every CLI command also passes today. Round 2 found that `recompute` did not; that
    is fixed, and the default no longer depends on the caller;
  - a wellness change on day W recomputes activities on W..W+27, the RHR median window for TRIMP (edges tested);
  - an activity whose metric computation fails keeps its marker and is retried;
  - the `sync_state` keys moved to `db/state_keys.py`, so the offline pipeline no longer imports the fetch
    layer.
  Nits fixed:
  - hrTSS/rTSS divergence is measured against the smaller value;
  - `load_sanity` tests constancy exactly;
  - a new `activities_without_load` count;
  - pace input validation, and `--pace` is rejected for bike;
  - `training athlete` without options no longer creates an empty row;
  - the full divergent-id list is printed;
  - streams are loaded through table columns (faster).
- Tests: 483 passed, 5 skipped (spec review round 2: no blockers left).

### Phase 1 – database, sync and backfill (code complete; local acceptance steps pending, see Next)
- SQLModel models for every table in PLAN §4 (`db/models.py`) and the initial Alembic migration
  (`0001_initial_schema`). A test checks that the migrated schema equals the models.
- `db/repo.py` provides idempotent upserts:
  - `raw_garmin` by (kind, ref_key), with a SHA-256 for change detection;
  - `activity` by garmin_id;
  - `activity_stream` replaced per activity;
  - `daily_wellness` by date;
  - `sync_state` key/value.
- `db/rebuild.py` normalizes activities and wellness from `raw_garmin` only, so the typed tables can be rebuilt
  offline. Sync uses the same functions.
- `garmin/client.py` has one method per endpoint. Every response goes to raw_garmin before it is returned
  (committed immediately). The activity list is paged through the rate-limited client (100 per page).
  Detail requests set `maxChartSize` to the activity duration, so 1 Hz data is not downsampled.
- `normalize/` (pure):
  - `normalize_activity` (summary with list-item fallback);
  - `normalize_streams` (descriptor-key mapping, 1 s grid, forward-fill ≤ 10 s, timer-based `moving`, speed from
    distance if the speed channel is missing);
  - `normalize_wellness` (sleep with GMT timestamps, RHR, stress, body battery via descriptors, user summary).
- `garmin/sync.py` (incremental):
  - activities since `last_activity_sync` − 2 days; a known activity is re-fetched only if its list item changed;
  - wellness from `last_wellness_date` to today;
  - training status / max metrics / lactate threshold are stored raw for today.
  One failing endpoint is logged and the run continues.
- `garmin/backfill.py` walks month by month backwards, with `backfill_cursor` saved after every month. Rerunning
  resumes, a larger `--months` extends the history, and already stored days/activities are skipped.
- CLI: `training sync`, `training backfill --months N`, `training db-stats`. 429 errors, rejected tokens and
  Ctrl+C give a clean message ("progress is saved – run again").
- Transient failures are retried, never lost. Before an activity is fetched it goes onto `pending_activities` in
  sync_state. Its list item (the "fully fetched" marker) is stored only when no endpoint failed with a non-404
  error. Wellness days work the same way through `pending_wellness_days`. Every sync/backfill retries pending
  work first, regardless of the date window. Days without any data are not written.
- Retries are bounded. After 5 failed runs an activity or day moves to `failed_activities` /
  `failed_wellness_days`. It is shown by `db-stats` and in the sync report, and it is retried only when its list
  item changes or with `training sync --retry-failed`. Nothing is fetched twice in one run.
  Transient = `is_retryable` (5xx, 429, network); 404, other 4xx and parse errors are permanent.
- `training backfill --restart` walks the range again, which picks up activities edited later in Garmin Connect.
  - It costs one list call per month; unchanged activities are skipped.
  - Days are skipped when they have a wellness row, or when all 5 endpoints answered and the day is not pending
    (days that simply have no data).
  - Only days whose endpoints return 404 are fetched again.
- Spec review of phase 1 (2026-09-29) found 3 Blockers, all fixed:
  - A failed or interrupted fetch used up an activity's change signal, so the activity was never fetched again.
  - Failed wellness days were stored as all-NULL rows and never retried.
  - The ≤ 10 s forward-fill was not applied to nulls inside a channel.
  Warnings fixed:
  - METRICS §0.1/§0.2/§0.4 interpretations moved into METRICS.md;
  - a network error ended the CLI with a traceback;
  - the resume sample of a pause was marked paused;
  - the STATUS note about old edits was wrong (now `--restart`).
- Spec review round 2 (2026-09-29) found no Blockers. Warnings fixed:
  - Ctrl+C during normalization left an updated activity stale. The completion marker, rows and pending removal
    now commit together.
  - 4xx errors counted as transient.
  - Retries were unbounded and happened twice per run.
  - `--restart` re-fetched days without data.
  The t = 0 rule was added to METRICS §0.2.
- Tests: 223 passed, 5 skipped (real-fixture conformance; they skip until fixtures are recorded).
  - Normalizers are tested against hand-made Garmin-shaped JSON in `backend/tests/fixtures/synthetic/`.
  - Sync is run twice and gives identical rows; a changed list item is re-fetched; failing endpoints are
    tolerated.
  - An interrupted backfill resumes without re-fetching finished months.
  - `rebuild_all` from raw works without network.
  - The CLI `sync` and `db-stats` commands are exercised against a temp DB.

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
3. **You, locally, after the fixtures are committed:** run `uv run pytest -q`. `test_fixture_conformance.py`
   then checks every guessed Garmin key against your real data (see Known issues); send Claude any failures.
4. **You, locally – phase 1 acceptance:** run `uv run training backfill --months 24`. It takes roughly 1–2 h at
   0.7 s per request: about 5 wellness calls per day, 4 per activity, and the list pages. Interrupt it once with
   Ctrl+C and run it again to check that it resumes. Then run `uv run training sync` twice and
   `uv run training db-stats`: the counts must not change on the second sync.
5. **You, locally – phase 2 report**, after the backfill. PLAN phase 2 asks for these numbers, and they need
   your real data:
   ```bash
   uv run training athlete --sex male --max-hr <max>
   uv run training threshold add --sport run  --lthr <bpm> --pace <m:ss> --valid-from 2024-01-01
   uv run training threshold add --sport bike --lthr <bpm> --valid-from 2024-01-01
   uv run training diagnostics
   ```
   The output gives the number of activities, the low-confidence share, Pearson r against Garmin training load
   (expect > 0.8; below 0.7 means review your LTHR first), and the runs where hrTSS and rTSS differ by more than
   40 %. Also compare time in zones for 5 activities with Garmin Connect (PLAN §7); it should match almost exactly.
6. **You, locally – phase 3 check:** run `uv run streamlit run ui-streamlit/app.py` against your real DB, and
   compare `GET /api/fitness/pmc` (`uv run training api`) with the Fitness page. Change an LTHR in Nastavenia
   with a `valid_from` in the middle of your history: only later activities may change.
7. **Phase 4** – progress without power: EF, decoupling, speed–HR curve, best efforts, threshold proposals,
   predictions.

## Known issues / open questions

- Phase 3 open points:
  - The lap keys (`lapDTOs[].duration/distance/averageHR/maxHR/averageSpeed/elevationGain`) are unverified until
    real fixtures exist.
  - `sync_stale` compares dates, not hours: stale if the last sync is 2 or more calendar days old. `sync_state`
    has no timestamps.
  - There is no CORS middleware yet (phase 9, React).
  - The UI computes the page count itself (`ActivityListDTO` has no `pages`).
  - METRICS gives no monotony threshold, so Fitness shows the value without a flag.
- Phase 2 interpretation choices, all literal to METRICS:
  - An empty stream or an activity without HR gives null hrTSS / IF_hr / TRIMP (METRICS §2.1, changed).
  - When `lthr ≤ rest_hr`, TRIMP_norm is null.
  - Indoor runs with a threshold_speed still get pace-zone times (rTSS stays null without usable GPS).
  - `other` uses the run speed limits.
  - NGS needs 30 full trailing windows, so at least 59 samples.
  - A Pearson r with zero variance is "insufficient".
  - `lag_hr` shifts by array position, so apply it to pause-free series (phase 4).
- The IF-table point (0.83, 0.75) sits on the old Z2/Z3 edge. It is harmless, since the table is independent of
  zones, but the 56.25 test value depends on it.

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
- **Garmin keys still to verify against real fixtures.** The phase 1 normalizers use keys taken from library source
  and Garmin's usual shapes. The conformance test checks them, and the strict checks compare moving seconds and the
  last `sumDistance` against the summary and verify the timezone offset. The main guesses:
  - detail descriptor keys (`directHeartRate`, `directSpeed`, `directElevation`, `directRunCadence` /
    `directBikeCadence`, `directLatitude` / `directLongitude`, `sumDistance`, `sumDuration`, `directTimestamp`) and
    their units. `directRunCadence` may be strides/min, not steps/min.
  - `summaryDTO.averageBikeCadence`, `summaryDTO.vO2MaxValue` (probably list-item only), and whether
    `summaryDTO.duration` is timer time.
  - `dailySleepDTO.sleepScores.overall.value`, `bodyBatteryAtWakeTime`, `avgStressLevel`, and the body-battery
    descriptor fields.
- Weight (`daily_wellness.weight_kg`) is not fetched yet. It needs `get_body_composition`, which can be added once
  a phase needs it.
- Sync looks back only 2 days, as the spec says. An activity edited in Garmin Connect more than 2 days after it
  was recorded is not picked up by `sync`. `training backfill --months N --restart` picks it up.
- If page N of an activity list fails, pages 1..N−1 of that call are not stored raw. The whole call is retried on
  the next run, so nothing is lost.
- Open METRICS.md points to decide before the phase that uses them:
  - §0.6 HR-lag direction. Proposal: pair speed(t) with HR(t + 30 s).
  - §10.4 rule 1 "whichever the template has fewer of" needs a deterministic tie-break.
  - §10.6 Z1 IF 0.50 is not the table midpoint (0.30–0.55). Confirm that it is intended.

## Decisions

- 2026-09-29 **The user approved two METRICS changes (§2.1, §3)**, implemented test-first by the metrics-implementer.
  - An activity without any valid HR sample has null hrTSS / IF_hr / TRIMP / TRIMP_norm, and so a null load
    unless rTSS applies. It still adds 0 to the PMC; `time_in_hr_zone` stays all zeros.
  - `gap_speed` is clamped to 0–7 m/s. A run entirely at +30 % grade is now capped at rTSS ≈ 544 per hour
    instead of ≈ 1221.

- 2026-09-29 **Metric orchestration lives in `training/pipeline.py`, not `metrics/pipeline.py`** (PLAN §6 phase 2),
  so that `metrics/` stays pure (CLAUDE.md). The CLI became a package `training/cli/` (auth, ingest, metrics)
  to stay under ~400 lines per file.
- 2026-09-29 **`activity_stream.grade` / `gap_speed` stay NULL in the DB.** Preprocessing computes them on the fly
  for each metric run (METRICS §0.5, §3), so they always follow the current formula. Persist them only if a phase
  needs them from SQL.
- 2026-09-29 **hrTSS vs rTSS divergence** ("> 40 %", PLAN phase 2) is `|a − b| / min(a, b)`, the more sensitive
  reading.
- 2026-09-29 **The PMC is always recomputed for the whole series.** CTL/ATL are recursive from 0, so a partial
  recompute would change values. It covers 2 years in well under a second.

- 2026-09-29 **Phase 2 METRICS clarifications written first**, marked "Clarified 2026-09-29 (phase 2, approved)"
  in §0.3–§0.5, §1, §2.1–§2.3, §2.5 and §4. They resolve points the spec leaves open:
  - window alignment and minimum periods;
  - population vs sample standard deviation for monotony;
  - which samples each sum runs over;
  - threshold resolution for `other`;
  - the JSON shapes.
  **Approved by the user on 2026-09-29.**

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
- 2026-09-29 **grade and gap_speed stay NULL in phase 1.** They are computed in phase 2 by `metrics/preprocess.py`
  and `metrics/gap.py` (METRICS §0.5, §3). `normalize/` only applies METRICS §0.1 (1 s grid, forward-fill ≤ 10 s)
  and §0.2 (`moving` = timer running, derived from `sumDuration`), plus the §0.4 speed derivation when the speed
  channel is missing. HR validity, clamping, altitude smoothing and lag (§0.3–0.6) are phase 2 preprocessing.
- 2026-09-29 **Stream normalization rules are now in METRICS.md** (§0.1, §0.2 and §0.4, marked "clarified
  2026-09-29"; changed in the doc first, per rule 6). **Approved by the user on 2026-09-29**:
  - Per channel, a gap is the time between consecutive valid values. If it is ≤ 10 s it is forward-filled, and
    this also covers nulls inside a channel.
  - Samples are bucketed per second with floor, and the last sample in a second wins.
  - In a pause gap, the running seconds are the last ones, so the resume sample counts as running.
  - When there is no speed channel, speed is derived from Δdistance (the derivation only; clamping is phase 2),
    and it is NaN across gaps > 10 s.
  - The grid is capped at 3 days as a safeguard against corrupt timestamps.
- 2026-09-29 **Timestamps are timezone-aware UTC** (SQLModel 0.0.47 `UTCDateTime` rejects naive values).
  `local_date` is a `date` and `tz` holds the IANA name, or a "+HH:MM" offset when no name is available.
- 2026-09-29 **Schema additions to PLAN §4:**
  - `raw_garmin` has `payload_sha256` and is unique on (kind, ref_key);
  - raw kinds `activity_list`, `activity_list_item` and `lactate_threshold` were added;
  - `activity_stream` has a cumulative `distance` column (needed for grade, METRICS §0.5);
  - `activity.moving_s` is Garmin's `movingDuration`. The metrics compute their own moving time from the stream.
- 2026-09-29 **The activity list is paged by us** (`connectapi` on the same search endpoint, 100 per page) instead of
  `get_activities_by_date`, which pages 20 at a time with no delay (rule 9).
- 2026-09-29 **Backfill fetches 5 wellness endpoints per day** (sleep, user summary, RHR, stress, body battery), so the
  raw cache is complete. Training status, max metrics and lactate threshold are stored for the sync day only.
