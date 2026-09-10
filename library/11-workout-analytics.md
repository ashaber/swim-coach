# Workout analytics (cardiac drift, splits, pauses, SWOLF)

**Thresholds in this file are provisional, pending a full research pass** —
this is a Slice-1 stub written to unblock `engine/swim_coach/analytics.py`,
not a fully sourced topic file. See `00-conventions.md` for the tagging
scheme and `reference_list.md` for citations.

Grounds `analytics.py`'s `SPLIT_EVEN_BAND_PCT`, `GAP_THRESHOLD_S`,
`CARDIAC_DRIFT_FLAG_PCT`, `STATIONARY_SPEED_MPS`, and `STATIONARY_MIN_S`
constants, and documents the SWOLF stroke-efficiency proxy used by
`swolf_trend`.

## Cardiac drift / aerobic decoupling

**[ADAPTED: general-endurance] Confidence: low.** Aerobic decoupling — a
rising heart-rate-to-pace (or heart-rate-to-speed) ratio from the first to
the second half of a steady-state effort — is a widely used
endurance-coaching heuristic for aerobic durability and fueling adequacy: a
large decoupling suggests either the effort outran current aerobic fitness
or fueling/hydration broke down mid-session, not a swim-specific finding.
No peer-reviewed citation for this specific technique currently exists in
`reference_list.md` (unlike the taper and HRV-guided-load claims elsewhere
in this library, which do cite primary sources) — this is included as a
practitioner heuristic pending a real citation search, not evidence-backed
research. `CARDIAC_DRIFT_FLAG_PCT = 5.0` (a >5% rise in the HR:pace ratio
between halves) is an engineering default, not a validated cutoff; only a
*rise* is flagged — negative decoupling (second half more efficient) is
reported but not treated as a concern. **Test:**
on a matched-effort steady swim/kayak session, check whether a flagged >5%
drift day coincides with the athlete's own reports of under-fueling, heat,
or fatigue more often than non-flagged days — if it doesn't, the threshold
needs recalibrating from the athlete's own data rather than trusted as-is.

## SWOLF as a stroke-efficiency proxy

**Coach judgment:** SWOLF (stroke count + seconds per length — literally a
scoring formula, not a physiological measurement) is a widely used
practical pool-swimming efficiency proxy: lower is better, and a rising
SWOLF across a session at a stable pace signals stroke-mechanics
degradation (fatigue) rather than a pacing choice. It is not itself a
cited research finding — no `Author (Year)` source in `reference_list.md`
validates SWOLF against an independent efficiency measure — so
`swolf_trend`'s first-quartile-vs-last-quartile comparison is offered as a
descriptive fatigue signal, not a proven one. **Requiring >= 8 active
lengths before computing a trend** is a coach-judgment floor against
noisy small-sample quartiles, not a statistically derived minimum.

**Coach judgment:** active lengths longer than 3× the median active-length
duration (`SWOLF_OUTLIER_DURATION_X = 3.0`) are excluded from the trend as
device auto-length-detection misses — the real pool fixture in this repo
contains a 1136s/5-stroke "length" among ~25-40s lengths that would
otherwise dominate the last-quartile mean (see
`tests/unit/fixtures/fit/README.md`). The 3× multiple is an engineering
default, not a derived value.

## Pause-gap threshold and even-split band

**Coach judgment:** `GAP_THRESHOLD_S = 30.0` (a `record`-frame timestamp
gap longer than this is treated as a real pause, not GPS/sensor smart-
recording variance) and `SPLIT_EVEN_BAND_PCT = 2.0` (a first-half/second-half
pace difference within ±2% is labeled "even" rather than "negative"/
"positive") are both engineering defaults chosen for this project's device
data (Garmin smart-recording intervals observed up to ~19s on a real kayak
export; see `tests/unit/fixtures/fit/README.md`), not values derived from a
cited study. Both are cheap to revisit once more real `.fit` exports exist
across more device/firmware combinations.

## Stationary-speed pause detection

**Coach judgment:** `STATIONARY_SPEED_MPS = 0.5` and `STATIONARY_MIN_S = 30.0`
(a sustained speed-series span below 0.5 m/s for at least 30s becomes a
`WorkoutPause(source="stationary")`) are engineering defaults chosen against
this athlete's real device data, not values derived from a cited study. They
exist because this athlete's devices record with **auto-pause off**: each
`.fit` file carries exactly one timer start/stop event pair spanning the
whole activity, and `record` frames keep sampling straight through a
physical stop -- so the existing timer-event and `GAP_THRESHOLD_S`
record-gap detectors find zero pauses even when the athlete clearly stopped
(a start-corral wait, a bottle/feed stop). Only the speed series exposes
those real stops.

Calibration evidence: a real 2026-06-13 MTB race (10 laps) has five known
per-lap bottle stops, each 32-88s long by the athlete's own account; at the
30s floor, the detector catches all five (plus the pre-race start-corral
wait) with no other spurious spans on that file. A 15s floor was tried
first and rejected: on a second real MTB ride (2026-07-09, more technical
singletrack), it produced ~92 spurious sub-15s spans -- almost certainly
slow technical riding misread as stops, not real ones -- so 30s is the
floor this project uses.

**Scoping caution, not a general-purpose stop detector:** the detector is
only run for FIT sessions whose raw `sport` is `"cycling"` (see
`parse_files._is_cycling_sport`), not for every sport a `.fit` file might
carry. This was a real finding, not a hypothetical: running the same 0.5
m/s / 30s thresholds against a real ~5-hour kayak trip (also auto-pause-off,
also carrying a full speed series) produced roughly 50 false-positive
"stops" -- that trip's average speed (11,494m / 18,196s = 0.63 m/s) sits
right at the threshold, so ordinary slow-paddling variance between strokes
trips it constantly. Cycling has a "fast baseline speed, rare real stop"
structure this threshold can exploit; a naturally slow-cruising sport
(kayaking, and presumably walking) does not, and applying the same flat
threshold there would mislead the athlete/coach about how much of a session
was actually a stop. Extending this detector to another sport family needs
its own calibration pass against real data for that sport first, not a
blind widening of `_is_cycling_sport`.

**GPS-drift caution for open water (untested, flagged explicitly):** this
detector has never been run against a real open-water swim `.fit` file with
a known feed/rest stop. A feeding or resting open-water swimmer drifts with
current/waves rather than staying put, so their GPS-derived speed may not
reach anywhere near 0 m/s even while genuinely stationary -- the opposite
failure mode from the kayak case above (a real stop that the detector
under-reports, or misses, rather than a non-stop it over-reports). If this
detector is ever extended to open-water swims, `STATIONARY_SPEED_MPS` likely
needs raising, and that revision should wait for a real feed-stop swim
`.fit` file to calibrate against, exactly as the cycling thresholds above
were calibrated against real MTB data rather than guessed. Speculative
caution, not a validated finding -- flagged here specifically so it isn't
silently forgotten before that file exists.

## Walk/run FIT sport-label sanity check

**[ADAPTED: general-endurance] Confidence: medium.** `Hreljac A. (1995)`
(`reference_list.md`, "Cross-discipline endurance") and the broader
gait-transition-speed biomechanics literature it sits within establish that
humans switch from walking to running at a preferred transition speed (PTS)
corresponding to a Froude number of approximately 0.5 -- for typical adult
leg lengths this works out to roughly 2.0-2.2 m/s. This is a well-supported
range with a commonly-cited center, not a single universally-agreed cutoff:
individual PTS shifts with leg length, fitness, terrain, and grade.
`RUN_WALK_TRANSITION_MPS = 2.1` (`parse_files.py`) is a practitioner's pick
of one representative value inside that range, not a value this athlete's
own device data has calibrated.

This exists because Garmin's raw FIT `session.sport` field is a *device
activity-profile* label, not a ground-truth measurement -- a watch left on
its "Run" profile during an actual walk still reports `sport="running"`,
and `_sport_detail` previously passed that string straight through as
display text. When the raw sport is "running" (or contains "run") and the
session's average speed (`total_distance / total_timer_time`, the same
session-level fields `parse_fit` already reads for pace) is below
`RUN_WALK_TRANSITION_MPS`, `_sport_detail` relabels the display text to
"walking" instead. This changes only the free-text `sport_detail` label --
the resolved `Sport` enum bucket (`cross_train`) is unchanged either way, so
load/volume math is unaffected. Same pattern as `_is_cycling_sport`'s
stationary-pause gating above: derive truth from the session's own numbers
rather than trusting the device's self-reported label. **Test:** if a real
slow-walk `.fit` file recorded under a Run profile ever shows a sustained
average speed *above* this threshold (e.g. brisk race-walking), the
practitioner cutoff needs revisiting against that real data, same as the
stationary-pause thresholds above were revised against real MTB rides.

## Per-sample grade for terrain-confound detection

**Coach judgment:** `parse_files.GRADE_SMOOTHING_M = 30.0` — per-sample road
grade (rise/run) is measured over a forward 30 m distance window from
altitude and distance deltas. 30 m smooths barometric-altimeter jitter
without blurring a real climb/descent. Engineering default chosen against
this athlete's real MTB `.fit` exports (grades land in a plausible ~-18% to
+23% band on `real_mtb_race.fit`), clamped to +/-45%, emitted only for FIT
sessions whose raw sport is `"cycling"` (the `_is_cycling_sport` gate).

## Deterministic activity-stream interval analyzer

Grounds `engine/swim_coach/interval_analysis.py` (detect sustained efforts
in a ride, assess each vs a target, flag terrain confounds; no LLM tokens
spent on the stream). Most thresholds are engineering defaults / coach
judgment chosen against this athlete's real cycling `.fit` data; two carry
an ADAPTED (cycling) tag with its own Confidence/Test, below.

### Detection thresholds (coach judgment)

**Coach judgment:** `EFFORT_MIN_S = 120.0` (shortest span counted as a
deliberate effort — structured cycling work bouts are minutes, not seconds;
cf. `24-cycling-periodization-intervals.md`), `EFFORT_MERGE_GAP_S = 25.0`
(a shorter sub-threshold dip — a corner, a freewheel over a crest — doesn't
end the effort), `EFFORT_DYNAMIC_FRAC = 0.62` (with no supplied target the
threshold sits this far from the ride's 40th- toward its 85th-percentile
working power), `COASTING_FLOOR_W = 20.0` (at/below this the rider is
freewheeling), `TARGET_GATE_FRAC = 0.80` (with a target supplied, "in an
effort" means >= 80% of it — 195W against a 239W target is still an
attempt). All engineering defaults tuned so the scan ignores steady
endurance riding but catches a threshold interval; none is a cited value.

### Interval quality vs. target

**[ADAPTED: cycling] Confidence: medium.** `IN_BAND_FRAC = 0.05` — percent
of an interval's samples within +/-5% of target power is the compliance
metric the power-meter-training literature favours, explicitly *not*
normalized power (a fatigue-cost estimate that outdoor coasting/surging
inflates, misleading a time-in-zone read). The +/-5% band is the standard
practitioner target-range width in the Allen/Coggan lineage (`Allen H.,
Coggan A. (2010)` / `(2019)`, *Training and Racing with a Power Meter*;
`reference_list.md`, "Cycling training (native)"), corroborated by
convergent secondary sources (TrainingPeaks, TrainerRoad, CTS). **Test:**
if this athlete's "on target" intervals routinely coincide with her saying
the session felt too easy/hard, revisit the band against her own RPE/HR.

**[ADAPTED: cycling] Confidence: medium.** `FADE_FLAG_PCT = 10.0` —
first-third-vs-last-third mean power drop within one effort. `Barsumyan A.,
Soost C., Burchard R. (2025)`, "Enhanced durability predicts success in
amateur road cycling: evidence of power output declines" — *Frontiers in
Sports and Active Living* (`reference_list.md`, "Cycling training
(native)") — found ~6.5% first-to-last power decline over a fatigued 20-min
TT in *successful* amateur road cyclists vs ~12.5% in *less successful*
ones (n=14; no 5-min or HR-response difference), so a within-interval fade
past ~10% is a real durability/pacing signal, not noise. One small
trained-amateur study of a fixed fatiguing protocol, not this athlete's
field intervals — hence medium. **Test:** if her flagged >10%-fade
intervals don't track hard days / poor fuelling / heat / late-ride efforts
more than her non-flagged ones, recalibrate from her own data.

### Terrain-confound detection (coach judgment)

**Coach judgment:** the confound this analyzer exists for — "a threshold
interval up a steepening dirt road reads like a power fade" — is flagged
from three engineering defaults: `GRADE_DROP_FLAG = 0.03` (a first-third-
to-last-third mean-grade decrease >= 3 percentage points is "materially
more downhill"), `HR_HELD_BAND_BPM = 2.0` (HR drift within +/-2 bpm is
"held"), `HR_BACKOFF_DROP_BPM = 5.0` (HR falling > 5 bpm alongside a power
fade reads as easing off). Rule: fade + grade dropped + HR held/rising ->
"likely terrain"; fade + HR dropped hard -> "backed off"; fade >= 10% + HR
held/rising + grade NOT dropped -> "genuine fade". No cited physiological
threshold — read-the-data-not-the-label heuristics, same spirit as
`_is_cycling_sport`; verified to behave sensibly on `real_mtb_race.fit`.
**Test:** if the flag fires on efforts she calls genuine fades (or misses
ones she calls terrain), tighten `GRADE_DROP_FLAG` / the HR bands against
her annotated rides.

### Tightened aerobic decoupling (supplements `cardiac_drift_pct`, never replaces it)

**Coach judgment:** `TIGHTENED_DECOUPLING_MIN_WORKING_FRAC = 0.5`. The
standard first-half-EF vs second-half-EF calc (`analytics.cardiac_drift`)
is documented by TrainingPeaks (`reference_list.md`, "Practical / non-
journal resources") as **invalid on "variable, stop-start or all-out"
rides** — exactly why this athlete's dirt-road interval rides confound the
unfiltered `cardiac_drift_pct`. `tightened_decoupling` runs the same
formula on genuinely *working* samples only (power > `COASTING_FLOOR_W`;
speed > 0.5 m/s absent power), returning `(None, reason)` when < 50% of
moving time was working. Both numbers are reported; the tightened one is
labelled with the fraction of moving time it covers. The 50% floor is a
coach-judgment cutoff. **Test:** the tightened and unfiltered numbers
should roughly agree on her steady Z2 rides and diverge (tightened =
trustworthy, or `None`) on stop-start interval rides; if the tightened one
is still noisy on steady rides, the working-sample filter needs work.

### Match-to-prescription (coach judgment)

**Coach judgment:** `DURATION_TOLERANCE_FRAC = 0.25` — a detected effort
within +/-25% of a prescribed rep's duration is "the same rep" when
aligning efforts to a recovered `WorkoutStructure`'s interval steps in
order. With no recoverable structure (the common case — `planned_session_
id` is never populated in practice, and a TrainerRoad-originated workout
carries none), efforts are reported raw against a caller-supplied target.
Engineering default.

## What's still a gap

- No citation exists yet for cardiac-drift/aerobic-decoupling thresholds in
  swimming or adjacent endurance sports specifically — a real gap, not a
  resolved one.
- Negative/positive/even split labeling (`split_analysis`) restates
  `Saavedra J.M., Einarsson, et al. (2018)`'s open-water negative-split
  finding (`reference_list.md`, "Swimming — CSS, pacing & performance")
  operationally as a per-workout label, but the ±2% even-split band itself
  is not from that paper — it's a coach-judgment bucketing choice layered
  on top of a real finding.
- SWOLF-vs-independent-efficiency-measure validation, and a swim-specific
  (rather than practitioner-heuristic) cardiac-drift threshold, are both
  candidates for a future full research pass on this file.
