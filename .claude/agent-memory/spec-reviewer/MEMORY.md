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

## Windows portability
- [Windows portability checklist](windows_portability.md) - encoding=, .env encoding, alembic %, CRLF artifacts, venv python path

## Phase 8 notes (2026-10-25, automation / ops)
- New pattern: RedactingFilter rewrites only record.getMessage(); exception tracebacks (exc_info/exc_text) and
  Typer pretty tracebacks reach the stderr handler unredacted (scratch-verified). Phase 8 redirects stderr to
  persistent files (cron.out, task.out, docker logs). Check exc_text/stack_info redaction on every stream handler.
- New pattern: daily loops that sleep a naive-local timedelta (`next_run_at(datetime.now(), at)`) shift by 1 h
  at DST: autumn wakes at 05:00 then runs AGAIN at 06:00, spring runs 07:00 (scratch-verified with zoneinfo).
  time.sleep is monotonic (host suspend, Pi clock jump). Ask for chunked sleep + recompute. Also check the loop
  catches every exception ("a failed run never stops the loop" comments are often false) and catches up a
  missed run after a restart.
- Docker checklist: container runs as root -> garminconnect re-dumps tokens on refresh (0600, os.replace) into
  the bind-mounted host token dir -> host user loses access; .dockerignore must mirror .gitignore secret
  patterns (garmin_tokens*.json, .garminconnect/); every PROJECT_ROOT-relative writable dir (reports_dir) must be
  on a volume; UV_NO_SYNC for exec'd commands. Build check that works offline-ish: `git archive HEAD | tar -x`
  into scratch, delete .dockerignore paths, `UV_PROJECT_ENVIRONMENT=<scratch>/venv uv sync --frozen --no-dev
  --extra ai` (verified OK in phase 8, PROJECT_ROOT resolves to the copy because uv installs editable).
- Lock files (O_CREAT|O_EXCL): stat() after FileExistsError can raise FileNotFoundError; stale takeover is a
  TOCTOU (two takers both run); __exit__ unlinks unconditionally (deletes a lock taken over from it). Prefer
  fcntl/msvcrt locks on a held handle. Also check which OTHER writers (UI "Run sync now", `training sync`,
  push-today) bypass the lock.
- Once-per-day markers (TELEGRAM_SENT_DATE) set after sending a provisional decision: the final plan of a later
  successful run is never announced. Check what the "once" message contained.
- dto.py 452 lines (still > 400). STATUS was updated this phase (first time since phase 4).

## §6.3 bike population / missing reasons (2026-10-25)
- New pattern: when a spec change narrows a POPULATION (rides with an 1800 s HR effort), the code also moved
  a separate CONDITION evaluated over the old population (bootstrap "no bike activity of the window has
  hrTSS/h" became "none of the rides WITH the effort"). Scratch: ride with hrTSS but no effort + effort rides
  without hrTSS -> avg_hr bootstrap and basis says "no bike threshold yet" although one exists. For every
  population change, list each predicate in the spec paragraph and check which set it is evaluated on.
- "Reason iff None" helpers: good design is reusing the same selection function (_lthr_selection) as the
  proposal; fuzz-check with random frames (scratch check_boot.py approach, 4000 cases, 0 mismatches).
- Formatted thresholds in user text (`{x:.2f}`) can round across the boundary ("highest 0.95" for 0.949 in
  "none reached >= 0.95"). Check every reason/caption that prints a value next to its cutoff.
- STATUS.md not updated again; dto.py 460 lines.

## Commutes §2.6 (2026-10-25, commit 091096e)
- Verified: Python is_commute == SQL commute_expr (3000-row fuzz, NULL moving/duration, overrides, 1500 edge,
  0 mismatches); migration 0004 (7c2e5f1a9b30 -> 643693e83815); normalize upserts only listed columns, so
  commute_override survives re-sync; _pre_taper_target returns T (not T_train), so taper = 0.5*T_pre - C.
- New pattern: "exclusion filters" as a population change. Mutation-test EVERY added filter (scratch worktree
  + replace-one-line script, ~20 s per mutant on the 11 relevant test files). Here 7 of 11 mutants survived
  (curves, §9, §6.3 frame, week view counts/load, season CTL uses T, set_commute curve refresh).
- New pattern: flags that change classification after the fact do not re-evaluate PERSISTED derived states
  (planned_workout done + completed_activity_id is never re-matched: match_completed only touches
  planned/pushed). Check every reclassification endpoint against stored matches/decisions.
- `compute_curve_snapshots` returns early on "no runs" -> snapshots never cleared when the last run is
  excluded (scratch-verified). Check early-return-on-empty before upsert loops whenever a filter is added.
- STATUS claims can exceed the code ("Plán week view shows commute_load" - only the DTO has it). Grep UI for
  every DTO field STATUS says is shown.
- User's 3 recorded real rides are 740-1064 s moving -> all commutes under §2.6.
- dto.py 470 lines. STATUS updated this time.

## Coach "Kondícia" §11 step 1 (2026-10-26, commit 51e1b04)
- Process: the orchestrator committed WHILE the review ran (asked for "uncommitted diff", tree was clean by
  the 2nd git call). Always `git log -1` + `git status` first; review HEAD if the tree became clean.
- Recurring (again): GET endpoints persist derived state. planning_fitness.ensure_week (called from GET
  /plan/week via existing_week and GET /plan/today via plan_day) freezes coach_week brake (Sunday ACWR,
  readiness, sleep debt) and coach_block base (4-week median) at first use, possibly before Monday's sync
  (Sunday-afternoon run not synced yet). Rows are never re-derived (not in recompute). Check every new
  "created on first use" table for input freshness + recompute.
- New pattern: retry windows vs time-of-day rules. "Final at 12:00" relies on a run at >= 12:00, but cron/
  Task Scheduler repeat `--at`+4 h and Docker MAX_RETRIES=4 x 1 h: `--at 05:45` never reaches noon ->
  plan waits forever, never pushed. Also daily_loop catch-up used ran_on (any run, incl. waiting).
- Mutation check again: 7/9 mutants survived in planning_fitness (all 3 commute filters, rTSS IF branch,
  ACWR and sleep-debt brakes, sleep_score-only wait). Workflow: `git worktree add --detach <scratch>/wt HEAD`,
  run with `UV_PROJECT_ENVIRONMENT=<repo>/.venv uv run --no-sync pytest` from the worktree (imports the
  worktree's training/, verified). ~5 s per mutant on the 2 fitness test files.
- conftest autouse fixture forces planning.mode_for -> "race" for all unmarked tests; real default mode
  (fitness) is only exercised by tests marked fitness_coach.
- Spec texts meant for the device ("vypni auto-pauzu") have no carrier: Step has no description field.
- File sizes: dto.py 480, morning.py 401, planning.py 400. STATUS updated this time.

## Kondícia round 2 (2026-10-26, commit fb2a2c5)
- Verified: coach_week.final + re-derive of non-final weeks (cascade) and `recompute` re-derive; migration 0006
  chains 3d9a4c71e2b5 -> 9b1e6d2f4a87, server_default false; 15/19 mutants killed (all commute filters, rTSS
  branch, both brakes, sleep-score wait, final flag, pipeline wiring, RETRY_UNTIL).
- New pattern: a "final/fresh" flag honoured by the writer (ensure_week) but not by a READ helper that returns
  the stored row (existing_week -> week view shows pre-sync numbers). Check every reader of a row that gains a
  freshness flag.
- New pattern: a hook added to pipeline.recompute also runs from every caller of it (athlete settings save,
  `training athlete`, purge-demo), not only the `recompute` command the spec names. Grep callers.
- Survivors again: behaviour changes with no tie test (5-min rounding halves up: no x.5 tie such as 42.5 min),
  one-line wiring fixes (cli ran_on -> ran_ok_on), exception-path fixes (IntegrityError re-read). Keep running
  the mutation script (scratchpad mut.py approach: list of (name, file, old, new), -x, 6 test files ~5-18 s each).
- Stale wording after the retry fix: MAX_RETRIES comment and daily_loop docstring still say "at most".

## Kondícia step 2 §11.4 block progress (2026-10-26, commit f1a0267)
- Process (again): committed during review (status showed dirty, HEAD already had it). Review HEAD.
- Mutation: 8/14 survived (all 3 commute filters in planning_block, run-sport filter -> bike EF in trend,
  candidates `<= end`, check-run key + status filters, `CoachWeek.monday <= today`, sleep window). Test files
  exercise only the seeded happy path. Ask for one negative case per WHERE clause.
- New pattern: spec "X is kept so Y is flagged" (reference_date -> stale > 60 d) implemented as data only;
  no DTO flag, UI never reads it. Grep the UI for every field a spec sentence says is "shown/flagged".
- New pattern: UI recomputes the DTO's `change` itself (and as a different quantity: EF in %), ignoring the
  service field. Check React for arithmetic on DTO values vs the spec's definition.
- Recurring: stored "filled when missing" values (coach_block.baseline) filled by a GET before the Monday
  sync and refreshed only by `training recompute` -> frozen stale for the whole block.
- dto.py 491 lines.

## Kondícia step 3 §11.5 predictions (2026-10-26, commit 4a65068)
- Process: other uncommitted work (wellness normalize/models/router = next Health task) sat in the tree while
  HEAD was reviewed; review only HEAD and do not attribute those files.
- Recurring (5th time): mutation survivors. 13/16 survived in coach/forecast.py + planning_forecast.py: >10 %
  singular-resample branch, negative-CI branch (tests use only positive slopes), v+dv<=0 guard, >=3 s/km and
  >=70 boundaries, sleep_s fallback in outlook, "pushed" status, both baselines, CTL/ATL prev + load_today
  wiring. Pure-function known-answer tests do not cover the DB glue; ask for one glue test per input.
- New pattern: "carry forward from X[today−1]" read with session.get(row of yesterday) silently falls back to 0
  when the row is missing (sync gap) instead of the last stored row -> TSB 0 (scratch: CTL 60/ATL 40 three days
  old -> tsb 0.0). Check every "yesterday's state" lookup for a missing-row fallback.
- New pattern: orientation-only extras appended inside an existing message builder (notify.morning_message)
  without their own try/except: any exception drops the whole Telegram message (send_morning catches all).
- Recurring: UI derives a spec-less quantity from DTO fields (Forecast.tsx secondsPerHour = s/km per hour of
  sleep) - business logic + formula outside METRICS.
- dto.py down to 396 (forecast DTOs split into dto_forecast.py). STATUS updated.

## Health page §12 (2026-10-26, commits 46b985b + ea128f3)
- Process: caller said "last two commits" (HEAD~2..HEAD) but the backend half was HEAD~2 itself (46b985b);
  HEAD~1 was an unrelated predictions fix. Map the described scope to commits with `git log --stat` first.
- Verified OK: §12.2 windows (mean7/28 incl. D, median/MAD of D−28..D−1 on a full calendar), pct, monthly,
  BH, Fisher CI 1.03/√(n−3), family skips, lag-1 shift, migration 0007 (9b1e6d2f4a87 -> 5e8c2a7d1f43, types
  match), rebuild_all re-normalizes wellness offline, upsert writes the new columns, empty DB does not 500.
- Recurring (6th time): mutation survivors 24/29 (every §12 threshold except mean7/MIN_N, BH and |ρ| ≥ 0.2
  gates, 28-day window edges, "better" direction, families battery/stress/activity, contrast quartile/min,
  raw-y contrast, ptp skip, health_frame end cut, service strength/side/days). Script: scratchpad mut.py
  (name, file, old, new) over test_analysis_health/test_services_health/test_normalize_wellness, ~3 s each.
- New pattern: quantile groups with `>= q3` / `<= q1` on zero-inflated series (load: 60 % rest days → bottom
  "quartile" = 60 % of days). Check tie handling of every quantile contrast.
- New pattern: UI fallback `mean7 ?? latest` under a "7 dní" caption - a fallback value shown with the
  primary value's label. Grep `??` next to labelled values.
- "No data = negative" clamps applied to a field that can be legitimately negative (sleep bodyBatteryChange).
- dto.py 408 lines again.
