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
from typing import Callable, Literal
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
    WorkoutStepOrRepeat,
    WorkoutStructure,
    WorkoutTarget,
)
from swim_coach.workout_templates import (
    TemplatePreference,
    build_main_set_step,
    render_prose,
    resolve_template,
)
from swim_coach.zones import bike_zone_table, zone_table

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

# --- Bike-primary week generation constants ---------------------------------
# engine/cycling-coach: a real, minimal session-content path for a
# "bike"-primary week (Event.target_metric == "duration_min", the
# multi-sport-unlock build already shipped on main -- see
# engine/multisport-target-metric-unlock). Deliberately NOT a
# cycling-specific periodization design (no long-ride ladder, no
# block-shape beyond what scaffold_macro's already-generic base/build/
# peak/taper arithmetic provides) -- this only distributes whatever
# weekly total that generic arithmetic already computed across a small,
# fixed, Coach-judgment session cadence. library/23-cycling-training.md.

BIKE_SESSIONS_PER_WEEK = 3
# Coach judgment: no source (including Galán-Rioja et al. 2023, cited in
# library/23-cycling-training.md) prescribes a specific weekly SESSION
# COUNT for a trained cyclist -- that review reports observed weekly HOUR
# ranges across periodization models, not a session-count target. 3/week is
# an engineering default so a bike-primary week has real, distinct content
# (one harder day, the rest endurance) instead of one undifferentiated
# blob or an empty placeholder.

BIKE_HARD_SESSION_SHARE = 0.35
# Coach judgment: of the week's total duration, this share goes to ONE
# Z3 tempo-emphasis ride; the remainder splits evenly across the other
# BIKE_SESSIONS_PER_WEEK - 1 sessions as Z2 endurance rides. Both
# pyramidal (more Z2, some Z3, little top-end) and polarized distributions
# are reported as viable without a clear winner by Galán-Rioja et al. 2023
# (library/23-cycling-training.md) -- this specific 35% split is this
# engine's own default, not a cited ratio.

BIKE_HARD_SESSION_MAX_MIN = 75.0
# Coach judgment: library/23-cycling-training.md documents no continuous-Z3
# duration ceiling for a single session (Galán-Rioja et al. 2023 reports
# viable weekly HOUR ranges across periodization models, not a per-session
# cap) -- this is a plain engineering safety ceiling, same footing as
# BIKE_HARD_SESSION_SHARE above, so `hard_min = total_duration_min *
# BIKE_HARD_SESSION_SHARE` can't produce an unbounded continuous tempo
# block for a large weekly total (a 600-min week uncapped would put 210
# continuous minutes at Z3). Any duration this cap displaces is
# redistributed into the week's Z2 endurance sessions instead of being
# lost -- see `_bike_week_sessions`.

DEFAULT_BIKE_SESSION_MIN = 15.0
# Floor so a heavily-taper-compressed or very-early-ramp bike session
# never collapses to a 0- or near-0-minute, unrepresentable session --
# same role DEFAULT_POOL_SESSION_MIN/RECOVERY_SESSION_MIN's floors already
# play for swim/recovery sessions. Coach judgment.
#
# **Not applied as a per-session floor on top of a fixed session count.**
# A real review bug (PR #167 review, Finding 6): flooring EACH of
# BIKE_SESSIONS_PER_WEEK sessions at this minimum independently could
# inflate a low-volume (taper) week's TOTAL actual duration by up to 50%
# (a 30-min weekly target -> 45 actual, three sessions floored to 15 each)
# -- silently overriding the +8%/week ramp-cap rail that was already
# applied upstream. `_bike_week_sessions` instead reduces the SESSION
# COUNT (via `_resolve_bike_session_count` below) when the weekly total
# can't support `BIKE_SESSIONS_PER_WEEK` sessions at this floor, keeping
# actual total duration within a small, bounded tolerance of the target.

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

BIKE_FINAL_TAPER_MIN_SESSIONS = 2
BIKE_FINAL_TAPER_OPENER_MIN = 20.0
BIKE_FINAL_TAPER_EASY_MIN = 20.0
# PR #167 red-team review, Finding 2 (must-fix): the final taper week's
# block-interpolated target (`scaffold_macro`'s `taper_end`) can round to
# (near) zero, and `_resolve_bike_session_count`'s low-volume fallback then
# collapses the WHOLE week to one `DEFAULT_BIKE_SESSION_MIN`-floored ride --
# zero race-week content for an athlete's actual, active, A-priority event.
# `library/23-cycling-training.md` carries no taper/pre-race-sharpener
# guidance to cite (confirmed absent this pass) -- these two floor
# durations, and the choice of "one short opener + one easy spin" instead
# of one minimal ride, are Coach judgment / common practitioner convention
# (some brief race-intensity-adjacent work to prime without adding fatigue,
# plus a short easy spin), not a cited finding. This ONLY overrides the
# final taper week of a qualifying (active, priority "A", same-macro) event
# when `_bike_week_sessions` would otherwise produce fewer than
# BIKE_FINAL_TAPER_MIN_SESSIONS sessions -- an ordinary, non-collapsed
# taper week is untouched. Still a flat single-zone block each
# (`_bike_session_structure`) -- same discipline-content limitation as
# every other bike session this build generates (see that function's own
# "Known, deliberate scope limit" note).

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
)
# Fixed rotation order `_select_bike_interval_template` cycles through --
# library/24 grounds the four templates themselves but no source specifies
# a sequencing rule across them, so this ordering (longest/least
# neuromuscularly-taxing work bout first, shortest/most taxing last) is this
# engine's own reasonable default (Coach judgment), not a cited cadence.

BIKE_FTP_CHECK_ELIGIBLE_SOURCES = ("app_estimate", "self_reported_historical")
# threshold-history build, `_bike_week_sessions`'s `ftp_source` param: an FTP
# reading from either of these two `ThresholdRecord.source` values is real
# signal but NOT a genuine recent test (an app's own modelled estimate, or
# the athlete's own recollection of an old number -- Andrew's own example:
# "I was 350w 10 years ago") -- exactly the case Andrew's real block-01
# embeds a "doubles as a fitness check" note for, as distinct from a
# genuinely fresh `field_test`/`ramp_test`/`race_file` reading that needs no
# such caveat.
BIKE_FTP_CHECK_PURPOSE_SUFFIX = (
    " — also doubles as a rough FTP check: your current FTP is based on an "
    "estimate, not a recent real test, so how this session feels/holds up "
    "tells us roughly where you actually are; we'll keep the current number "
    "until a real test (or race file) confirms or corrects it"
)
# Coach judgment, not citation-backed -- the wording itself; the DECISION to
# embed rather than run a dedicated test is Andrew's own real block-01
# precedent (Tim's app), quoted in this build's own design brief: "Threshold
# check 2x12min... doubles as a fitness check... today tells me roughly
# where you are... we hold 263W until race files confirm it."


def _select_bike_interval_template(week_index: int) -> str:
    """Deterministically rotate through `BIKE_INTERVAL_TEMPLATES`, one
    template per week in a fixed order, so a bike-primary athlete's
    differentiated "hard" session actually varies week to week instead of
    always being the same flat block -- closes the exact gap
    `_bike_session_structure`'s former docstring flagged as a "KNOWN,
    DOCUMENTED LIMITATION." `week_index` is expected to be a continuous
    week counter from the start of the athlete's macro (see
    `_bike_ramp_week_index`) so the rotation advances every real calendar
    week regardless of which macro block (base/build/peak/taper) it falls
    in -- there is no research basis for resetting the rotation at a block
    boundary, and a continuous counter is simpler to reason about.
    """
    return BIKE_INTERVAL_TEMPLATES[week_index % len(BIKE_INTERVAL_TEMPLATES)]


def _bike_ramp_week_index(macro: MacroPlan, week_start: date) -> int:
    """0-based count of weeks since this macro's very first week
    (`macro.blocks[0].start_date` -- always the start of the `base` block,
    see `scaffold_macro`), continuous across block boundaries (unlike
    `generate_week`'s own `week_index_in_block`, which resets to 0 at the
    start of every block). Shared by the bike-primary deload cadence
    (`BIKE_DELOAD_CADENCE_WEEKS` below) and the interval-template rotation
    (`_select_bike_interval_template` above) so both advance consistently
    week over week for the same athlete.
    """
    return (week_start - macro.blocks[0].start_date).days // 7


BIKE_DELOAD_CADENCE_WEEKS = 4
# Coach judgment, NOT citation-backed (library/24-cycling-periodization-
# intervals.md's own "Closing the deload-cadence gap" section is explicit
# that no source it reviewed -- Seiler 2010, Issurin 2008, Galán-Rioja et
# al. 2023 -- specifies a validated numeric deload-week cadence). That
# section's own text: "a periodic step-down cadence of roughly every
# 3rd-4th week (three build weeks, one reduced-volume week) ... is a
# reasonable default pending explicit athlete/coach confirmation." This
# engine picks 4 -- three ordinary weeks, the 4th reduced -- the exact
# reading of that parenthetical, and the top of library/24's stated
# "3rd-4th week" range. Closes the gap `generate_week`'s own former "KNOWN
# LIMITATION" comment flagged (volume climbed every week from base through
# peak with no periodic deload). Applied only within a bike-primary macro's
# base/build/peak blocks (continuous week count via `_bike_ramp_week_index`,
# NOT reset per block) -- never the taper block, which already has its own
# explicit per-week decay rule (`TAPER_WEEKLY_DECAY`). Swim is explicitly
# OUT of scope for this pass (see `generate_week`'s own docstring) -- the
# underlying block-interpolation math is sport-agnostic, so this constant
# and the branch that applies it are scoped strictly to `primary_sport ==
# "bike"`, deliberately not touching the swim path at all.

BIKE_DELOAD_VOLUME_REDUCTION = 0.30
# Coach judgment, NOT citation-backed -- library/24 grounds the deload
# CADENCE above but explicitly does not ground a reduction MAGNITUDE (no
# source found). Same order of magnitude as this engine's own existing
# reactive-cut fraction (`adapt.CUT_VOLUME_FRACTION = 0.25`, itself the
# midpoint of ROADMAP.md's documented 20-30% reactive-cut range) --
# deliberately a bit deeper (0.30) since a scheduled deload is a full week
# planned in advance, not a reactive one-off cut. Consistent with this
# codebase's own existing reduction of similar shape, not itself a second
# citation.

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
#
# **METRES -- only valid for `Event.target_metric == "distance_m"`.** See
# `MIN_RAMP_SEED_DURATION_MIN` below for the duration-unit counterpart
# `scaffold_macro` actually uses for `target_metric == "duration_min"`
# macros (PR #167 review, fragile note: this constant used to be reused
# unchanged for duration-metric macros too -- for a real ~300 min/week
# cyclist, the seed silently became "1000 minutes," so the +8%/week ramp
# clamp barely engaged at all for any realistic peak target. This first
# bit in engine/cycling-coach because it's the first PR to actually
# produce real duration-path content -- the bug originates in the
# already-merged #164, which unlocked the target_metric machinery without
# a real duration-unit consumer yet to expose it).

MIN_RAMP_SEED_DURATION_MIN = 60.0
# Coach judgment, engineering seed value, same footing/role as
# MIN_RAMP_SEED_VOLUME_M above -- just in the correct unit (MINUTES, not
# metres) for a `target_metric == "duration_min"` macro (engine/cycling-
# coach's bike-primary path today). A brand-new cyclist logging 0 min/week
# is a real starting point, same "don't cap growth at literal zero"
# reasoning as MIN_RAMP_SEED_VOLUME_M -- 60 min (a single easy ride) is
# this engine's own minutes-scale floor, not a validated number.

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


def _spread_days_evenly(count: int) -> list[int]:
    """Pick `count` Monday-relative day offsets spread evenly across the
    week (ascending Mon->Sun order) -- `_bike_week_sessions`'s own day
    placement, since a bike-only athlete has no `pool_schedule`-equivalent
    field to avoid conflicting with (unlike `_pick_days`'s `excluded` set,
    which swim callers use to dodge already-placed pool days).

    **Real review bug fixed here (PR #167 review, Finding 3):**
    `_bike_week_sessions` used to call `_pick_days(count, excluded=set())`,
    which -- with nothing excluded -- always returns the first `count`
    ascending offsets: `[0, 1, 2]` for a 3-session week, i.e. every ride
    lands Mon/Tue/Wed with the hardest (Z3) day first and zero rest between
    any of them. That only happened to look reasonable for swim because
    `pool_offsets` there always excludes the intervening days; nothing
    equivalent existed for bike.

    Offsets are `round(i * 7 / count)` for `i in range(count)` -- verified
    collision-free (distinct offsets) for every `count` in `1..7`, the only
    range `BIKE_SESSIONS_PER_WEEK` can realistically take.
    """
    if count <= 0:
        return []
    return [round(i * 7 / count) for i in range(count)]


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
    PEAK_WEEKLY_VOLUME_X_EVENT_DISTANCE -- ONLY when event.target_metric ==
    "distance_m" (the only sport this default-derivation formula is
    evidenced for). For any other target_metric ("duration_min"/"load_au"),
    peak_weekly_volume_m is REQUIRED: raises ValueError if omitted, rather
    than guessing at an unvalidated duration/load-driven default. Whenever a
    value is available (explicit or distance-derived), it's never allowed to
    exceed current_weekly_volume_m compounded at WEEKLY_VOLUME_RAMP_CAP/week
    over the base+build weeks -- this applies even if peak_weekly_volume_m
    is passed explicitly. If clamped, a UserWarning records the original vs.
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

    if event.target_metric == "distance_m":
        distance_driven_target = event.distance_m * PEAK_WEEKLY_VOLUME_X_EVENT_DISTANCE
    elif peak_weekly_volume_m is None:
        # No validated duration/load-driven default-derivation formula
        # exists yet -- fabricating a "target_value x some constant" number
        # here would violate this project's evidence-citation discipline
        # (no research grounds such a constant, unlike
        # PEAK_WEEKLY_VOLUME_X_EVENT_DISTANCE above). Deferred until real
        # sport-specific research lands (see ROADMAP.md IDEA 007-010 /
        # multi-sport-unlock design discussion) -- raise rather than guess.
        raise ValueError(
            f"scaffold_macro requires an explicit peak_weekly_volume_m when "
            f"event.target_metric={event.target_metric!r} (not 'distance_m') "
            "-- no default peak-volume formula exists yet for non-distance "
            "events"
        )
    else:
        distance_driven_target = None  # unreachable below: peak_weekly_volume_m is set
    ramp_weeks = base_weeks + build_weeks
    # PR #167 review fragile note: MIN_RAMP_SEED_VOLUME_M is METRES -- using
    # it as a duration-minutes floor for target_metric="duration_min"
    # silently defeated the ramp cap for a real cyclist (seed became "1000
    # minutes"). Branch on target_metric so each unit gets its own,
    # correctly-scaled floor; target_metric="load_au" (arbitrary AU units,
    # no natural minutes/metres floor) still uses the metres constant as an
    # engineering placeholder -- same "documented, not silently guessed"
    # footing generate_week's own bike-path docstring already uses for its
    # load_au scope limit, not a claim this is unit-correct for AU.
    ramp_seed_floor = (
        MIN_RAMP_SEED_DURATION_MIN
        if event.target_metric == "duration_min"
        else MIN_RAMP_SEED_VOLUME_M
    )
    ramp_seed = max(current_weekly_volume_m, ramp_seed_floor)
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
# `library/16-race-week.md` for the full citations.

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


_BIKE_INTERVAL_TEMPLATE_BUILDERS = {
    "sustained_threshold": _bike_sustained_threshold_main,
    "over_unders": _bike_over_unders_main,
    "short_short_vo2": _bike_short_short_main,
    "race_pace": _bike_race_pace_main,
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


def _resolve_bike_hard_min(total_duration_min: float) -> float:
    """The hard (Z3) session's duration, `BIKE_HARD_SESSION_SHARE` of
    `total_duration_min`, capped at `BIKE_HARD_SESSION_MAX_MIN` -- see that
    constant's own comment (PR #167 review, Finding 4). Shared between
    `_resolve_bike_session_count` and `_bike_week_sessions` so both use the
    exact same number."""
    return min(round(total_duration_min * BIKE_HARD_SESSION_SHARE, 1), BIKE_HARD_SESSION_MAX_MIN)


def _resolve_bike_session_count(total_duration_min: float) -> int:
    """How many of `BIKE_SESSIONS_PER_WEEK` sessions this week's total
    duration can actually support without any of them needing
    `DEFAULT_BIKE_SESSION_MIN`'s floor -- see that constant's own comment
    (PR #167 review, Finding 6) for the bug this replaces: flooring each
    session of a FIXED count independently, which could silently inflate a
    low-volume (taper) week's total actual duration by up to 50%.

    Tries `BIKE_SESSIONS_PER_WEEK` down to 2, returning the largest count
    whose hard/easy split (computed the same way `_bike_week_sessions`
    itself computes it) already clears the floor on both the hard session
    and every easy session, with no flooring needed at all. Falls back to a
    single session -- the whole week's total as one ride -- if not even 2
    sessions clear it; a single low-volume session is deliberately NOT
    labeled "hard" (see `_bike_week_sessions`'s own `is_hard` handling) so
    this never forces a compressed taper day into a tempo-ride label.
    """
    hard_min = _resolve_bike_hard_min(total_duration_min)
    for n in range(BIKE_SESSIONS_PER_WEEK, 1, -1):
        easy_count = n - 1
        remaining_min = max(0.0, total_duration_min - hard_min)
        easy_min = remaining_min / easy_count
        if hard_min >= DEFAULT_BIKE_SESSION_MIN and easy_min >= DEFAULT_BIKE_SESSION_MIN:
            return n
    return 1


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


def _bike_week_sessions(
    athlete: Athlete,
    week_start: date,
    total_duration_min: float,
    ftp_watts: float | None,
    *,
    is_indoor: bool | None = None,
    week_index: int = 0,
    ftp_source: str | None = None,
) -> list[Session]:
    """Generate up to `BIKE_SESSIONS_PER_WEEK` generic cycling sessions
    splitting `total_duration_min` across a small weekly cadence:
    `BIKE_HARD_SESSION_SHARE` of the total (capped at
    `BIKE_HARD_SESSION_MAX_MIN` -- Finding 4) goes to one differentiated
    "hard" interval session, the rest splits evenly across the remaining
    Z2 endurance sessions. The actual session COUNT may be fewer than
    `BIKE_SESSIONS_PER_WEEK` for a low-volume week -- see
    `_resolve_bike_session_count` (Finding 6). See the module-level
    constants above for the citation/scope notes, and `generate_week`'s own
    docstring for why `total_duration_min` is what it is.

    `week_index` (optional, defaults to 0 -- see below): which of
    `BIKE_INTERVAL_TEMPLATES` the week's hard session draws from
    (`_select_bike_interval_template`) -- library/24-cycling-
    periodization-intervals.md's four real interval archetypes
    (sustained threshold, over/unders, short-short VO2, race-pace) that
    replaced the flat single-power block every hard session used to get
    (PR #167 red-team review finding). The hard session's own
    `Session.intensity["zone"]`/`purpose` now vary by selected template
    (`BIKE_INTERVAL_TEMPLATE_META`) instead of being hardcoded "Z3" --
    unlike `is_indoor` above, this is NOT a byte-identical-unless-updated
    parameter: replacing the flat block is this pass's whole point, so
    even the default (`week_index=0`, "sustained_threshold") produces
    genuinely different (repeat-shaped) content than before this pass.
    Real callers (`generate_week`, `adapt.adapt_week`) pass a real
    continuous week counter (`_bike_ramp_week_index`) so the rotation
    actually advances week to week for a real athlete.

    `ftp_watts`, when known, resolves each session's zone into absolute
    watt bounds via `zones.bike_zone_table` (library/23-cycling-training.md);
    when `None`, sessions still carry a real zone name (e.g. "Z2") with no
    absolute watts -- the same graceful-partial-data convention
    `DEFAULT_CSS_PACE_S_PER_100M`'s swim counterpart already uses elsewhere
    in this module.

    `is_indoor` (optional, defaults to `None` -- every existing call site
    keeps producing byte-identical output unless updated to pass it):
    forwarded onto every session's own `Session.is_indoor`. PR #167 review,
    Finding 5: before this parameter existed, NOTHING in this engine ever
    produced a bike session with `is_indoor` set to anything but its model
    default (`None`) -- the indoor/trainer `.zwo`-export-vs-outdoor-Garmin-
    push branch (`app.garmin_push`/`app.routes.garmin`) covered a state
    that could never actually occur. This makes the mechanism reachable; a
    real "which of this week's rides are indoor" planning UI/tool is still
    out of scope for this pass (uniform per-week, not per-session, is the
    only shape this parameter supports today).

    Deliberately NOT a full cycling-specific periodization design (no
    long-ride ladder, no block-shape beyond scaffold_macro's own generic
    arithmetic plus the bike-specific periodic deload -- see
    `generate_week`'s own docstring) -- see this build's own scope note.
    Days are spread evenly across the week via `_spread_days_evenly`
    (Finding 3 -- NOT `_pick_days`, which with nothing excluded always
    returns the first N ascending offsets, clustering every ride at the
    start of the week) -- a bike-only athlete has no `pool_schedule`-
    equivalent field yet to avoid conflicting with.

    `Session.intensity` carries `{"zone": ..., "ftp_watts_lo": ...,
    "ftp_watts_hi": ...}` -- deliberately no `"anchor"` key (Session's own
    `_validate_intensity` only restricts `anchor` to `{css_pace, rpe, hr}`
    when present at all; a power-based target has no matching value in that
    set, so this omits the key entirely rather than mislabeling it).

    `ftp_source` (optional, threshold-history build -- defaults to `None`,
    every existing call site keeps producing byte-identical output unless
    updated to pass it): the athlete's most recent `ftp_watts`-metric
    `ThresholdRecord.source` (see that model), if the caller has one. When
    this week's hard session is `week_index`'s FIRST "sustained_threshold"
    occurrence (i.e. `week_index == 0` -- `_select_bike_interval_template`'s
    rotation always starts there) of a fresh bike macro, AND `ftp_source` is
    `"app_estimate"` or `"self_reported_historical"` (not a real test), an
    honest note is appended to that session's `purpose` text: this session
    doubles as a rough fitness check, the same way Andrew's own real block-01
    (Tim's app) embeds a "threshold check" into its first sustained-threshold
    session rather than running a dedicated ramp test -- appropriate ONLY
    because a stale-but-real estimate already exists (see
    `_bike_ramp_test_structure`'s own docstring for the genuinely
    from-scratch case this does NOT cover). Reuses this template's existing
    content unchanged -- no new session type, no ramp-rate generator here.
    """
    n = _resolve_bike_session_count(total_duration_min)
    hard_min = _resolve_bike_hard_min(total_duration_min)
    easy_count = n - 1
    remaining_min = max(0.0, total_duration_min - hard_min)
    easy_min = round(remaining_min / easy_count, 1) if easy_count > 0 else 0.0
    template = _select_bike_interval_template(week_index)
    template_meta = BIKE_INTERVAL_TEMPLATE_META[template]

    offsets = _spread_days_evenly(n)

    sessions: list[Session] = []
    for i, offset in enumerate(offsets):
        # A single-session week (Finding 6's low-volume fallback) is never
        # labeled "hard" -- there's no second (easy) session to contrast it
        # against, and forcing a compressed taper day into a tempo-ride
        # label would be a worse coaching call than the volume-inflation
        # bug this fallback exists to fix in the first place.
        is_hard = n > 1 and i == 0
        duration = total_duration_min if n == 1 else (hard_min if is_hard else easy_min)
        zone = template_meta["zone"] if is_hard else "Z2"
        intensity = _bike_intensity(zone, ftp_watts)
        purpose = (
            template_meta["purpose"]
            if is_hard
            else "endurance ride (Z2) — aerobic base"
        )
        if (
            is_hard
            and template == "sustained_threshold"
            and week_index == 0
            and ftp_source in BIKE_FTP_CHECK_ELIGIBLE_SOURCES
        ):
            purpose += BIKE_FTP_CHECK_PURPOSE_SUFFIX
        duration_min_final = max(duration, DEFAULT_BIKE_SESSION_MIN)
        structured = (
            _bike_hard_session_structure(template, duration_min_final, ftp_watts)
            if is_hard
            else _bike_session_structure(zone, duration_min_final, ftp_watts)
        )
        sessions.append(
            Session(
                id=uuid4(),
                athlete_id=athlete.id,
                date=week_start + timedelta(days=offset),
                sport="bike",
                source="ai_coach",
                duration_min=duration_min_final,
                distance_m=None,
                intensity=intensity,
                purpose=purpose,
                structure=render_prose(structured),
                structured=structured,
                status="planned",
                is_indoor=is_indoor,
            )
        )
    return sessions


def _strength_sessions(athlete: Athlete, week_start: date, offsets: list[int]) -> list[Session]:
    """STRENGTH_SESSIONS_PER_WEEK-shaped dryland strength `Session`s at the
    given Monday-relative day `offsets` -- the same content/placement logic
    every swim week has always used (STRENGTH_CORE_EXERCISES /
    STRENGTH_FULL_BODY_ADDITION, library/07-strength-dryland.md), factored
    out so `generate_week`'s bike-primary path can reuse it too (PR #167
    red-team review, Finding 3, must-fix: bike weeks previously bypassed
    this mechanism entirely -- zero strength sessions, despite
    library/23-cycling-training.md's own cited knee/overuse-injury evidence
    -- Clarsen et al. 2010, Bini & Priego-Quesada 2022 -- having no engine
    content attached at all).

    Deliberately reuses the EXISTING swim-authored shoulder/rotator-cuff
    content unchanged, per this pass's explicit scope ("apply existing,
    already-cited machinery to a new sport, not new periodization") --
    NOT a claim that this specific exercise selection is what
    Clarsen/Bini's KNEE-injury findings would themselves prescribe for a
    cyclist. Authoring real cycling-specific (knee-focused) strength
    content is documented future scope, not attempted here.
    """
    sessions: list[Session] = []
    for session_index, offset in enumerate(offsets):
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
    return sessions


def _bike_week_sessions_with_strength(
    athlete: Athlete,
    week_start: date,
    total_duration_min: float,
    ftp_watts: float | None,
    *,
    is_indoor: bool | None = None,
    week_index: int = 0,
    ftp_source: str | None = None,
) -> list[Session]:
    """`_bike_week_sessions`'s output plus STRENGTH_SESSIONS_PER_WEEK
    strength sessions placed on days it didn't already use -- the
    bike-primary counterpart to the swim branch's own strength placement
    (see `_strength_sessions`'s own docstring, PR #167 red-team review
    Finding 3). Shared by `generate_week`'s bike-primary path and
    `adapt.adapt_week`'s bike-primary cut/advance rebuild so both place
    strength identically rather than duplicating the logic.

    `week_index` (optional, defaults to 0): forwarded straight through to
    `_bike_week_sessions`'s own `week_index` -- see that function's
    docstring for the interval-template rotation this selects. `ftp_source`
    (optional, threshold-history build, defaults to `None`): forwarded
    straight through to `_bike_week_sessions`'s own `ftp_source` -- see that
    function's docstring for the FTP-check purpose-text note this enables.
    """
    bike_sessions = _bike_week_sessions(
        athlete,
        week_start,
        total_duration_min,
        ftp_watts,
        is_indoor=is_indoor,
        week_index=week_index,
        ftp_source=ftp_source,
    )
    excluded = {(s.date - week_start).days for s in bike_sessions}
    strength_offsets = _pick_days(STRENGTH_SESSIONS_PER_WEEK, excluded=excluded)
    return bike_sessions + _strength_sessions(athlete, week_start, strength_offsets)


def _bike_final_taper_sessions(
    athlete: Athlete, week_start: date, ftp_watts: float | None, *, is_indoor: bool | None = None
) -> list[Session]:
    """The final taper week's floor content for a bike-primary week whose
    normal `_bike_week_sessions` output would otherwise collapse to a
    single near-token ride -- see `BIKE_FINAL_TAPER_MIN_SESSIONS`'s own
    comment for the bug and citation status. Two short, genuinely distinct
    sessions: a brief opener (Z3, some race-intensity-adjacent work) early
    in the week, then one easy (Z2) spin -- spread via `_spread_days_evenly`
    like every other bike week, still a flat single-zone block each
    (`_bike_session_structure`).
    """
    offsets = _spread_days_evenly(BIKE_FINAL_TAPER_MIN_SESSIONS)
    plan = [
        (BIKE_FINAL_TAPER_OPENER_MIN, "Z3", "race-week opener — short, race-intensity-adjacent effort to prime without adding fatigue"),
        (BIKE_FINAL_TAPER_EASY_MIN, "Z2", "easy spin — final taper-week leg-opener, keep it light"),
    ]
    sessions: list[Session] = []
    for offset, (duration_min, zone, purpose) in zip(offsets, plan):
        structured = _bike_session_structure(zone, duration_min, ftp_watts)
        sessions.append(
            Session(
                id=uuid4(),
                athlete_id=athlete.id,
                date=week_start + timedelta(days=offset),
                sport="bike",
                source="ai_coach",
                duration_min=duration_min,
                distance_m=None,
                intensity=_bike_intensity(zone, ftp_watts),
                purpose=purpose,
                structure=render_prose(structured),
                structured=structured,
                status="planned",
                is_indoor=is_indoor,
            )
        )
    return sessions


def generate_week(
    athlete: Athlete,
    macro: MacroPlan,
    iso_week: str,
    week_start: date,
    event_format: EventFormat = "single_day",
    template_preference: TemplatePreference | None = None,
    event: Event | None = None,
    primary_sport: Literal["swim", "bike"] = "swim",
    ftp_watts: float | None = None,
    bike_indoor: bool | None = None,
    ftp_source: str | None = None,
) -> WeekPlan:
    """Generate one week's sessions.

    `ftp_source` (optional, threshold-history build -- defaults to `None`,
    every existing call site keeps producing byte-identical output unless
    updated to pass it): the athlete's most recent `ftp_watts`-metric
    `ThresholdRecord.source`, if the caller has one -- forwarded straight
    through to `_bike_week_sessions`'s own `ftp_source` for a
    `primary_sport="bike"` week; ignored for a swim week and for any week
    that isn't `week_index == 0`'s first "sustained_threshold" occurrence.
    See that function's docstring for the FTP-check purpose-text note this
    enables.

    `bike_indoor` (optional, defaults to `None` -- every existing call site
    keeps producing byte-identical output unless updated to pass it):
    forwarded straight through to `_bike_week_sessions`'s own `is_indoor`
    parameter for a `primary_sport="bike"` week; ignored for a swim week.
    See that function's docstring for the Finding-5 bug this fixes
    (`Session.is_indoor` previously had no producer anywhere in this
    engine).

    `event` (optional, defaults to `None` -- every existing call site keeps
    producing byte-identical output unless updated to pass it): when
    supplied AND it is the athlete's ACTIVE, priority `"A"` target event
    (`RACE_WEEK_PRIORITY`) AND `event.id == macro.event_id` (the macro this
    week belongs to was actually scaffolded toward this same event) AND
    this week is the LAST week of a `"taper"` block, the returned
    `WeekPlan.race_week_checklist` is populated with the final-taper-week
    race-prep content (carbohydrate-loading window, bodywork window,
    logistics checklist) -- see `_race_week_checklist`'s own docstring and
    `library/16-race-week.md`. In every other
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

    `primary_sport` (defaults to `"swim"` -- every existing call site keeps
    producing byte-identical output unless updated to pass `"bike"`):
    when `"bike"`, this function takes a completely SEPARATE, much simpler
    path (`_bike_week_sessions`) instead of everything described below --
    no pool sessions, no long swim, no strength/recovery days, no
    `event_format`/`template_preference` handling. The block-interpolated
    `target_volume_m` computed above is, for a bike-primary week,
    interpreted as the week's TOTAL DURATION IN MINUTES (matching
    `Event.target_metric == "duration_min"`, the multi-sport-unlock case
    this build actually implements content for -- see `models.Event`'s own
    docstring on why duration+intensity, not distance, is cycling's natural
    target unit) and split across `BIKE_SESSIONS_PER_WEEK` generic Z2/Z3
    sessions (`_bike_week_sessions`), plus `STRENGTH_SESSIONS_PER_WEEK`
    strength sessions placed on the days it didn't already use
    (`_bike_week_sessions_with_strength`/`_strength_sessions` -- PR #167
    red-team review, Finding 3, must-fix: this used to bypass strength
    placement entirely despite `library/23-cycling-training.md`'s own cited
    knee/overuse-injury evidence having no engine content attached; now
    reuses the exact same mechanism swim weeks already use).

    Two more gaps closed this pass (both scoped strictly to bike, see the
    module-level constant comments for full citation/scope detail): (1) the
    week's differentiated "hard" session now rotates through
    `BIKE_INTERVAL_TEMPLATES` (`_select_bike_interval_template`) instead of
    always being the same flat single-power block (library/24-cycling-
    periodization-intervals.md's four real interval archetypes); (2) every
    `BIKE_DELOAD_CADENCE_WEEKS`-th week within a bike-primary macro's
    base/build/peak span (never the pre-scheduled `taper` block, which
    already has its own decay rule) reduces `target_volume_m` by
    `BIKE_DELOAD_VOLUME_REDUCTION` -- a periodic deload the un-modified
    block-interpolation math above still does not provide for swim (see
    that math's own comment).

    **Known, deliberate scope limit:** a macro scaffolded with `Event.target_metric
    == "load_au"` also reaches this path (nothing here checks which
    target_metric produced `target_volume_m`), but the number would then be
    an AU load total, not minutes -- this build does not disambiguate
    between the two units. Extending this to genuinely handle `load_au`
    bike weeks is real, documented future scope, not attempted here
    (matching this build's own explicit brief: implement real content for
    the shipped multi-sport unlock without inventing a cycling-specific
    periodization design). `ftp_watts` (optional) is forwarded straight to
    `_bike_week_sessions` -- see that function's own docstring for what it
    does when `None`. `race_week_checklist` is populated for a bike-primary
    week under the exact same qualifying condition (active, priority "A",
    same macro's event, final week of the taper block) as the swim path
    below, reusing `_race_week_checklist` directly (PR #167 red-team
    review, Finding 2, must-fix -- previously stayed empty unconditionally).
    That same final taper week is also floored to at least
    `BIKE_FINAL_TAPER_MIN_SESSIONS` real sessions
    (`_bike_final_taper_sessions`) when the ordinary block-interpolated
    target would otherwise collapse it to one near-token ride -- see that
    constant's own comment.

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
    if primary_sport not in ("swim", "bike"):
        raise ValueError(f"unknown primary_sport: {primary_sport!r}, must be 'swim' or 'bike'")
    block_index, block = _find_block(macro, week_start)
    weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
    week_index_in_block = (week_start - block.start_date).days // 7
    if not (0 <= week_index_in_block < weeks_in_block):
        raise ValueError(f"{week_start} is not a valid week-start within block {block.name!r}")

    start_volume = _block_start_volume(macro, block_index, block)
    end_volume = block.weekly_volume_target_m
    # This interpolation climbs every week from the start of `base` straight
    # through `peak` with no periodic deload/recovery week built in -- for a
    # long runway that's ~21 straight weeks of non-decreasing target before
    # the pre-scheduled `taper` block finally brings volume down. This
    # block-interpolation math is entirely sport-agnostic
    # (block.weekly_volume_target_m and start_volume are just numbers, no
    # swim-specific step here), so this same gap applies equally to swim.
    #
    # BIKE-PRIMARY WEEKS NOW GET A REAL, SCOPED FIX (see the `if
    # primary_sport == "bike":` branch below, `BIKE_DELOAD_CADENCE_WEEKS`):
    # every `BIKE_DELOAD_CADENCE_WEEKS`-th week within a bike-primary
    # macro's base/build/peak span reduces `target_volume_m` by
    # `BIKE_DELOAD_VOLUME_REDUCTION`, grounded (cadence only, not magnitude
    # -- see that constant's own comment) in library/24-cycling-
    # periodization-intervals.md's "Closing the deload-cadence gap" section.
    #
    # SWIM IS DELIBERATELY LEFT UNCHANGED by this pass -- generalizing a
    # scheduled deload to swim's own periodization is a real, separate,
    # bigger design question (long-swim-ladder interaction, milestone-week
    # spacing, ROADMAP.md's own post-milestone recovery-day rules would all
    # need to be reconciled with a scheduled volume drop) and was explicitly
    # out of scope for this build stage. Swim still relies on the same
    # mitigations as before: a correctly-wired `/adapt` (`adapt.adapt_week`)
    # reactive wellness/load-ratio cut -- but not eliminated: a swim athlete
    # who stays green on every signal still climbs for the entire
    # base+build+peak span uninterrupted, same as before this pass.
    frac = (week_index_in_block + 1) / weeks_in_block
    target_volume_m = round(start_volume + (end_volume - start_volume) * frac)

    if primary_sport == "bike":
        # Separate, much simpler path -- see this function's own docstring
        # for the "bike-primary week" scope note (units, race-week
        # limitation, etc). None of the swim-specific machinery below
        # (pool_offsets, long swim, event_format, template_preference)
        # applies -- strength placement now DOES apply (Finding 3, below),
        # reusing the exact same mechanism swim weeks use.
        #
        # Interval-template rotation (library/24, `_select_bike_interval_
        # template`) and periodic deload (`BIKE_DELOAD_CADENCE_WEEKS`) both
        # key off a continuous week counter from the macro's own start, NOT
        # `week_index_in_block` above (which resets every block boundary).
        ramp_week_index = _bike_ramp_week_index(macro, week_start)
        is_deload_week = (
            block.name in ("base", "build", "peak")
            and (ramp_week_index + 1) % BIKE_DELOAD_CADENCE_WEEKS == 0
        )
        # Never the taper block -- that already has its own explicit
        # per-week decay rule (TAPER_WEEKLY_DECAY) which this must not
        # stack with. See BIKE_DELOAD_CADENCE_WEEKS's own comment for the
        # citation/coach-judgment status of both the cadence and the
        # magnitude below.
        if is_deload_week:
            target_volume_m = round(target_volume_m * (1 - BIKE_DELOAD_VOLUME_REDUCTION))
            focus = f"{block.focus} — scheduled deload week"
        else:
            focus = block.focus
        if event is not None and event.target_metric == "load_au":
            # Cheap sanity check for the docstring's own "Known, deliberate
            # scope limit" note above (PR #167 review, fragile note): this
            # path interprets target_volume_m as MINUTES, but a macro
            # scaffolded toward a target_metric="load_au" event feeds an
            # arbitrary-unit AU number through exactly the same path with
            # nothing else to catch the mismatch. Warn rather than silently
            # mislabeling an AU total as minutes -- real load_au-bike
            # support stays documented future scope, not attempted here.
            warnings.warn(
                f"generate_week's bike-primary path interprets "
                f"target_volume_m ({target_volume_m}) as TOTAL DURATION IN "
                f"MINUTES, but this week's event has target_metric="
                f"'load_au' -- the resulting bike sessions' duration_min "
                "will actually be an AU load number, not minutes. See "
                "generate_week's own docstring 'Known, deliberate scope "
                "limit' note.",
                stacklevel=2,
            )
        # Final-taper-week race content (PR #167 red-team review, Finding
        # 2, must-fix): same qualifying test (active, priority "A", same
        # macro's event, last week of the taper block) the swim branch uses
        # below for `_race_week_checklist` -- reused verbatim, not
        # duplicated, so a qualifying bike event now gets the same
        # carb-load/bodywork/logistics content a qualifying swim event
        # already did.
        is_final_taper_week = block.name == "taper" and week_index_in_block == weeks_in_block - 1
        is_qualifying_race_week = (
            event is not None
            and is_final_taper_week
            and event.id == macro.event_id
            and event.active
            and event.priority.strip().upper() == RACE_WEEK_PRIORITY
        )
        if is_qualifying_race_week:
            core_bike_sessions = _bike_week_sessions(
                athlete,
                week_start,
                float(target_volume_m),
                ftp_watts,
                is_indoor=bike_indoor,
                week_index=ramp_week_index,
                ftp_source=ftp_source,
            )
            if len(core_bike_sessions) < BIKE_FINAL_TAPER_MIN_SESSIONS:
                # The ordinary taper math collapsed this week to a single
                # near-token ride (Finding 2) -- floor it to real race-week
                # content instead.
                core_bike_sessions = _bike_final_taper_sessions(
                    athlete, week_start, ftp_watts, is_indoor=bike_indoor
                )
            excluded = {(s.date - week_start).days for s in core_bike_sessions}
            strength_offsets = _pick_days(STRENGTH_SESSIONS_PER_WEEK, excluded=excluded)
            bike_sessions = core_bike_sessions + _strength_sessions(
                athlete, week_start, strength_offsets
            )
            race_week_checklist = _race_week_checklist(event, week_start)
        else:
            bike_sessions = _bike_week_sessions_with_strength(
                athlete,
                week_start,
                float(target_volume_m),
                ftp_watts,
                is_indoor=bike_indoor,
                week_index=ramp_week_index,
                ftp_source=ftp_source,
            )
            race_week_checklist = []
        return WeekPlan(
            id=uuid4(),
            athlete_id=athlete.id,
            iso_week=iso_week,
            meso_block=block.name,
            focus=focus,
            target_volume_m=target_volume_m,
            sessions=bike_sessions,
            adaptation_rationale=None,
            draft=False,
            race_week_checklist=race_week_checklist,
        )

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
    sessions.extend(_strength_sessions(athlete, week_start, strength_offsets))

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
