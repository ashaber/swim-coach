"""Open-water session-content template library.

General-purpose session CONTENT templates for open-water-specific training
concepts (feed-window/fueling practice, negative-split pacing, chop/wind
adaptation, sighting, breathing-pattern variation, back-to-back multi-day-
stage fatigue simulation, taper activation, and a full race dress
rehearsal) -- the open-water counterpart to `plan.py`'s existing
`_additional_swim_structure_template` (pool-independent aerobic swim) and
`_strength_session_structure_template` (dryland strength), same
architectural pattern: a plain Python function that takes `distance_m` and
`css_pace_s` and returns a `WorkoutStructure` template (relative
`basis="zone"` targets, resolved later by `workout_templates.resolve_template`
against whichever real athlete the coach/planner is authoring for -- nothing
here is Renee-specific or hardcoded to any one athlete's numbers).

Motivation: today, `plan.py`'s `generate_week` leaves the week's actual long
swim / stage sessions with `structure=None`/`structured=None` -- real
distance, no real content ("swim 6000m"). This module exists so a coach
(via `backend/app/tools.py`'s `build_ow_session` wiring below, see
`_apply_session_overrides`'s `ow_template` field) can pick a real,
open-water-specific session template by name instead of only a bare
distance number, for exactly the situation this was built for: an athlete
doing a stretch of open-water-only training with no pool-coach input to
lean on, where every session's actual content has to come from somewhere.

## Duration-floor design (Coach judgment, not a cited research finding)

Every template is tagged `scaling="skill_scalable"` or
`scaling="endurance_floor"` (`OWTemplateScaling`), an applied-coaching
distinction (Andrew's own judgment, not a research citation -- see
`library/18-open-water-session-templates.md`'s "Duration-floor design"
section for the fuller writeup) that governs how aggressively a caller
(e.g. a taper week's volume-reduction pass) may compress one of these
sessions:

- **`skill_scalable`** (negative-split pacing, chop/wind adaptation,
  sighting, breathing-pattern variation, taper activation): the skill being
  trained doesn't need full volume/duration to fire -- a 50% cut still
  rehearses the same pacing/technique judgment, just over less distance.
  Safe to scale down roughly proportionally with a taper/volume factor.
- **`endurance_floor`** (feed-window practice, back-to-back stage
  simulation, race dress rehearsal): the session's actual physiological
  purpose (fat-oxidation shift, gut/fueling training at race-relevant
  duration, accumulated-fatigue durability) requires a real minimum
  continuous duration to occur at all. Cutting a 6-hour endurance/fueling
  session to 3 hours does not "train half as much" -- it may train nothing
  useful for the session's actual purpose. Each `endurance_floor` template
  therefore declares `min_duration_min` and its `build_*` function raises
  `ValueError` rather than silently building a session below that floor;
  callers needing a genuinely shorter session on a given day should reach
  for a `skill_scalable` template instead, not force an endurance template
  under its floor.

`OW_SESSION_TEMPLATES` is the registry a coach-authoring tool (or a human)
picks a template `id` from; `build_ow_session(template_id, distance_m,
css_pace_s)` is the one dispatch entrypoint, mirroring `workout_templates.
build_main_set_step`'s role for the pool-independent main-set menu.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from swim_coach.models import WorkoutRepeat, WorkoutStep, WorkoutStructure, WorkoutTarget
from swim_coach.zones import zone_table

OWTemplateScaling = Literal["skill_scalable", "endurance_floor"]

# --- shared sizing constants -------------------------------------------------
# Coach judgment, same practitioner-convention warm-up/cool-down proportions
# already used by plan.py's pool-independent ADDITIONAL_SWIM_* constants
# (library/14-swim-set-structure.md) -- kept as this module's own constants
# (not imported from plan.py) so this module has no import-time dependency
# on plan.py, same "duplicate the trivial constant, don't cross-import"
# convention workout_templates.py already documents for `_format_pace_s`.
OW_WARM_UP_SHARE = 0.12
OW_WARM_UP_MIN_M = 300
OW_COOL_DOWN_SHARE = 0.06
OW_COOL_DOWN_MIN_M = 200

FEED_STOP_S = 60
# Coach judgment: matches a real practiced in-race feed-stop length: long
# enough to actually drink/eat and resight, short enough not to cool down or
# lose significant time. library/08-ultra-feeding.md covers WHAT/how much to
# feed (in-swim carbohydrate dosing); this module only concerns itself with
# rehearsing the stop-and-restart logistics at the right pace/distance.
FEED_REP_M = 1200
# Coach judgment: matches the Gemini-sourced practitioner convention this
# module's feed-window/back-to-back templates were adapted from (~20 min of
# steady swimming between feed stops at a typical ultra CSS) -- not an
# independently cited figure, see library/18-open-water-session-templates.md.

FEED_WINDOW_MIN_DURATION_MIN = 75.0
BACK_TO_BACK_MIN_DURATION_MIN = 75.0
RACE_REHEARSAL_MIN_DURATION_MIN = 90.0
# Coach judgment (Andrew): the minimum continuous duration below which these
# three `endurance_floor` templates' real purpose (gut/fueling rehearsal,
# accumulated-fatigue durability, full-scale race-pace rehearsal) is unlikely
# to fire at all -- see this module's docstring and
# library/18-open-water-session-templates.md. Deliberately well below a real
# multi-hour race-day duration: these mark "long enough for the mechanism to
# have a chance to occur," not "as long as race day."

NEG_SPLIT_MIN_DISTANCE_M = 800
CHOP_WIND_MIN_DISTANCE_M = 800
SIGHTING_MIN_DISTANCE_M = 600
BREATHING_PATTERN_MIN_DISTANCE_M = 600
# Coach judgment: structural floors (not duration-floor citations) for the
# `skill_scalable` templates -- just enough distance for two genuinely
# different-feeling legs/blocks to exist at all; below this the template
# would degenerate into a single short blob with no real contrast.

TAPER_ACTIVATION_MAX_DISTANCE_M = 2000
# Coach judgment: this template is deliberately short/sharp (neuromuscular
# activation, not fitness-building) -- scaling it UP defeats its own taper
# purpose, the mirror-image concern of the endurance-floor templates above.


def _format_pace_s(pace_s: float) -> str:
    """Format seconds-per-100m as M:SS. Duplicated one-liner, same rationale
    as `workout_templates._format_pace_s`'s own docstring (no cross-module
    import for a trivial, stable formatter)."""
    total = int(round(pace_s))
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def _zone_range(zone: dict) -> str:
    """Format a zone's pace range, handling the open (unbounded) ends Z1
    (no hi bound) and Z5 (no lo bound) carry -- `zone_table` leaves those
    `None` by design (see `zones.py`)."""
    lo, hi = zone["pace_lo_s"], zone["pace_hi_s"]
    if lo is not None and hi is not None:
        return f"{_format_pace_s(lo)}-{_format_pace_s(hi)}/100m"
    if hi is not None:
        return f"at or faster than {_format_pace_s(hi)}/100m"
    return f"at or slower than {_format_pace_s(lo)}/100m"


def _round_100(value: float) -> int:
    return int(round(value / 100)) * 100


def _round_50(value: float) -> int:
    return int(round(value / 50)) * 50


def _duration_min_for_distance(distance_m: float, pace_s_per_100m: float) -> float:
    return round(max(distance_m, 0) / 100 * pace_s_per_100m / 60, 1)


def _warm_up_cool_down(distance_m: int) -> tuple[int, int]:
    """Warm-up/cool-down distances for a given total, clamped so their sum
    never reaches `distance_m` even for a short session (falls back to a
    quarter/eighth split instead of the normal share-based sizing)."""
    warm_up = max(OW_WARM_UP_MIN_M, _round_100(distance_m * OW_WARM_UP_SHARE))
    cool_down = max(OW_COOL_DOWN_MIN_M, _round_100(distance_m * OW_COOL_DOWN_SHARE))
    if warm_up + cool_down >= distance_m:
        warm_up = max(100, _round_100(distance_m / 4))
        cool_down = max(100, _round_100(distance_m / 8))
    return warm_up, cool_down


def _require_min_duration(distance_m: int, css_pace_s: float, floor_min: float, template_label: str) -> None:
    duration_min = _duration_min_for_distance(distance_m, css_pace_s)
    if duration_min < floor_min:
        raise ValueError(
            f"{template_label} needs at least {floor_min:.0f} min of continuous "
            f"swimming to serve its real purpose -- {distance_m}m at this CSS "
            f"implies only {duration_min:.0f} min. See library/"
            "18-open-water-session-templates.md's duration-floor design; use a "
            "skill_scalable template instead if a shorter session is needed "
            "on this day."
        )


def _steady_with_feed_reps(
    main_budget: int, rep_m: int, zone_range_label: str, rep_note: str
) -> tuple[WorkoutRepeat, int]:
    """Shared builder for "N reps of steady swimming, each followed by a feed
    stop" -- reused by feed-window practice, back-to-back stage simulation,
    and the race dress rehearsal (all three are, mechanically, the same
    steady-plus-feed-stop shape; only the framing/labels differ). Returns
    the `WorkoutRepeat` node plus the actual total distance it consumes (may
    differ slightly from `main_budget` due to rounding to a whole rep)."""
    reps = max(1, round(main_budget / rep_m)) if main_budget >= rep_m else 1
    actual_rep_m = _round_100(main_budget / reps) if reps else main_budget
    swim_rep = WorkoutStep(
        label=f"{actual_rep_m}m steady at Z2 pace ({zone_range_label}) -- {rep_note}",
        role="interval",
        duration_kind="distance_m",
        duration_value=actual_rep_m,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )
    feed_step = WorkoutStep(
        label=(
            f"{FEED_STOP_S}s feed stop -- tread water, take your real in-race "
            "fluid/calories, sight your next landmark before setting off again."
        ),
        role="rest",
        duration_kind="time_s",
        duration_value=FEED_STOP_S,
        modality="swim",
    )
    repeat = WorkoutRepeat(repeat_mode="count", count=reps, steps=[swim_rep, feed_step])
    return repeat, actual_rep_m * reps


def _wrap(
    warm_up_m: int,
    warm_up_label: str,
    main_items: list[WorkoutStep | WorkoutRepeat],
    cool_down_m: int,
    why_label: str,
) -> WorkoutStructure:
    warmup_step = WorkoutStep(
        label=warm_up_label,
        role="warmup",
        duration_kind="distance_m",
        duration_value=warm_up_m,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )
    cooldown_step = WorkoutStep(
        label=f"{cool_down_m}m easy choice of stroke.",
        role="cooldown",
        duration_kind="distance_m",
        duration_value=cool_down_m,
        modality="swim",
    )
    why_step = WorkoutStep(label=why_label, role="open", duration_kind="open", modality="swim")
    return WorkoutStructure(items=[warmup_step, *main_items, cooldown_step, why_step])


# --- 1. Feed-window practice (endurance_floor) -------------------------------
# Adapted from an external prompt-experiment idea ("Feed-Window Simulator":
# repeated ~1200m Z2 reps broken by 60s treading-water feed stops) -- kept
# the mechanical shape, dropped the fictional "advisory panel" framing it
# arrived with. See library/18-open-water-session-templates.md.


def build_feed_window_practice_template(distance_m: int, css_pace_s: float) -> WorkoutStructure:
    """Steady Z2 swimming broken into reps by real feed stops -- rehearses
    the actual logistics of in-race feeding (stopping, drinking/eating,
    resighting, restarting) at race-relevant pace and duration. Raises
    `ValueError` if `distance_m` at this `css_pace_s` implies less than
    `FEED_WINDOW_MIN_DURATION_MIN` of continuous swimming."""
    _require_min_duration(distance_m, css_pace_s, FEED_WINDOW_MIN_DURATION_MIN, "feed-window practice")
    zones = zone_table(css_pace_s)
    z2 = zones["Z2"]
    warm_up, cool_down = _warm_up_cool_down(distance_m)
    main_budget = max(0, distance_m - warm_up - cool_down)
    main_repeat, actual_main = _steady_with_feed_reps(
        main_budget, FEED_REP_M, _zone_range(z2), "hold your form, don't chase the clock."
    )
    cool_down = max(0, cool_down + (main_budget - actual_main))
    return _wrap(
        warm_up,
        f"{warm_up}m easy free, settling into rhythm before the first feed rep.",
        [main_repeat],
        cool_down,
        (
            "Why: continuous fueling/gut-training rehearsal at race-relevant pace "
            "and duration -- practicing the actual logistics of feeding is what "
            "prevents a late-race bonk or a fumbled feed on race day, not just "
            "accumulating swim volume. Coach judgment: see "
            "library/18-open-water-session-templates.md."
        ),
    )


# --- 2. Out-and-back negative split (skill_scalable) -------------------------


def build_negative_split_ow_template(distance_m: int, css_pace_s: float) -> WorkoutStructure:
    """Out leg at Z2, back leg at Z3 (noticeably faster) -- trains the
    pacing discipline to hold back early and finish strong, the single most
    common way ultra swims go wrong. Raises `ValueError` below
    `NEG_SPLIT_MIN_DISTANCE_M` (not enough distance for two legs to feel
    genuinely different)."""
    if distance_m < NEG_SPLIT_MIN_DISTANCE_M:
        raise ValueError(
            f"negative-split practice needs at least {NEG_SPLIT_MIN_DISTANCE_M}m "
            f"so the two legs are long enough to feel different; got {distance_m}m."
        )
    zones = zone_table(css_pace_s)
    z2, z3 = zones["Z2"], zones["Z3"]
    warm_up, cool_down = _warm_up_cool_down(distance_m)
    leg_budget = max(200, distance_m - warm_up - cool_down)
    out_leg = _round_100(leg_budget / 2)
    back_leg = leg_budget - out_leg
    out_step = WorkoutStep(
        label=f"{out_leg}m out at a controlled Z2 pace ({_zone_range(z2)}) -- steady, aerobic, leave something in reserve.",
        role="interval",
        duration_kind="distance_m",
        duration_value=out_leg,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )
    back_step = WorkoutStep(
        label=(
            f"{back_leg}m back at Z3 pace ({_zone_range(z3)}) -- noticeably faster "
            "than the out leg. The point is finishing faster than you started, not "
            "just swimming hard the whole way."
        ),
        role="interval",
        duration_kind="distance_m",
        duration_value=back_leg,
        target=WorkoutTarget(basis="zone", zone="Z3"),
        modality="swim",
    )
    return _wrap(
        warm_up,
        f"{warm_up}m easy free.",
        [out_step, back_step],
        cool_down,
        (
            "Why: pacing discipline -- ultra-distance swims are lost by going out "
            "too hard; deliberately practicing negative splits builds the judgment "
            "(and the confidence) to hold back early. Coach judgment."
        ),
    )


# --- 3. Chop / headwind adaptation (skill_scalable) --------------------------


def build_chop_wind_adaptation_template(distance_m: int, css_pace_s: float) -> WorkoutStructure:
    """Into-chop/headwind half (harder effort, bilateral-breathing emphasis)
    plus a downwind half (relaxed, stretched-out stroke) -- rehearses
    technique under real conditions rather than only in calm water. Raises
    `ValueError` below `CHOP_WIND_MIN_DISTANCE_M`."""
    if distance_m < CHOP_WIND_MIN_DISTANCE_M:
        raise ValueError(
            f"chop/wind adaptation needs at least {CHOP_WIND_MIN_DISTANCE_M}m "
            f"for two genuinely different halves; got {distance_m}m."
        )
    zones = zone_table(css_pace_s)
    z2, z3 = zones["Z2"], zones["Z3"]
    warm_up, cool_down = _warm_up_cool_down(distance_m)
    leg_budget = max(200, distance_m - warm_up - cool_down)
    into_leg = _round_100(leg_budget / 2)
    down_leg = leg_budget - into_leg
    into_step = WorkoutStep(
        label=(
            f"{into_leg}m into the chop/headwind (or against the hardest water "
            f"you can find) at Z3 effort ({_zone_range(z3)}) -- deliberately "
            "bilateral breathing, higher stroke rate, shorter reach."
        ),
        role="interval",
        duration_kind="distance_m",
        duration_value=into_leg,
        target=WorkoutTarget(basis="zone", zone="Z3"),
        modality="swim",
    )
    down_step = WorkoutStep(
        label=(
            f"{down_leg}m downwind/with the chop behind you at Z2 ({_zone_range(z2)}) "
            "-- let the water help, stretch the stroke back out, use the push."
        ),
        role="interval",
        duration_kind="distance_m",
        duration_value=down_leg,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )
    return _wrap(
        warm_up,
        f"{warm_up}m easy free.",
        [into_step, down_step],
        cool_down,
        (
            "Why: race-day chop won't wait for calm water -- rehearsing bilateral "
            "breathing and stroke-rate control against resistance now is cheaper "
            "than discovering the gap on race day. Coach judgment."
        ),
    )


# --- 4. Sighting drill (skill_scalable) --------------------------------------


def build_sighting_drill_template(distance_m: int, css_pace_s: float) -> WorkoutStructure:
    """Compares a frequent-sighting block against an infrequent-sighting
    block over equal distance -- the goal is finding the minimum sighting
    frequency that still holds a straight line, not sighting reflexively
    every stroke. (Deliberately does NOT include an eyes-closed/no-sighting
    drift drill -- a real but avoidable open-water safety risk not worth
    the marginal training value; see library/18-open-water-session-
    templates.md.) Raises `ValueError` below `SIGHTING_MIN_DISTANCE_M`."""
    if distance_m < SIGHTING_MIN_DISTANCE_M:
        raise ValueError(
            f"sighting drill needs at least {SIGHTING_MIN_DISTANCE_M}m for two "
            f"comparable blocks; got {distance_m}m."
        )
    zones = zone_table(css_pace_s)
    z2 = zones["Z2"]
    warm_up, cool_down = _warm_up_cool_down(distance_m)
    leg_budget = max(200, distance_m - warm_up - cool_down)
    frequent_leg = _round_100(leg_budget / 2)
    infrequent_leg = leg_budget - frequent_leg
    frequent_step = WorkoutStep(
        label=(
            f"{frequent_leg}m at Z2 ({_zone_range(z2)}) sighting every 4-6 strokes "
            "-- pick a real landmark ahead, note how much it costs your rhythm."
        ),
        role="interval",
        duration_kind="distance_m",
        duration_value=frequent_leg,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )
    infrequent_step = WorkoutStep(
        label=(
            f"{infrequent_leg}m at Z2 ({_zone_range(z2)}) sighting every 8-10 "
            "strokes -- same landmark habit, fewer looks; check afterwards "
            "whether you drifted more."
        ),
        role="interval",
        duration_kind="distance_m",
        duration_value=infrequent_leg,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )
    return _wrap(
        warm_up,
        f"{warm_up}m easy free.",
        [frequent_step, infrequent_step],
        cool_down,
        (
            "Why: sighting costs stroke efficiency -- the goal is the minimum "
            "sighting frequency that still holds your line, not sighting on "
            "reflex. Coach judgment."
        ),
    )


# --- 5. Breathing-pattern variation (skill_scalable) -------------------------


def build_breathing_pattern_variation_template(distance_m: int, css_pace_s: float) -> WorkoutStructure:
    """Alternating 200m blocks of bilateral (every 3) and weak-side-only
    unilateral breathing -- builds breathing-side flexibility as a practiced
    option rather than a panic response when chop, sun glare, or a support
    kayak forces breathing off an athlete's preferred side. Raises
    `ValueError` below `BREATHING_PATTERN_MIN_DISTANCE_M`."""
    if distance_m < BREATHING_PATTERN_MIN_DISTANCE_M:
        raise ValueError(
            f"breathing-pattern variation needs at least "
            f"{BREATHING_PATTERN_MIN_DISTANCE_M}m for at least one full "
            f"bilateral/unilateral pair; got {distance_m}m."
        )
    zones = zone_table(css_pace_s)
    z2 = zones["Z2"]
    warm_up, cool_down = _warm_up_cool_down(distance_m)
    main_budget = max(200, distance_m - warm_up - cool_down)
    block_m = 200
    pairs = max(1, round(main_budget / (block_m * 2)))
    actual_main = block_m * 2 * pairs
    cool_down = max(0, cool_down + (main_budget - actual_main))
    bilateral_step = WorkoutStep(
        label=f"{block_m}m at Z2 ({_zone_range(z2)}) bilateral breathing, every 3 strokes.",
        role="interval",
        duration_kind="distance_m",
        duration_value=block_m,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )
    unilateral_step = WorkoutStep(
        label=(
            f"{block_m}m at Z2 ({_zone_range(z2)}) unilateral breathing, weak side "
            "only -- accept it'll feel awkward, that's the point."
        ),
        role="interval",
        duration_kind="distance_m",
        duration_value=block_m,
        target=WorkoutTarget(basis="zone", zone="Z2"),
        modality="swim",
    )
    main_repeat = WorkoutRepeat(repeat_mode="count", count=pairs, steps=[bilateral_step, unilateral_step])
    return _wrap(
        warm_up,
        f"{warm_up}m easy free.",
        [main_repeat],
        cool_down,
        (
            "Why: breathing-side flexibility -- conditions or a support kayak can "
            "force breathing off your preferred side; this builds that as a "
            "practiced option, not a panic response. Coach judgment."
        ),
    )


# --- 6. Back-to-back multi-day-stage fatigue simulation (endurance_floor) ---
# For `Event.event_format == "multi_day_stage"` athletes: trains swimming
# well on ALREADY-accumulated fatigue, the specific demand a stage event
# (not a single continuous swim) actually makes. Day 1 and Day 2 are two
# separate calls (two separate real training days, typically Saturday +
# Sunday) sharing one template function with different framing, not one
# session -- mirrors `plan.py`'s own `multi_day_stage` Saturday/Sunday split.

BackToBackDay = Literal["day_1", "day_2"]


def build_back_to_back_stage_simulation_template(
    day: BackToBackDay, distance_m: int, css_pace_s: float
) -> WorkoutStructure:
    """Day 1: steady Z2 swim with feed-stop rehearsal, framed around swimming
    an honest, sustainable pace rather than "banking" a fast day -- a stage
    race rewards consistent pacing across days, not one heroic day. Day 2:
    the same steady/feed-stop shape, explicitly framed as swum on
    yesterday's accumulated fatigue (pace naturally sitting at the easier
    end of Z2 is expected, not a red flag). Raises `ValueError` for an
    invalid `day` or below `BACK_TO_BACK_MIN_DURATION_MIN`."""
    if day not in ("day_1", "day_2"):
        raise ValueError(f"day must be 'day_1' or 'day_2', got {day!r}")
    _require_min_duration(distance_m, css_pace_s, BACK_TO_BACK_MIN_DURATION_MIN, "back-to-back stage simulation")
    zones = zone_table(css_pace_s)
    z2 = zones["Z2"]
    warm_up, cool_down = _warm_up_cool_down(distance_m)
    main_budget = max(0, distance_m - warm_up - cool_down)
    if day == "day_1":
        rep_note = "an honest, sustainable pace -- don't bank effort for tomorrow by going easy today."
        why = (
            "Why: Day 1 of a back-to-back stage simulation -- a stage race rewards "
            "consistent pacing across days, not one heroic day followed by a "
            "wrecked second day. Coach judgment (see "
            "library/18-open-water-session-templates.md)."
        )
        warm_up_label = f"{warm_up}m easy free."
    else:
        rep_note = (
            "whatever pace that honestly is on today's legs -- sitting at the "
            "easier end of Z2 is expected and fine, this is the point of the "
            "session."
        )
        why = (
            "Why: Day 2, swum on yesterday's accumulated fatigue -- this is the "
            "specific demand a multi-day stage event makes that a single fresh "
            "swim never rehearses: holding technique and a sane pace when "
            "already tired going in. Coach judgment."
        )
        warm_up_label = f"{warm_up}m easy free -- expect to feel yesterday in your shoulders; that's the point."
    main_repeat, actual_main = _steady_with_feed_reps(main_budget, FEED_REP_M, _zone_range(z2), rep_note)
    cool_down = max(0, cool_down + (main_budget - actual_main))
    return _wrap(warm_up, warm_up_label, [main_repeat], cool_down, why)


# --- 7. Taper activation & stroke feel (skill_scalable, has a MAX not a MIN) -


def build_taper_activation_template(distance_m: int, css_pace_s: float) -> WorkoutStructure:
    """Short, sharp neuromuscular-activation session for the final taper --
    easy swimming, a few race-pace reps, a couple of quick accelerations,
    easy cool-down. Deliberately capped, not floored: this is feel work, not
    a fitness-building session, so scaling it UP defeats its purpose. Raises
    `ValueError` above `TAPER_ACTIVATION_MAX_DISTANCE_M`."""
    if distance_m > TAPER_ACTIVATION_MAX_DISTANCE_M:
        raise ValueError(
            f"taper activation is deliberately short/sharp -- "
            f"{TAPER_ACTIVATION_MAX_DISTANCE_M}m max, got {distance_m}m. Use a "
            "different template for a longer session this close to race day."
        )
    zones = zone_table(css_pace_s)
    z2, z4, z5 = zones["Z2"], zones["Z4"], zones["Z5"]
    warm_up = max(300, _round_100(distance_m * 0.35))
    cool_down = max(150, _round_100(distance_m * 0.15))
    if warm_up + cool_down >= distance_m:
        warm_up = max(100, _round_100(distance_m / 3))
        cool_down = max(100, _round_100(distance_m / 6))
    remaining = max(0, distance_m - warm_up - cool_down)

    race_pace_m = min(remaining, _round_100(remaining * 0.65))
    race_pace_reps = max(1, round(race_pace_m / 200)) if race_pace_m >= 100 else 0
    race_pace_rep_m = _round_100(race_pace_m / race_pace_reps) if race_pace_reps else 0
    actual_race = race_pace_rep_m * race_pace_reps

    accel_total = max(0, remaining - actual_race)
    accel_reps = max(1, round(accel_total / 50)) if accel_total >= 50 else 0
    accel_rep_m = _round_50(accel_total / accel_reps) if accel_reps else 0
    if accel_reps and accel_rep_m == 0:
        # A small odd remainder rounded down to 0 at 50m resolution -- fall
        # back to the raw per-rep distance rather than silently dropping the
        # whole acceleration block (and its share of distance_m).
        accel_rep_m = max(25, int(accel_total / accel_reps))
    actual_accel = accel_rep_m * accel_reps

    # Any rounding slack (from either block) is absorbed by cool-down, same
    # reconciliation convention as every other template in this module --
    # guarantees the structure always sums exactly to distance_m.
    leftover = remaining - actual_race - actual_accel
    cool_down = max(0, cool_down + leftover)

    items: list[WorkoutStep | WorkoutRepeat] = []
    if race_pace_rep_m > 0:
        race_pace_step = WorkoutStep(
            label=(
                f"{race_pace_rep_m}m at goal race pace ({_zone_range(z4)}) -- "
                "smooth, controlled, remind your body what race effort feels like."
            ),
            role="interval",
            duration_kind="distance_m",
            duration_value=race_pace_rep_m,
            target=WorkoutTarget(basis="zone", zone="Z4"),
            modality="swim",
        )
        rest_step = WorkoutStep(
            label="60s easy rest.", role="rest", duration_kind="time_s", duration_value=60, modality="swim"
        )
        items.append(WorkoutRepeat(repeat_mode="count", count=race_pace_reps, steps=[race_pace_step, rest_step]))
    if accel_reps and accel_rep_m > 0:
        accel_step = WorkoutStep(
            label=f"{accel_rep_m}m accelerating to a fast, sharp finish ({_zone_range(z5)}).",
            role="interval",
            duration_kind="distance_m",
            duration_value=accel_rep_m,
            target=WorkoutTarget(basis="zone", zone="Z5"),
            modality="swim",
        )
        accel_rest = WorkoutStep(
            label="30s easy rest.", role="rest", duration_kind="time_s", duration_value=30, modality="swim"
        )
        items.append(WorkoutRepeat(repeat_mode="count", count=accel_reps, steps=[accel_step, accel_rest]))
    return _wrap(
        warm_up,
        f"{warm_up}m easy free, loosen up, no agenda.",
        items,
        cool_down,
        (
            "Why: taper activation -- short, sharp reminders at race pace keep "
            "neuromuscular sharpness without adding fatigue this close to race "
            "day; this is feel work, not a fitness-building session. Coach "
            "judgment."
        ),
    )


# --- 8. Race dress rehearsal (endurance_floor) -------------------------------


def build_race_dress_rehearsal_template(distance_m: int, css_pace_s: float) -> WorkoutStructure:
    """Continuous swim at goal race pace, in full planned race kit, with
    feed stops on the athlete's real practiced schedule -- the last
    full-scale rehearsal before race day itself. Raises `ValueError` below
    `RACE_REHEARSAL_MIN_DURATION_MIN`."""
    _require_min_duration(distance_m, css_pace_s, RACE_REHEARSAL_MIN_DURATION_MIN, "race dress rehearsal")
    zones = zone_table(css_pace_s)
    z2 = zones["Z2"]
    warm_up, cool_down = _warm_up_cool_down(distance_m)
    main_budget = max(0, distance_m - warm_up - cool_down)
    main_repeat, actual_main = _steady_with_feed_reps(
        main_budget,
        FEED_REP_M,
        _zone_range(z2),
        "goal race pace, in full planned race kit -- this is a rehearsal, treat it like race day.",
    )
    cool_down = max(0, cool_down + (main_budget - actual_main))
    return _wrap(
        warm_up,
        f"{warm_up}m easy free in full race kit.",
        [main_repeat],
        cool_down,
        (
            "Why: the last full-scale rehearsal before race day -- kit, pace, and "
            "fueling logistics all together, so race day itself has no first-time "
            "surprises. Coach judgment."
        ),
    )


# --- Registry / dispatcher ---------------------------------------------------


@dataclass(frozen=True)
class OWSessionTemplate:
    id: str
    label: str
    scaling: OWTemplateScaling
    min_duration_min: float | None
    max_distance_m: float | None
    source_note: str
    build: Callable[[int, float], WorkoutStructure]


OW_SESSION_TEMPLATES: dict[str, OWSessionTemplate] = {
    "feed_window_practice": OWSessionTemplate(
        id="feed_window_practice",
        label="Feed-window practice",
        scaling="endurance_floor",
        min_duration_min=FEED_WINDOW_MIN_DURATION_MIN,
        max_distance_m=None,
        source_note="Adapted from an external prompt-experiment idea ('Feed-Window Simulator').",
        build=build_feed_window_practice_template,
    ),
    "negative_split": OWSessionTemplate(
        id="negative_split",
        label="Out-and-back negative split",
        scaling="skill_scalable",
        min_duration_min=None,
        max_distance_m=None,
        source_note="Adapted from an external prompt-experiment idea ('Out-and-Back Negative Split').",
        build=build_negative_split_ow_template,
    ),
    "chop_wind_adaptation": OWSessionTemplate(
        id="chop_wind_adaptation",
        label="Chop / headwind adaptation",
        scaling="skill_scalable",
        min_duration_min=None,
        max_distance_m=None,
        source_note="Adapted from an external prompt-experiment idea ('Headwind & Chop Strength Endurance').",
        build=build_chop_wind_adaptation_template,
    ),
    "sighting_drill": OWSessionTemplate(
        id="sighting_drill",
        label="Sighting drill",
        scaling="skill_scalable",
        min_duration_min=None,
        max_distance_m=None,
        source_note=(
            "Adapted from an external prompt-experiment idea ('Blind Sighting Matrix') -- the "
            "eyes-closed/no-sighting drift component was deliberately dropped as an avoidable "
            "open-water safety risk, not carried over."
        ),
        build=build_sighting_drill_template,
    ),
    "breathing_pattern_variation": OWSessionTemplate(
        id="breathing_pattern_variation",
        label="Breathing-pattern variation",
        scaling="skill_scalable",
        min_duration_min=None,
        max_distance_m=None,
        source_note="Adapted from an external prompt-experiment idea ('Hypoxic Pace Control').",
        build=build_breathing_pattern_variation_template,
    ),
    "back_to_back_stage_day1": OWSessionTemplate(
        id="back_to_back_stage_day1",
        label="Back-to-back stage simulation -- Day 1",
        scaling="endurance_floor",
        min_duration_min=BACK_TO_BACK_MIN_DURATION_MIN,
        max_distance_m=None,
        source_note="Adapted from an external prompt-experiment idea ('The 3-Day Back-to-Back Simulator').",
        build=lambda distance_m, css_pace_s: build_back_to_back_stage_simulation_template(
            "day_1", distance_m, css_pace_s
        ),
    ),
    "back_to_back_stage_day2": OWSessionTemplate(
        id="back_to_back_stage_day2",
        label="Back-to-back stage simulation -- Day 2 (on yesterday's fatigue)",
        scaling="endurance_floor",
        min_duration_min=BACK_TO_BACK_MIN_DURATION_MIN,
        max_distance_m=None,
        source_note="Adapted from an external prompt-experiment idea ('The 3-Day Back-to-Back Simulator').",
        build=lambda distance_m, css_pace_s: build_back_to_back_stage_simulation_template(
            "day_2", distance_m, css_pace_s
        ),
    ),
    "taper_activation": OWSessionTemplate(
        id="taper_activation",
        label="Taper activation & stroke feel",
        scaling="skill_scalable",
        min_duration_min=None,
        max_distance_m=TAPER_ACTIVATION_MAX_DISTANCE_M,
        source_note="Adapted from an external prompt-experiment idea ('Taper Activation & Stroke Feel').",
        build=build_taper_activation_template,
    ),
    "race_dress_rehearsal": OWSessionTemplate(
        id="race_dress_rehearsal",
        label="Race dress rehearsal",
        scaling="endurance_floor",
        min_duration_min=RACE_REHEARSAL_MIN_DURATION_MIN,
        max_distance_m=None,
        source_note=(
            "Adapted from an external prompt-experiment idea originally framed around a specific "
            "multi-day event's Day 1 -- generalized here to any athlete's final full-scale "
            "rehearsal, not tied to a particular event format."
        ),
        build=build_race_dress_rehearsal_template,
    ),
}


def list_ow_session_templates() -> list[dict]:
    """Athlete/coach-facing summary of the library -- what a coach-authoring
    tool (or a human) picks a template `id` from."""
    return [
        {
            "id": t.id,
            "label": t.label,
            "scaling": t.scaling,
            "min_duration_min": t.min_duration_min,
            "max_distance_m": t.max_distance_m,
        }
        for t in OW_SESSION_TEMPLATES.values()
    ]


def build_ow_session(template_id: str, distance_m: int, css_pace_s: float) -> WorkoutStructure:
    """Dispatch to the named template's build function -- the one entrypoint
    a coach-authoring tool needs. Raises `ValueError` for an unknown
    `template_id`, or for `distance_m`/`css_pace_s` outside the named
    template's documented floor/ceiling (see each `build_*` function's own
    docstring)."""
    template = OW_SESSION_TEMPLATES.get(template_id)
    if template is None:
        raise ValueError(f"unknown ow_template id {template_id!r}; known ids: {sorted(OW_SESSION_TEMPLATES)}")
    return template.build(distance_m, css_pace_s)
