# Workout analytics (cardiac drift, splits, pauses, SWOLF)

**Thresholds in this file are provisional, pending a full research pass** —
this is a Slice-1 stub written to unblock `engine/swim_coach/analytics.py`,
not a fully sourced topic file. See `00-conventions.md` for the tagging
scheme and `reference_list.md` for citations.

Grounds `analytics.py`'s `SPLIT_EVEN_BAND_PCT`, `GAP_THRESHOLD_S`, and
`CARDIAC_DRIFT_FLAG_PCT` constants, and documents the SWOLF stroke-efficiency
proxy used by `swolf_trend`.

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
