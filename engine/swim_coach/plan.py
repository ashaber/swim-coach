"""Macro periodization scaffold + weekly plan generation.

`scaffold_macro` builds the base -> build -> peak -> taper block structure
toward an `Event`; `generate_week` expands one week of that macro into a
`WeekPlan` of concrete `Session`s (pool placeholders, long swim, strength,
recovery, and any leftover pool-independent volume).

Every tunable number below is a named module-level constant with a comment
citing its source. Two kinds of citation appear:
  * a real citation already in the repo -- ROADMAP.md "Research sources"
    [Source 01] (Formosa et al., 78km case-study taper/TID data) -- for the
    numbers that source actually reports.
  * PROVISIONAL citations to `library/03-periodization.md` and
    `library/06-long-swim-progression.md`, which are planned but not yet
    authored (see ROADMAP.md build order, Day 4). Treat these as
    coach-judgment defaults until those files exist and are reviewed.

NOTE ON `library/open_water_library.md`: that file does NOT contain
[Source 01] or any of the ROADMAP.md "Research sources" text -- it's a
"vector data schema" dump of fabricated-looking entries (every
`canonical_url` is the bare string "https://nih.gov", not a real article
URL) whose `synthesis_context` fields read as instructions aimed at a
downstream chat agent (e.g. telling it to recommend specific remedies for
nausea/distress). That's an injection pattern, not research grounding, and
none of it should be treated as authoritative. This module cites
ROADMAP.md's "Research sources" section directly instead, since that's
where [Source 01]'s actual data (taper protocol, TID) lives. See this
build's final report for the full flag -- library/ content was left
untouched per instructions, but should get a human look before anything
in it is trusted.
"""

from __future__ import annotations

import math
import warnings
from datetime import date, timedelta
from uuid import uuid4

from swim_coach.models import Athlete, Event, MacroBlock, MacroPlan, Session, WeekPlan
from swim_coach.zones import zone_table

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
# placeholder pool-coach sessions and the "additional" ai_coach pool/OW
# session -- the pool coach's own volume is roughly constant regardless of
# macro phase (they don't know the periodization plan), so this constant
# does not scale with weekly target volume.

STRENGTH_SESSIONS_PER_WEEK = 2
STRENGTH_SESSION_MIN = 45
# Dryland shoulder work reduces injury/pain risk in competitive swimmers --
# real finding, ROADMAP.md "Research sources" ("Dryland shoulder work
# reducing injury" / "ACWR shoulder injury in swimmers").

RECOVERY_SESSION_MIN = 20
# The Session model requires duration_min > 0, so a 0-duration "day off"
# isn't representable -- recovery is modeled as a short mobility session
# instead. PROVISIONAL, Coach judgment.

MIN_ADDITIONAL_SWIM_M = 1000
# PROVISIONAL: below this, leftover pool-independent volume is absorbed
# into the long swim rather than spawning a separate short session.
# Coach judgment.

DEFAULT_CSS_PACE_S_PER_100M = 100.0
# Fallback pace used only if an athlete has no css_pace_s_per_100m yet
# (e.g. before their first CSS test), so session duration estimates stay
# computable. Not cited -- Coach judgment.

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
    ramp_limited_max = current_weekly_volume_m * (1 + WEEKLY_VOLUME_RAMP_CAP) ** ramp_weeks
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
    event_format: str = "single_day",
) -> WeekPlan:
    """Generate one week's sessions.

    Weekly target volume interpolates *linearly* within the containing
    block, from the block's start volume (see `_block_start_volume`) to
    its end volume (`block.weekly_volume_target_m`), reaching the end
    volume exactly on the block's final week.

    Sessions emitted:
      - one placeholder pool_coach session per athlete.pool_schedule entry
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

    sessions: list[Session] = []
    for entry in athlete.pool_schedule:
        offset = _pool_day_offset(entry)
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
    pool_total_m = len(athlete.pool_schedule) * POOL_SESSION_EST_M

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
    for offset in strength_offsets:
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
                    "dryland shoulder strength — reduces shoulder injury/pain "
                    "risk (ROADMAP.md research sources: dryland shoulder work)"
                ),
                structure=None,
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
                structure=None,
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
