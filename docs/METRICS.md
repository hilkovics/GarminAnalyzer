# METRICS.md – formula specification

Single source of truth for every computed number. Code references sections as `# METRICS §x.y`.
Inputs available: Garmin Connect JSON only – activity summaries, 1 Hz detail streams (HR, speed, altitude,
cadence, lat/lon, timer state), laps, HR-zone times, daily sleep, resting HR, Body Battery, stress, steps,
Garmin training load / training effect / VO2max estimates. **No power data.**

## 0. Stream preprocessing (applies to everything below)

1. Resample detail streams to 1 s. Forward-fill gaps ≤ 10 s; longer gaps stay NaN.
   *Clarified 2026-09-29:* the grid is `t = 0..T` in whole seconds since the first sample (floor; several
   samples in one second → the last one wins). Per channel, a gap is the time between two consecutive valid
   values a → b; it covers missing samples as well as nulls inside a channel (HR strap dropout, GPS loss).
   If `b − a ≤ 10 s` the seconds in between get a's value; otherwise all of them stay NaN (no partial fill).
   Leading/trailing NaN runs stay NaN.
2. Keep only samples where the timer is running (drop paused/stopped time). `moving_s` = number of kept samples.
   *Clarified 2026-09-29:* timer state comes from the timer channel (`sumDuration`). In a gap a → b of `g`
   seconds with timer increase Δ, the last `round(min(Δ, g))` seconds of (a, b] are running (so the resume
   sample b is running), the others paused; an unknown Δ counts as running, a negative Δ as 0. The first
   sample (t = 0) counts as running, so `moving_s` = 1 + Σ running seconds of all gaps.
3. HR validity: `40 ≤ hr ≤ 230`, else NaN. `hr_coverage` = valid HR samples / kept samples.
   If `hr_coverage < 0.70`, all HR-based metrics for the activity are flagged `low_confidence=True`.
   *Clarified 2026-09-29 (phase 2, approved):* applied to the kept samples of §0.2 (after the §0.1 forward-fill); an activity without any
   kept sample has `hr_coverage = 0`.
4. Speed: from Garmin speed stream (m/s); if missing, derive from cumulative distance (*clarified
   2026-09-29:* `(d_b − d_a) / (t_b − t_a)` on the seconds (a, b] between consecutive valid distance values;
   NaN over all of (a, b] when `t_b − t_a > 10 s`, and at t = 0). Clamp run speed to
   `0–7 m/s`, bike to `0–25 m/s`. Walking/stopped samples (run `< 1.0 m/s`, bike `< 2.0 m/s`) are kept for load
   metrics but excluded from efficiency/curve metrics.
   *Clarified 2026-09-29 (phase 2, approved):* clamping maps values below 0 to 0 and above the maximum to the maximum (they are not dropped);
   `other` uses the run limits.
5. Altitude: 5 s rolling median. Grade over a 10 s centred window: `grade = Δalt / Δdist`, clamp to ±0.30,
   NaN where `Δdist < 5 m`.
   *Clarified 2026-09-29 (phase 2, approved):* both windows are centred and computed on the kept samples in time order (a pause is skipped,
   not bridged by NaN). Rolling median: window 5 samples, at least 3 non-NaN values. Grade at sample i uses
   the samples i−5 and i+5 (clipped at the ends): `Δalt = alt[i+5] − alt[i−5]` (smoothed altitude),
   `Δdist = dist[i+5] − dist[i−5]` (cumulative distance). NaN if either value is missing or `Δdist < 5 m`.
6. HR lag: for any pairing of HR with pace/speed at sample level (§5, §6), shift HR **back** by 30 s.
   *Clarified 2026-09-29 (phase 4, approved):* pair **by time**, not by index:
   `hr_lagged(t) = hr(t + 30)` if every second of (t, t + 30] is a kept sample (no pause in between), else NaN – speed at second t is paired
   with the HR measured 30 s later (HR responds late). A pause inside (t, t + 30] therefore gives no partner,
   so speed before a stop is never paired with the recovered HR after it.

## 1. Thresholds and zones

Per sport (`run`, `bike`) and time-versioned (`valid_from`):

- `lthr` – lactate-threshold HR (bpm). Manual, with auto-proposals (§6.3).
- `threshold_speed` (run only, m/s) – speed sustainable ~60 min. Stored as speed; shown as pace.
- `max_hr`, `rest_hr` (athlete-level; `rest_hr` defaults to 28-day median of Garmin RHR).

**HR zones (Coggan, % of LTHR), half-open intervals on `r = hr / lthr`:**
Z1 `r < 0.68`, Z2 `0.68 ≤ r < 0.84`, Z3 `0.84 ≤ r < 0.95`, Z4 `0.95 ≤ r ≤ 1.05`, Z5 `r > 1.05`.
Boundaries stored per threshold record so they are reproducible. The user should set identical zones in
Garmin Connect (LTHR-based) so pushed workouts (§10) match.

**Run pace zones (% of threshold_speed), half-open intervals on `s = speed / threshold_speed`:**
Z1 `s < 0.78`, Z2 `0.78 ≤ s < 0.88`, Z3 `0.88 ≤ s < 0.95`, Z4 `0.95 ≤ s ≤ 1.05`, Z5 `s > 1.05`.

*(Changed 2026-09-29: the previous closed ranges `0.68–0.83`, `0.84–0.94` left gaps such as r = 0.835 unassigned.)*

`time_in_zone` per activity: seconds of valid HR samples per HR zone (and per pace zone for runs).
*Clarified 2026-09-29 (phase 2, approved):*
- Counted over the kept samples of §0.2. Pace zones use `gap_speed` (§3; equals speed where grade is NaN)
  and need a valid speed; walking samples count (they fall into Z1).
- `threshold.zones` stores the boundaries as `{"hr": [0.68, 0.84, 0.95, 1.05], "pace": [0.78, 0.88, 0.95,
  1.05]}`; `time_in_zone` is `{"1": s, …, "5": s}` (all five keys present, integers).
- Threshold resolution: the record of the activity's sport with the latest `valid_from ≤ local_date`.
  `other` uses the run record (LTHR only). No record → all threshold-based metrics are null.

## 2. Training load (all in TSS-equivalent points: 1 h at threshold = 100)

### 2.1 hrTSS (primary for bike and "other", secondary for run)

Map relative HR `r = hr / lthr` to an intensity factor with piecewise-linear interpolation through
(derived from the Coggan HR-zone ↔ power-zone correspondence, anchored so that LTHR ⇒ IF 1.0):

| r    | IF   |
|------|------|
| 0.50 | 0.30 |
| 0.68 | 0.55 |
| 0.83 | 0.75 |
| 0.94 | 0.90 |
| 1.00 | 1.00 |
| 1.05 | 1.05 |
| 1.15 | 1.20 |

Clamp `r` to `[0.50, 1.15]` before interpolation.
`hrTSS = Σ_i IF_i² · dt_i / 36` with `dt_i = 1 s` (derivation: `TSS = s · IF² · 100 / 3600`).
`IF_hr` (activity) = `sqrt(hrTSS · 36 / moving_s)`.
Tests: 3600 s at `hr == lthr` → `hrTSS == 100.0`; 3600 s at `r = 0.83` → `hrTSS == 56.25`.
*Clarified 2026-09-29 (phase 2, approved):* the sum runs over kept samples with valid HR (samples with NaN HR contribute 0); `moving_s` in
`IF_hr` is the §0.2 count including samples without HR. `lthr` missing → `hrTSS`, `IF_hr` null.
*Changed 2026-09-29 (approved by the user):* an activity with **no valid HR sample** (`hr_coverage == 0`, e.g. a
ride without the strap) has `hrTSS`, `IF_hr`, `TRIMP` and `TRIMP_norm` **null** (unknown), not 0. Its
`load_primary` is then null unless §2.4 selects rTSS. It still contributes 0 to `daily_load` (§4) – there is
nothing to impute – but it is flagged: diagnostics count it in `activities_without_load` and the UI marks it.

### 2.2 TRIMP (Banister) – secondary, reported for comparison

`HRr_i = (hr_i − rest_hr) / (max_hr − rest_hr)`, clamp `[0, 1]`.
Male: `TRIMP = Σ_i (dt_i/60) · HRr_i · 0.64 · e^(1.92·HRr_i)`; female: `0.86 · e^(1.67·HRr_i)`.
`TRIMP_norm = TRIMP · 100 / TRIMP_ref`, where `TRIMP_ref` = TRIMP of 60 min at `hr == lthr` for this athlete/sport.
*Clarified 2026-09-29 (phase 2, approved):* over kept samples with valid HR, `dt_i = 1 s`. `rest_hr` = athlete `rest_hr_override`, else the median
of `daily_wellness.rhr` over the 28 days ending on the activity's local date (null if none). `TRIMP` and
`TRIMP_norm` are null if `sex`, `max_hr`, `rest_hr` or `lthr` is missing or `max_hr ≤ rest_hr`.

### 2.3 rTSS (primary for runs with usable GPS and a threshold_speed)

`gap_speed_i` from §3. Normalized graded speed: `NGS = ( mean( rolling_mean_30s(gap_speed)^4 ) )^(1/4)`
over moving samples. `IF_pace = NGS / threshold_speed`. `rTSS = moving_s · IF_pace² / 36`.
Usable GPS: distance stream present, `≥ 90 %` of moving samples with speed, not treadmill/indoor.
*Clarified 2026-09-29 (phase 2, approved):* `rolling_mean_30s` is a trailing 30-sample mean over the kept samples; windows containing NaN are
skipped, and fewer than 30 valid windows → `rTSS` null. "Distance stream present" = at least one non-NaN
distance value. `threshold_speed` missing → `rTSS`, `IF_pace` null.

### 2.4 Primary load selection

- run → `rTSS` if available else `hrTSS`
- bike, other → `hrTSS`
- if `low_confidence` and Garmin `training_load` present → keep computed value but flag; do **not** substitute.
Store `load_primary`, `load_method`, `hrtss`, `trimp_norm`, `rtss`, `if_hr`, `if_pace`, `low_confidence`.

### 2.5 Sanity check (reported in Settings → Diagnostics)

Pearson r between `load_primary` and Garmin `training_load` across all activities with both present.
Expect `r > 0.8`. Below 0.7 → show a warning to review thresholds.
*Clarified 2026-09-29 (phase 2, approved):* needs at least 3 activities with both values, else `r` is null.

## 3. Grade-adjusted pace (GAP) – runs

Metabolic cost of running (Minetti et al. 2002), `i` = grade (fraction):
`C(i) = 155.4·i⁵ − 30.4·i⁴ − 43.3·i³ + 46.3·i² + 19.5·i + 3.6` (J/kg/m), `C(0) = 3.6`.
`gap_speed_i = speed_i · C(grade_i) / C(0)`. Where grade is NaN use `gap_speed = speed`.
*Changed 2026-09-29 (approved by the user):* `gap_speed` is clamped to the run speed range of §0.4
(`0–7 m/s`), so an altitude/GPS glitch at the ±0.30 grade clamp (C(0.30)/C(0) ≈ 3.5) cannot inflate NGS/rTSS.
Tests: flat run → `gap == speed`; +10 % grade at 2.5 m/s → GAP ≈ 2.5 · C(0.10)/3.6 ≈ 4.1 m/s.

## 4. Performance Management Chart (daily)

`daily_load[d]` = Σ `load_primary` of activities whose **local start date** is `d` (0 on rest days).
Series starts at the first synced day; the first 90 days are shaded "warming up" in the UI.

- `CTL[d] = CTL[d−1] + (daily_load[d] − CTL[d−1]) / 42`
- `ATL[d] = ATL[d−1] + (daily_load[d] − ATL[d−1]) / 7`
- `TSB[d] = CTL[d−1] − ATL[d−1]`
- `acute = mean(daily_load[d−6..d])`, `chronic = mean(daily_load[d−27..d])`, `ACWR = acute / chronic`
  (NaN if `chronic < 5`). Bands: `< 0.8` under, `0.8–1.3` optimal, `1.3–1.5` caution, `> 1.5` danger.
- `monotony = mean7 / std7` of daily loads (NaN if `std7 == 0` or fewer than 4 training days in 28 d).
- `strain = sum7 · monotony`
- `ramp_rate = CTL[d] − CTL[d−7]`. Warn if `> 6`.
- Weekly aggregates: ISO weeks, per sport: load, duration, distance, elevation, `time_in_zone`.
  Polarization index = share of time in Z1–Z2 vs Z3 vs Z4–Z5.

*Clarified 2026-09-29 (phase 2, approved):*
- `CTL` / `ATL` of the day before the first day are 0, so the first day's `TSB` is 0.
- Windows (`acute`, `chronic`, `mean7`, `std7`, `sum7`, the 28-day training-day count) include day d and
  need their full length of series history; before that the value is NaN. `std7` is the population
  standard deviation (ddof = 0). A training day is a day with `daily_load > 0`.
- `ramp_rate` is NaN for the first 7 days. Flags: `ramp_warning = ramp_rate > 6`, `acwr_band` per the
  bands above (NaN → no band), read as half-open: `< 0.8` under, `[0.8, 1.3)` optimal, `[1.3, 1.5]` caution,
  `> 1.5` danger. `std7 == 0` means all seven loads are equal (exact comparison, so floating-point residue of
  a constant window never yields a huge monotony). Because the 28-day training-day count needs full history,
  monotony and strain start on day 28.
- `daily_load` is split into `load_run`, `load_bike` (and `other`, part of the total only). An activity with
  a null `load_primary` contributes 0.
- Weekly aggregates: ISO week (Monday start). Duration = `duration_s` (timer time). Polarization shares use
  the HR `time_in_zone` totals of the week: `(Z1+Z2, Z3, Z4+Z5) / total`, null if the total is 0.

## 5. Aerobic efficiency and endurance (runs; bike variant in §5.4)

### 5.1 Steady-state detection
An activity is `steady_state` if, after dropping the first 600 s: `moving_s ≥ 1800`, `hr_coverage ≥ 0.9`,
mean HR in `[0.70, 0.88]·lthr`, std of 60 s-averaged HR `< 6 bpm`, and no continuous ≥ 60 s stretch with
`hr > 0.95·lthr`.
*Clarified 2026-09-29 (phase 4, approved):* all conditions are evaluated on the kept samples (§0.2) that remain after dropping the first 600 s
of moving time: `moving_s` here means their count, `hr_coverage` their valid-HR share. "60 s-averaged HR"
= means of consecutive non-overlapping 60-sample blocks (last partial block dropped, blocks with fewer than
30 valid HR values skipped); population std. The ≥ 60 s stretch counts consecutive kept samples with
valid HR above the limit (a NaN breaks the stretch). No threshold (lthr) → not steady state. Steady state
uses raw HR (no lag) and keeps walking samples (so long walk breaks can fail the HR checks);
EF/decoupling/curves use the §0.6 lag.

### 5.2 Efficiency Factor (EF)
On steady-state runs, after dropping the first 600 s and walking samples:
`EF = mean(gap_speed) [m/min] / mean(hr) [bpm]`. Trend: 28-day rolling median over steady-state runs
(show points + median line). Higher = fitter.
*Clarified 2026-09-29 (phase 4, approved):* samples = kept, after the first 600 s, not `is_slow`, with the §0.6 lag applied, and only pairs
where both `gap_speed` and lagged HR are valid. `m/min` = m/s · 60. Trend value on day d = median EF of the
steady-state runs with `local_date` in [d − 27, d]; null if none.

### 5.3 Aerobic decoupling (Pa:HR)
Same samples as EF, split into two equal halves: `EF1`, `EF2`.
`decoupling_pct = (EF1 − EF2) / EF1 · 100`. Bands: `< 5` good, `5–10` moderate, `> 10` poor endurance.
*Clarified 2026-09-29 (phase 4, approved):* halves by sample count of the EF sample set (first ⌊n/2⌋ vs the rest); needs ≥ 600 samples, else
null. Band edges half-open: `[5, 10]` moderate.

### 5.4 Bike efficiency (approximate, no power)
Use only samples with `|grade| ≤ 0.01`, speed `≥ 4 m/s`, after 600 s, no stops within ±30 s.
`EF_bike = mean(speed) [m/min] / mean(hr)`. Steady-state definition as §5.1. Show with a "terrain/wind
dependent – trend only" caveat. Decoupling as §5.3 on the same samples.
*Clarified 2026-09-29 (phase 4, approved):* a "stop" is a pause (a gap in `t` between consecutive kept samples) or a slow sample (§0.4, bike
`< 2.0 m/s`); every sample within 30 s (by `t`, inclusive) of a stop is excluded; the missing whole seconds of a
pause count as stop instants. Uses `speed`, not GAP; lag as §5.2.

## 6. Speed–HR curve, best efforts, threshold proposals

### 6.1 Speed–HR curve (runs; the main progress indicator without power)
For a trailing 28-day window: pool 60 s aggregates (mean gap_speed, mean HR with 30 s lag) from all runs,
excluding first 600 s and walking. Bin HR in 5 bpm bins; per bin take the median gap_speed, require ≥ 10
aggregates per bin. `pace_at_ref_hr` = value in the bin containing `ref_hr = 0.80·lthr` (configurable).
Store the curve monthly (month-end snapshots) to show shift over time. Present as pace (min/km).
*Clarified 2026-09-29 (phase 4, approved):*
- 60 s aggregate: take the kept samples after the first 600 s that have a lagged partner, remove slow
  samples, then cut the rest into consecutive non-overlapping 60-sample blocks (a block may span a short
  walking break); a block counts if every sample has valid gap_speed and lagged HR; mean gap_speed, mean HR.
- Bin = `floor(mean_hr / 5) · 5` (label = lower edge, e.g. 145 = [145, 150)). Bins with < 10 aggregates
  are omitted.
- `ref_hr = 0.80 · lthr` of the run threshold valid at the window end; `pace_at_ref_hr` = the median of the
  bin containing `ref_hr`, null if that bin is omitted.
- Snapshot for month M = the curve of the 28 days ending on the last day of M (or today for the current
  month), stored as `{"bins": {"145": v, …}, "counts": {…}, "ref_hr": x, "pace_at_ref_hr": v}`.
- `pace_at_ref_hr_day` (§9) = median gap_speed of that activity's own 60 s aggregates with mean HR in
  `[ref_hr − 5, ref_hr + 5]` (read "reference bin ±5 bpm" as ±5 bpm around ref_hr); needs ≥ 20 such
  aggregates, else null. Its trend on the Progres page uses the same 28-day median as §5.2.

### 6.2 Best efforts
Windows `W ∈ {60, 300, 600, 1200, 1800, 3600} s`. For each activity and W: max over all positions of the
mean of `gap_speed` (run) or `speed` (bike, W ≥ 300 only) over a contiguous window of moving samples
(no pause inside). Also **HR best efforts**: max rolling-mean HR over `{1200, 1800, 3600} s`.
Curves: best per W over trailing 90 days and all-time.
*Clarified 2026-09-29 (phase 4, approved):* "contiguous" = consecutive kept samples whose `t` increases by exactly 1 (no pause, no gap);
every sample in the window must have a valid value (a NaN breaks the window). The effort's distance is
`distance[last] − distance[first − 1]` when the sample before the window is contiguous (t = t_first − 1),
else `(distance[last] − distance[first]) · W / (W − 1)` – so W seconds of travel are counted, not W − 1
(stored with the effort; null if unavailable). HR efforts
for all sports; HR efforts use raw HR (no §0.6 lag, nothing is paired) and include walking samples, as
do speed efforts. Ties: the earliest position wins. Trailing 90 days = `local_date` in [today − 89, today].

### 6.3 Threshold proposals (never auto-applied; user confirms in Settings)
- `threshold_speed_est` = max over trailing 90 days of best 1800 s gap_speed (fallback: 0.95 · best 1200 s).
  Propose when it differs from current by `> 2 %`.
- `lthr_est` (per sport) = max over trailing 90 days of the 1800 s HR best effort **from activities with
  `if_pace ≥ 0.95` (run) or with the top-decile hrTSS/h (bike)**. Propose when `|Δ| > 3 bpm`.
- Show Garmin's own VO2max and lactate-threshold values (when available) next to the proposal.
*Clarified 2026-09-29 (phase 4, approved):* "current" = the threshold valid today. `lthr_est` for runs uses activities with `if_pace ≥ 0.95`; for
bikes, the activities whose `hrtss / (moving_s / 3600)` is in the top 10 % (≥ the 90th percentile, at least
one activity) among the sport's activities of the window. No qualifying data → no proposal. Without a
current threshold the estimate is always proposed. Proposals round: speed to 0.01 m/s, LTHR to whole bpm (half-up), and the > 2 % / > 3 bpm rules compare the
**rounded** estimate with the current value (so the shown numbers match the decision). The bike 90th
percentile uses linear interpolation (numpy default), capped at the maximum.

## 7. Race predictions (runs)

Reference performance = best of: activities flagged `is_race`, or best efforts with `W ≥ 600 s`,
converted to (distance, time) using the effort's actual distance.
- **Riegel:** `T2 = T1 · (D2/D1)^1.06` for 5 km, 10 km, 21.0975 km, 42.195 km.
- **Daniels VDOT:** with `v` in m/min and `t` in minutes: `VO2 = −4.60 + 0.182258·v + 0.000104·v²`,
  `pct = 0.8 + 0.1894393·e^(−0.012778·t) + 0.2989558·e^(−0.1932605·t)`, `VDOT = VO2 / pct`.
  Equivalent race time for distance D: solve `t` such that `VDOT(D/t, t) == VDOT` (bisection).
Show both; flag when the reference effort is older than 60 days.
*Clarified 2026-09-29 (phase 4, approved):* candidates = run `is_race` activities (distance_m, duration_s) and run gap_speed best efforts with
`W ≥ 600 s` and a known distance (distance, W), from the trailing 90 days (if none: all-time). The
reference is the candidate with the highest VDOT; Riegel and Daniels both start from it. Distances whose
reference distance is under 1/4 of the target are still predicted (flagged `extrapolated`). VDOT ties go to
the most recent candidate; "older than 60 days" = `today − local_date > 60`.
Tests: 10 km in 40:00 → `VDOT ≈ 51.94` (± 0.05); equivalent half marathon ≈ 1:28:33 (± 10 s).

## 8. Wellness, baselines, readiness

Daily wellness fields: `sleep_start, sleep_end, sleep_s, deep_s, light_s, rem_s, awake_s, sleep_score,
rhr, body_battery_wake, body_battery_min, stress_avg, steps, weight` (all nullable).
Baselines: trailing 28-day median and MAD (median absolute deviation) for `rhr, sleep_s, sleep_score, body_battery_wake`.

**Readiness (0–100)** = weighted mean of available component scores (weights renormalized if a component is missing):

| Component     | Weight | Score (clamp 0–100)                                                  |
|---------------|--------|----------------------------------------------------------------------|
| RHR           | 0.30   | `100 − 12.5 · max(0, rhr − rhr_median28)`                            |
| Sleep         | 0.30   | `sleep_score`; fallback `100 · sleep_s / max(7.5 h, sleep_s_median28)` |
| Body Battery  | 0.20   | `body_battery_wake`                                                  |
| Form          | 0.20   | `50 + 2 · TSB` (TSB from §4, today's value)                          |

Bands: `≥ 70` green (train as planned / can push), `45–69` yellow (as planned, nothing extra),
`< 45` red (easy or rest).

*Clarified 2026-09-29 (phase 5, proposed):*
- Wellness row `D` = the night that ends on the morning of `D` (Garmin's sleep `calendarDate`), RHR / Body
  Battery of day `D`.
- Baseline of day `D` = median and MAD over the valid values of the 28 days `D−28 … D−1` (day `D` itself is
  excluded, so a bad night cannot pull its own baseline). Needs ≥ 7 valid values, else null. MAD is the raw
  median absolute deviation (no 1.4826 scaling); it is only displayed (baseline ± MAD band).
- Components: RHR is null if `rhr` or its median is null. Sleep uses `sleep_score` if present, else the
  fallback if `sleep_s` is present (a null median counts as 7.5 h). Body Battery is `body_battery_wake`.
  Form uses `TSB[D]` from §4 (already the state entering the day). Each score is clamped to 0–100.
- Readiness is computed for every day with at least one wellness component (RHR, Sleep or Body Battery).
  Form alone does not produce a score. Missing components drop out and the remaining weights are
  renormalized to sum 1 (the reported weights are empty when there is no score). The value is stored
  unrounded in `daily_load.readiness`; bands are applied to that unrounded value (`45 ≤ x < 70` yellow), and
  the UI displays it truncated to an integer, so the shown number always matches its band (69.98 → "69",
  yellow).

## 9. Sleep ↔ performance correlation

Day-level dataset (`analysis/correlation.py`), one row per day with a qualifying run/bike:

- **Outcomes:** `ef` (§5.2 / §5.4, steady-state only), `decoupling_pct`, `pace_at_ref_hr_day` (§6.1 method
  applied to that single activity, requires ≥ 20 min in the reference bin ±5 bpm), `rpe_residual =
  rpe − rpe_expected` where `rpe_expected = 1 + 9 · clamp((IF_primary − 0.5) / 0.7, 0, 1)`.
- **Predictors (night before, "lag 0"):** `sleep_s, deep_s, rem_s, sleep_score, rhr, body_battery_wake`;
  plus `sleep_3n_mean`, `sleep_debt_7 = Σ_{7 nights} (max(8 h, sleep_s_median28) − sleep_s)`.
- **Controls:** `TSB`, `ATL`, previous day's `daily_load`.

Method:
1. Spearman ρ for each (predictor, outcome) at lag 0, lag 1 (two nights before), and 3-night mean.
2. Partial correlation: OLS-residualize both variables on the controls, then Spearman on residuals.
3. 1000-sample bootstrap 95 % CI for ρ. Report `n, ρ, CI, p`. If `n < 30` → "insufficient data".
4. Quartile contrast: mean outcome for top vs bottom quartile of the predictor, with bootstrap CI.
5. UI shows a plain-language sentence per finding and always the caveat that correlation ≠ causation
   and that HR-based EF is affected by heat, caffeine and illness.

*Clarified 2026-09-29 (phase 5, proposed):*
- **Per sport.** Run and bike form separate datasets (EF units differ); `other` is excluded. A qualifying
  day `D` has ≥ 1 activity of that sport with at least one non-null outcome. If there are several, the one
  with the longest `moving_s` is used.
- **Outcomes** are read from `activity_metric` (null if not steady state, per §5). `pace_at_ref_hr_day` is
  run only. `IF_primary` = `if_pace` when `load_method = rTSS`, else `if_hr`. `rpe` comes from `subjective`
  for that activity. `rpe_residual` is null if either value is missing.
- **Predictors.** For each base predictor, three variants: `lag0` = wellness row `D`, `lag1` = row `D−1`,
  `mean3` = mean of rows `D−2 … D` (needs ≥ 2 valid values). `sleep_3n_mean` is the `mean3` variant of
  `sleep_s`. `sleep_debt_7` is `lag0` only: the sum over nights `D−6 … D`, each term using that night's §8
  baseline (8 h floor here, as written; a null median counts as 8 h). Surpluses offset deficits. It needs ≥ 5 valid
  nights, and the sum is scaled by `7 / n_valid`.
- **Controls:** `TSB[D]` (§4, pre-day), `ATL[D−1]`, `daily_load[D−1]`. Values from before the activity are
  used, so the session's own load does not leak into its controls.
- `n` = rows where predictor and outcome are both non-null (plus all controls, for the partial correlation).
  If `n < 30`, status is `insufficient_data` and ρ, CI, p and the contrast are null (`n` is still reported).
- **Spearman:** `scipy.stats.spearmanr`, p-value from its t approximation. **Partial:** OLS with an
  intercept on the three controls, for predictor and outcome separately, then Spearman on the two residual
  vectors (p not df-adjusted).
- **Bootstrap:** 1000 resamples of the `n` rows with replacement, `numpy.random.default_rng(seed)` with
  `seed = 0` by default. For the partial correlation each resample re-runs the residualization. The CI is
  the percentile interval (2.5 %, 97.5 %). Resamples that yield NaN (a constant column) are dropped; if more
  than 10 % are NaN, the CI is null.
- **Quartile contrast:** `Q1`/`Q3` of the predictor (numpy linear quantiles), `bottom = x ≤ Q1`,
  `top = x ≥ Q3`. Contrast = `mean(outcome | top) − mean(outcome | bottom)`, not partialled, with a
  bootstrap CI (same resamples). It needs ≥ 5 rows in each group, and is null whenever ρ is null (e.g. a
  constant predictor, where both groups would be every row).
- **Findings:** every (sport, predictor variant, outcome) with `n ≥ 30`, sorted by |partial ρ| (raw ρ if the
  partial is null). A finding whose CI contains 0 is labelled uncertain. No multiple-comparison correction
  is applied; the caveat text says so.
- Numerical edge cases: residuals whose size is at rounding level (the controls explain the variable
  completely) are set to exactly 0, so the partial ρ is null rather than a correlation of noise; a control
  that is constant within a resample is handled by the pseudo-inverse. Ties in `moving_s` when picking the
  day's activity go to the lower activity id.

## 10. Coach: season plan, daily decision, workouts

### 10.1 Season phases (from goal race date `R`)
`weeks_to_R > 12` → **Base**; `12 ≥ weeks > 3` → **Build**; `3 ≥ weeks > 1` → **Peak**; last 7–10 days → **Taper**.
No goal → perpetual Base/Build alternating 3 weeks build + 1 recovery.
*Clarified 2026-09-29 (phase 6, proposed):* phases are per ISO week (Mon–Sun). `d` = days from the week's
Monday to `R` (the active goal with the earliest `race_date ≥ Monday`): `d > 84` Base, `21 < d ≤ 84` Build,
`10 < d ≤ 21` Peak, `0 ≤ d ≤ 10` Taper ("last 7–10 days" rounded to whole weeks, so the taper is 5–11 days
long). Weeks after `R` (and without any goal): the no-goal cycle, phase "Base", anchored on
`k = (Monday − 2024-01-01).days // 7`; `k % 4 == 3` is the recovery week.

### 10.2 Weekly targets
`weekly_target_load = 7 · (CTL_now + 6 · ramp)` with `ramp` (target CTL increase per week) = 4 (Base),
5 (Build), 0 (Peak), Taper = 50 % of previous week. Every 4th week is a **recovery week**: target · 0.70.
Run:bike split from settings (e.g. 60:40). Cap weekly `ramp_rate` (§4) at 6.
Derivation: with the 42-day constant, a constant daily load `L` changes CTL by ≈ `7 · (L − CTL) / 42 =
(L − CTL) / 6` per week, so raising CTL by `ramp` per week needs `L ≈ CTL + 6 · ramp`.
*(Changed 2026-09-29: the previous `7 · (CTL_now + ramp)` only raised CTL by ≈ ramp/6 per week.)*
*Clarified 2026-09-29 (phase 6, proposed):*
- `CTL_now` = CTL of the day before the week's Monday (0 if unknown). For future weeks (season timeline,
  simulation) CTL is projected by assuming each week's target is met as a constant daily load `T / 7`.
- Taper target = 0.5 × the target of the last week before the taper (not compounding over two taper weeks).
- Recovery week with a goal: Base/Build weeks with `d // 7 ≥ 4` and `(d // 7) % 4 == 0`; Peak and Taper
  weeks are never recovery weeks. Without a goal see §10.1.
- Ramp cap: with a constant daily load, CTL after 7 days rises by `(L − CTL)·(1 − (41/42)^7)`; the target is
  capped at `7 · (CTL_now + 6 / (1 − (41/42)^7))` so the projected weekly ramp never exceeds 6.
- Split: `run_share` = athlete `run_bike_split`; if null, the run share of `load_run + load_bike` over the last
  28 days ("other" load is not planned); 1.0 if there is no load. Run target = `T · run_share`, bike = the rest.

### 10.3 Weekly templates (sessions to place Mon–Sun; user picks fixed days in settings)
- Base: 1 × long (run or bike), 1 × tempo/hills, 3–4 × easy, 1 rest.
- Build: 1 × long, 1 × threshold intervals, 1 × VO2/hard hills, 2–3 × easy, 1 rest.
- Peak: 1 × long (shorter), 1 × race-pace session, 1 × short intervals, easy, 2 rest.
- Taper: 1 × short race-pace, strides, easy; volume −50 %, keep 2 short intense touches.
*Clarified 2026-09-29 (phase 6, proposed):* a week has a **role per weekday**: `rest`, `easy`, `long`, `q1`,
`q2`. Athlete `preferred_days` (`{"mon": "rest" | {"role": "long", "sport": "bike"}, …}`) overrides the
default `mon rest, tue q1, wed easy, thu q2, fri easy, sat long, sun easy`. Per phase:
- Base: `q2` → easy. Build: as is. Peak: the easy day right before `long` (else the last easy day) → rest.
  Taper: `long` → easy.
- Slot → workout (§10.7): run – Base `q1` rotates tempo / hill repeats / progression by `k % 3`; Build `q1`
  threshold intervals, `q2` VO2 intervals (even `k`) or hill repeats (odd `k`); Peak `q1` race-pace, `q2`
  short intervals; Taper `q1` short race-pace, `q2` strides; `easy` easy run; `long` long run (Peak: shorter
  range). Bike – `easy` endurance, `long` long ride, Base `q1` sweet spot, Build `q1` over-unders, `q2` bike
  VO2 intervals, Peak `q1` race-pace, `q2` short intervals, Taper `q1` short race-pace, `q2` spin-ups.
- Sport: explicit `preferred_days` sport; else `q1`/`q2`/`long` use the goal sport (run without a goal);
  `easy` uses the sport with the larger remaining weekly target (run on a tie).

### 10.4 Daily decision (run every morning after sync)
Inputs: readiness (§8), `ACWR`, `TSB`, `monotony`, sessions already completed this week, template.
1. If `readiness < 45` **or** `ACWR > 1.5` **or** `TSB < −30` → **rest or 30–40 min Z1** (whichever the template has fewer of).
2. Else if `monotony > 2.0` → prefer a session type not done in the last 7 days.
3. Else pick the next unfulfilled template slot for today's preferred sport; if a quality session was done
   yesterday, pick easy/long instead.
4. Scale duration so that `estimated_load` (§10.6) fills the remaining `weekly_target_load` across remaining sessions.
5. Output: structured workout (§10.5) + one-line reason string (deterministic, template-based).
*Clarified 2026-09-29 (phase 6, proposed):*
- Inputs for day `D`: `readiness[D]`, `TSB[D]` (already pre-day), `ACWR[D−1]` and `monotony[D−1]` (the last
  complete day). A null input never triggers its condition (the reason says the value is missing).
- Rule 1: **rest** if the week's rest quota is not yet used (days `Mon … D−1` without any activity < the
  template's rest days), else **40 min Z1** (recovery, today's sport). This replaces "whichever the template
  has fewer of", which had no deterministic reading.
- Rule 2: "session type" = the §10.7 workout key. If today's workout key was done (a `done` planned workout)
  in `D−7 … D−1`, take the first key of this week's remaining non-rest slots (order long, q1, q2, easy) that
  was not; if none, keep today's.
- Rule 3: today's role gives the slot (rest → rest). If today is `easy` and an earlier `q1`/`q2`/`long` slot
  of this week is unfulfilled (no `done` planned workout of that slot), take the earliest of them. A quality
  (`q1`/`q2`) choice becomes `easy` if yesterday had a done quality workout or an activity with IF ≥ 0.85
  (`if_pace` for rTSS, else `if_hr`).
- Rule 4: `remaining = weekly_target − Σ load_total[Mon … D−1]` (≥ 0); session weights long 2.0, q1/q2
  1.25, easy 1.0 over today's and the remaining non-rest days of the week; today's target =
  `remaining · w_today / Σ w`. Each workout has one integer parameter (minutes in 5-min steps, or reps) with
  the §10.7 range; the value whose `estimated_load` is closest to the target wins (ties → the smaller).
- Rest output = a planned workout with `sport = "rest"`, no steps, `estimated_load = 0`. Reasons are Slovak,
  built from fixed templates with the triggering values.

### 10.5 Workout structure (JSON, sport-agnostic)
```json
{"sport":"run","name":"Threshold 5x6","steps":[
 {"type":"warmup","duration_s":900,"target":{"kind":"hr_zone","zone":2}},
 {"type":"repeat","count":5,"steps":[
   {"type":"work","duration_s":360,"target":{"kind":"hr_zone","zone":4}},
   {"type":"recovery","duration_s":120,"target":{"kind":"hr_zone","zone":1}}]},
 {"type":"cooldown","duration_s":600,"target":{"kind":"hr_zone","zone":1}}]}
```
Targets: `hr_zone` (1–5), `pace_range` (run, from §1 pace zones), `open`. Bike uses `hr_zone` only.

### 10.6 Estimated load of a planned workout
`estimated_load = Σ_steps duration_s · IF_zone² / 36`, with `IF_zone` = zone midpoint IF from §2.1 table
(Z1 0.50, Z2 0.65, Z3 0.83, Z4 0.98, Z5 1.10).
*Clarified 2026-09-29 (phase 6, proposed):* repeats multiply their inner steps. Z1 0.50 is kept as written
(not the table midpoint 0.43: recovery work sits in the upper half of Z1, r ≈ 0.61). `open` steps carry an
`effort_zone` (1–5) used only here; `pace_range` steps carry their pace zone and use the same zone IF.

### 10.7 Workout library (initial)
Run: easy (Z2 40–75 min), long (Z2 90–150 min, last 20 min Z3 in Build), tempo (20–40 min Z4 continuous),
threshold intervals (4–6 × 6 min Z4 / 2 min Z1), VO2 intervals (5–8 × 3 min Z5 / 2 min Z1), hill repeats
(8–12 × 60–90 s hard / jog down), progression run (Z2 → Z3 → Z4 last 10 min), strides (easy + 6 × 20 s fast).
Bike: recovery spin (Z1 45 min), endurance (Z2 90–180 min), sweet spot (2–3 × 20 min high-Z3 / 5 min Z1),
over-unders (3 × 12 min alternating 2 min Z4 / 1 min Z3), long ride (Z2 with 3 × 10 min Z3).
*Clarified 2026-09-29 (phase 6, proposed):* quality sessions have warm-up 15 min Z2 and cool-down 10 min Z1.
Parameter (range, step):
- run: easy total 40–75 min; long total 90–150 (Peak 75–110; Build: last 20 min Z3); tempo main 20–40 min Z4;
  threshold 4–6 reps; VO2 5–8 reps; hill repeats 8–12 × (75 s open effort 5 / 120 s Z1); progression total
  45–75 min (last 20 min: 10 Z3 + 10 Z4); strides: easy 30–50 min Z2 + 6 × (20 s open effort 5 / 60 s Z1);
  race-pace 3–5 × (8 min at race zone / 3 min Z1), short race-pace 2–3 reps; short intervals 8–12 ×
  (1 min Z5 / 1 min Z1); recovery 40 min Z1 (rule 1, fixed).
- bike: recovery spin 45 min Z1 (fixed); endurance 90–180 min; long ride 120–240 min (Z2, 3 × 10 min Z3
  spread over the middle); sweet spot 2–3 × (20 min Z3 / 5 min Z1); over-unders 3 × [4 × (2 min Z4 / 1 min
  Z3)] with 5 min Z1 between sets (fixed); bike VO2 5–8 × (3 min Z5 / 3 min Z1); race-pace / short race-pace /
  short intervals as run; spin-ups: endurance 60–90 min + 6 × (20 s open effort 5 / 60 s Z1); rule-1
  recovery 40 min Z1.
- Race zone from the goal: run ≤ 5 km Z5, ≤ 21.1 km Z4, longer Z3; bike Z4 if `target_time_s ≤ 2 h`, else
  Z3; no goal → Z4.

### 10.8 Push to Garmin
Map §10.5 to the `garminconnect` workout builder (running/cycling workouts with HR-zone targets), upload,
then schedule on the planned date. Store `garmin_workout_id`. Re-pushing an already pushed plan updates
rather than duplicates. Zone numbers refer to the user's Garmin Connect HR zones, which must equal §1.
