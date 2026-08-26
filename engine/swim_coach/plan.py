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

from swim_coach.models import (
    Athlete,
    Event,
    MacroBlock,
    MacroPlan,
    RaceWeekChecklistItem,
    Session,
    WeekPlan,
    WorkoutLoad,
    WorkoutRepeat,
    WorkoutStep,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.workout_templates import (
    TemplatePreference,
    build_main_set_step,
    render_prose,
    resolve_template,
)
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

SESSION_ADJUSTMENT_INCREASE_CAP_PCT = 25.0
# Coach judgment: a single already-planned session, adjusted in place via
# `adjust_session`/`backend/app/tools.py`'s `propose_session_adjustment` (e.g.
# "I'm feeling strong, can you give me more today?"), may be scaled UP by at
# most this percentage in one request. Distinct from, and not a replacement
# for, WEEKLY_VOLUME_RAMP_CAP above: that cap governs how fast the *whole
# week's* target volume may climb build-to-build; this one bounds a single
# one-off ad-hoc increase to ONE session's own volume/intensity, requested
# mid-week outside the normal periodization math entirely. No swim-specific
# trial informs this exact number -- it is deliberately smaller than the
# weekly cap (a single session has far less room to safely absorb a surprise
# jump than a whole week does) and large enough to be a meaningful "yes, more"
# rather than a token gesture. No cap is applied to the "reduce" direction --
# an athlete asking for LESS today (fatigue, time-crunched) is never the
# unsafe direction. library/03-periodization.md (to be authored).

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

STRENGTH_EXERCISE_REFERENCE_URLS: dict[str, str] = {
    "Internal rotation at 90° abduction": "https://www.rehabhero.ca/exercise/90-degrees-internal-rotation",
    "External rotation at 90° abduction": "https://www.rehabhero.ca/exercise/90-degrees-external-rotation",
    "Scapular punches": "https://www.rehabhero.ca/exercise/serratus-punch",
    'Scapular retraction ("Ts")': "https://www.rehabhero.ca/exercise/prone-t-raise",
    'Retraction with upward rotation ("Ys")': "https://www.rehabhero.ca/exercise/prone-y-raise",
    "3 x 10 goblet squat or bodyweight squat": "https://www.rehabhero.ca/exercise/goblet-squat",
    "3 x 10 per side single-leg Romanian deadlift (or bodyweight equivalent)": (
        "https://www.rehabhero.ca/exercise/single-leg-deadlift"
    ),
    "3 x 10 plank or dead-bug core hold (30-45s each side)": "https://www.rehabhero.ca/exercise/plank",
}
# Coach judgment: these are technique-demonstration links (Rehab Hero, a
# physiotherapy exercise-library site), not research citations -- they carry
# no scientific claim about dosing/efficacy (that's STRENGTH_CORE_EXERCISES'
# and STRENGTH_FULL_BODY_ADDITION's own [EVIDENCE]/Coach judgment comments
# above), so they are deliberately NOT tagged [EVIDENCE: ...] or
# [ADAPTED: ...] per CLAUDE.md's evidence-discipline rule -- that tagging is
# for claims driving engine constants, not "here's what this move looks
# like" demo links. The plank entry covers the "plank or dead-bug" step
# (Rehab Hero also has a dead-bug page; one URL per step, plank is the
# named-first option in that step's label). Looked up by `.get()` wherever
# used, never `[]` -- a canned exercise added to either tuple above without a
# matching entry here is a no-op (`None`), never an error.

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


def _strength_session_structure_template(session_index: int) -> WorkoutStructure:
    """The `WorkoutStructure` TEMPLATE for a strength session -- same
    content/rationale as `_strength_session_structure` (see that thin
    prose-wrapper's docstring for the block/phase/dosing-progression
    rationale, which is unchanged here), just built as structured `WorkoutStep`/
    `WorkoutRepeat` nodes instead of hand-concatenated prose lines.

    The "2 sets x 10 reps each" rotator-cuff/scapular-stability core is a
    genuine `WorkoutRepeat(repeat_mode="count", count=2, ...)` wrapping one
    `WorkoutStep` per exercise (real structural fidelity, not just a bullet
    list) -- this is this migration's one production use of a real
    `WorkoutRepeat`. The general full-body addition's three items each
    already carry their own "3 x 10 ..." dosing baked into the bullet text
    itself (an existing asymmetry in the real content -- unlike the core
    exercises, there's no single shared rep scheme across all three), so
    they're standalone `WorkoutStep`s rather than a second `WorkoutRepeat`.

    Every `WorkoutLoad` here is `basis="bodyweight"` -- this session type has
    no per-exercise 1RM data collected anywhere yet (see
    `workout_templates.resolve_template`'s docstring), so `resolve_template`
    resolving against 1RM is a documented no-op on this real content today.
    Section headers and the trailing `Why:` line are `role="open"` steps
    (verbatim athlete-facing text, not really "workout structure" -- see
    `workout_templates.render_prose`'s docstring) rather than a field on
    `WorkoutStructure` itself, since the model has none.
    """
    items: list[WorkoutStep | WorkoutRepeat] = [
        WorkoutStep(
            label="Rotator-cuff / scapular-stability core (2 sets x 10 reps each):",
            role="open",
            duration_kind="open",
            modality="strength",
        ),
        WorkoutRepeat(
            repeat_mode="count",
            count=2,
            steps=[
                WorkoutStep(
                    label=exercise,
                    role="steady",
                    duration_kind="reps",
                    duration_value=10,
                    load=WorkoutLoad(basis="bodyweight"),
                    modality="strength",
                    exercise_name=exercise,
                    reference_url=STRENGTH_EXERCISE_REFERENCE_URLS.get(exercise),
                )
                for exercise in STRENGTH_CORE_EXERCISES
            ],
        ),
    ]
    if session_index % 2 == 1:
        items.append(
            WorkoutStep(
                label="General full-body (layered in as time allows):",
                role="open",
                duration_kind="open",
                modality="strength",
            )
        )
        items.extend(
            WorkoutStep(
                label=exercise,
                role="steady",
                duration_kind="open",
                load=WorkoutLoad(basis="bodyweight"),
                modality="strength",
                exercise_name=exercise,
                reference_url=STRENGTH_EXERCISE_REFERENCE_URLS.get(exercise),
            )
            for exercise in STRENGTH_FULL_BODY_ADDITION
        )
    items.append(
        WorkoutStep(
            label=(
                "Why: rotator-cuff strength/balance, reduces shoulder-injury risk "
                "(Hibberd 2012; Manske 2015; Tavares et al. 2025)."
            ),
            role="open",
            duration_kind="open",
            modality="strength",
        )
    )
    return WorkoutStructure(items=items)


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

    Byte-identical (unchanged output) to before the `WorkoutStructure`
    migration -- now a thin `render_prose` wrapper over
    `_strength_session_structure_template` instead of hand-concatenated
    lines, so this text and `Session.structured` (built by resolving that
    same template, see `generate_week`) share one source of truth and can
    never drift apart. See `tests/unit/test_plan.py`'s parity proof.
    """
    return render_prose(_strength_session_structure_template(session_index))


def _additional_swim_structure(
    macro_block_name: str,
    distance_m: int,
    css_pace_s: float,
    selector: int = 0,
    template_preference: TemplatePreference | None = None,
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
    through to `_additional_swim_structure_template` (structured) /
    `build_main_set_step` (its main-set step) -- both share
    `workout_templates._select_main_set_template`'s selection logic with the
    legacy `render_main_set`, which deterministically picks one template
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

    `template_preference` (optional): passed straight through to
    `_additional_swim_structure_template`/`build_main_set_step` -- narrows
    the main-set template rotation to candidates matching the preference
    (e.g. a coach-requested `purpose`/`equipment_any`/`interval_style`)
    instead of the default blind `selector % count` pick. See
    `swim_coach.workout_templates.TemplatePreference`.
    """
    if distance_m <= 0:
        return "No additional pool-independent volume this week."

    template = _additional_swim_structure_template(
        macro_block_name, distance_m, css_pace_s, selector, template_preference
    )
    return render_prose(template)


def _additional_swim_structure_template(
    macro_block_name: str,
    distance_m: int,
    css_pace_s: float,
    selector: int = 0,
    template_preference: TemplatePreference | None = None,
) -> WorkoutStructure:
    """Build the `WorkoutStructure` TEMPLATE for the "additional"
    pool-independent aerobic swim_ow session -- the structural counterpart
    to `_additional_swim_structure`'s prose (see that function's own
    docstring for the full warm-up/cool-down/main-set-format-menu rationale
    and citations, which is unchanged here). Callers must guard
    `distance_m <= 0` themselves (mirroring `_additional_swim_structure`'s
    own early return) -- there's no meaningful `WorkoutStructure` for "no
    additional volume this week."

    The warm-up/cool-down steps' `label`s are built here using the SAME
    concrete, already-CSS-resolved `z2`/`z3`/`z4` zone dicts as the legacy
    prose function (every real call site already has the athlete's CSS
    available at this point -- see `generate_week`) -- this is what
    guarantees byte-identical prose without duplicating the warm-up/
    cool-down text-formatting logic a second time. Each step's `target`
    field nonetheless stays the relative `basis="zone"` marker (not the
    resolved pace numbers already reflected in its label) until
    `workout_templates.resolve_template` is called -- `render_prose` never
    reads `target`, so this doesn't affect the prose parity proof, and it
    keeps the model's relative/resolved distinction real for any consumer
    (e.g. a future Garmin export) that DOES read `target`.
    """
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
    warmup_step = WorkoutStep(
        label=f"{warm_up}m easy, building to Z2 pace ({z2_range}) by the end.",
        role="warmup",
        duration_kind="distance_m",
        duration_value=warm_up,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )

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
    # `FORMAT_STRATEGIES`, and `build_main_set_step`'s deterministic
    # `selector % <template count>` rotation, same contract as before this
    # migration).
    main_set_step = build_main_set_step(
        macro_block_name, selector, reps, rep, z2, z3, z4, template_preference
    )

    cooldown_step = WorkoutStep(
        label=f"{cool_down}m easy choice of stroke.",
        role="cooldown",
        duration_kind="distance_m",
        duration_value=cool_down,
        modality="swim",
    )

    if macro_block_name == "base":
        why_label = "Why: continuous aerobic-volume emphasis (base-block phase)."
    else:
        why_label = (
            "Why: race-pace-adjacent, broken-distance emphasis -- evidence-based "
            "phase shift (González-Ravé et al. 2021; Pla et al. 2019)."
        )
    why_step = WorkoutStep(label=why_label, role="open", duration_kind="open", modality="swim")

    return WorkoutStructure(items=[warmup_step, main_set_step, cooldown_step, why_step])


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


# --- race week: final-taper-week content ------------------------------------
# Distinct from the taper block's own VOLUME/duration math above (TAPER_WEEKS_
# LONG/SHORT, TAPER_WEEKLY_DECAY) -- this section adds a final, more
# prescriptive CONTENT layer on top of whichever week already comes out of
# that math as the taper block's last week, without changing a single one of
# its volume numbers. See `_race_week_checklist`'s own docstring and
# `library/15-race-week.md` for the full citations.

RACE_WEEK_PRIORITY = "A"
# Coach judgment / engineering convention: race-week content only fires for
# the athlete's ACTIVE, priority "A" target event -- matches how
# `Event.priority` is documented (a free-text convention, "A"/"B", never
# itself gated on anywhere else in this engine -- see `Event.priority`'s own
# docstring and `Event.active`'s "changes how the coach *talks about* events
# ... never which events lookups find" note in models.py) but genuinely new
# here: unlike a read/lookup, firing an athlete-facing race-week checklist
# for a B-priority tune-up race or a soft-deleted/no-longer-happening event
# would be actively wrong, not merely stale. Compared case-insensitively
# (`.strip().upper()`) since `priority` carries no format validation.

CARB_LOAD_WINDOW_START_DAYS_OUT = 3
# **[ADAPTED: general-endurance] Confidence: high.** `Burke, Hawley, Wong &
# Jeukendrup (2011)`, "Carbohydrates for training and competition" --
# *Journal of Sports Sciences*, 29(sup1):S17-S27 -- the consensus review
# behind the now-standard 10-12 g/kg/day carbohydrate-loading target for
# 36-48h before events lasting >90 minutes in already well-trained athletes.
# `Bussau, Fairchild, Rao, Steele & Fournier (2002)`, "Carbohydrate loading
# in human muscle: an improved 1 day protocol" -- *European Journal of
# Applied Physiology*, 87(3):290-295 -- is the direct evidence that a
# well-trained athlete needs NO depletion phase: 8 endurance-trained
# athletes reached near-maximal muscle glycogen (95 -> 180 mmol/kg wet mass)
# within 1 day of 10 g/kg/day high-glycemic-index carbohydrate + rest, with
# 2 further days of the same diet adding no further store. Both papers are
# cited in `library/reference_list.md`'s "Race-week preparation" section.
# This constant models the window's EARLIER (72h-out) boundary as a whole
# calendar day out from `Event.event_date` -- deliberately the more
# conservative, earlier edge of the literature's "36-72h" range, so the
# athlete has the full window available rather than being told to start on
# its last, most time-pressured day. PROVISIONAL: collapsing a 36-72h
# *duration* range to a single whole-calendar-day marker is coach judgment,
# not itself a cited figure -- an event's exact start time (not modeled by
# `Event` today) would let this be more precise.

BODYWORK_WINDOW_DAYS_OUT = 5
# **Coach judgment / practitioner convention -- NOT a performance-evidence
# citation.** `Weerapong, Hume & Kolt (2005)`, "The Mechanisms of Massage
# and Effects on Performance, Muscle Recovery and Injury Prevention" --
# *Sports Medicine*, 35(3):235-256 -- and the more recent `Dakić, Toskić,
# Ilić, Đurić, Dopsaj & Šimenko (2023)` systematic review, "The Effects of
# Massage Therapy on Sport and Exercise Performance" -- *Sports*,
# 11(6):110 -- both converge on the same real but modest finding: massage
# shows little to no evidence of a direct PERFORMANCE benefit, but a
# consistent benefit to perceived soreness/fatigue and psychological state
# (reduced anxiety/stress, improved mood and perceived recovery).
# `[ADAPTED: general-endurance] Confidence: medium` for that soreness/
# psychological-benefit claim itself (both are narrative/systematic
# reviews spanning many sports, not swim-specific). The specific "3-5 days
# out, light activation/relaxation rather than deep/aggressive work" TIMING
# used here is a separate, weaker claim: it is widespread sports-massage-
# practitioner convention (enough recovery buffer before race day for any
# post-massage soreness to resolve, without losing the perceived-relaxation
# benefit to being too far out) -- NOT independently verified against a
# journal source this session, and must not be oversold as a cited
# performance intervention. This constant picks the window's earlier,
# more conservative edge (5 days out, not 3) for the same reason
# `CARB_LOAD_WINDOW_START_DAYS_OUT` picks its own early edge: more buffer
# before race day, and (not by design, just this athlete's specific
# event's weekday) it happens to land on the final taper week's own last
# (Sunday, recovery-day) session for Renee's actual Friday-race calendar --
# see `test_plan.py`'s race-week tests for the exact date math.

RACE_WEEK_LOGISTICS_LABELS: tuple[str, ...] = (
    "If traveling to the race venue, arrive with enough days to spare to "
    "acclimatize to the local time zone and water conditions before race "
    "day.",
    "Do a final full run-through of your race-day fueling plan (carbohydrate "
    "product, delivery method/feeding schedule, backup options) against the "
    "in-race protocol you've actually practiced in training.",
    "Confirm on-water support (kayak/boat escort, sighting/navigation plan, "
    "safety contacts) with race organizers.",
)
# Coach judgment, athlete-agnostic by construction -- these three items are
# GENERIC race-day-logistics prompts (any open-water athlete travelling to a
# venue, rehearsing a fueling plan, or needing on-water support benefits
# from checking all three), not hardcoded to any one athlete's race. They
# read as directly relevant to Renee's own Greece trip specifically because
# her real `Event` data (open-water, travel required, kayak-supported) is
# what it is -- see `athletes/renee/notes/decisions.md`'s 2026-07-05 entries
# and `athletes/renee/plan/weeks/2026-W29.yaml`'s existing "kayak support"
# dress-rehearsal language for the precedent this generalizes from -- not
# because Greece, kayaks, or any other athlete-specific noun is named here.
# The water-temperature/wetsuit-acclimatization detail in the first item is
# deliberately left generic prose (not a computed `water_temp_c` number)
# since `_race_week_checklist` below appends that number separately, only
# when `Event.water_temp_c` is actually set.


def _race_week_checklist(event: Event, week_start: date) -> list[RaceWeekChecklistItem]:
    """The final taper week's race-week content: a carbohydrate-loading
    item, a bodywork item, and the athlete-facing logistics checklist --
    see this module's `CARB_LOAD_WINDOW_START_DAYS_OUT`/
    `BODYWORK_WINDOW_DAYS_OUT`/`RACE_WEEK_LOGISTICS_LABELS` for the citations
    and rationale behind each.

    Every item's `date` is computed directly from `event.event_date` -- NOT
    from `week_start` -- specifically because the two physiologically-timed
    windows (carb-load, bodywork) do not reliably land inside the calling
    week's own 7 days (see `RaceWeekChecklistItem`'s docstring for why: a
    race that isn't itself on a Monday pushes some of these dates into the
    following, not-yet-generated event week). The three logistics items
    carry no comparable single physiologically-critical day, so they're
    anchored to `week_start` itself (the final taper week's Monday) --
    Coach judgment: settle logistics EARLY in the final week, distinctly
    separate from the later, evidence-timed physiological windows above.
    """
    carb_load_date = event.event_date - timedelta(days=CARB_LOAD_WINDOW_START_DAYS_OUT)
    bodywork_date = event.event_date - timedelta(days=BODYWORK_WINDOW_DAYS_OUT)

    items = [
        RaceWeekChecklistItem(
            date=carb_load_date,
            category="carb_load",
            label=(
                "Begin carbohydrate loading: 10-12 g/kg body weight/day, "
                "continuing through race day (Burke et al. 2011; Bussau et "
                "al. 2002 -- no depletion phase needed at this fitness "
                "level). Keep training volume low through this window; do "
                "not skip it."
            ),
        ),
        RaceWeekChecklistItem(
            date=bodywork_date,
            category="bodywork",
            label=(
                "Light activation/relaxation bodywork or massage session if "
                "available -- 3-5 days out, NOT the final 1-2 days. Modest, "
                "real evidence for perceived soreness/fatigue and mental "
                "readiness (Weerapong, Hume & Kolt 2005; Dakić et al. 2023), "
                "not a proven direct performance intervention -- keep it "
                "light, not deep/aggressive work this close to race day."
            ),
        ),
    ]
    for label in RACE_WEEK_LOGISTICS_LABELS:
        items.append(RaceWeekChecklistItem(date=week_start, category="logistics", label=label))

    if event.water_temp_c is not None:
        suit_note = "no wetsuit" if not event.wetsuit else "wetsuit"
        items.append(
            RaceWeekChecklistItem(
                date=week_start,
                category="logistics",
                label=(
                    f"Confirm final race-conditions plan for ~{event.water_temp_c:g}°C "
                    f"water ({suit_note}) -- last chance to bank open-water "
                    "acclimatization time before race day."
                ),
            )
        )
    return items


def generate_week(
    athlete: Athlete,
    macro: MacroPlan,
    iso_week: str,
    week_start: date,
    event_format: EventFormat = "single_day",
    template_preference: TemplatePreference | None = None,
    event: Event | None = None,
) -> WeekPlan:
    """Generate one week's sessions.

    `event` (optional, defaults to `None` -- every existing call site keeps
    producing byte-identical output unless updated to pass it): when
    supplied AND it is the athlete's ACTIVE, priority `"A"` target event
    (`RACE_WEEK_PRIORITY`) AND `event.id == macro.event_id` (the macro this
    week belongs to was actually scaffolded toward this same event) AND
    this week is the LAST week of a `"taper"` block, the returned
    `WeekPlan.race_week_checklist` is populated with the final-taper-week
    race-prep content (carbohydrate-loading window, bodywork window,
    logistics checklist) -- see `_race_week_checklist`'s own docstring and
    `library/15-race-week.md`. In every other
    case (no `event` passed, wrong/inactive/non-"A" event, or any week that
    isn't the taper block's final one) `race_week_checklist` stays the
    model's own default empty list -- an ordinary taper week is otherwise
    untouched. This deliberately does NOT change `target_volume_m`, the
    long-swim taper-decay cap, or any other volume/duration math above --
    purely additive content layered on top of whatever this function
    already computes.

    `template_preference` (optional): forwarded to every call site that
    picks a main-set template via the "additional pool-independent swim"
    generator (`_additional_swim_structure`/`_additional_swim_structure_
    template`) -- the no-pool-coach weekday pool sessions and the pool-
    independent "additional" swim_ow session, both of which otherwise land
    on whatever the deterministic `selector % count` rotation picks. Lets a
    chat request like "give me more kettlebell work this week" (via
    `backend/app/tools.py`'s `create_week_plan`/`replace_week_plan`) actually
    change which template gets selected. Does NOT affect the strength
    session template (`_strength_session_structure_template` has its own,
    separate rotation, out of scope for this pass) or the long swim/recovery
    sessions (neither uses the template library at all).

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
                        block.name,
                        no_coach_pool_distance_m,
                        css_pace_s,
                        week_index_in_block,
                        template_preference,
                    ),
                    structured=(
                        resolve_template(
                            _additional_swim_structure_template(
                                block.name,
                                no_coach_pool_distance_m,
                                css_pace_s,
                                week_index_in_block,
                                template_preference,
                            ),
                            athlete,
                        )
                        if no_coach_pool_distance_m > 0
                        else None
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
                structured=resolve_template(
                    _strength_session_structure_template(session_index), athlete
                ),
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
                    block.name,
                    additional_distance,
                    css_pace_s,
                    week_index_in_block,
                    template_preference,
                ),
                structured=resolve_template(
                    _additional_swim_structure_template(
                        block.name,
                        additional_distance,
                        css_pace_s,
                        week_index_in_block,
                        template_preference,
                    ),
                    athlete,
                ),
                status="planned",
            )
        )

    race_week_checklist: list[RaceWeekChecklistItem] = []
    is_final_taper_week = block.name == "taper" and week_index_in_block == weeks_in_block - 1
    if (
        event is not None
        and is_final_taper_week
        and event.id == macro.event_id
        and event.active
        and event.priority.strip().upper() == RACE_WEEK_PRIORITY
    ):
        race_week_checklist = _race_week_checklist(event, week_start)

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
        race_week_checklist=race_week_checklist,
    )


# --- adjust_session: same-session, in-place volume/intensity scaling --------
# Distinct from everything above `generate_week` builds (a brand-new week
# from the macro) -- this scales the content of ONE session that already
# exists on an already-generated, already-persisted week, for a request like
# "I'm fatigued today, can you make this shorter with less sprint work?" or
# "I'm feeling strong, give me a bit more." See `backend/app/tools.py`'s
# `propose_session_adjustment` for the draft-then-confirm tool wrapping this.

# Leaf-step rounding granularities below -- coarse enough that a scaled
# distance/time/rep value still reads as a sane, athlete-legible number
# (e.g. "1,575m" is a worse number to hand an athlete than "1,575" rounded to
# "1,575" -- rounding to the nearest 25m keeps it clean) rather than a
# precision requirement of any kind. Coach judgment, no citation.
_ADJUSTMENT_DISTANCE_ROUND_M = 25.0
_ADJUSTMENT_TIME_ROUND_S = 30.0

# Floors below keep a heavily-reduced item from collapsing to a
# contentless 0 -- an item that still exists in the tree should still read
# as a real (if small) rep/segment, not a step with nothing in it.
_ADJUSTMENT_MIN_DISTANCE_M = 25.0
_ADJUSTMENT_MIN_TIME_S = 30.0
_ADJUSTMENT_MIN_REPS = 1.0
_ADJUSTMENT_MIN_REPEAT_COUNT = 1
_ADJUSTMENT_MIN_REPEAT_DURATION_S = 60.0

# Roles that make up a session's "main set" weight -- the content
# `adjust_session` is actually allowed to scale. `warmup`/`cooldown`/`open`/
# `rest`/`recovery` are deliberately excluded: preserving the warm-up/
# cool-down shell (and any rest built into the set) is what keeps a scaled
# session reading as "the same workout, adjusted" rather than a different
# workout -- see this module's `_additional_swim_structure_template` and
# `_strength_session_structure_template`, whose own warmup/cooldown/open
# steps this mirrors.
_SCALABLE_ROLES = frozenset({"interval", "steady"})


def _clamp_adjustment_magnitude_pct(direction: Literal["reduce", "increase"], magnitude_pct: float) -> float:
    """Clamps a requested `adjust_session` magnitude into its safe range --
    see that function's own docstring for the rationale behind each bound.
    Returns the clamped (possibly unchanged) value; callers report this
    back to the athlete rather than the raw requested number, so a silently
    reduced "give me 60% more" isn't misreported as having been honored in
    full."""
    if direction == "increase":
        return max(1.0, min(magnitude_pct, SESSION_ADJUSTMENT_INCREASE_CAP_PCT))
    return max(1.0, min(magnitude_pct, 90.0))


def _adjustment_scale_factor(direction: Literal["reduce", "increase"], magnitude_pct: float) -> float:
    if direction == "increase":
        return 1.0 + magnitude_pct / 100.0
    return 1.0 - magnitude_pct / 100.0


def _item_has_role(item: "WorkoutStep | WorkoutRepeat", roles: frozenset[str]) -> bool:
    if item.kind == "step":
        return item.role in roles
    return any(_item_has_role(child, roles) for child in item.steps)


def _scale_leaf_step(step: WorkoutStep, factor: float) -> None:
    if step.duration_value is None:
        return  # role="open" steps (section headers, "Why:" lines) carry no number to scale
    if step.duration_kind == "distance_m":
        scaled = step.duration_value * factor
        step.duration_value = max(
            _ADJUSTMENT_MIN_DISTANCE_M,
            round(scaled / _ADJUSTMENT_DISTANCE_ROUND_M) * _ADJUSTMENT_DISTANCE_ROUND_M,
        )
    elif step.duration_kind == "time_s":
        scaled = step.duration_value * factor
        step.duration_value = max(
            _ADJUSTMENT_MIN_TIME_S, round(scaled / _ADJUSTMENT_TIME_ROUND_S) * _ADJUSTMENT_TIME_ROUND_S
        )
    elif step.duration_kind == "reps":
        step.duration_value = max(_ADJUSTMENT_MIN_REPS, round(step.duration_value * factor))
    # duration_kind == "open": nothing numeric to scale.


def _scale_repeat_wrapper(repeat: WorkoutRepeat, factor: float) -> None:
    """Scales a `WorkoutRepeat` wrapper's own `count`/`duration_s` -- NOT
    its nested `steps`' own per-iteration duration_values, which are left
    untouched. This is the "reduce repeat counts on interval/sprint blocks
    first" mechanism: a 10x200m interval set loses reps (10 -> 7), not
    200m-per-rep distance -- scaling both the wrapper and its children
    would double-apply the same adjustment."""
    if repeat.repeat_mode == "count" and repeat.count is not None:
        repeat.count = max(_ADJUSTMENT_MIN_REPEAT_COUNT, round(repeat.count * factor))
    elif repeat.duration_s is not None:  # for_duration / amrap
        scaled = repeat.duration_s * factor
        repeat.duration_s = max(
            _ADJUSTMENT_MIN_REPEAT_DURATION_S,
            round(scaled / _ADJUSTMENT_TIME_ROUND_S) * _ADJUSTMENT_TIME_ROUND_S,
        )


def _scale_structured_items(
    items: list["WorkoutStep | WorkoutRepeat"], factor: float, focus: Literal["interval", "overall"]
) -> None:
    """Mutates `items` in place, scaling whichever top-level items `focus`
    selects. `focus="interval"` targets only items carrying a role="interval"
    leaf somewhere inside them (recursively, so a `WorkoutRepeat` wrapping
    interval reps still counts); if the session has none at all (e.g. a
    strength or recovery session has no swim main-set interval content),
    falls back to every `_SCALABLE_ROLES` item instead of silently scaling
    nothing."""
    if focus == "interval":
        targets = [item for item in items if _item_has_role(item, frozenset({"interval"}))]
        if not targets:
            targets = [item for item in items if _item_has_role(item, _SCALABLE_ROLES)]
    else:
        targets = [item for item in items if _item_has_role(item, _SCALABLE_ROLES)]

    for item in targets:
        if item.kind == "step":
            _scale_leaf_step(item, factor)
        else:
            _scale_repeat_wrapper(item, factor)


def _sum_distance_m(items: list["WorkoutStep | WorkoutRepeat"]) -> float:
    """Recursively sums every `duration_kind="distance_m"` leaf's
    `duration_value`, weighting anything inside a `count`-mode
    `WorkoutRepeat` by its `count` -- the new source of truth for
    `Session.distance_m` after `_scale_structured_items` has mutated the
    tree, same keep-in-sync discipline `backend/app/tools.py`'s
    `_apply_session_overrides` already enforces for a coach-authored
    `structure` override. `for_duration`/`amrap` repeats contribute 0 (no
    reliable distance implied by a time-boxed round) -- not reachable by
    any template this engine ships today (see `WorkoutRepeat`'s own
    docstring: "rarely used")."""
    total = 0.0
    for item in items:
        if item.kind == "step":
            if item.duration_kind == "distance_m" and item.duration_value:
                total += item.duration_value
        elif item.repeat_mode == "count" and item.count:
            total += item.count * _sum_distance_m(item.steps)
    return total


def adjust_session(
    session: Session,
    *,
    direction: Literal["reduce", "increase"],
    magnitude_pct: float,
    focus: Literal["interval", "overall"] = "overall",
    css_pace_s: float | None = None,
) -> float:
    """Scale one already-planned `Session`'s volume/intensity up or down IN
    PLACE, for `backend/app/tools.py`'s `propose_session_adjustment`
    draft-then-confirm tool -- e.g. "I'm fatigued today, can you make this
    shorter with less sprint work?" or "I'm feeling strong, give me a bit
    more." Callers that need the pre-adjustment session to survive
    unmodified (for a before/after comparison) must pass a
    `session.model_copy(deep=True)`, same convention as `backend/app/
    tools.py`'s `_apply_session_overrides` mutating its own `week` argument
    directly. Returns the actual, post-clamp magnitude_pct that was applied
    (see `_clamp_adjustment_magnitude_pct`) -- report THIS back to the
    athlete, not the raw requested number, since a request beyond the safe
    range is silently clamped rather than rejected.

    Does NOT regenerate the session from a different template -- it scales
    the EXISTING content in place, which is what keeps the result reading
    as "the same workout, adjusted" rather than a random different one.

    `magnitude_pct` is clamped before use:
      - "reduce": [1, 90] -- can go most of the way to nothing (a fatigued
        or time-crunched athlete's need can be severe) but never to exactly
        zero, which would leave a degenerate, contentless session; a
        request to skip the session entirely is a different conversation,
        not "shorter."
      - "increase": [1, SESSION_ADJUSTMENT_INCREASE_CAP_PCT] -- see that
        constant's own docstring for the safety rationale. No such cap
        applies to "reduce": an athlete asking for less today is never the
        unsafe direction.

    `focus`:
      - "interval": scale role="interval" content first -- a `WorkoutRepeat`
        wrapping interval reps loses reps off its `count` (10x200m ->
        7x200m, NOT 10x140m -- see `_scale_repeat_wrapper`), while a bare
        interval `WorkoutStep` not wrapped in a repeat (the shape
        `_additional_swim_structure_template`'s main-set step actually
        uses today) has its own `duration_value` scaled directly instead,
        since there is no separate rep count to reduce. Falls back to
        "overall" if the session has no role="interval" content at all
        (e.g. a strength or recovery session) rather than scaling nothing.
      - "overall" (default): scale every `_SCALABLE_ROLES` item
        proportionally (interval AND steady-role content alike). Either
        way, warm-up/cool-down/open (section header / "Why:") content is
        never touched.

    When `session.structured` is `None` -- most of this athlete's real
    sessions today: pool-coach placeholders and hand-written prose carry no
    structured IR at all -- there is nothing to walk, so `distance_m`/
    `duration_min` are scaled directly instead; that is the entire
    mechanism in that case.

    When `session.structured` IS present, the scaled tree becomes the new
    source of truth for `distance_m` (`_sum_distance_m`), and `duration_min`
    is then re-estimated from the new distance at `css_pace_s`
    (`_duration_min_for_distance`) when available and the new distance is
    nonzero (a real swim distance); otherwise (a strength session with no
    distance-kind content, or no CSS pace on file) `duration_min` is instead
    scaled directly by the same `direction`/`magnitude_pct` factor the tree
    itself was scaled by.

    KNOWN LIMITATION: numbers already baked into a step's own athlete-facing
    `label` text (a rendered "10 x 200m ..." main-set narrative, or a
    strength section header's hand-written "2 sets x 10 reps") are NOT
    rewritten to match a scaled `count`/`duration_value` -- the seven
    different `FORMAT_STRATEGIES` narrative phrasings (`workout_templates.
    py`) have no reliable generic inverse to parse and rewrite safely. The
    machine-actionable fields that actually drive the athlete's stats, the
    Plan tab's tree render, and any Garmin export (`duration_value`/`count`/
    `duration_s`) are correctly scaled either way; only free text may still
    describe the pre-adjustment rep count. An accepted trade-off, not
    silently swept under the rug -- same spirit as this module's other
    documented KNOWN EDGE CASEs (see `NO_COACH_POOL_SESSION_FLOOR_M` above).
    """
    magnitude_pct = _clamp_adjustment_magnitude_pct(direction, magnitude_pct)
    factor = _adjustment_scale_factor(direction, magnitude_pct)

    if session.structured is not None:
        _scale_structured_items(session.structured.items, factor, focus)
        new_distance = _sum_distance_m(session.structured.items)
        if new_distance > 0:
            session.distance_m = round(new_distance)
            if css_pace_s is not None:
                session.duration_min = max(
                    _duration_min_for_distance(session.distance_m, css_pace_s), 10.0
                )
            else:
                session.duration_min = max(round(session.duration_min * factor, 1), 10.0)
        else:
            # No distance-kind content at all (e.g. a strength session) --
            # nothing for _sum_distance_m to total, so fall back to scaling
            # whatever scalar fields the session already carries directly.
            if session.distance_m is not None:
                session.distance_m = max(1, round(session.distance_m * factor))
            session.duration_min = max(round(session.duration_min * factor, 1), 10.0)
    else:
        if session.distance_m is not None:
            session.distance_m = max(1, round(session.distance_m * factor))
        session.duration_min = max(round(session.duration_min * factor, 1), 10.0)

    return magnitude_pct


def count_structured_steps(structured: WorkoutStructure | None) -> int | None:
    """The "effective step count" `propose_session_adjustment`'s comparison
    reports -- `None` when the session has no structured IR at all (nothing
    to count), otherwise every leaf `WorkoutStep` in the tree, with anything
    inside a `count`-mode `WorkoutRepeat` counted once per iteration (e.g. a
    2x-wrapped 5-exercise core block counts as 10) so a rep-count reduction
    (10x200m -> 7x200m) is visible in the comparison even though the number
    of top-level tree ITEMS never changed."""
    if structured is None:
        return None

    def _count(items: list["WorkoutStep | WorkoutRepeat"]) -> int:
        total = 0
        for item in items:
            if item.kind == "step":
                total += 1
            else:
                multiplier = item.count if (item.repeat_mode == "count" and item.count) else 1
                total += multiplier * _count(item.steps)
        return total

    return _count(structured.items)
