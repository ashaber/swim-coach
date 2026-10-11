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

**`Coach judgment:`** Starts and technical reps are timed by hand on the
day, so write them that way. End each recovery after a start or a
technical rep with a lap-key step (`duration_kind: "open"`, "recover until
lap key"); on a Garmin it exports as a lap-button step, so the athlete
rides the recovery they need rather than a clock that ignores a
remount. A start itself is a fixed short step: tell the athlete to press
lap, then launch on their own count of 1-10 s, because the watch cannot
randomize the gap and a fixed countdown teaches the body to anticipate it.
Judge a set of starts against the BEST start so far, not the first: the
first one or two are often ridden at about 90% on purpose and built from, and
the stop rule (stop once a start's best 5 s is more than 10% under the best
so far) must not fire on a deliberate build. On a tight technical course
(corner sequence, barrier or run-up, remount) continuous power is
impossible, so judge those reps by heart rate against LTHR, not by average
power against a watts target.

## How the analyzer reads these sessions

All of these numbers are `Coach judgment:` fitted to a handful of real
rides, not cited values; each carries a `Test:` line in its code comment.

- **Double-burst starts.** A start ridden as a launch, a brake for a
  corner, then a second effort out of it carries `burst2_*` and the dip
  between them (`BURST2_MAX_GAP_S = 20`, `BURST2_DIP_FRAC_OF_PEAK = 0.5`,
  `BURST2_MIN_FRAC_OF_MAIN_PEAK = 0.6`). The stop rule scores a start on the
  better of its two bursts. Sets of reps under `START_MIN_PRESCRIBED_S = 10`
  s (5 s builds) are openers: a peak read, no stop rule.
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
