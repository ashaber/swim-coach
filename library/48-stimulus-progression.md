# Stimulus model and progression rules (the engine's dose-by-dose progression read)

See `00-conventions.md` for tags. Grounds the constants in `engine/swim_coach/stimulus.py` and `engine/swim_coach/progression.py`.

**Sport scope: all sports with a profile (bike and swim today).** **UNREVIEWED**, pending human review. **No study compares interval levers as progression steps.** Section 10 cites the research that bounds a session (ceilings); every other rule and number, the lever order, step sizes, entry shapes and the threshold-change rule included, is a `Coach judgment:` decision written down so it can be checked against athlete data, not a finding.

## 1. What a stimulus kind is (`Coach judgment:`)

Each work step has a zone rank 1 to 5. A zone is meaningful at 10% of ranked work (`KIND_MIN_SHARE`). Two or more of tempo, threshold and vo2 at 30% each (`MIXED_MIN_SHARE`) make `mixed`; otherwise the highest meaningful zone sets the kind (Z3 tempo, Z4 threshold, Z5 vo2), and all-Z1/Z2 work is `endurance`. Endurance becomes `long` at or above `max(per-sport floor, 0.85 x recent longest)` (`LONG_FRACTION_OF_RECENT_LONGEST`; floors `BIKE_LONG_MIN_WORK_S` 5,400 s and `SWIM_LONG_MIN_WORK_M` 4,000 m). Races, openers and warm-ups are not stimuli. The dose of a quality kind is its Z3+ work; the dose of endurance and long is all work.

**Test:** over 8 weeks of the athlete's real sessions, list each session's computed kind beside the coach's title; if more than 1 in 5 disagree, adjust the shares or floors.

## 2. Estimated dose when only a zone is known (`Coach judgment:`)

With no structure, a Z3+ session is assumed to be half work (`ESTIMATED_QUALITY_WORK_FRACTION` 0.5); a Z1/Z2 session is all work. Estimated doses never drive a progress verdict.

**Test:** for sessions that have both a structure and a zone, compare the structured work to half the session; adopt the median ratio if it differs by more than 0.15.

## 3. Progression verdicts (`Coach judgment:`)

The most recent usable session of a kind decides. `progress`: at least 90% of planned work done (`COMPLETION_PROGRESS_MIN_PCT`) or unplanned, reps in band at or above 70% (the existing `INTENSITY_MATCH_MIN_IN_BAND_PCT`), fade at or under 5% (`FADE_FREE_PCT`), RPE under 9 (`RPE_MARGINAL_MIN`), recovery not strained; next dose is 1.0 to 1.10 x (`PROGRESSION_STEP_FRACTION` 0.10). `repeat`: completed but marginal on any one; next dose 0.95 to 1.0 x (`REPEAT_TOLERANCE_FRACTION` 0.05). `reduce`: completion under 75% (`COMPLETION_REDUCE_BELOW_PCT`), in band under 50% (`IN_BAND_REDUCE_BELOW_PCT`), or two marginal sessions in a row (`CONSECUTIVE_REPEATS_TO_REDUCE`); one step down. `rebuild`: over 28 days since the kind (`PROGRESSION_STALE_DAYS`); one step below the last clean dose. `insufficient_data`: no usable record, or only estimated doses.

**Test:** replay 12 weeks of the athlete's history; after each `progress` verdict, the next same-kind session should be completed at least 80% of the time. If it is not, shrink the step.

## 4. Fallback when no shape is derivable: rep length before total volume (`Coach judgment:`)

When a `progress` verdict follows a longest rep below the kind's target (`BIKE_REP_TARGET_S`: tempo 1,200 s, threshold 600 s, vo2 240 s; `SWIM_REP_TARGET_M`: tempo 400 m, threshold 200 m, vo2 100 m), the dose read holds total work and raises the longest-rep cap by one step, up to that target. It applies only when the reference session has no regular shape (section 9); with a shape, candidates replace it.

**Test:** compare in-band share and fade for sessions that raised rep length first against sessions that raised total work first, same athlete, over a season.

## 5. Recovery response (`Coach judgment:`)

Wellness rows on the 1 to 2 days after a session (`RECOVERY_WINDOW_DAYS`) are read with the existing baseline-deviation function. The status is `strained` when HRV is at or under -5%, resting HR at or over +5% (`RECOVERY_DEVIATION_CONCERNING_PCT`, the same 5% the web app uses), or the composite is at or under the existing red threshold of 2.0. It is `recovered` when a signal exists and none breach, and `unknown` when none exist; missing data is never "recovered". `unknown` does not block `progress` but lowers confidence one level. Informational only: `17-wellness-load-integration.md` finds no validated deviation threshold.

**Test:** across logged sessions, `strained` should precede a poorer next same-kind session more often than `recovered` does; if the two rates match, drop recovery from the verdict.

## 6. Unplanned work and the rest of the week (`Coach judgment:`)

Unplanned work is any workout with no matched session. For each remaining planned session the review flags: `duplicate_stimulus` when unplanned work already delivered the same kind at 75% or more of its dose (`DUPLICATE_STIMULUS_FRACTION`); `hard_too_soon` when a tempo, threshold, vo2 or mixed session falls under 48 hours after an unplanned hard or long workout (`HARD_RECOVERY_WINDOW_H`); `load_over_target` when done plus remaining planned load exceeds the planned week by more than the 8% weekly ramp rail (`WEEKLY_VOLUME_RAMP_CAP`). Nothing is rescheduled.

**Test:** after weeks with flagged impacts, check whether the athlete skipped, shortened or failed the flagged session more often than unflagged ones.

## 7. Guardrail findings (`Coach judgment:`)

`check_week` runs the progression read against an authored week. When the reference and planned sessions both have a shape (section 9) in the same zone, findings come from the levers, else from the dose (no new number beyond `PROGRESSION_STEP_FRACTION`). Lever findings: `progression-multi-lever-*` (medium) when more than one lever progresses at once; `progression-oversized-step-*` (medium, high after reduce or rebuild) when one lever moves more than one step; `progression-over-ceiling-*` (medium) past the zone's ceiling, quoting its source; `progression-threshold-rebase-*` (medium) when the threshold rose and the plan continues from the old reference; `progression-retest-*` (low) at the ceiling after clean sessions with no test planned and no taper; `progression-zone-jump-*` (low) when the planned zone has no history and the easier zone's last session is below its promotion point (silent without easier-zone history). Evidence quotes both rungs. Dose findings: `progression-jump-*` when planned work exceeds the top of the suggested range by more than one further step (high after reduce or rebuild, else medium); `progression-rep-length-*` (low) when the longest planned rep exceeds the suggested cap by more than one step. Both paths keep `progression-ignores-*` (medium; reduce or rebuild, planned work at or above the last reference) and `progression-stalled-*` (low; second session in a row not above the reference; silent in taper and race weeks). `unplanned-*` carries section 6 through. Weak data never fires the first rules.

**Test:** over a season, weeks that drew a finding and kept the plan should show more skipped, shortened or failed sessions of that kind than weeks that drew none; if not, loosen that rule. For zone-jump, a first session in a harder zone after a flagged jump should fail more often than after an unflagged one.

## 8. Calibration against real execution data (`Coach judgment:`)

**Substituted work:** completion is only meaningful when the delivered kind equals the planned kind (endurance and long are one family); otherwise the record keeps the delivered kind, carries `planned_kind` and `substituted`, has no completion or in-band, and the planned kind counts as missed. **Matched prescription:** when the analyzer located the planned reps, the executed kind is the planned kind, and an in-band share of 0 with no resolved target is unknown, not zero. **Endurance and long** are measured on the whole aerobic time (moving time; total swum distance), never on detected efforts. **Quality dose** is the Z3+ work; total work, rep count and longest rep follow that filter. **Estimated execution** gives no completion, grade `unknown`, never a reference. Completion over 150% (`COMPLETION_SANITY_MAX_PCT`) adds a "check the match" reason. **Minimum quality dose** (`BIKE_MIN_DOSE_S`: tempo 600 s, threshold 480 s, vo2 180 s; `SWIM_MIN_DOSE_M`: 400, 300, 200 m; mixed uses the smallest): below it the workout reads as endurance on its whole extent. **Practical rounding** of suggested doses: bike work 30 s and reps 15 s (`BIKE_WORK_ROUND_S`, `BIKE_REP_ROUND_S`), swim 50 m and 25 m (`SWIM_WORK_ROUND_M`, `SWIM_REP_ROUND_M`). **Shaped sessions only:** a quality kind's progression is read from sessions that are not substituted and have a derivable shape (section 9); with none, from planned unsubstituted sessions, then any unsubstituted one (the dose fallback). Other work, such as a club ride or a substituted session, is listed as "also delivered", never read. **Load scale:** done work is priced on the planned scale (RPE times minutes, or the matched target); with any workout unpriced, `load_over_target` is suppressed.

**Test:** replay the last 12 weeks and list the records created, the substituted ones and the endurance fallbacks; if more than 1 in 5 quality records fall under a floor, or suggested ranges are not within one unit of what the athlete did next, adjust the floors and units. Also list the sessions left out as "also delivered"; if the athlete's next session repeats one of them rather than the read reference, widen what counts as shaped.

## 9. The lever model (`Coach judgment:`)

A quality session in Z3, Z4 or Z5 is a shape: sets, reps per set, rep size (seconds or metres), rest and set rest; the work in the zone follows. A shape is derived from a planned structure or executed record only when its reps are regular (same size within 10%, rests in at most two groups); an irregular ride gives none, never a guess. Dominant block: contiguous work steps are merged, reps are clustered by zone and size (within 10%), and the cluster carrying at least 75% of the work (`DOMINANT_MIN_SHARE`) is the shape if contiguous and big enough (two reps, or one at least the zone's entry rep); other reps, such as primers, are ignored and noted. Progression moves exactly one lever one step from the last cleanly completed session, so a failure points at one lever: rep size lengthens, rest shortens, reps and sets rise, and consolidate merges broken reps into fewer longer ones (3 x 3 min becomes 2 x 5 min, at most +15% work). Steps are grids, not percentages: bike tempo reps 8, 10, 12, 15, 20 min; threshold reps 3 to 20 min; VO2 on-time 15, 20, 30, 40 s, reps 6, 8, 10, 13, up to 3 sets; swim by distance. Lever order in `templates/progression_levers.yaml` is only a default preference. With no history the entry shape applies: bike 2x8 min/4 min tempo, 2x(3x3 min/1 min)/5 min threshold, 6x15 s/15 s VO2; swim 4x200 m/20 s, 8x100 m/15 s, 8x50 m/20 s. The athlete's own patterns are reached by single steps from these; no target list is named. At the ceiling the policy promotes (tempo to the threshold entry) or asks for a threshold retest.

**Test:** validated when sessions one step up are completed in band at least as often as repeats; if they fail more often, shrink that lever's step or reorder the levers. Check the 75% share on sessions with a primer: if the derived shape differs from the one the athlete calls the session, change the share.

## 10. Ceilings: per-session work in the zone

`[ADAPTED: cycling]` Seiler, Jøranson, Olesen, Hetlelid (2013), "Adaptations to aerobic interval training: interactive effects of exercise intensity and total work duration", *Scand J Med Sci Sports*: in trained cyclists 4 x 8 min at maximal tolerable effort (32 min) gave larger gains than 4 x 4 or 4 x 16 min, so time at the right effort matters. Confidence: low-medium (secondary summary). Test: sessions up to the ceiling are done in band as often as shorter ones.

`[ADAPTED: cycling]` Baron et al. (2003), "Maximal lactate steady state does not correspond to a complete physiological steady state", *Int J Sports Med*: eight trained cyclists rode 30 min at maximal lactate steady state; lactate held while heart rate and breathing drifted. About 30 min is tolerated. Confidence: low-medium (eight men). Test: reps in the last third of a 30 min session fade by no more than the free band.

`Coach judgment:` the bike threshold ceiling is 40 min (2 x 20 min), the top of the athlete's own pattern and above the 30 to 32 min tested; reaching it prompts a test, not more volume.

`[ADAPTED: cycling]` Rønnestad, Hansen, Vegge, Tønnessen, Slettaløkken (2015), "Short intervals induce superior training adaptations compared with long intervals in cyclists, an effort-matched approach", *Scand J Med Sci Sports*, and Rønnestad, Hansen, Nygaard, Lundby (2020), same journal: 3 sets of 13 x 30 s on / 15 s off (19.5 min on-time, 3 min between sets) beat effort-matched 4 x 5 min, so short on/off is a strong VO2 protocol. Bike VO2 ceilings: 19.5 min on-time for short reps; 20 min for long reps (4 x 4 to 4 x 5 min, Seiler 2013). Confidence: low-medium (small groups, 3 to 10 weeks). Test: sessions near 19.5 min on-time are completed in band at least 70% of the time.

`[ADAPTED: cycling]` Sylta et al. (2016), "The effect of different high-intensity periodization models on endurance adaptations", *Med Sci Sports Exerc*: at matched total load, raising, lowering or mixing interval duration across 12 weeks made no difference in 63 cyclists, so lever order is preference, not evidence. Confidence: medium. Test: athletes progressed by different lever orders show similar in-band rates at matched load.

`[EVIDENCE: swim]` Dekerle et al. (2010), "Critical swimming speed and critical stroke rate in intermittent aerobic exercise", *J Sci Med Sport* : 10 x 400 m at critical swimming speed with 40 s recovery kept blood lactate stable in nine competitive male swimmers (abstract level). Swim threshold ceiling: 4,000 m. Test: sessions up to 4,000 m are done in band as often as shorter ones.

`Coach judgment:` all other ceilings (bike tempo 60 min, swim tempo 3,200 m, swim VO2 1,200 m) and `max_rep_size`; no tested protocol was found for them.

## 11. A threshold change restarts the climb (`Coach judgment:`)

Each ledger record carries the sport's threshold on its date (FTP for the bike, CSS pace for swimming, where a faster pace is higher), from dated threshold records; with none on or before the date the athlete's current value stands in, marked unknown. When the threshold has risen by at least `rebase.min_change_pct` since the reference session (bike 2%, swim 1.5%), the reference steps down `steps_per_pct` x the percent rise levers (bike 0.5, swim 1.0; rounded, at least 1), never below the zone's entry shape, and that restart shape is the first candidate. A fall is noted and does not restart upward; an unknown earlier threshold does not restart. Near the top of a zone the next step is a test, not more volume.

**Test:** validated when sessions at the restart level are completed in band more often than the pre-rise shape would be; if the old shape is still completed in band, halve `steps_per_pct`.

## Research needed

1. Interval progression rates: no study compares levers (rep length, rest, reps, sets) as progression steps, or gives how much work or rep length trained adults add per exposure for tempo, threshold and vo2 work (bike and swim separately).
2. Recovery-response thresholds: validated HRV and resting-HR deviations after one hard session, by sport and age band.
3. The hard-recovery window after threshold and vo2 work in masters athletes.
4. Whether swim-set pace zones from CSS classify rep intensity as reliably as power zones classify bike efforts.
