# spec-reviewer memory (GarminAnalyzer)

## Recurring patterns to re-check every review
- Incremental recompute scope: for any derived store keyed by period (curve_snapshot months, weekly
  aggregates), check that the "touched" set covers periods whose window END moved (month rollover, sync gaps),
  not only periods containing changed activity dates. Phase 4: `months_touched([*days, last])` misses the
  previous month when no activity falls in its last days -> stale month-end snapshot (verified by scratch test).
- Interpretation choices written only in module docstrings ("Interpretation choices ...") instead of
  METRICS.md clarifications (rule 6). Ask to promote them into the "(proposed)" METRICS notes.
- Index-based shifts over kept samples (lag_hr, rolling windows) silently bridge pauses; check spec wording
  (by index vs by t) and flag if the spec itself bridges pauses.
- Rounded value vs raw value used for threshold/propose decisions (§6.3) - make sure spec says which.
- Test files creeping over ~400 lines (test_metrics_efforts.py 454 in phase 4).
- Error isolation: per-activity loops catch/rollback, but follow-up global steps (daily load, curves) run
  outside try; check they tolerate one broken activity.

## Useful review tooling
- Scratch DB tests: put test_*.py in the scratchpad and run
  `cd backend && uv run pytest -q -s -p no:cacheprovider -p tests.conftest --rootdir=<scratch> <file>`;
  fixture `session` (migrated tmp DB) and `tests.test_pipeline_progress.add_run` are reusable.
- Known-good numbers: VDOT(10 km, 40:00) = 51.944; HM equivalent 5312.8 s (1:28:33); Riegel HM 5295 s.
- test_db.py compares Alembic head with SQLModel metadata (compare_metadata), so model/migration drift fails tests.

## Project state notes
- Phase 4 METRICS clarifications (§0.6, §5-§7) marked "(proposed)", awaiting user approval as of 2026-09-29.
- Garmin LT speed unit (x10 when < 1) in services/garmin_values.py is an unverified guess.

## Round-2 notes (phase 4, 2026-09-29)
- Fixes verified: `pipeline_progress.refresh_curves` + sync_state `curves_refreshed_until` (rollover scratch
  test now matches full recompute), lag by time (`preprocess.has_lag_partner`/`lag_hr(t, hr)`).
- New pattern: state-key-based incremental logic has a first-run gap (key absent -> falls back to "now"), so
  data computed before the upgrade stays stale unless a full recompute is run. Check for this whenever a new
  sync_state cursor is introduced.
- Re-run my own scratch repro on round 2 instead of trusting the new unit test.

## Phase 5 notes (2026-09-29)
- New pattern: in-process result caches keyed by a "cheap fingerprint" (count/max/sum of ONE column per
  table). Always check the fingerprint covers every column the cached computation reads. services/sleep.py
  `_fingerprint` sums only ef/sleep_s/rpe/load_total -> rhr, sleep_score, deep/rem, BB, decoupling, pace,
  if_*, tsb/atl edits leave findings stale (scratch-verified: rhr sign flip -> cached rho unchanged).
  Also check for a second UI-layer cache (st.cache_data ttl) stacked on top.
- Persisted-vs-live duplicates (daily_load.readiness vs get_readiness recompute): equal by construction, but
  pre-upgrade DBs have NULL persisted values until `recompute` (same first-run gap as sync_state cursors).
- docs/STATUS.md not updated in phase 5 diff; check STATUS every review.
- dto.py crossed 400 lines (499) in phase 5; test_analysis_correlation.py 654 lines. Hard wall-clock
  timing asserts (<10 s) in unit tests - flag as flaky.
- Slovak sentence direction verified OK: phrase = higher predictor, sign of headline (partial else raw) rho
  flips outcome word; pace_at_ref_hr_day is m/s (higher = faster).

## Phase 5 round 2 (2026-09-29)
- Blocker 1 verified fixed: services/sleep.py now keys the cache by sha256 of
  `hash_pandas_object(frame.astype(object), index=True)` over the exact build_dataset inputs. Scratch-checked
  (pandas 3.0.6): same hash across processes (fixed hash_key); NaN/NaT/None, 1e-15 float edits, timestamp and
  index changes all detected; None vs NaN in an object column hash the same (harmless, both null).
  A cache hit costs about 0.15 s at 4 years of data. The Streamlit ttl cache was removed.
- New pattern: after a fix, docstrings and comments still describe the old mechanism (module docstring still
  says "database identity and a cheap fingerprint"; timing-test docstring says < 10 s but asserts < 30).
  Grep for the old wording every round 2.
- Check approval claims in STATUS against METRICS.md and the commit that approved them (phase 4 approval came in
  ea1c748, which is legitimate).

## Phase 6 notes (2026-09-29, coach)
- New pattern: "reference value computed virtually from the current state" instead of the stored history.
  coach/season.py `_virtual_pre_taper_target` uses CTL before the *current* Monday for the pre-taper week, and
  planning.week_target always calls season_plan(monday, 1, ...), so the 2nd taper week (and taper week 1 if
  Peak was not met) is not 0.5 x the real pre-taper target (§10.2). Check any "previous period" reference
  for whether it is read from history or reconstructed from today's state.
- New pattern: GET/view endpoints that persist a decision (services/plan.get_today via plan_day, called by
  GET /api/plan/today and the Streamlit Plán page). A view before the morning sync freezes a decision with
  readiness[D]/TSB[D] missing and without match_completed; nightly then keeps it. Check every "decide on
  first call" service for input freshness.
- Doc-change drift: when METRICS clarifications are edited mid-phase (ddd6f36 run share, a6d625a rule 1/2),
  module docstrings that quote the clarification are not updated (season.py, rules.py). Diff quoted text.
- Sync-wrapping try/except without session.rollback() (services/sync.py, cli/ingest.py) - flag each phase.
- STATUS.md again not updated (phase 6). test_coach_rules.py 481 lines.

## Phase 6 round 2 (2026-09-29)
- B1 verified: planning._pre_taper_target = weekly_target(CTL[pre_taper_monday − 1]) passed into season_plan;
  scratch-checked race offsets 0/3/7/10/13 days (all taper weeks = min(0.5·ref, cap)). New B1 test fails on
  ed6bc41 by value (real regression test).
- B2 verified: provisional = structure.origin "auto" + provisional flag, status "planned"; nightly re-decides only
  when ALL rows of the day are provisional. No id reuse: SQLAlchemy flushes the INSERT before the DELETE of the
  same mapper, so the new id = max+1 (scratch: 1 -> 2 -> regen 3). The `_inputs_complete` call sits before
  session.delete so autoflush cannot free the id first - keep an eye on new queries added between delete/add.
- New pattern: "freshness" flags based on a sync_state cursor that is committed MID-sync
  (LAST_ACTIVITY_SYNC is set before the wellness loop in garmin/sync.py). A 429 in wellness + a settings save
  (services/settings -> pipeline.recompute(end=today) creates daily_load[D]) makes a pre-wellness decision look
  complete. Check which cursor actually covers the inputs (readiness needs LAST_WELLNESS_DATE).
- New pattern: "never fails / rollback" tests that raise a plain exception without a failed flush pass on the old
  code too (test_a_planning_failure_never_fails_the_sync passed on ed6bc41). Run new tests against the base
  commit (git worktree in scratchpad) to see if they really fail without the fix.
- Stale wording again after the fix: planning module docstring ("plan today if nothing is planned yet"),
  services/plan.get_today and the /plan/today summary ("the same plan afterwards").

## Phase 7 notes (2026-09-29, Garmin push / Telegram / AI report)
- New pattern: secrets in URLs (Telegram `/bot<token>/`) leak through third-party DEBUG loggers, not our own
  log calls. cli/_app.py sets urllib3 to DEBUG under `-v`, and urllib3.connectionpool logs the request path.
  Scratch-reproduced with a local HTTP server. The "token never in logs" unit test only checks our logger at
  default level. Check every secret-in-URL call against the `-v` logger levels.
- New pattern: spec actions that only happen on the next explicit call (regeneration to rest -> delete only
  when the rest row is pushed) but the UI hides that call (no push button on rest cards) and cron only
  pushes today. Trace every "X causes Y in Garmin" rule to a caller that actually runs it.
- Non-idempotent POSTs other than the obvious one: schedule_workout is also a POST (retried by backoff, and
  re-sent after a crash before the save), so duplicate *calendar entries* are possible even when the workout
  itself is not duplicated. Also: a response parsed after a successful POST (created["workoutId"]) and a
  commit after it form a crash window. Suggest pending markers plus a lookup by name/schedule before re-POSTing.
- 404 on update/delete of a remote object the user removed by hand -> stuck row, cron fails every day. Check
  that every remote-id flow can recover from "gone".
- Cron re-push: push_day PUTs every already-pushed row on every run (no payload hash). Harmless but not a
  no-op. Ask for a hash skip.
- New routes that can raise ServiceError(502) often omit UPSTREAM from `responses=` (plan push routes).
- Optional extras (anthropic `ai`): the lazy import sits outside try/except, so a missing extra gives a raw
  ImportError / 500. Check every optional import.
- Report/week naming depends on the run weekday (ISO week of `today` + "next week" = today + 7). Check
  period labels of anything cron-generated.
- STATUS.md not updated for the third phase in a row. Generated personal reports in docs/reports are not
  gitignored.

## Phase 7 round 2 (2026-09-29)
- Verified: redaction filter on root handlers catches propagated records from any logger (urllib3 test uses a
  real local server); markers cleared on success; payload_hash skip never skips a date change; schedule and
  upload are 1-attempt POSTs; 404 on update/delete recovers. New push tests fail on the base commit (real).
- New pattern: pending markers only work if every code path that REPLACES the row or changes the lookup key
  carries them. Scratch-verified gaps: planning._decide_and_store copies structure["garmin"] only when
  garmin_workout_id is set (upload_pending dropped by a regeneration -> second upload); upload_pending is
  honoured only if it equals the CURRENT name; rest path ignores upload_pending (orphan); schedule_pending on
  day D1 is ignored after a date move to D2 (old entry never unscheduled). Check markers against: regen,
  name/key change, sport->rest, date change.
- Recovery lookups over a paged list (get_workouts(0, 100)) with unknown default order silently fail once the
  library grows past the page -> duplicate. Check ordering/paging of every "find by name" recovery.
- Entry-point scripts (scripts/*.py via typer.run) bypass the CLI callback, so anything installed there
  (logging setup, redaction) is missing on the cron path. Check every script entry point.
- Label fixes that do not move the data window: week_label now names the ended week, but weekly_inputs still
  uses today-6..today and "Tento/Budúci týždeň" = week of today / today+7 (Monday run -> upcoming week).
- A test that calls the new helper itself (log_redaction.install()) does not prove the wiring (cli/_app.py);
  it passed on the base commit with the module copied in.
