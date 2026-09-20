# GPS lap-boundary detection (bike)

See `00-conventions.md` for the tagging scheme and `reference_list.md` for
full citations. Grounds `engine/swim_coach/gps_laps.py`'s
`GPS_LAP_PROXIMITY_M`, `GPS_LAP_MIN_AWAY_M`, `GPS_LAP_MIN_DURATION_S`, and
`MIN_USABLE_GPS_SAMPLES` constants, plus the `efficiency_mps_per_w` metric.

**Sport scope: `bike`.** Same scoping intent as `23-cycling-training.md`
through `31-multi-race-season-periodization.md` -- a real, closed-loop
repeated course (a criterium, a cyclocross lap course, an MTB race lap) is
the shape this module targets, and nothing here is presented to a
swim-only athlete. `context.py` routing wiring for this file is not done
in this pass (same "deferred to a future build stage" status those files
already document for themselves) -- this build ships a pure function, not
a wired `/coach` topic.

## The real, grounded problem

A real cyclocross race (Andrew, 2026-09-19) recorded exactly one native
FIT `lap` frame for the whole 46.2-minute activity: auto-lap is
profile-specific on his device and wasn't enabled for the profile used
that day, and the one manual lap-key press he made mid-race didn't
register as a separate FIT lap either. A cyclocross course is a closed
loop ridden repeatedly, so the real per-lap boundaries are still
recoverable after the fact -- from GPS position, not from device
telemetry that was never recorded.

**No existing citation applies to lap-boundary detection from a GPS
track.** This is an engineering/geometry problem (accurately locating
when a moving GPS receiver has returned near a fixed point, filtering
receiver noise), not a physiological or training-methodology claim, so
nothing here carries an EVIDENCE or ADAPTED evidence tag -- every
threshold below is **Coach judgment**, stated as such, same posture as
`11-workout-analytics.md`'s pause-gap/stationary-pause thresholds.

## Reference point and geodesic distance

**Coach judgment:** the detector's reference point is simply the first
valid GPS sample of the activity -- the start. For a looped course, start
and finish are normally the same physical point, so a real per-lap
boundary is "when the athlete's position returns near where they started."
No separate "explicit finish line" parameter was added for v1: the real
motivating case (and every closed-loop race format this targets) already
has start == finish, and adding a second reference point with no real
caller needing it would be speculative complexity for its own sake.

**Coach judgment:** distance between GPS points is computed via the
haversine great-circle formula, never a flat lat/lng-degree Euclidean
approximation. A degree of longitude shrinks with `cos(latitude)`, so a
naive Euclidean distance over raw lat/lng values is measurably wrong even
at a single race-course's scale (hundreds of meters to a few kilometers) --
this isn't a "close enough" rounding choice, it's simply the correct
formula for the problem, at negligible extra computational cost.

## Proximity, arm-distance, and minimum-duration thresholds

**Coach judgment:** `GPS_LAP_PROXIMITY_M = 20.0` -- how close a sample must
land (real geodesic distance) to the reference point to count as a
lap-boundary crossing. Consumer GPS chipsets (the exact device class this
project already ingests `.fit` from) typically hold roughly 3-5m
horizontal accuracy under open sky, degrading to commonly-cited ranges of
10-15m or more under tree cover, tight technical turns, or multipath near
structures -- all real conditions a race course's start/finish area can
have. 20m gives margin for that realistic degradation without being so
wide that it risks conflating genuinely different nearby points on a tight
course. No published source pins this exact number for GPS lap-boundary
detection specifically (this isn't a physiology claim with a literature
to search); it's an engineering default sized to well-known consumer-GPS
accuracy ranges, not a value validated against real detection outcomes yet.

**Coach judgment:** `GPS_LAP_MIN_AWAY_M = 50.0` -- 2.5x the proximity
threshold. Before a later "near the reference point" sample is eligible to
confirm a new lap boundary, the athlete must have moved at least this far
away from the reference point since the last confirmed boundary. Without
this, GPS jitter sitting right at the start line at the very beginning of
a recording could immediately register a bogus duplicate "lap" a few
seconds in -- the exact false-positive/duplicate-at-the-start failure mode
the brief for this build called out explicitly.

**Coach judgment:** `GPS_LAP_MIN_DURATION_S = 120.0` -- the minimum
elapsed time between two CONFIRMED boundary crossings. A real cyclocross
lap runs several minutes, not seconds; race organizers conventionally size
a course/lap-count combination so a lead rider's lap takes roughly
2.5-4 minutes. 120s sits comfortably below the shortest realistic real
lap while remaining far above the kind of near-line noise a naive
proximity-only check could otherwise double- or triple-count (several GPS
fixes in a row within the proximity radius as the athlete slows through a
finish chute or start corral). This is the primary noise-rejection floor
against spurious multi-lap detections in quick succession that the brief
asked for.

**Interaction the module's own tests pin explicitly**: because
`GPS_LAP_MIN_DURATION_S` is measured from the last CONFIRMED boundary (not
the last rejected candidate), a course with real per-lap durations shorter
than 120s does not simply drop those laps -- it silently MERGES consecutive
real laps until enough elapsed time accumulates to confirm a boundary. A
caller working with a course whose real laps are known to run under ~2
minutes should pass an explicit, smaller `min_lap_duration_s`, not rely on
the default.

**Coach judgment:** `MIN_USABLE_GPS_SAMPLES = 2` -- fewer than two real
(non-`None`) lat/lng samples can't establish "moved away from the start and
came back," so detection isn't attempted at all (`[]`) rather than
guessing.

## The efficiency metric: `efficiency_mps_per_w`

**Coach judgment**, a new metric designed for this build -- no existing
citation exists to find for a per-lap speed-vs-Normalized-Power ratio; the
formula and its stated limitation are both original reasoning, not sourced
from a paper. Andrew's own framing (verbatim, from the build brief): "if
the NP for a lap is lower for the same average speed, it was more
efficient... won't tell us why but usually would expect to see efficiency
improve as I learn the course, unless the course breaks down significantly
(mud)." The metric is `avg_speed_mps / normalized_power_w` for the lap --
higher is more efficient (more speed per watt of fatigue-weighted effort),
matching the "higher = better" convention of this project's other
efficiency-shaped numbers rather than a lower-is-better cost ratio.

**Real, stated limitation** (see `gps_laps.GpsLapMetrics.efficiency_mps_per_w`'s
own docstring for the identical text, kept in sync): this metric cannot
distinguish "genuinely more efficient" (same or higher speed for less
power) from "riding easier, or fading" (power AND speed both drop
together, which also raises this same ratio, because the denominator can
fall faster than the numerator). A rising efficiency number across a
race's laps is only a genuine improvement signal when read alongside that
lap's own average speed holding steady or rising too -- a rising ratio
with falling speed is fade, not improvement, and this field alone does not
distinguish the two. This is a real, load-bearing caveat, not a
formality: it is the single biggest way this metric could be
misinterpreted by a coach or athlete glancing at just one number.

## Provenance: distinct from `models.WorkoutLap`

`models.WorkoutLap` is explicitly documented as "one device lap/interval,
from a FIT `lap` frame" -- real device-recorded telemetry. A GPS-detected
lap boundary is a fundamentally different provenance: computed after the
fact from the raw position stream, never present on the device's own
recording, and potentially wrong in ways a device-native lap frame simply
isn't (GPS drift, a missed crossing, a false trigger near a course
feature that happens to sit within the proximity radius of the start).
`gps_laps.GpsLap` is kept as its own separate dataclass -- not merged into
`WorkoutLap`'s field/list, not silently presented with the same
confidence as device telemetry -- the same "distinct from `WorkoutSet`"
precedent `WorkoutLap`'s own docstring already sets for a different
provenance boundary.
