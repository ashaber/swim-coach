"""Injury/layoff-aware ramp-then-taper simulation against the Banister
CTL/ATL/TSB model (`load.py`'s `ctl_atl_tsb_series`), plus a dedicated
session-content generator for the recommended shape.

**Origin and drift from the abandoned draft.** This module is informed by
(but is NOT a copy of) an exploratory, read-only draft that lived only on
the unmerged `origin/engine/race-day-tsb-taper-search` branch
(`taper_search.py`, ~387 lines) -- the athlete/coach explicitly declined to
merge it months ago because "a CLI tool isn't effective for my use case"
(it was wired only to a `simulate-taper` CLI command, never a coach-callable
tool), NOT because its underlying hold-then-decay math was wrong. That
math -- `recent_baseline_daily_load`, `taper_volume_fraction`, the grid-search
shape, the `TaperCandidate` dataclass -- is reused here, verified against
this repo's CURRENT `load.py`/`plan.py` (which has moved on since that
branch was written: LTHR normalization, lap-based TRIMP summation, and
sRPE-to-HRR normalization have all merged into `load.py` since). One real
piece of drift was found and fixed here: the old draft imported a
`RACE_DAY_TSB_BAND` constant from `load.py` that no longer exists anywhere
in this codebase (confirmed via repo-wide search before writing this
module) -- it is defined fresh below, with its own citation, not assumed
to still be there.

**The actual new capability this module adds, closing the old draft's core
gap:** the old draft only ever modeled "hold the athlete's own recent real
baseline load, then decay it" -- it had no concept of ramping UP from a
reduced/injured baseline. Feeding an injured/laid-off athlete's literal
recent daily load into that logic would model her staying near that
depressed level all the way to race day, which is wrong. This module adds a
genuine three-phase RAMP -> HOLD -> TAPER projection: load rises from the
athlete's current real recent baseline toward a restriction-capped target
(the RAMP), continues at that target until the taper decay window opens
(the HOLD -- see `project_ramp_taper_series`'s docstring for why this is
NOT an independently-searched grid dimension), then decays via the exact
same `taper_volume_fraction`/`TAPER_WEEKLY_DECAY`-derived formula the old
draft already used, down to race day.

**Restriction-driven capping (the safety-critical part):** `resolve_ramp_
target` reads a caller-supplied `restriction` (`Athlete`'s current active
`HealthStatus.restriction`, resolved by the CALLER -- this module takes
plain values, not a `HealthStatus` object, staying decoupled from
`backend/app/context.py`'s `_active_health_statuses` resolution logic; see
that function for how the tool layer resolves "current active restriction"
from the full history):
  - `"no_training"`: **no ramp is permitted at all.** The ramp target is
    pinned to the athlete's own current recent baseline -- never higher.
    `search_taper_grid` does not even generate a `ramp_days > 0` candidate
    in this case (not merely a filtered-out one).
  - `"light_only"`: a ramp is permitted, but its target is capped at
    `LIGHT_ONLY_RAMP_CAP_FRACTION` of the athlete's PRE-LAYOFF baseline
    (see `pre_layoff_baseline_daily_load` and the constant's own citation
    comment below for the honest confidence level on that fraction).
  - `None` / `"none"` (no active restriction on file): no injury-driven cap
    -- the ramp targets the higher of the athlete's current recent baseline
    and her own pre-layoff baseline. For a genuinely uninterrupted athlete
    those two numbers are close to identical, so the ramp becomes a
    mathematical no-op and this collapses to the old draft's plain
    hold-then-decay behavior (`test_no_active_health_status_collapses_to_
    hold_then_decay_regression` in `tests/unit/test_taper_search.py` proves
    this precisely: varying `ramp_days` for a steady-state history produces
    byte-identical projected TSB). For an athlete genuinely returning from
    ANY kind of layoff (illness, travel) without a logged `HealthStatus`,
    the same ramp-aware shape still applies -- this module never assumes
    "no injury record" means "already back at full baseline."

**This module remains read-only / no side effects**, same discipline as the
old draft: every function here is a pure read+compute function over
already-loaded `Athlete`/`Event`/`Workout` data (or, for
`generate_taper_sessions`, plain projection-shape parameters) -- no
`store.save_*` call anywhere in this file, no I/O, no LLM calls. Only the
TOOL layer (`backend/app/tools.py`'s `propose_injury_adapted_taper`)
persists anything, and only on explicit `confirm=True`, per CLAUDE.md's
"never auto-persist a plan change without a human confirming it" rail.

**Citations, re-verified this session (not trusted secondhand):**
- **✓ Mujika I., Padilla S. (2003)**, "Scientific bases for precompetition
  tapering strategies," *Medicine & Science in Sports & Exercise*,
  35(7):1182-1187. Confirmed by direct web search this session: tapering is
  "best achieved by maintaining training intensity, reducing training
  volume (up to 60-90%) and slightly reducing training frequency (no more
  than 20%), with optimal duration ranging between 4 and more than 28
  days." This is the "hold intensity, cut volume" principle both the
  taper-decay phase below AND (per this build's own extension, see
  `LIGHT_ONLY_RAMP_CAP_FRACTION` below) the ramp-back-up phase lean on.
- **✓ Wang Z., Wang Y., Gao W., Zhong Y. (2023)**, "Effects of tapering on
  performance in endurance athletes: A systematic review and meta-analysis,"
  *PLOS ONE*, 18(5):e0282838. Confirmed by direct web search this session:
  14-study meta-analysis found a taper of >=21 days with a 41-60% volume
  reduction (intensity/frequency held) an effective strategy.
- **✓ RACE_DAY_TSB_BAND**: Joe Friel, quoted in TrainingPeaks' "Applying the
  Numbers Part 3: Training Stress Balance" (confirmed by direct fetch this
  session): "When I'm tapering and peaking athletes for A-priority races I
  like to have their Form at around plus 15 to plus 25 on race day,"
  while noting some athletes perform best around +5 to +10. `[ADAPTED:
  cycling]` -- a cycling/TrainingPeaks practitioner convention, not a
  swim-specific finding, applied here on top of `load.py`'s own already-
  flagged CTL/ATL time-constant citation debt (`CTL_TIME_CONSTANT_DAYS`/
  `ATL_TIME_CONSTANT_DAYS` are themselves carried over from cycling,
  unverified for swimming). **Confidence: medium.** See the constant's own
  comment below for the exact band chosen and why.

**2026-09 update: CTL substitution replaces the flat-mean ramp floor/
ceiling, ACWR was explicitly considered and rejected.** Andrew's own
question, verbatim: "are we using recent max duration? recent max load?
Should we be using Acute:Chronic Workload Ratio (ACWR)... EWMA of ATL and
CTL instead of static trailing-maximum values? ACWR would account for decay
of fitness due to time off and also would allow for a higher rate of
increase back to pre-injury load." Two things were true when this was
asked: (1) the ramp floor/ceiling (`recent_baseline_daily_load`/
`pre_layoff_baseline_daily_load`, both now DELETED -- see below) were flat
TRAILING ARITHMETIC MEANS, not maxima, and had no decay awareness at all --
an athlete who stopped logging during a layoff had her "recent baseline"
silently frozen at whatever her last active window looked like, no matter
how much real detraining time had since passed; (2) this codebase's own
`load.py` already carries an explicit LOW-confidence caveat on ACWR as a
safety threshold for swimmers specifically (`load.py`'s
`ACWR_ACUTE_WINDOW_DAYS`/`ACWR_CHRONIC_WINDOW_DAYS` citation block: elevated
ACWR was associated with shoulder pain in *youth* swimmers, but the
odds-ratio confidence interval's lower bound sits near 1.0 -- marginal --
and "ACWR methodology is broadly criticized," with a separate cohort
finding week-to-week ratio/ACWR a weak predictor compared to a simpler
single-session-vs-30-day-longest check). Given that, and after this was
surfaced to Andrew, the confirmed decision was: **CTL substitution, not a
literal ACWR ratio or its threshold.** This module does NOT implement an
ACWR ratio or any ACWR-derived threshold anywhere -- that would mean adopting
a SECOND, separately low-confidence methodology on top of the one this
codebase already carries citation debt for, for no real gain over what was
already sitting computed and unused right here.

The actual substitution: `search_taper_grid` already computes `series =
ctl_atl_tsb_series(loads)` and takes `ctl0` from its last entry -- `ctl0` IS
already a decay-aware EWMA of daily load (the same Banister model,
`CTL_TIME_CONSTANT_DAYS=42`) -- exactly the "EWMA of CTL instead of a
static trailing window" Andrew asked for, just not yet being used as the
ramp floor. The ramp floor is now `ctl0` directly (no new computation). The
ramp ceiling is now a point-in-time CTL LOOKUP (`ctl_at`, below) at the
pre-layoff boundary date, out of the SAME already-computed `series` --
still not a second average, and still reusing the one EWMA machinery this
module already trusted for its TSB projection. A third, genuinely new
capability came out of building this: `series` previously only ever walked
to the LATEST LOGGED day, so an athlete who stopped logging entirely during
her injury would never see her CTL decay past that day, even if weeks had
passed since -- `search_taper_grid` now seeds a zero-load day at `as_of`
when it's after the latest logged day, letting the walk (and the decay)
reach all the way to "today" (see that function's own docstring paragraph
on this extension for the exact guard). The net effect is that the
window-shrinking hack that used to compensate for the flat mean's staleness
(`effective_recent_window_days`, now deleted) is no longer needed at all --
CTL's own decay handles "don't let a stale pre-injury number dominate"
natively, which is this build's real structural win over the mechanism it
replaces.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal
from uuid import uuid4

from swim_coach.load import (
    ATL_TIME_CONSTANT_DAYS,
    CTL_TIME_CONSTANT_DAYS,
    ZONE_ASSUMED_RPE,
    ctl_atl_tsb_series,
    daily_loads,
)
from swim_coach.models import Athlete, Event, Session, Wellness, Workout
from swim_coach.plan import (
    RECOVERY_SESSION_MIN,
    _pool_day_offset,
    _round_100,
    _z2_pace_s_per_100m,
)

Restriction = Literal["none", "light_only", "no_training"]

RACE_DAY_TSB_BAND = {"low": 5.0, "high": 25.0}
# See module docstring's citation block (Joe Friel / TrainingPeaks). This
# constant did NOT exist anywhere in this codebase before this module --
# the abandoned draft branch this module is informed by imported it from
# `load.py`, but a repo-wide search confirmed `load.py` never actually
# defined it (drift between that branch and current `main`, or it was
# never finished there either way). Defined fresh here, in this module,
# since it's specific to race-day taper planning, not a general load-math
# constant `load.py`'s other consumers need. Band chosen to span both
# numbers Friel gives (a narrower "some athletes" +5-10 low end, a
# "typical A-race" +15-25 high end) rather than picking just one -- a
# candidate landing anywhere in +5..+25 is treated as "in band," not just
# the narrower +15-25 window. `[ADAPTED: cycling]`, Confidence: medium.
# library/22-injury-adapted-taper.md.

NO_RESTRICTION_PRE_LAYOFF_LOOKBACK_DAYS = 21
# Coach judgment / PROVISIONAL, library/22-injury-adapted-taper.md. Formerly
# `RECENT_BASELINE_WINDOW_DAYS` (the old flat-mean recent-baseline window,
# deleted under CTL substitution -- see module docstring's 2026-09 update
# paragraph); the VALUE is unchanged (21 days) but its role now is purely to
# pick a `pre_layoff_boundary` DATE for the `ctl_at` lookup below, not to
# size an averaging window (CTL substitution has no averaging windows left
# at all -- see `ctl_at`, `search_taper_grid`). Used ONLY as the generic
# "how far back counts as pre-layoff" fallback when there's no active
# `HealthStatus` to anchor a real boundary date (`restriction_reported_at is
# None` in `search_taper_grid`) -- three weeks back from `anchor_date`, long
# enough that for a genuinely steady, uninterrupted athlete the CTL read at
# that date is close to (see `resolve_ramp_target`'s no-restriction
# docstring) the current CTL, collapsing the ramp to a near-no-op, same
# posture as the deleted constant it replaces.

LIGHT_ONLY_RAMP_CAP_FRACTION = 0.55
# Coach judgment / PROVISIONAL, library/22-injury-adapted-taper.md. Confidence: LOW-MEDIUM -- there is NO
# established research pinning an exact "how much of pre-injury baseline is
# safe to ramp back to in N days" figure; this is stated honestly, not
# implied to be more precise than it is. 0.55 sits in the middle of a
# defensible 40-70% range this build considered: the grounding is this
# build's own real motivating context (an athlete's real advisory-panel
# consultation, Sept 2026, explicitly reasoning "same swim intensity,
# meaningfully less volume" for a shoulder-injury return-to-swim taper) and
# the SAME "hold intensity, cut volume" principle Mujika & Padilla (2003,
# see module docstring) already establishes for the taper-DECAY side of
# training, applied here symmetrically to the ramp-BACK-UP side: if cutting
# volume by 60-90% while holding intensity is the safe direction going INTO
# a taper, a conservative (not aggressive) fraction of pre-injury volume,
# with intensity likewise held rather than chased, is the same logic
# applied in reverse. This is this module's own extension of that
# principle, NOT a claim that Mujika & Padilla's paper itself addresses
# return-from-injury ramping -- it does not.
# **Test:** revisit once real dual-logged return-from-injury data exists
# (for this or other athletes) to check whether this fraction was too
# conservative (return-to-training stalled unnecessarily) or not
# conservative enough (a re-injury or flare-up followed a ramp that used
# this fraction) -- either observation should move this number, not just
# confirm it.

RAMP_DAYS_GRID_DEFAULT: tuple[int, ...] = (0, 2, 4, 6, 8, 10, 14)
# Coach judgment / PROVISIONAL, library/22-injury-adapted-taper.md. Zero (no ramp
# at all) is always included so the grid can discover "don't ramp" is
# actually the best answer for a given runway. The rest climbs in
# short/even steps through two weeks -- short-notice, injury-interrupted
# runways (this build's own real motivating case: 12 days) are exactly
# where a coarser weekly grid would miss the relevant granularity, so this
# grid is day-granular rather than week-granular, unlike `taper_weeks`
# below (which stays week-granular, matching `plan.py`'s own
# `TAPER_WEEKLY_DECAY` convention). Not searched beyond 14 days: a ramp
# longer than two weeks stops being a "short-notice return" and starts
# being ordinary periodization, which `plan.scaffold_macro`/`generate_week`
# already own.

TAPER_WEEKS_GRID_MIN = 1
# Coach judgment, unchanged from the old draft: the shortest block worth
# calling a taper (see Wang et al. (2023)'s finding that even <=21-day
# tapers show a real, measurable effect -- this project's own
# `TAPER_WEEKS_LONG`/`TAPER_WEEKS_SHORT` in `plan.py` already use 2-4 weeks
# for a NORMAL macro taper; this grid intentionally searches shorter, since
# this module exists specifically for short-notice/compressed runways a
# normal macro taper wouldn't fit).

DECAY_GRID_MIN = 0.10
DECAY_GRID_MAX = 0.45
DECAY_GRID_STEP = 0.05
# Unchanged from the old draft: brackets `plan.py`'s real
# TAPER_WEEKLY_DECAY = 0.25 on both sides. Andrew's own stated range
# (~0.10-0.45); no library citation attaches to this specific numeric grid,
# only to the general "volume reduction is the taper lever" finding cited
# in the module docstring.

REST_DAY_LOAD_FRACTION_THRESHOLD = 0.15
# Coach judgment / PROVISIONAL, library/22-injury-adapted-taper.md. A day whose
# target load (from the ramp/hold/taper shape) falls at or below this
# fraction of `ramp_target_daily_load` is rendered as a full rest/recovery
# day by `generate_taper_sessions` rather than an unrealistically tiny
# token swim (e.g. a "3-minute swim" that isn't a real session).

REST_DAY_CADENCE_DAYS = 3
# Coach judgment / PROVISIONAL, library/22-injury-adapted-taper.md, flagged
# honestly as a real, acknowledged simplification: `project_ramp_taper_
# series`'s TSB projection treats each phase's target load as a smooth,
# continuous per-day number (mathematically clean, and consistent with how
# `load.ctl_atl_tsb_series`'s multi-day exponential smoothing already
# behaves -- it barely distinguishes "the same total load spread evenly"
# from "the same total load lumped onto fewer, harder days"). Real training
# doesn't work that way -- a swimmer doesn't swim an identical fraction of
# volume every single day -- so `generate_taper_sessions` imposes a simple
# "every third day is a full rest day" rhythm on top of the smooth
# projection, independent of whichever phase that day falls in (matching
# the real motivating advisory-panel plan's own cadence of roughly one rest
# day for every two training days). This is NOT fed back into the TSB
# projection itself -- the small discrepancy between "smooth projected
# load" and "lumpier real session content" is a real, small, honestly-flagged
# gap, not reconciled in this build. **Test:** revisit if real athlete
# adherence data suggests this cadence doesn't match how load is actually
# best distributed for a short-notice return-to-training window.

MIN_SESSION_DURATION_MIN = 15.0
# Coach judgment: shortest duration this generator will still call a real
# swim session rather than folding it into a rest day -- mirrors
# `plan.py`'s own `max(_duration_min_for_distance(...), 15.0)` floor for its
# no-pool-coach pool sessions.

_GENERATOR_ZONE = "Z2"
# All swim sessions this generator authors use Z2 (steady aerobic) as the
# held intensity, regardless of ramp/hold/taper phase -- the "hold
# intensity, vary volume" principle both Mujika & Padilla (2003) and this
# module's own `LIGHT_ONLY_RAMP_CAP_FRACTION` extension already commit to;
# see module docstring. Reuses `load.ZONE_ASSUMED_RPE[_GENERATOR_ZONE]` as
# the AU-load -> duration_min inversion factor (see `_duration_min_for_
# day_load` below) rather than inventing a new assumed-intensity constant.


@dataclass(frozen=True)
class TaperCandidate:
    """One grid point's simulated ramp-then-taper result.

    `hold_days` is DERIVED, not independently searched -- see
    `project_ramp_taper_series`'s docstring for why "ramp to a target, then
    hold that target until taper" is one continuous idea whose hold length
    falls out of `ramp_days`/`taper_weeks` rather than needing its own grid
    dimension. `fits_available_runway` is False when this candidate's ramp
    would need to run past where the taper block would otherwise start
    (i.e. the taper had to be pushed later than `taper_weeks` alone would
    imply to let the ramp finish) -- included for visibility, never
    silently dropped, but flagged rather than presented as a genuinely
    proposable plan. `restriction`/`ramp_cap_fraction_applied` record which
    safety cap (if any) shaped this candidate's `ramp_target_daily_load`.
    """

    ramp_days: int
    hold_days: int
    taper_weeks: int
    decay: float
    ramp_target_daily_load: float
    volume_fraction: float
    ramp_end_date: date
    taper_start_date: date
    projected_ctl: float
    projected_atl: float
    projected_tsb: float
    in_band: bool
    fits_available_runway: bool
    restriction: Restriction | None
    ramp_cap_fraction_applied: float | None


def ctl_at(series: list[tuple[date, float, float, float]], target_date: date) -> float | None:
    """Look up the projected CTL for `target_date` in an already-computed
    `load.ctl_atl_tsb_series` result -- an O(1) dict lookup, not a fresh
    average or an O(n) scan. This is the "point-in-time EWMA read" this
    module's CTL-substituted ramp ceiling is built on (see module
    docstring's 2026-09 update paragraph): `search_taper_grid` already has
    a full day-by-day `series` computed for its own TSB projection, so the
    pre-layoff baseline is a LOOKUP into that, not a second, independently
    -averaged number.

    Returns `None` if `target_date` falls before the earliest day `series`
    walked (`series[0]`'s date) -- an honest "not available from this
    history," not a fabricated number. Since `ctl_atl_tsb_series` walks
    every calendar day with no gaps once it starts, "before the first day"
    is the ONLY way a `target_date` can be genuinely missing (a `target_
    date` on or after the first day is always present as an exact key).
    `ctl_at` itself makes no policy decision about what to do with a
    `None` -- that is the CALLER's job (see `search_taper_grid`'s own
    fallback to the earliest available CTL, documented where it's applied,
    with its own citation for why that specific fallback is the most
    defensible one available).

    Returns `None` for an empty `series` too (nothing to look up at all).
    """
    if not series:
        return None
    if target_date < series[0][0]:
        return None
    by_date = {d: ctl for d, ctl, _atl, _tsb in series}
    return by_date.get(target_date)


def taper_volume_fraction(taper_weeks: int, decay: float) -> float:
    """`scaffold_macro`'s own taper-volume formula
    (`peak_volume * (1 - TAPER_WEEKLY_DECAY * taper_weeks)`), reduced to
    just the fraction (dropping the `peak_volume` multiplier since this
    module applies the same fraction to LOAD, not volume). Floored at 0.0,
    same as `scaffold_macro`'s own `max(0, ...)`.
    """
    return max(0.0, 1.0 - decay * taper_weeks)


def resolve_ramp_target(
    current_recent_baseline: float,
    pre_layoff_baseline: float,
    restriction: Restriction | None,
) -> tuple[float, float | None, bool]:
    """Resolve the ramp's target daily load, honoring whichever
    restriction-driven safety cap applies -- see module docstring's
    "Restriction-driven capping" section for the full rationale.

    This function's own math/signature is unchanged by the 2026-09
    CTL-substitution build (see module docstring) -- only what its two
    float inputs REPRESENT changed. `current_recent_baseline` is now the
    athlete's current `ctl0` (a decay-aware Banister EWMA read at
    `anchor_date`, extended through to `as_of` when she's stopped logging --
    see `search_taper_grid`), not a flat trailing mean. `pre_layoff_
    baseline` is now a point-in-time CTL LOOKUP at the pre-layoff boundary
    date (`ctl_at`, above, called by `search_taper_grid`), not a second
    flat mean either -- both numbers now come from the same single EWMA
    series this module already computes for its TSB projection, read at two
    different dates, rather than two independently-averaged windows.

    Returns `(ramp_target_daily_load, ramp_cap_fraction_applied,
    ramp_permitted)`:
      - `restriction == "no_training"`: `(current_recent_baseline, None,
        False)` -- the target is pinned to the current baseline; no ramp
        above it is ever permitted.
      - `restriction == "light_only"`: target is exactly
        `pre_layoff_baseline * LIGHT_ONLY_RAMP_CAP_FRACTION` -- a hard
        ceiling, never extended upward to match a higher current-baseline
        reading. See the real bug fixed below for why this is a ceiling,
        not the floor-adjusted target an earlier version computed.
        `ramp_cap_fraction_applied = LIGHT_ONLY_RAMP_CAP_FRACTION`.
      - `restriction in (None, "none")`: no injury-driven cap -- target is
        `max(current_recent_baseline, pre_layoff_baseline)`. For a steady,
        uninterrupted athlete, CTL read at "now" is provably >= CTL read at
        any earlier date (`ctl_atl_tsb_series`'s recursion is monotonically
        increasing toward a constant load's ceiling -- see the regression
        test this collapse behavior is proven against, in
        `tests/unit/test_taper_search.py`), so this `max()` picks
        `current_recent_baseline` exactly and the ramp becomes a
        mathematical no-op (see module docstring's regression-test
        pointer); for an athlete genuinely returning from an unlogged
        layoff (current CTL decayed below her earlier pre-layoff CTL),
        this still ramps back toward her own real prior capacity. This
        `max()` floor is safe to keep ONLY here, where there is no active
        safety restriction to potentially override.

    **Real review bug fixed here before merge, safety-critical**: the
    `light_only` branch used to compute `target = max(current_recent_
    baseline, capped_target)` -- intended to mean "never propose ramping
    DOWN below what she's already doing," but it actually meant "if her
    own recent-baseline number ever reads ABOVE the cap, for ANY reason,
    silently abandon the cap entirely and target that higher number
    instead." That reading can happen for reasons that have nothing to do
    with the athlete genuinely, safely handling more than the cap: the
    `recent_baseline_daily_load` window is deliberately SHRUNK to
    `days_since_restriction_reported` right when a restriction is fresh
    (see `search_taper_grid` below) -- meaning if the athlete logged a big
    session on the very day she was hurt (plausible for an in-practice
    injury), that single day can dominate the shrunk window and read at or
    near her full pre-injury load, silently erasing the cap at the exact
    moment it matters most. A safety ceiling that a data artifact can
    quietly cancel is not a ceiling. Fixed: `light_only`'s target is now
    `pre_layoff_baseline * LIGHT_ONLY_RAMP_CAP_FRACTION`, full stop -- an
    absolute ceiling, never extended upward to match a higher
    current-baseline reading. If a coach/athlete genuinely believes more
    is safe than this cap allows, that's what `restriction_override` (see
    the calling tool) is for -- an explicit, visible, human choice to
    relax the assumption, never an silent side-effect of which exact days
    happened to fall inside a rolling average window.
    """
    if restriction == "no_training":
        return current_recent_baseline, None, False
    if restriction == "light_only":
        capped_target = pre_layoff_baseline * LIGHT_ONLY_RAMP_CAP_FRACTION
        return capped_target, LIGHT_ONLY_RAMP_CAP_FRACTION, True
    target = max(current_recent_baseline, pre_layoff_baseline)
    return target, None, True


def _phase_day_load(
    day: date,
    *,
    anchor_date: date,
    current_baseline_daily_load: float,
    ramp_target_daily_load: float,
    ramp_days: int,
    taper_start_date: date,
    volume_fraction: float,
) -> float:
    """The target daily load for one projected `day`, per the three-phase
    ramp -> hold -> taper shape -- shared by `project_ramp_taper_series`
    (the smooth TSB projection) and `generate_taper_sessions` (session
    content), so the two never silently disagree about what a given day's
    target load is.

    Phase membership, in priority order:
      1. `day == taper_start_date == anchor_date + ramp_days` (the RAMP's
         own final day exactly coincides with TAPER's first day, the
         `hold_days == 0` case): RAMP wins, resolving to the ramp's own
         completed value (`ramp_target_daily_load`) -- see the real bug
         fixed below for why this single-day exception exists.
      2. `day >= taper_start_date`: TAPER -- `ramp_target_daily_load *
         volume_fraction`.
      3. `ramp_days > 0` and `day` falls within the first `ramp_days` days
         after `anchor_date`: RAMP -- linear interpolation from
         `current_baseline_daily_load` (at `anchor_date`) to
         `ramp_target_daily_load` (at `anchor_date + ramp_days`).
      4. Otherwise: HOLD -- flat `ramp_target_daily_load`. This covers both
         the explicit post-ramp hold window AND, when `ramp_days == 0`, every
         pre-taper day (immediately "at target" -- the old draft's plain
         hold-then-decay shape).

    **Real review bug fixed here before merge, narrowly**: whenever
    `hold_days == 0` (`taper_start_date == ramp_end_date` exactly -- taper
    starts the instant the ramp's own linear rise would complete, no hold
    window in between), the ramp's own FINAL day used to be classified as
    TAPER (since `day >= taper_start_date` was checked first and is also
    true on that exact day) -- silently clipping the ramp one day short of
    ever actually reaching `ramp_target_daily_load`, dropping straight to
    the tapered value instead.

    The fix is deliberately a single-day special case (#1 above), NOT a
    blanket "RAMP always wins over TAPER" reordering -- an earlier attempt
    at that broke a real, separately-tested invariant: when
    `ramp_target_daily_load == current_baseline_daily_load` (a flat/no-op
    "ramp" -- the ordinary no-restriction, steady-state case;
    `project_ramp_taper_series` deliberately does NOT clamp
    `taper_start_date` against `ramp_end_date` in that case, since there's
    no real rising ramp worth protecting), `taper_start_date` can fall
    WELL BEFORE `ramp_end_date` by many days, not just the single boundary
    day -- and for every one of those non-boundary overlap days, TAPER
    must still win (applying the real volume reduction), exactly as this
    module's own regression test (`test_project_ramp_taper_series_ramp_is_
    noop_when_target_equals_current`) requires to prove this build
    collapses to byte-identical output to the old hold-then-decay draft in
    that case. Only the EXACT coincidence of the ramp's own final day and
    taper's first day gets the exception; every other overlap still
    resolves TAPER-first, unchanged from before.

    A second guard on the same exception, found by the SAME regression
    test after the first fix attempt: `taper_start_date` is NOT clamped
    against `ramp_end_date` at all when the ramp is flat/no-op
    (`ramp_target_daily_load == current_baseline_daily_load` -- see
    `project_ramp_taper_series`'s own docstring). For a fixed
    `taper_start_date`, some `ramp_days` value in a grid search can
    coincidentally land `anchor_date + ramp_days` exactly ON that
    already-fixed date -- but since there's no real ramp value to protect
    in the no-op case, that coincidence must NOT trigger the exception
    (which would make different `ramp_days` values diverge in their
    projected TSB for what's supposed to be a value-identical no-op). The
    exception is scoped to `ramp_target_daily_load !=
    current_baseline_daily_load` -- a genuinely rising (or falling) ramp
    with a real value worth completing before any taper discount applies.
    """
    if (
        ramp_days > 0
        and ramp_target_daily_load != current_baseline_daily_load
        and day == taper_start_date == anchor_date + timedelta(days=ramp_days)
    ):
        return ramp_target_daily_load
    if day >= taper_start_date:
        return ramp_target_daily_load * volume_fraction
    day_offset = (day - anchor_date).days
    if ramp_days > 0 and day_offset <= ramp_days:
        frac = max(0.0, day_offset) / ramp_days
        return current_baseline_daily_load + (ramp_target_daily_load - current_baseline_daily_load) * frac
    return ramp_target_daily_load


def project_ramp_taper_series(
    ctl0: float,
    atl0: float,
    anchor_date: date,
    race_date: date,
    current_baseline_daily_load: float,
    ramp_target_daily_load: float,
    ramp_days: int,
    taper_weeks: int,
    decay: float,
    *,
    ctl_tau_days: float = CTL_TIME_CONSTANT_DAYS,
    atl_tau_days: float = ATL_TIME_CONSTANT_DAYS,
) -> tuple[float, float, float, float, date, date]:
    """Project CTL/ATL/TSB forward day-by-day from `anchor_date` through the
    day BEFORE `race_date` -- race day itself is the event, not training
    load being tapered toward, so it's deliberately excluded from the
    projection (same convention the old draft used).

    Three phases per day, computed by `_phase_day_load` (see its docstring
    for the exact rule): RAMP (linear rise from `current_baseline_daily_load`
    toward `ramp_target_daily_load` over `ramp_days`), HOLD (flat at
    `ramp_target_daily_load`), TAPER (`ramp_target_daily_load *
    taper_volume_fraction(taper_weeks, decay)`, from `taper_start_date`
    through race day - 1).

    `taper_start_date = max(race_date - timedelta(weeks=taper_weeks),
    anchor_date + timedelta(days=ramp_days))`, but **only when
    `ramp_target_daily_load > current_baseline_daily_load` -- i.e. only when
    there is an actual rising ramp to protect.** When the two are equal (or
    the "ramp" would be flat/falling -- the no-restriction, steady-state
    case; see module docstring's regression-test pointer), `ramp_days` has
    no bearing on `taper_start_date` at all, since a ramp with nothing to
    rise toward isn't a phase worth protecting -- this is what lets this
    function collapse to byte-identical output to the old
    hold-then-decay draft regardless of `ramp_days` in that case. When a
    real ramp IS being protected, it is never truncated to hit an arbitrary
    decay-window start (cutting a return-to-training ramp short is the less
    safe direction to compromise in) -- instead the taper is pushed later,
    and the caller can see this via `TaperCandidate.fits_available_runway`
    (computed by callers as `taper_start_date == race_date -
    timedelta(weeks=taper_weeks)`).

    Same Banister recursion as `load.ctl_atl_tsb_series`: `CTL_t = CTL_{t-1}
    + (load_t - CTL_{t-1}) / ctl_tau_days`, same shape for ATL.

    Returns `(projected_ctl, projected_atl, projected_tsb, volume_fraction,
    ramp_end_date, taper_start_date)` as of the last projected day. If
    `anchor_date` is already on or after `race_date - 1 day` (no runway left
    to project), no recursion steps run and `(ctl0, atl0, ctl0 - atl0,
    volume_fraction, ramp_end_date, taper_start_date)` is returned unchanged
    -- an honest "nothing to project," not a crash or a fabricated step.
    """
    volume_fraction = taper_volume_fraction(taper_weeks, decay)
    nominal_taper_start_date = race_date - timedelta(weeks=taper_weeks)
    ramp_end_date = anchor_date + timedelta(days=ramp_days)
    is_rising_ramp = ramp_days > 0 and ramp_target_daily_load > current_baseline_daily_load
    taper_start_date = max(nominal_taper_start_date, ramp_end_date) if is_rising_ramp else nominal_taper_start_date

    ctl, atl = ctl0, atl0
    day = anchor_date + timedelta(days=1)
    last_projected_day = race_date - timedelta(days=1)
    while day <= last_projected_day:
        load = _phase_day_load(
            day,
            anchor_date=anchor_date,
            current_baseline_daily_load=current_baseline_daily_load,
            ramp_target_daily_load=ramp_target_daily_load,
            ramp_days=ramp_days,
            taper_start_date=taper_start_date,
            volume_fraction=volume_fraction,
        )
        ctl = ctl + (load - ctl) / ctl_tau_days
        atl = atl + (load - atl) / atl_tau_days
        day += timedelta(days=1)

    return ctl, atl, ctl - atl, volume_fraction, ramp_end_date, taper_start_date


def _decay_grid(decay_min: float, decay_max: float, decay_step: float) -> list[float]:
    steps = round((decay_max - decay_min) / decay_step)
    return [round(decay_min + i * decay_step, 10) for i in range(steps + 1)]


def _distance_to_band(tsb: float, band: dict[str, float]) -> float:
    if band["low"] <= tsb <= band["high"]:
        return 0.0
    return min(abs(tsb - band["low"]), abs(tsb - band["high"]))


def search_taper_grid(
    *,
    athlete: Athlete,
    event: Event,
    workouts: list[Workout],
    wellness: list[Wellness] | None = None,
    as_of: date,
    restriction: Restriction | None = None,
    restriction_reported_at: date | None = None,
    ramp_days_grid: tuple[int, ...] = RAMP_DAYS_GRID_DEFAULT,
    taper_weeks_min: int = TAPER_WEEKS_GRID_MIN,
    decay_min: float = DECAY_GRID_MIN,
    decay_max: float = DECAY_GRID_MAX,
    decay_step: float = DECAY_GRID_STEP,
    tsb_band: dict[str, float] = RACE_DAY_TSB_BAND,
) -> dict[str, object]:
    """Read-only grid search over `(ramp_days, taper_weeks, decay)`: for
    every combination, project the athlete's real current CTL/ATL forward
    (`project_ramp_taper_series`) and report whether the resulting race-day
    TSB lands inside `tsb_band`. NEVER writes anything -- see module
    docstring.

    `restriction`/`restriction_reported_at` are plain values the CALLER
    resolves (typically from the athlete's current active `HealthStatus`,
    via `backend/app/context.py`'s `_active_health_statuses` -- this module
    stays decoupled from that model/resolution logic on purpose).

    **Ramp floor and ceiling are both CTL reads now, not flat means (see
    module docstring's 2026-09 update paragraph for the full rationale and
    the ACWR alternative explicitly considered and rejected):**
      - The floor (`recent_baseline_daily_load` in the returned dict) is
        `ctl0` directly -- the athlete's real, decay-aware EWMA fitness as
        of `anchor_date`. No averaging window to configure or shrink
        anymore: CTL's own 42-day exponential decay already naturally
        discounts old (pre-layoff) history relative to recent history,
        which is exactly the property the OLD flat-mean system needed a
        manual `effective_recent_window_days`-shrinking hack to
        approximate (see the removed mechanism's own git history for that
        hack, and this module's earlier bug-fix commentary) -- that hack is
        gone; CTL supersedes it structurally, not just numerically.
      - The ceiling (`pre_layoff_baseline_daily_load`) is a point-in-time
        CTL LOOKUP (`ctl_at`, above) at `pre_layoff_boundary` -- the active
        `HealthStatus.reported_at` date when one exists, or
        `anchor_date - NO_RESTRICTION_PRE_LAYOFF_LOOKBACK_DAYS` as a
        generic "before recent" fallback when there's no active
        restriction on file. If `pre_layoff_boundary` falls before the
        earliest day `series` ever walked (a short/incomplete logging
        history -- `ctl_at` returns `None` in exactly this case, and only
        this case, since `ctl_atl_tsb_series` never has gaps once it
        starts), this falls back to the EARLIEST available CTL in the
        series (`series[0]`) -- the most defensible available proxy, since
        `ctl_atl_tsb_series` seeds CTL near 0 at the true start of walked
        history, so the earliest available point is the closest honest
        answer available for "what was her fitness before this history
        even starts," rather than fabricating a number for a date the
        engine has no data reaching back to. `pre_layoff_baseline_used_
        earliest_fallback` in the returned dict says plainly whether this
        fallback was used.

    **A real, new capability this build adds: CTL decay is extended through
    to `as_of` ("today"), not just to the last LOGGED day.**
    `ctl_atl_tsb_series` only ever walks calendar days from the earliest to
    the LATEST KEY PRESENT in the `daily_load_values` dict it's given. An
    athlete who has stopped logging entirely during an injury (this
    module's own real motivating scenario -- see module docstring) would,
    without this extension, have `anchor_date`/`ctl0` frozen at her last
    LOGGED day, never decaying through the real elapsed time since --
    missing exactly the "decay of fitness due to time off" this build
    exists to capture. Fix: if `as_of` is AFTER the latest key already
    present in the computed daily loads, a zero-load entry is seeded at
    `as_of` before calling `ctl_atl_tsb_series` -- the same "a day missing
    from the dict counts as zero load" convention `daily_loads`/
    `ctl_atl_tsb_series` already use everywhere in this codebase, not a new
    semantic. This ONLY ever extends the walked range forward: nothing is
    seeded (the dict is used unchanged) when `as_of` is on or before the
    latest existing key, so an ordinary athlete who logged something today
    or recently is completely unaffected, and the walk's true START is
    never touched either way.

    The real starting point (`ctl0`/`atl0`/`anchor_date`) comes from running
    `load.ctl_atl_tsb_series` over the athlete's REAL logged
    `workouts`/`wellness` history (extended per the above) and taking its
    last entry. Raises `ValueError` if `workouts` produces no loggable day
    at all.

    Only `ramp_days_grid` values consistent with `restriction`'s ramp
    permission are searched -- `resolve_ramp_target`'s `ramp_permitted`
    flag being `False` (`restriction == "no_training"`) restricts the grid
    to `(0,)` only, so no ramp candidate above baseline is ever generated,
    not merely filtered out afterward.

    Returns a dict with `anchor_date`/`ctl0`/`atl0`/`tsb0`,
    `recent_baseline_daily_load`, `pre_layoff_baseline_daily_load`,
    `pre_layoff_baseline_boundary_date`, `pre_layoff_baseline_used_
    earliest_fallback`, `restriction`, `ramp_permitted`,
    `ramp_cap_fraction_applied`, `ramp_target_daily_load`, `race_date`,
    `days_available`, `weeks_available`, `tsb_band`, `candidates` (list of
    `TaperCandidate`), `any_in_band` (bool), `closest_to_band` (smallest
    distance into `tsb_band` among candidates that `fits_available_runway`,
    ties broken by grid order -- always populated), and `recommended`
    (alias of `closest_to_band` today -- kept as its own key so a future,
    more elaborate recommendation rule doesn't require renaming this
    field).
    """
    wellness = wellness or []
    loads = daily_loads(workouts, athlete=athlete, wellness=wellness)
    if not loads:
        raise ValueError(
            "no logged workouts for this athlete -- cannot compute a starting "
            "CTL/ATL or a recent baseline daily load"
        )

    # Extend CTL decay through to `as_of` when the athlete has stopped
    # logging -- see this function's own docstring paragraph above for the
    # full rationale and the forward-only guard. `loads` is copied rather
    # than mutated in place since it's a fresh dict from `daily_loads`
    # either way, but copying keeps the seeding step visibly self-contained.
    latest_logged_day = max(loads)
    if as_of > latest_logged_day:
        loads = {**loads, as_of: 0.0}

    series = ctl_atl_tsb_series(loads)
    anchor_date, ctl0, atl0, tsb0 = series[-1]

    recent_baseline = ctl0
    pre_layoff_boundary = (
        restriction_reported_at
        if restriction_reported_at is not None
        else anchor_date - timedelta(days=NO_RESTRICTION_PRE_LAYOFF_LOOKBACK_DAYS)
    )
    pre_layoff_baseline = ctl_at(series, pre_layoff_boundary)
    pre_layoff_baseline_used_earliest_fallback = pre_layoff_baseline is None
    if pre_layoff_baseline is None:
        pre_layoff_baseline = series[0][1]

    ramp_target, ramp_cap_fraction_applied, ramp_permitted = resolve_ramp_target(
        recent_baseline, pre_layoff_baseline, restriction
    )

    race_date = event.event_date
    days_available = max(0, (race_date - as_of).days)
    weeks_available = days_available // 7

    # Defensive floor, not just a default: a `taper_weeks=0` candidate is
    # structurally invalid -- its `taper_start_date` would equal `race_date`
    # exactly, which the day-stepping projection loop (bounded at
    # `race_date - 1`) never reaches, so its `decay`/`volume_fraction`
    # would be computed and reported but never actually applied to a
    # single projected day -- silently misrepresenting a no-taper
    # candidate as a legitimate one that "fits the runway." Not reachable
    # via this tool's own call site today (which never overrides this
    # parameter), but clamped here so a future caller can't reintroduce
    # this by passing a smaller value.
    taper_weeks_min = max(1, taper_weeks_min)

    effective_ramp_days_grid = ramp_days_grid if ramp_permitted else (0,)
    ramp_days_values = sorted({d for d in effective_ramp_days_grid if d >= 0})
    taper_weeks_values = list(range(taper_weeks_min, max(taper_weeks_min, weeks_available) + 1))
    decay_values = _decay_grid(decay_min, decay_max, decay_step)

    candidates: list[TaperCandidate] = []
    for ramp_days in ramp_days_values:
        for taper_weeks in taper_weeks_values:
            for decay in decay_values:
                nominal_taper_start = race_date - timedelta(weeks=taper_weeks)
                ctl, atl, tsb, volume_fraction, ramp_end_date, taper_start_date = (
                    project_ramp_taper_series(
                        ctl0,
                        atl0,
                        anchor_date,
                        race_date,
                        recent_baseline,
                        ramp_target,
                        ramp_days,
                        taper_weeks,
                        decay,
                    )
                )
                hold_days = max(0, (taper_start_date - ramp_end_date).days)
                candidates.append(
                    TaperCandidate(
                        ramp_days=ramp_days,
                        hold_days=hold_days,
                        taper_weeks=taper_weeks,
                        decay=decay,
                        ramp_target_daily_load=ramp_target,
                        volume_fraction=volume_fraction,
                        ramp_end_date=ramp_end_date,
                        taper_start_date=taper_start_date,
                        projected_ctl=ctl,
                        projected_atl=atl,
                        projected_tsb=tsb,
                        in_band=tsb_band["low"] <= tsb <= tsb_band["high"],
                        fits_available_runway=(taper_start_date == nominal_taper_start),
                        restriction=restriction,
                        ramp_cap_fraction_applied=ramp_cap_fraction_applied,
                    )
                )

    any_in_band = any(c.in_band for c in candidates)
    fitting = [c for c in candidates if c.fits_available_runway] or candidates
    closest_to_band = min(fitting, key=lambda c: _distance_to_band(c.projected_tsb, tsb_band))

    return {
        "anchor_date": anchor_date,
        "ctl0": ctl0,
        "atl0": atl0,
        "tsb0": tsb0,
        "recent_baseline_daily_load": recent_baseline,
        "pre_layoff_baseline_daily_load": pre_layoff_baseline,
        "pre_layoff_baseline_boundary_date": pre_layoff_boundary,
        "pre_layoff_baseline_used_earliest_fallback": pre_layoff_baseline_used_earliest_fallback,
        "restriction": restriction,
        "ramp_permitted": ramp_permitted,
        "ramp_cap_fraction_applied": ramp_cap_fraction_applied,
        "ramp_target_daily_load": ramp_target,
        "race_date": race_date,
        "days_available": days_available,
        "weeks_available": weeks_available,
        "tsb_band": tsb_band,
        "candidates": candidates,
        "any_in_band": any_in_band,
        "closest_to_band": closest_to_band,
        "recommended": closest_to_band,
    }


# --- session-content generation for the recommended candidate ----------------


def _weekday_pool_offsets(athlete: Athlete) -> set[int]:
    return {_pool_day_offset(entry) for entry in athlete.pool_schedule}


def _duration_min_for_day_load(day_load: float) -> float:
    """Invert `load.session_target_load_au`'s own `duration_min *
    ZONE_ASSUMED_RPE[zone]` formula to recover a duration from a target AU
    load, reusing `load.ZONE_ASSUMED_RPE` directly rather than inventing a
    new assumed-intensity constant for this generator. Assumes
    `_GENERATOR_ZONE` ("Z2") throughout -- see that constant's own comment
    for why every generated swim session holds the same steady-aerobic
    intensity regardless of ramp/hold/taper phase.
    """
    assumed_rpe = ZONE_ASSUMED_RPE[_GENERATOR_ZONE]
    return day_load / assumed_rpe


def _session_role(
    day: date,
    *,
    anchor_date: date,
    current_baseline_daily_load: float,
    ramp_target_daily_load: float,
    ramp_days: int,
    taper_start_date: date,
) -> Literal["ramp", "hold", "taper"]:
    # Same phase-membership priority as _phase_day_load's own fixed
    # ordering, INCLUDING both of its hold_days==0 exception's guards (the
    # single-day coincidence AND the "only for a genuinely rising/falling
    # ramp, never a flat no-op one" scoping -- see that function's
    # docstring for the real bugs this avoids) -- kept in sync
    # deliberately so a session's LABELED role can never disagree with the
    # load value `_phase_day_load` actually computed for the same day.
    if (
        ramp_days > 0
        and ramp_target_daily_load != current_baseline_daily_load
        and day == taper_start_date == anchor_date + timedelta(days=ramp_days)
    ):
        return "ramp"
    if day >= taper_start_date:
        return "taper"
    day_offset = (day - anchor_date).days
    if ramp_days > 0 and day_offset <= ramp_days:
        return "ramp"
    return "hold"


def _restriction_clause(restriction: Restriction | None) -> str:
    if restriction in (None, "none"):
        return "no active health restriction on file"
    return f"active health restriction on file: {restriction}"


def _session_purpose(role: Literal["ramp", "hold", "taper", "rest"], restriction: Restriction | None) -> str:
    clause = _restriction_clause(restriction)
    if role == "ramp":
        return (
            f"Engine-proposed ramp-phase day of a capped, restriction-aware "
            f"return-to-training ramp ({clause}) -- gradually rebuilding "
            f"volume toward a capped target before tapering into the event. "
            f"Not pool-coach- or athlete-authored; a draft from "
            f"propose_injury_adapted_taper, for discussion before "
            f"confirmation."
        )
    if role == "hold":
        return (
            f"Engine-proposed hold-phase day at the ramp's capped target "
            f"({clause}) -- steady volume before the taper decay begins. "
            f"Not pool-coach- or athlete-authored; a draft from "
            f"propose_injury_adapted_taper, for discussion before "
            f"confirmation."
        )
    if role == "taper":
        return (
            f"Engine-proposed taper-decay day ({clause}) -- intensity held, "
            f"volume reduced per the taper decay curve heading into race "
            f"day. Not pool-coach- or athlete-authored; a draft from "
            f"propose_injury_adapted_taper, for discussion before "
            f"confirmation."
        )
    return (
        f"Engine-proposed full rest day within the injury/layoff-aware "
        f"ramp-then-taper plan ({clause}) -- no swimming. Not pool-coach- "
        f"or athlete-authored; a draft from propose_injury_adapted_taper, "
        f"for discussion before confirmation."
    )


def generate_taper_sessions(
    *,
    athlete: Athlete,
    event: Event,
    anchor_date: date,
    race_date: date,
    current_baseline_daily_load: float,
    ramp_target_daily_load: float,
    ramp_days: int,
    taper_start_date: date,
    volume_fraction: float,
    restriction: Restriction | None,
    as_of: date,
) -> list[Session]:
    """Turn one chosen ramp/hold/taper shape into concrete, DRAFT `Session`
    objects for every day from `max(anchor_date, as_of) + 1` through
    `race_date - 1` (race day itself is the event, not a training day).
    Every `Session.id` is a fresh `uuid4()`; nothing here is persisted (see
    module docstring) -- the tool layer decides whether/how to persist, on
    explicit `confirm=True` only.

    **Real review bug fixed here before merge**: `anchor_date` is the
    athlete's LAST LOGGED workout day (needed elsewhere, e.g.
    `project_ramp_taper_series`, as the real starting point for the CTL/ATL
    recursion -- that math legitimately must anchor on where real logged
    data ends). But this function used to ALSO use that same date as the
    start of the CALENDAR RANGE it generates real `Session` rows for --
    for the athlete this feature was built for, who has stopped logging
    workouts because she's injured (this feature's own motivating
    scenario), `anchor_date` can be days behind `as_of` (today), and the
    old code would generate -- and, on `confirm=True`, PERSIST -- sessions
    dated in the PAST, silently overwriting whatever real plan record
    already existed for those already-happened days.

    The fix only changes where the GENERATION LOOP starts
    (`max(anchor_date, as_of)`) -- `anchor_date` itself is still passed
    unchanged to `_phase_day_load`/`_session_role` for their own
    ramp/taper phase-boundary math (`ramp_end_date = anchor_date +
    ramp_days`, etc.), since those comparisons are against absolute dates
    and are unaffected by where the generation loop itself begins. If
    real time has passed since `anchor_date` such that the ramp/hold
    phases would already be over by `as_of`, the athlete simply starts
    wherever the shape says today actually falls (e.g. straight into
    TAPER) -- this build never retroactively fabricates sessions for days
    that already happened, whether or not they were logged.

    Each day's target load comes from the exact same `_phase_day_load` rule
    `project_ramp_taper_series` uses, so the projection and the generated
    session content can never silently disagree about what a given day's
    role/target is.

    A day is rendered as a full rest/recovery day (`sport="recovery"`,
    `distance_m=None`, matching this codebase's existing rest-day
    convention -- see `plan.generate_week`'s own Sunday recovery session)
    when EITHER its target-load fraction falls at or below
    `REST_DAY_LOAD_FRACTION_THRESHOLD`, OR it falls on the
    `REST_DAY_CADENCE_DAYS` rest-day rhythm (see that constant's own
    comment for the honest "not fed back into the TSB projection" caveat).
    Every other day becomes a continuous swim session: `sport="swim_pool"`
    on one of `athlete.pool_schedule`'s days, `sport="swim_ow"` otherwise
    (a coarse, deliberately simple pool-vs-open-water rule -- see this
    build's own PR description for why a fuller rule wasn't attempted).
    Duration comes from inverting `load.ZONE_ASSUMED_RPE["Z2"]`'s own
    AU-per-minute assumption (`_duration_min_for_day_load`), floored at
    `MIN_SESSION_DURATION_MIN`; distance is derived from that duration via
    the athlete's own Z2 pace (`plan._z2_pace_s_per_100m`), rounded to the
    nearest 100m (`plan._round_100`) for realism, matching how `plan.py`'s
    own generators round distances.

    Every session's `purpose` field plainly states it is engine-proposed
    and names the current restriction context (or its explicit absence),
    plus its role in the ramp/hold/taper shape (see `_session_purpose`).
    """
    pace_s = _z2_pace_s_per_100m(athlete)
    pool_offsets = _weekday_pool_offsets(athlete)

    sessions: list[Session] = []
    generation_start = max(anchor_date, as_of)
    day = generation_start + timedelta(days=1)
    last_day = race_date - timedelta(days=1)
    day_index = 0
    while day <= last_day:
        day_load = _phase_day_load(
            day,
            anchor_date=anchor_date,
            current_baseline_daily_load=current_baseline_daily_load,
            ramp_target_daily_load=ramp_target_daily_load,
            ramp_days=ramp_days,
            taper_start_date=taper_start_date,
            volume_fraction=volume_fraction,
        )
        load_fraction = (
            day_load / ramp_target_daily_load if ramp_target_daily_load > 0 else 0.0
        )
        is_cadence_rest = day_index % REST_DAY_CADENCE_DAYS == (REST_DAY_CADENCE_DAYS - 1)
        is_rest = load_fraction <= REST_DAY_LOAD_FRACTION_THRESHOLD or is_cadence_rest

        if is_rest:
            sessions.append(
                Session(
                    id=uuid4(),
                    athlete_id=athlete.id,
                    date=day,
                    sport="recovery",
                    source="ai_coach",
                    duration_min=RECOVERY_SESSION_MIN,
                    distance_m=None,
                    intensity={"zone": "Z1", "anchor": "rpe"},
                    purpose=_session_purpose("rest", restriction),
                    structure=None,
                    status="planned",
                )
            )
        else:
            role = _session_role(
                day,
                anchor_date=anchor_date,
                current_baseline_daily_load=current_baseline_daily_load,
                ramp_target_daily_load=ramp_target_daily_load,
                ramp_days=ramp_days,
                taper_start_date=taper_start_date,
            )
            duration_min = max(MIN_SESSION_DURATION_MIN, _duration_min_for_day_load(day_load))
            distance_m = max(0, _round_100(duration_min / 60 * 3600 / pace_s * 100))
            weekday_offset = day.weekday()
            sport = "swim_pool" if weekday_offset in pool_offsets else "swim_ow"
            sessions.append(
                Session(
                    id=uuid4(),
                    athlete_id=athlete.id,
                    date=day,
                    sport=sport,
                    source="ai_coach",
                    duration_min=round(duration_min, 1),
                    distance_m=distance_m,
                    intensity={"zone": _GENERATOR_ZONE, "anchor": "css_pace"},
                    purpose=_session_purpose(role, restriction),
                    structure=None,
                    status="planned",
                )
            )
        day_index += 1
        day += timedelta(days=1)

    return sessions
