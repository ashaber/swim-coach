# Stimulus model and progression rules (the engine's dose-by-dose progression read)

See `00-conventions.md` for tags. Grounds the constants in `engine/swim_coach/stimulus.py` and `engine/swim_coach/progression.py`.

**Sport scope: all sports with a profile (bike and swim today).** **UNREVIEWED**, pending human review. **The library holds no interval-progression evidence.** Every rule and number below is a `Coach judgment:` decision, written down so it can be checked against athlete data, not a finding. No external source is cited.

## 1. What a stimulus kind is (`Coach judgment:`)

Each work step has a zone rank 1 to 5. A zone is meaningful at 10% of ranked work (`KIND_MIN_SHARE`). Two or more of tempo, threshold and vo2 at 30% each (`MIXED_MIN_SHARE`) make `mixed`; otherwise the highest meaningful zone sets the kind (Z3 tempo, Z4 threshold, Z5 vo2), and all-Z1/Z2 work is `endurance`. Endurance becomes `long` at or above `max(per-sport floor, 0.85 x recent longest)` (`LONG_FRACTION_OF_RECENT_LONGEST`; floors `BIKE_LONG_MIN_WORK_S` 5,400 s and `SWIM_LONG_MIN_WORK_M` 4,000 m). Races, openers and warm-ups are not stimuli. The dose of a quality kind is its Z3+ work; the dose of endurance and long is all work.

**Test:** over 8 weeks of the athlete's real sessions, list each session's computed kind beside the coach's title; if more than 1 in 5 disagree, adjust the shares or floors.

## 2. Estimated dose when only a zone is known (`Coach judgment:`)

With no structure, a Z3+ session is assumed to be half work (`ESTIMATED_QUALITY_WORK_FRACTION` 0.5); a Z1/Z2 session is all work. Estimated doses never drive a progress verdict.

**Test:** for sessions that have both a structure and a zone, compare the structured work to half the session; adopt the median ratio if it differs by more than 0.15.

## 3. Progression verdicts (`Coach judgment:`)

The most recent usable session of a kind decides. `progress`: at least 90% of planned work done (`COMPLETION_PROGRESS_MIN_PCT`) or unplanned, reps in band at or above 70% (the existing `INTENSITY_MATCH_MIN_IN_BAND_PCT`), fade at or under 5% (`FADE_FREE_PCT`), RPE under 9 (`RPE_MARGINAL_MIN`), recovery not strained; next dose is 1.0 to 1.10 x (`PROGRESSION_STEP_FRACTION` 0.10). `repeat`: completed but marginal on any one; next dose 0.95 to 1.0 x (`REPEAT_TOLERANCE_FRACTION` 0.05). `reduce`: completion under 75% (`COMPLETION_REDUCE_BELOW_PCT`), in band under 50% (`IN_BAND_REDUCE_BELOW_PCT`), or two marginal sessions in a row (`CONSECUTIVE_REPEATS_TO_REDUCE`); one step down. `rebuild`: over 28 days since the kind (`PROGRESSION_STALE_DAYS`); one step below the last clean dose. `insufficient_data`: no usable record, or only estimated doses.

**Test:** replay 12 weeks of the athlete's history; after each `progress` verdict, the next same-kind session should be completed at least 80% of the time. If it is not, shrink the step.

## 4. Rep length before total volume (`Coach judgment:`)

When a `progress` verdict follows a longest rep below the kind's target (`BIKE_REP_TARGET_S`: tempo 1,200 s, threshold 600 s, vo2 240 s; `SWIM_REP_TARGET_M`: tempo 400 m, threshold 200 m, vo2 100 m), the read holds total work and raises the longest-rep cap by one step, up to that target.

**Test:** compare in-band share and fade for sessions that raised rep length first against sessions that raised total work first, same athlete, over a season.

## 5. Recovery response (`Coach judgment:`)

Wellness rows on the 1 to 2 days after a session (`RECOVERY_WINDOW_DAYS`) are read with the existing baseline-deviation function. The status is `strained` when HRV is at or under -5%, resting HR at or over +5% (`RECOVERY_DEVIATION_CONCERNING_PCT`, the same 5% the web app uses), or the composite is at or under the existing red threshold of 2.0. It is `recovered` when a signal exists and none breach, and `unknown` when none exist; missing data is never "recovered". `unknown` does not block `progress` but lowers confidence one level. This is informational: `17-wellness-load-integration.md` finds no validated deviation threshold.

**Test:** across logged sessions, `strained` should precede a poorer next same-kind session more often than `recovered` does; if the two rates match, drop recovery from the verdict.

## 6. Unplanned work and the rest of the week (`Coach judgment:`)

Unplanned work is any workout with no matched session. For each remaining planned session the review flags: `duplicate_stimulus` when unplanned work already delivered the same kind at 75% or more of its dose (`DUPLICATE_STIMULUS_FRACTION`); `hard_too_soon` when a tempo, threshold, vo2 or mixed session falls under 48 hours after an unplanned hard or long workout (`HARD_RECOVERY_WINDOW_H`); `load_over_target` when done plus remaining planned load exceeds the planned week by more than the 8% weekly ramp rail (`WEEKLY_VOLUME_RAMP_CAP`). Nothing is rescheduled.

**Test:** after weeks with flagged impacts, check whether the athlete skipped, shortened or failed the flagged session more often than unflagged ones.

## 7. Guardrail findings (`Coach judgment:`)

`check_week` can run the progression read against an authored week. All thresholds reuse `PROGRESSION_STEP_FRACTION`; no new number. `progression-jump-*` fires when planned work exceeds the top of the suggested range by more than one further step (high when the verdict is reduce or rebuild, else medium). `progression-ignores-*` (medium) fires when the verdict is reduce or rebuild and planned work is at or above the last reference dose. `progression-stalled-*` (low) fires when the verdict is progress and planned work is at or under the reference for the second session of that kind in a row; it is silent in taper and race weeks. `progression-rep-length-*` (low) fires when the longest planned rep exceeds the suggested cap by more than one step. `unplanned-*` carries the section 6 impacts through. Low-confidence, insufficient-data and estimated-dose cases never fire the first four.

**Test:** over a season, check whether weeks that drew a jump or ignores finding and kept the plan had more skipped, shortened or failed sessions of that kind than weeks that drew none. If not, widen the allowance.

## 8. Calibration against real execution data (`Coach judgment:`)

Rules added after the first real-data runs. **Substituted work:** completion is only meaningful when the delivered kind equals the planned kind (endurance and long count as one family); otherwise the record keeps the delivered kind, carries `planned_kind` and `substituted`, has no completion or in-band, and counts the planned kind as missed. **Matched prescription:** when the analyzer located the planned reps, the executed kind is the planned kind, and an in-band share of 0 with no resolved target zone or band is unknown, not zero. **Endurance and long** are measured on the ride's whole aerobic time (moving time, else duration; total swum distance), never on detected efforts. **Quality dose** is the Z3+ work, and total work, rep count and longest rep follow that one filter. **Estimated execution** gives no completion, grade `unknown`, never a reference dose. Completion over 150% (`COMPLETION_SANITY_MAX_PCT`) on structured data adds a "check the match" reason. Races, openers and warm-ups (session or workout) make no record. **Minimum quality dose per kind** (`BIKE_MIN_DOSE_S`: tempo 600 s, threshold 480 s, vo2 180 s; `SWIM_MIN_DOSE_M`: tempo 400 m, threshold 300 m, vo2 200 m; mixed uses the smallest): below it the workout is read as endurance on its whole extent, so one workout yields one record. **Practical rounding** of suggested doses: bike work 30 s and reps 15 s (`BIKE_WORK_ROUND_S`, `BIKE_REP_ROUND_S`), swim work 50 m and reps 25 m (`SWIM_WORK_ROUND_M`, `SWIM_REP_ROUND_M`); a rep cap is always at least one unit above the current longest rep. **Load scale:** done work in the week review is priced on the planned scale (RPE times minutes, or the matched session's target), because `session_load` is a different scale for power and heart-rate tiers; with any done workout unpriced, `load_over_target` is suppressed.

**Test:** replay the athlete's last 12 weeks and list the records created, the substituted ones and the endurance fallbacks; if more than 1 in 5 quality records fall under a floor, or suggested ranges are not within one unit of what the athlete actually did next, adjust the floors and units.

## Research needed

1. Interval progression rates: how much work or rep length trained adults add per exposure for tempo, threshold and vo2 work (bike and swim separately).
2. Recovery-response thresholds: validated HRV and resting-HR deviations after one hard session, by sport and age band.
3. The hard-recovery window after threshold and vo2 work in masters athletes.
4. Whether swim-set pace zones from CSS classify rep intensity as reliably as power zones classify bike efforts.
