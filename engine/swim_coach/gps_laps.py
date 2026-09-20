"""GPS-derived lap-boundary detection and per-lap efficiency metrics.

Motivating case (real, not hypothetical): a real cyclocross race (Andrew,
2026-09-19, `workouts.id = '678a693e-052d-4202-bd7e-3acfc39acb5a'`, athlete
slug `andrew`, 49.4min/14423m -- NOT the `a4391e6d-...` workout from the
same day, which was that morning's warmup, corrected after an earlier
mix-up) whose device recorded exactly TWO native FIT `lap` frames for the
entire race -- auto-lap was profile-specific and wasn't enabled for this
activity's profile; the athlete's one manual lap-key press (at the end of
his real lap 1) produced lap frame 0, and everything after (laps 2 through
5) collapsed into a single lap frame 1. A cyclocross course is a closed
loop ridden repeatedly, so the real per-lap boundaries are recoverable
from GPS position alone even when the device's own lap telemetry is
useless.

Real validation note on detected lap 1's boundary (confirmed by Andrew,
not a guess): it lands slightly before his own manual lap-1 press --
explained by the race's real start position, which was slightly off the
main course and passed through the start/finish line almost immediately,
rather than a GPS-noise/staging-area artifact as originally guessed.
Laps 2-5, each bounded by two genuine start/finish line crossings, aren't
affected by this start-position quirk.

Pure functions over the columnar series dict `parse_files._build_series`
produces (`t_s` plus `lat`/`lng`/`power_w`/`speed_mps`/... channels, same
shape `analytics.normalized_power_w` already consumes) -- no I/O, no
network, no LLM. Nothing in this module is wired into `analytics.
compute_analytics`/`models.Workout` persistence yet; it is a standalone
detection + metrics pass a caller (CLI command, or a future analytics
field) can run over an already-loaded `series` dict.

**Explicitly out of scope** (do not extend this module to do it): full
course-segmentation / geospatial terrain analysis of what happens WITHIN a
lap (which corners or features cost time). This module only finds lap
BOUNDARIES (start/finish crossings) and, once a lap is bounded, the single
efficiency comparison described below -- nothing about course shape.

## Algorithm (`detect_gps_laps`)

1. **Reference point**: the first sample with a valid `lat`/`lng` pair --
   i.e. the start of the activity. For a looped course, start and finish
   are normally the same point, so this needs no separate "finish line"
   parameter for v1 (the real use case this was built for -- see the module
   docstring above -- has exactly one such point).
2. **Single linear pass** over the series, tracking real geodesic distance
   (`haversine_distance_m`, never a flat lat/lng-degree approximation --
   wrong at any real course scale) from the reference point:
   - A crossing only becomes eligible to fire once the athlete has moved at
     least `GPS_LAP_MIN_AWAY_M` away from the reference point since the
     last confirmed crossing (`armed`) -- otherwise GPS jitter sitting
     right at the start line would immediately register a bogus duplicate
     lap a few seconds into the recording.
   - Once armed, a sample within `GPS_LAP_PROXIMITY_M` of the reference
     point is a candidate crossing. It's only confirmed (and un-arms the
     detector again) if at least `GPS_LAP_MIN_DURATION_S` has elapsed since
     the previous confirmed crossing -- the noise-rejection floor against
     several near-line samples in a row firing as separate "laps".
   - A `None` lat/lng sample (a dropped GPS fix -- the parser already
     allows per-channel gaps) is simply skipped; it neither arms nor
     un-arms the detector and never itself counts as a crossing.
3. **Output**: `GpsLap(start_idx, end_idx)` pairs -- INDEX offsets into the
   series arrays (not raw `(start_t_s, end_t_s)` floats), matching
   `interval_analysis.DetectedEffort`'s own convention, chosen for the same
   reason that module gives: a caller slicing `power_w`/`hr`/etc. for a
   lap's per-lap metrics wants direct array slicing, not a re-search
   through `t_s` for the nearest sample. `start_s`/`end_s` are carried
   alongside as a convenience (and `duration_s` derives from them), same as
   `DetectedEffort`. The crossing sample itself is the shared boundary --
   included as both the previous lap's `end_idx` and the next lap's
   `start_idx` -- a single ~1Hz sample, immaterial to a lap's aggregate
   metrics.
4. Only FULLY CLOSED laps (a confirmed crossing at both ends) are returned.
   The final stretch after the last confirmed crossing to the end of the
   recording -- e.g. the real finish sprint, which may cross a chip-timing
   line a few meters from where the GPS track happened to start, or simply
   the tail of a DNF/early stop -- is deliberately NOT reported as a
   trailing partial lap: there's no confirmed end boundary for it, and
   guessing one would silently fabricate a lap. Same posture for the
   opposite edge case: if the athlete never returns near the reference
   point at all (a point-to-point route, or a recording stopped mid-lap),
   this returns `[]` -- zero laps, not one "whole activity" lap; a caller
   that wants a whole-activity fallback already has the plain series dict
   for that.

Never raises. Returns `[]` (not `None`) for every "nothing usable" case:
`series` is falsy/`None`, no `lat`/`lng` channel at all, every sample in
those channels is `None`, fewer than 2 usable points, or the athlete never
produces a second confirmed crossing. `[]` is used rather than `None`
(unlike, say, `analytics.cardiac_drift`) to match this module's own
sibling functions here (`analyze_gps_laps` chains directly off it) and
`analytics.stationary_pauses`'s "no usable channel -> `[]`" convention for
a function that returns a list of things by nature -- a caller can always
iterate the result without a `None` check either way.

## Per-lap metrics (`lap_metrics`)

For each detected lap: Normalized Power (`analytics.normalized_power_w`,
reused directly -- not reimplemented -- over the lap's own sliced series),
average speed (mean of `speed_mps` in range; falls back to
distance-covered/duration via `dist_m` when `speed_mps` is absent or
entirely `None` for the slice), and `efficiency_mps_per_w` -- see that
field's own docstring below for the metric's definition and, explicitly,
its real limitation.

See `library/32-gps-lap-detection.md` for the full reasoning behind every
threshold below.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass

from swim_coach import analytics

# --- constants (library/32-gps-lap-detection.md) --------------------------------------

EARTH_RADIUS_M = 6_371_000.0
# Mean Earth radius, the standard constant used in the haversine great-
# circle-distance formula. Not a "coach judgment" figure -- a geometric
# constant.

GPS_LAP_PROXIMITY_M = 20.0
# Coach judgment: how close (real geodesic distance) a sample must land to
# the reference point to count as a lap-boundary crossing. Consumer GPS
# chipsets (the class of device this project already ingests .fit from)
# typically hold ~3-5m horizontal accuracy under open sky but commonly
# degrade to 10-15m+ under tree cover, tight turns, or multipath near
# structures -- real conditions a start/finish area can have. 20m gives
# margin for that degradation without being so wide it risks conflating two
# genuinely different nearby points on a technical course. No swim/cycling-
# specific published source pins this exact number for GPS lap-boundary
# detection -- it's an engineering default sized to real consumer-GPS
# accuracy ranges, not a validated cutoff. library/32-gps-lap-detection.md.

GPS_LAP_MIN_AWAY_M = 50.0
# Coach judgment: 2.5x GPS_LAP_PROXIMITY_M. The athlete must have
# unambiguously left the reference point's proximity zone before a later
# return is eligible to confirm a new crossing -- otherwise GPS jitter
# sitting right at the boundary's edge at the very start of the recording
# could immediately fire a bogus duplicate lap a few seconds in.
# library/32-gps-lap-detection.md.

GPS_LAP_MIN_DURATION_S = 120.0
# Coach judgment: the minimum elapsed time between two confirmed crossings.
# A real cyclocross lap is minutes, not seconds -- courses are
# conventionally designed/lap-counted so a lead rider's lap takes roughly
# 2.5-4 minutes. 120s sits safely below the shortest realistic real lap
# while staying far above the kind of near-line noise (several samples in
# a row within GPS_LAP_PROXIMITY_M as the athlete slows through a finish
# chute or start corral) that a naive proximity-only check could otherwise
# double-count as separate laps. library/32-gps-lap-detection.md.

MIN_USABLE_GPS_SAMPLES = 2
# Coach judgment: fewer than 2 real lat/lng samples can't establish
# "moved away and came back" at all -- returned as [] rather than attempted.
# library/32-gps-lap-detection.md.


# --- geodesic distance -----------------------------------------------------------------


def haversine_distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Real great-circle distance (meters) between two lat/lng points, via
    the standard haversine formula. Deliberately NOT a flat lat/lng-degree
    Euclidean approximation -- that's wrong at any real course scale (a
    degree of longitude shrinks with `cos(latitude)`, and even a small
    course spans enough distance that the error compounds sample to
    sample)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return EARTH_RADIUS_M * c


# --- detection result type --------------------------------------------------------------


@dataclass(frozen=True)
class GpsLap:
    """One GPS-DETECTED lap boundary -- a DIFFERENT provenance than
    `models.WorkoutLap` (device-native FIT `lap` frame telemetry). This is
    a derived, computed lap: located after the fact from the raw GPS
    stream, never present on the device's own recording. Deliberately kept
    out of `WorkoutLap`'s own field/list (its docstring's own "Distinct
    from `WorkoutSet`" precedent applies here too) -- a plain, separate
    dataclass, not persisted, not wired into `models.Workout` for v1.

    `start_idx`/`end_idx` are inclusive index offsets into the series
    arrays this lap was detected from (see module docstring, point 3, for
    why index offsets rather than raw times); `start_s`/`end_s` are the
    matching `t_s` values, carried alongside as a convenience.
    """

    n: int
    start_idx: int
    end_idx: int  # inclusive
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def _first_valid_gps_index(lat: list, lng: list) -> int | None:
    for i, (la, lo) in enumerate(zip(lat, lng)):
        if la is not None and lo is not None:
            return i
    return None


def detect_gps_laps(
    series: dict | None,
    *,
    proximity_m: float = GPS_LAP_PROXIMITY_M,
    min_away_m: float = GPS_LAP_MIN_AWAY_M,
    min_lap_duration_s: float = GPS_LAP_MIN_DURATION_S,
) -> list[GpsLap]:
    """Detect real per-course-lap boundaries from GPS position on a looped
    course. See the module docstring for the full algorithm and edge-case
    posture. Never raises -- see module docstring for every `[]` case.
    """
    if not series:
        return []
    t_s = series.get("t_s")
    lat = series.get("lat")
    lng = series.get("lng")
    if not t_s or not lat or not lng:
        return []

    ref_idx = _first_valid_gps_index(lat, lng)
    if ref_idx is None:
        return []

    n = len(t_s)
    if n - ref_idx < MIN_USABLE_GPS_SAMPLES:
        return []

    ref_lat, ref_lng = lat[ref_idx], lng[ref_idx]

    boundaries: list[int] = [ref_idx]
    armed = False
    last_boundary_t = t_s[ref_idx]

    for i in range(ref_idx + 1, n):
        la, lo = lat[i], lng[i]
        if la is None or lo is None:
            continue
        dist = haversine_distance_m(ref_lat, ref_lng, la, lo)
        if not armed:
            if dist >= min_away_m:
                armed = True
            continue
        if dist <= proximity_m and t_s[i] - last_boundary_t >= min_lap_duration_s:
            boundaries.append(i)
            last_boundary_t = t_s[i]
            armed = False

    laps = [
        GpsLap(
            n=k + 1,
            start_idx=boundaries[k],
            end_idx=boundaries[k + 1],
            start_s=t_s[boundaries[k]],
            end_s=t_s[boundaries[k + 1]],
        )
        for k in range(len(boundaries) - 1)
    ]
    return laps


# --- per-lap metrics ----------------------------------------------------------------


# Coach judgment: freewheeling reads as literal 0W on a power meter --
# this small allowance is only for sensor noise/quantization around true
# zero, not a research-backed number.
COASTING_POWER_THRESHOLD_W = 5.0


@dataclass(frozen=True)
class GpsLapMetrics:
    """Per-detected-lap numbers -- several DELIBERATELY DIFFERENT lenses on
    the same lap, not one combined score. Andrew's own framing (2026-09-20,
    reviewing a set of metrics suggestions and picking these three as
    worth building alongside `efficiency_mps_per_w`): each metric shows a
    slightly different aspect, and the COACH interprets them together --
    e.g. "speed increased, work dropped, VI improved" reads as a genuine,
    multi-signal efficiency gain, where any ONE of these fields moving on
    its own is much easier to misread (see `efficiency_mps_per_w`'s own
    fade-vs-genuine-improvement confound below, which every field here
    shares some version of). Deliberately NOT collapsed into a single
    "efficiency score" -- Andrew's own words: "we may redefine efficiency
    with experience" -- exposing the real components and letting
    interpretation evolve is preferred over locking in an unvalidated
    combining formula now.

    See `lap_metrics` and each field's own docstring for definitions and
    (where one exists) a real, named limitation."""

    lap_n: int
    start_s: float
    end_s: float
    duration_s: float
    normalized_power_w: float | None
    avg_speed_mps: float | None
    efficiency_mps_per_w: float | None
    """Average speed per watt of Normalized Power for this lap:
    `avg_speed_mps / normalized_power_w`. Higher = more efficient -- more
    speed produced per watt of (fatigue-weighted) effort, matching Andrew's
    own framing verbatim: "if the NP for a lap is lower for the same
    average speed, it was more efficient... won't tell us why but usually
    would expect to see efficiency improve as I learn the course, unless
    the course breaks down significantly (mud)."

    **Coach judgment** (a new metric for this build, not a cited formula --
    no existing citation exists to find for a per-lap speed/NP ratio;
    designed here, not sourced): `speed / NP` rather than `NP / speed` so
    that "better" reads as "higher", matching this project's other
    efficiency-shaped numbers (e.g. `interval_analysis`'s efficiency-factor
    convention of HR or power divided INTO a favorable direction). No
    other design choice (e.g. NP / speed, or a normalized 0-100 score) is
    more "correct" -- this ratio's only job is to sort laps consistently
    within one activity for one athlete on one course.

    **Real, named limitation -- stated plainly, not glossed over**: this
    metric CANNOT distinguish "genuinely more efficient" (same or higher
    speed for less power -- learning the course's lines, better positioning
    in a group, smoother technique) from "riding easier, or fading" (lower
    power AND lower speed together, which also produces a HIGHER
    `efficiency_mps_per_w` under this formula, because the denominator fell
    faster than -- or as fast as -- the numerator can be read as "cheap").
    A rising efficiency number across a race's laps is only a genuine
    efficiency-gain signal when read ALONGSIDE the lap's own `avg_speed_mps`
    holding roughly steady or rising too; a rising ratio with FALLING speed
    is fade, not improvement, and this field alone does not flag that
    difference -- a caller comparing laps must look at both fields
    together, this metric was never designed to be read in isolation.
    library/32-gps-lap-detection.md.
    """
    total_work_kj: float | None
    """Total mechanical work for this lap, in kilojoules:
    `average_power_w * duration_s / 1000` -- the standard convention every
    cycling head unit/platform uses for "kJ" (average power IS total
    work / total time by definition, so this is exact, not an
    approximation -- no per-sample integration/gap-handling edge cases to
    get wrong, unlike Normalized Power's own rolling-window algorithm).

    Deliberately NOT power/distance or power/speed-normalized -- this is
    the ABSOLUTE energy cost lens: correcting sloppy lines, bobbling a
    barrier, or overshooting a corner and re-accelerating all show up here
    as MORE total kJ for a lap that covers essentially the same distance,
    even when the resulting lap TIME doesn't change enough to look
    alarming on its own. Coach judgment (Andrew's own framing,
    2026-09-20): a rising kJ trend across otherwise-similar laps is worth
    a coach's attention on its own; read alongside `avg_speed_mps` and
    `variability_index` for why, not in isolation.
    """
    variability_index: float | None
    """Normalized Power / average power for this lap -- the standard,
    already-widely-used measure of how SPIKY the lap's effort was (a
    smooth, steady lap has VI close to 1.0; frequent hard accelerations
    out of corners or barriers push it higher). Distinct from
    `efficiency_mps_per_w`/`total_work_kj` -- this says nothing about how
    much work was done or how fast the lap was, only how EVENLY the power
    was delivered. `None` under the same conditions `normalized_power_w`/
    `average_power_w` themselves are (no usable power channel).

    Coach judgment on interpretation (Andrew's own framing): a rising VI
    across otherwise-similar laps, especially paired with falling
    `avg_speed_mps`, points at lost momentum through technical
    sections -- more forced re-accelerations, not more raw fitness demand
    -- rather than at fatigue alone (fatigue typically shows first as
    falling `normalized_power_w`/`total_work_kj`, not as rising spikiness
    of an unchanged power ceiling). Not independently verified against a
    cyclocross-specific citation -- VI itself is a standard, established
    metric; this specific interpretive claim about what a RISING CX-lap VI
    means is reasoned from that standard definition, not sourced from a
    study of cyclocross specifically (none exists -- see this codebase's
    2026-09-19 race-analysis research pass).
    """
    coasting_s: float | None
    """Total time (seconds) this lap spent at or below
    `COASTING_POWER_THRESHOLD_W` -- not pedaling meaningfully, whether
    freewheeling through a corner or fully dismounted/stopped. `None` when
    the lap's slice has no usable power/time data at all (distinct from a
    real `0.0`, which means real samples existed and none of them were at
    or below the threshold).

    Coach judgment (Andrew's own framing): falling coasting time paired
    with a SLOWER lap is a real signal on its own -- carrying less
    momentum through the technical sections (so less time freewheeling)
    while still going slower usually means more braking/scrubbed speed,
    not more pedaling effort. This field doesn't distinguish braking from
    simply choosing tighter, slower lines -- read it as one more component
    to combine, same posture as every other field on this class.
    """


def _slice_series(series: dict, start_idx: int, end_idx: int) -> dict:
    """Every list-valued channel in `series`, sliced to `[start_idx,
    end_idx]` inclusive -- the shape `analytics.normalized_power_w` and
    this module's other per-lap helpers expect. Channels absent from
    `series` stay absent."""
    b = end_idx + 1
    return {k: v[start_idx:b] for k, v in series.items() if isinstance(v, list)}


def _avg_speed_mps(sliced: dict) -> float | None:
    """Mean of `speed_mps` over the slice, ignoring `None` samples. Falls
    back to distance-covered/duration via `dist_m` (first-to-last valid
    sample) when `speed_mps` is absent or every sample in it is `None`
    within this slice."""
    speed = sliced.get("speed_mps")
    if speed:
        clean = [s for s in speed if s is not None]
        if clean:
            return statistics.fmean(clean)

    dist = sliced.get("dist_m")
    t_s = sliced.get("t_s")
    if dist and t_s:
        usable = [(t, d) for t, d in zip(t_s, dist) if d is not None]
        if len(usable) >= 2:
            (t0, d0), (t1, d1) = usable[0], usable[-1]
            duration = t1 - t0
            if duration > 0:
                return (d1 - d0) / duration
    return None


def _coasting_s(sliced: dict) -> float | None:
    """Total time (seconds) at/below `COASTING_POWER_THRESHOLD_W` --
    each sample's power is treated as holding until the NEXT sample
    (left-Riemann; the slice's very last sample contributes no duration,
    since nothing follows it to weight -- same convention `total_work_kj`
    avoids needing entirely by using avg_power*duration instead, but this
    field genuinely needs a sample-by-sample walk since it's asking WHERE
    within the lap the power was low, not just the lap's overall total).
    `None` when no usable power/time pair exists anywhere in the slice --
    distinct from a real `0.0`, which means real samples existed and none
    of them were at/below the threshold."""
    power = sliced.get("power_w")
    t_s = sliced.get("t_s")
    if not power or not t_s or len(power) < 2:
        return None
    total = 0.0
    any_valid = False
    for i in range(len(power) - 1):
        p, t0, t1 = power[i], t_s[i], t_s[i + 1]
        if p is None or t0 is None or t1 is None:
            continue
        any_valid = True
        if p <= COASTING_POWER_THRESHOLD_W:
            total += t1 - t0
    return total if any_valid else None


def lap_metrics(series: dict, lap: GpsLap) -> GpsLapMetrics:
    """Normalized Power, average speed, `efficiency_mps_per_w`,
    `total_work_kj`, `variability_index`, and `coasting_s` for one
    detected `GpsLap`'s slice of `series` -- several deliberately
    different lenses on the same lap, see `GpsLapMetrics`'s own docstring
    for why they're kept separate rather than combined into one score.
    Never raises -- any unavailable input (no power channel, no usable
    speed/distance) yields `None` for that field, same posture as
    `analytics.normalized_power_w`/`average_power_w`.
    """
    sliced = _slice_series(series, lap.start_idx, lap.end_idx)
    norm_power = analytics.normalized_power_w(sliced)
    avg_power = analytics.average_power_w(sliced)
    avg_speed = _avg_speed_mps(sliced)

    efficiency = None
    if norm_power is not None and norm_power > 0 and avg_speed is not None:
        efficiency = avg_speed / norm_power

    total_work_kj = None
    if avg_power is not None:
        total_work_kj = avg_power * lap.duration_s / 1000

    variability_index = None
    if norm_power is not None and avg_power is not None and avg_power > 0:
        variability_index = norm_power / avg_power

    return GpsLapMetrics(
        lap_n=lap.n,
        start_s=lap.start_s,
        end_s=lap.end_s,
        duration_s=lap.duration_s,
        normalized_power_w=norm_power,
        avg_speed_mps=avg_speed,
        efficiency_mps_per_w=efficiency,
        total_work_kj=total_work_kj,
        variability_index=variability_index,
        coasting_s=_coasting_s(sliced),
    )


def analyze_gps_laps(series: dict | None, **detect_kwargs) -> list[GpsLapMetrics]:
    """Convenience orchestrator: `detect_gps_laps(series, **detect_kwargs)`
    then `lap_metrics` for each detected lap. `[]` whenever `detect_gps_laps`
    itself returns `[]` -- see that function's docstring for every such
    case. `**detect_kwargs` forwards `proximity_m`/`min_away_m`/
    `min_lap_duration_s` overrides straight through.
    """
    laps = detect_gps_laps(series, **detect_kwargs)
    return [lap_metrics(series, lap) for lap in laps]
