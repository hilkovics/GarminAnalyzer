# PLAN.md – kompletný postup pre Claude Code (Opus 5.5)

Osobná tréningová analytika pre beh + bicykel z Garmin Forerunner 945 (hrudný pás, bez wattmetra).
Nič sa nesťahuje ručne: appka si všetko ťahá z Garmin Connect ako JSON. Začíname so Streamlit UI,
architektúra je od prvého dňa pripravená na React, aby prechod bol len výmena prezentačnej vrstvy.

Súvisiace dokumenty: `CLAUDE.md` (pravidlá pre Claude Code), `docs/METRICS.md` (vzorce),
`docs/STATUS.md` (čo je hotové – vytvorí sa vo fáze 0).

---

## 1. Princípy, ktoré umožnia neskorší React bez prepisovania

1. **Core je knižnica, nie appka.** `backend/training/` nemá žiadnu závislosť na UI. Streamlit aj FastAPI
   sú tenké vrstvy nad `services/`.
2. **Services vracajú Pydantic DTO.** Rovnaké objekty renderuje Streamlit dnes a serializuje FastAPI pre React zajtra.
   API kontrakt (§4) je definovaný od fázy 3, hoci ho zatiaľ používajú len testy.
3. **Raw JSON z Garminu sa ukladá celý.** Databáza je len cache – keď sa zmení vzorec, spustíš `recompute`,
   nie nový sync. Keď sa DB stratí, spustíš `backfill`.
4. **Sync je hlúpy a idempotentný.** Cron ho spúšťa ráno; UI ho nikdy nespúšťa na pozadí.
5. **Vzorce sú v METRICS.md a majú testy.** Claude Code implementuje spec, nevymýšľa.

---

## 2. Architektúra

```
Garmin Connect (garminconnect, tokeny v garmin_tokens.json)
        │  JSON
        ▼
training/garmin/        client.py (rate limit, retry) · sync.py (incremental) · backfill.py (cursor)
        │
        ▼
raw_garmin (SQLite)     verbatim payloady: activity_summary, activity_details, laps, hr_zones, sleep, rhr, bb, stress, summary
        │
        ▼
training/normalize/     JSON → typované riadky (activities, activity_streams, daily_wellness)
        │
        ▼
training/metrics/       čisté funkcie nad pandas: zones · gap · load · pmc · efficiency · efforts · predictions
training/analysis/      wellness baselines · readiness · correlation
training/coach/         season · rules · library · garmin_push · llm (voliteľné)
        │
        ▼
training/services/      activities · fitness · progress · sleep · plan · settings  →  Pydantic DTO (dto.py)
        │                          │
        ▼                          ▼
ui-streamlit/ (fáza 3–8)      training/api/ FastAPI (fáza 3+)  →  frontend/ React (fáza 9)
```

---

## 3. Štruktúra repozitára

```
training-app/
├── CLAUDE.md
├── docs/  PLAN.md · METRICS.md · STATUS.md · API.md (generuje sa z OpenAPI vo fáze 3)
├── backend/
│   ├── pyproject.toml            # uv, ruff, pytest, alembic
│   ├── alembic/
│   ├── training/
│   │   ├── config.py             # pydantic-settings, TRAINING_* env
│   │   ├── cli.py                # typer: login, sync, backfill, recompute, api, propose-thresholds
│   │   ├── db/                   # models.py (SQLModel), session.py, repo.py
│   │   ├── garmin/               # client.py, sync.py, backfill.py, endpoints.py
│   │   ├── normalize/            # activities.py, streams.py, wellness.py
│   │   ├── metrics/              # preprocess.py, zones.py, gap.py, load.py, pmc.py, efficiency.py, efforts.py, predictions.py
│   │   ├── analysis/             # wellness.py, readiness.py, correlation.py
│   │   ├── coach/                # season.py, rules.py, library.py, workout.py, garmin_push.py, llm.py
│   │   ├── services/             # dto.py, activities.py, fitness.py, progress.py, sleep.py, plan.py, settings.py, diagnostics.py
│   │   └── api/                  # main.py, deps.py, routers/{activities,fitness,progress,wellness,plan,settings,sync}.py
│   └── tests/
│       ├── fixtures/             # zaznamenané Garmin JSON odpovede (anonymizované GPS)
│       ├── synthetic.py          # generátory syntetických streamov so známymi výsledkami
│       └── test_*.py
├── ui-streamlit/
│   ├── app.py
│   ├── pages/  1_Dashboard.py · 2_Aktivity.py · 3_Fitness.py · 4_Progres.py · 5_Spanok.py · 6_Plan.py · 7_Nastavenia.py
│   └── components/               # grafy (Plotly) nad DTO – žiadna logika
├── frontend/                     # fáza 9: Vite + React + TS
├── scripts/  record_fixtures.py · install_cron.sh · telegram_morning.py
├── data/                         # training.db (gitignored)
└── docker-compose.yml            # fáza 8, voliteľné (RPi / NAS)
```

---

## 4. Dátový model (SQLModel, Alembic)

| Tabuľka | Kľúčové stĺpce |
|---|---|
| `athlete` | id, sex, birth_year, max_hr, rest_hr_override, weight_kg, run_bike_split, preferred_days (json) |
| `threshold` | id, sport (run/bike), valid_from (date), lthr, threshold_speed (run), zones (json), source (manual/proposal) |
| `raw_garmin` | id, kind (activity_summary/activity_details/laps/hr_zones/sleep/rhr/body_battery/stress/user_summary/training_status/max_metrics), ref_key (garmin_id alebo dátum), fetched_at, payload (json) |
| `activity` | id, garmin_id (unique), sport, sub_sport, name, start_utc, tz, local_date, duration_s, moving_s, distance_m, elev_gain_m, avg_hr, max_hr, avg_speed, avg_cadence, calories, is_race, is_indoor, garmin_training_load, garmin_aerobic_te, garmin_anaerobic_te, garmin_vo2max |
| `activity_stream` | activity_id, t (s), hr, speed, gap_speed, alt, grade, cadence, lat, lon, moving (bool) – 1 Hz |
| `activity_metric` | activity_id, load_primary, load_method, hrtss, trimp_norm, rtss, if_hr, if_pace, hr_coverage, low_confidence, time_in_hr_zone (json), time_in_pace_zone (json), steady_state, ef, decoupling_pct, pace_at_ref_hr_day, threshold_id_used |
| `best_effort` | activity_id, sport, kind (gap_speed/speed/hr), window_s, value |
| `daily_wellness` | date (pk), sleep_start, sleep_end, sleep_s, deep_s, light_s, rem_s, awake_s, sleep_score, rhr, body_battery_wake, body_battery_min, stress_avg, steps, weight_kg |
| `daily_load` | date (pk), load_total, load_run, load_bike, ctl, atl, tsb, acwr, monotony, strain, ramp_rate, readiness |
| `subjective` | id, date, activity_id (nullable), rpe (1–10), feel (1–5), soreness (0–3), notes |
| `goal` | id, race_date, distance_m, target_time_s, sport, active |
| `planned_workout` | id, date, sport, name, structure (json §10.5), estimated_load, reason, status (planned/pushed/done/skipped), garmin_workout_id, completed_activity_id |
| `curve_snapshot` | id, month, sport, curve (json – HR bin → gap_speed) |
| `sync_state` | key (pk), value – kurzory (last_activity_sync, last_wellness_date, backfill_cursor) |

---

## 5. API kontrakt (FastAPI, prefix `/api`) – definovaný vo fáze 3, React ho použije vo fáze 9

```
GET  /activities?from&to&sport&page              → ActivityListDTO
GET  /activities/{id}                            → ActivityDetailDTO (summary + metrics + laps)
GET  /activities/{id}/streams?fields=hr,speed,…   → StreamsDTO (downsampled na max 2000 bodov, param `points`)
POST /activities/{id}/subjective                 → SubjectiveDTO
GET  /fitness/pmc?from&to                        → PmcDTO (denné rady ctl/atl/tsb/acwr/monotony/ramp + flags)
GET  /fitness/weekly?weeks=12                    → WeeklyDTO[] (objem, zóny, polarizácia per šport)
GET  /progress/ef?sport&days=180                 → SeriesDTO
GET  /progress/speed-hr-curve?months=6           → CurveDTO[]
GET  /progress/best-efforts?sport&range=90d|all  → BestEffortsDTO
GET  /progress/predictions                       → PredictionsDTO
GET  /progress/threshold-proposals               → ProposalDTO[]
GET  /wellness/daily?from&to                     → WellnessDTO[]
GET  /wellness/readiness/today                   → ReadinessDTO
GET  /wellness/correlations                      → CorrelationDTO[]
GET  /plan/season                                → SeasonDTO
GET  /plan/week?date                             → WeekPlanDTO
GET  /plan/today                                 → DailyDecisionDTO
POST /plan/{id}/push                             → PlannedWorkoutDTO (po push do Garminu)
POST /plan/{id}/status                           → PlannedWorkoutDTO
GET  /settings                                   → SettingsDTO ;  PUT /settings/thresholds → ThresholdDTO
GET  /diagnostics                                → DiagnosticsDTO (posledný sync, korelácia s Garmin load, chyby)
POST /sync                                       → SyncResultDTO (synchronne, len pre lokálne použitie)
```

Streamlit **nevolá HTTP** – importuje `services/` priamo (jeden proces, jednoduchosť). React bude volať HTTP.
Obidve dostávajú rovnaké DTO, takže logika sa nikde neduplikuje.

---

## 6. Fázy

Každá fáza = jedna alebo dve sessions v Claude Code. Postup: **Plan mode → schválenie plánu → implementácia
→ testy → STATUS.md → commit.** Prompty nižšie sú pripravené na skopírovanie (po anglicky, lebo kód aj docs sú
anglické; Claude Code rozumie aj slovenským doplnkom).

### Fáza 0 – Základ repozitára a prihlásenie do Garminu (1 večer)

**Vznikne:** `uv` projekt, ruff, pytest, Alembic init, prázdny balík s modulmi, `docs/STATUS.md`,
CLI `training login`, skript na záznam fixtures.

**Prompt:**
```
Read CLAUDE.md, docs/PLAN.md and docs/METRICS.md fully before doing anything.

Set up the repository skeleton exactly as described in PLAN.md §3:
- backend/ as a uv-managed Python 3.12 project (pyproject with ruff, pytest, sqlmodel, alembic, typer, rich,
  pydantic-settings, pandas, numpy, scipy, statsmodels, garminconnect, fastapi, uvicorn, streamlit, plotly).
- Empty modules with docstrings for every path in §3, an Alembic setup pointing at data/training.db,
  training/config.py (pydantic-settings, TRAINING_ prefix, DB path, GARMINTOKENS path, rate-limit seconds).
- CLI `training login`: interactive Garmin login via garminconnect with MFA prompt, token store at
  ~/.garminconnect (respect GARMINTOKENS). Never echo credentials. Print a success line and the token path.
- CLI `training whoami`: uses stored tokens to fetch the user profile and prints display name – used to verify login.
- scripts/record_fixtures.py: downloads the last 6 activities (summary + details + laps + HR zones) and the
  last 14 days of sleep, RHR, body battery, stress and daily summary, anonymizes lat/lon (adds a constant
  offset), and writes them to backend/tests/fixtures/ with descriptive names. Inspect the installed
  garminconnect package to find the correct method names; do not guess.
- docs/STATUS.md with sections: Done / Next / Known issues / Decisions.
- .gitignore for data/, tokens, .venv, __pycache__.
Run ruff and pytest (a single smoke test is fine). Finish by updating STATUS.md and proposing a commit message.
```

**Akceptačné kritériá:** `uv run training login` prejde vrátane MFA; `whoami` vypíše meno; fixtures existujú
a obsahujú aspoň jeden beh s výškovým profilom a jeden bike; `pytest` zelený.

**Ty ručne:** v Garmin Connect nastav HR zóny podľa %LTHR z METRICS §1 (aby sa zhodovali s pushnutými tréningmi).

---

### Fáza 1 – Databáza, sync a backfill (1–2 sessions)

**Vznikne:** všetky tabuľky z §4 + migrácia, normalizéry, inkrementálny `sync`, resumable `backfill`, `raw_garmin` cache.

**Prompt:**
```
Read CLAUDE.md, PLAN.md §4 and §6 Phase 1, and STATUS.md.

Implement the data layer and Garmin ingestion:
1. SQLModel models for every table in PLAN.md §4 and the initial Alembic migration.
2. training/garmin/client.py: thin wrapper around garminconnect with token loading, 0.7 s spacing between
   calls, exponential backoff on 429/5xx (max 5 tries), and one method per endpoint we need (activities by
   date range, activity details, laps/splits, HR zones, sleep, RHR, body battery, stress, daily summary,
   training status, max metrics/VO2max). Every response is written to raw_garmin (kind, ref_key, payload)
   before anything else happens.
3. training/normalize/: pure functions raw JSON → row dicts for activity, activity_stream (1 Hz, per
   METRICS §0 preprocessing incl. moving flag; grade and gap_speed computed here via metrics/gap.py stub or
   left NULL if you prefer computing in phase 2 – decide and document), daily_wellness. Map Garmin
   activityDetailMetrics by their metric descriptor keys, never by position. Test against fixtures.
4. training/garmin/sync.py: incremental – activities since last_activity_sync minus 2 days (re-fetch
   overlapping ones only if the summary changed), wellness for every date from last_wellness_date to today.
   Idempotent upserts keyed by garmin_id / date. Update sync_state. Log a summary (n new, n updated).
5. training/garmin/backfill.py: walks backwards month by month up to --months, persists a cursor in
   sync_state so an interrupted run resumes. Wellness backfill day by day.
6. CLI: `training sync`, `training backfill --months 24`, `training db-stats` (row counts per table).
Tests: normalizers against fixtures; sync idempotency with a mocked client (run twice → identical row counts).
Update STATUS.md, run ruff + pytest, propose a commit.
```

**Akceptačné kritériá:** `backfill --months 24` dobehne (aj po prerušení a znovuspustení); druhé `sync`
nepridá duplikáty; `db-stats` ukazuje aktivity, streamy aj wellness; `recompute`-friendly (všetko z raw JSON).

---

### Fáza 2 – Metriky záťaže a PMC (1–2 sessions)

**Vznikne:** zóny, GAP, hrTSS, TRIMP, rTSS, výber primárnej záťaže, denný PMC, `recompute`, diagnostika vs. Garmin load.

**Prompt:**
```
Read CLAUDE.md, METRICS.md §0–§4 and STATUS.md. This phase is test-first.

1. tests/synthetic.py: generators for synthetic 1 Hz streams (constant HR/speed, ramps, intervals,
   flat/hilly altitude profiles) with docstrings stating the expected metric values from METRICS.md.
2. Write failing tests first for: zones (§1), gap (§3: flat → gap == speed; +10 % grade case), hrTSS (§2.1:
   1 h at LTHR == 100.0, 1 h at r=0.83 == 56.25), TRIMP normalization (§2.2), rTSS with NGS (§2.3), primary
   selection (§2.4), PMC (§4: hand-computed 10-day series for CTL/ATL/TSB/ACWR/monotony/strain/ramp).
3. Implement metrics/preprocess.py, zones.py, gap.py, load.py, pmc.py as pure functions over DataFrames.
   Each docstring cites its METRICS section. Thresholds are resolved per activity date from the threshold table.
4. training/metrics/pipeline.py: compute_activity_metrics(activity_id) and compute_daily_load(from, to);
   `training recompute [--since]` runs everything from stored raw JSON with no network.
5. Hook recompute of affected days into `sync`.
6. services/diagnostics.py: Pearson r between load_primary and garmin_training_load (§2.5) + last sync info.
Run the full recompute on the real DB and report: number of activities, share flagged low_confidence,
the Pearson r, and any activity where hrTSS and rTSS differ by more than 40 % (list garmin_ids) so I can
sanity-check thresholds. Update STATUS.md, ruff, pytest, commit message.
```

**Akceptačné kritériá:** testy so syntetickými dátami prechádzajú na presné hodnoty; korelácia s Garmin
training load `> 0.8` (ak nie, najprv skontroluj LTHR); `recompute` beží offline.

---

### Fáza 3 – Services, API kostra a Streamlit UI v1 (2 sessions)

**Vznikne:** `services/` s DTO, FastAPI s read-only endpointmi zo §5 (aktivity, fitness, settings, diagnostics),
Streamlit stránky Dashboard, Aktivity (zoznam + detail), Fitness, Nastavenia (prahy s históriou).

**Prompt:**
```
Read CLAUDE.md, PLAN.md §5 and §6 Phase 3, STATUS.md.

1. services/dto.py: Pydantic models for ActivityListDTO, ActivityDetailDTO, StreamsDTO, PmcDTO, WeeklyDTO,
   SettingsDTO, ThresholdDTO, DiagnosticsDTO, SyncResultDTO. Field names in snake_case, units documented.
2. services/activities.py, fitness.py, settings.py, diagnostics.py returning those DTOs. Streams are
   downsampled with LTTB to `points` (default 1500).
3. api/: FastAPI app with routers for the endpoints of §5 that these services cover. Export OpenAPI to
   docs/API.md (a script `training export-openapi`). Add API tests with TestClient against a seeded test DB.
4. ui-streamlit/: app.py with navigation and pages Dashboard (this week vs last 4: load, time, distance per
   sport; PMC mini; ACWR badge), Aktivity (filterable table → detail page with HR/pace/altitude Plotly chart,
   laps, time in zones, load breakdown hrTSS/rTSS/TRIMP, subjective RPE form saving via a service),
   Fitness (PMC chart with 90-day "warming up" band, weekly bars, monotony/ramp flags), Nastavenia (athlete,
   thresholds with valid_from history, zone table preview, diagnostics, "Run sync now" button that calls the
   CLI sync function synchronously with a spinner). Pages contain zero business logic.
5. Shared Plotly components in ui-streamlit/components/ that take DTOs only.
Verify visually with the real DB (describe what you see). Update STATUS.md, ruff, pytest, commit message.
```

**Akceptačné kritériá:** Streamlit beží nad reálnymi dátami; `GET /api/fitness/pmc` vracia to isté, čo vidíš v UI;
zmena LTHR s dátumom a `recompute` zmení len aktivity od toho dátumu.

---

### Fáza 4 – Progres bez wattov (1–2 sessions)

**Vznikne:** steady-state detekcia, EF, decoupling, speed–HR krivka + pace@refHR, best efforts, návrhy prahov,
predikcie; stránka Progres; endpointy `/progress/*`.

**Prompt:**
```
Read CLAUDE.md, METRICS.md §5–§7 and STATUS.md. Test-first with synthetic streams.

1. metrics/efficiency.py (§5: steady_state, EF run + bike variant, decoupling), metrics/efforts.py (§6.2 best
   efforts incl. HR efforts; §6.1 speed–HR curve with monthly snapshots into curve_snapshot; §6.3 threshold
   proposals as pure functions), metrics/predictions.py (§7 Riegel + Daniels VDOT with bisection solver;
   test: a 10 km in 40:00 gives VDOT ≈ 51.94 and HM ≈ 1:28:33 – see METRICS §7).
2. Extend pipeline + recompute; persist ef/decoupling/steady_state/pace_at_ref_hr_day in activity_metric
   and best efforts in best_effort.
3. services/progress.py + DTOs (SeriesDTO, CurveDTO, BestEffortsDTO, PredictionsDTO, ProposalDTO) + routers.
4. Streamlit page Progres: EF trend with 28-day median, decoupling scatter, speed–HR curves for the last 6
   months overlaid, pace@refHR trend, best-effort curves 90 d vs all-time, predictions table, threshold
   proposals with an "apply as new threshold valid from today" action in Nastavenia.
5. `training propose-thresholds` CLI prints the same proposals.
Report the current proposals and how many runs qualify as steady_state. Update STATUS.md, ruff, pytest, commit message.
```

**Akceptačné kritériá:** aspoň 30 % easy behov je `steady_state` (ak menej, preskúmaj prahy §5.1 a povedz mi to);
krivky sa vykreslia; predikcie zodpovedajú tvojim reálnym časom rádovo (±3 %).

---

### Fáza 5 – Spánok, readiness, korelácie (1–2 sessions)

**Vznikne:** baseline štatistiky, readiness skóre, korelačný modul, stránka Spánok, endpointy `/wellness/*`.

**Prompt:**
```
Read CLAUDE.md, METRICS.md §8–§9 and STATUS.md.

1. analysis/wellness.py: 28-day rolling median/MAD baselines; analysis/readiness.py per §8 with missing-component
   renormalization (tests: all components present; RHR missing; TSB extreme).
2. analysis/correlation.py per §9: dataset builder (one row per qualifying day), Spearman at lags 0/1/3-night
   mean, partial correlation via OLS residualization on controls, bootstrap CI (seeded), quartile contrast,
   `insufficient data` when n < 30. Tests on synthetic data with a planted correlation and a planted confounder.
3. Persist readiness into daily_load during recompute/sync.
4. services/sleep.py + DTOs (WellnessDTO, ReadinessDTO, CorrelationDTO) + routers.
5. Streamlit page Spánok: sleep duration/stages stacked bars, sleep score and RHR with baselines, sleep debt,
   readiness gauge for today with component breakdown, and a "Findings" section rendering each correlation as
   one plain-Slovak sentence + n/ρ/CI, sorted by |ρ|, with the fixed caveat text from §9.5.
Report today's readiness and the top 3 findings. Update STATUS.md, ruff, pytest, commit message.
```

**Akceptačné kritériá:** readiness sa počíta pre každý deň s wellness; korelácie sa ukazujú až pri n ≥ 30;
plantovaná korelácia v teste je detegovaná, plantovaný confounder zmizne po parciálnej korelácii.

---

### Fáza 6 – Tréner: sezóna, pravidlá, plán (2 sessions)

**Vznikne:** ciele, fázy sezóny, týždenné ciele, knižnica tréningov, denné rozhodnutie, stránka Plán.

**Prompt:**
```
Read CLAUDE.md, METRICS.md §10 and STATUS.md. Deterministic, rule-based, fully tested – no LLM in this phase.

1. coach/season.py (§10.1–10.2), coach/library.py (§10.7 as data, parametrized by duration), coach/workout.py
   (§10.5 schema as Pydantic + §10.6 estimated_load), coach/rules.py (§10.4 daily decision returning a
   PlannedWorkout + reason). Tests: each rule branch; a full simulated 16-week season with a fake CTL series.
2. `training plan-today` CLI and a nightly step in `sync` that creates/updates today's planned_workout if none exists.
3. services/plan.py + DTOs (SeasonDTO, WeekPlanDTO, DailyDecisionDTO, PlannedWorkoutDTO) + routers, incl.
   POST /plan/{id}/status (done/skipped) and matching a completed activity to a planned workout by date+sport.
4. Streamlit page Plán: goal editor, season timeline, this week (planned vs done with load bars),
   today's card (workout steps, estimated load, reason, readiness), buttons to mark done/skipped and to
   regenerate with a different sport.
Update STATUS.md, ruff, pytest, commit message.
```

**Akceptačné kritériá:** denný návrh sa mení podľa readiness/ACWR v testoch; simulovaná sezóna nikdy neprekročí
ramp 6/týždeň; plán je viditeľný v UI aj cez `/api/plan/today`.

---

### Fáza 7 – Push do Garminu, ranná správa, AI report (1–2 sessions)

**Prompt:**
```
Read CLAUDE.md, METRICS.md §10.8 and STATUS.md.

1. coach/garmin_push.py: convert the §10.5 structure into garminconnect running/cycling workouts with HR-zone
   targets, upload, schedule on the date, store garmin_workout_id; re-push updates instead of duplicating.
   Inspect the installed garminconnect workout module for the exact builder API. Dry-run flag prints the payload.
2. POST /plan/{id}/push + a button on the Plán page + `training push-today` CLI (used by cron after sync).
3. scripts/telegram_morning.py: optional; if TRAINING_TELEGRAM_TOKEN/CHAT_ID are set, send readiness, today's
   workout and yesterday's load in one message. Never fails the sync if Telegram is down.
4. coach/llm.py (optional, behind TRAINING_ANTHROPIC_API_KEY): weekly summary prompt built from DTOs only
   (last 7 days, PMC, top findings, next week plan) → short Slovak report stored in docs/reports/ and shown
   on Dashboard. The LLM never changes the plan; it explains it.
Update STATUS.md, ruff, pytest, commit message.
```

**Akceptačné kritériá:** tréning sa objaví v Garmin Connect kalendári a synchronizuje na hodinky; opakovaný push
nevytvorí duplikát; Telegram správa príde po rannom synce.

---

### Fáza 8 – Automatizácia a prevádzka (1 session)

**Prompt:**
```
Read CLAUDE.md and STATUS.md.

1. `training morning` CLI = sync → recompute affected → plan-today → push-today → telegram, with structured
   logging to data/logs/ and a non-zero exit code on failure. Idempotent, safe to run twice.
2. scripts/install_cron.sh (Linux/macOS crontab at 06:00) and docs for Windows Task Scheduler.
3. docker-compose.yml (optional target: Raspberry Pi / NAS): one service for Streamlit, one cron-like
   service running `training morning`, volume for data/ and the token dir. Document the token bootstrap
   (login once on the host, mount ~/.garminconnect).
4. Health: Dashboard shows "last successful sync" and turns red after 36 h; diagnostics lists the last errors.
5. Login-breakage playbook in docs/OPERATIONS.md: what to do when garminconnect login fails (update the
   library, re-run `training login`, wait for upstream fix – the DB is a cache, nothing is lost).
Update STATUS.md, commit message.
```

---

### Fáza 9 – React aplikácia (3–4 sessions; kedykoľvek po fáze 3, ideálne po 6)

Streamlit zostáva funkčný až do parity; potom sa `ui-streamlit/` zmaže.

**Prompt (session 1 – základ):**
```
Read CLAUDE.md, PLAN.md §5 and docs/API.md, STATUS.md.

Create frontend/ with Vite + React 18 + TypeScript, Tailwind, TanStack Query, TanStack Router, Recharts,
Zod schemas generated from docs/API.md (or openapi-typescript against the running API). PWA manifest +
service worker (workbox) for mobile home-screen use. Layout: bottom nav on mobile, sidebar on desktop; pages
Dashboard, Activities, Fitness, Progress, Sleep, Plan, Settings – start with Dashboard and Fitness using
the existing endpoints. Add CORS to FastAPI for the dev origin and a production mode where FastAPI serves
frontend/dist as static files at / (single process, single port). `uv run training api --serve-frontend`.
Update STATUS.md, commit message.
```

**Prompt (sessions 2–4 – parita):**
```
Port the remaining Streamlit pages to React one page per session in this order: Activities (list + detail
with synced HR/pace/altitude charts and RPE form), Progress, Sleep, Plan, Settings. Each page must use only
the /api endpoints; if a page needs data the API does not expose yet, add the endpoint + DTO in services/
first (the Streamlit page must keep working from the same service). When all pages match, delete
ui-streamlit/, remove streamlit from pyproject, update CLAUDE.md commands and docs. Update STATUS.md, commit.
```

**Akceptačné kritériá:** appka beží na jednom porte z FastAPI, funguje ako PWA na mobile, `services/` sa počas
migrácie nemenili okrem pridávania nových endpointov.

---

## 7. Ako pracovať s Claude Code počas projektu

- **Jedna fáza = jedna session.** Začni Plan mode („naplánuj fázu X podľa PLAN.md, neimplementuj“), prečítaj plán,
  oprav, potom implementácia. Po commite `/clear` – ďalšia fáza začína s čistým kontextom a číta STATUS.md.
- **Metriky vždy test-first.** Ak Claude Code navrhne inú konštantu než METRICS.md, nech to napíše ako
  návrh do STATUS.md → Decisions; ty rozhodneš a zmeníš doc.
- **Overuj proti Garminu.** Po fáze 2 porovnaj 5 aktivít: hrTSS vs. Garmin training load (rôzne jednotky, ale
  poradie musí sedieť), čas v zónach vs. Garmin Connect (má sedieť takmer presne).
- **Nikdy nedávaj heslo do promptu ani do súborov.** Login rob ty v termináli; Claude Code pracuje s tokenmi.
- **Keď sa rozbije Garmin login** (stáva sa po ich zmenách): `uv lock --upgrade-package garminconnect && uv sync`,
  `training login`, prípadne počkaj na fix knižnice. Dáta neprídu o nič – DB je cache.
- **Commit po každej fáze**, správa v tvare `phase-N: …`. Pri väčšej fáze aj priebežné commity po krokoch.
- **Refaktor len s dôvodom.** Ak Claude Code chce „vyčistiť“ architektúru, pripomeň CLAUDE.md pravidlá 1–3.

## 8. Riziká a záložné plány

| Riziko | Dopad | Riešenie |
|---|---|---|
| Neoficiálne Garmin API sa zmení | sync stojí dni | raw cache, aktualizácia knižnice, `OPERATIONS.md`; núdzovo Strava API (len aktivity) |
| HR dropouty na páse | zlé hrTSS | `hr_coverage` flag, rTSS pre beh, low_confidence v UI |
| Bike bez wattov = hrubý progres | menej presné trendy | EF_bike len na rovine s upozornením; Garmin VO2max; neskôr voliteľne wattmeter → pridať §2 power metriky |
| Málo dát na korelácie | falošné závery | tvrdý limit n ≥ 30, CI, parciálne korelácie, caveat text |
| Streamlit → React prepis | dvojitá práca | services + DTO + API od fázy 3; UI vrstvy bez logiky |
