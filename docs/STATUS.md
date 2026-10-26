# STATUS

Last updated: 2026-10-26 (coach "Kondícia" step 2)

## Done

### Coach "Kondícia" – step 2: block progress (2026-10-26, METRICS §11.4)
- **Pure** `training/coach/block_progress.py`: fitness snapshot on a day (28-day median pace at the reference
  HR, §5.2 EF trend, §7 reference VDOT with Daniels 5/10 km), change vs the baseline, check-run result
  (Daniels from the 30-min `gap_speed` effort), block summary (menu items, run time, brake weeks, sleep,
  readiness, green-day share). 7 known-answer tests.
- **Glue** `planning_block.py`: baseline = snapshot of the day before the block, stored in
  `coach_block.baseline` (filled lazily, refreshed by `training recompute`); week records for started weeks;
  check runs from done `fit_check` plans with a linked activity.
- **API:** `GET /api/plan/block?start=` (`BlockProgressDTO`, null without blocks; never creates a block in
  race mode), `GET /api/plan/blocks`.
- **UI:** card "Blok" on Plán (fitness mode) and Progres (runs, with a block picker): summary tiles, start vs
  now with green/red change, weekly running time chart + table, check runs. Checked in the browser on demo
  data (desktop dark, phone light; fixed a phone overflow). Plán refetches the week and block after today's
  first decision.
- **Rule 6 changed (user):** in a test week without a green day the check run is given on a yellow day.
- **Next:** step 3 (predictions: morning note from the personal sleep→performance relation, 7-day outlook).

### Coach "Kondícia" – step 1 (2026-10-26; docs/COACH_V2.md approved by the user, rules in METRICS §11)
- **When:** every day without an active race goal (`planning.mode_for` → "fitness"); with a goal the §10 rules
  stay unchanged. Primarily running, 3 runs a week, the bike is extra and unplanned (override "bike").
- **Pure rules** `training/coach/fitness.py` (§11.1–§11.3): week menu K/D/Ľ, day colour from readiness
  (≥ 70 / 45–70 / < 45), rules 0–7, weekly running time (×1.07, hold/cut brakes, recovery weeks 4/8/12 at 0.7,
  test weeks 6/12 with the check run), split D 40 / K 30 / Ľ 30 % with clamps (weekday D ≤ 60 min), quality
  rotation threshold / VO2 / tempo / hills. 21 tests with known answers.
- **DB:** `coach_block` + `coach_week` (migration 0005). `planning_fitness.py` creates the week on first use
  (a new 12-week block when none is open, gaps filled in order so every brake applies), builds the §11.2 inputs
  (done items, unplanned run fills Ľ, hard yesterday, available days from preferred days "rest"), commutes ignored.
- **Waiting for sleep:** before 12:00 without last night's sleep the plan is provisional (`waiting_sleep`), the
  morning run's plan step is "waiting" (exit code 4), push and Telegram wait; the sync's nightly step decides
  again. Schedulers repeat hourly 09:00–13:00 with `training morning --once-per-day` (no-op after a complete run).
- **API/UI:** `WeekPlanDTO.mode/fitness` (block week n/12, target and done running time, brake, menu with done
  dates), `DailyDecisionDTO.mode/waiting_sleep`, `MorningRunDTO.waiting`. Plán page shows the Kondícia week
  instead of the TSS target and the season; the day chips show K/D/Ľ; "čaká na spánok" on Plán, Dashboard and
  in the morning-run table.
- **Tests:** existing §10 tests run in race mode (conftest fixture; mark `fitness_coach` for §11 tests).
- **Spec review fixes:** week numbers are final only after the Monday sync (`coach_week.final`, migration 0006),
  re-derived before that (also by the week view) and by the `training recompute` command only (B1); known-answer tests for every commute filter, both brakes,
  `if_pace` for rTSS and the sleep-score wait (B2); retries (Docker loop, Task Scheduler, cron) run at least
  until 13:00 (W1); a restart catches up a waiting run (W2); check-run name says "vypni auto-pauzu" (W4);
  concurrent week creation is tolerated (W6); a second run on a planned day fills Ľ; 5-min rounding halves up.
- **W5 decided by the user:** in a test week without a green day, rule 6 gives the check run (also on a
  yellow day) instead of the mild K.
- **Next:** step 2 (block progress: baseline, check-run results, end-of-block summary), step 3 (predictions).
  Open: Garmin HR zones must match LTHR 172; after 4 weeks check how many K days were green.

### Windows PC as the always-ready runner (2026-10-26, user: the Beelink SER9 is also the everyday PC)
- `install_task_windows.ps1`: daily 09:00 with **WakeToRun** (wake timers enabled via powercfg), logon type
  **S4U** (runs as the user also when nobody is signed in, no stored password, no window; one UAC prompt, the
  script re-launches itself elevated for the signed-in user), `-InteractiveOnly` keeps the old mode.
- `training/keep_awake.py`: the one-shot `training morning` asks Windows to stay awake during the run
  (SetThreadExecutionState), so the unattended-sleep timeout after a timer wake cannot cut a sync.
- A fully shut down PC cannot be woken by Windows: the user sleeps it at night, or sets a BIOS RTC wake.
- Not run on Windows here (pwsh 7 parse check only); verify: sleep the PC before 09:00 and check
  `Get-ScheduledTaskInfo` / Dashboard "Ranný beh" afterwards.

### Always-on home server (2026-10-26, user's choice: a small computer at home)
- **Why:** the morning run (sync → plan → push → Telegram) must happen at **09:00** even with the PC off.
  Chosen over a cloud VPS (Garmin blocks datacenter IPs more often; health data stays at home).
- **docker-compose.yml:** `app` (React + API, published on 127.0.0.1 only, healthcheck), `morning`
  (`training morning --loop --at ${MORNING_AT:-09:00}`), `streamlit` behind a profile. Access from PC and phone
  through Tailscale (`tailscale serve` → HTTPS, PWA installable); the API has no login, so nothing is exposed on
  the LAN or internet.
- **Dockerfile:** runs `/opt/venv/bin/training` directly. Fixed a phase-8 bug found by actually running the
  stack: as the host user, `uv run` failed on the root-owned build cache (`Permission denied` loop). uv pinned
  (`ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.8.17`). Built and run here (x86-64, Docker 29): app healthy, `/` and
  `/plan` served, morning loop waiting for 09:00 Europe/Bratislava, a manual run works (sync fails without tokens
  as expected). Not yet built on a Raspberry Pi (arm64).
- **Scripts:** `scripts/server_setup.sh` (checks Docker, writes `.env` with UID/GID/TZ/MORNING_AT keeping user
  values, builds, waits for health, `tailscale serve`; tested with fakes in `test_server_setup.py`);
  `scripts/move_to_server.ps1` (stops the local app, WAL checkpoint, scp of DB + Garmin tokens, removes the Windows
  task so only the server pushes to Garmin, optional desktop icon); `install_shortcut_windows.ps1 -Url` opens the
  server's address in an Edge app window. PowerShell scripts parse-checked with pwsh 7, not run on Windows.
- **Retries:** `morning.daily_loop` retries a failed run (non-zero exit or crash) every hour, at most 4 times,
  same day only (`RETRY_DELAY`, `MAX_RETRIES`); verified the catch-up on start in the running stack.
- **Default time 09:00** everywhere (`training morning --at`, cron/Task Scheduler scripts, compose).
- **Docs:** `docs/SERVER.md` (hardware, OS, Docker, Tailscale, moving data, operations), OPERATIONS.md §2.
- **Next for the user:** buy/prepare the Pi, follow docs/SERVER.md, report the first 09:00 run.

### Phase 9 – React app (2026-10-25; code complete, Streamlit kept until the user retires it)
- **Stack:** `frontend/` – Vite 6, React 18, TypeScript, Tailwind 4, TanStack Query + Router, Recharts, PWA
  (vite-plugin-pwa), fonts bundled (offline). Types generated from `docs/openapi.json` (`npm run gen:api`).
- **Served by FastAPI** (`training api`): `frontend/dist` at `/` with an SPA fallback, `/api`, `/docs` untouched;
  CORS only for the Vite dev server. `frontend/dist` is committed so the app runs without Node;
  `test_api_frontend.py` fails when dist is older than the sources (rebuild: `cd frontend && npm run build`).
- **Pages:** Dashboard, Aktivity (list + detail with synced HR/pace/altitude charts, zones, laps, load, RPE form,
  commute switch), Fitness, Progres, Spánok, Plán (today actions, Garmin push, week, season, goal, preferred
  days), Nastavenia (athlete, thresholds, zones, proposals with apply, sync, diagnostics, morning runs). Dark,
  light and auto themes; sidebar on desktop, bottom navigation on phones. Built by the orchestrator (foundation,
  Dashboard, Fitness) and 5 parallel ui-page-builder agents (one page each, merged without conflicts).
- **API additions:** `POST /api/progress/threshold-proposals/apply` (`ProposalApplyIn`).
- **Fixed on the way:** parallel first requests raced inside Alembic (KeyError / segfault) – migrations and the
  API engine creation are now serialized (`db/session.py`, `api/deps.py`).
- **Desktop icon (Windows):** `scripts/install_shortcut_windows.ps1` → "Training Analytics" on the desktop and in
  Start; `scripts/start_app.ps1` starts `uv run training api` if needed and opens an Edge app window. The
  scripts are parse-checked with PowerShell 7 here; not run on Windows yet.
- **Not done / open:** the phone cannot reach the PC server (127.0.0.1 only, no auth; PWA needs HTTPS – e.g.
  Tailscale serve, to be set up with the user); Streamlit is not deleted (PLAN says after parity – waiting for
  the user's go after trying the React app); date inputs follow the browser locale.
- Tests: Python 1951 passed; frontend vitest 40 passed, `tsc -b` clean. (Home-server session: 1957 passed.)

### Commutes (2026-10-25, METRICS §2.6 – approved by the user)
- **Rule:** a bike ride with < 25 min of moving time is a commute; a per-activity override
  (`activity.commute_override`, migration 0004) wins. `training/commute.py` holds the rule (`is_commute`) and
  the same rule in SQL (`commute_expr`).
- **Fatigue yes:** commute load stays in `daily_load` (CTL/ATL/TSB/ACWR/monotony, readiness, diagnostics).
- **Training no:** no EF/decoupling/day pace, no best efforts, not in curves, §6.3 proposals or the §9 day
  activity; the coach uses `T_train = max(0, T − C)` (`C` = 7/28 · commute load of the previous 28 days),
  non-commute week load, run share, active days, yesterday's IF and matching (`planning.py`, `season.py`).
  The Plán week view shows training load per day plus `commute_load`.
- **UI / API:** "dochádzka" tag in the activity list and detail, a radio "automaticky / dochádzka / tréning"
  on the activity detail, `PUT /api/activities/{id}/commute` (`CommuteIn`), `ActivitySummaryDTO.is_commute`.
- **After pulling:** `uv run training recompute` drops the commutes' best efforts and EF values.
- **Review fixes:** reclassifying a matched ride as a commute re-opens or re-matches its workout
  (`planning._unmatch_commutes`, also on every match pass); explicit curve months are written even without
  runs; `set_commute` rolls back on a recompute error (ServiceError); Plán week card / chart show the commute
  load; `SeasonWeekDTO` / `WeekPlanDTO` carry `commute_load`; the AI report marks commutes; indoor rides are
  never commutes by the rule (METRICS §2.6, decided autonomously and reported to the user).
- Test scenario: the weekly 20-min seeded ride is marked as training (`commute=False`) so the older tests keep
  their meaning; `test_commute.py` covers the rule, pipeline, coach and service.

### Real Garmin fixtures (2026-10-25)
- **Recorded on Windows and committed** (`c335139`): 6 activities (3 runs, 3 rides), 14 days of wellness, body
  battery, max metrics, training status and the lactate threshold. Anonymized: names, ids and GPS checked.
- **Conformance tests pass** on them (cloud and Windows), so the phase-1 key guesses are confirmed: the detail
  descriptor keys, the summary/sleep/stress/body-battery keys and timer-time `duration`.
- **Fixed: run cadence in the streams was half.** `directRunCadence` counts one foot (~82); the summary's
  `averageRunCadence` is steps/min (~165). Streams now prefer `directDoubleCadence` and double a lone
  `directRunCadence`. The conformance test checks the stream median against the summary. Nothing computed
  uses cadence; `training recompute` rewrites stored streams.
- **Lactate threshold** `speed` is 0.3 for 3.0 m/s, matching the existing ×10 handling.
- **Still unverified:** the Garmin push responses (schedule id, calendar item keys). The recording does not call
  those endpoints; the first real `push-today` shows them (a log warning names the keys if the id is missing).
- **Demo data found in the real DB** (`db-stats` / `diagnostics` on Windows): 139 activities with garmin ids
  9000000xx, 238 wellness days and the demo thresholds (run 168 bpm / 4:15, bike 160) came from
  `scripts/seed_demo.py` run into `data/training.db` (the bash `VAR=… uv run` form does not work in PowerShell).
  Backfill skipped the real wellness of those days because a row already existed.
  - New `training purge-demo [--yes]` (`db/demo.py`): removes only rows without a raw Garmin payload (demo-range
    id + "Demo " name for activities; no raw wellness for a day; exact demo threshold values), then recomputes.
    The athlete row is only reported.
  - `seed_demo.py` now writes `data/demo.db` by default (`--db`), never writes into a DB with raw payloads, and
    documents the PowerShell form.
  - After the purge: `backfill --months 24 --restart` fetches the missing wellness days; real thresholds and
    athlete values have to be entered.
- Garmin push on the real account: `push-today` twice → "unchanged", workout id returned. Calendar entry still
  to be confirmed by the user.
- Diagnostics before the purge: load vs Garmin training load r = 0.84 (n = 289), good.
- **After the purge, wellness backfill and real thresholds** (run LTHR 172 / 5:33 from Garmin, bike LTHR 165 as a
  starting estimate): all 329 activities have a load, **r = 0.89 (n = 329)** vs Garmin training load – the
  phase-2 acceptance (§2.5, r > 0.8) is met on real data. hrTSS and rTSS differ by > 40 % on 2 runs only.
- Open: the bike LTHR proposal (§6.3) needs hrTSS, so it can never appear before a first bike threshold exists.
  **Fixed** (METRICS §6.3 changed 2026-10-25, approved): without any ride hrTSS in the window the rides are ranked
  by `avg_hr` (same top-10 % rule); the basis says "average HR (no bike threshold yet)".
- **Approved 2026-10-25:** the METRICS clarifications of phase 5 (§8–§9), phase 6 (§10) and phase 7 (§10.8).
- **Bike LTHR population** (METRICS §6.3 changed 2026-10-25, approved): only rides with an 1800 s HR best
  effort enter the top-10 % selection. On real data no bike proposal appeared with the old rule; the likely
  cause (unverified) is that the top rides lacked 30 min of HR without a pause.
- **At least 3 rides** (METRICS §6.3 changed 2026-10-25, approved): the bike population needs 3 rides with an
  1800 s HR effort, else no proposal ("only N ride(s) … (at least 3 needed)"). On real data the old rule
  proposed 151 bpm from the single ride of the last 90 days with 30 min of HR without a pause.
- **Real data explains the missing efforts:** the recorded activities are 13–40 min of timer time, several with
  pauses of 4–20 min in the middle (e.g. a run with 40 min moving and a 7-min stop); HR has no dropouts and the
  samples are 2–7 s apart. A 30-min effort without stopping (field test) is needed for HR-based proposals.
- **Why a proposal is missing:** `lthr_missing_reason` / `speed_missing_reason` (`metrics/efforts.py`) →
  `services.progress.get_proposal_gaps` (`ProposalGapDTO`) → `GET /api/progress/threshold-proposals/missing`,
  `training propose-thresholds` and a caption on Nastavenia / Progres. Real data: the run LTHR is presumably
  missing because no run reached `if_pace` 0.95 against 5:33 – the new message will confirm.
- Open: the run threshold-pace proposal (6:40/km, best 30-min GAP of 90 days) is far slower than Garmin's 5:33;
  the user keeps 5:33 (hrTSS and rTSS agree).
- Tests: 1929 passed (cloud, nothing skipped); Windows 1879 passed, 2 skipped (bash cron tests) before this fix.

### Phase 8 – automation and operations (code complete; Windows task and Docker image not run yet)
- **`training morning`** (`training/morning.py`, `cli/morning.py`): sync (+ metrics + nightly plan) → plan →
  push → telegram.
  - Each step is isolated. A failed sync keeps the plan provisional, so it is not pushed.
  - Telegram is sent once per day (`TELEGRAM_SENT_DATE`).
  - Runs are recorded under `MORNING_RUNS` (≤ 30).
  - Exit code: 0 = ok, 1 = a failed step, 3 = locked (`data/logs/morning.lock`, taken over after 3 h).
  - `--loop --at HH:MM` for Docker.
- **Logs:** `data/logs/training.log` – JSON lines, rotated, every line passes the credential redaction filter.
- **Schedulers:**
  - `scripts/install_task_windows.ps1` (Task Scheduler: runs when available, so a laptop that slept still runs
    it) – not run in the cloud, there is no PowerShell here.
  - `scripts/install_cron.sh` – tested with a fake crontab.
- **Docker:** `Dockerfile` + `docker-compose.yml` (ui + morning loop, `./data` and the token directory mounted,
  secrets in an optional `.env`). The compose file validates; the image build is untested (no Docker daemon
  here).
- **Health:**
  - Dashboard "Ranný beh" line: red after a failed run or 36 h without a successful one.
  - Nastavenia → Sync a diagnostika: the last 10 runs and the latest errors (`services/morning_runs.py`,
    `dto_health.py`).
- `docs/OPERATIONS.md`: the daily run, schedulers, Docker token bootstrap, the Garmin login-breakage playbook,
  backup and recovery, common situations.
- Spec review: no blockers. Warnings fixed:
  - Tracebacks redacted on every handler.
  - The `--loop` waits by the wall clock in ≤ 5-min chunks (DST-safe), catches up a missed day on start
    and never dies on a crash.
  - A provisional plan is neither pushed nor marks Telegram as sent; the message says "predbežný".
  - The lock tolerates races, is released only by its owner, and a dead PID is taken over.
  - Docker runs as the host UID/GID, reports go to `data/reports`, and `.dockerignore` excludes tokens/DBs.
  - Task Scheduler waits for the network.
  - cron `%` is escaped.
  - OPERATIONS.md wording corrected.
- Open (by design, noted): the run status is red also when only Telegram/push failed; `sync_stale` compares
  dates (24–48 h) while its text says 36 h; manual `training sync` / UI sync don't take the morning lock.
- Tests: 1852 passed, 5 skipped.

### Kokpit design in the Streamlit UI (2026-10-23)
- **Design:** the Claude Design export is in `docs/design/` (with screenshots and its known sample-data mistakes).
  Streamlit screenshots after the change are in `docs/design/streamlit/`.
- **Theme:** `.streamlit/config.toml` has dark and light variants. The palette in `components/theme.py` follows
  the design tokens. Plotly charts use one fixed set, readable on both themes.
- **Numbers:** Slovak format everywhere in the UI – decimal comma, a real minus sign, `d. m.` date ticks.
- **Labels:** raw codes replaced (ručne / návrh, hrTSS / rTSS, Beh / Bicykel).
- **New elements:**
  - Dashboard: a readiness gauge, a "Dnešný tréning" card and metric tiles with colour bars.
  - A workout profile chart (Dashboard and Plán).
  - Plán: the week as 7 day cards.
  - Spánok: a mini ρ axis on each finding, with uncertain findings muted.
- **Not matched:**
  - Cards are outlined, not filled, because Streamlit CSS cannot know the active theme.
  - Barlow fonts are configured via Google Fonts URLs but could not be verified in the sandbox.
  - The design's sidebar brand block, sync box and theme toggle are not reproduced.
  - Text built by services (plan reasons, the Telegram message) still uses a decimal point, e.g. "IF 0.94".

### Windows compatibility (2026-10-23)
- Text files are read and written as UTF-8 explicitly (`export-openapi`, `scripts/record_fixtures.py`, `.env`,
  tests); the Windows default code page (cp1250) broke 4 tests and would break non-ASCII fixtures. Generated
  docs and fixtures are written with LF line endings on every OS.
- SQLite URLs use `as_posix()` (`Settings.db_url`, `db/session.py`), so they read `sqlite:///C:/…` on Windows.
- Full suite on Windows 11: 1787 passed, 5 skipped (no real Garmin fixtures yet).
- `garminconnect` 0.3.17 → 0.3.19: the first `training login` was rejected with 429 / Cloudflare 403 on every
  login strategy; retry after a few hours with the new version (or from another network).

### Phase 7 – push to Garmin, morning message, AI report (code complete; needs a real-account check)
- **Garmin push** (METRICS §10.8, clarifications proposed):
  - `coach/garmin_push.py` converts a §10.5 workout into the JSON the garminconnect 0.3 builders emit (HR
    zones as `zoneNumber`, repeats, unique `stepOrder`).
  - `training/push.py`:
    - First push: upload once, save the id immediately, schedule once.
    - Re-push: update in place; nothing is sent when the payload and date are unchanged (cron-safe).
    - A date change moves the calendar entry.
    - A regeneration keeps the Garmin id; a regeneration to rest deletes the workout.
    - A workout deleted in Garmin is uploaded again.
    - Pending markers stop a lost response from creating a duplicate.
  - Entry points: `POST /api/plan/{id}/push`, `POST /api/plan/today/push`, `training push-today
    [--dry-run]`, and the Plán page buttons ("Poslať / Aktualizovať v Garmin", "Odstrániť z Garmin").
- **Telegram morning message** (optional, `TRAINING_TELEGRAM_TOKEN` / `TRAINING_TELEGRAM_CHAT_ID`):
  - Code: `services/notify.py`, `training telegram-morning [--dry-run]`, `scripts/telegram_morning.py`.
  - It never fails and never logs the token. The CLI log filter (`training/log_redaction.py`) also redacts
    the token from urllib3 DEBUG lines (review blocker).
- **Weekly AI report** (optional, `TRAINING_ANTHROPIC_API_KEY`, `uv sync --extra ai`):
  - `coach/llm.py` builds the prompt from DTOs only and calls `claude-opus-5-5` with server-side fallbacks.
    Refusals and cut-off answers are errors; the model that actually answered is recorded.
  - `services/report.py` writes `docs/reports/YYYY-Www.md`, named after the week that just ended. The files
    are gitignored because they hold health data.
  - Entry points: `training weekly-report [--dry-run]`, `/api/reports/latest`, `/api/reports/weekly`, and a
    Dashboard expander. The LLM only explains the plan and never changes it.
- **Demo** (dry runs on the demo DB): `push-today --dry-run` prints the cycling "Sweet spot 2×20 min"
  payload; `telegram-morning --dry-run` gives the 6-line message; `weekly-report --dry-run` prints the
  prompt. All pages load in the browser without exceptions.
- **Spec review:** 2 blockers fixed and tested – the token in urllib3 DEBUG logs, and a regeneration to rest
  that could not be removed from Garmin. Also fixed: duplicate risks (upload/schedule markers, schedule sent
  once), 404 recovery, unchanged re-push, the missing `ai` extra, the served model, `max_tokens`, the week
  label, the 502 declaration, and rollback.
- **Review round 2:** READY; also fixed the remaining duplicate/orphan paths (markers survive a regeneration, a rename, a switch to rest and a date change; the workout lookup pages through the whole library), the cron script now uses the shared logging + redaction setup, and the report data is anchored on the reviewed week.
- **Tests:** 1787 passed, 5 skipped. ruff clean.

### Phase 6 – coach: season, rules, plan (code complete; METRICS §10 clarifications approved 2026-10-25)
- `coach/` (pure, deterministic, no LLM; test-first by three metrics-implementers):
  - `workout.py`: the §10.5 schema as Pydantic, plus §10.6 `estimated_load`.
  - `library.py`: §10.7 as data. Every workout has one parameter, and `fit_param` picks the value whose
    load is closest to the day's target.
  - `season.py`: §10.1 phases and §10.2 targets (ramp cap, recovery weeks, non-compounding taper, CTL
    projection).
  - `template.py`: §10.3 weekday roles and `preferred_days`.
  - `rules.py`: the §10.4 daily decision with Slovak reasons.
- Glue: `training/planning.py` (context from the DB, a persisted `planned_workout`, date+sport matching,
  done/skipped status).
- Where plans are made:
  - `training plan-today [--force] [--sport] [--date]`.
  - The nightly step at the end of `training sync` and `POST /sync`. A failure there is rolled back and
    never fails the sync.
- Services/API/UI (ui-page-builder):
  - `services/plan.py` + `dto_plan.py`.
  - `/api/plan/today`, `/today/regenerate`, `/week`, `/season`, `/goal` (GET/PUT/DELETE), `/{id}`,
    `/{id}/status`.
  - Plán page: today's card (steps, load, reason, readiness, done/skip/regenerate), this week planned vs
    done, season timeline, goal editor, preferred-days editor.
- Acceptance:
  - The decision changes with readiness and with ACWR (rules and DB tests).
  - A simulated 16-week season peaks at a ramp of 4.76 (limit 6).
  - The plan is visible in the UI and via `/api/plan/today` (browser-checked on the demo DB, no
    exceptions on any page).
- Spec review, 2 blockers fixed and tested:
  1. The taper reference was rebuilt from the current week's CTL (compounding). It now uses the stored
     CTL before the last pre-taper week.
  2. A decision made before the morning sync (the page opened first) was frozen for the day. It is now
     provisional and the nightly step decides it again.

  Round 2: READY. A plan is also provisional until the wellness cursor reaches the day, `provisional` is shown
  in the DTO, and the rollback test fails without the rollback.
  Warnings fixed: stale docstrings, `_ctl_before` = exactly Monday−1, rollback after a caught planning
  failure, interpretation notes moved into METRICS §10, UI imports only services, run share per week.
- Demo (`plan-today` on the demo DB, no goal → Base cycle, recovery week): today "Progresívny beh 60 min",
  estimated 56 points (day target 55). `--sport bike` gives "Sweet spot 2×20 min".
- Tests: 1706 passed, 5 skipped. ruff clean.

### Phase 5 – sleep, readiness, correlations (code complete; METRICS §8–§9 clarifications approved 2026-10-25)
- `analysis/` (pure, test-first by two metrics-implementers):
  - `wellness.py`: trailing 28-day median/MAD baselines (D−28…D−1, ≥ 7 values) and `sleep_debt_7`.
  - `readiness.py`: §8 components, renormalized weights, bands.
  - `correlation.py` + `stats.py`: §9 per-sport dataset (lag0/lag1/mean3, controls TSB[D], ATL[D−1],
    load[D−1]), Spearman, partial correlation via OLS residuals, a vectorized seeded bootstrap, the quartile
    contrast, and `insufficient_data` below n = 30. A planted correlation is detected; a planted confounder
    disappears after partialling.
- Pipeline: `pipeline_wellness.compute_readiness` runs at the end of every `compute_daily_load`, so `recompute`,
  `sync`, a threshold change and an athlete change all refresh `daily_load.readiness`.
- Services/API/UI (ui-page-builder):
  - `services/sleep.py`, `sleep_findings.py` (Slovak sentences, caveat) and `dto_wellness.py`.
  - `GET /api/wellness/daily`, `/wellness/readiness/today`, `/wellness/readiness/{day}` and
    `/wellness/correlations`.
  - Streamlit Spánok page: readiness gauge + breakdown, sleep stages, sleep score and RHR with median ± MAD,
    sleep debt, and Findings.
  - Correlations are cached in-process by a hash of all their inputs, so any data change refreshes them.
- Spec review: round 1 – 1 blocker (the cache fingerprint missed most inputs → stale findings) fixed and tested;
  warnings (DTO file size, test split, timing-test margin, doc notes) addressed; round 2 – READY.
- **Demo report** (`scripts/seed_demo.py`, 240 synthetic days with a planted sleep → HR effect; no real data
  yet): readiness today **77, green** (RHR 100, sleep 84, Body Battery 74, form 37). Top 3 run findings:
  1. sleep_s (night before) → EF: partial ρ +0.46 [0.21; 0.65], n = 51 – the planted effect.
  2. sleep_s (3-night mean) → EF: partial ρ +0.35 [0.04; 0.57], n = 51.
  3. REM (night before) → pace at ref HR: ρ −0.31 [−0.52; +0.05], n = 41 – uncertain (chance).
- Tests: 1227 passed, 5 skipped (real fixtures). ruff clean.

### Phase 4 – progress without power (code complete; METRICS clarifications approved)
- `metrics/`, test-first by two metrics-implementers:
  - `efficiency.py` (§5): steady state, EF, decoupling, bike variant, the 28-day `ef_trend`.
  - `curve.py` (§6.1): 60 s aggregates, speed–HR curve, `pace_at_ref_hr_day`. It is a separate module (was
    `efforts.py` in PLAN) so the two implementers could work in parallel.
  - `efforts.py` (§6.2–§6.3): best efforts, `best_per_window`, threshold proposals.
  - `predictions.py` (§7): Riegel, VDOT with bisection, reference choice. 10 km in 40:00 gives VDOT 51.94 and a
    half marathon of 1:28:33.
- `pipeline_progress.py` stores the §5 fields in `activity_metric` and efforts in `best_effort` (new columns
  `distance_m` and `start_t`, migration 0003). It also writes monthly `curve_snapshot`s (never after today).
  A run-LTHR change refreshes the curves.
- Services, API and UI:
  - `services/progress.py` and the `/api/progress/*` endpoints.
  - The Progres page: EF, decoupling, curves, pace@refHR, best efforts 90 d / all, predictions, proposals.
  - Nastavenia: "apply proposal" (source `proposal`).
  - `training propose-thresholds`.
- Browser check on the demo DB: the Progres page renders with no exceptions.
- Spec review of phase 4: round 1 found 1 Blocker, fixed. Month curve snapshots went stale after month end, so
  refresh now covers every month since `curves_refreshed_until`. Warnings fixed:
  - the HR lag now pairs by time and never bridges a pause;
  - rules that were only in docstrings moved into METRICS;
  - a run LTHR change refreshes all months;
  - a broken run no longer stops the curve step.
  Round 2: READY TO COMMIT.
- Tests: 1082 passed, 5 skipped.
- Unverified Garmin keys (`services/garmin_values.py`):
  - `lactate_threshold.speed_and_heart_rate.{heartRate, speed}`; the speed unit is guessed as ×10 when < 1;
  - `max_metrics[0].generic.vo2MaxPreciseValue`.
  Check both against real fixtures.

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
7. **You, locally – phase 4/5 check:** after upgrading an existing DB run `uv run training recompute` once
   (fills EF/curves and `daily_load.readiness`; until then `/wellness/daily` shows no readiness while
   `/wellness/readiness/today` computes it live). Then open Progres and Spánok and report today's readiness
   and the top 3 findings from your real data.
8. ~~Approve the phase 5 / 6 METRICS clarifications~~ – approved 2026-10-25.
9. **You, locally – phase 6 check:** set your goal on the Plán page (or `PUT /api/plan/goal`), your
   run:bike split (`training athlete`) and your preferred days, then run `uv run training sync` and check
   today's plan and its reason. Set your Garmin HR zones to METRICS §1 before phase 7 pushes workouts.
10. **You, locally – phase 7 acceptance:**
    1. Run `uv run training push-today --dry-run`, then `uv run training push-today`.
    2. Check that the workout appears in the Garmin Connect calendar and reaches the watch.
    3. Run `push-today` again: it must say `unchanged`, with no duplicate in Garmin.
    4. Optional: set `TRAINING_TELEGRAM_TOKEN` / `TRAINING_TELEGRAM_CHAT_ID` and run
       `uv run training telegram-morning`.
    5. Optional: set `TRAINING_ANTHROPIC_API_KEY` and run `uv sync --extra ai` and
       `uv run training weekly-report`.
11. ~~Approve the §10.8 phase 7 clarification~~ – approved 2026-10-25.
12. **Phase 8** – automation: `training morning` (sync → plan → push → telegram), cron/Docker, logs.

## Known issues / open questions
- Plain `uv sync` (without `--extra ai`) makes `uv run pytest` stop at collection: `test_report.py` imports
  `anthropic` at module level. Use `uv sync --extra ai`, or have the test skip via `pytest.importorskip`.
- A `%` in the DB path breaks Alembic (`set_main_option` interpolation); escape it as `%%` if it ever matters.
- Phase 7 (unverified Garmin keys – check on the first real push):
  - The schedule response's id key (`workoutScheduleId` is assumed).
  - The calendar item keys `itemType` / `date` / `workoutId` / `id`, used to recover a lost schedule
    response and to move a date without a stored schedule id.
  - If they differ, a date change could leave the old calendar entry. A warning is logged when no schedule
    id is found.
  - Log redaction is installed by the CLI; the API/Streamlit processes don't send Telegram messages.
- Phase 6:
  - The §10.7 ranges cap a default run week at about 420 points; a larger weekly target (Build with
    CTL > ≈ 39) is not reachable, and every workout then sits at its maximum. Options are wider ranges
    or double sessions – your call.
  - `planned_workout` has no unique index on the date. Plans are one per day by construction, but a page
    view and the cron sync running at the same second could create two rows.
  - `dto.py` (≈ 418 lines) and `test_coach_rules.py` (≈ 480 lines) are slightly over the file-size
    guideline.

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
- **Garmin keys to verify against real fixtures – confirmed 2026-10-25 (see "Real Garmin fixtures").** The phase 1 normalizers use keys taken from library source
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
  - (resolved) Phase-4 METRICS clarifications approved by the user on 2026-09-29.
  - (resolved, proposed) §10.4 rule 1: rest while the week's rest quota is open, else 40 min Z1 (METRICS §10.4 phase 6).
  - §10.6 Z1 IF 0.50 is kept as written (not the table midpoint 0.43); noted in METRICS §10.6 – confirm.

## Decisions

- 2026-09-29 **Deviations from PLAN §3 and §5 in phase 3.**
  - Streamlit uses `st.navigation` with `ui-streamlit/views/` (one script per page), `sections/` (render blocks)
    and `components/` (Plotly, DTO in → figure out) instead of the numbered `pages/` files.
  - The API adds `GET /fitness/dashboard` (DashboardDTO) and `PUT /settings/athlete` (AthleteIn → AthleteDTO).
  - `GET /diagnostics` lives in `routers/sync.py`.
  PLAN.md is updated.

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
