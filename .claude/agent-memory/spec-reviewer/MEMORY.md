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
