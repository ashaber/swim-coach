"""Bike workout builders and their constants (extracted from `plan.py`; library/24, library/28)."""

from __future__ import annotations

from typing import Callable, Literal

from swim_coach.models import (
    Athlete,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStepOrRepeat,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.stimulus import StimulusKind, walk_leaves
from swim_coach.workout_builders.intent import WorkoutIntent
from swim_coach.workout_builders.registry import (
    ZONE_KINDS,
    BuildResult,
    ParamRange,
    WorkoutBuilder,
    register,
)
from swim_coach.workout_builders.rung import format_duration, format_rung
from swim_coach.zones import bike_zone_table

BIKE_WARMUP_COOLDOWN_MIN = 5.0
# Coach judgment: a flat, easy-zone warm-up/cool-down window bracketing a
# generic Z2/Z3 bike session's main block -- same "some warm-up matters, no
# source fixes an exact proportion" footing as swim's own
# ADDITIONAL_SWIM_WARM_UP_SHARE (library/14-swim-set-structure.md); no
# cycling-specific session-shape source exists to cite instead
# (library/23-cycling-training.md has none). Symmetric and much shorter
# than swim's proportional warm-up since a bike session's total duration
# is typically far longer per session and doesn't need a %-of-session
# scaling rule to stay sane.

BIKE_MIN_MAIN_BLOCK_S = 600.0
# Below 10 minutes of main-block time (after reserving
# BIKE_WARMUP_COOLDOWN_MIN on each side), warm-up/cool-down are dropped
# entirely and the whole session becomes one continuous block at its
# assigned zone -- same "too short to bother splitting" floor
# MIN_ADDITIONAL_SWIM_M's swim counterpart applies. Coach judgment.

# --- Bike interval-session templates (engine/cycling-coach, deferred-gap --
# closing pass) -----------------------------------------------------------
# library/24-cycling-periodization-intervals.md's "Interval-design taxonomy
# (Laursen & Buchheit)" section grounds four named %FTP-band/duration/
# work:rest archetypes (Buchheit & Laursen 2013; Laursen & Buchheit 2019),
# closing the gap `_bike_session_structure`'s former "KNOWN, DOCUMENTED
# LIMITATION" comment flagged (every hard session was the same flat block
# regardless of week/discipline, contradicting that same library file's own
# Protzen et al. 2026 warning that MTB/CX needs surge/interval-shaped
# content). The exact work/rest seconds and rep counts below are this
# engine's OWN specific instantiation within each template's stated range --
# library/24 itself says as much ("the specific instantiation ... is Coach
# judgment: practitioner convention layered on the taxonomy's general
# principles above, not a verbatim quote from Laursen & Buchheit").
# %FTP-band -> Coggan zone mapping uses `zones.py`'s existing named Z1-Z5
# table (library/23-cycling-training.md) rather than inventing a
# custom-band WorkoutTarget -- every existing bike zone in this codebase
# already resolves through that same named table (`_bike_step`/
# `bike_zone_table`), so snapping each template's stated %FTP band to its
# closest single Coggan zone is the consistent choice, not a new mechanism.

BIKE_SUSTAINED_THRESHOLD_WORK_S = 600.0
# 10 min -- the midpoint of library/24's "roughly 8-12 minutes" sustained-
# threshold work-bout range.
BIKE_SUSTAINED_THRESHOLD_REST_S = 240.0
# 4 min -- library/24 says only "near-full recovery between reps," no exact
# figure. Coach judgment default; see `_fit_units_with_flexible_gap` for how
# this is actually adjusted per-session to exactly fill the available
# main-block time (this constant is a bias/starting point, not a hard rule).
BIKE_SUSTAINED_THRESHOLD_MIN_REPS = 2
BIKE_SUSTAINED_THRESHOLD_MAX_REPS = 3
# library/24: "2-3 reps per session."
BIKE_SUSTAINED_THRESHOLD_ZONE = "Z4"
# library/24: ~91-100% FTP -- falls entirely within Z4's 90-105% band
# (zones.py's BIKE_Z3_HI_PCT_FTP/BIKE_Z4_HI_PCT_FTP, library/23).

BIKE_OVER_UNDER_ON_S = 90.0
BIKE_OVER_UNDER_OFF_S = 90.0
# library/24: "alternating ~90-second sub-threshold ... and ~90-second
# supra-threshold work."
BIKE_OVER_UNDER_CYCLES_PER_BLOCK = 2
# 2 on/off cycles = 2*(90+90)s = 6 min per block -- the lower bound of
# library/24's "roughly 6-8 minutes" per-block range; a fixed per-block
# shape (only the number of BLOCKS adapts to available time below), same
# posture as every other "fixed citation-grounded work shape, adaptive
# rep/block count" template here.
BIKE_OVER_UNDER_BLOCK_REST_S = 180.0
# 3 min easy between blocks -- library/24 says only "recovery between
# blocks," no exact figure. Coach judgment default (see
# BIKE_SUSTAINED_THRESHOLD_REST_S's comment on how this is actually used).
BIKE_OVER_UNDER_MIN_BLOCKS = 2
BIKE_OVER_UNDER_MAX_BLOCKS = 4
# library/24: "2-4 blocks per session."
BIKE_OVER_UNDER_OVER_ZONE = "Z4"
# library/24: "over" ~100-105% FTP -- within Z4's 90-105% band.
BIKE_OVER_UNDER_UNDER_ZONE = "Z3"
# library/24: "under" ~76-85% FTP -- within Z3's 75-90% band.

BIKE_SHORT_SHORT_ON_S = 30.0
BIKE_SHORT_SHORT_OFF_S = 15.0
# library/24: "roughly 30-40 seconds on, 15-20 seconds off" -- the literal
# "30s/15s" example given in that file's own taxonomy-grounding paragraph.
BIKE_SHORT_SHORT_REPS_PER_SET = 10
# library/24: "sets of 8-12 reps" -- 10 is the midpoint.
BIKE_SHORT_SHORT_SET_REST_S = 240.0
# 4 min -- library/24 says only "several minutes of easy recovery between
# sets," no exact figure. Coach judgment default.
BIKE_SHORT_SHORT_MIN_SETS = 1
BIKE_SHORT_SHORT_MAX_SETS = 2
# library/24: "1-2 sets per session."
BIKE_SHORT_SHORT_ZONE = "Z5"
# library/24: ~106-118% FTP -- within Z5's 105-120% band.

BIKE_RACE_PACE_WORK_S = 150.0
# 2.5 min -- the midpoint of library/24's "roughly 2-3 minutes" race-pace
# work-bout range.
BIKE_RACE_PACE_REST_S = 150.0
# 2.5 min (1:1 with work) -- library/24 says only "near-full recovery
# between reps," no exact figure. Coach judgment default.
BIKE_RACE_PACE_MIN_REPS = 3
BIKE_RACE_PACE_MAX_REPS = 5
# library/24: "3-5 reps per session."
BIKE_RACE_PACE_ZONE = "Z5"
# library/24: ~105-114% FTP, explicitly described as bridging "the Z4/Z5
# boundary" -- doesn't sit cleanly inside one named Coggan zone. Approximated
# to Z5 (105-120% FTP) since library/24 frames this template as bridging
# TOWARD the VO2max stimulus ("Bridges the threshold and VO2max stimuli");
# Z4 would be the equally-defensible alternative snap -- documented here as
# an engineering approximation, not a precise reproduction of the stated
# 105-114% band.

BIKE_OPENERS_REST_S = 180.0
# Full recovery between openers (~1:2 work:rest of the old flat-bout shape,
# kept as the recovery figure for the new ramp shape below too) --
# library/24 says "full recovery", no exact figure; Coach judgment default,
# adjusted per-session by `_fit_units_with_flexible_gap` the same way every
# other template's rest constant is.
BIKE_OPENERS_MIN_REPS = 2
BIKE_OPENERS_MAX_REPS = 4
# Build E (race-week-content-refinement): reduced from the original 3-5 --
# each "rep" is now a full progressive ramp (see BIKE_OPENERS_RAMP_* below),
# not one flat bout, so fewer reps already deliver real race-intensity
# contact; keeping total high-intensity (Z5) exposure minimal fits taper
# theory better (library/24's Bosquet 2007/Mujika & Padilla 2003 citations:
# cut volume/new stress, hold intensity). Coach judgment for the exact
# 2-4 figure -- no source specifies openers rep count.
BIKE_OPENERS_ZONE = "Z4"
# Nominal top-level `Session.intensity["zone"]` for the whole
# openers/primer session -- Z3->Z4->Z5 is a progressive ramp (see below),
# and most of each ramp's time is spent in Z3/Z4, so "Z4" remains the
# honest single-zone label for session-level classification
# (`_session_is_hard_bike`'s `_BIKE_HARD_MIN_ZONE_RANK` already includes Z3-Z5, so
# this choice doesn't change hard-day counting either way).

BIKE_OPENERS_RAMP_Z3_S = 60.0
BIKE_OPENERS_RAMP_Z4_S = 45.0
BIKE_OPENERS_RAMP_Z5_S = 8.0
# Build E (race-week-content-refinement): replaces the old flat "3-5 x
# ~1-2 min @ Z4" repeated-fixed-effort shape with a single progressive
# ramp per rep -- Z3 for BIKE_OPENERS_RAMP_Z3_S, straight into Z4 for
# BIKE_OPENERS_RAMP_Z4_S, straight into a brief Z5 burst for
# BIKE_OPENERS_RAMP_Z5_S -- matching Andrew's own stated real pre-race
# practice verbatim: "typically have ramp of 1 min z3, 45s z4, and <10sec
# z5." `Coach judgment:` for the specific seconds (Andrew's own literal
# numbers; 8s chosen as a defensible value strictly under his stated "<10
# sec" bound for the Z5 tail) -- library/24's own openers subsection
# already establishes the umbrella "keep intensity, cut volume" taper
# principle (Bosquet 2007; Mujika & Padilla 2003) that grounds doing SOME
# race-intensity work here at all; the specific REP SHAPE (ramp vs. the
# old repeated-fixed-bout convention) is coach judgment either way -- this
# is Andrew's own real, live-usage practice, and a brief progressive ramp
# with a very short top-end exposure is, if anything, a MORE minimal total
# high-intensity dose than the old shape (3-5 x 90s @ Z4 = 270-450s of
# sustained low-Z4 work vs. this ramp's 8-32s of actual Z5 across 2-4
# reps), which fits taper theory's "cut load, keep contact" logic at least
# as well. **Test:** if race power/form the week after a ramp-shaped
# openers taper reads flat or worse compared to the old flat-bout shape
# across a few real races, that's the signal to revert the shape (not the
# umbrella taper principle, which stays either way).

BIKE_REST_GAP_CAP_MULTIPLIER = 2.0
# Coach judgment, not citation-backed: `_fit_units_with_flexible_gap` sizes
# the rest after each work bout/block/set to consume whatever main-block
# time is left, which -- verified live this pass by reading the raw
# exported `.zwo` XML, not just a test assertion -- could inflate "recovery
# between reps" to something coaching-nonsensical on a large-volume week
# (25 real minutes of rest after one 7.5-min short-short VO2 set). Each
# template's own rest constant (e.g. BIKE_SHORT_SHORT_SET_REST_S) times
# this multiplier caps how far the gap is allowed to grow; anything beyond
# the cap becomes a trailing "fill remaining time" step instead (still real
# training-adjacent volume, just not mislabeled as inter-rep recovery).

BIKE_INTERVAL_TEMPLATE_META: dict[str, dict[str, str]] = {
    "sustained_threshold": {
        "zone": BIKE_SUSTAINED_THRESHOLD_ZONE,
        "purpose": "sustained threshold intervals (Z4) — lactate-threshold-adjacent, long work bouts",
    },
    "over_unders": {
        "zone": BIKE_OVER_UNDER_OVER_ZONE,
        "purpose": "over/unders (Z3/Z4) — fluctuating lactate production/clearance under alternating load",
    },
    "short_short_vo2": {
        "zone": BIKE_SHORT_SHORT_ZONE,
        "purpose": "short-short VO2 intervals (Z5) — fixed-ratio 30s/15s on/off, VO2-kinetics priming",
    },
    "race_pace": {
        "zone": BIKE_RACE_PACE_ZONE,
        "purpose": "race-pace intervals (Z5) — punchy repeated efforts, race-specificity",
    },
    "openers": {
        "zone": BIKE_OPENERS_ZONE,
        "purpose": (
            "openers — short progressive-ramp race-intensity work "
            "(Z3 build → Z4 → brief Z5 top-end, full recovery between ramps); "
            "low total volume, taper week: this switches from building CTL "
            "to race-ready without adding fatigue"
        ),
    },
}
# Session-level `Session.intensity["zone"]` for the week's hard session is
# set from this table (per selected template), NOT hardcoded "Z3" as it was
# before this pass -- a session whose actual interval content sits at Z4/Z5
# labeled "Z3" at the top level would be a real correctness problem (wrong
# zone/watts bounds via `_bike_intensity`/`zones.bike_zone_table`), worse
# than the flat-block status quo this pass replaces. No production code
# outside this module and its own tests reads `Session.intensity["zone"]`
# to mean specifically "Z3 == the hard session" (verified this pass by
# search) -- the count/duration/is_indoor/taper/strength machinery this
# build must not disturb identifies "hard" structurally (`is_hard`), not by
# zone string.

BIKE_INTERVAL_TEMPLATES: tuple[str, ...] = (
    "sustained_threshold",
    "over_unders",
    "short_short_vo2",
    "race_pace",
    "openers",
)
# The first four are the fixed WEEK-TO-WEEK ROTATION `_select_bike_interval_
# template` cycles through (`_BIKE_ROTATION_TEMPLATES` below) -- library/24
# grounds the four templates themselves but no source specifies a sequencing
# rule across them, so this ordering (longest/least neuromuscularly-taxing
# work bout first, shortest/most taxing last) is this engine's own
# reasonable default (Coach judgment), not a cited cadence.
#
# "openers" (Build A defect 5, engine/week-generator-realism) is NOT part of
# that blind rotation -- it is selected ONLY when a race is within
# `BIKE_OPENERS_PROXIMITY_DAYS` or the week falls in a `"taper"` MacroBlock
# (`_select_bike_interval_template`'s `use_openers`), where it overrides
# whatever the rotation would otherwise pick. Short race-intensity primers,
# low total volume -- see `_bike_openers_main` and library/24's
# "Openers / pre-race primers (taper)" subsection.

def _bike_step(
    label: str,
    role: Literal["warmup", "steady", "cooldown"],
    duration_s: float,
    zone: str,
    ftp_watts: float | None,
) -> WorkoutStep:
    """One leaf `WorkoutStep` for a bike session block -- see
    `_bike_session_structure`'s docstring for the caller. Resolves `zone` to
    a real `WorkoutTarget`: `basis="power_w"` (absolute watts, from
    `zones.bike_zone_table`) once `ftp_watts` is known, else `basis="zone"`
    (the zone name alone, for a device to apply its own configured power
    zone) -- the same graceful partial-data convention
    `_bike_week_sessions`'s own `Session.intensity` dict already uses for
    exactly this None-vs-known-FTP split.
    """
    if ftp_watts is not None:
        zone_row = bike_zone_table(ftp_watts)[zone]
        watts_lo, watts_hi = zone_row["watts_lo"], zone_row["watts_hi"]
        target = WorkoutTarget(basis="power_w", low=watts_lo, high=watts_hi)
        watts_txt = f"{round(watts_lo)}-{round(watts_hi)}W" if watts_hi is not None else f">{round(watts_lo)}W"
        zone_txt = f"{zone} ({watts_txt})"
    else:
        target = WorkoutTarget(basis="zone", zone=zone)
        zone_txt = zone
    return WorkoutStep(
        label=f"{label} -- {zone_txt}",
        role=role,
        duration_kind="time_s",
        duration_value=duration_s,
        target=target,
        modality="bike",
    )


def _bike_warmup_cooldown_reserve(duration_min: float) -> tuple[float, float, float]:
    """(warmup_s, cooldown_s, main_s) reservation shared by every bike
    session-structure builder (`_bike_session_structure` and
    `_bike_hard_session_structure` below) -- factored out so both use
    identical warm-up/cool-down math rather than two copies that could
    silently drift. Below `BIKE_MIN_MAIN_BLOCK_S` of main-block time after
    reserving `BIKE_WARMUP_COOLDOWN_MIN` on each side, both are dropped and
    the whole session becomes one continuous block (see those constants).
    """
    total_s = round(duration_min * 60)
    warmup_s = round(min(BIKE_WARMUP_COOLDOWN_MIN, duration_min / 4) * 60)
    cooldown_s = round(min(BIKE_WARMUP_COOLDOWN_MIN, duration_min / 4) * 60)
    main_s = total_s - warmup_s - cooldown_s
    if main_s < BIKE_MIN_MAIN_BLOCK_S:
        warmup_s, cooldown_s, main_s = 0, 0, total_s
    return warmup_s, cooldown_s, main_s


def _bike_session_structure(zone: str, duration_min: float, ftp_watts: float | None) -> WorkoutStructure:
    """Warm-up / main-block / cool-down `WorkoutStructure` for one FLAT
    (single continuous zone) bike session -- the real structured content
    `models.WorkoutStep`'s own "bike" modality comment flagged as deferred
    when Part B of this build shipped ("no cycling WorkoutSteps are
    actually constructed by this build"); this was that follow-up
    (engine/cycling-coach Part C, delivery/logging).

    **Scope, post interval-template pass:** this function still generates
    every EASY (Z2 endurance) bike session's content, and the final-taper
    week's floor content (`_bike_final_taper_sessions`) -- both genuinely
    are meant to be one flat steady block, not an interval session. The
    week's differentiated HARD session no longer uses this function -- see
    `_bike_hard_session_structure` and `_select_bike_interval_template`
    for the four real interval templates (library/24-cycling-
    periodization-intervals.md) that replaced the single flat block this
    function's own docstring used to flag as a known, documented
    limitation (PR #167 red-team review; that finding contradicted
    `library/23-cycling-training.md`'s Protzen et al. 2026 warning that
    MTB/CX sessions need surge/interval-shaped content, not steady-state).

    NOTE for any future caller: unlike swim's `basis="zone"` targets, a
    bike `basis="zone"` target here must NEVER be run through
    `workout_templates.resolve_template` -- that function's `_resolve_target`
    unconditionally resolves `basis="zone"` via the CSS-anchored swim
    `zones.zone_table`, which would silently reinterpret a bike power zone
    as a swim pace. This function already returns fully resolved content
    (either `basis="power_w"` or an intentionally-unresolved-but-device-
    understood `basis="zone"`, same as swim's own zone-basis targets can be
    left directly Garmin-exportable -- see `garmin_export`'s
    `test_zone_basis_target_uses_speed_zone`), so it must never be passed to
    `resolve_template`.
    """
    warmup_s, cooldown_s, main_s = _bike_warmup_cooldown_reserve(duration_min)

    items: list[WorkoutStep] = []
    if warmup_s > 0:
        items.append(_bike_step("Warm-up, easy spin", "warmup", warmup_s, "Z1", ftp_watts))
    items.append(_bike_step("Main set: steady ride", "steady", main_s, zone, ftp_watts))
    if cooldown_s > 0:
        items.append(_bike_step("Cool-down, easy spin", "cooldown", cooldown_s, "Z1", ftp_watts))
    return WorkoutStructure(items=items)


def _fit_units_with_flexible_gap(
    main_s: float, unit_s: float, min_units: int, max_units: int, max_gap_s: float
) -> tuple[int, float, float]:
    """Pick the largest repeat count in `[min_units, max_units]` whose
    fixed, citation-grounded `unit_s` (one work bout, or one whole
    block/set) fits `count` times within `main_s`; falls back below
    `min_units` (down to 1) when even the minimum doesn't fit -- same
    low-volume graceful-degradation posture `_resolve_bike_session_count`
    already established elsewhere in this module, rather than emitting a
    malformed/overflowing structure.

    Returns `(count, gap_s, trailing_s)`. The gap (rest after each unit,
    including the last -- see below) is NOT one of this template's fixed
    constants -- it's sized to consume main-block time left after `count`
    full units, capped at `max_gap_s` so a large weekly volume can't
    inflate "recovery between reps" into something coaching-nonsensical
    (verified live this pass: an uncapped version put 25 REAL minutes of
    rest after a 7.5-min short-short VO2 set on a 300-min-total week's hard
    session -- read straight from the exported `.zwo` XML, not just a test
    assertion). Whatever time the cap can't absorb becomes `trailing_s`, a
    single fill step the caller appends before cool-down instead (still
    real training-adjacent volume, just not disguised as "recovery between
    reps"). `count * (unit_s + gap_s) + trailing_s` always equals `main_s`
    exactly.

    Gap applies AFTER EVERY UNIT, including the last one -- matches the
    actual semantics of `WorkoutRepeat(repeat_mode="count", steps=[work,
    rest])`, which unconditionally loops the full 2-step pattern `count`
    times with no special "omit the final rest" case (also `zwo_export`'s
    own `IntervalsT` conversion: `Repeat=count` cycles of `OnDuration`/
    `OffDuration`, always including the final off). `count == 1` returns
    `gap_s = 0.0` and folds all leftover main-block time into `trailing_s`.
    """
    count = max_units
    while count > min_units and count * unit_s > main_s:
        count -= 1
    if count * unit_s > main_s:
        count = 1
    if count <= 1:
        return count, 0.0, max(0.0, main_s - unit_s * count)
    ideal_gap_s = main_s / count - unit_s
    gap_s = max(0.0, min(ideal_gap_s, max_gap_s))
    trailing_s = main_s - count * (unit_s + gap_s)
    return count, gap_s, trailing_s


def _bike_open_header(label: str) -> WorkoutStep:
    """One athlete-facing, non-structural "section header" line -- same
    `role="open"`/`duration_kind="open"` convention
    `_strength_session_structure_template` already established (verbatim
    prose carried on a step, not real workout structure -- see
    `WorkoutStep`'s own docstring and `render_prose`). `duration_value`
    stays `None`, so this never contributes to a session's total structured
    duration. Used here so every hard bike session's rendered prose still
    contains a "Main set: ..." line (matching the pre-existing invariant
    `_bike_session_structure`'s flat block always produced) even though the
    real content underneath is now a `WorkoutRepeat`, not one flat step.
    """
    return WorkoutStep(label=label, role="open", duration_kind="open", modality="bike")


def _bike_reps_with_rest_main(
    main_set_label: str,
    work_label: str,
    work_zone: str,
    work_s: float,
    rest_label: str,
    min_reps: int,
    max_reps: int,
    max_gap_s: float,
    main_s: float,
    ftp_watts: float | None,
) -> list[WorkoutStepOrRepeat]:
    """Main-block content for a template shaped as N reps of one fixed
    work bout with rest between reps (sustained threshold, race-pace) --
    a single `WorkoutRepeat(repeat_mode="count", ...)` wrapping exactly
    two leaf steps (work, rest), the same on/off-pair shape
    `zwo_export._convert_repeat` already supports for `IntervalsT`. Falls
    back to a flat single block (this template's own zone) when `main_s`
    can't even fit one work bout -- see `_fit_units_with_flexible_gap`
    (including for `max_gap_s`, the cap on how large "recovery between
    reps" is allowed to grow before the remainder becomes a trailing fill
    step instead).
    """
    if main_s < work_s:
        return [_bike_step("Main set: steady ride", "steady", main_s, work_zone, ftp_watts)]
    count, gap_s, trailing_s = _fit_units_with_flexible_gap(main_s, work_s, min_reps, max_reps, max_gap_s)
    work_min = round(work_s / 60, 1)
    if count == 1:
        header = _bike_open_header(f"Main set: {main_set_label} — 1 x {work_min} min @ {work_zone}")
        items: list[WorkoutStepOrRepeat] = [
            header,
            _bike_step(work_label, "interval", work_s, work_zone, ftp_watts),
        ]
        if trailing_s > 0:
            items.append(_bike_step("Easy spin, fill remaining time", "recovery", trailing_s, "Z1", ftp_watts))
        return items
    rest_min = round(gap_s / 60, 1)
    header = _bike_open_header(
        f"Main set: {main_set_label} — {count} x {work_min} min @ {work_zone}, "
        f"~{rest_min} min recovery between reps"
    )
    items = [
        header,
        WorkoutRepeat(
            repeat_mode="count",
            count=count,
            steps=[
                _bike_step(work_label, "interval", work_s, work_zone, ftp_watts),
                _bike_step(rest_label, "recovery", gap_s, "Z1", ftp_watts),
            ],
        ),
    ]
    if trailing_s > 0:
        items.append(_bike_step("Easy spin, fill remaining time", "recovery", trailing_s, "Z1", ftp_watts))
    return items


def _bike_blocks_with_rest_main(
    main_set_label: str,
    build_unit: Callable[[], WorkoutRepeat],
    unit_s: float,
    unit_label: str,
    fallback_zone: str,
    min_units: int,
    max_units: int,
    max_gap_s: float,
    main_s: float,
    ftp_watts: float | None,
    inter_unit_rest_label: str,
) -> list[WorkoutStepOrRepeat]:
    """Main-block content for a template shaped as N repetitions of a
    fixed, INTERNALLY-STRUCTURED unit (over/unders' 6-min on/off block,
    short-short's 7.5-min 10x30/15 set) with rest after each unit -- unlike
    `_bike_reps_with_rest_main`, each unit is itself a `WorkoutRepeat`
    (`build_unit()`), so the returned list is flat top-level items
    (unit-repeat, rest-step, unit-repeat, rest-step, ...) rather than one
    nested repeat -- `zwo_export`'s `IntervalsT` conversion only supports a
    single level of repeat nesting, so keeping every `WorkoutRepeat` at the
    top level (never nested inside another) is deliberate, not an
    oversight. A rest step follows EVERY unit, including the last one
    (leading into cool-down) -- matches `_fit_units_with_flexible_gap`'s own
    `count * (unit_s + gap_s) + trailing_s == main_s` contract, the same
    trailing-gap convention `_bike_reps_with_rest_main`'s single
    `WorkoutRepeat` already has no way to avoid. `max_gap_s` caps the
    rest-after-each-unit duration (any excess main-block time becomes one
    trailing fill step instead of an unrealistically long "recovery"
    label -- see `_fit_units_with_flexible_gap`'s own comment for the real
    bug this closes). Falls back to a flat single block when `main_s`
    can't even fit one whole unit -- see `_fit_units_with_flexible_gap`.
    """
    if main_s < unit_s:
        return [_bike_step("Main set: steady ride", "steady", main_s, fallback_zone, ftp_watts)]
    count, gap_s, trailing_s = _fit_units_with_flexible_gap(main_s, unit_s, min_units, max_units, max_gap_s)
    rest_min = round(gap_s / 60, 1)
    header_text = (
        f"Main set: {main_set_label} — {count} x {unit_label}"
        + (f", ~{rest_min} min recovery after each {inter_unit_rest_label.rsplit(' ', 1)[-1][:-1]}" if count > 1 else "")
    )
    items: list[WorkoutStepOrRepeat] = [_bike_open_header(header_text)]
    for _ in range(count):
        items.append(build_unit())
        if count > 1:
            items.append(_bike_step(inter_unit_rest_label, "recovery", gap_s, "Z1", ftp_watts))
    if trailing_s > 0:
        items.append(_bike_step("Easy spin, fill remaining time", "recovery", trailing_s, "Z1", ftp_watts))
    return items


def _bike_sustained_threshold_main(main_s: float, ftp_watts: float | None) -> list[WorkoutStepOrRepeat]:
    """library/24 "Sustained threshold": 2-3 reps of an 8-12 min work bout
    (~91-100% FTP, Z4) with near-full recovery between reps."""
    return _bike_reps_with_rest_main(
        "sustained threshold intervals",
        "Threshold interval",
        BIKE_SUSTAINED_THRESHOLD_ZONE,
        BIKE_SUSTAINED_THRESHOLD_WORK_S,
        "Recovery between reps",
        BIKE_SUSTAINED_THRESHOLD_MIN_REPS,
        BIKE_SUSTAINED_THRESHOLD_MAX_REPS,
        BIKE_SUSTAINED_THRESHOLD_REST_S * BIKE_REST_GAP_CAP_MULTIPLIER,
        main_s,
        ftp_watts,
    )


def _bike_race_pace_main(main_s: float, ftp_watts: float | None) -> list[WorkoutStepOrRepeat]:
    """library/24 "Race-pace / long VO2": 3-5 reps of a 2-3 min work bout
    (~105-114% FTP, approximated Z5) with near-full recovery between reps."""
    return _bike_reps_with_rest_main(
        "race-pace intervals",
        "Race-pace interval",
        BIKE_RACE_PACE_ZONE,
        BIKE_RACE_PACE_WORK_S,
        "Recovery between reps",
        BIKE_RACE_PACE_MIN_REPS,
        BIKE_RACE_PACE_MAX_REPS,
        BIKE_RACE_PACE_REST_S * BIKE_REST_GAP_CAP_MULTIPLIER,
        main_s,
        ftp_watts,
    )


def _bike_over_unders_main(main_s: float, ftp_watts: float | None) -> list[WorkoutStepOrRepeat]:
    """library/24 "Over/unders": 2-4 blocks per session, each block a
    fixed `BIKE_OVER_UNDER_CYCLES_PER_BLOCK` x (90s over ~100-105% FTP /
    90s under ~76-85% FTP) alternation, with recovery between blocks."""
    block_s = BIKE_OVER_UNDER_CYCLES_PER_BLOCK * (BIKE_OVER_UNDER_ON_S + BIKE_OVER_UNDER_OFF_S)

    def _build_block() -> WorkoutRepeat:
        return WorkoutRepeat(
            repeat_mode="count",
            count=BIKE_OVER_UNDER_CYCLES_PER_BLOCK,
            steps=[
                _bike_step("Over — supra-threshold", "interval", BIKE_OVER_UNDER_ON_S, BIKE_OVER_UNDER_OVER_ZONE, ftp_watts),
                _bike_step("Under — sub-threshold", "interval", BIKE_OVER_UNDER_OFF_S, BIKE_OVER_UNDER_UNDER_ZONE, ftp_watts),
            ],
        )

    return _bike_blocks_with_rest_main(
        "over/unders",
        _build_block,
        block_s,
        f"{BIKE_OVER_UNDER_CYCLES_PER_BLOCK} x 90s/90s over/under block",
        BIKE_OVER_UNDER_OVER_ZONE,
        BIKE_OVER_UNDER_MIN_BLOCKS,
        BIKE_OVER_UNDER_MAX_BLOCKS,
        BIKE_OVER_UNDER_BLOCK_REST_S * BIKE_REST_GAP_CAP_MULTIPLIER,
        main_s,
        ftp_watts,
        "Recovery between blocks",
    )


def _bike_short_short_main(main_s: float, ftp_watts: float | None) -> list[WorkoutStepOrRepeat]:
    """library/24 "Short-short (VO2)": 1-2 sets of `BIKE_SHORT_SHORT_
    REPS_PER_SET` x (30s on ~106-118% FTP / 15s off) fixed-ratio reps, with
    recovery between sets."""
    set_s = BIKE_SHORT_SHORT_REPS_PER_SET * (BIKE_SHORT_SHORT_ON_S + BIKE_SHORT_SHORT_OFF_S)

    def _build_set() -> WorkoutRepeat:
        return WorkoutRepeat(
            repeat_mode="count",
            count=BIKE_SHORT_SHORT_REPS_PER_SET,
            steps=[
                _bike_step("Short-short ON", "interval", BIKE_SHORT_SHORT_ON_S, BIKE_SHORT_SHORT_ZONE, ftp_watts),
                _bike_step("Short-short OFF", "recovery", BIKE_SHORT_SHORT_OFF_S, "Z1", ftp_watts),
            ],
        )

    return _bike_blocks_with_rest_main(
        "short-short VO2 intervals",
        _build_set,
        set_s,
        f"{BIKE_SHORT_SHORT_REPS_PER_SET} x 30s/15s set",
        BIKE_SHORT_SHORT_ZONE,
        BIKE_SHORT_SHORT_MIN_SETS,
        BIKE_SHORT_SHORT_MAX_SETS,
        BIKE_SHORT_SHORT_SET_REST_S * BIKE_REST_GAP_CAP_MULTIPLIER,
        main_s,
        ftp_watts,
        "Recovery between sets",
    )


def _bike_openers_ramp_unit(ftp_watts: float | None) -> WorkoutRepeat:
    """One progressive-ramp "rep": Z3 for `BIKE_OPENERS_RAMP_Z3_S`, straight
    into Z4 for `BIKE_OPENERS_RAMP_Z4_S`, straight into a brief Z5 burst
    for `BIKE_OPENERS_RAMP_Z5_S` -- Andrew's own real pre-race-openers
    practice (see `BIKE_OPENERS_RAMP_*`'s own comment). Wrapped in a
    `count=1` `WorkoutRepeat` (not three loose top-level steps) so
    `_bike_blocks_with_rest_main` can treat it as one atomic "unit" the
    same way `_bike_over_unders_main`/`_bike_short_short_main` already
    wrap their own internally-structured units."""
    return WorkoutRepeat(
        repeat_mode="count",
        count=1,
        steps=[
            _bike_step("Ramp — Z3 build", "interval", BIKE_OPENERS_RAMP_Z3_S, "Z3", ftp_watts),
            _bike_step("Ramp — Z4", "interval", BIKE_OPENERS_RAMP_Z4_S, "Z4", ftp_watts),
            _bike_step("Ramp — Z5 (brief top-end)", "interval", BIKE_OPENERS_RAMP_Z5_S, "Z5", ftp_watts),
        ],
    )


def _bike_openers_main(main_s: float, ftp_watts: float | None) -> list[WorkoutStepOrRepeat]:
    """library/24 "Openers / pre-race primers (taper)": `BIKE_OPENERS_MIN_
    REPS`-`BIKE_OPENERS_MAX_REPS` progressive ramps (`_bike_openers_ramp_
    unit` -- Z3 -> Z4 -> brief Z5), full recovery between ramps. Build E
    (race-week-content-refinement) rewrite of the original flat "N x fixed
    ~1-2 min @ Z4" shape -- see `BIKE_OPENERS_RAMP_*`'s own comment for why.
    Selected on a taper/pre-race week where the WEEKLY VOLUME is also
    pulled down (`BIKE_TAPER_INTENSITY_VOLUME_REDUCTION`), so the total
    load is low even though the ramps themselves touch race-intensity.
    Build A defect 5, engine/week-generator-realism; ramp shape Build E."""
    unit_s = BIKE_OPENERS_RAMP_Z3_S + BIKE_OPENERS_RAMP_Z4_S + BIKE_OPENERS_RAMP_Z5_S
    return _bike_blocks_with_rest_main(
        "openers (pre-race primers, progressive ramp)",
        lambda: _bike_openers_ramp_unit(ftp_watts),
        unit_s,
        f"ramp ({BIKE_OPENERS_RAMP_Z3_S:.0f}s Z3 / {BIKE_OPENERS_RAMP_Z4_S:.0f}s Z4 / "
        f"{BIKE_OPENERS_RAMP_Z5_S:.0f}s Z5)",
        BIKE_OPENERS_ZONE,
        BIKE_OPENERS_MIN_REPS,
        BIKE_OPENERS_MAX_REPS,
        BIKE_OPENERS_REST_S * BIKE_REST_GAP_CAP_MULTIPLIER,
        main_s,
        ftp_watts,
        "Full recovery between ramps",
    )


_BIKE_INTERVAL_TEMPLATE_BUILDERS = {
    "sustained_threshold": _bike_sustained_threshold_main,
    "over_unders": _bike_over_unders_main,
    "short_short_vo2": _bike_short_short_main,
    "race_pace": _bike_race_pace_main,
    "openers": _bike_openers_main,
}


def _bike_hard_session_structure(
    template: str, duration_min: float, ftp_watts: float | None
) -> WorkoutStructure:
    """Warm-up / interval-template main-block / cool-down `WorkoutStructure`
    for the week's differentiated HARD bike session -- the real,
    repeat-shaped replacement for the flat single block
    `_bike_session_structure` used to generate for every bike session
    (PR #167 red-team review finding; see that function's own docstring).
    `template` is one of `BIKE_INTERVAL_TEMPLATES`
    (`_select_bike_interval_template` picks which one for a given week).
    Same warm-up/cool-down reservation as `_bike_session_structure`
    (`_bike_warmup_cooldown_reserve`) -- only the main-block content
    differs.
    """
    if template not in _BIKE_INTERVAL_TEMPLATE_BUILDERS:
        raise ValueError(f"unknown bike interval template: {template!r}")
    warmup_s, cooldown_s, main_s = _bike_warmup_cooldown_reserve(duration_min)

    items: list[WorkoutStepOrRepeat] = []
    if warmup_s > 0:
        items.append(_bike_step("Warm-up, easy spin", "warmup", warmup_s, "Z1", ftp_watts))
    items.extend(_BIKE_INTERVAL_TEMPLATE_BUILDERS[template](main_s, ftp_watts))
    if cooldown_s > 0:
        items.append(_bike_step("Cool-down, easy spin", "cooldown", cooldown_s, "Z1", ftp_watts))
    return WorkoutStructure(items=items)


# --- Ramp test (threshold-history build) -- real FTP-from-scratch test ------
#
# Andrew's own framing, explicitly (this build's design session): the 2x12min
# "threshold check" embedded in his real block-01 (`_bike_sustained_threshold_
# main`/the FTP-check purpose-text note below) is a heuristic appropriate ONLY
# because his FTP is already reasonably well-known -- it is NOT a substitute
# for a real ramp test when no current reading exists. This section is that
# separate, real path: a from-scratch or from-reset FTP-establishing test,
# not a fitness-check bolted onto an ordinary training session.
#
# Protocol grounding (WebSearch-verified this session, direct-fetch confirmed
# against cyclecoach.com -- Ric Stern's own site -- and roadmancycling.com;
# see library/24-cycling-periodization-intervals.md's "Ramp test protocol and
# FTP formula" section for the full citation writeup and Confidence/Test
# lines). This is NOT a peer-reviewed journal citation -- it is cited here,
# and in library/24, as a genuine practical/non-journal resource (this
# project's own reference_list.md "Practical / non-journal resources"
# category), same tier as e.g. the TrainingPeaks swim-TSS citation already
# grounding `load.py`'s SWIM_TSS_INTENSITY_EXPONENT.
BIKE_RAMP_TEST_WARMUP_MIN = 5.0
# Coach judgment, not citation-backed -- roadmancycling.com's own protocol
# description says only "a few minutes of easy spinning," no exact figure.
BIKE_RAMP_TEST_START_WATTS_DEFAULT = 100.0
# roadmancycling.com (direct-fetch confirmed): "a common structure starts
# around 100W" -- the no-current-FTP-reading default (see design section 6:
# "start around 50% FTP (or a fixed low wattage)").
BIKE_RAMP_TEST_START_FRACTION_OF_FTP = 0.50
# Same source's "(or roughly 50% of estimated FTP)" alternative -- used
# instead of the fixed 100W default whenever a prior (even if stale)
# ftp_watts reading exists, so the ramp starts at a realistic intensity
# for THIS athlete rather than an arbitrary population default.
BIKE_RAMP_TEST_STEP_WATTS_PER_MIN = 20.0
# roadmancycling.com (direct-fetch confirmed): "adds 20W per minute" --
# also matches TrainerRoad/Zwift's own widely-used ramp-test step rate.
BIKE_RAMP_TEST_DURATION_MIN = 20.0
# The real protocol is discrete (a new 1-minute stage every minute until
# voluntary failure, typically "8-25 minutes including the build" per the
# same source) -- ZWO's `<Ramp>` element is a single CONTINUOUS linear
# power ramp over a fixed duration, not a sequence of 1-minute steps. 20
# minutes is this engine's own reasonable fixed-duration approximation
# (Coach judgment: the middle of that observed 8-25 min range) delivering a
# real, close-enough-to-linear approximation of the discrete step protocol
# for a trainer app to render -- an athlete who fails before reaching the
# ramp's end simply stops the workout early, same as the real discrete
# protocol's own "ride until you can't hold the target" termination rule.
# `end_watts` is deliberately set high enough that most athletes will fail
# well before reaching it (a real ceiling, not a target to complete).
BIKE_RAMP_TEST_FTP_FROM_BEST_1MIN_FRACTION = 0.75
# Ric Stern's own quantified MAP-to-threshold-power relationship
# (cyclecoach.com, direct-fetch confirmed this session): "the ramp test
# takes 75% of your best one-minute power to estimate FTP," within a
# documented ~72-77% individual-variation range. See library/24 for the
# full writeup -- Confidence: medium (a real, named practitioner-expert's
# own quantified figure, cross-confirmed across multiple independently
# direct-fetched sources this session, but NOT a peer-reviewed journal
# study -- this project's evidence-tagging scheme reserves [EVIDENCE]/
# [ADAPTED] for actual research papers; this is graded as a genuine
# practical/non-journal resource instead, same tier as the TrainingPeaks
# swim-TSS citation already used elsewhere in this engine).


def _bike_ramp_test_structure(ftp_watts: float | None) -> WorkoutStructure:
    """A real, from-scratch (or from-reset) FTP-establishing ramp test --
    warm-up, then a single continuous power ramp (role="ramp", the
    threshold-history build's new `WorkoutStep.role` value -- see that
    field's own comment) climbing at `BIKE_RAMP_TEST_STEP_WATTS_PER_MIN`
    from a realistic starting point to a real, rarely-reached ceiling. This
    is genuinely different from `_bike_hard_session_structure`'s
    "sustained_threshold" template -- that's an ordinary training session
    that ALSO happens to double as a rough fitness check (see this
    module's FTP-check purpose-text note in `_bike_week_sessions`); this
    function is a dedicated, standalone test session whose entire point is
    establishing (or resetting) the athlete's FTP anchor from real data,
    for when no current reading exists at all (design section 6's explicit
    "different situations, not competing designs" framing).

    The athlete pedals until failure, then reports back their best 1-minute
    average power (either read directly off their own device/app, or via
    the ride file this session's `.zwo`/Garmin export produces); the coach
    computes FTP with `ftp_from_ramp_test` below and offers to log it via
    `record_threshold_test(source="ramp_test")` +
    `update_athlete_profile`. Deliverable via the exact same ZWO/Garmin
    export pipeline as any other bike session (`zwo_export.to_zwo_workout`/
    `garmin_export`) -- no new delivery mechanism, matching design section
    6's own framing ("just a real, available one" path, not swim-coach's
    only one).

    `ftp_watts`, when known (even a stale/estimated prior reading -- this
    function does NOT check its source/age, that judgment belongs to the
    CALLER deciding whether a ramp test is warranted at all), anchors the
    start point closer to the athlete's real range
    (`BIKE_RAMP_TEST_START_FRACTION_OF_FTP`); `None` (the genuinely
    from-scratch case this function exists for) falls back to
    `BIKE_RAMP_TEST_START_WATTS_DEFAULT`. No cool-down step is appended --
    `zwo_export.to_zwo_workout`'s own trailing-cool-down fallback covers
    delivery, and a real ramp test ends at voluntary failure, not a planned
    duration, so appending a fixed cool-down here would misrepresent the
    main block as something the athlete completes on schedule.
    """
    warmup_s = round(BIKE_RAMP_TEST_WARMUP_MIN * 60)
    ramp_s = round(BIKE_RAMP_TEST_DURATION_MIN * 60)
    start_watts = (
        ftp_watts * BIKE_RAMP_TEST_START_FRACTION_OF_FTP
        if ftp_watts is not None
        else BIKE_RAMP_TEST_START_WATTS_DEFAULT
    )
    end_watts = start_watts + BIKE_RAMP_TEST_STEP_WATTS_PER_MIN * BIKE_RAMP_TEST_DURATION_MIN

    items: list[WorkoutStepOrRepeat] = [
        _bike_step("Warm-up, easy spin", "warmup", warmup_s, "Z1", ftp_watts),
        WorkoutStep(
            label=(
                f"Ramp to failure -- start ~{round(start_watts)}W, "
                f"+{round(BIKE_RAMP_TEST_STEP_WATTS_PER_MIN)}W/min until you can no "
                "longer hold the target"
            ),
            role="ramp",
            duration_kind="time_s",
            duration_value=ramp_s,
            target=WorkoutTarget(basis="power_w", low=start_watts, high=end_watts),
            modality="bike",
        ),
    ]
    return WorkoutStructure(items=items)


def ftp_from_ramp_test(best_1min_power_w: float) -> float:
    """FTP estimate from a completed ramp test's best 1-minute average
    power -- `BIKE_RAMP_TEST_FTP_FROM_BEST_1MIN_FRACTION` (75%, Ric Stern's
    own quantified MAP-to-threshold figure) applied directly. See this
    module's ramp-test constants block above for the full citation. Pure
    arithmetic -- the caller is responsible for actually obtaining
    `best_1min_power_w` (from the athlete's own device/app reading, or a
    ride-file analysis this build does not itself implement)."""
    return round(best_1min_power_w * BIKE_RAMP_TEST_FTP_FROM_BEST_1MIN_FRACTION, 1)


# --- 2x20 test (Build F) -- real two-effort field test, coach content ------
#
# The real defect this build fixes: a real "2x20 FTP test" was handed to the
# athlete as Wednesday's session, but the coach hand-authored it with a fixed
# `WorkoutTarget(basis="power_w", low=X, high=Y)` -- prescribing a target
# power to HOLD, which is what an ordinary training session does, not what a
# genuine TEST does. A test's entire point is measuring the athlete's real,
# currently-unknown ceiling; pre-setting the power band the athlete paces to
# quietly turns the test into a training session and defeats the reason it
# was called for in the first place. This section gives the coach a real,
# correctly-shaped 2x20 protocol to prescribe instead of hand-inventing one
# -- `record_threshold_test`'s `source="field_test"` enum value already
# names "a 20-min FTP test" as exactly this case (backend/app/tools.py).
#
# Protocol grounding (WebSearch + direct-fetch verified this session; see
# library/28-bike-ftp-test-protocols.md for the full citation writeup and
# Confidence/Test lines). Same "practical/non-journal resource" tier as this
# module's own ramp-test citations just above -- NOT a peer-reviewed journal
# citation.
BIKE_2X20_TEST_WARMUP_MIN = 10.0
# TrainerDay's own purpose-built "TEST 2x20 FTP Intervals" workout template
# (direct-fetch confirmed this session): 10 min warm-up.
BIKE_2X20_TEST_EFFORT_MIN = 20.0
# The defining duration of this protocol -- two 20-minute maximal efforts.
BIKE_2X20_TEST_RECOVERY_MIN = 10.0
# TrainerDay's same template's 10-minute recovery between the two efforts --
# also matches the real, independently documented CTS/TrainerRoad two-effort
# (8-minute) FTP test's own 10-minute recovery convention (trainright.com,
# Chris Carmichael/CTS -- direct-fetch confirmed this session): convergent
# across two independent real dual-effort test protocols, not just one
# source. (A third source, an Endurance Nation-attributed forum description,
# instead used a 2-minute recovery -- noted in library/28 as a real,
# divergent variant NOT adopted here, in favor of the two-source-convergent
# 10-minute figure.)
BIKE_2X20_TEST_COOLDOWN_MIN = 15.0
# Same TrainerDay template's own trailing cool-down.
BIKE_2X20_TEST_EFFORT_RPE = 9.0
# `WorkoutTarget(basis="rpe")` value for both work efforts -- deliberately
# NOT a power/zone target (see this section's own header comment; this is
# this build's entire reason for existing). 9, not 10, on library/19-srpe-
# protocol.md's own modified-Borg-CR-10 scale (0-10, "10 = Maximal /
# Exhausting"): a real, sustained-for-20-minutes maximal effort is hard but
# not the single-point instantaneous exhaustion "10" describes -- `Coach
# judgment` for the exact number (9 is itself unanchored in Foster's own
# instrument, library/19), the athlete-facing step label carries the real
# instruction ("your honest hardest sustainable pace for the full 20
# minutes") rather than leaning on the number alone.
BIKE_2X20_TEST_FTP_FROM_AVG_FRACTION = 0.95
# Allen & Coggan's well-established single-20-minute-effort convention
# (already cited in this module's ramp-test section above, and in
# `23-cycling-training.md`/`reference_list.md` for the same book's zone/TSS
# content) applied here to the AVERAGE of both 20-minute efforts' own
# average power. `Coach judgment` for combining two efforts this way
# specifically -- no single authoritative source states a 2x20-specific
# formula; this extends the well-established single-effort 0.95 convention
# the same way trainright.com's own documented "apps" convention combines
# the CTS 8-minute test's two efforts (average-then-discount), rather than
# the alternative CTS-coach convention of taking only the higher effort --
# see `ftp_from_2x20_test`'s own docstring and library/28 for the full
# writeup.


def _bike_2x20_test_structure(ftp_watts: float | None) -> WorkoutStructure:
    """A real, standalone two-effort FTP test -- warm-up, a 20-minute
    maximal effort, an easy recovery spin, a second 20-minute maximal
    effort, cool-down, a trailing `role="open"` "Why:" pacing note. See
    this module's own 2x20-test header comment above for the real defect
    this fixes, and `ftp_from_2x20_test` below for the matching formula.

    **Critical, the whole point of this function:** both 20-minute work
    steps carry `WorkoutTarget(basis="rpe", ...)` -- NEVER `basis="power_w"`
    or `basis="zone"`. A genuine FTP test measures the athlete's real,
    currently-unknown ceiling; a fixed power/zone band would instead be
    something the athlete paces TO, which is what an ordinary training
    session does. This mirrors `_skills_session_structure`'s own
    `basis="rpe"` drill blocks -- the same "no power/zone target on a
    genuinely effort-anchored block" convention already established
    elsewhere in this module for bike sessions.

    `ftp_watts`, when known, only ever anchors the warm-up/recovery/cool-
    down steps (via `_bike_step`'s existing Z1-zone resolution, the same
    easy-spin convention every other recovery/rest step in this module
    already uses) -- never the two work efforts themselves, which is the
    whole point. Deliverable via the exact same ZWO/Garmin export pipeline
    as any other bike session -- an `rpe`-basis step with no power target
    already degrades gracefully to a `<FreeRide>`/untargeted step on both
    exporters (see `zwo_export._leaf_power_fractions`/
    `garmin_export._apply_target`), so no export-side change was needed for
    this build; see `test_bike_2x20_test_structure_exports_cleanly_via_zwo`/
    `..._garmin_fit`.
    """
    warmup_s = round(BIKE_2X20_TEST_WARMUP_MIN * 60)
    effort_s = round(BIKE_2X20_TEST_EFFORT_MIN * 60)
    recovery_s = round(BIKE_2X20_TEST_RECOVERY_MIN * 60)
    cooldown_s = round(BIKE_2X20_TEST_COOLDOWN_MIN * 60)
    effort_target = WorkoutTarget(basis="rpe", low=BIKE_2X20_TEST_EFFORT_RPE, high=BIKE_2X20_TEST_EFFORT_RPE)

    def _effort_step(n: int) -> WorkoutStep:
        return WorkoutStep(
            label=(
                f"Effort {n} of 2 -- 20 min, RPE {BIKE_2X20_TEST_EFFORT_RPE:.0f} -- "
                "your honest hardest sustainable pace for the full 20 "
                "minutes; ride to how you feel, do NOT pace to a power number"
            ),
            role="interval",
            duration_kind="time_s",
            duration_value=effort_s,
            target=effort_target,
            modality="bike",
        )

    items: list[WorkoutStepOrRepeat] = [
        _bike_step("Warm-up, easy spin build", "warmup", warmup_s, "Z1", ftp_watts),
        _effort_step(1),
        _bike_step("Easy spin recovery between efforts", "recovery", recovery_s, "Z1", ftp_watts),
        _effort_step(2),
        _bike_step("Cool-down, easy spin", "cooldown", cooldown_s, "Z1", ftp_watts),
        WorkoutStep(
            label=(
                "Why: a genuine FTP test measures your real ceiling -- "
                "prescribing a power target to hold would just be another "
                "training session in a test's clothing. Start controlled, "
                "don't blow up in the first 5 minutes, then hold the "
                "hardest honest pace you can for the rest of each 20 "
                "minutes (TrainerRoad's own FTP-test pacing guidance, "
                "library/28)."
            ),
            role="open",
            duration_kind="open",
            modality="bike",
        ),
    ]
    return WorkoutStructure(items=items)


def ftp_from_2x20_test(avg_w_1: float, avg_w_2: float) -> float:
    """FTP estimate from a completed 2x20 test's two average-power readings
    -- `BIKE_2X20_TEST_FTP_FROM_AVG_FRACTION` (0.95, Allen & Coggan's own
    single-20-minute-effort convention) applied to the AVERAGE of both
    efforts' own average power. See this module's 2x20-test constants block
    above for the full citation and the Coach-judgment reasoning behind
    averaging the two efforts (rather than taking only the higher one, a
    real documented alternative convention -- see library/28). Pure
    arithmetic -- the caller is responsible for actually obtaining
    `avg_w_1`/`avg_w_2` (read directly off the athlete's own device/app, or
    a ride-file analysis this build does not itself implement) -- same
    shape as `ftp_from_ramp_test` above.
    """
    return round(((avg_w_1 + avg_w_2) / 2) * BIKE_2X20_TEST_FTP_FROM_AVG_FRACTION, 1)


# --- Build E: standalone pre-race primer (day before EACH race) -----------
#
# Genuinely different from `_bike_openers_main`/`BIKE_OPENERS_*` above: that
# template is what the week's REGULAR differentiated hard session becomes
# during a taper block or race-proximity week (still sized off the week's
# own hard-session-share budget, `BIKE_HARD_SESSION_SHARE`). This section
# is an ADDITIVE, deliberately tiny standalone session placed exactly one
# day before each race date -- the real defect this closes (Andrew's
# "openers on race day"/"expected them on Friday" finding): the old code
# picked the earliest free day in the week for a primer-ish session, not
# the day immediately before the race, and sized it like a normal hard
# day (up to BIKE_HARD_SESSION_MAX_MIN=75 min) rather than a short,
# nominal primer. Reuses `_bike_openers_ramp_unit`'s progressive-ramp
# shape (this file's own "Openers / pre-race primers" section, Build E
# revision) -- same physiological intent, much less total exposure.

BIKE_PRERACE_PRIMER_WARMUP_MIN = 10.0
BIKE_PRERACE_PRIMER_COOLDOWN_MIN = 5.0
# Coach judgment -- matches SKILLS_WARMUP_MIN/SKILLS_COOLDOWN_MIN's own
# easy-spin bookend convention (library/27), no separate citation: a short
# warm-up before touching race intensity and a short spin-down are
# standard practice, not a numerically-derived figure.
BIKE_PRERACE_PRIMER_REPS = 3
# Coach judgment: "a few" ramps -- library/24's openers subsection cites no
# exact count for a standalone day-before-race primer specifically (its
# "3-5" figure is `BIKE_OPENERS_MIN_REPS`/`MAX_REPS`, the WEEKLY hard-day
# swap's own budget-driven range, not a fixed nominal-duration session's
# count). 3 keeps this a short, genuinely nominal session (see the
# resulting ~25-30 min total below) rather than a scaled-down full hard
# day, consistent with taper theory's "minimal total high-intensity
# exposure" framing (library/24 -- Bosquet 2007; Mujika & Padilla 2003).


def _bike_ramp_reps_structure(
    ftp_watts: float | None, reps: int, *, main_set_label: str, why_text: str
) -> WorkoutStructure:
    """Warm-up / `reps` progressive ramps (full recovery between) /
    cool-down -- the shared builder behind BOTH the day-before-race primer
    (`_bike_prerace_primer_structure`, `reps=BIKE_PRERACE_PRIMER_REPS`) and
    the race-week midweek quality touch (`_bike_midweek_quality_structure`,
    `reps=BIKE_MIDWEEK_QUALITY_REPS`) -- same ramp-unit shape
    (`_bike_openers_ramp_unit`), same warm-up/cool-down bookends
    (`BIKE_PRERACE_PRIMER_WARMUP_MIN`/`_COOLDOWN_MIN`, reused for both --
    Coach judgment, no separate citation needed for a second short bookend
    figure), differing only in rep count and athlete-facing text. A short,
    NOMINAL session either way (like `_skills_session_structure`'s fixed
    duration, not proportional to weekly volume)."""
    items: list[WorkoutStepOrRepeat] = [
        _bike_step(
            "Warm-up, easy spin build",
            "warmup",
            BIKE_PRERACE_PRIMER_WARMUP_MIN * 60,
            "Z2",
            ftp_watts,
        ),
        _bike_open_header(
            f"Main set: {main_set_label} — {reps} x progressive ramp "
            f"({BIKE_OPENERS_RAMP_Z3_S:.0f}s Z3 / {BIKE_OPENERS_RAMP_Z4_S:.0f}s Z4 / "
            f"{BIKE_OPENERS_RAMP_Z5_S:.0f}s Z5), full recovery between ramps"
        ),
    ]
    for i in range(reps):
        items.append(_bike_openers_ramp_unit(ftp_watts))
        if i < reps - 1:
            items.append(
                _bike_step("Easy spin, full recovery", "recovery", BIKE_OPENERS_REST_S, "Z1", ftp_watts)
            )
    items.append(
        _bike_step(
            "Cool-down, easy spin",
            "cooldown",
            BIKE_PRERACE_PRIMER_COOLDOWN_MIN * 60,
            "Z1",
            ftp_watts,
        )
    )
    items.append(
        WorkoutStep(label=why_text, role="open", duration_kind="open", modality="bike")
    )
    return WorkoutStructure(items=items)


def _bike_ramp_reps_duration_min(reps: int) -> float:
    """Fixed nominal duration -- warm-up + N ramps + (N-1) full-recovery
    gaps + cool-down. NOT sized from the week's volume target, same
    "nominal by definition" posture `_skills_session_duration_min` already
    takes for the skills day. Shared by the primer and the midweek quality
    touch -- see `_bike_ramp_reps_structure`."""
    ramp_min = (BIKE_OPENERS_RAMP_Z3_S + BIKE_OPENERS_RAMP_Z4_S + BIKE_OPENERS_RAMP_Z5_S) / 60
    rest_min = BIKE_OPENERS_REST_S / 60
    return (
        BIKE_PRERACE_PRIMER_WARMUP_MIN
        + reps * ramp_min
        + max(0, reps - 1) * rest_min
        + BIKE_PRERACE_PRIMER_COOLDOWN_MIN
    )


def _bike_prerace_primer_structure(ftp_watts: float | None) -> WorkoutStructure:
    """`_bike_ramp_reps_structure` at `BIKE_PRERACE_PRIMER_REPS` -- see
    this section's own header comment for how this differs from
    `_bike_openers_main`."""
    return _bike_ramp_reps_structure(
        ftp_watts,
        BIKE_PRERACE_PRIMER_REPS,
        main_set_label="pre-race primer",
        why_text=(
            "Why: a short primer the day before the race wakes up "
            "race-pace legs and neuromuscular readiness without adding "
            "fatigue -- keep intensity, cut volume (Bosquet 2007; "
            "Mujika & Padilla 2003, library/24)."
        ),
    )

BIKE_MIDWEEK_QUALITY_REPS = 4
# Coach judgment: one more ramp rep than the Friday primer's
# `BIKE_PRERACE_PRIMER_REPS` (3), reusing the exact same ramp-unit shape
# (`_bike_openers_ramp_unit`) rather than inventing a third rep
# convention -- library/24's own openers grounding already covers this
# taper-content territory. Tim's real reference numbers for this slot
# (load 28, 30 min) sit between his own easy spin (load 30, 45 min, all
# easy) and a normal build-week hard day: read as "some quality content,
# more contact than the deliberately-minimal day-before-race primer, well
# short of a real interval session" -- not a volume target to hit exactly
# (his tool's load units aren't this engine's sRPE-based ones).

def _bike_midweek_quality_structure(ftp_watts: float | None) -> WorkoutStructure:
    """`_bike_ramp_reps_structure` at `BIKE_MIDWEEK_QUALITY_REPS` -- see
    this section's own header for how this differs from the Friday
    primer (`_bike_prerace_primer_structure`, fewer reps) and from
    `_bike_openers_main` (the WEEKLY hard-day swap, sized off the week's
    volume budget instead of a fixed nominal duration)."""
    return _bike_ramp_reps_structure(
        ftp_watts,
        BIKE_MIDWEEK_QUALITY_REPS,
        main_set_label="race-week quality touch",
        why_text=(
            "Why: a brief midweek quality touch keeps some race-pace "
            "contact without adding real training load this close to the "
            "race -- more contact than the day-before-race session, well "
            "short of an interval day (Bosquet 2007; Mujika & Padilla "
            "2003, library/24)."
        ),
    )


def _bike_intensity(zone: str, ftp_watts: float | None) -> dict:
    """`Session.intensity` dict for one bike session at `zone` -- shared by
    every bike-session builder in this module (`_bike_week_sessions`,
    `_bike_final_taper_sessions`) so all of them resolve `ftp_watts` the
    same way: absolute watt bounds (`ftp_watts_lo`/`ftp_watts_hi`) via
    `zones.bike_zone_table` once `ftp_watts` is known, else the zone name
    alone -- the same graceful partial-data convention `_bike_step`'s own
    docstring documents for `WorkoutTarget`. Deliberately no `"anchor"` key
    -- see `_bike_week_sessions`'s own docstring for why.
    """
    intensity: dict = {"zone": zone}
    if ftp_watts is not None:
        zone_row = bike_zone_table(ftp_watts)[zone]
        intensity["ftp_watts_lo"] = round(zone_row["watts_lo"], 0)
        intensity["ftp_watts_hi"] = (
            round(zone_row["watts_hi"], 0) if zone_row["watts_hi"] is not None else None
        )
    return intensity


# --- registered archetypes (the workout compiler's bike builders) ----------------------------------
#
# Explicit-reps ranges below are Coach judgment (library/23-cycling-training.md,
# "Workout compiler: explicit-reps ranges"): wider than the auto-fit ranges above (which stay the
# library's 2-3 / 3-5 / 1-2 reps) because an explicit coach request may go beyond the default
# shape, but bounded so a typo cannot compile into an unrideable session.
BIKE_TOTAL_MIN_RANGE = ParamRange(10, 1440, "minutes")
BIKE_EXPLICIT_REPS_RANGE = ParamRange(1, 10)
BIKE_THRESHOLD_REPS_RANGE = ParamRange(1, 6)
BIKE_THRESHOLD_REP_S_RANGE = ParamRange(300, 1800, "seconds")
BIKE_LONG_REST_S_RANGE = ParamRange(30, 900, "seconds")
BIKE_RACE_PACE_REP_S_RANGE = ParamRange(60, 300, "seconds")
BIKE_OVER_UNDER_BLOCKS_RANGE = ParamRange(1, 6, "blocks")
BIKE_OVER_UNDER_CYCLES_RANGE = ParamRange(1, 6, "on/off cycles per block")
BIKE_OVER_UNDER_LEG_S_RANGE = ParamRange(30, 300, "seconds per over and per under")
BIKE_SHORT_SHORT_SETS_RANGE = ParamRange(1, 4, "sets")
BIKE_SHORT_SHORT_REPS_RANGE = ParamRange(4, 20, "reps per set")
BIKE_SHORT_SHORT_ON_S_RANGE = ParamRange(10, 90, "seconds on")
BIKE_SHORT_SHORT_OFF_S_RANGE = ParamRange(5, 90, "seconds off between reps")
BIKE_OPENERS_RAMPS_RANGE = ParamRange(1, 6, "ramps")
BIKE_OPENERS_REST_S_RANGE = ParamRange(60, 600, "seconds")
BIKE_THRESHOLD_ZONE_RANGE = ParamRange(3, 5, "Z3-Z5")
BIKE_ENDURANCE_ZONE_RANGE = ParamRange(1, 2, "Z1-Z2")

_MAIN_LABELS = {
    "sustained_threshold": ("sustained threshold intervals", "Threshold interval"),
    "race_pace": ("race-pace intervals", "Race-pace interval"),
}


def _zone_from(intent: WorkoutIntent, rng: ParamRange, default: str, adj: list[str]) -> str:
    if intent.target_zone is None:
        return default
    return f"Z{int(rng.clamp('target_zone', int(intent.target_zone[1:]), adj))}"


def _items_seconds(items: list[WorkoutStepOrRepeat]) -> float:
    leaves = walk_leaves(WorkoutStructure(items=items), time_only=True)
    return sum((leaf.duration_s or 0.0) * leaf.reps for leaf in leaves)


def _assemble_session(
    main: list[WorkoutStepOrRepeat], asked_min: float | None, ftp: float | None, adj: list[str]
) -> WorkoutStructure:
    """Warm-up + main + cool-down; the asked total is filled with easy spin when the main block is
    shorter, and grows (recorded by the compiler's total check) when the main block is longer."""
    need = _items_seconds(main)
    keep = round(BIKE_WARMUP_COOLDOWN_MIN * 60)
    warm, cool, avail = _bike_warmup_cooldown_reserve(asked_min) if asked_min else (keep, keep, need)
    if need > avail:
        warm = cool = keep
        avail = need
    items: list[WorkoutStepOrRepeat] = [_bike_step("Warm-up, easy spin", "warmup", warm, "Z1", ftp)] if warm else []
    items.extend(main)
    fill = avail - need
    if fill >= 30:
        items.append(_bike_step("Easy spin, fill remaining time", "recovery", fill, "Z1", ftp))
        adj.append(f"added {fill / 60:.0f} min easy spin to reach the asked {asked_min:g} min total")
    if cool:
        items.append(_bike_step("Cool-down, easy spin", "cooldown", cool, "Z1", ftp))
    return WorkoutStructure(items=items)


def _main_seconds_for(asked_min: float | None) -> float | None:
    return _bike_warmup_cooldown_reserve(asked_min)[2] if asked_min else None


def _reps_explicit(
    archetype: str, intent: WorkoutIntent, ftp: float | None, main_s: float | None, zone: str, adj: list[str]
) -> list[WorkoutStepOrRepeat]:
    work_default, rest_default, lo, hi = {
        "sustained_threshold": (
            BIKE_SUSTAINED_THRESHOLD_WORK_S,
            BIKE_SUSTAINED_THRESHOLD_REST_S,
            BIKE_SUSTAINED_THRESHOLD_MIN_REPS,
            BIKE_SUSTAINED_THRESHOLD_MAX_REPS,
        ),
        "race_pace": (BIKE_RACE_PACE_WORK_S, BIKE_RACE_PACE_REST_S, BIKE_RACE_PACE_MIN_REPS, BIKE_RACE_PACE_MAX_REPS),
    }[archetype]
    rep_rng = BIKE_THRESHOLD_REP_S_RANGE if archetype == "sustained_threshold" else BIKE_RACE_PACE_REP_S_RANGE
    reps_rng = BIKE_THRESHOLD_REPS_RANGE if archetype == "sustained_threshold" else BIKE_EXPLICIT_REPS_RANGE
    work_s = rep_rng.clamp("rep_duration_s", intent.rep_duration_s or work_default, adj)
    rest_s = BIKE_LONG_REST_S_RANGE.clamp("rest_s", intent.rest_s if intent.rest_s is not None else rest_default, adj)
    label, work_label = _MAIN_LABELS[archetype]
    if archetype == "sustained_threshold" and zone != "Z4":
        name = _ZONE_KIND_NAMES[zone]
        label, work_label = f"{name.lower()} intervals", f"{name} interval"
    if intent.reps is not None:
        reps = int(reps_rng.clamp("reps", intent.reps, adj))
        return _bike_reps_with_rest_main(
            label, work_label, zone, work_s, "Recovery between reps", reps, reps, rest_s, reps * (work_s + rest_s), ftp
        )
    return _bike_reps_with_rest_main(
        label, work_label, zone, work_s, "Recovery between reps", lo, hi, rest_s * BIKE_REST_GAP_CAP_MULTIPLIER, main_s, ftp
    )


def _blocks(
    label: str,
    build: Callable[[], WorkoutRepeat],
    unit_s: float,
    unit_label: str,
    zone: str,
    count: int | None,
    bounds: tuple[int, int],
    rest_s: float,
    main_s: float | None,
    ftp: float | None,
    rest_label: str,
) -> list[WorkoutStepOrRepeat]:
    """`count` units exactly when given (each followed by `rest_s`), else as many as fit `main_s`."""
    if count is not None:
        main, lo, hi, cap = count * (unit_s + rest_s), count, count, rest_s
    else:
        main = main_s or bounds[0] * (unit_s + rest_s)
        (lo, hi), cap = bounds, rest_s * BIKE_REST_GAP_CAP_MULTIPLIER
    return _bike_blocks_with_rest_main(label, build, unit_s, unit_label, zone, lo, hi, cap, main, ftp, rest_label)


def _over_unders_explicit(
    intent: WorkoutIntent, ftp: float | None, main_s: float | None, adj: list[str]
) -> list[WorkoutStepOrRepeat]:
    leg = BIKE_OVER_UNDER_LEG_S_RANGE.clamp("rep_duration_s", intent.rep_duration_s or BIKE_OVER_UNDER_ON_S, adj)
    cycles = int(BIKE_OVER_UNDER_CYCLES_RANGE.clamp("reps", intent.reps or BIKE_OVER_UNDER_CYCLES_PER_BLOCK, adj))
    rest_in = intent.rest_s if intent.rest_s is not None else BIKE_OVER_UNDER_BLOCK_REST_S
    rest = BIKE_LONG_REST_S_RANGE.clamp("rest_s", rest_in, adj)
    sets = int(BIKE_OVER_UNDER_BLOCKS_RANGE.clamp("sets", intent.sets, adj)) if intent.sets else None

    def build() -> WorkoutRepeat:
        return WorkoutRepeat(
            repeat_mode="count",
            count=cycles,
            steps=[
                _bike_step("Over — supra-threshold", "interval", leg, BIKE_OVER_UNDER_OVER_ZONE, ftp),
                _bike_step("Under — sub-threshold", "interval", leg, BIKE_OVER_UNDER_UNDER_ZONE, ftp),
            ],
        )

    bounds = (BIKE_OVER_UNDER_MIN_BLOCKS, BIKE_OVER_UNDER_MAX_BLOCKS)
    unit_label = f"{cycles} x {leg:g}s/{leg:g}s over/under block"
    return _blocks(
        "over/unders", build, cycles * 2 * leg, unit_label, BIKE_OVER_UNDER_OVER_ZONE, sets, bounds, rest, main_s, ftp,
        "Recovery between blocks",
    )


def _short_short_explicit(
    intent: WorkoutIntent, ftp: float | None, main_s: float | None, adj: list[str]
) -> list[WorkoutStepOrRepeat]:
    on = BIKE_SHORT_SHORT_ON_S_RANGE.clamp("rep_duration_s", intent.rep_duration_s or BIKE_SHORT_SHORT_ON_S, adj)
    off_in = intent.rest_s if intent.rest_s is not None else BIKE_SHORT_SHORT_OFF_S
    off = BIKE_SHORT_SHORT_OFF_S_RANGE.clamp("rest_s", off_in, adj)
    reps = int(BIKE_SHORT_SHORT_REPS_RANGE.clamp("reps", intent.reps or BIKE_SHORT_SHORT_REPS_PER_SET, adj))
    sets = int(BIKE_SHORT_SHORT_SETS_RANGE.clamp("sets", intent.sets, adj)) if intent.sets else None

    def build() -> WorkoutRepeat:
        return WorkoutRepeat(
            repeat_mode="count",
            count=reps,
            steps=[
                _bike_step("Short-short ON", "interval", on, BIKE_SHORT_SHORT_ZONE, ftp),
                _bike_step("Short-short OFF", "recovery", off, "Z1", ftp),
            ],
        )

    bounds = (BIKE_SHORT_SHORT_MIN_SETS, BIKE_SHORT_SHORT_MAX_SETS)
    return _blocks(
        "short-short VO2 intervals", build, reps * (on + off), f"{reps} x {on:g}s/{off:g}s set", BIKE_SHORT_SHORT_ZONE,
        sets, bounds, BIKE_SHORT_SHORT_SET_REST_S, main_s, ftp, "Recovery between sets",
    )


def _openers_explicit(
    intent: WorkoutIntent, ftp: float | None, main_s: float | None, adj: list[str]
) -> list[WorkoutStepOrRepeat]:
    ramps = int(BIKE_OPENERS_RAMPS_RANGE.clamp("reps", intent.reps, adj)) if intent.reps else None
    rest_in = intent.rest_s if intent.rest_s is not None else BIKE_OPENERS_REST_S
    rest = BIKE_OPENERS_REST_S_RANGE.clamp("rest_s", rest_in, adj)
    unit_s = BIKE_OPENERS_RAMP_Z3_S + BIKE_OPENERS_RAMP_Z4_S + BIKE_OPENERS_RAMP_Z5_S
    unit_label = (
        f"ramp ({BIKE_OPENERS_RAMP_Z3_S:.0f}s Z3 / {BIKE_OPENERS_RAMP_Z4_S:.0f}s Z4 / {BIKE_OPENERS_RAMP_Z5_S:.0f}s Z5)"
    )
    return _blocks(
        "openers (pre-race primers, progressive ramp)", lambda: _bike_openers_ramp_unit(ftp), unit_s, unit_label,
        BIKE_OPENERS_ZONE, ramps, (BIKE_OPENERS_MIN_REPS, BIKE_OPENERS_MAX_REPS), rest, main_s, ftp,
        "Full recovery between ramps",
    )


_EXPLICIT_TRIGGERS = ("reps", "rep_duration_s", "rest_s", "sets")


def _explicit_items(
    archetype: str, intent: WorkoutIntent, ftp: float | None, main_s: float | None, zone: str, adj: list[str]
) -> list[WorkoutStepOrRepeat]:
    if archetype in _MAIN_LABELS:
        return _reps_explicit(archetype, intent, ftp, main_s, zone, adj)
    fn = {
        "over_unders": _over_unders_explicit,
        "short_short_vo2": _short_short_explicit,
        "openers": _openers_explicit,
    }[archetype]
    return fn(intent, ftp, main_s, adj)


def _build_hard(intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
    adj: list[str] = []
    ftp = athlete.ftp_watts
    arch = intent.archetype
    default_zone = BIKE_INTERVAL_TEMPLATE_META[arch]["zone"]
    zone = default_zone
    if arch == "sustained_threshold":
        zone = _zone_from(intent, BIKE_THRESHOLD_ZONE_RANGE, default_zone, adj)
    explicit = zone != default_zone or any(getattr(intent, f) is not None for f in _EXPLICIT_TRIGGERS)
    if not explicit and not intent.total_duration_min:
        raise ValueError(f"bike archetype {arch!r} needs total_duration_min or reps with rep_duration_s")
    asked = None
    if intent.total_duration_min:
        asked = BIKE_TOTAL_MIN_RANGE.clamp("total_duration_min", intent.total_duration_min, adj)
    if explicit:
        main = _explicit_items(arch, intent, ftp, _main_seconds_for(asked), zone, adj)
        structure = _assemble_session(main, asked, ftp, adj)
    else:
        structure = _bike_hard_session_structure(arch, asked, ftp)
    return BuildResult(structure=structure, intensity=_bike_intensity(zone, ftp), adjustments=adj)


def _build_endurance(intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
    adj: list[str] = []
    if not intent.total_duration_min:
        raise ValueError("bike archetype 'endurance' needs total_duration_min (bike sessions are sized in time)")
    zone = _zone_from(intent, BIKE_ENDURANCE_ZONE_RANGE, "Z2", adj)
    minutes = BIKE_TOTAL_MIN_RANGE.clamp("total_duration_min", intent.total_duration_min, adj)
    structure = _bike_session_structure(zone, minutes, athlete.ftp_watts)
    return BuildResult(structure=structure, intensity=_bike_intensity(zone, athlete.ftp_watts), adjustments=adj)


def _fixed_builder(
    make: Callable[[float | None], WorkoutStructure], zone: str
) -> Callable[[WorkoutIntent, Athlete], BuildResult]:
    def build(intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
        return BuildResult(structure=make(athlete.ftp_watts), intensity=_bike_intensity(zone, athlete.ftp_watts))

    return build


# --- steady_intervals: the zone-neutral reps x work / rest builder (progression rungs) -------------
#
# Coach judgment (library/23-cycling-training.md, "Workout compiler: explicit-reps ranges"). Reps go
# down to 10 s so one builder also compiles short on/off VO2 work (15/15 up to 40/20, any reps or
# sets); it is the canonical builder for `parse_rung`. `short_short_vo2` stays the library-shaped
# auto-fit session (10 x 30/15 sets).
BIKE_STEADY_REPS_RANGE = ParamRange(1, 60, "reps per set")
BIKE_STEADY_SETS_RANGE = ParamRange(1, 10, "sets")
BIKE_STEADY_REP_S_RANGE = ParamRange(10, 3600, "seconds")
BIKE_STEADY_REST_S_RANGE = ParamRange(0, 900, "seconds")
BIKE_STEADY_SET_REST_S_RANGE = ParamRange(0, 1800, "seconds, total recovery between sets")
# Default rest is 1:1 with the work, capped at the sustained-threshold rest (race-pace uses 1:1,
# sustained threshold 4 min); default total recovery between sets is the short-short set rest.
_STEADY_REST_CAP_S = BIKE_SUSTAINED_THRESHOLD_REST_S
_ZONE_KIND_NAMES = {"Z3": "Tempo", "Z4": "Threshold", "Z5": "VO2"}


def _zone_rank_in_range(intent: WorkoutIntent) -> str:
    rank = int(intent.target_zone[1:]) if intent.target_zone else 4
    return f"Z{int(BIKE_THRESHOLD_ZONE_RANGE.lo if rank < 3 else min(rank, BIKE_THRESHOLD_ZONE_RANGE.hi))}"


def _zone_kind(intent: WorkoutIntent) -> StimulusKind:
    return ZONE_KINDS[_zone_rank_in_range(intent)]


def _steady_rest_defaults(intent: WorkoutIntent) -> tuple[float, float | None]:
    work = intent.rep_duration_s or BIKE_SUSTAINED_THRESHOLD_WORK_S
    rest = intent.rest_s if intent.rest_s is not None else min(_STEADY_REST_CAP_S, work)
    set_rest = intent.set_rest_s if intent.set_rest_s is not None else BIKE_SHORT_SHORT_SET_REST_S
    return rest, set_rest


def _steady_set(zone: str, reps: int, work_s: float, rest_s: float, ftp: float | None) -> WorkoutRepeat:
    name = _ZONE_KIND_NAMES[zone]
    steps = [_bike_step(f"{name} interval", "interval", work_s, zone, ftp)]
    if rest_s > 0:
        steps.append(_bike_step("Recovery between reps", "recovery", rest_s, "Z1", ftp))
    return WorkoutRepeat(repeat_mode="count", count=reps, steps=steps)


def _steady_main(
    zone: str, sets: int, reps: int, work_s: float, rest_s: float, set_rest_s: float, ftp: float | None
) -> list[WorkoutStepOrRepeat]:
    """`sets` flat sibling repeats; between sets only the rest beyond the in-set rest, none after the last."""
    text = format_rung(sets, reps, format_duration(work_s), rest_s, set_rest_s, zone)
    items: list[WorkoutStepOrRepeat] = [
        _bike_open_header(f"Main set: {_ZONE_KIND_NAMES[zone].lower()} intervals — {text}")
    ]
    for index in range(sets):
        items.append(_steady_set(zone, reps, work_s, rest_s, ftp))
        gap = set_rest_s - rest_s
        if index < sets - 1 and gap > 0:
            items.append(_bike_step("Recovery between sets", "recovery", gap, "Z1", ftp))
    return items


def _steady_reps(
    intent: WorkoutIntent, main_s: float | None, sets: int, work_s: float, rest_s: float, set_rest_s: float,
    adj: list[str],
) -> int:
    if intent.reps is not None:
        return int(BIKE_STEADY_REPS_RANGE.clamp("reps", intent.reps, adj))
    if main_s is None:
        raise ValueError("bike archetype 'steady_intervals' needs reps, or a total_duration_min to fit them to")
    gaps = (sets - 1) * max(0.0, set_rest_s - rest_s)
    fitted = int((main_s - gaps) // (sets * (work_s + rest_s)))
    return int(BIKE_STEADY_REPS_RANGE.clamp("reps", max(1, fitted), []))


def _build_steady(intent: WorkoutIntent, athlete: Athlete) -> BuildResult:
    adj: list[str] = []
    ftp = athlete.ftp_watts
    zone = _zone_rank_in_range(intent)
    if intent.target_zone and zone != intent.target_zone:
        adj.append(f"asked target_zone={intent.target_zone}; built {zone} (builder range Z3-Z5)")
    work_s = BIKE_STEADY_REP_S_RANGE.clamp("rep_duration_s", intent.rep_duration_s or BIKE_SUSTAINED_THRESHOLD_WORK_S, adj)
    rest_in, set_rest_in = _steady_rest_defaults(intent.model_copy(update={"rep_duration_s": work_s}))
    rest_s = BIKE_STEADY_REST_S_RANGE.clamp("rest_s", rest_in, adj)
    sets = int(BIKE_STEADY_SETS_RANGE.clamp("sets", intent.sets or 1, adj))
    set_rest_s = BIKE_STEADY_SET_REST_S_RANGE.clamp("set_rest_s", set_rest_in, adj)
    if sets > 1 and set_rest_s < rest_s:
        adj.append(f"set_rest_s={set_rest_s:g} is below rest_s={rest_s:g}; sets follow the in-set rest directly")
    asked = None
    if intent.total_duration_min:
        asked = BIKE_TOTAL_MIN_RANGE.clamp("total_duration_min", intent.total_duration_min, adj)
    reps = _steady_reps(intent, _main_seconds_for(asked), sets, work_s, rest_s, set_rest_s, adj)
    main = _steady_main(zone, sets, reps, work_s, rest_s, set_rest_s, ftp)
    structure = _assemble_session(main, asked, ftp, adj)
    return BuildResult(structure=structure, intensity=_bike_intensity(zone, ftp), adjustments=adj)


_BIKE = frozenset({"bike"})
_TOTAL = {"total_duration_min": BIKE_TOTAL_MIN_RANGE}
_HARD_SPECS: tuple[tuple[str, str, str, dict[str, ParamRange]], ...] = (
    (
        "sustained_threshold",
        "threshold",
        "Long threshold reps (default 2-3 x 10 min Z4) with near-full recovery.",
        {
            **_TOTAL,
            "reps": BIKE_THRESHOLD_REPS_RANGE,
            "rep_duration_s": BIKE_THRESHOLD_REP_S_RANGE,
            "rest_s": BIKE_LONG_REST_S_RANGE,
            "target_zone": BIKE_THRESHOLD_ZONE_RANGE,
        },
    ),
    (
        "over_unders",
        "mixed",
        "Over/under blocks (default 2-4 blocks of 2 x 90s Z4 over / Z3 under).",
        {
            **_TOTAL,
            "sets": BIKE_OVER_UNDER_BLOCKS_RANGE,
            "reps": BIKE_OVER_UNDER_CYCLES_RANGE,
            "rep_duration_s": BIKE_OVER_UNDER_LEG_S_RANGE,
            "rest_s": BIKE_LONG_REST_S_RANGE,
        },
    ),
    (
        "short_short_vo2",
        "vo2",
        "Short-short VO2 sets (default 1-2 sets of 10 x 30s on / 15s off, Z5).",
        {
            **_TOTAL,
            "sets": BIKE_SHORT_SHORT_SETS_RANGE,
            "reps": BIKE_SHORT_SHORT_REPS_RANGE,
            "rep_duration_s": BIKE_SHORT_SHORT_ON_S_RANGE,
            "rest_s": BIKE_SHORT_SHORT_OFF_S_RANGE,
        },
    ),
    (
        "race_pace",
        "vo2",
        "Race-pace reps (default 3-5 x 2.5 min Z5) with near-full recovery.",
        {
            **_TOTAL,
            "reps": BIKE_EXPLICIT_REPS_RANGE,
            "rep_duration_s": BIKE_RACE_PACE_REP_S_RANGE,
            "rest_s": BIKE_LONG_REST_S_RANGE,
        },
    ),
    (
        "openers",
        "mixed",
        "Taper openers: 2-4 progressive ramps (Z3, Z4, brief Z5) with full recovery.",
        {**_TOTAL, "reps": BIKE_OPENERS_RAMPS_RANGE, "rest_s": BIKE_OPENERS_REST_S_RANGE},
    ),
)
_FIXED_SPECS = (
    ("prerace_primer", "mixed", "Fixed day-before-race primer: 3 progressive ramps, about 30 min.",
     _bike_prerace_primer_structure, BIKE_OPENERS_ZONE),
    ("midweek_quality", "mixed", "Fixed race-week quality touch: 4 progressive ramps, about 35 min.",
     _bike_midweek_quality_structure, BIKE_OPENERS_ZONE),
    ("ramp_test", "vo2", "Ramp-to-failure FTP test (fixed, 25 min); no power target to hold.",
     _bike_ramp_test_structure, "Z5"),
    ("test_2x20", "threshold", "Two 20-min maximal efforts FTP test; RPE-paced, no power target.",
     _bike_2x20_test_structure, "Z4"),
)


def _register_bike_builders() -> None:
    for arch, kind, summary, params in _HARD_SPECS:
        kind_for = _zone_kind if arch == "sustained_threshold" else None
        register(WorkoutBuilder("bike", arch, kind, summary, _BIKE, params, _build_hard, kind_for))
    steady_params = {
        **_TOTAL,
        "sets": BIKE_STEADY_SETS_RANGE,
        "reps": BIKE_STEADY_REPS_RANGE,
        "rep_duration_s": BIKE_STEADY_REP_S_RANGE,
        "rest_s": BIKE_STEADY_REST_S_RANGE,
        "set_rest_s": BIKE_STEADY_SET_REST_S_RANGE,
        "target_zone": BIKE_THRESHOLD_ZONE_RANGE,
    }
    register(
        WorkoutBuilder(
            "bike", "steady_intervals", "threshold",
            "Any sets x reps x work / rest at Z3 (tempo), Z4 (threshold) or Z5 (VO2); also short on/off VO2 work.",
            _BIKE, steady_params, _build_steady, _zone_kind, True, _steady_rest_defaults,
        )
    )
    endurance_params = {**_TOTAL, "target_zone": BIKE_ENDURANCE_ZONE_RANGE}
    summary = "Flat easy ride (default Z2) with warm-up and cool-down."
    register(WorkoutBuilder("bike", "endurance", "endurance", summary, _BIKE, endurance_params, _build_endurance))
    for arch, kind, summary, make, zone in _FIXED_SPECS:
        register(WorkoutBuilder("bike", arch, kind, summary, _BIKE, {}, _fixed_builder(make, zone)))


_register_bike_builders()
