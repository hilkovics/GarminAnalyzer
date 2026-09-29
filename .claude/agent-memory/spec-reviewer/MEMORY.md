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
