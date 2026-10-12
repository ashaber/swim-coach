# Race week: the sharpener, the openers, and the cyclocross hard start

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations. Extends `24-cycling-periodization-intervals.md` ("Openers /
pre-race primers") and `03-periodization.md` (taper block, +8%/week ramp
rail) for a priority bike race week. Bike-scoped.

**UNREVIEWED**, pending human review.

## The sharpener (about 3-4 days before a priority race)

The sharpener is the LAST real stimulus before the race: short, intense,
small volume. A reasonable shape is about 60 minutes at IF ~0.65-0.75 and
TSS ~45-60, with a few race-pace or threshold efforts inside it.

`[ADAPTED: general-endurance]` Tapers work by cutting volume while holding
intensity: Mujika & Padilla (2003) describe maintaining training intensity
while reducing volume substantially, and the Bosquet et al. (2007)
meta-analysis found the best-performing tapers cut volume by about 41-60%
with intensity and frequency held constant. The sharpener is that principle
applied to one session: a small dose of real intensity so the legs are not
only rested but still sharp. Both sources are multi-sport, not
cyclist-specific, and neither prescribes a single sharpener session; the
IF/TSS figures above are practitioner shapes, not study results.
**Confidence: medium.** **Test:** if the athlete arrives at the start line
flat after a sharpener of this size (or reports the sharpener itself left
them tired), shrink it or move it earlier next race and compare.

## The openers (the day before the race)

The openers are a different thing and do not replace the sharpener: very low
load, about 20-40 minutes, a few short builds up to race pace, just to wake
the legs. One does not substitute for the other; a race week normally has
both, a few days apart.

**`Coach judgment:`** The sharpener supplies stimulus, the openers supply
readiness. Skipping the sharpener because "openers are coming" leaves the
last real intensity a week or more out; making the openers hard enough to be
a stimulus spends freshness the day before the race.

## The cyclocross "hard start"

**`Coach judgment:`** Rehearse the lap-1 launch-then-settle as ONE
continuous effort: a roughly 10-20 s all-out launch from a slow roll that
goes straight into about 2-4 minutes at threshold/race pace without easing
off in between. That is what the first lap of a race asks for. Do NOT
program it as separate standing starts followed by separate VO2 intervals;
that rehearses two unrelated things and never the transition from the launch
into sustainable race effort.

## The +8%/week ramp rail in a race week

**`Coach judgment:`** The +8%/week minutes ramp rail in
`03-periodization.md` is a build-phase rule. In a race week the race days
and their warm-ups inflate weekly minutes even though the training stress is
low, so the rail can fire on a week that is not a real ramp. The coach
should still surface the finding, but treat it as low-signal for a race week
and say so plainly rather than rewriting a sound taper to satisfy it. A
load-based (TSS) bike rail that ignores warm-up and race minutes is a future
idea, not built; `plan_check` behaviour is unchanged.

## Writing starts and technical-course reps

**`Coach judgment:`** Write each start as a TIMED step equal to the intended
hold, so the watch counts down and beeps at the end, with a label naming the
shape ("15 s launch -> hold race pace to beep"; "12 s all-out, brake for
corner, ~10 s out" is read as 22 s). Follow it with an `open` recovery
(`duration_kind: "open"`, "recover until lap key"; it exports to a Garmin as a
lap-button step) so the athlete starts the next rep when ready, not on a clock
that ignores a remount. The watch cannot randomize the gap, so tell the athlete
to press lap, then launch on their own count of 1-10 s. If he wants an in-ride
read, a Lap Max Power data field on the head unit gives one.

Starts are skill practice, and the comparison is a post-ride review, not an
in-ride instruction: nobody can see a 10% drop mid-ride. Judge each start
against the BEST start so far (the first one or two are often ridden at about
90% on purpose). A start more than 10% under that is "weak". One weak start
followed by a recovery is almost always execution (missed clip, slow launch);
only consecutive weak starts, or a steady decline into the last start, read as
fatigue. Also read held seconds against the intended hold: not holding power
is not fading. On a tight technical course (corner sequence, barrier or
run-up, remount) continuous power is impossible, so judge those reps by heart
rate against LTHR, not average power against a watts target.

## How the analyzer reads these sessions

All of these numbers are `Coach judgment:` fitted to a handful of real
rides, not cited values; each carries a `Test:` line in its code comment.

- **Double-burst starts.** A start ridden as a launch, a brake for a
  corner, then a second effort out of it carries `burst2_*` and the dip
  between them (`BURST2_MAX_GAP_S = 20`, `BURST2_DIP_FRAC_OF_PEAK = 0.5`,
  `BURST2_MIN_FRAC_OF_MAIN_PEAK = 0.6`). The weak-start read scores a start on the
  better of its two bursts, and `held_s` counts seconds at or above 1.5 x FTP
  across both (the corner dip excluded). Sets of reps under `START_MIN_PRESCRIBED_S = 10`
  s (5 s builds) are openers: a peak read, no weak-start read.
- **Weak starts.** `WEAK_START_DROP_PCT = 10` under the best start so far. Weak
  and isolated (the next start recovers, or the last start after a fine one) is
  an `execution_miss`; consecutive weak starts, or the last start ending a
  steady decline, is `fatigue`. Launch clues on a weak start: time-to-peak at
  least `LAUNCH_SLOW_MARGIN_S = 2` s over the set median, or launch cadence
  (first 3 s) under `LAUNCH_LOW_CADENCE_FRAC = 0.8` of the median.
- **Technical reps (HR-scored).** A work rep of at least
  `TECH_MIN_REP_S = 120` s is technical when its step label names technical
  terrain, or when at least `TECH_LOW_POWER_TIME_PCT = 20` % of it is spent
  under half of FTP (half that, `TECH_LABEL_ASSISTED_TIME_PCT = 10`, when only
  the plan text says technical). Such a rep reports average power, NP, average
  HR, % of LTHR and seconds at or above 90% of LTHR, and reads "effort
  held" at `TECH_HR_HELD_PCT_LTHR = 85`; it gets no under-target or fade verdict.
  A rep with under `STREAM_MIN_COVERAGE = 0.8` of its seconds recorded is
  reported from the lap summary and not scored.
- **Lap shape.** With no plan, or a plan the analyzer cannot time-align (lap-key
  steps), at least `SHAPE_MIN_REPEATS = 3` alternating work/recovery laps with
  matching durations (`SHAPE_DURATION_TOL_*`) are treated as the prescription
  with open targets (`detection_source = "lap_shape"`). Work laps of at least
  60 s must average `SHAPE_WORK_VS_REST_POWER = 1.25` x their recovery; shorter
  ones must show a 1.5 x FTP burst nearby.
- **Race start.** On a race (`race=True`), the first sample at or above
  `RACE_BURST_MIN_FRAC_FTP = 1.5` x FTP that is followed by 5 min averaging at
  least `RACE_FOLLOW_MIN_FRAC_FTP = 0.6` x FTP is the start. Reported: peak, best
  5/15/30 s, burst length, seconds until the trailing 30 s mean sits within
  `RACE_SETTLE_BAND_FRAC = 10` % of the following 5 min, and the first 5 min NP
  against the race's NP from the start onward. No decoupling read is emitted
  for a race, nor for an interval or starts session.
