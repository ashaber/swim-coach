"""Deterministic activity-stream interval analyzer.

Answers "did I hit my intervals?" from a synced ride, spending **zero LLM
tokens** on the stream: a span-scan detects sustained efforts within a ride
(even mid-3-hour-ride), each effort is assessed against its prescribed
target when one is recoverable, and the athlete's real-world terrain
confounds (a threshold interval up a steepening dirt road reads like a
power fade) are flagged rather than silently mis-called.

Pure functions over the columnar series dict `parse_files._build_series`
produces (`t_s` plus `power_w`/`hr`/`grade`/... channels) -- no I/O, no
network, no LLM. `analytics.compute_analytics` is the only caller that
turns this into a persisted `models.WorkoutIntervals`.

Every named threshold below cites `library/26-activity-stream-interval-analysis.md`'s
"Deterministic activity-stream interval analyzer" section (and, for the
interval-shape taxonomy, `library/24-cycling-periodization-intervals.md`).

## Algorithms (each detailed in its function's docstring)

1. **Effort detection** (`detect_efforts`) -- single linear pass over the
   power channel (HR if there's no power) at a low primitive floor, then a
   two-way split: primitives >= `EFFORT_MIN_S` become sustained efforts
   (after a *sustained-level* gate that rejects a warm-up ramp transiently
   cresting the threshold), and runs of short primitives separated by short
   recoveries are collapsed by a **set-clustering** pass into one "rep set"
   effort (so a 30/30 VO2 session surfaces as "6 sets", not "0 efforts"
   and not "60 noise blips").
2. **Per-effort quality** (`assess_effort`) -- split each effort's samples
   into equal thirds and compare first-vs-last: mean power, %-of-target,
   time within an **adaptive** band of target (tight indoors on an ERG,
   wider on rough ground), power fade %, HR drift, mean-grade change.
3. **Terrain confound** (`_terrain_flag`) -- a fixed decision tree over
   (fade %, HR drift, grade change) that decides whether a power fade is
   downhill terrain, the athlete backing off, or a genuine
   fatigue/durability fade.
4. **Sub-structure** (`_sub_structure`) -- within one detected effort,
   report a clustered rep set's on/off pattern, or split a continuous
   over/under block into its OVER vs UNDER halves.
5. **Prescription match** (`match_efforts_to_structure`) -- flatten the
   planned `WorkoutStructure` to a list of interval reps (expanding repeat
   counts), then align the i-th detected effort to the i-th prescribed rep
   positionally, with a +/-25% duration tolerance.
6. **Tightened decoupling** (`tightened_decoupling`) -- the standard
   first-half vs second-half efficiency-factor (HR / power) ratio, but
   computed only over genuinely working samples, refused (with a reason)
   when the ride is too stop-start for that number to mean anything, and
   also refused for an **all-interval** session that carries no steady
   aerobic block for the number to describe.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from swim_coach.models import (
    IntervalEffort,
    IntervalSubStructure,
    WorkoutIntervals,
    WorkoutStructure,
)

# --- constants (library/26-activity-stream-interval-analysis.md) -------------------------------------

EFFORT_MIN_S = 120.0
# Coach judgment: the shortest span still counted as a *sustained* effort
# in its own right. A structured cycling threshold/VO2 work bout at the
# "long interval" end is minutes, not seconds (Buchheit/Laursen's long-
# interval family -- `library/24`). Shorter above-threshold spans are not
# discarded outright any more (that made 30/30-style work invisible) -- they
# are handed to the set-clustering pass below. library/26-activity-stream-interval-analysis.md.

MICRO_EFFORT_MIN_S = 12.0
# Coach judgment / PROVISIONAL: the primitive-detection floor the raw span
# scan uses. A short-short VO2 rep is ~30-40s on (`library/24`, "Short-short
# (VO2)"); after the leading ramp into the rep and a trailing settle, ~12s
# of genuinely-above-threshold samples is the smallest run worth treating as
# a candidate rep. Below this is sensor noise / a single freewheel-and-stamp.
# No source pins the exact number -- tuned against this athlete's real 30/30
# ERG file (lojsta) where a 10s floor also worked and a 20s floor started
# dropping real reps. library/26-activity-stream-interval-analysis.md.

EFFORT_MERGE_GAP_S = 25.0
# Coach judgment: a dip below threshold shorter than this (a corner, a
# freewheel over a crest, a rough patch mid-interval) does NOT end the
# effort -- the scan bridges it, mirroring `analytics.stationary_pauses`'s
# single-source span logic one level up. Longer than
# `analytics.GAP_THRESHOLD_S`'s 30s only by coincidence; different
# measurement. library/26-activity-stream-interval-analysis.md.

SET_RECOVERY_MAX_S = 75.0
# Coach judgment / PROVISIONAL: the longest gap between two consecutive
# short above-threshold reps that still keeps them in the SAME set. A
# short-short set's float recovery is ~15-20s and an over/under-ish 30/30's
# is ~30s (`library/24`), while sets are separated by "several minutes of
# easy recovery" -- so a 75s ceiling comfortably bridges an in-set float
# (even a sloppy one) without ever joining two sets across their multi-
# minute rest. No source pins 75s exactly. library/26-activity-stream-interval-analysis.md.

SET_MIN_REPS = 4
# Coach judgment: a run of fewer than four short above-threshold reps is
# not a "set" -- it's a handful of isolated surges (a sprint for a town
# sign, a few kicks over rollers, some warm-up openers) and "did I hit my
# intervals?" is not asking about those. `library/24` describes VO2 sets as
# "8-12 reps"; four is a floor, not a target -- deliberately above three so
# a warm-up's two or three openers never cluster into a phantom "set".
# library/26-activity-stream-interval-analysis.md.

SET_MIN_ON_POWER_FRAC = 0.80
# Coach judgment: a clustered set is only kept if the mean power across its
# ON reps reaches this fraction of the target (or, with no target, the
# dynamic detection threshold). A cluster of ~180W surges during a 263W
# warm-up is not a VO2 set the athlete "did" -- same 0.80 as
# `TARGET_GATE_FRAC`/`SUSTAINED_EFFORT_GATE_FRAC`, applied to the ON
# segments' average. library/26-activity-stream-interval-analysis.md.

SET_MAX_REP_S = 150.0
# Coach judgment: a primitive longer than this is a work bout in its own
# right (it is at/over `EFFORT_MIN_S` plus a 25% duration tolerance), never
# a "rep" inside a short-short set -- so it can't be swept into a clustered
# set even if short recoveries sit either side of it. library/26-activity-stream-interval-analysis.md.

SET_MAX_SPAN_S = 1500.0
# Coach judgment: a clustered set spanning more than ~25 min of wall clock
# is not one coherent VO2/over-under set -- it is a long stretch of punchy
# riding (an XC race, a group ride) that happens to have sub-75s gaps. Such
# a cluster is dropped rather than reported as a single 25-min "effort".
# library/26-activity-stream-interval-analysis.md.

EFFORT_DYNAMIC_FRAC = 0.62
# Coach judgment: with no supplied target, the detection threshold sits
# this far up from the ride's own 40th-percentile working power toward its
# 85th-percentile working power -- high enough to ignore steady endurance
# riding, low enough to catch a threshold (not just VO2) interval.
# library/26-activity-stream-interval-analysis.md.

COASTING_FLOOR_W = 20.0
# Coach judgment: at or below this the rider is freewheeling, not pedalling
# -- excluded from "working" percentiles, from the tightened-decoupling
# calc, and it's the floor `analyze` passes as `exclude_below_w`.
# library/26-activity-stream-interval-analysis.md.

TARGET_GATE_FRAC = 0.80
# Coach judgment: when a target IS supplied, a sample counts as "in an
# effort" at or above 80% of it -- an athlete aiming for 239W who is
# holding 195W is still visibly *trying* to do the interval, not resting.
# library/26-activity-stream-interval-analysis.md.

SUSTAINED_EFFORT_GATE_FRAC = 0.80
# Coach judgment: a candidate >= `EFFORT_MIN_S` span only survives if its
# own MEAN power (not just momentary threshold crossings) reaches this
# fraction of the target -- a warm-up ramp from 138->248W transiently
# crests an 80%-of-263W line near its top but averages ~73% of it, so it
# must NOT register as a (failed) effort. Same 0.80 as `TARGET_GATE_FRAC`:
# the instantaneous entry bar and the whole-span average bar are the same
# height by design -- "195W against a 239W target is still an attempt"
# applies to the *sustained* level too, not one lucky sample. In dynamic
# (no-target) mode the equivalent gate is "span mean >= the detection
# threshold itself". library/26-activity-stream-interval-analysis.md.

IN_BAND_FRAC = 0.05
# [ADAPTED: cycling] Confidence: medium. Time within +/-5% of target power
# is the compliance metric the power-training literature favours for
# judging an interval (explicitly NOT normalized power, a fatigue-cost
# estimate cautioned against for this use). +/-5% is the standard
# practitioner target band (Allen/Coggan lineage) -- and the right band for
# an indoor ERG ride, which holds watts to within a percent or two. It is
# the FLOOR and the indoor value of the adaptive band below. library/26-activity-stream-interval-analysis.md.

IN_BAND_FRAC_MAX = 0.15
# Coach judgment: the widest the adaptive in-band tolerance opens for a
# rough-ground ride. +/-15% of target is about the honest limit of "held
# the interval" for a gravel/MTB effort where grade, surface and line
# choice move the power around under a rider who is pacing by feel and
# breathing, not chasing the number sample-to-sample. Beyond this it is not
# terrain noise any more, it's a different intensity. library/26-activity-stream-interval-analysis.md.

IN_BAND_ROUGHNESS_MULT = 2.0
# Coach judgment: the adaptive band is `roughness * this`, clamped to
# [`IN_BAND_FRAC`, `IN_BAND_FRAC_MAX`], where `roughness` is the ride's
# median sample-to-sample |power change| as a fraction of mean working
# power. On this athlete's real files that lands ~5% (indoor ERG, roughness
# ~0.005), ~9% (paved road / gravel, ~0.046), ~15% (MTB, ~0.115) -- i.e. the
# band an experienced coach would eyeball for each surface. The multiplier
# is a fitted constant, not a cited one. library/26-activity-stream-interval-analysis.md.

INDOOR_ROUGHNESS_MAX = 0.02
# Coach judgment: a ride whose median sample-to-sample power roughness is
# below this was almost certainly ridden in ERG/trainer mode (the trainer,
# not the rider, is holding the watts) -- it keeps the tight `IN_BAND_FRAC`
# band regardless of the adaptive calc. A caller that knows the FIT
# `sub_sport`/`trainer` flag can override via `analyze(..., indoor=...)`.
# library/26-activity-stream-interval-analysis.md.

FADE_FLAG_PCT = 10.0
# [ADAPTED: cycling] Confidence: medium. First-third-vs-last-third mean
# power drop within one effort. `Barsumyan A., Soost C., Burchard R.
# (2025)` measured ~6.5% first-to-last power decline over a 20-min fatigued
# interval in successful amateur road cyclists vs ~12.5% in less successful
# ones -- so a >~10% fade is a meaningful durability/pacing signal, not
# noise. library/26-activity-stream-interval-analysis.md.

HR_HELD_BAND_BPM = 2.0
# Coach judgment: an HR drift between -2 and +2 bpm across an effort is
# "held" -- neither a back-off nor a climb. library/26-activity-stream-interval-analysis.md.

HR_BACKOFF_DROP_BPM = 5.0
# Coach judgment: HR falling more than 5 bpm across an effort, alongside a
# power fade, reads as the athlete easing off, not terrain.
# library/26-activity-stream-interval-analysis.md.

GRADE_DROP_FLAG = 0.03
# Coach judgment: a mid-effort mean-grade decrease of >= 3 percentage
# points (first third vs last third) is "materially more downhill" -- the
# terrain confound this analyzer exists to catch on dirt-road intervals.
# library/26-activity-stream-interval-analysis.md.

TIGHTENED_DECOUPLING_MIN_WORKING_FRAC = 0.5
# Coach judgment: the standard first-half-EF vs second-half-EF decoupling
# calc is documented (TrainingPeaks) as invalid on "variable, stop-start
# or all-out" rides -- so if less than half the moving time was spent
# above `COASTING_FLOOR_W`, `tightened_decoupling` returns `(None,
# reason)` rather than a misleading number. library/26-activity-stream-interval-analysis.md.

ALL_INTERVAL_EFFORT_COVERAGE = 0.45
# Coach judgment: if the ride's own dynamic-threshold efforts (detected
# with NO supplied target, so this is a property of the RIDE, not of the
# coach's query) cover at least this fraction of working time AND there are
# at least `ALL_INTERVAL_MIN_EFFORTS` of them, the ride is "all-interval"
# -- a pure VO2/threshold session with no steady aerobic block -- and a
# first-half/second-half efficiency-factor decoupling number is meaningless.
# `analyze` then returns `None` + a reason for `decoupling_tightened_pct`.
# On this athlete's real files this lands ~0.51 on a 30/30 VO2 ERG session
# (fires) vs ~0.38 on a 2x12 threshold ride and ~0.22-0.27 on long mixed
# rides (all keep their real number). The fraction is a fitted cutoff.
# library/26-activity-stream-interval-analysis.md.

ALL_INTERVAL_MIN_EFFORTS = 3
# Coach judgment: a single long sustained block (a 40k TT, one 30-min
# tempo) can cover a high fraction of a short ride's working time without
# being an "all-interval" session -- so the all-interval guard also
# requires three or more distinct dynamic efforts before it will null the
# decoupling read. library/26-activity-stream-interval-analysis.md.

OVER_UNDER_MIN_CYCLES = 3
# Coach judgment: an over/under set is "roughly regular" alternation -- at
# least three OVER segments (`library/24` describes 2-4 over/under blocks
# built from many ~90s alternations). Two high patches inside an effort is
# not a pattern. library/26-activity-stream-interval-analysis.md.

OVER_UNDER_SMOOTH_S = 30.0
# Coach judgment: raw MTB/gravel power crosses its own mean many times a
# minute from surface and line noise alone (~150 zero-crossings in a 10-min
# effort on this athlete's real singletrack file) -- so power is first
# smoothed with a centred ~30s moving average before high/low runs are
# labelled. 30s is short enough to preserve a real ~90-120s over/under
# segment and long enough to erase the sample-to-sample chatter.
# library/26-activity-stream-interval-analysis.md.

OVER_UNDER_MIN_SEG_S = 20.0
# Coach judgment: after smoothing, a high or low run shorter than this is
# merged into its neighbour before cycles are counted -- residual wobble,
# not an over/under segment (those are ~90s, `library/24`). library/26-activity-stream-interval-analysis.md.

OVER_UNDER_MIN_MEDIAN_SEG_S = 30.0
# Coach judgment: the median OVER-segment must last at least this long for
# the pattern to be a real over/under rather than a stepped effort whose
# sustained portion happens to wobble across its own mean. library/26-activity-stream-interval-analysis.md.

OVER_UNDER_MIN_SPREAD_FRAC = 0.16
# Coach judgment: the OVER-segment mean and UNDER-segment mean must differ
# by at least this fraction of the effort's overall mean for the effort to
# be called an over/under. `library/24`'s canonical over (~100-105% FTP)
# vs under (~76-85% FTP) is a ~20% spread; the defining feature is that the
# UNDER segments deliberately drop *below* threshold. A steady threshold
# block's incidental power wobble stays bunched near the target (this
# athlete's real 2x12 file: ~15% smoothed spread, all of it near threshold)
# -- 16% is the floor that separates a set ridden loosely by feel (still a
# real ~18-25% spread on her Heat Animation file) from a 2x12 that only
# looks bimodal because a climb undulates. library/26-activity-stream-interval-analysis.md.

DURATION_TOLERANCE_FRAC = 0.25
# Coach judgment: a detected effort whose duration is within +/-25% of a
# prescribed rep's duration is "the same rep" for match_efforts_to_
# structure's alignment. library/26-activity-stream-interval-analysis.md.


# --- result types (internal; analyze() returns the pydantic WorkoutIntervals) ------


@dataclass(frozen=True)
class DetectedEffort:
    """One sustained effort located by `detect_efforts` -- index range into
    the series arrays plus its wall-clock span. `kind == "rep_set"` when it
    is a run of short reps the set-clustering pass collapsed; `member_spans`
    then holds each ON rep's `(start_idx, end_idx)` (inclusive)."""

    n: int
    start_idx: int
    end_idx: int  # inclusive
    start_s: float
    end_s: float
    kind: str = "sustained"  # "sustained" | "rep_set"
    member_spans: tuple[tuple[int, int], ...] = field(default=())

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


@dataclass(frozen=True)
class EffortQuality:
    """`assess_effort`'s verdict on one effort -- the raw numbers behind
    the persisted `models.IntervalEffort`."""

    avg_w: float | None
    avg_hr: int | None
    target_w: float | None
    pct_of_target: float | None
    avg_vs_target_w: float | None
    time_in_band_pct: float | None
    fade_pct: float | None
    hr_drift_bpm: float | None
    grade_delta_pct_pts: float | None
    terrain_flag: str | None
    verdict: str


@dataclass(frozen=True)
class MatchResult:
    matched: bool
    prescribed_count: int
    detected_count: int
    # per_rep[i] = (detected_index_or_None, target_w_or_None, duration_ok)
    per_rep: list[tuple[int | None, float | None, bool]]


# --- small helpers -----------------------------------------------------------------


def _mean(values: list) -> float | None:
    clean = [v for v in values if v is not None]
    return statistics.fmean(clean) if clean else None


def _percentile(sorted_vals: list[float], frac: float) -> float:
    if not sorted_vals:
        return 0.0
    if frac <= 0:
        return sorted_vals[0]
    if frac >= 1:
        return sorted_vals[-1]
    pos = frac * (len(sorted_vals) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def _thirds(values: list) -> tuple[list, list, list]:
    n = len(values)
    if n < 3:
        return values, [], values
    cut = n // 3
    return values[:cut], values[cut : n * 2 // 3], values[-cut:]


def _detection_channel(series: dict) -> tuple[str, list] | None:
    """`("power", series["power_w"])` when a usable power channel exists,
    else `("hr", series["hr"])`, else `None`."""
    for key, basis in (("power_w", "power"), ("hr", "hr")):
        chan = series.get(key)
        if chan and any(v is not None for v in chan):
            return basis, chan
    return None


# --- effort detection ------------------------------------------------------------------


@dataclass(frozen=True)
class _Span:
    start_idx: int
    end_idx: int  # inclusive
    start_s: float
    end_s: float

    @property
    def duration_s(self) -> float:
        return self.end_s - self.start_s


def _scan_spans(
    t_s: list, chan: list, threshold: float, *, merge_gap_s: float, min_s: float
) -> list[_Span]:
    """Single linear pass: every run of `chan >= threshold` (dips shorter
    than `merge_gap_s` bridged) lasting at least `min_s` becomes a `_Span`."""
    spans: list[_Span] = []
    span_start: int | None = None
    last_above: int | None = None

    def close(end_idx: int) -> None:
        nonlocal span_start, last_above
        if span_start is not None:
            if t_s[end_idx] - t_s[span_start] >= min_s:
                spans.append(
                    _Span(span_start, end_idx, t_s[span_start], t_s[end_idx])
                )
        span_start = None
        last_above = None

    for i in range(len(t_s)):
        v = chan[i]
        above = v is not None and v >= threshold
        if above:
            if span_start is None:
                span_start = i
            last_above = i
        elif span_start is not None and last_above is not None:
            if t_s[i] - t_s[last_above] > merge_gap_s:
                close(last_above)
    if span_start is not None and last_above is not None:
        close(last_above)
    return spans


def _span_channel_mean(chan: list, span: _Span) -> float | None:
    return _mean(chan[span.start_idx : span.end_idx + 1])


def detect_efforts(
    series: dict,
    *,
    target_w: float | None = None,
    min_effort_s: float = EFFORT_MIN_S,
    merge_gap_s: float = EFFORT_MERGE_GAP_S,
) -> list[DetectedEffort]:
    """Locate the ride's deliberate efforts: sustained work bouts AND
    clustered short-rep sets.

    Algorithm:

    1. **Pick the channel**: `power_w` if it has any real samples, else
       `hr`, else return `[]`.
    2. **Derive the threshold** (unchanged): `target_w * TARGET_GATE_FRAC`
       when a target is supplied (power only), else a dynamic
       `P40 + EFFORT_DYNAMIC_FRAC * (P85 - P40)` over the ride's own working
       samples.
    3. **Primitive scan** (`_scan_spans`) at the low `MICRO_EFFORT_MIN_S`
       floor -- bridging sub-`merge_gap_s` dips -- so a 30s VO2 rep is a
       primitive, not invisible.
    4. **Split the primitives**:
       - `dur >= min_effort_s` -> a **sustained** candidate. It survives
         only if its own mean on the detection channel reaches the
         *sustained-level* gate: `target_w * SUSTAINED_EFFORT_GATE_FRAC`
         with a target, or the detection threshold itself without one. This
         is what stops a warm-up ramp -- mean well under target, only its
         tip over the line -- from registering as a failed effort.
       - `MICRO_EFFORT_MIN_S <= dur < SET_MAX_REP_S` -> a **short rep**,
         handed to clustering.
       - anything between `SET_MAX_REP_S` and `min_effort_s` that failed the
         sustained gate is dropped (too long to be a rep, too weak to be an
         effort).
    5. **Set clustering**: walk the short reps in time order; a new set
       starts whenever the gap from the previous rep's end exceeds
       `SET_RECOVERY_MAX_S`. A set with `>= SET_MIN_REPS` reps and a total
       span `<= SET_MAX_SPAN_S` becomes ONE `DetectedEffort` (`kind=
       "rep_set"`, `member_spans` = each rep) spanning first-rep-start to
       last-rep-end. Smaller/looser clusters are discarded as isolated
       surges.
    6. **Merge & renumber**: sustained efforts + set efforts, sorted by
       start time, numbered 1..k.

    See `library/26-activity-stream-interval-analysis.md` and `library/24-cycling-
    periodization-intervals.md`.
    """
    t_s = series.get("t_s")
    picked = _detection_channel(series)
    if not t_s or picked is None:
        return []
    basis, chan = picked

    if basis == "power" and target_w:
        threshold = target_w * TARGET_GATE_FRAC
        sustained_gate = target_w * SUSTAINED_EFFORT_GATE_FRAC
    else:
        floor = COASTING_FLOOR_W if basis == "power" else 0.0
        working = sorted(v for v in chan if v is not None and v > floor)
        if len(working) < 10:
            return []
        lo = _percentile(working, 0.40)
        hi = _percentile(working, 0.85)
        threshold = lo + EFFORT_DYNAMIC_FRAC * (hi - lo)
        # Dynamic mode has no external target to gate against; the sustained
        # bar is just "the span didn't spend most of itself down at ordinary
        # endurance power" -- i.e. its mean clears the ride's own 40th-
        # percentile working power. This kills a mid-ride lull that only
        # crested `threshold` on a couple of bridged spikes, without the
        # tight target-mode gate that (correctly) needs a real number.
        sustained_gate = lo

    primitives = _scan_spans(
        t_s, chan, threshold, merge_gap_s=merge_gap_s, min_s=MICRO_EFFORT_MIN_S
    )

    sustained: list[DetectedEffort] = []
    short_reps: list[_Span] = []
    for sp in primitives:
        if sp.duration_s >= min_effort_s:
            m = _span_channel_mean(chan, sp)
            if m is not None and m >= sustained_gate:
                sustained.append(
                    DetectedEffort(
                        n=0, start_idx=sp.start_idx, end_idx=sp.end_idx,
                        start_s=sp.start_s, end_s=sp.end_s,
                    )
                )
        elif sp.duration_s < SET_MAX_REP_S:
            short_reps.append(sp)
        # (SET_MAX_REP_S..min_effort_s that failed the gate: dropped)

    set_efforts = [
        se
        for se in _cluster_rep_sets(short_reps)
        if _rep_set_on_power(chan, se) is not None
        and _rep_set_on_power(chan, se) >= sustained_gate
    ]

    merged = sorted(sustained + set_efforts, key=lambda e: e.start_s)
    return [
        DetectedEffort(
            n=k + 1, start_idx=e.start_idx, end_idx=e.end_idx,
            start_s=e.start_s, end_s=e.end_s, kind=e.kind, member_spans=e.member_spans,
        )
        for k, e in enumerate(merged)
    ]


def _rep_set_on_power(chan: list, effort: DetectedEffort) -> float | None:
    """Mean of the detection channel over a clustered set's ON reps only
    (the float recoveries between reps excluded)."""
    vals = [
        v
        for a, b in effort.member_spans
        for v in chan[a : b + 1]
        if v is not None
    ]
    return statistics.fmean(vals) if vals else None


def _cluster_rep_sets(short_reps: list[_Span]) -> list[DetectedEffort]:
    """Group time-ordered short reps into sets (new set once the gap from
    the previous rep exceeds `SET_RECOVERY_MAX_S`); keep a group as one
    `rep_set` effort only if it has `>= SET_MIN_REPS` reps and spans
    `<= SET_MAX_SPAN_S`."""
    if not short_reps:
        return []
    reps = sorted(short_reps, key=lambda s: s.start_s)
    groups: list[list[_Span]] = [[reps[0]]]
    for sp in reps[1:]:
        if sp.start_s - groups[-1][-1].end_s <= SET_RECOVERY_MAX_S:
            groups[-1].append(sp)
        else:
            groups.append([sp])

    out: list[DetectedEffort] = []
    for g in groups:
        if len(g) < SET_MIN_REPS:
            continue
        span_s = g[-1].end_s - g[0].start_s
        if span_s > SET_MAX_SPAN_S:
            continue
        out.append(
            DetectedEffort(
                n=0,
                start_idx=g[0].start_idx,
                end_idx=g[-1].end_idx,
                start_s=g[0].start_s,
                end_s=g[-1].end_s,
                kind="rep_set",
                member_spans=tuple((sp.start_idx, sp.end_idx) for sp in g),
            )
        )
    return out


# --- adaptive in-band tolerance -------------------------------------------------------


def _power_roughness(series: dict) -> float | None:
    """Median sample-to-sample |power change| as a fraction of mean working
    power -- a surface/mode proxy: ~0.005 on an indoor ERG ride, ~0.05 on
    pavement/gravel, ~0.12 on singletrack. `None` if there's no power."""
    power = series.get("power_w")
    if not power:
        return None
    working = [p for p in power if p is not None and p > COASTING_FLOOR_W]
    if len(working) < 30:
        return None
    mean_p = statistics.fmean(working)
    if mean_p <= 0:
        return None
    diffs = [abs(working[i] - working[i - 1]) for i in range(1, len(working))]
    return statistics.median(diffs) / mean_p


def _adaptive_in_band_frac(series: dict, *, indoor: bool | None = None) -> float:
    """The +/-fraction-of-target band `assess_effort` calls "in band" for
    THIS ride: `IN_BAND_FRAC` (tight) indoors or when power is very smooth,
    scaling up to `IN_BAND_FRAC_MAX` as the ride's sample-to-sample power
    roughness rises. See the `IN_BAND_*` constants."""
    if indoor is True:
        return IN_BAND_FRAC
    roughness = _power_roughness(series)
    if roughness is None:
        return IN_BAND_FRAC
    if indoor is None and roughness < INDOOR_ROUGHNESS_MAX:
        return IN_BAND_FRAC
    band = roughness * IN_BAND_ROUGHNESS_MULT
    return max(IN_BAND_FRAC, min(IN_BAND_FRAC_MAX, band))


# --- per-effort quality --------------------------------------------------------------


def assess_effort(
    series: dict,
    effort: DetectedEffort,
    *,
    target_w: float | None = None,
    in_band_frac: float = IN_BAND_FRAC,
) -> EffortQuality:
    """Assess one detected effort: average power, average-vs-target (W and
    %), time-in-target-band %, within-effort power fade %, HR drift, and a
    terrain-confound flag.

    `in_band_frac` is the +/-fraction of target counted as "in band"
    (default `IN_BAND_FRAC`; `analyze` passes `_adaptive_in_band_frac`'s
    surface-scaled value). Everything else is unchanged: slice the series to
    `[start_idx, end_idx]`, then mean power, vs-target, thirds-based fade,
    HR drift, grade delta, `_terrain_flag`, `_verdict`.

    See `library/26-activity-stream-interval-analysis.md`.
    """
    a, b = effort.start_idx, effort.end_idx + 1
    power = (series.get("power_w") or [])[a:b]
    hr = (series.get("hr") or [])[a:b]
    grade = (series.get("grade") or [])[a:b]

    avg_w = _mean(power)
    avg_hr_f = _mean(hr)
    avg_hr = round(avg_hr_f) if avg_hr_f is not None else None

    pct_of_target = avg_vs_target_w = time_in_band_pct = None
    if target_w and avg_w is not None:
        pct_of_target = round(avg_w / target_w * 100, 1)
        avg_vs_target_w = round(avg_w - target_w, 1)
        lo, hi = target_w * (1 - in_band_frac), target_w * (1 + in_band_frac)
        clean = [p for p in power if p is not None]
        if clean:
            time_in_band_pct = round(sum(lo <= p <= hi for p in clean) / len(clean) * 100, 1)

    p1, _p2, p3 = _thirds(power)
    fade_pct = None
    m1, m3 = _mean(p1), _mean(p3)
    if m1 and m1 > 0 and m3 is not None:
        fade_pct = round((m1 - m3) / m1 * 100, 1)

    h1, _h2, h3 = _thirds(hr)
    hr_drift_bpm = None
    hm1, hm3 = _mean(h1), _mean(h3)
    if hm1 is not None and hm3 is not None:
        hr_drift_bpm = round(hm3 - hm1, 1)

    g1, _g2, g3 = _thirds(grade)
    grade_delta_pct_pts = None
    gm1, gm3 = _mean(g1), _mean(g3)
    if gm1 is not None and gm3 is not None:
        grade_delta_pct_pts = round((gm1 - gm3) * 100, 1)

    terrain_flag = _terrain_flag(fade_pct, hr_drift_bpm, grade_delta_pct_pts)
    verdict = _verdict(pct_of_target, time_in_band_pct, fade_pct, terrain_flag, avg_w, target_w)

    return EffortQuality(
        avg_w=round(avg_w, 1) if avg_w is not None else None,
        avg_hr=avg_hr,
        target_w=target_w,
        pct_of_target=pct_of_target,
        avg_vs_target_w=avg_vs_target_w,
        time_in_band_pct=time_in_band_pct,
        fade_pct=fade_pct,
        hr_drift_bpm=hr_drift_bpm,
        grade_delta_pct_pts=grade_delta_pct_pts,
        terrain_flag=terrain_flag,
        verdict=verdict,
    )


def _terrain_flag(
    fade_pct: float | None, hr_drift_bpm: float | None, grade_delta_pct_pts: float | None
) -> str | None:
    """Fixed decision tree, evaluated in this order (first match wins):
    1. fade <= 3% -> `None` (nothing to explain).
    2. grade dropped >= `GRADE_DROP_FLAG` AND HR held/rising -> "terrain":
       the power fell because the road stopped climbing, not because the
       athlete tired.
    3. HR dropped >= `HR_BACKOFF_DROP_BPM` (alongside the fade) -> "backed
       off": power and HR fell together.
    4. fade >= `FADE_FLAG_PCT` (10%) AND HR held/rising -> "genuine fade":
       power fell while HR did not -- fatigue/durability.
    5. otherwise -> `None`.
    "held/rising" = HR drift >= `-HR_HELD_BAND_BPM` (>= -2 bpm).
    """
    if fade_pct is None or fade_pct <= 3.0:
        return None  # no meaningful fade to explain
    hr_held_or_rising = hr_drift_bpm is None or hr_drift_bpm >= -HR_HELD_BAND_BPM
    hr_dropped = hr_drift_bpm is not None and hr_drift_bpm <= -HR_BACKOFF_DROP_BPM
    grade_dropped = grade_delta_pct_pts is not None and grade_delta_pct_pts >= GRADE_DROP_FLAG * 100

    if grade_dropped and hr_held_or_rising:
        return (
            "power fade tracks a downhill grade change "
            f"(~{grade_delta_pct_pts:.0f} pts less climb) while HR held -- "
            "likely terrain, not easing off"
        )
    if hr_dropped:
        return "power and HR both dropped -- backed off"
    if fade_pct >= FADE_FLAG_PCT and hr_held_or_rising:
        return (
            f"power faded {fade_pct:.0f}% with HR held -- genuine fade "
            "(fatigue/durability), not terrain"
        )
    return None


def _verdict(
    pct_of_target: float | None,
    time_in_band_pct: float | None,
    fade_pct: float | None,
    terrain_flag: str | None,
    avg_w: float | None,
    target_w: float | None,
) -> str:
    if target_w and pct_of_target is not None:
        if 97 <= pct_of_target <= 103 and (time_in_band_pct or 0) >= 50:
            head = "on target"
        elif pct_of_target < 92:
            head = f"under target ({pct_of_target:.0f}%)"
        elif pct_of_target > 108:
            head = f"over target ({pct_of_target:.0f}%)"
        else:
            head = f"near target ({pct_of_target:.0f}%)"
    elif avg_w is not None:
        head = f"~{avg_w:.0f}W (no target supplied)"
    else:
        head = "HR-only effort (no power)"

    if terrain_flag:
        return f"{head}; {terrain_flag}"
    if fade_pct is not None and fade_pct >= FADE_FLAG_PCT:
        return f"{head}; faded {fade_pct:.0f}% end-to-end"
    if fade_pct is not None and fade_pct <= -FADE_FLAG_PCT:
        return f"{head}; built through it (+{-fade_pct:.0f}%)"
    return head


# --- sub-structure: rep sets & over/unders ------------------------------------------


def _sub_structure(series: dict, effort: DetectedEffort) -> IntervalSubStructure | None:
    """Describe one effort's internal shape, or `None` if it's a single flat
    block.

    - `effort.kind == "rep_set"` (set-clustering pass): report the ON-rep
      count, ON-power vs float-recovery-power, and their median durations,
      straight from `member_spans`.
    - otherwise: look for a roughly regular OVER/UNDER oscillation
      (`_detect_over_under`) and, if found, report the OVER vs UNDER halves.
    """
    power = series.get("power_w")
    t_s = series.get("t_s")
    if not power or not t_s:
        return None

    if effort.kind == "rep_set" and effort.member_spans:
        return _rep_set_sub_structure(power, t_s, effort)

    return _detect_over_under(
        power[effort.start_idx : effort.end_idx + 1],
        t_s[effort.start_idx : effort.end_idx + 1],
    )


def _rep_set_sub_structure(
    power: list, t_s: list, effort: DetectedEffort
) -> IntervalSubStructure | None:
    on_vals: list[float] = []
    on_durs: list[float] = []
    for a, b in effort.member_spans:
        seg = [p for p in power[a : b + 1] if p is not None]
        on_vals.extend(seg)
        on_durs.append(t_s[b] - t_s[a])

    off_vals: list[float] = []
    off_durs: list[float] = []
    for (a0, b0), (a1, _b1) in zip(effort.member_spans, effort.member_spans[1:]):
        seg = [p for p in power[b0 + 1 : a1] if p is not None]
        off_vals.extend(seg)
        off_durs.append(t_s[a1] - t_s[b0])

    span = effort.duration_s or 1.0
    on_total = sum(on_durs)
    off_total = sum(off_durs)
    high_avg = round(statistics.fmean(on_vals), 1) if on_vals else None
    low_avg = round(statistics.fmean(off_vals), 1) if off_vals else None
    high_s = round(statistics.median(on_durs), 1) if on_durs else None
    low_s = round(statistics.median(off_durs), 1) if off_durs else None
    note = (
        f"{len(effort.member_spans)} reps of ~{high_s:.0f}s on"
        + (f" / ~{low_s:.0f}s float" if low_s else "")
        + (f", ~{high_avg:.0f}W on vs ~{low_avg:.0f}W float" if high_avg and low_avg else "")
    )
    return IntervalSubStructure(
        pattern="rep_set",
        n_reps=len(effort.member_spans),
        high_avg_w=high_avg,
        low_avg_w=low_avg,
        high_s=high_s,
        low_s=low_s,
        time_in_high_pct=round(on_total / span * 100, 1),
        time_in_low_pct=round(off_total / span * 100, 1),
        note=note,
    )


def _centred_moving_average(vals: list[float], t_s: list[float], window_s: float) -> list[float]:
    """Centred moving average of `vals` over a +/- `window_s / 2` time
    window. O(n) via a two-pointer sliding sum (samples are ~1 Hz and
    monotonic in `t_s`)."""
    n = len(vals)
    out = [0.0] * n
    half = window_s / 2
    lo = 0
    hi = 0
    run = 0.0
    for i in range(n):
        while lo < n and t_s[lo] < t_s[i] - half:
            run -= vals[lo]
            lo += 1
        while hi < n and t_s[hi] <= t_s[i] + half:
            run += vals[hi]
            hi += 1
        count = hi - lo
        out[i] = run / count if count else vals[i]
    return out


def _detect_over_under(power: list, t_s: list) -> IntervalSubStructure | None:
    """Within one continuous effort, find a roughly regular high/low
    alternation. Power is first smoothed with a centred `OVER_UNDER_SMOOTH_S`
    moving average (raw off-road power crosses its own mean constantly);
    smoothed samples are labelled high/low against the smoothed mean; runs
    shorter than `OVER_UNDER_MIN_SEG_S` are merged into their neighbour; and
    it is an over/under only if `>= OVER_UNDER_MIN_CYCLES` OVER runs remain,
    the median OVER run lasts `>= OVER_UNDER_MIN_MEDIAN_SEG_S`, and the
    OVER-mean vs UNDER-mean spread is `>= OVER_UNDER_MIN_SPREAD_FRAC` of the
    effort mean."""
    raw = [(t, p) for t, p in zip(t_s, power) if p is not None]
    if len(raw) < 60:
        return None
    ts = [t for t, _ in raw]
    sm = _centred_moving_average([p for _, p in raw], ts, OVER_UNDER_SMOOTH_S)
    vals = list(zip(ts, sm))
    mean_p = statistics.fmean(sm)
    if mean_p <= 0:
        return None

    runs: list[list] = []
    for t, p in vals:
        is_high = p >= mean_p
        if runs and runs[-1][0] == is_high:
            runs[-1][1].append((t, p))
        else:
            runs.append([is_high, [(t, p)]])

    def run_dur(pts: list) -> float:
        return pts[-1][0] - pts[0][0]

    merged: list[list] = []
    for is_high, pts in runs:
        if merged and run_dur(pts) < OVER_UNDER_MIN_SEG_S:
            merged[-1][1].extend(pts)
        elif merged and merged[-1][0] == is_high:
            merged[-1][1].extend(pts)
        else:
            merged.append([is_high, list(pts)])
    if len(merged) >= 2 and run_dur(merged[0][1]) < OVER_UNDER_MIN_SEG_S:
        merged[1][1] = merged[0][1] + merged[1][1]
        merged.pop(0)
    coalesced: list[list] = []
    for is_high, pts in merged:
        if coalesced and coalesced[-1][0] == is_high:
            coalesced[-1][1].extend(pts)
        else:
            coalesced.append([is_high, pts])

    over_runs = [pts for is_high, pts in coalesced if is_high]
    under_runs = [pts for is_high, pts in coalesced if not is_high]
    if len(over_runs) < OVER_UNDER_MIN_CYCLES or not under_runs:
        return None
    if statistics.median([run_dur(pts) for pts in over_runs]) < OVER_UNDER_MIN_MEDIAN_SEG_S:
        return None

    over_vals = [p for pts in over_runs for _, p in pts]
    under_vals = [p for pts in under_runs for _, p in pts]
    over_avg = statistics.fmean(over_vals)
    under_avg = statistics.fmean(under_vals)
    if (over_avg - under_avg) / mean_p < OVER_UNDER_MIN_SPREAD_FRAC:
        return None

    span = (vals[-1][0] - vals[0][0]) or 1.0
    over_time = sum(run_dur(pts) for pts in over_runs)
    under_time = sum(run_dur(pts) for pts in under_runs)
    high_s = round(statistics.median([run_dur(pts) for pts in over_runs]), 1)
    low_s = round(statistics.median([run_dur(pts) for pts in under_runs]), 1)
    return IntervalSubStructure(
        pattern="over_under",
        n_reps=len(over_runs),
        high_avg_w=round(over_avg, 1),
        low_avg_w=round(under_avg, 1),
        high_s=high_s,
        low_s=low_s,
        time_in_high_pct=round(over_time / span * 100, 1),
        time_in_low_pct=round(under_time / span * 100, 1),
        note=(
            f"{len(over_runs)} over/under cycles, ~{over_avg:.0f}W over "
            f"(~{high_s:.0f}s) vs ~{under_avg:.0f}W under (~{low_s:.0f}s)"
        ),
    )


# --- match to prescription ---------------------------------------------------------


def _prescribed_reps(structure: WorkoutStructure) -> list[tuple[float | None, float | None]]:
    """Flatten a `WorkoutStructure` to `(duration_s, target_w)` for every
    time-based `role == "interval"` leaf, expanding `WorkoutRepeat` counts.
    `target_w` is read from a `basis == "power_w"` target's `low` (or the
    low/high midpoint); otherwise `None`."""
    out: list[tuple[float | None, float | None]] = []

    def visit(items: list) -> None:
        for item in items:
            if getattr(item, "kind", None) == "repeat":
                count = item.count or 1
                for _ in range(count):
                    visit(item.steps)
            elif getattr(item, "role", None) == "interval":
                dur = item.duration_value if item.duration_kind == "time_s" else None
                tw = None
                tgt = getattr(item, "target", None)
                if tgt is not None and tgt.basis == "power_w":
                    if tgt.low is not None and tgt.high is not None:
                        tw = (tgt.low + tgt.high) / 2
                    else:
                        tw = tgt.low if tgt.low is not None else tgt.high
                out.append((dur, tw))

    visit(structure.items)
    return out


def match_efforts_to_structure(
    detected: list[DetectedEffort], structure: WorkoutStructure | None
) -> MatchResult:
    """Align detected efforts to a prescribed structure's interval reps.

    Algorithm:
    1. `_prescribed_reps` flattens the `WorkoutStructure` tree to an
       ordered `[(duration_s, target_w), ...]` list of every
       `role == "interval"` leaf, expanding each `WorkoutRepeat` by its
       `count`. `target_w` comes from a `basis == "power_w"` target's
       `low`/`high` midpoint.
    2. **Positional alignment**: the i-th prescribed rep is matched to the
       i-th detected effort (no reordering, no best-fit search). A rep's
       `duration_ok` is `abs(detected.duration_s - prescribed) <=
       prescribed * DURATION_TOLERANCE_FRAC` (+/-25%). Prescribed reps
       past the end of the detected list get `(None, target_w, False)`.
    3. `matched` is `True` only if the counts are equal AND every rep's
       `duration_ok`.

    When `structure` is `None` or carries no interval reps, returns
    `matched=False` and the caller reports the detected efforts raw with a
    caller-supplied target. See `library/26-activity-stream-interval-analysis.md`.
    """
    reps = _prescribed_reps(structure) if structure is not None else []
    if not reps:
        return MatchResult(matched=False, prescribed_count=0, detected_count=len(detected), per_rep=[])

    per_rep: list[tuple[int | None, float | None, bool]] = []
    for i, (dur, tw) in enumerate(reps):
        if i < len(detected):
            det = detected[i]
            dur_ok = (
                dur is None
                or dur <= 0
                or abs(det.duration_s - dur) <= dur * DURATION_TOLERANCE_FRAC
            )
            per_rep.append((det.n, tw, bool(dur_ok)))
        else:
            per_rep.append((None, tw, False))

    matched = len(detected) == len(reps) and all(ok for _, _, ok in per_rep)
    return MatchResult(
        matched=matched,
        prescribed_count=len(reps),
        detected_count=len(detected),
        per_rep=per_rep,
    )


# --- tightened decoupling ----------------------------------------------------------


def _is_all_interval(series: dict) -> bool:
    """`True` when the ride is a pure VO2/threshold session with no steady
    aerobic block for a decoupling read to describe: its own
    *dynamic-threshold* efforts (detected with no supplied target, so this
    is a property of the ride and not of the coach's query) number
    `>= ALL_INTERVAL_MIN_EFFORTS` and together cover
    `>= ALL_INTERVAL_EFFORT_COVERAGE` of the ride's working time. See those
    two constants."""
    t_s = series.get("t_s")
    if not t_s:
        return False
    efforts = detect_efforts(series, target_w=None)
    if len(efforts) < ALL_INTERVAL_MIN_EFFORTS:
        return False

    power = series.get("power_w")
    if power and any(p is not None for p in power):
        working_idx = [i for i, p in enumerate(power) if p is not None and p > COASTING_FLOOR_W]
    else:
        working_idx = list(range(len(t_s)))
    if len(working_idx) < 2:
        return False
    working_total = t_s[working_idx[-1]] - t_s[working_idx[0]]
    if working_total <= 0:
        return False
    coverage = sum(e.duration_s for e in efforts) / working_total
    return coverage >= ALL_INTERVAL_EFFORT_COVERAGE


def tightened_decoupling(
    series: dict, *, exclude_below_w: float = COASTING_FLOOR_W
) -> tuple[float | None, str]:
    """The standard first-half-EF vs second-half-EF aerobic-decoupling
    formula (as `analytics.cardiac_drift` uses), but filtered to genuinely
    *working* samples.

    Algorithm:
    1. Require an HR channel and a power (or speed) channel, else
       `(None, reason)`.
    2. `moving` = samples with HR and a positive effort value. `working`
       = `moving` filtered to effort `> floor` (`exclude_below_w` for
       power, 0.5 m/s for speed).
    3. If `len(working) / len(moving) < TIGHTENED_DECOUPLING_MIN_WORKING_
       FRAC` (0.5), the ride was too stop-start -- return `(None, reason)`
       rather than a misleading number.
    4. Split `working` at its own time midpoint into `first` / `second`.
    5. For each half, `EF = mean(HR) / mean(effort)`. Decoupling `pct =
       (EF_second / EF_first - 1) * 100` -- positive means HR crept up
       relative to power (aerobic system drifting).

    The **all-interval** guard (`_is_all_interval`) lives one
    level up in `analyze`, not here -- this function still returns a raw
    number for a caller that wants it (e.g. the CLI), and `analyze`
    overrides it to `(None, reason)` when the ride has no steady block.

    SUPPLEMENTS `WorkoutAnalytics.cardiac_drift_pct`; never replaces it.
    See `library/26-activity-stream-interval-analysis.md`.
    """
    t_s = series.get("t_s")
    hr = series.get("hr")
    if not t_s or not hr or not any(v is not None for v in hr):
        return None, "no HR data -- decoupling needs heart rate"

    power = series.get("power_w")
    speed = series.get("speed_mps")
    use_power = bool(power) and any(v is not None for v in power)
    effort_chan = power if use_power else speed
    if not effort_chan or not any(v is not None for v in effort_chan):
        return None, "no power or speed channel -- can't isolate working effort"
    floor = exclude_below_w if use_power else 0.5

    moving = [
        (t, h, e)
        for t, h, e in zip(t_s, hr, effort_chan)
        if h is not None and e is not None and e > 0
    ]
    working = [(t, h, e) for t, h, e in moving if e > floor]
    if len(moving) < 8 or not working:
        return None, "not enough moving samples for a decoupling read"

    frac = len(working) / len(moving)
    if frac < TIGHTENED_DECOUPLING_MIN_WORKING_FRAC:
        return None, (
            f"ride too stop-start for a valid decoupling read -- only {frac * 100:.0f}% "
            "of moving time was above the coasting floor"
        )

    mid_t = (working[0][0] + working[-1][0]) / 2
    first = [(h, e) for t, h, e in working if t < mid_t]
    second = [(h, e) for t, h, e in working if t >= mid_t]
    if len(first) < 3 or len(second) < 3:
        return None, "working samples too lopsided in time for a first-half/second-half split"

    def hr_per_effort(pairs: list[tuple[float, float]]) -> float:
        return statistics.fmean(h for h, _ in pairs) / statistics.fmean(e for _, e in pairs)

    r1, r2 = hr_per_effort(first), hr_per_effort(second)
    if r1 == 0:
        return None, "degenerate first-half efficiency (zero)"
    pct = round((r2 / r1 - 1) * 100, 1)
    return pct, (
        f"measured on the {frac * 100:.0f}% of moving time spent working "
        f"(above {floor:g}{'W' if use_power else ' m/s'})"
    )


# --- public entry point ----------------------------------------------------------


def analyze(
    series: dict | None,
    *,
    sport: str | None,
    target_w: float | None = None,
    structure: WorkoutStructure | None = None,
    indoor: bool | None = None,
) -> WorkoutIntervals | None:
    """Full deterministic interval analysis for one ride. Returns a
    `models.WorkoutIntervals` for `sport == "bike"` rides that carry a
    usable power or HR series; `None` for every other sport / series-less
    workout (that's what keeps swim/kayak `analytics.intervals` `None`).

    `target_w` is the caller-supplied per-interval power target (e.g. the
    coach passing "2x12 at 91% of 263W"). `structure`, when a
    `WorkoutStructure` is recoverable for the session, aligns detected
    efforts to prescribed reps and takes each rep's own `power_w` target.
    `indoor` (optional) forces the tight in-band tolerance when the caller
    knows the ride was on an ERG/trainer; left `None` it's inferred from
    the ride's own power roughness.

    Orchestration:
    1. Gate: `sport == "bike"` and a usable power/HR series, else `None`.
    2. `detect_efforts` -> sustained efforts + clustered rep sets.
    3. `match_efforts_to_structure` -> positional rep alignment.
    4. `_adaptive_in_band_frac` -> this ride's in-band tolerance.
    5. Per effort: `assess_effort` (effective target = matched rep target
       else `target_w`) + `_sub_structure` -> a persisted
       `models.IntervalEffort`.
    6. `tightened_decoupling`, then override to `(None, reason)` if
       `_is_all_interval` says the ride is a pure VO2/threshold session.
    7. Assemble into `models.WorkoutIntervals`.
    """
    if sport != "bike" or not series:
        return None
    picked = _detection_channel(series)
    if picked is None:
        return None
    basis = picked[0]

    reps = _prescribed_reps(structure) if structure is not None else []
    efforts = detect_efforts(series, target_w=target_w)
    match = match_efforts_to_structure(efforts, structure)
    in_band = _adaptive_in_band_frac(series, indoor=indoor)

    out_efforts: list[IntervalEffort] = []
    for e in efforts:
        rep_target = None
        if reps and e.n - 1 < len(reps):
            rep_target = reps[e.n - 1][1]
        eff_target = rep_target if rep_target is not None else target_w
        q = assess_effort(series, e, target_w=eff_target, in_band_frac=in_band)
        out_efforts.append(
            IntervalEffort(
                n=e.n,
                start_s=round(e.start_s, 1),
                duration_s=round(e.duration_s, 1),
                avg_w=q.avg_w,
                avg_hr=q.avg_hr,
                target_w=round(eff_target, 1) if eff_target is not None else None,
                pct_of_target=q.pct_of_target,
                avg_vs_target_w=q.avg_vs_target_w,
                time_in_band_pct=q.time_in_band_pct,
                fade_pct=q.fade_pct,
                hr_drift_bpm=q.hr_drift_bpm,
                grade_delta_pct_pts=q.grade_delta_pct_pts,
                terrain_flag=q.terrain_flag,
                verdict=q.verdict,
                sub_structure=_sub_structure(series, e),
            )
        )

    decoupling_pct, decoupling_note = tightened_decoupling(series)
    if decoupling_pct is not None and _is_all_interval(series):
        decoupling_pct = None
        decoupling_note = (
            "all-interval session -- no steady aerobic block for a valid decoupling read"
        )

    return WorkoutIntervals(
        efforts_detected=len(efforts),
        detection_basis=basis,
        matched_to_prescription=match.matched,
        prescribed_count=match.prescribed_count or (len(reps) or None),
        efforts=out_efforts,
        decoupling_tightened_pct=decoupling_pct,
        decoupling_note=decoupling_note,
    )
