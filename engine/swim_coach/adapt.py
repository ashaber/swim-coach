"""Deterministic adaptation rule table + event-format-aware long-swim ladder.

`adapt_week()` is `/adapt`'s Sunday-ritual engine call: given the athlete's
recent training-load/wellness/compliance signals (via `load.py`) plus last
week's actual plan, it decides whether to CUT, REPEAT, HOLD, or ADVANCE next
week's volume and long swim, and returns a draft (`draft=True`) `WeekPlan`
whose `adaptation_rationale` is a JSON string listing which rules fired and
the numbers behind them -- CLAUDE.md's "never hand-compute in chat" rule
means `/adapt` reads this rationale rather than re-deriving it.

Rule table (ROADMAP.md "Adaptation rules"; every threshold is a named
constant below, cited to `library/03-periodization.md` /
`library/06-long-swim-progression.md` / `library/reference_list.md`).
Priority, highest first (a red flag always wins, even at 100% compliance):
  1. wellness composite red (<= WELLNESS_RED_THRESHOLD) OR 7d:28d load ratio
     > LOAD_RATIO_RED_THRESHOLD -> **cut**: reduce target volume by
     CUT_VOLUME_FRACTION, hold the long swim at its current absolute
     distance (never advance the ladder on a cut week), add a recovery day.
  2. compliance < COMPLIANCE_REPEAT_THRESHOLD -> **repeat**: hold volume and
     long swim at last week's actual level (repeat the progression step).
  3. fewer than RECOVERY_DAYS_AFTER_MILESTONE_MIN days have passed since the
     last long-swim milestone (`days_since_last_milestone`, when the caller
     supplies it) -> **hold**: forced recovery window, no ladder advance
     regardless of how green the other signals are.
  4. compliance >= COMPLIANCE_ADVANCE_THRESHOLD -> **advance**: volume
     +<= WEEKLY_VOLUME_RAMP_CAP (plan.py's shared safety rail), long swim
     advances per the event-format-specific ladder (below).
  5. otherwise -> **hold**: repeat volume/long swim, no advance, no cut.

Long-swim ladder (ROADMAP.md "Event format parameter + long-swim
progression"):
  - `single_day`: an escalating single continuous swim toward a peak of
    SINGLE_DAY_PEAK_SHARE_MAX of `event.distance_m`, each milestone step
    capped at +SINGLE_SESSION_STEP_CAP over the athlete's longest swim_ow in
    the prior LONGEST_SWIM_LOOKBACK_DAYS days.
  - `multi_day_stage`: back-to-back Saturday+Sunday swims, longest single
    day capped at STAGE_LONGEST_DAY_SHARE_MAX of `event.distance_m`, same
    single-session step cap applied per day.

Both ladders reuse `plan.generate_week` for the baseline weekly schedule
(pool placeholders, strength/recovery placement, macro-block/taper
volume caps) rather than re-implementing session scheduling -- only the
long-swim session(s), `target_volume_m`, and (on a cut) one strength->
recovery conversion are overridden on top of that baseline.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from uuid import uuid4

from swim_coach.load import (
    acute_chronic_ratio,
    compliance as compute_compliance,
    wellness_composite,
)
from swim_coach.models import Athlete, Event, MacroPlan, Session, Wellness, WeekPlan, Workout
from swim_coach.plan import (
    LONG_SWIM_SHARE,
    RECOVERY_SESSION_MIN,
    STAGE_SATURDAY_SHARE,
    WEEKLY_VOLUME_RAMP_CAP,
    _duration_min_for_distance,
    _round_100,
    _z2_pace_s_per_100m,
    generate_week,
)

# --- rule-table constants (ROADMAP.md "Adaptation rules") --------------------

WELLNESS_RED_THRESHOLD = 2.0
# ROADMAP.md: "wellness composite red (<=2.0)". library/03-periodization.md.

LOAD_RATIO_RED_THRESHOLD = 1.4
# ROADMAP.md: "7d:28d load ratio >1.4". library/03-periodization.md; see
# load.py's ACWR caveat (Feijen et al. 2021 / Garmin-RunSafe,
# library/reference_list.md) -- this ratio is a coarse secondary signal, not
# a precise injury forecast.

WELLNESS_WINDOW_DAYS = 7
# Trailing window (days, inclusive of as_of) averaged into the wellness
# red-flag check -- a single bad day shouldn't trigger a cut; a bad week
# should. Coach judgment, library/03-periodization.md.

CUT_VOLUME_FRACTION = 0.25
# ROADMAP.md: "cut volume 20-30%". This engine uses the documented range's
# midpoint as a single deterministic value rather than scaling continuously
# by how far over threshold the signals are (kept simple for Day 4; a finer
# severity-scaled cut is a reasonable future refinement). Coach judgment,
# library/03-periodization.md.

COMPLIANCE_REPEAT_THRESHOLD = 70.0
COMPLIANCE_ADVANCE_THRESHOLD = 90.0
# ROADMAP.md: "Compliance <70% -> repeat progression step"; "all green +
# compliance >=90% -> advance". library/03-periodization.md.

# --- long-swim ladder constants (library/06-long-swim-progression.md) -------

LONGEST_SWIM_LOOKBACK_DAYS = 30
# Garmin-RunSafe cohort (library/reference_list.md): injury risk tracked
# against the longest single session in the prior 30 days.

SINGLE_SESSION_STEP_CAP = 0.15
# Upper bound of ROADMAP.md's "+10-15% over the athlete's longest swim in
# the prior 30 days" milestone-step cap. The directly evidence-backed
# number is narrower: the Garmin-RunSafe cohort (library/reference_list.md,
# `[ADAPTED: running]`, confidence: medium) found injury risk rose above a
# single session exceeding the prior-30-day longest by *10%* specifically --
# this engine's 15% ceiling is ROADMAP's deliberately slightly more
# permissive upper bound, not itself a verified figure. The Santa Barbara
# Channel Swimming Association guidance (library/reference_list.md,
# "Practical / non-journal resources") separately recommends capping weekly
# volume increases at 10% and building via "2-3 major long-swim milestones,"
# consistent with treating milestone jumps (not smooth weekly ramps) as the
# primary lever here.

SINGLE_DAY_PEAK_SHARE_MIN = 0.60
SINGLE_DAY_PEAK_SHARE_MAX = 0.70
# ROADMAP.md: single_day peak long swim of "~60-70% of event distance"
# (Santa Barbara Channel Swimming Association guidance, "peak training
# swims of 20K to 23K (60-70% of target distance)" for a 33K swim --
# library/reference_list.md). The engine uses the MAX as a hard ceiling
# (never exceeded); the range's low end is advisory only, not separately
# enforced.

LONG_SWIM_SHARE_PEAK_MIN = 0.55
LONG_SWIM_SHARE_PEAK_MAX = 0.65
# ROADMAP.md: "Long-swim share of weekly volume rises to ~55-65% in peak
# weeks" -- library/06-long-swim-progression.md (to be authored). Not
# separately enforced as a hard planning cap in this pass (the ladder step
# cap and the peak-distance cap already bound the long swim); tracked here
# as the documented target range for /adapt's judgment review.

STAGE_LONGEST_DAY_SHARE_MIN = 0.30
STAGE_LONGEST_DAY_SHARE_MAX = 0.40
# ROADMAP.md: multi_day_stage "longest single swim tops out ~30-40% of
# total distance." Engine uses the MAX as a hard ceiling.
# library/06-long-swim-progression.md (to be authored).

RECOVERY_DAYS_AFTER_MILESTONE_MIN = 3
RECOVERY_DAYS_AFTER_MILESTONE_MAX = 5
# ROADMAP.md: "each milestone swim followed by 3-5 mandated easy/recovery
# days" (Garmin single-session finding + channel-swim guidance,
# library/reference_list.md). This engine enforces the MIN as a hard gate
# via `days_since_last_milestone` (below RECOVERY_DAYS_AFTER_MILESTONE_MIN
# days since the last milestone forces `hold`, no advance); the single week
# a call to `adapt_week` can directly annotate as "easy" is bounded by that
# week's own date range (see `adapt_week` docstring "Known limitation").

# --- informational intensity-balance check (not a planning constraint) -----

EASY_RPE_MAX = 5
# Coach judgment: RPE<=5 (of the Workout model's 1-10 scale) counts as
# "easy" for the informational intensity-balance check below. Not an
# [EVIDENCE] claim -- library/03-periodization.md.

TARGET_EASY_TIME_SHARE = 0.80
# ROADMAP.md "Adaptation rules": "balance 80/20 intensity distribution
# across total swim time." NOTE: the canonical 80/20 polarized-training
# citation (e.g. Seiler) is NOT in library/reference_list.md -- this project
# has no verified source for the specific "80/20" split, so it is applied
# here as Coach judgment, informational only. The engine cannot enforce this
# at *planning* time because pool-coach session content (most of weekly
# swim time) is unknown until delivered post-hoc; this is a monitoring
# signal surfaced in `adaptation_rationale` for /adapt's judgment review,
# not a session-generation constraint.

INTENSITY_BALANCE_WINDOW_DAYS = 28


# --- signal helpers ------------------------------------------------------------


def _wellness_mean(wellness: list[Wellness], as_of: date, window_days: int = WELLNESS_WINDOW_DAYS) -> float | None:
    cutoff = as_of - timedelta(days=window_days - 1)
    window = [w for w in wellness if cutoff <= w.date <= as_of]
    if not window:
        return None
    return sum(wellness_composite(w) for w in window) / len(window)


def _longest_recent_swim_m(
    workouts: list[Workout], as_of: date, window_days: int = LONGEST_SWIM_LOOKBACK_DAYS
) -> int:
    """Longest single open-water swim logged in the trailing `window_days`
    days (inclusive of `as_of`). Returns 0 if none -- the ladder then holds
    at the current planned distance rather than guessing a safe step from
    no data."""
    cutoff = as_of - timedelta(days=window_days - 1)
    candidates = [
        w.distance_m for w in workouts if w.sport == "swim_ow" and cutoff <= w.date <= as_of
    ]
    return max(candidates, default=0)


def _intensity_balance(
    workouts: list[Workout], as_of: date, window_days: int = INTENSITY_BALANCE_WINDOW_DAYS
) -> dict | None:
    """Informational easy/hard swim-time split over the trailing window (see
    TARGET_EASY_TIME_SHARE docstring above) -- surfaced in the rationale,
    never gates cut/repeat/advance. Returns None if no rpe-tagged swim time
    is logged in the window."""
    cutoff = as_of - timedelta(days=window_days - 1)
    window = [
        w
        for w in workouts
        if w.sport in ("swim_pool", "swim_ow") and w.rpe is not None and cutoff <= w.date <= as_of
    ]
    total_min = sum(w.duration_min for w in window)
    if total_min == 0:
        return None
    easy_min = sum(w.duration_min for w in window if w.rpe <= EASY_RPE_MAX)
    return {
        "easy_share": round(easy_min / total_min, 3),
        "target_easy_share": TARGET_EASY_TIME_SHARE,
        "total_swim_min": round(total_min, 1),
    }


# --- long-swim ladder ------------------------------------------------------------


def _advance_single_day_long_swim_m(
    current_long_swim_m: int,
    longest_recent_swim_m: int,
    event_distance_m: int,
    next_target_volume_m: int,
) -> int:
    """Next single-day continuous long-swim distance on an ADVANCE week.

    Monotonic (never below `current_long_swim_m`), bounded by three caps:
    the Garmin single-session step cap over the athlete's actual prior-30-
    day longest swim, the event-distance peak-share ceiling, and the
    physical ceiling of the week's own target volume.
    """
    peak_cap = round(event_distance_m * SINGLE_DAY_PEAK_SHARE_MAX)
    step_cap = (
        round(longest_recent_swim_m * (1 + SINGLE_SESSION_STEP_CAP))
        if longest_recent_swim_m > 0
        else current_long_swim_m
    )
    candidate = max(current_long_swim_m, min(step_cap, peak_cap))
    return min(candidate, next_target_volume_m)


def _advance_stage_weekend_swims_m(
    current_saturday_m: int,
    longest_recent_swim_m: int,
    event_distance_m: int,
    next_target_volume_m: int,
) -> tuple[int, int]:
    """Next (saturday_m, sunday_m) stage-swim pair on an ADVANCE week.

    Saturday (the longer day) is bounded by the same Garmin step cap and an
    event-distance peak-share ceiling as the single-day ladder, plus the
    total weekend volume available (`LONG_SWIM_SHARE` of `next_target_volume_m`,
    split via `STAGE_SATURDAY_SHARE` -- same constants `plan.py` uses for the
    weekly baseline). Sunday absorbs whatever weekend volume remains.
    """
    peak_cap = round(event_distance_m * STAGE_LONGEST_DAY_SHARE_MAX)
    step_cap = (
        round(longest_recent_swim_m * (1 + SINGLE_SESSION_STEP_CAP))
        if longest_recent_swim_m > 0
        else current_saturday_m
    )
    total_weekend = _round_100(next_target_volume_m * LONG_SWIM_SHARE)
    saturday_uncapped = _round_100(total_weekend * STAGE_SATURDAY_SHARE)
    saturday = max(current_saturday_m, min(saturday_uncapped, step_cap, peak_cap, total_weekend))
    sunday = max(0, total_weekend - saturday)
    return saturday, sunday


# --- main entry point --------------------------------------------------------------


def adapt_week(
    athlete: Athlete,
    event: Event,
    macro: MacroPlan,
    iso_week: str,
    week_start: date,
    current_week: WeekPlan,
    workouts: list[Workout],
    wellness: list[Wellness],
    as_of: date,
    days_since_last_milestone: int | None = None,
) -> WeekPlan:
    """Produce a draft next-week `WeekPlan` (`draft=True`) from the
    adaptation rule table + event-format-aware long-swim ladder (see module
    docstring).

    `current_week` is the most recently completed/finalized `WeekPlan` --
    its `target_volume_m` and long-swim session(s) are the baseline the
    ladder steps from (not the macro's idealized next-week interpolation).
    `as_of` is the last day of signal data to consider (typically the day
    before `week_start`). `days_since_last_milestone`, when known, gates a
    forced recovery-window `hold` (see RECOVERY_DAYS_AFTER_MILESTONE_MIN).

    Known limitation: ROADMAP.md's "each milestone followed by 3-5 easy/
    recovery days" spans into the week *after* a milestone week. A single
    call to `adapt_week` only controls one week's sessions, so it can only
    mark the day(s) within *this* week's own date range as post-milestone
    recovery (Sunday, for `single_day`) -- the remaining recovery days spill
    into the following week's `adapt_week` call, which should receive an
    accurate `days_since_last_milestone` (via the caller/CLI/skill) to
    enforce the rest of the window via the forced-hold rule above.
    """
    event_format = event.event_format

    # --- signals -------------------------------------------------------------
    wellness_mean = _wellness_mean(wellness, as_of)
    wellness_red = wellness_mean is not None and wellness_mean <= WELLNESS_RED_THRESHOLD

    load_ratio = acute_chronic_ratio(workouts, as_of)
    load_ratio_red = load_ratio is not None and load_ratio > LOAD_RATIO_RED_THRESHOLD

    last_week_dates = [s.date for s in current_week.sessions]
    last_week_start = min(last_week_dates) if last_week_dates else week_start - timedelta(days=7)
    last_week_end = max(last_week_dates) if last_week_dates else week_start - timedelta(days=1)
    last_week_workouts = [w for w in workouts if last_week_start <= w.date <= last_week_end]
    compliance_pct = compute_compliance(current_week.sessions, last_week_workouts)

    intensity_balance = _intensity_balance(workouts, as_of)

    # --- rule table (priority: cut > repeat > forced-recovery-window > advance > hold) ---
    fired: list[str] = []
    if wellness_red or load_ratio_red:
        action = "cut"
        if wellness_red:
            fired.append(
                f"wellness composite {wellness_mean:.2f} <= {WELLNESS_RED_THRESHOLD} over "
                f"trailing {WELLNESS_WINDOW_DAYS}d (red)"
            )
        if load_ratio_red:
            fired.append(
                f"7d:28d load ratio {load_ratio:.2f} > {LOAD_RATIO_RED_THRESHOLD} (red)"
            )
    elif compliance_pct < COMPLIANCE_REPEAT_THRESHOLD:
        action = "repeat"
        fired.append(
            f"compliance {compliance_pct:.1f}% < {COMPLIANCE_REPEAT_THRESHOLD}% -> "
            "repeat progression step"
        )
    elif (
        days_since_last_milestone is not None
        and days_since_last_milestone < RECOVERY_DAYS_AFTER_MILESTONE_MIN
    ):
        action = "hold"
        fired.append(
            f"only {days_since_last_milestone}d since last long-swim milestone "
            f"(< {RECOVERY_DAYS_AFTER_MILESTONE_MIN}d minimum) -> forced recovery "
            "window, no advance"
        )
    elif compliance_pct >= COMPLIANCE_ADVANCE_THRESHOLD:
        action = "advance"
        fired.append(
            f"all green + compliance {compliance_pct:.1f}% >= "
            f"{COMPLIANCE_ADVANCE_THRESHOLD}% -> advance"
        )
    else:
        action = "hold"
        fired.append(
            f"compliance {compliance_pct:.1f}% between {COMPLIANCE_REPEAT_THRESHOLD}% and "
            f"{COMPLIANCE_ADVANCE_THRESHOLD}%, no red flags -> hold"
        )

    # --- baseline schedule (pool/strength placement, taper caps) --------------
    baseline = generate_week(athlete, macro, iso_week, week_start, event_format=event_format)

    # --- target volume ---------------------------------------------------------
    current_target_volume_m = current_week.target_volume_m
    if action == "cut":
        next_target_volume_m = round(current_target_volume_m * (1 - CUT_VOLUME_FRACTION))
    elif action == "advance":
        next_target_volume_m = round(current_target_volume_m * (1 + WEEKLY_VOLUME_RAMP_CAP))
    else:  # repeat / hold
        next_target_volume_m = current_target_volume_m

    # --- long swim(s) ------------------------------------------------------------
    long_swim_sessions = [
        s for s in current_week.sessions if s.sport == "swim_ow" and s.date.weekday() in (5, 6)
    ]
    current_saturday_m = next(
        (s.distance_m for s in long_swim_sessions if s.date.weekday() == 5), 0
    )
    current_sunday_m = next(
        (s.distance_m for s in long_swim_sessions if s.date.weekday() == 6), 0
    )
    longest_recent_m = _longest_recent_swim_m(workouts, as_of)
    milestone = False

    if event_format == "multi_day_stage":
        if action == "advance":
            saturday_m, sunday_m = _advance_stage_weekend_swims_m(
                current_saturday_m, longest_recent_m, event.distance_m, next_target_volume_m
            )
            milestone = saturday_m > current_saturday_m
        else:
            saturday_m, sunday_m = current_saturday_m, current_sunday_m
            if action == "cut":
                weekend_total = saturday_m + sunday_m
                if weekend_total > next_target_volume_m and weekend_total > 0:
                    scale = next_target_volume_m / weekend_total
                    saturday_m = _round_100(saturday_m * scale)
                    sunday_m = max(0, next_target_volume_m - saturday_m)
    else:
        if action == "advance":
            saturday_m = _advance_single_day_long_swim_m(
                current_saturday_m, longest_recent_m, event.distance_m, next_target_volume_m
            )
            milestone = saturday_m > current_saturday_m
        else:
            saturday_m = current_saturday_m
            if action == "cut":
                saturday_m = min(saturday_m, next_target_volume_m)
        sunday_m = 0

    # --- assemble sessions: baseline schedule, long-swim override, cut/milestone tweaks ---
    pace_s = _z2_pace_s_per_100m(athlete)
    sessions: list[Session] = []
    for session in baseline.sessions:
        if session.sport == "swim_ow" and session.date.weekday() == 5:
            sessions.append(
                session.model_copy(
                    update={
                        "distance_m": saturday_m,
                        "duration_min": max(_duration_min_for_distance(saturday_m, pace_s), 15.0),
                    }
                )
            )
        elif session.sport == "swim_ow" and session.date.weekday() == 6:
            sessions.append(
                session.model_copy(
                    update={
                        "distance_m": sunday_m,
                        "duration_min": max(_duration_min_for_distance(sunday_m, pace_s), 15.0),
                    }
                )
            )
        else:
            sessions.append(session)

    if action == "cut":
        # "add a recovery day": convert the last strength session (ai_coach-
        # owned, not a fixed pool-coach commitment) into a recovery session.
        strength_indices = [i for i, s in enumerate(sessions) if s.sport == "strength"]
        if strength_indices:
            idx = strength_indices[-1]
            converted = sessions[idx]
            sessions[idx] = converted.model_copy(
                update={
                    "sport": "recovery",
                    "distance_m": None,
                    "duration_min": RECOVERY_SESSION_MIN,
                    "intensity": {"zone": "Z1", "anchor": "rpe"},
                    "purpose": (
                        "recovery (converted from strength) -- cut week: "
                        + "; ".join(fired)
                    ),
                    "structure": None,
                }
            )

    if milestone:
        # Mark the one post-milestone recovery day that falls within this
        # week's own date range (Sunday) as easy -- see "Known limitation"
        # in the docstring for the rest of the 3-5 day window.
        sessions = [
            (
                session.model_copy(
                    update={
                        "purpose": (
                            session.purpose
                            + " -- EASY (day 1 of post-milestone recovery window; "
                            f"{RECOVERY_DAYS_AFTER_MILESTONE_MIN}-"
                            f"{RECOVERY_DAYS_AFTER_MILESTONE_MAX}d window continues "
                            "into next week's plan)"
                        )
                    }
                )
                if session.date.weekday() == 6
                else session
            )
            for session in sessions
        ]

    rationale = {
        "action": action,
        "rules_fired": fired,
        "signals": {
            "wellness_composite_mean": wellness_mean,
            "wellness_window_days": WELLNESS_WINDOW_DAYS,
            "load_ratio_7d_28d": load_ratio,
            "compliance_pct": compliance_pct,
            "intensity_balance": intensity_balance,
        },
        "volume": {
            "previous_target_m": current_target_volume_m,
            "next_target_m": next_target_volume_m,
        },
        "long_swim": {
            "event_format": event_format,
            "previous_saturday_m": current_saturday_m,
            "previous_sunday_m": current_sunday_m,
            "next_saturday_m": saturday_m,
            "next_sunday_m": sunday_m,
            "longest_recent_swim_m": longest_recent_m,
            "milestone": milestone,
        },
    }

    return WeekPlan(
        id=uuid4(),
        athlete_id=athlete.id,
        iso_week=iso_week,
        meso_block=baseline.meso_block,
        focus=baseline.focus,
        target_volume_m=next_target_volume_m,
        sessions=sessions,
        adaptation_rationale=json.dumps(rationale, sort_keys=True),
        draft=True,
    )
