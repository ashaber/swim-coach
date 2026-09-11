"""Tests for swim_coach.plan: macro scaffold + weekly plan generation.

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import re
import uuid
import warnings
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event, RaceWeekChecklistItem, WorkoutRepeat, WorkoutStep
from swim_coach.plan import (
    BIKE_DELOAD_CADENCE_WEEKS,
    BIKE_DELOAD_VOLUME_REDUCTION,
    BIKE_FINAL_TAPER_MIN_SESSIONS,
    BIKE_HARD_SESSION_MAX_MIN,
    BIKE_HARD_SESSION_SHARE,
    BIKE_INTERVAL_TEMPLATE_META,
    BIKE_INTERVAL_TEMPLATES,
    BIKE_SESSIONS_PER_WEEK,
    BODYWORK_WINDOW_DAYS_OUT,
    CARB_LOAD_WINDOW_START_DAYS_OUT,
    DEFAULT_BIKE_SESSION_MIN,
    DEFAULT_POOL_SESSION_MIN,
    LONG_SWIM_SHARE,
    MIN_MACRO_WEEKS,
    MIN_RAMP_SEED_VOLUME_M,
    NO_COACH_POOL_SESSION_FLOOR_M,
    POOL_SESSION_EST_M,
    SESSION_ADJUSTMENT_INCREASE_CAP_PCT,
    SHARPEN_WEEKS_MAX,
    SHARPEN_WEEKS_MIN,
    SHARPENING_MIN_MACRO_WEEKS,
    STRENGTH_CORE_EXERCISES,
    STRENGTH_EXERCISE_REFERENCE_URLS,
    STRENGTH_FULL_BODY_ADDITION,
    STRENGTH_SESSIONS_PER_WEEK,
    TAPER_WEEKLY_DECAY,
    TAPER_WEEKS_SHORT,
    WEEKLY_VOLUME_RAMP_CAP,
    _additional_swim_structure,
    _additional_swim_structure_template,
    _bike_ramp_week_index,
    _bike_week_sessions,
    _duration_min_for_distance,
    _format_pace_s,
    _no_coach_pool_purpose,
    _race_week_checklist,
    _round_100,
    _select_bike_interval_template,
    _strength_session_structure,
    _strength_session_structure_template,
    _z2_pace_s_per_100m,
    adjust_session,
    count_structured_steps,
    generate_week,
    scaffold_macro,
    scaffold_sharpening_macro,
)
from swim_coach.store import FileStore
from swim_coach.workout_templates import render_prose, resolve_template
from swim_coach.zones import zone_table

ATHLETE_ID = uuid.uuid4()
START = date(2026, 1, 5)  # a Monday


def make_athlete(**overrides):
    data = dict(
        id=ATHLETE_ID,
        slug="wife",
        name="Jane Doe",
        css_pace_s_per_100m=95.0,
        zones=None,
        constraints={},
        pool_schedule=["tue", "thu", "fri"],
    )
    data.update(overrides)
    return Athlete(**data)


def make_event(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        name="Catalina Channel",
        event_date=START + timedelta(weeks=24),
        distance_m=20000,
        water_temp_c=18.0,
        wetsuit=False,
        priority="A",
    )
    data.update(overrides)
    return Event(**data)


def _iso_week(d: date) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _leaf_steps(items):
    """Every real `WorkoutStep` leaf in a `WorkoutStructure.items`-shaped
    list, one level deep into any `WorkoutRepeat` (matches this codebase's
    own "no repeat nests inside another repeat" convention -- see
    `plan._bike_blocks_with_rest_main`'s own docstring)."""
    for item in items:
        if item.kind == "step":
            yield item
        else:
            yield from item.steps


def _total_structured_s(structured) -> float:
    """Recursively sum every leaf `WorkoutStep.duration_value` in a
    `WorkoutStructure`, correctly handling a `WorkoutRepeat` (each child's
    duration counted `count` times) and an "open" annotation step (no
    `duration_value` -- contributes 0, matching `plan._bike_open_header`'s
    own convention). Used by the bike-primary structured-content tests
    below now that a hard session's main block may be a `WorkoutRepeat`,
    not always one flat `WorkoutStep`."""
    total = 0.0
    for item in structured.items:
        if item.kind == "step":
            total += item.duration_value or 0.0
        else:
            multiplier = item.count if (item.repeat_mode == "count" and item.count) else 1
            total += multiplier * sum(
                (child.duration_value or 0.0) for child in item.steps if child.kind == "step"
            )
    return total


# --- block allocation ---------------------------------------------------------


def test_scaffold_macro_long_runway_block_allocation():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )

    assert [b.name for b in macro.blocks] == ["base", "build", "peak", "taper"]
    weeks = {
        b.name: (b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks
    }
    # 24 weeks total: taper=4, peak=3, remainder=17 -> base=ceil(17*0.6)=11, build=6
    assert weeks == {"base": 11, "build": 6, "peak": 3, "taper": 4}
    assert sum(weeks.values()) == 24

    # blocks are contiguous and span exactly [start_monday, event_monday)
    assert macro.blocks[0].start_date == START
    for prev, curr in zip(macro.blocks, macro.blocks[1:]):
        assert curr.start_date == prev.end_date + timedelta(days=1)
    assert macro.blocks[-1].end_date == START + timedelta(weeks=24) - timedelta(days=1)


def test_scaffold_macro_short_runway_block_allocation():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=10))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=14000, peak_weekly_volume_m=20000
    )

    weeks = {
        b.name: (b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks
    }
    # 10 weeks total: taper=2, peak=2, remainder=6 -> base=ceil(6*0.6)=4, build=2
    assert weeks == {"base": 4, "build": 2, "peak": 2, "taper": 2}
    assert sum(weeks.values()) == 10
    assert macro.blocks[-1].end_date == START + timedelta(weeks=10) - timedelta(days=1)


def test_scaffold_macro_raises_if_under_min_weeks():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=7))
    with pytest.raises(ValueError):
        scaffold_macro(athlete, event, START, current_weekly_volume_m=8000)


def test_scaffold_macro_non_distance_event_requires_explicit_peak_volume():
    # Multi-sport unlock: target_metric != "distance_m" has no validated
    # default-derivation formula (unlike PEAK_WEEKLY_VOLUME_X_EVENT_DISTANCE
    # for swim), so scaffold_macro must refuse to guess.
    athlete = make_athlete()
    event = make_event(
        event_date=START + timedelta(weeks=24),
        target_metric="duration_min",
        distance_m=None,
        target_value=120.0,
    )
    with pytest.raises(ValueError, match="requires an explicit peak_weekly_volume_m"):
        scaffold_macro(athlete, event, START, current_weekly_volume_m=8000)


def test_scaffold_macro_ramp_seed_uses_duration_floor_for_duration_metric_events():
    # Fragile note fixed here (originates in the already-merged #164, but
    # this PR is the first to produce real duration-path content, so the
    # first PR this actually bites): MIN_RAMP_SEED_VOLUME_M=1000 is METRES;
    # scaffold_macro's ramp-seed math ran unchanged for target_metric=
    # "duration_min" before this fix, so a real cyclist's seed became
    # "1000 minutes" -- the 8%/week ramp clamp barely engaged (clamping to
    # ~3700 "minutes" from a real 60-min/week start) instead of the correct
    # minutes-scale clamp (~222 minutes) a duration-unit seed produces.
    athlete = make_athlete(sports=["bike"])
    event = make_event(
        event_date=START + timedelta(weeks=24),
        target_metric="duration_min",
        distance_m=None,
        target_value=300.0,
    )
    with pytest.warns(UserWarning, match="ramp cap"):
        macro = scaffold_macro(
            athlete, event, START, current_weekly_volume_m=60, peak_weekly_volume_m=100000
        )
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    # 60 * 1.08**17 (17 ramp weeks over this runway) ~= 222 -- NOT ~3700,
    # which is what the metres-scale seed bug would have produced.
    assert peak_block.weekly_volume_target_m == pytest.approx(222, abs=2)


def test_scaffold_macro_non_distance_event_with_explicit_peak_volume_produces_a_macro():
    athlete = make_athlete()
    event = make_event(
        event_date=START + timedelta(weeks=24),
        target_metric="duration_min",
        distance_m=None,
        target_value=120.0,
    )
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    assert [b.name for b in macro.blocks] == ["base", "build", "peak", "taper"]
    # The ramp-cap safety math still applies -- sport-agnostic, no distance
    # assumption baked into it.
    assert macro.blocks[-2].weekly_volume_target_m <= 20000


# --- generate_week: bike-primary path (engine/cycling-coach) -----------------


def _make_bike_macro(**event_overrides):
    athlete = make_athlete(sports=["bike"])
    event = make_event(
        event_date=START + timedelta(weeks=24),
        target_metric="duration_min",
        distance_m=None,
        target_value=300.0,
        **event_overrides,
    )
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600
    )
    return athlete, event, macro


def test_generate_week_bike_primary_produces_real_bike_sessions():
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
    )
    bike_sessions = [s for s in week.sessions if s.sport == "bike"]
    assert len(bike_sessions) == BIKE_SESSIONS_PER_WEEK
    assert all(s.source == "ai_coach" for s in bike_sessions)
    assert all(s.distance_m is None for s in bike_sessions)
    assert all(s.duration_min > 0 for s in bike_sessions)
    assert all(s.status == "planned" for s in bike_sessions)
    # one hard (interval-template) session, the rest Z2 endurance -- the
    # hard session's zone now comes from whichever BIKE_INTERVAL_TEMPLATES
    # entry _select_bike_interval_template picks for this week (week_index
    # 0, since week_start is the macro's very first week), not a hardcoded
    # "Z3" (see plan.py's BIKE_INTERVAL_TEMPLATE_META comment for why).
    expected_hard_zone = BIKE_INTERVAL_TEMPLATE_META[_select_bike_interval_template(0)]["zone"]
    zones_used = [s.intensity["zone"] for s in bike_sessions]
    assert zones_used.count(expected_hard_zone) == 1
    assert zones_used.count("Z2") == BIKE_SESSIONS_PER_WEEK - 1
    # no "anchor" key -- power-based targets have no matching Session
    # intensity anchor value (css_pace/rpe/hr), so it's omitted, not
    # mislabeled.
    assert all("anchor" not in s.intensity for s in bike_sessions)
    assert week.race_week_checklist == []


def test_generate_week_bike_primary_includes_strength_session():
    # PR #167 red-team review, Finding 3 (must-fix): bike weeks previously
    # bypassed the strength-session placement mechanism entirely (3 bike
    # sessions, zero strength/recovery), despite
    # library/23-cycling-training.md's own cited knee/overuse-injury
    # evidence (Clarsen et al. 2010; Bini & Priego-Quesada 2022) having no
    # engine content attached. This now reuses the EXISTING swim strength
    # mechanism (STRENGTH_SESSIONS_PER_WEEK/_strength_sessions), not new
    # cycling-specific content.
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
    )
    strength_sessions = [s for s in week.sessions if s.sport == "strength"]
    assert len(strength_sessions) == STRENGTH_SESSIONS_PER_WEEK
    for s in strength_sessions:
        assert s.source == "ai_coach"
        assert s.duration_min > 0
        assert s.structure is not None
        assert s.status == "planned"
    # no silent gaps: total sessions is bike + strength, nothing dropped.
    assert len(week.sessions) == BIKE_SESSIONS_PER_WEEK + STRENGTH_SESSIONS_PER_WEEK
    # strength sessions don't collide with a bike-session day.
    bike_dates = {s.date for s in week.sessions if s.sport == "bike"}
    assert all(s.date not in bike_dates for s in strength_sessions)


def test_generate_week_bike_primary_total_duration_matches_target():
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
    )
    # target_volume_m is a BIKE duration target -- strength sessions'
    # STRENGTH_SESSION_MIN is separate, fixed content, not drawn from it.
    total = sum(s.duration_min for s in week.sessions if s.sport == "bike")
    assert total == pytest.approx(week.target_volume_m, rel=0.02)


def test_generate_week_bike_primary_hard_session_share():
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
    )
    expected_hard_zone = BIKE_INTERVAL_TEMPLATE_META[_select_bike_interval_template(0)]["zone"]
    hard = next(s for s in week.sessions if s.intensity["zone"] == expected_hard_zone)
    # This fixture's target (293 min) * BIKE_HARD_SESSION_SHARE would be
    # ~102.5 min uncapped -- above BIKE_HARD_SESSION_MAX_MIN (Finding 4), so
    # the hard session lands at the cap itself, not the raw share.
    assert week.target_volume_m * BIKE_HARD_SESSION_SHARE > BIKE_HARD_SESSION_MAX_MIN
    assert hard.duration_min == pytest.approx(BIKE_HARD_SESSION_MAX_MIN, rel=0.01)


def test_generate_week_bike_primary_without_ftp_has_no_watts():
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
    )
    for s in week.sessions:
        assert "ftp_watts_lo" not in s.intensity
        assert "ftp_watts_hi" not in s.intensity


def test_generate_week_bike_primary_with_ftp_sets_watt_bounds():
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete,
        macro,
        _iso_week(week_start),
        week_start,
        primary_sport="bike",
        ftp_watts=250.0,
    )
    # Full Z1-Z5 table (zones.py's BIKE_Z*_HI_PCT_FTP, library/23-cycling-
    # training.md) -- covers Z2 (every easy session) and whichever zone
    # this week's selected interval template's hard session actually uses
    # (BIKE_INTERVAL_TEMPLATE_META), not just "Z2"/"Z3".
    expected_lo_pct = {"Z1": 0.0, "Z2": 0.55, "Z3": 0.75, "Z4": 0.90, "Z5": 1.05}
    expected_hi_pct = {"Z1": 0.55, "Z2": 0.75, "Z3": 0.90, "Z4": 1.05, "Z5": 1.20}
    for s in week.sessions:
        if s.sport != "bike":
            continue
        zone = s.intensity["zone"]
        assert s.intensity["ftp_watts_lo"] == pytest.approx(250.0 * expected_lo_pct[zone], abs=1)
        assert s.intensity["ftp_watts_hi"] == pytest.approx(250.0 * expected_hi_pct[zone], abs=1)


def test_generate_week_default_primary_sport_is_swim_unchanged():
    # primary_sport defaults to "swim" -- every existing call site (no
    # kwarg passed) must keep producing the ordinary swim-week shape.
    athlete = make_athlete()
    event = make_event()
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    week_start = macro.blocks[0].start_date
    week_default = generate_week(athlete, macro, _iso_week(week_start), week_start)
    week_explicit = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="swim"
    )
    assert week_default.target_volume_m == week_explicit.target_volume_m
    assert [s.sport for s in week_default.sessions] == [s.sport for s in week_explicit.sessions]
    assert any(s.sport in ("swim_pool", "swim_ow") for s in week_default.sessions)


def test_generate_week_bike_primary_sessions_have_structured_content():
    # engine/cycling-coach Part C: bike sessions must carry real structured
    # content (warm-up + main block + cool-down) so the Garmin FIT push /
    # .zwo export paths have something real to export -- previously every
    # bike session left `structured=None`.
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start, primary_sport="bike")
    bike_sessions = [s for s in week.sessions if s.sport == "bike"]
    hard_zone = BIKE_INTERVAL_TEMPLATE_META[_select_bike_interval_template(0)]["zone"]
    for s in bike_sessions:
        assert s.structured is not None
        assert s.structure is not None
        assert all(step.modality == "bike" for step in _leaf_steps(s.structured.items))
        if s.intensity["zone"] != hard_zone:
            # every EASY (Z2) session is still a flat, non-progression main
            # block (PR #167 review, Finding 2: "steady" is the role that
            # tells zwo_export.py to export a SteadyState at the zone's
            # midpoint instead of a Ramp from 0%FTP) -- unchanged by this
            # pass, see `_bike_session_structure`.
            roles = [step.role for step in s.structured.items]
            assert "steady" in roles
        # warm-up + main + cool-down all sum, in seconds, to duration_min --
        # recursively through any WorkoutRepeat the hard session's selected
        # interval template introduced (see `_total_structured_s`).
        total_s = _total_structured_s(s.structured)
        assert total_s == pytest.approx(s.duration_min * 60, abs=1)


def test_generate_week_bike_primary_structured_uses_zone_basis_without_ftp():
    # Restricted to the easy (Z2) sessions -- those are still one flat
    # "steady" block (`_bike_session_structure`, unchanged by this pass).
    # The hard session's own structured-content/target-basis shape is
    # covered separately below (interval-template tests) since it may now
    # be a WorkoutRepeat, not a single top-level "steady" step.
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start, primary_sport="bike")
    for s in week.sessions:
        if s.sport != "bike" or s.intensity["zone"] != "Z2":
            continue
        main_step = next(step for step in s.structured.items if step.role == "steady")
        assert main_step.target.basis == "zone"
        assert main_step.target.zone == s.intensity["zone"]


def test_generate_week_bike_primary_structured_uses_power_w_with_ftp():
    # Restricted to the easy (Z2) sessions -- see the zone-basis test above
    # for why.
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, primary_sport="bike", ftp_watts=250.0
    )
    for s in week.sessions:
        if s.sport != "bike" or s.intensity["zone"] != "Z2":
            continue
        main_step = next(step for step in s.structured.items if step.role == "steady")
        assert main_step.target.basis == "power_w"
        assert main_step.target.low == pytest.approx(s.intensity["ftp_watts_lo"], abs=1)
        assert main_step.target.high == pytest.approx(s.intensity["ftp_watts_hi"], abs=1)


def test_generate_week_bike_primary_structured_prose_has_main_set_line():
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start, primary_sport="bike")
    for s in week.sessions:
        if s.sport != "bike":
            continue
        assert "Main set:" in s.structure


# --- _bike_week_sessions: day spread, hard-session cap, low-volume count ----
# (PR #167 review findings 3, 4, 5, 6) ----------------------------------------


def test_bike_week_sessions_days_are_spread_not_clustered():
    # Real review bug fixed here (Finding 3): `_pick_days(3, excluded=set())`
    # always returns [0, 1, 2] (Mon/Tue/Wed) -- the hardest day landing
    # first, with zero rest between any of the week's rides. The docstring
    # claimed "spread evenly... via _pick_days with no exclusions," which
    # was false (that only happened to work for swim because pool_offsets
    # excludes the intervening days there).
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 180.0, None)
    offsets = sorted((s.date - START).days for s in sessions)
    assert len(offsets) == len(set(offsets))  # distinct days
    assert offsets != [0, 1, 2]  # not clustered at the start of the week
    # no two sessions on adjacent days for a 3-session week -- genuinely
    # spread, not just "technically distinct."
    assert all(b - a > 1 for a, b in zip(offsets, offsets[1:]))


def test_bike_week_sessions_hard_session_capped_for_large_weekly_total():
    # Real review bug fixed here (Finding 4): `hard_min = total_duration_min
    # * BIKE_HARD_SESSION_SHARE` had no ceiling -- a 600-min week produced a
    # 210-minute continuous Z3 block, with nothing (CTL, ramp history,
    # ftp_watts provenance) sanity-checking it.
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 600.0, None)
    expected_hard_zone = BIKE_INTERVAL_TEMPLATE_META[_select_bike_interval_template(0)]["zone"]
    hard = next(s for s in sessions if s.intensity["zone"] == expected_hard_zone)
    assert hard.duration_min <= BIKE_HARD_SESSION_MAX_MIN
    # The duration beyond the cap goes to the week's Z2 volume, not lost --
    # total actual duration still tracks the target.
    total = sum(s.duration_min for s in sessions)
    assert total == pytest.approx(600.0, rel=0.02)


def test_bike_week_sessions_hard_session_uncapped_below_threshold():
    # The cap must not distort an ordinary, already-sane week.
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 150.0, None)
    expected_hard_zone = BIKE_INTERVAL_TEMPLATE_META[_select_bike_interval_template(0)]["zone"]
    hard = next(s for s in sessions if s.intensity["zone"] == expected_hard_zone)
    assert hard.duration_min == pytest.approx(150.0 * BIKE_HARD_SESSION_SHARE, rel=0.05)
    assert hard.duration_min < BIKE_HARD_SESSION_MAX_MIN


def test_bike_week_sessions_low_volume_reduces_session_count_not_floor_inflation():
    # Real review bug fixed here (Finding 6): flooring EACH session's
    # duration at DEFAULT_BIKE_SESSION_MIN independently inflated a taper
    # week's total by up to 50% (a 30-min target -> 45 actual, three
    # sessions floored to 15 each) -- silently violating the ramp cap
    # that was already applied upstream. Reducing session count instead
    # keeps total duration within a small, bounded tolerance of the target.
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 30.0, None)
    total = sum(s.duration_min for s in sessions)
    assert total == pytest.approx(30.0, rel=0.15)
    assert len(sessions) < BIKE_SESSIONS_PER_WEEK
    assert all(s.duration_min > 0 for s in sessions)


def test_bike_week_sessions_ordinary_volume_keeps_full_session_count():
    # A normal (non-taper) week must not be affected by Finding 6's fix.
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 300.0, None)
    assert len(sessions) == BIKE_SESSIONS_PER_WEEK


def test_bike_week_sessions_is_indoor_defaults_to_none():
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 180.0, None)
    assert all(s.is_indoor is None for s in sessions)


def test_bike_week_sessions_is_indoor_param_reaches_sessions():
    # Real review bug fixed here (Finding 5): `Session.is_indoor` had no
    # producer anywhere -- every real bike session this engine planned left
    # it permanently `None`, so the indoor-rejection branch in
    # `app.garmin_push`/`app.routes.garmin` covered a state that could
    # never occur in practice. This threads a real, explicit, caller-
    # overridable parameter through to make the mechanism reachable.
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 180.0, None, is_indoor=True)
    assert sessions  # sanity: fixture actually produced sessions
    assert all(s.is_indoor is True for s in sessions)


def test_generate_week_bike_primary_bike_indoor_param_reaches_sessions():
    # Same guarantee as above, through the public generate_week API a real
    # caller would actually use.
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete,
        macro,
        _iso_week(week_start),
        week_start,
        primary_sport="bike",
        bike_indoor=True,
    )
    # `is_indoor` is a bike-specific field -- strength sessions never set it
    # (not a "which bike ride" question), so this only applies to the
    # week's actual bike sessions.
    assert all(s.is_indoor is True for s in week.sessions if s.sport == "bike")


def test_generate_week_bike_primary_default_bike_indoor_is_none():
    # Default (no bike_indoor passed) must stay exactly as before --
    # additive-only, zero behavior change for every existing call site.
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start, primary_sport="bike")
    assert all(s.is_indoor is None for s in week.sessions)


def test_generate_week_bike_primary_warns_when_event_target_metric_is_load_au():
    # Fragile note fixed here (PR #167 review): generate_week's bike path
    # interprets target_volume_m as MINUTES (see this function's own
    # docstring); a macro scaffolded toward a target_metric="load_au" event
    # feeds an arbitrary-unit AU number through the exact same path with
    # nothing to catch the mismatch. A cheap warning beats silence -- real
    # load_au-bike support stays out of scope for this pass.
    athlete = make_athlete(sports=["bike"])
    event = make_event(
        event_date=START + timedelta(weeks=24),
        target_metric="load_au",
        distance_m=None,
        target_value=300.0,
    )
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600
    )
    week_start = macro.blocks[0].start_date
    with pytest.warns(UserWarning, match="load_au"):
        generate_week(
            athlete, macro, _iso_week(week_start), week_start, primary_sport="bike", event=event
        )


def test_generate_week_bike_primary_no_warning_when_event_omitted():
    # Every existing call site (no `event` kwarg under primary_sport="bike")
    # must keep behaving exactly as before -- no new warning just because
    # `event` wasn't supplied (the bike path doesn't require it).
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        generate_week(athlete, macro, _iso_week(week_start), week_start, primary_sport="bike")


def test_generate_week_bike_primary_no_warning_for_duration_min_event():
    # The ordinary, intended case (target_metric="duration_min") must not
    # warn.
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        generate_week(
            athlete, macro, _iso_week(week_start), week_start, primary_sport="bike", event=event
        )


# --- bike interval-template rotation + periodic deload ---------------------
# (engine/cycling-coach, interval-template/deload pass, grounded in
# library/24-cycling-periodization-intervals.md) -----------------------------


def test_select_bike_interval_template_cycles_through_all_four_in_fixed_order():
    from swim_coach.plan import _BIKE_ROTATION_TEMPLATES

    # "openers" (Build A defect 5) is in BIKE_INTERVAL_TEMPLATES but NOT in
    # the blind week-to-week rotation -- it is only ever selected via
    # `use_openers` (taper block / race proximity).
    assert _BIKE_ROTATION_TEMPLATES == tuple(
        t for t in BIKE_INTERVAL_TEMPLATES if t != "openers"
    )
    seen = [_select_bike_interval_template(i) for i in range(8)]
    assert seen[:4] == list(_BIKE_ROTATION_TEMPLATES)
    assert seen[4:8] == list(_BIKE_ROTATION_TEMPLATES)  # wraps and repeats
    assert "openers" not in seen


def test_bike_ramp_week_index_is_continuous_across_block_boundaries():
    athlete, event, macro = _make_bike_macro()
    macro_start = macro.blocks[0].start_date
    assert _bike_ramp_week_index(macro, macro_start) == 0
    assert _bike_ramp_week_index(macro, macro_start + timedelta(weeks=1)) == 1
    # A week inside the SECOND block (build) still counts continuously from
    # the macro's own start -- does not reset to 0 at the block boundary.
    build_block = next(b for b in macro.blocks if b.name == "build")
    expected = (build_block.start_date - macro_start).days // 7
    assert _bike_ramp_week_index(macro, build_block.start_date) == expected
    assert expected > 0


def test_generate_week_bike_primary_hard_session_varies_across_consecutive_weeks():
    # The actual "before/after" proof of gap #1: consecutive weeks' hard
    # session must NOT all be identical flat blocks any more.
    athlete, event, macro = _make_bike_macro()
    base_block = next(b for b in macro.blocks if b.name == "base")
    weeks_to_check = min(4, (base_block.end_date - base_block.start_date).days // 7 + 1)
    hard_zones = []
    hard_purposes = []
    for i in range(weeks_to_check):
        week_start = base_block.start_date + timedelta(weeks=i)
        week = generate_week(
            athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
        )
        bike_sessions = [s for s in week.sessions if s.sport == "bike"]
        hard = next(s for s in bike_sessions if s.intensity["zone"] != "Z2")
        hard_zones.append(hard.intensity["zone"])
        hard_purposes.append(hard.purpose)
    # Real variety: not every one of the first 4 weeks is the same template.
    assert len(set(hard_purposes)) > 1
    # And it matches the documented fixed rotation order exactly.
    assert hard_purposes == [
        BIKE_INTERVAL_TEMPLATE_META[_select_bike_interval_template(i)]["purpose"]
        for i in range(weeks_to_check)
    ]


def test_bike_sustained_threshold_hard_session_is_a_real_repeat_structure():
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 300.0, 250.0, week_index=0)
    assert _select_bike_interval_template(0) == "sustained_threshold"
    hard = next(s for s in sessions if s.intensity["zone"] == "Z4")
    repeats = [item for item in hard.structured.items if item.kind == "repeat"]
    assert len(repeats) == 1
    repeat = repeats[0]
    assert 2 <= repeat.count <= 3  # BIKE_SUSTAINED_THRESHOLD_MIN/MAX_REPS
    assert len(repeat.steps) == 2
    work, rest = repeat.steps
    assert work.duration_value == pytest.approx(600.0)  # BIKE_SUSTAINED_THRESHOLD_WORK_S
    assert work.target.basis == "power_w"


def test_bike_over_unders_hard_session_has_flat_top_level_blocks_no_nested_repeats():
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 300.0, 250.0, week_index=1)
    assert _select_bike_interval_template(1) == "over_unders"
    hard = next(s for s in sessions if s.intensity["zone"] == "Z4")
    block_repeats = [item for item in hard.structured.items if item.kind == "repeat"]
    assert 2 <= len(block_repeats) <= 4  # BIKE_OVER_UNDER_MIN/MAX_BLOCKS
    # No nesting: every top-level WorkoutRepeat's own children are plain
    # WorkoutSteps (zwo_export's IntervalsT conversion requires this).
    for block in block_repeats:
        assert all(child.kind == "step" for child in block.steps)
        assert block.count == 2  # BIKE_OVER_UNDER_CYCLES_PER_BLOCK
        on, off = block.steps
        assert on.duration_value == pytest.approx(90.0)
        assert off.duration_value == pytest.approx(90.0)
        assert on.target.low > off.target.low  # "over" is genuinely harder than "under"


def test_bike_short_short_hard_session_has_correct_30_15_ratio():
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 300.0, 250.0, week_index=2)
    assert _select_bike_interval_template(2) == "short_short_vo2"
    hard = next(s for s in sessions if s.intensity["zone"] == "Z5")
    set_repeats = [item for item in hard.structured.items if item.kind == "repeat"]
    assert 1 <= len(set_repeats) <= 2  # BIKE_SHORT_SHORT_MIN/MAX_SETS
    for one_set in set_repeats:
        assert one_set.count == 10  # BIKE_SHORT_SHORT_REPS_PER_SET
        on, off = one_set.steps
        assert on.duration_value == pytest.approx(30.0)
        assert off.duration_value == pytest.approx(15.0)


def test_bike_race_pace_hard_session_is_a_real_repeat_structure():
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 300.0, 250.0, week_index=3)
    assert _select_bike_interval_template(3) == "race_pace"
    hard = next(s for s in sessions if s.intensity["zone"] == "Z5")
    repeats = [item for item in hard.structured.items if item.kind == "repeat"]
    assert len(repeats) == 1
    repeat = repeats[0]
    assert 3 <= repeat.count <= 5  # BIKE_RACE_PACE_MIN/MAX_REPS
    work, rest = repeat.steps
    assert work.duration_value == pytest.approx(150.0)  # BIKE_RACE_PACE_WORK_S


# --- threshold-history build: FTP-check purpose-text note -----------------


def test_bike_first_sustained_threshold_week_notes_ftp_check_when_source_is_app_estimate():
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(
        athlete, START, 300.0, 250.0, week_index=0, ftp_source="app_estimate"
    )
    assert _select_bike_interval_template(0) == "sustained_threshold"
    hard = next(s for s in sessions if s.intensity["zone"] == "Z4")
    assert "also doubles as a rough FTP check" in hard.purpose


def test_bike_first_sustained_threshold_week_notes_ftp_check_when_source_is_self_reported_historical():
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(
        athlete, START, 300.0, 250.0, week_index=0, ftp_source="self_reported_historical"
    )
    hard = next(s for s in sessions if s.intensity["zone"] == "Z4")
    assert "also doubles as a rough FTP check" in hard.purpose


def test_bike_first_sustained_threshold_week_no_note_when_ftp_source_is_a_real_test():
    athlete = make_athlete(sports=["bike"])
    for real_source in ("field_test", "ramp_test", "race_file"):
        sessions = _bike_week_sessions(
            athlete, START, 300.0, 250.0, week_index=0, ftp_source=real_source
        )
        hard = next(s for s in sessions if s.intensity["zone"] == "Z4")
        assert "FTP check" not in hard.purpose


def test_bike_first_sustained_threshold_week_no_note_when_ftp_source_is_none():
    # Default -- every existing call site keeps producing byte-identical
    # output unless updated to pass ftp_source.
    athlete = make_athlete(sports=["bike"])
    sessions = _bike_week_sessions(athlete, START, 300.0, 250.0, week_index=0)
    hard = next(s for s in sessions if s.intensity["zone"] == "Z4")
    assert "FTP check" not in hard.purpose


def test_bike_ftp_check_note_only_on_the_first_sustained_threshold_week_not_later_ones():
    # week_index=4 also lands on "sustained_threshold" (the rotation cycles
    # every 4 weeks), but it is NOT the macro's first occurrence -- the note
    # is deliberately scoped to week_index == 0 only.
    athlete = make_athlete(sports=["bike"])
    assert _select_bike_interval_template(4) == "sustained_threshold"
    sessions = _bike_week_sessions(
        athlete, START, 300.0, 250.0, week_index=4, ftp_source="app_estimate"
    )
    hard = next(s for s in sessions if s.intensity["zone"] == "Z4")
    assert "FTP check" not in hard.purpose


def test_bike_ftp_check_note_only_on_sustained_threshold_not_other_templates():
    # week_index=1 -> "over_unders" -- an app_estimate source must not leak
    # the note onto a week whose hard session isn't even the
    # sustained_threshold template this heuristic is scoped to.
    athlete = make_athlete(sports=["bike"])
    assert _select_bike_interval_template(1) == "over_unders"
    sessions = _bike_week_sessions(
        athlete, START, 300.0, 250.0, week_index=1, ftp_source="app_estimate"
    )
    hard = next(s for s in sessions if s.intensity["zone"] == "Z4")
    assert "FTP check" not in hard.purpose


def test_bike_ftp_check_note_reaches_generate_week_end_to_end():
    athlete, event, macro = _make_bike_macro()
    week_start = macro.blocks[0].start_date

    week = generate_week(
        athlete,
        macro,
        _iso_week(week_start),
        week_start,
        primary_sport="bike",
        ftp_watts=250.0,
        ftp_source="app_estimate",
    )
    hard = next(s for s in week.sessions if s.sport == "bike" and s.intensity.get("zone") == "Z4")
    assert "also doubles as a rough FTP check" in hard.purpose


# --- threshold-history build: bike ramp test --------------------------------


def test_bike_ramp_test_structure_starts_with_warmup_then_ramp_role():
    from swim_coach.plan import _bike_ramp_test_structure

    structured = _bike_ramp_test_structure(None)
    assert structured.items[0].role == "warmup"
    assert structured.items[1].role == "ramp"
    assert structured.items[1].modality == "bike"
    assert structured.items[1].target.basis == "power_w"


def test_bike_ramp_test_structure_no_current_ftp_uses_fixed_default_start():
    from swim_coach.plan import (
        BIKE_RAMP_TEST_START_WATTS_DEFAULT,
        _bike_ramp_test_structure,
    )

    structured = _bike_ramp_test_structure(None)
    ramp = structured.items[1]
    assert ramp.target.low == pytest.approx(BIKE_RAMP_TEST_START_WATTS_DEFAULT)


def test_bike_ramp_test_structure_known_ftp_starts_at_half_ftp():
    from swim_coach.plan import (
        BIKE_RAMP_TEST_START_FRACTION_OF_FTP,
        _bike_ramp_test_structure,
    )

    structured = _bike_ramp_test_structure(300.0)
    ramp = structured.items[1]
    assert ramp.target.low == pytest.approx(300.0 * BIKE_RAMP_TEST_START_FRACTION_OF_FTP)


def test_bike_ramp_test_structure_climbs_steadily_not_flat():
    from swim_coach.plan import _bike_ramp_test_structure

    structured = _bike_ramp_test_structure(250.0)
    ramp = structured.items[1]
    assert ramp.target.high > ramp.target.low  # a real climb, not a flat block


def test_bike_ramp_test_structure_no_nonsensical_negative_or_zero_values():
    # The warm-up step legitimately carries a Z1-derived low bound of 0
    # (same zero-floor case zwo_export._convert_leaf corrects at export
    # time for every bike warm-up in this engine, not specific to the ramp
    # test) -- this test's own job is the RAMP step specifically, which
    # must always be a real, positive, genuinely climbing power range.
    from swim_coach.plan import _bike_ramp_test_structure

    for ftp in (None, 150.0, 300.0, 500.0):
        structured = _bike_ramp_test_structure(ftp)
        ramp = next(item for item in structured.items if item.role == "ramp")
        assert ramp.duration_value > 0
        assert ramp.target.low > 0
        assert ramp.target.high > ramp.target.low


def test_bike_ramp_test_structure_exports_valid_ramp_element():
    # Real end-to-end proof: build the structure, export it through the
    # exact same ZWO pipeline any other bike session uses, and read the
    # raw XML back -- matching this session's own discipline of reading
    # real output, not just trusting a structure-level assertion.
    import xml.etree.ElementTree as ET

    from swim_coach.plan import _bike_ramp_test_structure
    from swim_coach.zwo_export import to_zwo_workout

    structured = _bike_ramp_test_structure(263.0)
    xml_str = to_zwo_workout(structured, ftp_watts=263.0, name="FTP Ramp Test")
    root = ET.fromstring(xml_str)
    workout = root.find("workout")
    tags = [child.tag for child in workout]
    assert tags[0] == "Warmup"
    assert "Ramp" in tags
    ramp = workout.find("Ramp")
    assert float(ramp.attrib["PowerLow"]) > 0
    assert float(ramp.attrib["PowerHigh"]) > float(ramp.attrib["PowerLow"])
    assert int(ramp.attrib["Duration"]) > 0
    # Cool-down auto-appended by to_zwo_workout's own trailing fallback --
    # this generator deliberately appends no cool-down of its own (a real
    # ramp test ends at voluntary failure, not a planned duration).
    assert tags[-1] == "Cooldown"


def test_ftp_from_ramp_test_applies_75_percent_of_best_1min_power():
    from swim_coach.plan import BIKE_RAMP_TEST_FTP_FROM_BEST_1MIN_FRACTION, ftp_from_ramp_test

    assert BIKE_RAMP_TEST_FTP_FROM_BEST_1MIN_FRACTION == pytest.approx(0.75)
    # Matches roadmancycling.com's own worked example, direct-fetch
    # confirmed this session: "If your final minute averaged 320W, your
    # FTP estimate is 240W."
    assert ftp_from_ramp_test(320.0) == pytest.approx(240.0)


# --- Build F: real 2x20 FTP test protocol ------------------------------------


def test_bike_2x20_test_structure_shape_warmup_effort_recovery_effort_cooldown():
    from swim_coach.plan import _bike_2x20_test_structure

    structured = _bike_2x20_test_structure(None)
    roles = [item.role for item in structured.items]
    assert roles[0] == "warmup"
    assert "interval" in roles
    assert "recovery" in roles
    assert roles[-2] == "cooldown"  # trailing "Why:" open step comes last
    assert roles[-1] == "open"
    # Exactly two work efforts.
    assert roles.count("interval") == 2


def test_bike_2x20_test_work_steps_never_carry_power_w_or_zone_target():
    # THE regression this build exists to prevent: a real FTP TEST must
    # never prescribe a fixed power target for the athlete to pace to --
    # that defeats the entire point of testing (measuring the athlete's
    # real, unknown ceiling) and silently turns a test into an ordinary
    # training session (the real incident that motivated this build).
    from swim_coach.plan import _bike_2x20_test_structure

    for ftp in (None, 200.0, 350.0):
        structured = _bike_2x20_test_structure(ftp)
        work_steps = [item for item in structured.items if item.role == "interval"]
        assert len(work_steps) == 2
        for step in work_steps:
            assert step.target is not None
            assert step.target.basis == "rpe"
            assert step.target.basis != "power_w"
            assert step.target.basis != "zone"


def test_bike_2x20_test_work_steps_are_real_20_minute_efforts():
    from swim_coach.plan import BIKE_2X20_TEST_EFFORT_MIN, _bike_2x20_test_structure

    structured = _bike_2x20_test_structure(250.0)
    work_steps = [item for item in structured.items if item.role == "interval"]
    for step in work_steps:
        assert step.duration_kind == "time_s"
        assert step.duration_value == pytest.approx(BIKE_2X20_TEST_EFFORT_MIN * 60)
        assert step.modality == "bike"


def test_bike_2x20_test_has_a_real_recovery_interval_between_efforts():
    from swim_coach.plan import BIKE_2X20_TEST_RECOVERY_MIN, _bike_2x20_test_structure

    structured = _bike_2x20_test_structure(250.0)
    recovery = next(item for item in structured.items if item.role == "recovery")
    assert recovery.duration_kind == "time_s"
    assert recovery.duration_value == pytest.approx(BIKE_2X20_TEST_RECOVERY_MIN * 60)
    # Sits between the two work efforts, not before/after both of them.
    roles = [item.role for item in structured.items]
    interval_indices = [i for i, r in enumerate(roles) if r == "interval"]
    recovery_index = roles.index("recovery")
    assert interval_indices[0] < recovery_index < interval_indices[1]


def test_bike_2x20_test_why_line_documents_pacing_not_target():
    # The trailing "Why:" line is real, athlete-facing pacing guidance
    # (a legitimate coaching cue), never a target power number.
    from swim_coach.plan import _bike_2x20_test_structure

    structured = _bike_2x20_test_structure(250.0)
    why_step = structured.items[-1]
    assert why_step.role == "open"
    assert "Why:" in why_step.label
    assert "W" not in why_step.label.split("Why:")[1].split(".")[0]  # no stray watt figure


def test_bike_2x20_test_structure_exports_cleanly_via_zwo():
    # Real end-to-end proof the rpe-basis work steps don't crash the ZWO
    # pipeline -- they carry no power target, so they must degrade to a
    # FreeRide element rather than raising or silently mis-exporting a
    # power number that was never actually prescribed.
    import xml.etree.ElementTree as ET

    from swim_coach.plan import _bike_2x20_test_structure
    from swim_coach.zwo_export import to_zwo_workout

    structured = _bike_2x20_test_structure(263.0)
    xml_str = to_zwo_workout(structured, ftp_watts=263.0, name="2x20 FTP Test")
    root = ET.fromstring(xml_str)
    workout = root.find("workout")
    tags = [child.tag for child in workout]
    assert tags[0] == "Warmup"
    assert tags[-1] == "Cooldown"
    assert tags.count("FreeRide") == 2  # the two untargeted rpe-basis efforts


def test_bike_2x20_test_structure_exports_cleanly_via_garmin_fit():
    # Same real end-to-end proof for the Garmin/.FIT export path.
    from swim_coach.garmin_export import to_garmin_fit_workout
    from swim_coach.plan import _bike_2x20_test_structure

    structured = _bike_2x20_test_structure(263.0)
    fit_bytes = to_garmin_fit_workout(structured, sport="bike", name="2x20 FTP Test")
    assert isinstance(fit_bytes, (bytes, bytearray))
    assert len(fit_bytes) > 0


def test_ftp_from_2x20_test_applies_95_percent_of_average_of_both_efforts():
    from swim_coach.plan import BIKE_2X20_TEST_FTP_FROM_AVG_FRACTION, ftp_from_2x20_test

    assert BIKE_2X20_TEST_FTP_FROM_AVG_FRACTION == pytest.approx(0.95)
    # Worked example: two efforts averaging 300W and 280W -> mean 290W ->
    # FTP = 290 * 0.95 = 275.5W.
    assert ftp_from_2x20_test(300.0, 280.0) == pytest.approx(275.5)
    # Order-independent (a true average of the two readings).
    assert ftp_from_2x20_test(280.0, 300.0) == pytest.approx(275.5)


def test_ftp_from_2x20_test_equal_efforts_matches_single_effort_convention():
    # When both efforts are identical, this must reduce to exactly the
    # well-established single-20-minute-effort convention
    # (BIKE_2X20_TEST_FTP_FROM_AVG_FRACTION applied directly) -- a sanity
    # check that averaging two equal readings doesn't distort the number.
    from swim_coach.plan import ftp_from_2x20_test

    assert ftp_from_2x20_test(300.0, 300.0) == pytest.approx(300.0 * 0.95)


def test_bike_interval_template_low_volume_degrades_to_flat_block():
    # Same low-volume graceful-degradation posture as _resolve_bike_session_
    # count -- when the available main-block time is too small to fit even
    # one full work bout of the selected template, fall back to the classic
    # flat single block rather than emitting a malformed/overflowing
    # structure. In practice DEFAULT_BIKE_SESSION_MIN's 15-min floor keeps
    # `_bike_week_sessions` from ever actually reaching this main_s that
    # small (see `_bike_warmup_cooldown_reserve`'s own math), so this is
    # exercised directly against the template builder, the same way
    # `_fit_units_with_flexible_gap`'s own degenerate-count path is real
    # defensive code for an input this build's own callers don't currently
    # produce.
    from swim_coach.plan import (
        _bike_over_unders_main,
        _bike_short_short_main,
        _bike_sustained_threshold_main,
    )

    for builder, unit_s in (
        (_bike_sustained_threshold_main, 600.0),
        (_bike_over_unders_main, 360.0),
        (_bike_short_short_main, 450.0),
    ):
        main_s = unit_s - 30.0  # just under one whole unit
        items = builder(main_s, None)
        assert len(items) == 1
        assert items[0].kind == "step"
        assert items[0].role == "steady"
        assert items[0].duration_value == pytest.approx(main_s)


def test_generate_week_bike_primary_deload_week_reduces_target_volume():
    # library/24's cadence (BIKE_DELOAD_CADENCE_WEEKS=4, "three build weeks,
    # one reduced-volume week") applied to a bike-primary macro's
    # base/build/peak span.
    from swim_coach.plan import _block_start_volume, _find_block

    athlete, event, macro = _make_bike_macro()
    macro_start = macro.blocks[0].start_date
    deload_found = False
    for week_index in range(20):  # this fixture's base+build+peak span
        week_start = macro_start + timedelta(weeks=week_index)
        block_index, block = _find_block(macro, week_start)
        if block.name == "taper":
            break
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        week_index_in_block = (week_start - block.start_date).days // 7
        start_volume = _block_start_volume(macro, block_index, block)
        end_volume = block.weekly_volume_target_m
        frac = (week_index_in_block + 1) / weeks_in_block
        expected_non_deload = round(start_volume + (end_volume - start_volume) * frac)

        week = generate_week(
            athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
        )
        is_deload = (week_index + 1) % BIKE_DELOAD_CADENCE_WEEKS == 0
        if is_deload:
            deload_found = True
            expected_deload = round(expected_non_deload * (1 - BIKE_DELOAD_VOLUME_REDUCTION))
            assert week.target_volume_m == expected_deload
            assert week.target_volume_m < expected_non_deload
            assert "deload" in week.focus.lower()
        else:
            assert week.target_volume_m == expected_non_deload
            assert "deload" not in week.focus.lower()
    assert deload_found  # sanity: this fixture's runway actually exercises it


def test_generate_week_bike_primary_deload_never_applies_in_taper():
    athlete, event, macro = _make_bike_macro()
    taper_block = next(b for b in macro.blocks if b.name == "taper")
    weeks_in_taper = (taper_block.end_date - taper_block.start_date).days // 7 + 1
    for i in range(weeks_in_taper):
        week_start = taper_block.start_date + timedelta(weeks=i)
        week = generate_week(
            athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
        )
        assert "deload" not in week.focus.lower()


def test_generate_week_bike_primary_deload_week_still_produces_real_sessions():
    # A deload week's reduced target must still be a real, non-degenerate
    # week -- reuses _resolve_bike_session_count's own graceful session-
    # count reduction (Finding 6) rather than anything new.
    athlete, event, macro = _make_bike_macro()
    macro_start = macro.blocks[0].start_date
    # Calendar week 4 (1-indexed) = ramp_week_index 3 -> this fixture's
    # first deload week (see the cadence test above).
    deload_week_start = macro_start + timedelta(weeks=3)
    week = generate_week(
        athlete, macro, _iso_week(deload_week_start), deload_week_start, primary_sport="bike"
    )
    bike_sessions = [s for s in week.sessions if s.sport == "bike"]
    assert len(bike_sessions) >= 1
    assert all(s.duration_min > 0 for s in bike_sessions)
    total = sum(s.duration_min for s in bike_sessions)
    assert total == pytest.approx(week.target_volume_m, rel=0.15)


def test_generate_week_bike_primary_swim_macro_unaffected_by_deload_or_rotation():
    # Deload/rotation are scoped strictly to primary_sport="bike" -- an
    # ordinary swim macro's weekly target must be untouched (same math as
    # before this pass).
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    week_start = macro.blocks[0].start_date + timedelta(weeks=3)  # would be a deload week if bike
    from swim_coach.plan import _block_start_volume, _find_block

    block_index, block = _find_block(macro, week_start)
    weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
    week_index_in_block = (week_start - block.start_date).days // 7
    start_volume = _block_start_volume(macro, block_index, block)
    end_volume = block.weekly_volume_target_m
    frac = (week_index_in_block + 1) / weeks_in_block
    expected = round(start_volume + (end_volume - start_volume) * frac)

    week = generate_week(athlete, macro, _iso_week(week_start), week_start)  # default: swim
    assert week.target_volume_m == expected


def test_generate_week_rejects_unknown_primary_sport():
    athlete = make_athlete()
    event = make_event()
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    week_start = macro.blocks[0].start_date
    with pytest.raises(ValueError, match="unknown primary_sport"):
        generate_week(
            athlete, macro, _iso_week(week_start), week_start, primary_sport="run"
        )


def test_scaffold_macro_refuses_2k_per_week_athlete_signing_up_for_20k_next_week():
    # Regression test for a real scenario Andrew explicitly named as
    # intentional friction to preserve, not a bug to fix: an athlete
    # currently swimming 2000m/week impulsively signs up for a 20000m event
    # about a week out. MIN_MACRO_WEEKS (8 weeks minimum runway) must still
    # refuse this outright -- there's no safe way to periodize a 20km swim
    # in a single week regardless of current_weekly_volume_m or
    # peak_weekly_volume_m. This isn't new behavior; the test exists purely
    # so this exact, real-world-named shape never silently regresses.
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=1), distance_m=20000)

    with pytest.raises(ValueError, match="need at least 8 to periodize"):
        scaffold_macro(athlete, event, START, current_weekly_volume_m=2000)


def test_scaffold_macro_start_snaps_to_next_monday():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=10))
    tuesday = START + timedelta(days=1)
    macro = scaffold_macro(
        athlete, event, tuesday, current_weekly_volume_m=14000, peak_weekly_volume_m=20000
    )
    # Monday on/after a Tuesday is the *following* Monday, not the same week
    assert macro.blocks[0].start_date == START + timedelta(days=7)


# --- peak volume sizing ---------------------------------------------------------


def test_peak_volume_defaults_from_event_distance():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24), distance_m=20000)
    # current volume generous enough that the ramp cap doesn't bind
    macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=30000)
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    assert peak_block.weekly_volume_target_m == 50000  # 20000 * 2.5


def test_peak_volume_clamped_by_ramp_cap_when_default():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24), distance_m=50000)
    with pytest.warns(UserWarning, match="clamped"):
        macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=5000)
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    ramp_weeks = next(
        (b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks if b.name == "base"
    ) + next((b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks if b.name == "build")
    expected = round(5000 * (1 + WEEKLY_VOLUME_RAMP_CAP) ** ramp_weeks)
    assert peak_block.weekly_volume_target_m == expected


def test_peak_volume_clamped_even_when_passed_explicitly():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24), distance_m=20000)
    with pytest.warns(UserWarning, match="clamped"):
        macro = scaffold_macro(
            athlete, event, START, current_weekly_volume_m=5000, peak_weekly_volume_m=999_999
        )
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    assert peak_block.weekly_volume_target_m < 999_999


def test_peak_volume_not_clamped_when_under_cap_and_explicit():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24), distance_m=20000)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        macro = scaffold_macro(
            athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
        )
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    assert peak_block.weekly_volume_target_m == 20000


# --- zero-volume ramp-cap bug fix (MIN_RAMP_SEED_VOLUME_M) ----------------------


def test_scaffold_macro_zero_current_volume_produces_nonzero_ramped_macro():
    # Regression test for the ramp-cap bug: current_weekly_volume_m=0 (a
    # real, legitimate starting point -- a brand-new swimmer) used to zero
    # out ramp_limited_max entirely (0 * anything == 0), so
    # peak_volume = min(candidate_peak, ramp_limited_max) was always 0 and
    # every block (base/build/peak) inherited it, regardless of the
    # requested target. The fix seeds the ramp ceiling at
    # MIN_RAMP_SEED_VOLUME_M instead of the raw (possibly zero) current
    # volume -- this asserts the macro comes back non-zero and sensibly
    # ramped instead.
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24), distance_m=20000)
    with pytest.warns(UserWarning, match="clamped"):
        macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=0)

    base_block = next(b for b in macro.blocks if b.name == "base")
    build_block = next(b for b in macro.blocks if b.name == "build")
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    assert base_block.weekly_volume_target_m > 0
    assert build_block.weekly_volume_target_m > 0
    assert peak_block.weekly_volume_target_m > 0

    ramp_weeks = next(
        (b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks if b.name == "base"
    ) + next((b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks if b.name == "build")
    expected_ceiling = round(MIN_RAMP_SEED_VOLUME_M * (1 + WEEKLY_VOLUME_RAMP_CAP) ** ramp_weeks)
    assert peak_block.weekly_volume_target_m == expected_ceiling


def test_scaffold_macro_zero_current_volume_generates_a_usable_week():
    # End-to-end: a zero-volume macro must be usable by generate_week too,
    # not just non-zero at the MacroBlock level (this is the actual failure
    # mode reported: the tool "succeeded" but every generated week had
    # target_volume_m == 0).
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=10), distance_m=5000)
    with pytest.warns(UserWarning, match="clamped"):
        macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=0)
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)
    assert week.target_volume_m > 0


def test_scaffold_macro_near_zero_current_volume_also_seeded():
    # A tiny-but-nonzero current volume (below the seed) must also be
    # seeded up, not just literal zero -- max(current, seed) covers both.
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24), distance_m=20000)
    with pytest.warns(UserWarning, match="clamped"):
        macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=200)
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    assert peak_block.weekly_volume_target_m > 0


# --- taper decay ----------------------------------------------------------------


def test_taper_block_end_volume_decays_25pct_per_week_over_4_weeks():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    taper_block = next(b for b in macro.blocks if b.name == "taper")
    # 4-week taper: 20000 * (1 - 0.25*4) == 0
    assert taper_block.weekly_volume_target_m == 0


def test_taper_weekly_targets_decay_within_block():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    taper_block = next(b for b in macro.blocks if b.name == "taper")
    targets = []
    for i in range(4):
        week_start = taper_block.start_date + timedelta(weeks=i)
        week = generate_week(athlete, macro, _iso_week(week_start), week_start)
        targets.append(week.target_volume_m)
    # 20000 * (1 - 0.25*1..4) == 15000, 10000, 5000, 0
    assert targets == [15000, 10000, 5000, 0]


# --- ramp cap property ------------------------------------------------------------


def test_ramp_cap_never_exceeded_across_whole_macro():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    targets = []
    for block in macro.blocks:
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(athlete, macro, _iso_week(week_start), week_start)
            targets.append(week.target_volume_m)

    for prev, curr in zip(targets, targets[1:]):
        if curr > prev:
            # allow a couple of meters of rounding slack
            assert curr <= prev * (1 + WEEKLY_VOLUME_RAMP_CAP) + 2


# --- generate_week session composition -------------------------------------------


@pytest.fixture
def short_macro():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=10))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=14000, peak_weekly_volume_m=20000
    )
    return athlete, macro


def test_generate_week_pool_placeholders_on_right_days(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    pool_sessions = [s for s in week.sessions if s.sport == "swim_pool" and s.source == "pool_coach"]
    assert len(pool_sessions) == 3
    assert {s.date.weekday() for s in pool_sessions} == {1, 3, 4}  # tue, thu, fri
    for s in pool_sessions:
        assert s.structure is None
        assert s.status == "planned"
        assert s.intensity == {"anchor": "rpe"}
        assert "pool coach" in s.purpose


def test_generate_week_long_swim_on_saturday(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    long_swims = [s for s in week.sessions if s.sport == "swim_ow" and s.date.weekday() == 5]
    assert len(long_swims) == 1
    assert long_swims[0].intensity == {"zone": "Z2", "anchor": "css_pace"}
    assert long_swims[0].distance_m >= 0


def test_generate_week_long_swim_structure_unchanged_regression(short_macro):
    # Regression guard: the Saturday long swim (and, in multi_day_stage
    # format, its Sunday stage counterpart) must stay continuous/
    # negative-split per library/06-long-swim-progression.md -- this plan
    # only adds structure to strength sessions and the separate
    # "additional" swim_ow session, never to these weekend sessions.
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date

    single = generate_week(athlete, macro, _iso_week(week_start), week_start, event_format="single_day")
    single_weekend = [s for s in single.sessions if s.sport == "swim_ow" and s.date.weekday() in (5, 6)]
    assert len(single_weekend) == 1
    assert single_weekend[0].structure is None
    assert single_weekend[0].purpose == "long open-water swim — endurance and fueling-practice anchor of the week"

    stage = generate_week(athlete, macro, _iso_week(week_start), week_start, event_format="multi_day_stage")
    stage_weekend = [s for s in stage.sessions if s.sport == "swim_ow" and s.date.weekday() in (5, 6)]
    assert len(stage_weekend) == 2
    for session in stage_weekend:
        assert session.structure is None


def test_generate_week_strength_and_recovery_counts(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    strength = [s for s in week.sessions if s.sport == "strength"]
    assert len(strength) == STRENGTH_SESSIONS_PER_WEEK
    pool_offsets = {1, 3, 4}
    # placed on non-pool days where possible
    assert {s.date.weekday() for s in strength}.isdisjoint(pool_offsets)

    recovery = [s for s in week.sessions if s.sport == "recovery"]
    assert len(recovery) == 1
    assert recovery[0].duration_min > 0
    assert recovery[0].purpose == "mobility / full rest"


def test_generate_week_strength_sessions_carry_real_structure(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    strength = sorted(
        (s for s in week.sessions if s.sport == "strength"), key=lambda s: s.date
    )
    assert len(strength) == STRENGTH_SESSIONS_PER_WEEK
    for session in strength:
        assert session.structure is not None
        assert session.structure.strip() != ""
        # every session includes the rotator-cuff/scapular-stability core
        for exercise in STRENGTH_CORE_EXERCISES:
            assert exercise in session.structure

    # the two sessions aren't identical -- the second layers in full-body work
    assert strength[0].structure != strength[1].structure
    assert "full-body" in strength[1].structure.lower()


def test_strength_session_structure_matches_session_index():
    session_0 = _strength_session_structure(0)
    session_1 = _strength_session_structure(1)
    for exercise in STRENGTH_CORE_EXERCISES:
        assert exercise in session_0
        assert exercise in session_1
    assert "full-body" not in session_0.lower()
    assert "full-body" in session_1.lower()


def test_generate_week_volume_within_tolerance_across_macro(short_macro):
    athlete, macro = short_macro
    for block in macro.blocks:
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(athlete, macro, _iso_week(week_start), week_start)
            total_swim = sum(
                s.distance_m or 0 for s in week.sessions if s.sport in ("swim_pool", "swim_ow")
            )
            if week.target_volume_m == 0:
                continue
            deviation = abs(total_swim - week.target_volume_m) / week.target_volume_m
            assert deviation <= 0.10, (
                f"{week.iso_week}: total swim {total_swim} vs target "
                f"{week.target_volume_m} (block={block.name})"
            )


def test_generate_week_outside_macro_raises(short_macro):
    athlete, macro = short_macro
    too_early = macro.blocks[0].start_date - timedelta(weeks=1)
    with pytest.raises(ValueError):
        generate_week(athlete, macro, _iso_week(too_early), too_early)

    too_late = macro.blocks[-1].end_date + timedelta(days=1)
    with pytest.raises(ValueError):
        generate_week(athlete, macro, _iso_week(too_late), too_late)


def test_generate_week_handles_dict_and_string_pool_schedule_entries():
    athlete = make_athlete(pool_schedule=["mon", {"day": "wednesday"}, "friday"])
    event = make_event(event_date=START + timedelta(weeks=10))
    macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=14000, peak_weekly_volume_m=20000)
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)
    pool_sessions = [s for s in week.sessions if s.sport == "swim_pool" and s.source == "pool_coach"]
    assert {s.date.weekday() for s in pool_sessions} == {0, 2, 4}  # mon, wed, fri


# --- has_pool_coach: no-coach pool sessions get real structure -------------------


def test_generate_week_has_pool_coach_true_default_matches_pre_change_behavior(short_macro):
    # Regression guard: has_pool_coach left at its default (True, field
    # omitted at construction, same as every existing athlete) must produce
    # byte-for-byte (modulo random ids) the same pool-session output as
    # before this field existed -- content-less pool_coach placeholders.
    athlete, macro = short_macro
    assert athlete.has_pool_coach is True  # default, never set at construction
    week_start = macro.blocks[0].start_date
    week_default = generate_week(athlete, macro, _iso_week(week_start), week_start)

    athlete_explicit_true = athlete.model_copy(update={"has_pool_coach": True})
    week_explicit = generate_week(athlete_explicit_true, macro, _iso_week(week_start), week_start)

    def _shape(week):
        return [
            (
                s.sport,
                s.source,
                s.date,
                s.distance_m,
                s.duration_min,
                s.intensity,
                s.purpose,
                s.structure,
                s.status,
            )
            for s in week.sessions
        ]

    assert _shape(week_default) == _shape(week_explicit)

    pool_sessions = [s for s in week_default.sessions if s.sport == "swim_pool"]
    assert len(pool_sessions) == 3
    for s in pool_sessions:
        assert s.source == "pool_coach"
        assert s.structure is None
        assert s.intensity == {"anchor": "rpe"}
        assert "pool coach" in s.purpose
        assert s.distance_m == POOL_SESSION_EST_M
        assert s.duration_min == DEFAULT_POOL_SESSION_MIN


def test_generate_week_has_pool_coach_true_unaffected_across_whole_macro(short_macro):
    # Regression guard for the no-coach-pool-volume fix below: the
    # has_pool_coach=True branch (and its POOL_SESSION_EST_M /
    # DEFAULT_POOL_SESSION_MIN-based pool_total_m accounting) must stay
    # byte-for-byte identical to pre-fix `main` for every week across the
    # whole macro, not just one week -- this branch is not touched by the
    # fix at all.
    athlete, macro = short_macro
    for block in macro.blocks:
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(athlete, macro, _iso_week(week_start), week_start)
            pool_sessions = [s for s in week.sessions if s.sport == "swim_pool"]
            assert len(pool_sessions) == len(athlete.pool_schedule)
            for s in pool_sessions:
                assert s.source == "pool_coach"
                assert s.distance_m == POOL_SESSION_EST_M
                assert s.duration_min == DEFAULT_POOL_SESSION_MIN
                assert s.structure is None
                assert s.intensity == {"anchor": "rpe"}


def test_generate_week_no_pool_coach_produces_real_structure(short_macro):
    # Regression test for the reported bug: has_pool_coach=False pool-day
    # sessions must scale with target_volume_m (reserve LONG_SWIM_SHARE for
    # the long swim, split the rest across pool days), NOT reuse the
    # pool-coach placeholder's fixed POOL_SESSION_EST_M estimate.
    athlete, macro = short_macro
    athlete = athlete.model_copy(update={"has_pool_coach": False})
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    expected_per_day = max(
        NO_COACH_POOL_SESSION_FLOOR_M,
        _round_100(
            max(0.0, week.target_volume_m - week.target_volume_m * LONG_SWIM_SHARE)
            / len(athlete.pool_schedule)
        ),
    )
    pace_s = _z2_pace_s_per_100m(athlete)
    expected_duration = max(_duration_min_for_distance(expected_per_day, pace_s), 15.0)

    pool_sessions = [s for s in week.sessions if s.sport == "swim_pool"]
    assert len(pool_sessions) == 3
    assert {s.date.weekday() for s in pool_sessions} == {1, 3, 4}  # tue, thu, fri
    for s in pool_sessions:
        assert s.source == "ai_coach"
        assert s.status == "planned"
        assert s.distance_m == expected_per_day
        assert s.distance_m != POOL_SESSION_EST_M  # the bug being fixed
        assert s.duration_min == expected_duration
        assert s.structure is not None
        assert s.structure.strip() != ""
        assert "Warm-up" in s.structure
        assert "Main set" in s.structure
        assert "Cool-down" in s.structure
        # Regression guard: purpose must be the real, block-aware training
        # purpose (_no_coach_pool_purpose), not the old hardcoded dev-note
        # text ("pool practice -- no pool coach on hand, structure authored
        # below") that said nothing about the actual training purpose.
        assert s.purpose == _no_coach_pool_purpose(macro.blocks[0].name)
        assert "no pool coach on hand" not in s.purpose


def test_generate_week_no_pool_coach_leaves_strength_and_recovery_unaffected(short_macro):
    # Strength and recovery sessions (which never carry distance_m) are
    # identical regardless of has_pool_coach, and the week's target_volume_m
    # itself is unaffected either way. The long swim (swim_ow) is NOT
    # asserted identical here -- with the fix, pool_total_m now legitimately
    # differs between the two branches (has_pool_coach=False pool sessions
    # scale with target_volume_m instead of the fixed POOL_SESSION_EST_M
    # placeholder), which cascades into the remainder/long-swim
    # reconciliation. See test_generate_week_no_coach_total_volume_tracks_
    # target below for the property that actually matters post-fix.
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week_with_coach = generate_week(athlete, macro, _iso_week(week_start), week_start)
    week_without_coach = generate_week(
        athlete.model_copy(update={"has_pool_coach": False}), macro, _iso_week(week_start), week_start
    )

    def _shape(week, sport):
        return [
            (s.sport, s.date, s.distance_m, s.duration_min, s.purpose)
            for s in week.sessions
            if s.sport == sport
        ]

    assert _shape(week_with_coach, "strength") == _shape(week_without_coach, "strength")
    assert _shape(week_with_coach, "recovery") == _shape(week_without_coach, "recovery")
    assert week_with_coach.target_volume_m == week_without_coach.target_volume_m


def test_generate_week_no_pool_coach_fixes_reported_bug_small_target_volume():
    # The exact reported bug (found via the coach's own dogfooding feedback
    # log): an early-base/post-layoff-restart week with a small
    # target_volume_m (~1000-1300m in the real scenario) and 2
    # pool-schedule days used to size every pool session at the fixed
    # POOL_SESSION_EST_M (3500m) regardless of target_volume_m --
    # pool_total_m alone came out to 2 * 3500 = 7000m, ~6x the periodized
    # target, no matter how many times the week was regenerated. This
    # reproduces that shape (current_weekly_volume_m=0, a 10-week runway,
    # 2 pool days) and asserts the fix keeps total week volume tracking
    # target_volume_m instead of blowing past it by multiples.
    athlete = make_athlete(pool_schedule=["tue", "thu"], has_pool_coach=False)
    event = make_event(event_date=START + timedelta(weeks=12), distance_m=5000)
    with pytest.warns(UserWarning, match="clamped"):
        macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=0)
    base_block = next(b for b in macro.blocks if b.name == "base")
    week_start = base_block.start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    # this exact construction reproduces the real reported scenario's
    # target_volume_m precisely: 1213m
    assert week.target_volume_m == 1213

    pool_sessions = [s for s in week.sessions if s.sport == "swim_pool"]
    assert len(pool_sessions) == 2
    pool_total_m = sum(s.distance_m for s in pool_sessions)
    # before the fix this would be 2 * POOL_SESSION_EST_M == 7000m, ~6x the
    # target, regardless of target_volume_m
    assert pool_total_m < POOL_SESSION_EST_M  # nowhere near the old 7000m total
    for s in pool_sessions:
        assert 0 < s.distance_m < POOL_SESSION_EST_M

    total_swim = sum(
        s.distance_m or 0 for s in week.sessions if s.sport in ("swim_pool", "swim_ow")
    )
    # total swim volume tracks target_volume_m -- generous tolerance for
    # floors/rounding, but nowhere near the old ~6x overage
    assert total_swim <= week.target_volume_m * 1.5
    assert total_swim >= week.target_volume_m * 0.5


def test_generate_week_no_pool_coach_large_target_volume_not_needlessly_floored(short_macro):
    # A mid-build/peak-block week has plenty of volume budget -- per-day
    # pool distances should reflect that (not collapse to the floor just
    # because the floor exists).
    athlete, macro = short_macro
    athlete = athlete.model_copy(update={"has_pool_coach": False})
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    week_start = peak_block.start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    pool_sessions = [s for s in week.sessions if s.sport == "swim_pool"]
    assert len(pool_sessions) == 3
    for s in pool_sessions:
        assert s.distance_m > NO_COACH_POOL_SESSION_FLOOR_M * 2
        assert s.duration_min > 15.0


def test_generate_week_no_pool_coach_sessions_never_below_floor_or_nonpositive(short_macro):
    # Property test across the whole macro: no has_pool_coach=False pool
    # session should ever get a non-positive or sub-floor distance, even in
    # low-volume weeks (e.g. early base).
    athlete, macro = short_macro
    athlete = athlete.model_copy(update={"has_pool_coach": False})
    for block in macro.blocks:
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(athlete, macro, _iso_week(week_start), week_start)
            for s in week.sessions:
                if s.sport == "swim_pool":
                    assert s.distance_m >= NO_COACH_POOL_SESSION_FLOOR_M
                    assert s.distance_m > 0
                    assert s.duration_min > 0


def test_generate_week_no_pool_coach_floor_can_still_modestly_exceed_target_with_many_pool_days():
    # Known edge case (see NO_COACH_POOL_SESSION_FLOOR_M's comment in
    # plan.py): when a genuinely-early restart week's target_volume_m is
    # small enough that NO_COACH_POOL_SESSION_FLOOR_M * len(pool_schedule)
    # exceeds it, the floor pushes pool_total_m back above target_volume_m
    # -- a bounded, smaller-scale recurrence of the bug the floor-based fix
    # otherwise resolves. Reproduces the same restart shape as
    # test_generate_week_no_pool_coach_fixes_reported_bug_small_target_volume
    # (current_weekly_volume_m=0, target_volume_m ends up 1213m) but with 5
    # pool days -- within this project's documented 3-5 days/week pool
    # attendance (CLAUDE.md) -- instead of 2, which is enough to trigger the
    # floor for every pool day. This test pins the current, accepted,
    # bounded behavior so a future change can't silently make the overage
    # worse without a test failure calling it out.
    athlete = make_athlete(pool_schedule=["mon", "tue", "wed", "thu", "fri"], has_pool_coach=False)
    event = make_event(event_date=START + timedelta(weeks=12), distance_m=5000)
    with pytest.warns(UserWarning, match="clamped"):
        macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=0)
    base_block = next(b for b in macro.blocks if b.name == "base")
    week_start = base_block.start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    assert week.target_volume_m == 1213

    pool_sessions = [s for s in week.sessions if s.sport == "swim_pool"]
    assert len(pool_sessions) == 5
    for s in pool_sessions:
        # every session sits right at the floor -- the raw formula-derived
        # distance for this scenario is below it
        assert s.distance_m == NO_COACH_POOL_SESSION_FLOOR_M

    pool_total_m = sum(s.distance_m for s in pool_sessions)
    assert pool_total_m == 5 * NO_COACH_POOL_SESSION_FLOOR_M  # 1500m

    long_swims = [s for s in week.sessions if s.sport == "swim_ow"]
    assert len(long_swims) == 1
    # the remainder/long-swim reconciliation absorbs as much of the
    # floor-driven overage as it can, flooring the long swim at 0m --
    # confirms it's handled sanely (never negative) even though it can't
    # fully compensate
    assert long_swims[0].distance_m == 0

    total_swim = sum(s.distance_m or 0 for s in week.sessions if s.sport in ("swim_pool", "swim_ow"))
    # total swim volume modestly exceeds target_volume_m in this corner
    # case (bounded overage: floor * pool_days - target, not the old
    # unbounded POOL_SESSION_EST_M-scale overage) -- pin the exact bound so
    # this can't silently regress further
    assert total_swim == 1500
    assert total_swim > week.target_volume_m
    assert total_swim <= week.target_volume_m * 1.25


# --- event_format: multi_day_stage --------------------------------------------------


def test_generate_week_defaults_to_single_day_format(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week_default = generate_week(athlete, macro, _iso_week(week_start), week_start)
    week_explicit = generate_week(
        athlete, macro, _iso_week(week_start), week_start, event_format="single_day"
    )
    # Same sessions modulo random ids -- compare the shape, not identity.
    assert [(s.sport, s.date, s.distance_m) for s in week_default.sessions] == [
        (s.sport, s.date, s.distance_m) for s in week_explicit.sessions
    ]


def test_generate_week_rejects_unknown_event_format(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    with pytest.raises(ValueError):
        generate_week(
            athlete, macro, _iso_week(week_start), week_start, event_format="two_day_sprint"
        )


def test_generate_week_stage_format_splits_across_saturday_and_sunday(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, event_format="multi_day_stage"
    )

    long_swims = [s for s in week.sessions if s.sport == "swim_ow"]
    assert {s.date.weekday() for s in long_swims} == {5, 6}  # Saturday, Sunday
    saturday = next(s for s in long_swims if s.date.weekday() == 5)
    sunday = next(s for s in long_swims if s.date.weekday() == 6)
    # Saturday gets the larger (or equal) share of the two stage swims.
    assert saturday.distance_m >= sunday.distance_m
    for s in long_swims:
        assert s.intensity == {"zone": "Z2", "anchor": "css_pace"}


def test_generate_week_stage_format_has_no_sunday_recovery_session(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(
        athlete, macro, _iso_week(week_start), week_start, event_format="multi_day_stage"
    )
    recovery = [s for s in week.sessions if s.sport == "recovery"]
    assert recovery == []


def test_generate_week_stage_format_total_long_swim_volume_matches_single_day(short_macro):
    # Splitting across the weekend shouldn't change the total long-swim
    # volume vs. the single_day continuous-swim total for the same week.
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    single = generate_week(athlete, macro, _iso_week(week_start), week_start, event_format="single_day")
    stage = generate_week(athlete, macro, _iso_week(week_start), week_start, event_format="multi_day_stage")

    single_total = sum(s.distance_m for s in single.sessions if s.sport == "swim_ow")
    stage_total = sum(s.distance_m for s in stage.sessions if s.sport == "swim_ow")
    assert stage_total == pytest.approx(single_total, abs=100)


def test_generate_week_stage_format_still_validates_and_stays_in_tolerance(short_macro):
    athlete, macro = short_macro
    for block in macro.blocks:
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(
                athlete, macro, _iso_week(week_start), week_start, event_format="multi_day_stage"
            )
            total_swim = sum(
                s.distance_m or 0 for s in week.sessions if s.sport in ("swim_pool", "swim_ow")
            )
            if week.target_volume_m == 0:
                continue
            deviation = abs(total_swim - week.target_volume_m) / week.target_volume_m
            assert deviation <= 0.10


# --- round-trip through FileStore -------------------------------------------------


def test_generate_week_round_trips_through_file_store(tmp_path, short_macro):
    athlete, macro = short_macro
    store = FileStore(base_dir=tmp_path)
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    store.save_week("wife", week)
    loaded = store.load_week("wife", week.iso_week)
    assert loaded == week
    for session in loaded.sessions:
        assert session.athlete_id == athlete.id


# --- additional pool-independent swim session structure ---------------------------


def test_generate_week_additional_swim_session_has_real_structure(short_macro):
    # The "peak" block's first week for this fixture reliably produces a
    # remainder >= MIN_ADDITIONAL_SWIM_M (verified by direct simulation):
    # target 20000m - 3 pool sessions (10500m) - long swim (6600m) = 2900m.
    athlete, macro = short_macro
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    week_start = peak_block.start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    additional = [s for s in week.sessions if s.purpose == "additional pool-independent aerobic volume"]
    assert len(additional) == 1
    session = additional[0]
    assert session.distance_m >= 1000
    assert session.structure is not None
    assert session.structure.strip() != ""
    assert "Warm-up" in session.structure
    assert "Main set" in session.structure
    assert "Cool-down" in session.structure
    assert "/100m" in session.structure  # real pace numbers, not vague filler
    # a non-base block should use the broken-distance/negative-split format
    assert "broken-distance" in session.structure


def test_generate_week_additional_swim_structure_uses_continuous_format_in_base_block():
    # A single pool day/week leaves enough pool-independent volume that the
    # additional-swim remainder path triggers in every block, including
    # base -- reliably exercising the base-block continuous-format branch
    # (unlike short_macro's 3-day pool schedule, which never triggers it in
    # base at these volumes).
    athlete = make_athlete(pool_schedule=["tue"])
    event = make_event(event_date=START + timedelta(weeks=10))
    macro = scaffold_macro(athlete, event, START, current_weekly_volume_m=14000, peak_weekly_volume_m=20000)
    base_block = next(b for b in macro.blocks if b.name == "base")
    week_start = base_block.start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    additional = [s for s in week.sessions if s.purpose == "additional pool-independent aerobic volume"]
    assert len(additional) == 1
    assert "@ Z2" in additional[0].structure
    assert "broken-distance" not in additional[0].structure


def test_additional_swim_structure_handles_zero_distance():
    assert _additional_swim_structure("base", 0, 95.0) == "No additional pool-independent volume this week."


def test_additional_swim_structure_never_called_for_long_swim_sessions(short_macro):
    # Direct regression guard on the helper itself: generate_week must never
    # pass long-swim/stage-swim data through _additional_swim_structure --
    # enforced structurally above (test_generate_week_long_swim_structure_
    # unchanged_regression), this just confirms the function is usable
    # standalone and produces distinct output from a None/continuous design.
    athlete, macro = short_macro
    text = _additional_swim_structure("build", 2000, athlete.css_pace_s_per_100m)
    assert text != "No additional pool-independent volume this week."
    assert "Warm-up" in text and "Cool-down" in text


@pytest.mark.parametrize("macro_block_name", ["base", "build", "peak", "taper"])
@pytest.mark.parametrize("distance_m", list(range(1000, 4001, 100)))
def test_additional_swim_structure_sums_to_requested_distance(macro_block_name, distance_m):
    # Regression guard: warm-up + main set (reps x rep length) + cool-down
    # must sum exactly to distance_m -- a real rounding bug in an earlier
    # version of this function let the printed main-set rep count drift
    # from the warm-up/cool-down split, so the described session's total
    # could silently overshoot or undershoot the session's actual
    # distance_m by up to a full rep length (as much as 10% at the low end
    # of realistic "additional swim" distances).
    text = _additional_swim_structure(macro_block_name, distance_m, 95.0)
    warm_up = int(re.search(r"Warm-up: (\d+)m", text).group(1))
    cool_down = int(re.search(r"Cool-down: (\d+)m", text).group(1))
    main_set = re.search(r"Main set: (\d+) x (\d+)m", text)
    reps, rep_len = int(main_set.group(1)), int(main_set.group(2))
    assert warm_up + reps * rep_len + cool_down == distance_m


# --- real citations, not internal library/ paths, in athlete-facing text ------
# Regression coverage for the bug where _additional_swim_structure's Main-set
# line and _strength_session_structure's purpose ended with a citation to this
# project's own internal engine-config file (e.g.
# "library/14-swim-set-structure.md") instead of a real, verifiable source.
# The fix moves the real citation to a trailing "Why: ..." line and drops the
# internal path entirely.


def test_additional_swim_structure_why_line_base_block():
    text = _additional_swim_structure("base", 2000, 95.0)
    assert text.splitlines()[-1] == "Why: continuous aerobic-volume emphasis (base-block phase)."
    assert "library/" not in text


@pytest.mark.parametrize("macro_block_name", ["build", "peak", "taper"])
def test_additional_swim_structure_why_line_non_base_blocks(macro_block_name):
    text = _additional_swim_structure(macro_block_name, 2000, 95.0)
    assert text.splitlines()[-1] == (
        "Why: race-pace-adjacent, broken-distance emphasis -- evidence-based "
        "phase shift (González-Ravé et al. 2021; Pla et al. 2019)."
    )
    assert "library/" not in text


def test_additional_swim_structure_main_set_line_has_no_internal_citation():
    # The specific bug: the Main-set line itself used to end with
    # "; library/14-swim-set-structure.md" (base) or
    # "library/14-swim-set-structure.md, cross-referencing
    # 04-css-intensity-anchors.md's negative-split evidence" (build/peak/
    # taper) -- a citation to this project's own internal file, not a real
    # source. The real citation now lives only in the trailing Why: line.
    base_text = _additional_swim_structure("base", 2000, 95.0)
    main_set_line = next(line for line in base_text.splitlines() if line.startswith("Main set:"))
    assert "library/" not in main_set_line
    assert main_set_line.endswith("(base-block emphasis).")

    build_text = _additional_swim_structure("build", 2000, 95.0)
    main_set_line = next(line for line in build_text.splitlines() if line.startswith("Main set:"))
    assert "library/" not in main_set_line
    assert main_set_line.endswith("(build block).")


# --- expanded main-set template menu + deterministic rotation ----------------
# _additional_swim_structure's new `selector` parameter picks a template via
# `selector % <template count>` (2 templates for base, 4 for build/peak/
# taper) -- see its docstring. All new templates are Coach judgment drawn
# from library/14-swim-set-structure.md's open "Main-set format menu", same
# citation footing as the two pre-existing templates covered above.


def test_additional_swim_structure_base_block_broken_distance_lite_template():
    # distance_m=2000, css_pace_s=95.0 -> warm_up=400, cool_down_budget=200,
    # main_set_budget=1400 -> rep=300 (>=1200), reps=round(1400/300)=5,
    # remaining_for_cool_down=100 (no giveback triggered) -> cool_down=100.
    distance_m, css_pace_s = 2000, 95.0
    text = _additional_swim_structure("base", distance_m, css_pace_s, selector=1)
    z2 = zone_table(css_pace_s)["Z2"]
    z2_range = f"{_format_pace_s(z2['pace_lo_s'])}-{_format_pace_s(z2['pace_hi_s'])}/100m"
    lines = text.splitlines()
    assert lines[0] == f"Warm-up: 400m easy, building to Z2 pace ({z2_range}) by the end."
    assert lines[1] == (
        f"Main set: 5 x (150m + 150m) @ Z2 ({z2_range}), 10s rest between segments / "
        "15s between reps -- broken-distance-lite aerobic volume, same total distance "
        "and pace as straight reps (base-block emphasis)."
    )
    assert lines[2] == "Cool-down: 100m easy choice of stroke."
    assert lines[3] == "Why: continuous aerobic-volume emphasis (base-block phase)."
    assert "Z3" not in text and "Z4" not in text
    assert "library/" not in text


def test_additional_swim_structure_build_block_pyramid_template():
    # Same distance/pace as above but non-base branch: rep=200 (main_set_
    # budget 1400 >= 800), reps=round(1400/200)=7, cool_down=200. mid =
    # 7 // 2 + 1 = 4.
    distance_m, css_pace_s = 2000, 95.0
    text = _additional_swim_structure("build", distance_m, css_pace_s, selector=1)
    z3 = zone_table(css_pace_s)["Z3"]
    z4 = zone_table(css_pace_s)["Z4"]
    z3_range = f"{_format_pace_s(z3['pace_lo_s'])}-{_format_pace_s(z3['pace_hi_s'])}/100m"
    z4_range = f"{_format_pace_s(z4['pace_lo_s'])}-{_format_pace_s(z4['pace_hi_s'])}/100m"
    lines = text.splitlines()
    assert lines[1] == (
        f"Main set: 7 x 200m broken-distance pyramid, effort ramps from Z3 ({z3_range}) "
        f"up to Z4 ({z4_range}) at rep 4 of 7 and back down to Z3 by the final rep, "
        "each repeat negative-split -- race-pace-adjacent emphasis (build block)."
    )
    assert lines[-1] == (
        "Why: race-pace-adjacent, broken-distance emphasis -- evidence-based "
        "phase shift (González-Ravé et al. 2021; Pla et al. 2019)."
    )
    assert "library/" not in text


def test_additional_swim_structure_build_block_ladder_template():
    # Same reps/rep as the pyramid test (7 x 200m): ladder pairs 7 into
    # num_pairs=3, leftover=1; rep_short=100, rep_long=300.
    distance_m, css_pace_s = 2000, 95.0
    text = _additional_swim_structure("build", distance_m, css_pace_s, selector=2)
    z3 = zone_table(css_pace_s)["Z3"]
    z4 = zone_table(css_pace_s)["Z4"]
    z3_range = f"{_format_pace_s(z3['pace_lo_s'])}-{_format_pace_s(z3['pace_hi_s'])}/100m"
    z4_range = f"{_format_pace_s(z4['pace_lo_s'])}-{_format_pace_s(z4['pace_hi_s'])}/100m"
    lines = text.splitlines()
    assert lines[1] == (
        "Main set: 3 x (100m + 300m) climbing pairs, plus 1 x 200m capstone rep to "
        "finish, broken-distance ladder, each pair negative-split from Z3 "
        f"({z3_range}) toward Z4 ({z4_range}) -- race-pace-adjacent emphasis (build block)."
    )
    assert "library/" not in text


def test_additional_swim_structure_build_block_straight_negative_split_template():
    distance_m, css_pace_s = 2000, 95.0
    text = _additional_swim_structure("build", distance_m, css_pace_s, selector=3)
    z3 = zone_table(css_pace_s)["Z3"]
    z4 = zone_table(css_pace_s)["Z4"]
    z3_range = f"{_format_pace_s(z3['pace_lo_s'])}-{_format_pace_s(z3['pace_hi_s'])}/100m"
    z4_range = f"{_format_pace_s(z4['pace_lo_s'])}-{_format_pace_s(z4['pace_hi_s'])}/100m"
    lines = text.splitlines()
    assert lines[1] == (
        f"Main set: 7 x 200m @ Z3 ({z3_range}), each rep negative-split building to "
        f"Z4 ({z4_range}) by the finish, no descend-across-reps progression, 10s rest "
        "-- race-pace-adjacent emphasis (build block)."
    )
    assert "library/" not in text


@pytest.mark.parametrize(
    "distance_m,css_pace_s,expected_reps", [(300, 95.0, 1), (540, 120.0, 2)]
)
def test_additional_swim_structure_pyramid_degenerate_low_reps_no_self_contradiction(
    distance_m, css_pace_s, expected_reps
):
    # Independent-review regression: no_coach_pool_distance_m's floor
    # (NO_COACH_POOL_SESSION_FLOOR_M=300, see generate_week) is a real
    # production path that can hand _additional_swim_structure a small
    # enough distance_m to yield reps in {1, 2} for build/peak/taper
    # blocks. The general pyramid formula `mid = reps // 2 + 1` makes the
    # peak land ON the final rep whenever reps<=2, so the generic template
    # text ("ramps ... at rep N of N and back down to Z3 by the final
    # rep") was self-contradictory -- the final rep can't be both the peak
    # AND the down-ramp. Confirm the degenerate branch (reps<=2) avoids
    # that phrasing and still reports the expected rep count.
    text = _additional_swim_structure("build", distance_m, css_pace_s, selector=1)
    main_set_line = next(line for line in text.splitlines() if line.startswith("Main set:"))
    m = re.search(r"Main set: (\d+) x (\d+)m", main_set_line)
    assert int(m.group(1)) == expected_reps
    assert "and back down" not in main_set_line
    assert "at rep" not in main_set_line
    assert "library/" not in text


def test_additional_swim_structure_ladder_title_is_informative_via_ui_cut_rule():
    # Independent-review regression: web/src/plan.js's deriveSessionTitle
    # derives each session's compact title by cutting the "Main set: ..."
    # line at whichever comes first, its first comma or its first " -- ".
    # The ladder template originally led with "broken-distance ladder -- ",
    # so the cut landed immediately after "ladder" and every ladder week
    # showed the same generic "Broken-distance ladder" title with no
    # reps/distance numbers to distinguish one week's plan from another's
    # -- unlike the other three templates, whose numeric detail always
    # precedes their first comma/dash. Confirm the numeric detail now
    # survives the same cut rule the UI actually applies.
    text = _additional_swim_structure("build", 2000, 95.0, selector=2)
    main_set_line = next(line for line in text.splitlines() if line.startswith("Main set:"))
    content = main_set_line[len("Main set: ") :]
    comma_idx = content.find(",")
    dash_idx = content.find(" -- ")
    candidates = [i for i in (comma_idx, dash_idx) if i != -1]
    cut = content[: min(candidates)] if candidates else content
    assert re.search(r"\d", cut), f"derived title has no numeric detail: {cut!r}"


@pytest.mark.parametrize("macro_block_name", ["build", "peak", "taper"])
def test_additional_swim_structure_pyramid_template_names_correct_block(macro_block_name):
    text = _additional_swim_structure(macro_block_name, 2000, 95.0, selector=1)
    main_set_line = next(line for line in text.splitlines() if line.startswith("Main set:"))
    assert main_set_line.endswith(f"({macro_block_name} block).")


def test_additional_swim_structure_rotation_is_deterministic():
    # The core safety property: same (block, selector) -> byte-identical
    # output, every time, forever -- no random/global state involved.
    text_a = _additional_swim_structure("build", 3400, 92.0, selector=5)
    text_b = _additional_swim_structure("build", 3400, 92.0, selector=5)
    assert text_a == text_b

    text_a_base = _additional_swim_structure("base", 1800, 88.0, selector=3)
    text_b_base = _additional_swim_structure("base", 1800, 88.0, selector=3)
    assert text_a_base == text_b_base


def test_additional_swim_structure_rotation_wraps_with_modulo():
    # Template-menu sizes now live in engine/swim_coach/workout_templates/
    # *.yaml (16 build/peak/taper templates, 2 base templates, as of the
    # PR #87 researched-workout ETL + descending_ladder strategy addition)
    # rather than a plan.py constant -- see tests/unit/test_workout_
    # templates.py for the loader-level guarantees.
    assert _additional_swim_structure("build", 2000, 95.0, selector=0) == _additional_swim_structure(
        "build", 2000, 95.0, selector=16
    )
    assert _additional_swim_structure("build", 2000, 95.0, selector=1) == _additional_swim_structure(
        "build", 2000, 95.0, selector=17
    )
    assert _additional_swim_structure("base", 2000, 95.0, selector=0) == _additional_swim_structure(
        "base", 2000, 95.0, selector=2
    )


def test_additional_swim_structure_build_block_rotation_selects_multiple_templates():
    # Regression guard against a rotation rule that accidentally always
    # resolves to index 0 -- simulates 4 consecutive weeks' selector values.
    texts = [_additional_swim_structure("build", 2000, 95.0, selector=s) for s in range(4)]
    assert len(set(texts)) == 4
    assert "descend 1-" in texts[0]
    assert "pyramid" in texts[1]
    assert "broken-distance ladder" in texts[2]
    assert "no descend-across-reps" in texts[3]


def test_additional_swim_structure_base_block_rotation_selects_multiple_templates():
    texts = [_additional_swim_structure("base", 2000, 95.0, selector=s) for s in range(2)]
    assert len(set(texts)) == 2
    assert "continuous aerobic volume (base-block emphasis)." in texts[0]
    assert "broken-distance-lite" in texts[1]


@pytest.mark.parametrize("selector", [0, 1])
def test_additional_swim_structure_base_templates_stay_aerobic_no_z3_z4(selector):
    # Direct string assertion (not just eyeballing): base-block output must
    # never contain Z3/Z4 race-pace language, regardless of which template
    # in the rotation is selected -- the base->build periodization
    # principle (library/03-periodization.md, library/14-swim-set-
    # structure.md) forbids race-pace-adjacent work in the base block.
    text = _additional_swim_structure("base", 2000, 95.0, selector=selector)
    assert "Z3" not in text
    assert "Z4" not in text
    assert "Z2" in text


@pytest.mark.parametrize("selector", [0, 1])
def test_additional_swim_structure_base_templates_no_internal_citation(selector):
    text = _additional_swim_structure("base", 2000, 95.0, selector=selector)
    assert "library/" not in text


@pytest.mark.parametrize("selector", [0, 1, 2, 3])
def test_additional_swim_structure_build_templates_no_internal_citation(selector):
    text = _additional_swim_structure("build", 2000, 95.0, selector=selector)
    assert "library/" not in text


@pytest.mark.parametrize("distance_m", [1200, 1900, 2500, 3300, 4000])
def test_additional_swim_structure_base_split_template_sums_to_requested_distance(distance_m):
    text = _additional_swim_structure("base", distance_m, 95.0, selector=1)
    warm_up = int(re.search(r"Warm-up: (\d+)m", text).group(1))
    cool_down = int(re.search(r"Cool-down: (\d+)m", text).group(1))
    split = re.search(r"Main set: (\d+) x \((\d+)m \+ (\d+)m\)", text)
    reps, seg_a, seg_b = int(split.group(1)), int(split.group(2)), int(split.group(3))
    assert warm_up + reps * (seg_a + seg_b) + cool_down == distance_m


@pytest.mark.parametrize("macro_block_name", ["build", "peak", "taper"])
@pytest.mark.parametrize("distance_m", [1200, 1900, 2500, 3300, 4000])
@pytest.mark.parametrize("selector", [1, 3])  # pyramid, straight negative-split
def test_additional_swim_structure_pyramid_and_negsplit_sum_to_requested_distance(
    macro_block_name, distance_m, selector
):
    text = _additional_swim_structure(macro_block_name, distance_m, 95.0, selector=selector)
    warm_up = int(re.search(r"Warm-up: (\d+)m", text).group(1))
    cool_down = int(re.search(r"Cool-down: (\d+)m", text).group(1))
    main_set = re.search(r"Main set: (\d+) x (\d+)m", text)
    reps, rep_len = int(main_set.group(1)), int(main_set.group(2))
    assert warm_up + reps * rep_len + cool_down == distance_m


@pytest.mark.parametrize("macro_block_name", ["build", "peak", "taper"])
@pytest.mark.parametrize("distance_m", [1200, 1900, 2500, 3300, 4000])
def test_additional_swim_structure_ladder_sums_to_requested_distance(macro_block_name, distance_m):
    # The ladder's exact-sum guarantee is by construction (see comment in
    # plan.py): num_pairs*(rep_short+rep_long) + leftover*rep == reps*rep.
    text = _additional_swim_structure(macro_block_name, distance_m, 95.0, selector=2)
    warm_up = int(re.search(r"Warm-up: (\d+)m", text).group(1))
    cool_down = int(re.search(r"Cool-down: (\d+)m", text).group(1))
    ladder = re.search(
        r"Main set: (\d+) x \((\d+)m \+ (\d+)m\) climbing pairs"
        r"(, plus 1 x (\d+)m capstone rep to finish)?, broken-distance ladder",
        text,
    )
    num_pairs, rep_short, rep_long = int(ladder.group(1)), int(ladder.group(2)), int(ladder.group(3))
    capstone = int(ladder.group(5)) if ladder.group(4) else 0
    main_set_total = num_pairs * (rep_short + rep_long) + capstone
    assert warm_up + main_set_total + cool_down == distance_m


def test_generate_week_additional_swim_structure_rotates_across_weeks():
    # Regression guard on the actual call-site wiring: generate_week must
    # thread a real, changing selector (week_index_in_block) into
    # _additional_swim_structure so consecutive weeks in the SAME macro
    # block don't render an identical main-set template -- this is the
    # actual fix for the "every week looks the same" monotony complaint.
    athlete = make_athlete(pool_schedule=["tue"])
    event = make_event(event_date=START + timedelta(weeks=10))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=14000, peak_weekly_volume_m=20000
    )
    base_block = next(b for b in macro.blocks if b.name == "base")
    weeks_in_block = (base_block.end_date - base_block.start_date).days // 7 + 1
    assert weeks_in_block >= 2  # sanity: fixture must actually span >1 week

    structures = []
    for i in range(weeks_in_block):
        week_start = base_block.start_date + timedelta(weeks=i)
        week = generate_week(athlete, macro, _iso_week(week_start), week_start)
        additional = [
            s for s in week.sessions if s.purpose == "additional pool-independent aerobic volume"
        ]
        assert len(additional) == 1
        structures.append(additional[0].structure)

    assert len(set(structures)) > 1


def test_generate_week_additional_swim_structure_is_reproducible_for_same_week():
    athlete = make_athlete(pool_schedule=["tue"])
    event = make_event(event_date=START + timedelta(weeks=10))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=14000, peak_weekly_volume_m=20000
    )
    base_block = next(b for b in macro.blocks if b.name == "base")
    week_start = base_block.start_date

    week_a = generate_week(athlete, macro, _iso_week(week_start), week_start)
    week_b = generate_week(athlete, macro, _iso_week(week_start), week_start)
    structure_a = next(
        s.structure for s in week_a.sessions if s.purpose == "additional pool-independent aerobic volume"
    )
    structure_b = next(
        s.structure for s in week_b.sessions if s.purpose == "additional pool-independent aerobic volume"
    )
    assert structure_a == structure_b


@pytest.mark.parametrize("session_index", [0, 1])
def test_strength_session_structure_why_line_cites_real_sources(session_index):
    text = _strength_session_structure(session_index)
    assert text.splitlines()[-1] == (
        "Why: rotator-cuff strength/balance, reduces shoulder-injury risk "
        "(Hibberd 2012; Manske 2015; Tavares et al. 2025)."
    )
    assert "library/" not in text


def test_no_coach_pool_purpose_base_block():
    assert _no_coach_pool_purpose("base") == "Continuous aerobic volume — base-block emphasis"


@pytest.mark.parametrize("block_name", ["build", "peak", "taper"])
def test_no_coach_pool_purpose_non_base_blocks(block_name):
    assert _no_coach_pool_purpose(block_name) == f"Race-pace-adjacent volume — {block_name}-block emphasis"


def test_strength_session_purpose_has_no_internal_citation(short_macro):
    # The specific bug: generate_week's strength-session purpose ended with
    # "(library/07-strength-dryland.md)" -- an internal-path-as-citation,
    # same class of bug as the Main-set line above. The real citations now
    # live only in _strength_session_structure's own Why: line.
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)
    strength = [s for s in week.sessions if s.sport == "strength"]
    assert len(strength) == STRENGTH_SESSIONS_PER_WEEK
    for s in strength:
        assert "library/" not in s.purpose
        assert "dryland shoulder strength" in s.purpose


def test_generate_week_never_leaks_internal_library_paths_into_athlete_facing_text(short_macro):
    # Cheap, direct insurance against this exact class of bug recurring:
    # no generated purpose/structure text anywhere should contain the
    # substring "library/" -- that's always an internal engine-config file
    # path, never a real, athlete-facing citation.
    athlete, macro = short_macro
    for has_pool_coach in (True, False):
        athlete_variant = athlete.model_copy(update={"has_pool_coach": has_pool_coach})
        for block in macro.blocks:
            weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
            for i in range(weeks_in_block):
                week_start = block.start_date + timedelta(weeks=i)
                week = generate_week(athlete_variant, macro, _iso_week(week_start), week_start)
                for s in week.sessions:
                    assert "library/" not in (s.purpose or "")
                    assert "library/" not in (s.structure or "")


# --- WorkoutStructure migration: byte-identical parity proofs ------------------
# The whole point of building WorkoutStructure alongside the legacy prose is
# that it's provably NOT a behavior change: render_prose(resolve_template(
# <template>, athlete)) must equal today's real _additional_swim_structure /
# _strength_session_structure prose output EXACTLY, for every real template +
# selector -- same regression-proof discipline as PR #86's migration.

_PARITY_BLOCKS = ("base", "build", "peak", "taper")
_PARITY_DISTANCES_M = (1000, 1500, 2000, 3000, 4000)
_PARITY_CSS_PACES_S = (80.0, 95.0, 110.0)


def _candidate_count_for_block(macro_block_name: str) -> int:
    from swim_coach.workout_templates import TEMPLATES_DIR, load_workout_templates

    templates = load_workout_templates(TEMPLATES_DIR)
    return len([t for t in templates if macro_block_name in t.applicable_blocks])


@pytest.mark.parametrize("css_pace_s", _PARITY_CSS_PACES_S)
@pytest.mark.parametrize("distance_m", _PARITY_DISTANCES_M)
@pytest.mark.parametrize("macro_block_name", _PARITY_BLOCKS)
def test_additional_swim_structure_template_parity_for_every_selector(
    macro_block_name, distance_m, css_pace_s
):
    athlete = make_athlete(css_pace_s_per_100m=css_pace_s)
    for selector in range(_candidate_count_for_block(macro_block_name)):
        expected = _additional_swim_structure(macro_block_name, distance_m, css_pace_s, selector)
        template = _additional_swim_structure_template(macro_block_name, distance_m, css_pace_s, selector)
        resolved = resolve_template(template, athlete)
        got = render_prose(resolved)
        assert got == expected


def test_additional_swim_structure_template_parity_zero_distance_has_no_template():
    # distance_m <= 0 has no meaningful WorkoutStructure -- callers (i.e.
    # generate_week) must guard this themselves, mirroring
    # _additional_swim_structure's own early return.
    assert _additional_swim_structure("base", 0, 95.0) == "No additional pool-independent volume this week."


@pytest.mark.parametrize("session_index", [0, 1, 2, 3])
def test_strength_session_structure_template_parity(session_index):
    athlete = make_athlete()
    expected = _strength_session_structure(session_index)
    template = _strength_session_structure_template(session_index)
    resolved = resolve_template(template, athlete)
    got = render_prose(resolved)
    assert got == expected


def test_strength_session_structure_template_uses_a_real_workout_repeat():
    # The one production use of a genuine WorkoutRepeat this pass ships --
    # the "2 sets x 10 reps each" rotator-cuff/scapular-stability core.
    template = _strength_session_structure_template(0)
    repeats = [item for item in template.items if isinstance(item, WorkoutRepeat)]
    assert len(repeats) == 1
    core_repeat = repeats[0]
    assert core_repeat.repeat_mode == "count"
    assert core_repeat.count == 2
    assert len(core_repeat.steps) == len(STRENGTH_CORE_EXERCISES)
    for step in core_repeat.steps:
        assert isinstance(step, WorkoutStep)
        assert step.load.basis == "bodyweight"
        assert step.exercise_name in STRENGTH_CORE_EXERCISES


# --- STRENGTH_EXERCISE_REFERENCE_URLS ----------------------------------------


def test_strength_exercise_reference_urls_covers_every_canned_exercise():
    # Guard test: every canned strength exercise (core + full-body) must
    # have a dict entry -- catches a future exercise added to either tuple
    # without a matching technique link.
    covered = set(STRENGTH_EXERCISE_REFERENCE_URLS)
    for exercise in STRENGTH_CORE_EXERCISES:
        assert exercise in covered, f"missing reference URL for {exercise!r}"
    for exercise in STRENGTH_FULL_BODY_ADDITION:
        assert exercise in covered, f"missing reference URL for {exercise!r}"


@pytest.mark.parametrize("session_index", [0, 1])
def test_strength_session_structure_template_canned_steps_carry_reference_urls(session_index):
    template = _strength_session_structure_template(session_index)

    def walk(items):
        for item in items:
            if isinstance(item, WorkoutRepeat):
                yield from walk(item.steps)
            else:
                yield item

    steps = list(walk(template.items))
    exercise_steps = [s for s in steps if s.exercise_name is not None]
    assert len(exercise_steps) > 0
    for step in exercise_steps:
        assert step.reference_url == STRENGTH_EXERCISE_REFERENCE_URLS[step.exercise_name]
        assert step.reference_url is not None

    # role="open" section-header/Why: steps carry no exercise_name and no
    # reference_url.
    open_steps = [s for s in steps if s.role == "open"]
    assert len(open_steps) > 0
    for step in open_steps:
        assert step.exercise_name is None
        assert step.reference_url is None


def test_strength_exercise_reference_urls_get_is_none_for_unknown_exercise():
    # .get(), never [] -- a miss must be None, never a KeyError.
    assert STRENGTH_EXERCISE_REFERENCE_URLS.get("not a real exercise") is None


# --- Session.structured populated correctly by generate_week ------------------


def test_generate_week_populates_structured_for_strength_sessions_across_all_blocks(short_macro):
    athlete, macro = short_macro
    for block in macro.blocks:
        week_start = block.start_date
        week = generate_week(athlete, macro, _iso_week(week_start), week_start)
        strength = [s for s in week.sessions if s.sport == "strength"]
        assert len(strength) == STRENGTH_SESSIONS_PER_WEEK
        for session_index, s in enumerate(strength):
            assert s.structured is not None
            assert render_prose(s.structured) == s.structure
            assert render_prose(s.structured) == _strength_session_structure(session_index)


def test_generate_week_populates_structured_for_no_coach_pool_sessions_across_all_blocks(short_macro):
    athlete, macro = short_macro
    athlete = athlete.model_copy(update={"has_pool_coach": False})
    for block in macro.blocks:
        week_start = block.start_date
        week = generate_week(athlete, macro, _iso_week(week_start), week_start)
        pool_sessions = [s for s in week.sessions if s.sport == "swim_pool"]
        assert len(pool_sessions) == len(athlete.pool_schedule)
        for s in pool_sessions:
            assert s.structured is not None
            assert render_prose(s.structured) == s.structure
            # real, athlete-CSS-resolved pace numbers -- not a bare zone name.
            warmup = s.structured.items[0]
            assert warmup.role == "warmup"
            assert warmup.target.basis == "absolute"
            z2 = zone_table(athlete.css_pace_s_per_100m)["Z2"]
            assert warmup.target.low == z2["pace_lo_s"]
            assert warmup.target.high == z2["pace_hi_s"]


def test_generate_week_populates_structured_for_additional_swim_session(short_macro):
    athlete, macro = short_macro
    for block in macro.blocks:
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(athlete, macro, _iso_week(week_start), week_start)
            additional = [
                s
                for s in week.sessions
                if s.sport == "swim_ow" and s.purpose == "additional pool-independent aerobic volume"
            ]
            for s in additional:
                assert s.structured is not None
                assert render_prose(s.structured) == s.structure


def test_generate_week_pool_coach_placeholder_and_long_swim_have_no_structured(short_macro):
    # No real content is authored for these sessions today (structure=None)
    # -- structured stays None too, consistent with there being nothing to
    # structure.
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)
    placeholders = [s for s in week.sessions if s.source == "pool_coach"]
    assert placeholders
    for s in placeholders:
        assert s.structured is None
    long_swims = [s for s in week.sessions if s.sport == "swim_ow" and "long open-water" in s.purpose]
    assert long_swims
    for s in long_swims:
        assert s.structured is None
    recovery = [s for s in week.sessions if s.sport == "recovery"]
    assert recovery
    for s in recovery:
        assert s.structured is None


# --- adjust_session ----------------------------------------------------------


def _pool_coach_placeholder_session(short_macro) -> "Session":
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)
    return next(s for s in week.sessions if s.source == "pool_coach")


def _additional_swim_session(short_macro):
    athlete, macro = short_macro
    for block in macro.blocks:
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(athlete, macro, _iso_week(week_start), week_start)
            for s in week.sessions:
                if s.sport == "swim_ow" and s.purpose == "additional pool-independent aerobic volume":
                    return athlete, s
    raise AssertionError("short_macro produced no 'additional' swim_ow session")


def _strength_session(short_macro):
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)
    return athlete, next(s for s in week.sessions if s.sport == "strength")


def test_adjust_session_reduce_with_no_structured_scales_distance_and_duration(short_macro):
    session = _pool_coach_placeholder_session(short_macro)
    old_distance, old_duration = session.distance_m, session.duration_min

    applied = adjust_session(session, direction="reduce", magnitude_pct=20.0)

    assert applied == 20.0
    assert session.distance_m < old_distance
    assert session.duration_min < old_duration
    assert session.structured is None


def test_adjust_session_increase_with_no_structured_scales_distance_and_duration(short_macro):
    session = _pool_coach_placeholder_session(short_macro)
    old_distance, old_duration = session.distance_m, session.duration_min

    applied = adjust_session(session, direction="increase", magnitude_pct=10.0)

    assert applied == 10.0
    assert session.distance_m > old_distance
    assert session.duration_min > old_duration


def test_adjust_session_increase_is_clamped_to_the_safety_cap(short_macro):
    session = _pool_coach_placeholder_session(short_macro)
    old_distance = session.distance_m

    applied = adjust_session(session, direction="increase", magnitude_pct=200.0)

    assert applied == SESSION_ADJUSTMENT_INCREASE_CAP_PCT
    # scaled by the CAPPED factor, not the requested 200%
    assert session.distance_m == pytest.approx(
        old_distance * (1 + SESSION_ADJUSTMENT_INCREASE_CAP_PCT / 100), rel=0.05
    )


def test_adjust_session_reduce_is_clamped_below_total_zero(short_macro):
    session = _pool_coach_placeholder_session(short_macro)

    applied = adjust_session(session, direction="reduce", magnitude_pct=500.0)

    assert applied == 90.0
    assert session.distance_m > 0
    assert session.duration_min > 0


def test_adjust_session_reduce_interval_focus_shrinks_main_set_preserves_warmup_cooldown(short_macro):
    athlete, session = _additional_swim_session(short_macro)
    original = session.model_copy(deep=True)
    old_items = {id(item): item for item in original.structured.items}
    warmup_before = next(i for i in original.structured.items if i.role == "warmup")
    cooldown_before = next(i for i in original.structured.items if i.role == "cooldown")
    interval_before = next(i for i in original.structured.items if i.role == "interval")

    adjust_session(
        session, direction="reduce", magnitude_pct=30.0, focus="interval", css_pace_s=athlete.css_pace_s_per_100m
    )

    warmup_after = next(i for i in session.structured.items if i.role == "warmup")
    cooldown_after = next(i for i in session.structured.items if i.role == "cooldown")
    interval_after = next(i for i in session.structured.items if i.role == "interval")

    assert warmup_after.duration_value == warmup_before.duration_value
    assert cooldown_after.duration_value == cooldown_before.duration_value
    assert interval_after.duration_value < interval_before.duration_value
    assert session.distance_m < original.distance_m


def test_adjust_session_recomputes_distance_m_from_scaled_structured_tree(short_macro):
    athlete, session = _additional_swim_session(short_macro)

    adjust_session(
        session, direction="reduce", magnitude_pct=25.0, focus="overall", css_pace_s=athlete.css_pace_s_per_100m
    )

    total = sum(
        item.duration_value
        for item in session.structured.items
        if item.duration_kind == "distance_m" and item.duration_value
    )
    assert session.distance_m == round(total)


def test_adjust_session_strength_repeat_count_scales_down(short_macro):
    athlete, session = _strength_session(short_macro)
    core_repeat_before = next(i for i in session.structured.items if i.kind == "repeat")
    assert core_repeat_before.count == 2
    steps_before = count_structured_steps(session.structured)

    adjust_session(session, direction="reduce", magnitude_pct=50.0, focus="overall")

    core_repeat_after = next(i for i in session.structured.items if i.kind == "repeat")
    assert core_repeat_after.count == 1
    assert count_structured_steps(session.structured) < steps_before


def test_adjust_session_interval_focus_falls_back_to_overall_when_no_interval_role(short_macro):
    # A strength session has no role="interval" content at all -- focus=
    # "interval" must still scale something (the role="steady" core work)
    # rather than silently leaving the session untouched.
    athlete, session = _strength_session(short_macro)
    core_repeat_before = next(i for i in session.structured.items if i.kind == "repeat")
    assert core_repeat_before.count == 2

    adjust_session(session, direction="reduce", magnitude_pct=50.0, focus="interval")

    core_repeat_after = next(i for i in session.structured.items if i.kind == "repeat")
    assert core_repeat_after.count == 1


def test_adjust_session_strength_with_no_distance_kind_content_scales_duration_only(short_macro):
    athlete, session = _strength_session(short_macro)
    assert session.distance_m is None
    old_duration = session.duration_min

    adjust_session(session, direction="reduce", magnitude_pct=20.0, focus="overall")

    assert session.distance_m is None
    assert session.duration_min < old_duration


def test_count_structured_steps_is_none_without_structured():
    assert count_structured_steps(None) is None


def test_count_structured_steps_counts_repeat_iterations(short_macro):
    athlete, session = _strength_session(short_macro)
    # STRENGTH_CORE_EXERCISES steps, each performed `count` (2) times, plus
    # whatever standalone open/full-body steps this session_index carries.
    repeat = next(i for i in session.structured.items if i.kind == "repeat")
    expected_repeat_contribution = repeat.count * len(repeat.steps)
    standalone = sum(1 for i in session.structured.items if i.kind == "step")
    assert count_structured_steps(session.structured) == expected_repeat_contribution + standalone


# --- race week: final-taper-week content --------------------------------------
# `event_date` below is deliberately a FRIDAY (event_monday + 4 days), not a
# Monday -- mirrors Renee's real UltraSwim 33.3 date (2026-09-18, a Friday)
# and is exactly the case that makes the carb-load window land in the
# following (not-yet-generated) event week while the bodywork window still
# lands inside the final taper week's own last day -- see
# `RaceWeekChecklistItem`'s docstring and `_race_week_checklist`'s.


@pytest.fixture
def race_week_macro():
    """A short (10-week) runway -- taper=2 weeks -- ending the Sunday before
    a Friday event, so `taper_block`'s 2nd (final) week is the one under
    test; its 1st week is the "ordinary taper week" negative control."""
    athlete = make_athlete()
    event_monday = START + timedelta(weeks=10)
    event = make_event(event_date=event_monday + timedelta(days=4))  # Friday
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=14000, peak_weekly_volume_m=20000
    )
    taper_block = next(b for b in macro.blocks if b.name == "taper")
    assert (taper_block.end_date - taper_block.start_date).days // 7 + 1 == 2
    final_week_start = taper_block.start_date + timedelta(weeks=1)
    assert final_week_start + timedelta(days=6) == event_monday - timedelta(days=1)
    return athlete, event, macro, taper_block, final_week_start


def test_race_week_checklist_populated_on_final_taper_week_for_active_a_event(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=event
    )

    assert len(week.race_week_checklist) > 0
    categories = {item.category for item in week.race_week_checklist}
    assert categories == {"carb_load", "bodywork", "logistics"}


def test_race_week_carb_load_date_is_precisely_computed_and_may_fall_outside_the_week(
    race_week_macro,
):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=event
    )

    carb_load = next(i for i in week.race_week_checklist if i.category == "carb_load")
    expected_date = event.event_date - timedelta(days=CARB_LOAD_WINDOW_START_DAYS_OUT)
    assert carb_load.date == expected_date
    # This is the whole point of computing from event_date rather than
    # week_start: for a Friday race, the 72h-out carb-load date lands in the
    # week AFTER this WeekPlan's own 7-day span (the un-modeled event week).
    assert carb_load.date > final_week_start + timedelta(days=6)
    assert "10-12 g/kg" in carb_load.label
    assert "Burke" in carb_load.label


def test_race_week_bodywork_date_lands_on_final_taper_weeks_last_day(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=event
    )

    bodywork = next(i for i in week.race_week_checklist if i.category == "bodywork")
    expected_date = event.event_date - timedelta(days=BODYWORK_WINDOW_DAYS_OUT)
    assert bodywork.date == expected_date
    # Unlike carb-load above, the bodywork window's earlier (5-day-out) edge
    # happens to fall exactly on this week's own last day for a Friday race.
    assert bodywork.date == final_week_start + timedelta(days=6)
    assert "3-5 days" in bodywork.label
    assert "Weerapong" in bodywork.label


def test_race_week_logistics_items_are_distinct_from_physiology_and_dated_at_week_start(
    race_week_macro,
):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=event
    )

    logistics = [i for i in week.race_week_checklist if i.category == "logistics"]
    # 3 generic items + 1 water-temp item (make_event sets water_temp_c=18.0)
    assert len(logistics) == 4
    assert all(item.date == final_week_start for item in logistics)
    joined = " ".join(item.label for item in logistics)
    assert "acclimatize" in joined
    assert "fueling plan" in joined
    assert "support" in joined
    assert "18" in joined  # water_temp_c echoed into the conditions item
    # Never conflate the athlete-specific logistics checklist with the
    # cited physiological windows above.
    assert "Burke" not in joined
    assert "Weerapong" not in joined


def test_race_week_logistics_omits_water_temp_item_when_event_has_none(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    event = event.model_copy(update={"water_temp_c": None})
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=event
    )
    logistics = [i for i in week.race_week_checklist if i.category == "logistics"]
    assert len(logistics) == 3


def test_race_week_checklist_absent_on_ordinary_taper_week(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    ordinary_week_start = taper_block.start_date  # week 0 of 2 -- not final
    assert ordinary_week_start != final_week_start
    week = generate_week(
        athlete, macro, _iso_week(ordinary_week_start), ordinary_week_start, event=event
    )
    assert week.race_week_checklist == []


def test_race_week_checklist_absent_on_non_taper_final_week(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    peak_block = next(b for b in macro.blocks if b.name == "peak")
    peak_last_week_start = peak_block.end_date - timedelta(days=6)
    week = generate_week(
        athlete, macro, _iso_week(peak_last_week_start), peak_last_week_start, event=event
    )
    assert week.race_week_checklist == []


def test_race_week_checklist_absent_when_event_not_passed(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    week = generate_week(athlete, macro, _iso_week(final_week_start), final_week_start)
    assert week.race_week_checklist == []


def test_race_week_checklist_absent_for_b_priority_event(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    b_event = event.model_copy(update={"priority": "B"})
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=b_event
    )
    assert week.race_week_checklist == []


def test_race_week_checklist_absent_for_inactive_event(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    inactive_event = event.model_copy(update={"active": False})
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=inactive_event
    )
    assert week.race_week_checklist == []


def test_race_week_checklist_absent_when_event_id_does_not_match_macro(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    unrelated_event = make_event(event_date=event.event_date, priority="A")
    assert unrelated_event.id != macro.event_id
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=unrelated_event
    )
    assert week.race_week_checklist == []


def test_race_week_checklist_priority_match_is_case_insensitive(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    lowercase_event = event.model_copy(update={"priority": "a"})
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=lowercase_event
    )
    assert len(week.race_week_checklist) > 0


def test_race_week_checklist_does_not_touch_volume_or_session_composition(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    with_event = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, event=event
    )
    without_event = generate_week(athlete, macro, _iso_week(final_week_start), final_week_start)

    assert with_event.target_volume_m == without_event.target_volume_m
    assert [s.distance_m for s in with_event.sessions] == [
        s.distance_m for s in without_event.sessions
    ]
    assert [s.date for s in with_event.sessions] == [s.date for s in without_event.sessions]


def test_race_week_checklist_helper_returns_every_item_as_a_real_model(race_week_macro):
    athlete, event, macro, taper_block, final_week_start = race_week_macro
    items = _race_week_checklist(event, final_week_start)
    assert all(isinstance(item, RaceWeekChecklistItem) for item in items)


# --- race week: bike-primary final taper week (PR #167 red-team review, Finding 2) --------
# Verified live by the reviewer: a 4-week taper from a light prior week
# produces taper_end = max(0, round(peak*(1-0.25*4))) = 0, and
# DEFAULT_BIKE_SESSION_MIN's per-session floor combined with the low-volume
# session-count reduction collapsed the entire final taper week to ONE
# 15-minute session -- with event.priority=="A"/event.active==True, and
# zero race-week checklist content (generate_week's bike path used to
# return race_week_checklist=[] unconditionally).


@pytest.fixture
def bike_race_week_macro():
    """Bike-primary counterpart to `race_week_macro` above. Reuses
    `_make_bike_macro`'s 24-week runway (>= TAPER_RUNWAY_THRESHOLD_WEEKS),
    which sizes a 4-week (TAPER_WEEKS_LONG) taper -- taper_end =
    round(peak*(1-0.25*4)) = 0, reproducing Finding 2's exact collapse
    scenario ("a 4-week taper from a light prior week produces
    taper_end = 0") for the final taper week under test."""
    athlete, event, macro = _make_bike_macro()
    taper_block = next(b for b in macro.blocks if b.name == "taper")
    assert (taper_block.end_date - taper_block.start_date).days // 7 + 1 == 4
    final_week_start = taper_block.start_date + timedelta(weeks=3)
    return athlete, event, macro, taper_block, final_week_start


def test_generate_week_bike_primary_final_taper_week_target_collapses_to_zero(bike_race_week_macro):
    # Sanity check: this fixture actually reproduces Finding 2's exact
    # collapse scenario before testing the fix below.
    athlete, event, macro, taper_block, final_week_start = bike_race_week_macro
    week = generate_week(
        athlete, macro, _iso_week(final_week_start), final_week_start, primary_sport="bike"
    )
    assert week.target_volume_m == 0


def test_generate_week_bike_primary_final_taper_week_has_real_content_not_one_token_ride(
    bike_race_week_macro,
):
    athlete, event, macro, taper_block, final_week_start = bike_race_week_macro
    week = generate_week(
        athlete,
        macro,
        _iso_week(final_week_start),
        final_week_start,
        primary_sport="bike",
        event=event,
    )
    bike_sessions = [s for s in week.sessions if s.sport == "bike"]
    assert len(bike_sessions) >= BIKE_FINAL_TAPER_MIN_SESSIONS
    assert all(s.duration_min > 0 for s in bike_sessions)
    # genuinely more than a single DEFAULT_BIKE_SESSION_MIN-floored token
    # ride for the whole week (Finding 2's exact bug).
    total_min = sum(s.duration_min for s in bike_sessions)
    assert total_min > DEFAULT_BIKE_SESSION_MIN
    # distinct days, distinct real content -- not a duplicate/degenerate pair.
    dates = {s.date for s in bike_sessions}
    assert len(dates) == len(bike_sessions)


def test_generate_week_bike_primary_final_taper_week_has_race_week_checklist(bike_race_week_macro):
    athlete, event, macro, taper_block, final_week_start = bike_race_week_macro
    week = generate_week(
        athlete,
        macro,
        _iso_week(final_week_start),
        final_week_start,
        primary_sport="bike",
        event=event,
    )
    assert len(week.race_week_checklist) > 0
    categories = {item.category for item in week.race_week_checklist}
    assert categories == {"carb_load", "bodywork", "logistics"}


def test_generate_week_bike_primary_ordinary_taper_week_no_checklist_and_full_session_count(
    bike_race_week_macro,
):
    # Negative control: the floor/checklist only fire on the FINAL taper
    # week of a qualifying event -- an earlier (non-collapsed) taper week is
    # untouched.
    athlete, event, macro, taper_block, final_week_start = bike_race_week_macro
    ordinary_week_start = taper_block.start_date
    assert ordinary_week_start != final_week_start
    week = generate_week(
        athlete,
        macro,
        _iso_week(ordinary_week_start),
        ordinary_week_start,
        primary_sport="bike",
        event=event,
    )
    assert week.race_week_checklist == []


def test_generate_week_bike_primary_final_taper_week_no_floor_or_checklist_for_b_priority_event(
    bike_race_week_macro,
):
    # Negative control: a non-qualifying (B-priority) event gets neither the
    # floor nor the checklist -- same qualifying gate the swim path uses.
    athlete, event, macro, taper_block, final_week_start = bike_race_week_macro
    event = event.model_copy(update={"priority": "B"})
    week = generate_week(
        athlete,
        macro,
        _iso_week(final_week_start),
        final_week_start,
        primary_sport="bike",
        event=event,
    )
    assert week.race_week_checklist == []


# --- scaffold_sharpening_macro (sharpening-macro build) -----------------------------
#
# A second, genuinely DIFFERENT periodization shape from scaffold_macro's
# own base->build->peak->taper -- see swim_coach.plan.scaffold_sharpening_
# macro's own docstring. Andrew's real scenario: ~5.5 weeks to a cyclocross
# peak, but already consistently training since April -- MIN_MACRO_WEEKS
# (8) correctly refuses the standard shape, and this shape exists for
# exactly that case.


def _make_sharpening_event(**overrides):
    data = dict(
        id=uuid.uuid4(),
        athlete_id=ATHLETE_ID,
        name="CX Sharpening Goal",
        event_date=START + timedelta(weeks=5),
        target_metric="duration_min",
        distance_m=None,
        target_value=120.0,
        priority="A",
        primary_sport="bike",
    )
    data.update(overrides)
    return Event(**data)


def test_sharpening_min_macro_weeks_is_derived_and_below_min_macro_weeks():
    # Non-negotiable design property: the sharpening shape's own floor is a
    # DERIVED number (Issurin's minimum transmutation-block length +
    # scaffold_macro's own short taper, both already-existing constants,
    # not a newly-invented one), and always strictly below MIN_MACRO_WEEKS
    # so the two shapes' accepted runway ranges never overlap.
    assert SHARPENING_MIN_MACRO_WEEKS == SHARPEN_WEEKS_MIN + TAPER_WEEKS_SHORT
    assert SHARPENING_MIN_MACRO_WEEKS < MIN_MACRO_WEEKS


def test_scaffold_sharpening_macro_raises_below_its_own_min_weeks():
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=SHARPENING_MIN_MACRO_WEEKS - 1))
    with pytest.raises(ValueError, match="need at least"):
        scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)


def test_scaffold_sharpening_macro_refuses_runway_long_enough_for_the_standard_shape():
    # This shape must never encroach on scaffold_macro's own territory --
    # explicit "existing shape untouched" scope rule.
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=MIN_MACRO_WEEKS))
    with pytest.raises(ValueError, match="scaffold_macro instead"):
        scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)


def test_scaffold_sharpening_macro_block_allocation_no_hold_at_minimum_runway():
    # weeks_available == SHARPENING_MIN_MACRO_WEEKS (4): all of it goes to
    # sharpen (2, Issurin's own floor) + taper (2) -- no spare runway for
    # a hold phase.
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=SHARPENING_MIN_MACRO_WEEKS))
    macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)
    weeks = {b.name: (b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks}
    assert [b.name for b in macro.blocks] == ["sharpen", "taper"]
    assert weeks == {"sharpen": SHARPEN_WEEKS_MIN, "taper": TAPER_WEEKS_SHORT}
    assert sum(weeks.values()) == SHARPENING_MIN_MACRO_WEEKS
    assert macro.blocks[0].start_date == START
    assert macro.blocks[-1].end_date == START + timedelta(weeks=SHARPENING_MIN_MACRO_WEEKS) - timedelta(days=1)


def test_scaffold_sharpening_macro_block_allocation_sharpen_caps_at_issurin_max():
    # weeks_available == 6: sharpen would want remainder(4)=4 which is
    # exactly SHARPEN_WEEKS_MAX -- still no hold phase (remainder consumed
    # entirely by sharpen).
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=6))
    macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)
    weeks = {b.name: (b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks}
    assert weeks == {"sharpen": SHARPEN_WEEKS_MAX, "taper": TAPER_WEEKS_SHORT}
    assert sum(weeks.values()) == 6


def test_scaffold_sharpening_macro_block_allocation_hold_appears_with_spare_runway():
    # weeks_available == 7: remainder=5 > SHARPEN_WEEKS_MAX(4) -- sharpen
    # caps at 4, and the leftover 1 week becomes a real `hold` block. This
    # is the "only present if runway allows" property.
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=7))
    macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)
    assert [b.name for b in macro.blocks] == ["hold", "sharpen", "taper"]
    weeks = {b.name: (b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks}
    assert weeks == {"hold": 1, "sharpen": SHARPEN_WEEKS_MAX, "taper": TAPER_WEEKS_SHORT}
    assert sum(weeks.values()) == 7
    # blocks are contiguous
    for prev, curr in zip(macro.blocks, macro.blocks[1:]):
        assert curr.start_date == prev.end_date + timedelta(days=1)


def test_scaffold_sharpening_macro_andrews_real_scenario_five_and_a_half_weeks():
    # Andrew's own real test case: ~5.5 weeks of runway (floors to 5 whole
    # weeks, same _monday_on_or_after/_monday_of_week arithmetic scaffold_
    # macro itself uses) toward a real cyclocross-shaped goal.
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(
        event_date=START + timedelta(weeks=5, days=3)  # ~5.5 weeks out
    )
    macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)
    weeks = {b.name: (b.end_date - b.start_date).days // 7 + 1 for b in macro.blocks}
    assert weeks == {"sharpen": 3, "taper": TAPER_WEEKS_SHORT}
    assert sum(weeks.values()) == 5


# --- Mandatory correctness property #1: genuinely different shape -------------------


def test_scaffold_sharpening_macro_volume_is_flat_no_ramp_math_at_all():
    # Direct proof this is NOT scaffold_macro's shape compressed into fewer
    # weeks: scaffold_macro ramps linearly from a low starting volume to
    # peak across its base+build weeks (WEEKLY_VOLUME_RAMP_CAP/week). This
    # shape has NO ramp math at all -- hold and sharpen both end at the
    # exact same flat volume as current_weekly_volume_m.
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=7))
    macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)
    hold_block = next(b for b in macro.blocks if b.name == "hold")
    sharpen_block = next(b for b in macro.blocks if b.name == "sharpen")
    assert hold_block.weekly_volume_target_m == 300
    assert sharpen_block.weekly_volume_target_m == 300


def test_scaffold_sharpening_macro_generate_week_interpolation_is_flat_across_hold_and_sharpen():
    # Not just the block-level end target -- prove every INDIVIDUAL week
    # generate_week produces within hold/sharpen carries the identical
    # target_volume_m (flat), in direct contrast to scaffold_macro's own
    # base block, where generate_week's linear interpolation makes each
    # week's target STRICTLY GREATER than the last (a real ramp). Same
    # athlete, same current volume, both real generate_week calls -- not an
    # assertion about the block config alone.
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=7))
    sharp_macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)

    sharp_targets = []
    for block in sharp_macro.blocks:
        if block.name not in ("hold", "sharpen"):
            continue
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(
                athlete, sharp_macro, _iso_week(week_start), week_start, primary_sport="bike"
            )
            sharp_targets.append(week.target_volume_m)
    assert sharp_targets == [300] * len(sharp_targets)  # flat -- no ramp, by construction

    # Contrast: scaffold_macro's own base block for a real long-runway
    # SWIM macro (deliberately swim, not bike, here -- bike's own periodic
    # deload cadence would otherwise interrupt monotonicity for an
    # unrelated reason; swim's base/build/peak span is documented to climb
    # with no deload at all, the cleanest "genuine ramp" contrast) -- its
    # weekly targets strictly increase week over week, the exact shape this
    # build must NOT reproduce for the sharpening macro.
    swim_athlete = make_athlete()
    swim_event = make_event(event_date=START + timedelta(weeks=24))
    long_macro = scaffold_macro(
        swim_athlete, swim_event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    base_block = next(b for b in long_macro.blocks if b.name == "base")
    weeks_in_base = (base_block.end_date - base_block.start_date).days // 7 + 1
    base_targets = []
    for i in range(weeks_in_base):
        week_start = base_block.start_date + timedelta(weeks=i)
        week = generate_week(swim_athlete, long_macro, _iso_week(week_start), week_start)
        base_targets.append(week.target_volume_m)
    assert base_targets == sorted(base_targets)
    assert len(set(base_targets)) > 1  # a real ramp, not flat like the sharpening shape


def test_scaffold_sharpening_macro_taper_reuses_existing_decay_formula_unchanged():
    # The taper block is NOT re-derived -- it decays off the flat
    # hold/sharpen volume via the exact same TAPER_WEEKLY_DECAY formula
    # scaffold_macro's own taper block uses off its (ramped) peak.
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=6))
    macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)
    taper_block = next(b for b in macro.blocks if b.name == "taper")
    expected = max(0, round(300 * (1 - TAPER_WEEKLY_DECAY * TAPER_WEEKS_SHORT)))
    assert taper_block.weekly_volume_target_m == expected


def test_scaffold_sharpening_macro_explicit_sharpen_volume_overrides_current():
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=6))
    macro = scaffold_sharpening_macro(
        athlete, event, START, current_weekly_volume_m=300, sharpen_weekly_volume_m=250
    )
    sharpen_block = next(b for b in macro.blocks if b.name == "sharpen")
    assert sharpen_block.weekly_volume_target_m == 250


def test_scaffold_sharpening_macro_produces_a_valid_macro_plan_for_swim_athlete_too():
    # scaffold_sharpening_macro itself is sport-agnostic block-building math
    # (like scaffold_macro) -- it is the TOOL LAYER (backend/app/tools.py)
    # that scopes real invocation to primary_sport="bike" for this build,
    # not this engine function itself refusing a swim athlete. Confirms the
    # function doesn't crash/misbehave for a swim event; does not claim
    # generate_week's swim path was extended to understand "hold"/"sharpen"
    # (explicitly out of scope -- see MacroBlock.name's own docstring).
    athlete = make_athlete()
    event = make_event(
        event_date=START + timedelta(weeks=5), name="Short-runway swim goal"
    )
    macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=8000)
    assert [b.name for b in macro.blocks] == ["sharpen", "taper"]


# --- generate_week bike-path handling of hold/sharpen blocks -------------------------


@pytest.fixture
def sharpening_bike_macro():
    athlete = make_athlete(sports=["bike"])
    event = _make_sharpening_event(event_date=START + timedelta(weeks=7))
    macro = scaffold_sharpening_macro(athlete, event, START, current_weekly_volume_m=300)
    return athlete, event, macro


def test_generate_week_bike_primary_produces_real_sessions_for_hold_block(sharpening_bike_macro):
    athlete, event, macro = sharpening_bike_macro
    hold_block = next(b for b in macro.blocks if b.name == "hold")
    week = generate_week(
        athlete, macro, _iso_week(hold_block.start_date), hold_block.start_date, primary_sport="bike"
    )
    assert week.meso_block == "hold"
    bike_sessions = [s for s in week.sessions if s.sport == "bike"]
    assert len(bike_sessions) >= 1
    assert all(s.duration_min > 0 for s in bike_sessions)


def test_generate_week_bike_primary_produces_real_sessions_for_sharpen_block(sharpening_bike_macro):
    athlete, event, macro = sharpening_bike_macro
    sharpen_block = next(b for b in macro.blocks if b.name == "sharpen")
    week = generate_week(
        athlete, macro, _iso_week(sharpen_block.start_date), sharpen_block.start_date, primary_sport="bike"
    )
    assert week.meso_block == "sharpen"
    bike_sessions = [s for s in week.sessions if s.sport == "bike"]
    assert len(bike_sessions) >= 1
    # Real race-specific interval content -- reuses the existing template
    # rotation, not a flat generic block.
    hard_sessions = [s for s in bike_sessions if "endurance ride" not in s.purpose]
    assert len(hard_sessions) >= 1


def test_generate_week_bike_primary_hold_and_sharpen_never_get_scheduled_deload(sharpening_bike_macro):
    # Deliberate design decision (see the code comment above is_deload_week
    # in generate_week): hold/sharpen are excluded from the periodic
    # BIKE_DELOAD_CADENCE_WEEKS step-down, same as taper already is -- a
    # short, already-concentrated block has nothing to "step down" from.
    athlete, event, macro = sharpening_bike_macro
    for block in macro.blocks:
        if block.name not in ("hold", "sharpen"):
            continue
        weeks_in_block = (block.end_date - block.start_date).days // 7 + 1
        for i in range(weeks_in_block):
            week_start = block.start_date + timedelta(weeks=i)
            week = generate_week(
                athlete, macro, _iso_week(week_start), week_start, primary_sport="bike"
            )
            assert "deload" not in week.focus.lower()


# --- Mandatory correctness property #2: base-detection is athlete-level, --------------
# --- event-independent (has_established_training_base lives in load.py; -------------
# --- see tests/unit/test_load.py for the direct, structural proof). This ------------
# --- test proves the SAME macro shape and volumes come out of scaffold_ -------------
# --- sharpening_macro regardless of which event/goal it's called for, given --------
# --- the same athlete/current-volume/start -- the engine layer itself carries -------
# --- no event-specific branching that could make the shape depend on the goal. -------


def test_scaffold_sharpening_macro_same_shape_regardless_of_which_goal_is_passed():
    athlete = make_athlete(sports=["bike"])
    cyclocross_goal = _make_sharpening_event(
        name="Cyclocross Regional Championship", event_date=START + timedelta(weeks=5, days=3)
    )
    unrelated_mtb_goal = _make_sharpening_event(
        name="December MTB Enduro", event_date=START + timedelta(weeks=5, days=3)
    )
    macro_a = scaffold_sharpening_macro(athlete, cyclocross_goal, START, current_weekly_volume_m=300)
    macro_b = scaffold_sharpening_macro(athlete, unrelated_mtb_goal, START, current_weekly_volume_m=300)

    shape_a = [(b.name, (b.end_date - b.start_date).days, b.weekly_volume_target_m) for b in macro_a.blocks]
    shape_b = [(b.name, (b.end_date - b.start_date).days, b.weekly_volume_target_m) for b in macro_b.blocks]
    assert shape_a == shape_b


# --- Mandatory correctness property #3: zero regression to scaffold_macro's ----------
# --- existing shape -- pinned, exact expected values (a snapshot), not just ----------
# --- "the old tests still pass" -----------------------------------------------------


def test_scaffold_macro_swim_macro_unchanged_pinned_snapshot():
    athlete = make_athlete()
    event = make_event(event_date=START + timedelta(weeks=24))
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=8000, peak_weekly_volume_m=20000
    )
    snapshot = [
        (b.name, b.start_date.isoformat(), b.end_date.isoformat(), b.weekly_volume_target_m)
        for b in macro.blocks
    ]
    assert snapshot == [
        ("base", "2026-01-05", "2026-03-22", 17000),
        ("build", "2026-03-23", "2026-05-03", 20000),
        ("peak", "2026-05-04", "2026-05-24", 20000),
        ("taper", "2026-05-25", "2026-06-21", 0),
    ]


def test_scaffold_macro_long_runway_bike_macro_unchanged_pinned_snapshot():
    athlete = make_athlete(sports=["bike"])
    event = make_event(
        event_date=START + timedelta(weeks=24),
        target_metric="duration_min",
        distance_m=None,
        target_value=300.0,
        primary_sport="bike",
    )
    macro = scaffold_macro(
        athlete, event, START, current_weekly_volume_m=200, peak_weekly_volume_m=600
    )
    snapshot = [
        (b.name, b.start_date.isoformat(), b.end_date.isoformat(), b.weekly_volume_target_m)
        for b in macro.blocks
    ]
    assert snapshot == [
        ("base", "2026-01-05", "2026-03-22", 510),
        ("build", "2026-03-23", "2026-05-03", 600),
        ("peak", "2026-05-04", "2026-05-24", 600),
        ("taper", "2026-05-25", "2026-06-21", 0),
    ]
