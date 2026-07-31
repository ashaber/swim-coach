"""Macro periodization scaffold + weekly plan generation.

`scaffold_macro` builds the base -> build -> peak -> taper block structure
toward an `Event`; `generate_week` expands one week of that macro into a
`WeekPlan` of concrete `Session`s (pool placeholders, long swim, strength,
recovery, and any leftover pool-independent volume) -- the long swim's
weekend arrangement follows `Event.event_format` (`single_day`: one
continuous Saturday swim; `multi_day_stage`: split across Saturday+Sunday).

Every tunable number below is a named module-level constant with a comment
citing its source: `library/reference_list.md` (the project's only
trustworthy citation source -- see `library/00-conventions.md`) for claims
that trace to a verified paper/source, or `library/03-periodization.md` /
`library/06-long-swim-progression.md` (both authored on Day 4, alongside
`load.py` and `adapt.py`) for this engine's own coach-judgment defaults.
Two now-deleted files (`open_water_library.md`, an earlier "vector data
schema" dump with fabricated URLs/IDs and injected instruction-like text,
and its nutrition counterpart) are NOT valid citation sources -- see
`library/reference_list.md`'s header for the full account of why they were
removed and replaced.
"""

from __future__ import annotations

import math
import warnings
from datetime import date, timedelta
from typing import Literal
from uuid import uuid4

from swim_coach.models import Athlete, Event, MacroBlock, MacroPlan, Session, WeekPlan
from swim_coach.workout_templates import render_main_set
from swim_coach.zones import zone_table

EventFormat = Literal["single_day", "multi_day_stage"]

# --- Macro block allocation constants ---------------------------------------

MIN_MACRO_WEEKS = 8
# PROVISIONAL: minimum runway to periodize safely -- base+build+peak+taper
# each need at least a week or two to mean anything. Below this, refuse
# rather than produce a degenerate plan. library/03-periodization.md
# (to be authored).

TAPER_RUNWAY_THRESHOLD_WEEKS = 16
TAPER_WEEKS_LONG = 4
TAPER_WEEKS_SHORT = 2
# 4-week taper for runways >= 16 weeks. KNOWN CITATION DEBT (see
# library/reference_list.md "Corrections log" #1): this was originally cited
# to Formosa et al.'s 78-km solo OW case study as "4-week exponential decay,
# 25% linear/week," but reference_list.md's verification found the actual
# paper reports a ~3-week taper with ~43% total volume reduction (intensity
# maintained) -- the "4-week/25%" figures were embellishments and must not be
# cited to Formosa. TAPER_WEEKS_LONG/TAPER_WEEKLY_DECAY below are left as
# PROVISIONAL coach-judgment values (library/03-periodization.md) rather than
# changed to match the corrected Formosa numbers in this pass, since existing
# Day 1-3 tests assert the current 4-week/25% behavior; re-deriving the taper
# block from the corrected source is flagged as follow-up work, not done here.
# Shorter runways compress to a 2-week taper -- PROVISIONAL,
# library/03-periodization.md.

PEAK_WEEKS_LONG = 3
PEAK_WEEKS_SHORT = 2
# PROVISIONAL: library/03-periodization.md (to be authored).

BASE_SHARE = 0.6
# PROVISIONAL: of the weeks remaining after taper+peak are carved out, base
# gets ceil(60%) and build gets the rest. library/03-periodization.md.

BASE_END_VOLUME_SHARE_OF_PEAK = 0.85
# PROVISIONAL: base block ramps toward ~85% of peak weekly volume by its
# final week; build closes the remaining gap to 100%. library/03-periodization.md.

TAPER_WEEKLY_DECAY = 0.25
# 4-week, 25%-of-peak-per-week linear taper decay. See the citation-debt note
# on TAPER_WEEKS_LONG above -- this is PROVISIONAL / coach judgment, not a
# verified Formosa figure.

PEAK_WEEKLY_VOLUME_X_EVENT_DISTANCE = 2.5
# PROVISIONAL: default peak weekly volume, expressed as a multiple of event
# distance, when the athlete/coach doesn't supply one explicitly.
# library/06-long-swim-progression.md (to be authored).

WEEKLY_VOLUME_RAMP_CAP = 0.08
# Safety rail: weekly volume must never increase more than 8%/week.
# CLAUDE.md safety rails ("weekly volume +<=8%... without explicit athlete
# confirmation") / library/03-periodization.md.

LONG_SWIM_SHARE = 0.33
# PROVISIONAL: long swim as a share of that week's target volume -- a single
# Saturday swim for event_format="single_day", split across Saturday+Sunday
# for "multi_day_stage" (see STAGE_SATURDAY_SHARE below). Same total share
# either way; only the weekend arrangement differs.
# library/06-long-swim-progression.md (to be authored).

STAGE_SATURDAY_SHARE = 0.55
# PROVISIONAL: for event_format="multi_day_stage", the week's long-swim
# volume (LONG_SWIM_SHARE of target) is split across back-to-back Saturday
# + Sunday swims rather than one continuous swim, per ROADMAP.md "Event
# format parameter" (mirrors events like UltraSwim 33.3's 4-day option:
# "longest single swim tops out ~30-40% of total distance ... no single
# monster swim"). Saturday gets the larger (fresher-legs) share, since a
# stage event's Sunday leg is always swum on Saturday's fatigue -- training
# should mirror that order. library/06-long-swim-progression.md
# (to be authored).

# --- Weekly session-generation constants ------------------------------------

DEFAULT_POOL_SESSION_MIN = 75
# PROVISIONAL: estimated duration for a coach-assigned pool placeholder
# session (content is unknown until the pool coach delivers it post-hoc).
# library/06-long-swim-progression.md (to be authored).

POOL_SESSION_EST_M = 3500
# PROVISIONAL: matches the ~3,500-4,000m sample workouts in
# library/sample_pool_workout_*.md. Used as the estimated distance for both
# placeholder pool-coach sessions (athlete.has_pool_coach=True) and the
# "additional" ai_coach pool/OW session -- the pool coach's own volume is
# roughly constant regardless of macro phase (they don't know the
# periodization plan), so this constant does not scale with weekly target
# volume. NOT used for has_pool_coach=False pool-day sessions -- see
# NO_COACH_POOL_SESSION_FLOOR_M below.

NO_COACH_POOL_SESSION_FLOOR_M = 300
# Floor (not a target) for a no-pool-coach pool-day session's per-day
# distance, used only in the has_pool_coach=False branch. Unlike
# POOL_SESSION_EST_M (a real masters coach's own volume, which genuinely
# doesn't scale with this project's periodization), a no-pool-coach pool
# session IS authored by this engine and must scale with the week's
# target_volume_m -- so its distance is derived from target_volume_m minus
# the long swim's reserved share, split across the week's pool days, with
# this floor only to keep a genuinely-early-restart week's session from
# collapsing to 0m or an absurdly tiny distance. Deliberately much smaller
# than POOL_SESSION_EST_M's scale. library/06-long-swim-progression.md.
#
# KNOWN EDGE CASE: when NO_COACH_POOL_SESSION_FLOOR_M * len(pool_schedule)
# exceeds target_volume_m (a genuinely-early restart week combined with a
# near-daily pool_schedule, e.g. 5 pool days at a ~1200m target), the floor
# necessarily pushes pool_total_m back above target_volume_m -- a smaller,
# bounded recurrence of the bug this constant was introduced to fix (bounded
# by floor * pool_days, vs. the old unbounded POOL_SESSION_EST_M * pool_days
# overage). The remainder/long-swim reconciliation below absorbs as much of
# this as it can, flooring the long swim at 0m, but cannot fully compensate
# once the long swim hits that floor -- total swim volume can still modestly
# exceed target_volume_m in this corner case. Accepted as a deliberate
# trade-off (a sane per-session minimum matters more than exact target
# tracking in an already-degenerate week) rather than fixed further here --
# see test_generate_week_no_pool_coach_floor_can_still_modestly_exceed_
# target_with_many_pool_days in tests/unit/test_plan.py, which pins the
# current bounded behavior so it can't silently regress.

STRENGTH_SESSIONS_PER_WEEK = 2
STRENGTH_SESSION_MIN = 45
# Dry-land shoulder work improves rotator-cuff strength/balance in
# competitive swimmers -- three RCTs (Hibberd 2012, Manske 2015, Tavares
# et al. 2025), library/reference_list.md "Injury & training load".
# Frequency grounded in library/04-css-intensity-anchors.md, independently
# corroborated by Tavares' (twice weekly) and Manske's (2-3x/week) own
# protocols; full programming detail (exercise selection, dosing,
# duration, placement, cut-week/taper handling) in
# library/07-strength-dryland.md.

STRENGTH_CORE_EXERCISES = (
    "Internal rotation at 90° abduction",
    "External rotation at 90° abduction",
    "Scapular punches",
    'Scapular retraction ("Ts")',
    'Retraction with upward rotation ("Ys")',
)
# Rotator-cuff/scapular-stabilizer core, dosed 2 sets x 10 reps per
# Tavares, Vilas-Boas & Castro (2025) -- the strongest/most recent of the
# three swimmer-shoulder RCTs cited in library/07-strength-dryland.md's
# "What's actually in a session" section. [EVIDENCE: swim] for the
# exercise selection and the 2-3 sets x 10-20 rep range the three trials
# collectively used; Coach judgment for collapsing that range to this one
# fixed dose (the trials disagree on load -- bands at a self-regulated RPE
# vs. dumbbells at 75% 1RM) -- see library/07-strength-dryland.md.

STRENGTH_FULL_BODY_ADDITION = (
    "3 x 10 goblet squat or bodyweight squat",
    "3 x 10 per side single-leg Romanian deadlift (or bodyweight equivalent)",
    "3 x 10 plank or dead-bug core hold (30-45s each side)",
)
# General full-body work layered in as time allows -- Coach judgment, no
# swim-specific RCT tested this addition. library/07-strength-dryland.md.

RECOVERY_SESSION_MIN = 20
# The Session model requires duration_min > 0, so a 0-duration "day off"
# isn't representable -- recovery is modeled as a short mobility session
# instead. PROVISIONAL, Coach judgment.

MIN_ADDITIONAL_SWIM_M = 1000
# PROVISIONAL: below this, leftover pool-independent volume is absorbed
# into the long swim rather than spawning a separate short session.
# Coach judgment.

MIN_RAMP_SEED_VOLUME_M = 1000
# Coach judgment, engineering seed value (no citation needed, same footing
# as MIN_ADDITIONAL_SWIM_M above) -- current_weekly_volume_m=0 is a real
# starting point (a brand-new swimmer), but the ramp cap's job is to bound
# growth from a REAL baseline; capping at literal zero is a degenerate
# multiplication artifact, not the intended safety behavior. This seed
# only affects the ramp CEILING calculation below, not any other reported
# "current volume" -- an athlete's real current_weekly_volume_m is still 0
# everywhere else it's used/reported.

DEFAULT_CSS_PACE_S_PER_100M = 100.0
# Fallback pace used only if an athlete has no css_pace_s_per_100m yet
# (e.g. before their first CSS test), so session duration estimates stay
# computable. Not cited -- Coach judgment.

ADDITIONAL_SWIM_WARM_UP_SHARE = 0.2
ADDITIONAL_SWIM_COOL_DOWN_SHARE = 0.1
ADDITIONAL_SWIM_MIN_WARM_UP_M = 200
ADDITIONAL_SWIM_MIN_COOL_DOWN_M = 100
# Coach judgment / practitioner convention -- library/14-swim-set-structure.md
# ("Session skeleton" section) is explicit that no citable source fixes a
# warm-up or cool-down proportion; McGowan et al. (2015) grounds only that a
# warm-up is worthwhile, not its size. This governs ONLY the "additional"
# pool-independent swim_ow session below -- the Saturday long-swim session
# (library/06-long-swim-progression.md) stays continuous/negative-split and
# is untouched by these constants.

ADDITIONAL_SWIM_BASE_BLOCK_REP_M = 300
ADDITIONAL_SWIM_BUILD_BLOCK_REP_M = 200
# Coach judgment -- main-set rep length for the two main-set formats below.
# library/14-swim-set-structure.md's "Main-set format menu" section is
# explicit that no source ranks these formats; the base-vs-build/peak/taper
# *emphasis* shift itself is [EVIDENCE: swim] (González-Ravé et al. 2021;
# Pla et al. 2019), the concrete rep length is not.

# The size of each block-category's main-set format menu (base: 2, build/
# peak/taper: 4, as of this writing) is no longer a fixed constant here --
# it's however many templates `engine/swim_coach/workout_templates/*.yaml`
# ships for that block, read by `swim_coach.workout_templates.
# render_main_set` at render time. All format *choices* are Coach judgment
# per library/14-swim-set-structure.md's "Main-set format menu" section
# ("straight aerobic repeats, descending sets, broken-distance/pyramid sets,
# and negative-split segments are the shared vocabulary of pool coaching ...
# offered as legitimate, standard coaching options" -- that file is explicit
# no source ranks one format as superior). `_additional_swim_structure`'s
# `selector` picks among the applicable templates via `selector % <count>`,
# deterministically -- same block + same selector always yields the same
# template, forever (no random/global state), which is what makes this
# rotation safe to unit-test and audit.

_WEEKDAY_OFFSETS = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


# --- date helpers ------------------------------------------------------------


def _monday_on_or_after(d: date) -> date:
    return d + timedelta(days=(7 - d.weekday()) % 7)


def _monday_of_week(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _pool_day_offset(entry: str | dict) -> int:
    """Map a pool_schedule entry (weekday string or {"day": ...} dict) to a
    Monday-relative day offset (0=Monday .. 6=Sunday). Accepts abbreviated
    ("tue") or full ("tuesday") names, case-insensitively."""
    day = entry["day"] if isinstance(entry, dict) else entry
    key = str(day).strip().lower()[:3]
    if key not in _WEEKDAY_OFFSETS:
        raise ValueError(f"unrecognized pool_schedule day: {day!r}")
    return _WEEKDAY_OFFSETS[key]


def _round_100(value: float) -> int:
    return int(round(value / 100)) * 100


def _z2_pace_s_per_100m(athlete: Athlete) -> float:
    css = athlete.css_pace_s_per_100m or DEFAULT_CSS_PACE_S_PER_100M
    z2 = zone_table(css)["Z2"]
    return (z2["pace_lo_s"] + z2["pace_hi_s"]) / 2


def _duration_min_for_distance(distance_m: float, pace_s_per_100m: float) -> float:
    return round(max(distance_m, 0) / 100 * pace_s_per_100m / 60, 1)


def _pick_days(count: int, excluded: set[int]) -> list[int]:
    """Pick `count` Monday-relative day offsets, preferring days not in
    `excluded` (in ascending Mon->Sun order), falling back to reusing
    excluded days (still ascending order) if there aren't enough free days.
    """
    order = list(range(7))
    chosen = [d for d in order if d not in excluded][:count]
    if len(chosen) < count:
        remaining = [d for d in order if d not in chosen]
        chosen.extend(remaining[: count - len(chosen)])
    return chosen[:count]


def _format_pace_s(pace_s: float) -> str:
    """Format a seconds-per-100m pace as M:SS (e.g. 92.3 -> '1:32')."""
    total = int(round(pace_s))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def _strength_session_structure(session_index: int) -> str:
    """Fixed default strength-session program text (not macro-block-aware
    -- see library/07-strength-dryland.md's "Open questions" section for
    why block/phase progression is explicitly out of scope here).

    `session_index` (0-based) selects which of the week's
    `STRENGTH_SESSIONS_PER_WEEK` strength sessions this is: session 0 is
    the rotator-cuff/scapular-stability core only; odd-indexed sessions
    add general full-body work layered in as time allows, matching
    library/07-strength-dryland.md's "core of each session, general
    full-body layered in" framing. Dosing (2 sets x 10 reps) follows
    Tavares, Vilas-Boas & Castro (2025) -- see library/07-strength-dryland.md
    for the full citation set (Hibberd 2012, Manske 2015, Tavares 2025) and
    the dosing-range caveat.

    Returns a final `Why: ...` line citing the real sources behind this
    session's rotator-cuff/scapular-stability emphasis (Hibberd 2012, Manske
    2015, Tavares et al. 2025) -- athlete-facing text, so a real citation,
    never the internal `library/07-strength-dryland.md` path.
    """
    lines = ["Rotator-cuff / scapular-stability core (2 sets x 10 reps each):"]
    lines.extend(f"  - {exercise}" for exercise in STRENGTH_CORE_EXERCISES)
    if session_index % 2 == 1:
        lines.append("General full-body (layered in as time allows):")
        lines.extend(f"  - {exercise}" for exercise in STRENGTH_FULL_BODY_ADDITION)
    lines.append(
        "Why: rotator-cuff strength/balance, reduces shoulder-injury risk "
        "(Hibberd 2012; Manske 2015; Tavares et al. 2025)."
    )
    return "\n".join(lines)


def _additional_swim_structure(
    macro_block_name: str, distance_m: int, css_pace_s: float, selector: int = 0
) -> str:
    """Warm-up / main-set / cool-down text for the "additional"
    pool-independent aerobic swim_ow session (the `remainder >=
    MIN_ADDITIONAL_SWIM_M` path in `generate_week`), and reused verbatim by
    `generate_week`'s `athlete.has_pool_coach is False` branch to author
    real content for weekday pool-slot sessions that would otherwise be a
    content-less `pool_coach` placeholder (there's no masters coach handing
    out that content post-hoc, so the engine authors it instead).

    This function must NEVER be called for the Saturday/stage long-swim
    session(s) -- those stay continuous/negative-split by design
    (library/06-long-swim-progression.md) and are not touched here.

    Warm-up/cool-down proportions are Coach judgment / practitioner
    convention (library/14-swim-set-structure.md); the base-vs-build/peak/
    taper emphasis shift (continuous aerobic volume vs. broken-distance,
    race-pace-adjacent work) is [EVIDENCE: swim] per González-Ravé et al.
    (2021) and Pla et al. (2019), also cited in `14`. Distances are rounded
    to the nearest 100m (main-set reps to the nearest rep length) and are
    illustrative, not exact to the meter.

    Main-set format menu and rotation: this is data-driven -- see
    `swim_coach.workout_templates` for the full template library
    (`engine/swim_coach/workout_templates/*.yaml`), the `FORMAT_STRATEGIES`
    that compute each shape's numbers, and the load-time validation that
    keeps every template's arithmetic and periodization-boundary rules
    honest. `selector` (typically the week's 0-based index within its macro
    block -- see `generate_week`'s `week_index_in_block`) is passed straight
    through to `render_main_set`, which deterministically picks one template
    from the block-category's menu via `selector % <template count>` -- the
    same `(macro_block_name, selector)` pair always renders the same
    template, every time, so the whole rotation stays reproducible/auditable
    (no random or global state involved). This does NOT change the
    function's total-volume or zone-math contract -- warm-up + main set +
    cool-down still sum exactly to `distance_m` for every template, only the
    main set's internal SHAPE differs. All shipped templates are drawn from
    library/14-swim-set-structure.md's "Main-set format menu" (an explicitly
    open menu -- "No verified source in this pass ranks one format as
    superior"); the base-vs-build/peak/taper *emphasis* shift is the only
    piece of this with real evidence (González-Ravé et al. 2021; Pla et al.
    2019), and it applies identically no matter which template a given
    block/rotation lands on.

    Returns a final `Why: ...` line (athlete-facing rationale, no internal
    `library/` paths) instead of citing internal file paths on the Main-set
    line itself: base block gets a Coach-judgment framing (no citation
    oversold where none exists); build/peak/taper gets the real citation
    (González-Ravé et al. 2021; Pla et al. 2019) backing the phase shift --
    identical wording regardless of which template within the block was
    selected.
    """
    if distance_m <= 0:
        return "No additional pool-independent volume this week."

    zones = zone_table(css_pace_s)
    z2, z3, z4 = zones["Z2"], zones["Z3"], zones["Z4"]

    warm_up = max(
        ADDITIONAL_SWIM_MIN_WARM_UP_M, _round_100(distance_m * ADDITIONAL_SWIM_WARM_UP_SHARE)
    )
    # Sized only to choose a sensible rep length / rep count below -- the
    # actual cool-down (and therefore the session's true total) is
    # reconciled after reps are picked, so warm-up + main set + cool-down
    # always sums exactly to `distance_m` instead of drifting by a rep's
    # worth of rounding (a real bug in an earlier version of this function:
    # rounding `main_set_total / rep` to the nearest rep, without feeding
    # that rounding back into the cool-down, could over- or under-state the
    # printed session total by up to one rep length relative to distance_m).
    cool_down_budget_estimate = max(
        ADDITIONAL_SWIM_MIN_COOL_DOWN_M, _round_100(distance_m * ADDITIONAL_SWIM_COOL_DOWN_SHARE)
    )
    main_set_budget = max(0, distance_m - warm_up - cool_down_budget_estimate)

    z2_range = f"{_format_pace_s(z2['pace_lo_s'])}-{_format_pace_s(z2['pace_hi_s'])}/100m"
    lines = [f"Warm-up: {warm_up}m easy, building to Z2 pace ({z2_range}) by the end."]

    if macro_block_name == "base":
        rep = ADDITIONAL_SWIM_BASE_BLOCK_REP_M if main_set_budget >= 1200 else 200
    else:
        rep = ADDITIONAL_SWIM_BUILD_BLOCK_REP_M if main_set_budget >= 800 else 100
    reps = max(1, round(main_set_budget / rep))

    remaining_for_cool_down = distance_m - warm_up - reps * rep
    # If rounding pushed the main set to consume (almost) everything,
    # give back one rep so the cool-down doesn't collapse toward 0m.
    while (
        reps > 1
        and remaining_for_cool_down < ADDITIONAL_SWIM_MIN_COOL_DOWN_M
        and remaining_for_cool_down + rep >= ADDITIONAL_SWIM_MIN_COOL_DOWN_M
    ):
        reps -= 1
        remaining_for_cool_down += rep
    cool_down = max(0, remaining_for_cool_down)

    # Template menu selection + rendering is fully data-driven -- see
    # `swim_coach.workout_templates` (the `WorkoutTemplate` YAML library,
    # `FORMAT_STRATEGIES`, and `render_main_set`'s deterministic
    # `selector % <template count>` rotation, same contract as before this
    # migration).
    lines.append(render_main_set(macro_block_name, selector, reps, rep, z2, z3, z4))

    lines.append(f"Cool-down: {cool_down}m easy choice of stroke.")

    if macro_block_name == "base":
        lines.append("Why: continuous aerobic-volume emphasis (base-block phase).")
    else:
        lines.append(
            "Why: race-pace-adjacent, broken-distance emphasis -- evidence-based "
            "phase shift (González-Ravé et al. 2021; Pla et al. 2019)."
        )
    return "\n".join(lines)


def _no_coach_pool_purpose(block_name: str) -> str:
    """Real, block-aware `purpose` text for a no-pool-coach weekday pool
    session -- i.e. `generate_week()`'s `athlete.has_pool_coach is False`
    branch, whose `structure` is authored by `_additional_swim_structure`
    (see that function's own docstring). Mirrors the tone of this file's
    other purpose strings (e.g. the long-swim session's "long open-water
    swim -- endurance and fueling-practice anchor of the week") instead of
    the generic dev-note text this replaces ("pool practice -- no pool
    coach on hand, structure authored below"), which said nothing about the
    actual training purpose.
    """
    if block_name == "base":
        return "Continuous aerobic volume — base-block emphasis"
    return f"Race-pace-adjacent volume — {block_name}-block emphasis"


# --- macro scaffold -----------------------------------------------------------


def scaffold_macro(
    athlete: Athlete,
    event: Event,
    start: date,
    current_weekly_volume_m: int,
    peak_weekly_volume_m: int | None = None,
) -> MacroPlan:
    """Build the base -> build -> peak -> taper macro scaffold toward `event`.

    Weeks available = whole weeks from the Monday on/after `start` to the
    Monday of the event's week (race week itself is not modeled as a macro
    block -- it's handled separately). Raises ValueError if that's fewer
    than MIN_MACRO_WEEKS.

    Block allocation runs back-to-front: taper and peak are sized first
    (longer for runways >= TAPER_RUNWAY_THRESHOLD_WEEKS weeks), then the
    remaining weeks split base/build (base getting ceil(BASE_SHARE)).

    peak_weekly_volume_m defaults to event.distance_m *
    PEAK_WEEKLY_VOLUME_X_EVENT_DISTANCE, but is never allowed to exceed
    current_weekly_volume_m compounded at WEEKLY_VOLUME_RAMP_CAP/week over
    the base+build weeks -- this applies even if peak_weekly_volume_m is
    passed explicitly. If clamped, a UserWarning records the original vs.
    clamped value.

    Each MacroBlock's `weekly_volume_target_m` is the block's END-of-block
    weekly volume (not its start) -- `generate_week` interpolates within a
    block from the previous block's end volume to this one.
    """
    start_monday = _monday_on_or_after(start)
    event_monday = _monday_of_week(event.event_date)
    weeks_available = (event_monday - start_monday).days // 7
    if weeks_available < MIN_MACRO_WEEKS:
        raise ValueError(
            f"only {weeks_available} whole weeks available before "
            f"{event.name!r}; need at least {MIN_MACRO_WEEKS} to periodize "
            "safely"
        )

    long_runway = weeks_available >= TAPER_RUNWAY_THRESHOLD_WEEKS
    taper_weeks = TAPER_WEEKS_LONG if long_runway else TAPER_WEEKS_SHORT
    peak_weeks = PEAK_WEEKS_LONG if long_runway else PEAK_WEEKS_SHORT
    remainder_weeks = weeks_available - taper_weeks - peak_weeks
    base_weeks = math.ceil(remainder_weeks * BASE_SHARE)
    build_weeks = remainder_weeks - base_weeks

    distance_driven_target = event.distance_m * PEAK_WEEKLY_VOLUME_X_EVENT_DISTANCE
    ramp_weeks = base_weeks + build_weeks
    ramp_seed = max(current_weekly_volume_m, MIN_RAMP_SEED_VOLUME_M)
    ramp_limited_max = ramp_seed * (1 + WEEKLY_VOLUME_RAMP_CAP) ** ramp_weeks
    candidate_peak = (
        peak_weekly_volume_m if peak_weekly_volume_m is not None else distance_driven_target
    )
    peak_volume = min(candidate_peak, ramp_limited_max)
    if peak_volume < candidate_peak:
        warnings.warn(
            f"peak_weekly_volume_m clamped from {candidate_peak:.0f}m to "
            f"{peak_volume:.0f}m by the {WEEKLY_VOLUME_RAMP_CAP:.0%}/week ramp "
            f"cap over {ramp_weeks} weeks",
            stacklevel=2,
        )
    peak_volume = round(peak_volume)

    base_end = round(peak_volume * BASE_END_VOLUME_SHARE_OF_PEAK)
    build_end = peak_volume
    peak_end = peak_volume
    taper_end = max(0, round(peak_volume * (1 - TAPER_WEEKLY_DECAY * taper_weeks)))

    block_specs = [
        ("base", base_weeks, base_end, "aerobic base"),
        ("build", build_weeks, build_end, "race-specific build"),
        ("peak", peak_weeks, peak_end, "peak volume"),
        ("taper", taper_weeks, taper_end, "taper"),
    ]

    blocks: list[MacroBlock] = []
    cursor = start_monday
    for name, n_weeks, end_target, focus in block_specs:
        block_end = cursor + timedelta(weeks=n_weeks) - timedelta(days=1)
        blocks.append(
            MacroBlock(
                name=name,  # type: ignore[arg-type]
                start_date=cursor,
                end_date=block_end,
                weekly_volume_target_m=end_target,
                focus=focus,
            )
        )
        cursor = block_end + timedelta(days=1)

    return MacroPlan(id=uuid4(), athlete_id=athlete.id, event_id=event.id, blocks=blocks)


def _find_block(macro: MacroPlan, week_start: date) -> tuple[int, MacroBlock]:
    for index, block in enumerate(macro.blocks):
        if block.start_date <= week_start <= block.end_date:
            return index, block
    raise ValueError(f"{week_start} is outside this macro plan's date range")


def _block_start_volume(macro: MacroPlan, block_index: int, block: MacroBlock) -> float:
    """The volume the block's interpolation ramps *from*.

    For every block after the first, that's simply the previous block's
    end-of-block volume. The first block (base) has no previous block to
    ramp from, and MacroPlan doesn't carry the original
    current_weekly_volume_m used to size it -- so its start volume is
    back-derived from its own end volume, by inverting the same
    WEEKLY_VOLUME_RAMP_CAP used elsewhere: a `base_weeks`-week-long, simple
    (non-compounding) accumulation of `WEEKLY_VOLUME_RAMP_CAP * start` per
    week. Combined with linear interpolation (see generate_week), this
    guarantees the first block's week-over-week increase never exceeds
    WEEKLY_VOLUME_RAMP_CAP, by construction, without needing to thread the
    athlete's original current volume through every call.
    """
    if block_index == 0:
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        return block.weekly_volume_target_m / (1 + WEEKLY_VOLUME_RAMP_CAP * weeks_in_block)
    return macro.blocks[block_index - 1].weekly_volume_target_m


def generate_week(
    athlete: Athlete,
    macro: MacroPlan,
    iso_week: str,
    week_start: date,
    event_format: EventFormat = "single_day",
) -> WeekPlan:
    """Generate one week's sessions.

    Weekly target volume interpolates *linearly* within the containing
    block, from the block's start volume (see `_block_start_volume`) to
    its end volume (`block.weekly_volume_target_m`), reaching the end
    volume exactly on the block's final week.

    Sessions emitted:
      - one pool session per athlete.pool_schedule entry: when
        `athlete.has_pool_coach` is True (the default), a content-less
        `pool_coach` placeholder (unchanged pre-existing behavior -- a real
        masters coach hands out that session's content post-hoc, at
        POOL_SESSION_EST_M/DEFAULT_POOL_SESSION_MIN, a volume that doesn't
        scale with this project's periodization). When False, an
        `ai_coach` session with real warm-up/main-set/cool-down structure
        authored by `_additional_swim_structure` instead -- here the
        engine itself is authoring periodization-aware content, so each
        pool day's distance/duration is derived from target_volume_m
        (reserving the long swim's share first, splitting the remainder
        across the week's pool days, floored at
        NO_COACH_POOL_SESSION_FLOOR_M) rather than reusing the pool-coach
        placeholder's fixed estimate.
      - the week's long-swim volume (LONG_SWIM_SHARE of weekly target,
        capped during taper -- see below), arranged per `event_format`:
          * "single_day" (default, matches `Event.event_format`'s default
            and preserves pre-Day-4 behavior exactly): one continuous
            Saturday open-water swim.
          * "multi_day_stage": split across back-to-back Saturday +
            Sunday swims (STAGE_SATURDAY_SHARE / remainder), with no
            separate Sunday recovery session that week (Sunday is now a
            swim day) -- see ROADMAP.md "Event format parameter".
      - STRENGTH_SESSIONS_PER_WEEK strength sessions, placed on days
        without pool practice where possible
      - one recovery/mobility day (Sunday) -- "single_day" format only;
        "multi_day_stage" occupies Sunday with the second stage swim
        instead (recovery emphasis shifts to refueling between the two
        stage swims, noted in each stage session's purpose/structure).
      - if pool-independent volume remains (weekly target minus pool
        estimates minus long swim) and it's >= MIN_ADDITIONAL_SWIM_M, one
        additional ai_coach swim_ow session for the remainder; otherwise
        the remainder (which may be negative, if pool estimates alone
        exceed target) is absorbed into the long swim, floored at 0.

    In the taper block, the long swim is additionally capped at the last
    non-taper (i.e. peak block) week's long swim distance, times
    (1 - TAPER_WEEKLY_DECAY * weeks_into_taper), floored at 0 -- this is
    the explicit per-week decay rule from ROADMAP.md [Source 01], applied
    directly to the (pre-split, total) long swim regardless of what the
    general linear weekly-target interpolation computes for that week.

    Only the weekend long-swim *arrangement* depends on `event_format` --
    macro block volumes are unaffected either way (ROADMAP.md: "It does
    not change the macro block volumes ... it changes weekly composition").
    """
    if event_format not in ("single_day", "multi_day_stage"):
        raise ValueError(
            f"unknown event_format: {event_format!r}, must be 'single_day' or "
            "'multi_day_stage'"
        )
    block_index, block = _find_block(macro, week_start)
    weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
    week_index_in_block = (week_start - block.start_date).days // 7
    if not (0 <= week_index_in_block < weeks_in_block):
        raise ValueError(f"{week_start} is not a valid week-start within block {block.name!r}")

    start_volume = _block_start_volume(macro, block_index, block)
    end_volume = block.weekly_volume_target_m
    frac = (week_index_in_block + 1) / weeks_in_block
    target_volume_m = round(start_volume + (end_volume - start_volume) * frac)

    pool_offsets = {_pool_day_offset(entry) for entry in athlete.pool_schedule}
    pace_s = _z2_pace_s_per_100m(athlete)
    css_pace_s = athlete.css_pace_s_per_100m or DEFAULT_CSS_PACE_S_PER_100M

    no_coach_pool_distance_m = 0
    if not athlete.has_pool_coach and athlete.pool_schedule:
        # The engine itself is authoring this content (no real masters
        # coach's independent volume to defer to), so each pool day's
        # distance must scale with target_volume_m: reserve the long swim's
        # share first (same LONG_SWIM_SHARE used below), split what's left
        # evenly across the week's pool days, floored so a genuinely-early
        # week never produces a 0m or absurdly tiny session.
        reserved_for_long_swim = target_volume_m * LONG_SWIM_SHARE
        remaining_for_pool = max(0.0, target_volume_m - reserved_for_long_swim)
        raw_per_day = remaining_for_pool / len(athlete.pool_schedule)
        no_coach_pool_distance_m = max(NO_COACH_POOL_SESSION_FLOOR_M, _round_100(raw_per_day))

    sessions: list[Session] = []
    for entry in athlete.pool_schedule:
        offset = _pool_day_offset(entry)
        if athlete.has_pool_coach:
            # Unchanged from before has_pool_coach existed -- a real masters
            # coach hands out this session's content post-hoc, so the
            # engine can only placeholder it (see module docstring).
            sessions.append(
                Session(
                    id=uuid4(),
                    athlete_id=athlete.id,
                    date=week_start + timedelta(days=offset),
                    sport="swim_pool",
                    source="pool_coach",
                    duration_min=DEFAULT_POOL_SESSION_MIN,
                    distance_m=POOL_SESSION_EST_M,
                    intensity={"anchor": "rpe"},
                    purpose="coached pool practice — content assigned by pool coach after session",
                    structure=None,
                    status="planned",
                )
            )
        else:
            # No masters coach on deck for this pool slot -- the engine
            # authors real warm-up/main-set/cool-down structure itself,
            # reusing the same generator the "additional" pool-independent
            # session already uses (`_additional_swim_structure`). Distance
            # and duration scale with target_volume_m via
            # no_coach_pool_distance_m above, rather than reusing the
            # pool-coach placeholder's fixed POOL_SESSION_EST_M estimate.
            sessions.append(
                Session(
                    id=uuid4(),
                    athlete_id=athlete.id,
                    date=week_start + timedelta(days=offset),
                    sport="swim_pool",
                    source="ai_coach",
                    duration_min=max(
                        _duration_min_for_distance(no_coach_pool_distance_m, pace_s), 15.0
                    ),
                    distance_m=no_coach_pool_distance_m,
                    intensity={"anchor": "rpe"},
                    purpose=_no_coach_pool_purpose(block.name),
                    structure=_additional_swim_structure(
                        block.name, no_coach_pool_distance_m, css_pace_s, week_index_in_block
                    ),
                    status="planned",
                )
            )
    if athlete.has_pool_coach:
        pool_total_m = len(athlete.pool_schedule) * POOL_SESSION_EST_M
    else:
        pool_total_m = len(athlete.pool_schedule) * no_coach_pool_distance_m

    long_swim_distance = _round_100(target_volume_m * LONG_SWIM_SHARE)
    if block.name == "taper":
        peak_block = macro.blocks[block_index - 1]
        peak_long_swim = _round_100(peak_block.weekly_volume_target_m * LONG_SWIM_SHARE)
        weeks_into_taper = week_index_in_block + 1
        cap = max(0, _round_100(peak_long_swim * (1 - TAPER_WEEKLY_DECAY * weeks_into_taper)))
        long_swim_distance = min(long_swim_distance, cap)
    long_swim_distance = max(0, long_swim_distance)

    remainder = target_volume_m - pool_total_m - long_swim_distance
    additional_distance = 0
    if remainder >= MIN_ADDITIONAL_SWIM_M:
        additional_distance = remainder
    elif remainder != 0:
        long_swim_distance = max(0, long_swim_distance + remainder)

    if event_format == "multi_day_stage":
        saturday_distance = _round_100(long_swim_distance * STAGE_SATURDAY_SHARE)
        sunday_distance = max(0, long_swim_distance - saturday_distance)
        sessions.append(
            Session(
                id=uuid4(),
                athlete_id=athlete.id,
                date=week_start + timedelta(days=_WEEKDAY_OFFSETS["sat"]),
                sport="swim_ow",
                source="ai_coach",
                duration_min=max(_duration_min_for_distance(saturday_distance, pace_s), 15.0),
                distance_m=saturday_distance,
                intensity={"zone": "Z2", "anchor": "css_pace"},
                purpose="stage day 1 (Saturday) — back-to-back long open-water swim",
                structure=None,
                status="planned",
            )
        )
        sessions.append(
            Session(
                id=uuid4(),
                athlete_id=athlete.id,
                date=week_start + timedelta(days=_WEEKDAY_OFFSETS["sun"]),
                sport="swim_ow",
                source="ai_coach",
                duration_min=max(_duration_min_for_distance(sunday_distance, pace_s), 15.0),
                distance_m=sunday_distance,
                intensity={"zone": "Z2", "anchor": "css_pace"},
                purpose="stage day 2 (Sunday) — swum on Saturday's fatigue; refuel/recover aggressively overnight between stage days",
                structure=None,
                status="planned",
            )
        )
    else:
        sessions.append(
            Session(
                id=uuid4(),
                athlete_id=athlete.id,
                date=week_start + timedelta(days=_WEEKDAY_OFFSETS["sat"]),
                sport="swim_ow",
                source="ai_coach",
                duration_min=max(_duration_min_for_distance(long_swim_distance, pace_s), 15.0),
                distance_m=long_swim_distance,
                intensity={"zone": "Z2", "anchor": "css_pace"},
                purpose="long open-water swim — endurance and fueling-practice anchor of the week",
                structure=None,
                status="planned",
            )
        )

    strength_offsets = _pick_days(
        STRENGTH_SESSIONS_PER_WEEK, excluded=pool_offsets | {_WEEKDAY_OFFSETS["sat"], _WEEKDAY_OFFSETS["sun"]}
    )
    for session_index, offset in enumerate(strength_offsets):
        sessions.append(
            Session(
                id=uuid4(),
                athlete_id=athlete.id,
                date=week_start + timedelta(days=offset),
                sport="strength",
                source="ai_coach",
                duration_min=STRENGTH_SESSION_MIN,
                distance_m=None,
                intensity={"anchor": "rpe"},
                purpose=(
                    "dryland shoulder strength — rotator-cuff/scapular-stability "
                    "strength & balance"
                ),
                structure=_strength_session_structure(session_index),
                status="planned",
            )
        )

    if event_format != "multi_day_stage":
        # "multi_day_stage" occupies Sunday with the second stage swim
        # instead -- see docstring.
        sessions.append(
            Session(
                id=uuid4(),
                athlete_id=athlete.id,
                date=week_start + timedelta(days=_WEEKDAY_OFFSETS["sun"]),
                sport="recovery",
                source="ai_coach",
                duration_min=RECOVERY_SESSION_MIN,
                distance_m=None,
                intensity={"zone": "Z1", "anchor": "rpe"},
                purpose="mobility / full rest",
                structure=None,
                status="planned",
            )
        )

    if additional_distance:
        additional_offset = _pick_days(
            1,
            excluded=pool_offsets
            | set(strength_offsets)
            | {_WEEKDAY_OFFSETS["sat"], _WEEKDAY_OFFSETS["sun"]},
        )[0]
        sessions.append(
            Session(
                id=uuid4(),
                athlete_id=athlete.id,
                date=week_start + timedelta(days=additional_offset),
                sport="swim_ow",
                source="ai_coach",
                duration_min=_duration_min_for_distance(additional_distance, pace_s),
                distance_m=additional_distance,
                intensity={"zone": "Z2", "anchor": "css_pace"},
                purpose="additional pool-independent aerobic volume",
                structure=_additional_swim_structure(
                    block.name, additional_distance, css_pace_s, week_index_in_block
                ),
                status="planned",
            )
        )

    return WeekPlan(
        id=uuid4(),
        athlete_id=athlete.id,
        iso_week=iso_week,
        meso_block=block.name,
        focus=block.focus,
        target_volume_m=target_volume_m,
        sessions=sessions,
        adaptation_rationale=None,
        draft=False,
    )
