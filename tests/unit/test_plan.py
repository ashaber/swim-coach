"""Tests for swim_coach.plan: macro scaffold + weekly plan generation.

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import re
import uuid
import warnings
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event, WorkoutRepeat, WorkoutStep
from swim_coach.plan import (
    DEFAULT_POOL_SESSION_MIN,
    LONG_SWIM_SHARE,
    MIN_RAMP_SEED_VOLUME_M,
    NO_COACH_POOL_SESSION_FLOOR_M,
    POOL_SESSION_EST_M,
    SESSION_ADJUSTMENT_INCREASE_CAP_PCT,
    STRENGTH_CORE_EXERCISES,
    STRENGTH_EXERCISE_REFERENCE_URLS,
    STRENGTH_FULL_BODY_ADDITION,
    STRENGTH_SESSIONS_PER_WEEK,
    WEEKLY_VOLUME_RAMP_CAP,
    _additional_swim_structure,
    _additional_swim_structure_template,
    _duration_min_for_distance,
    _format_pace_s,
    _no_coach_pool_purpose,
    _round_100,
    _strength_session_structure,
    _strength_session_structure_template,
    _z2_pace_s_per_100m,
    adjust_session,
    count_structured_steps,
    generate_week,
    scaffold_macro,
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
