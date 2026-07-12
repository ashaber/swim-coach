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
