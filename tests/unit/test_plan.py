"""Tests for swim_coach.plan: macro scaffold + weekly plan generation.

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import re
import uuid
import warnings
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event
from swim_coach.plan import (
    DEFAULT_POOL_SESSION_MIN,
    MIN_RAMP_SEED_VOLUME_M,
    POOL_SESSION_EST_M,
    STRENGTH_CORE_EXERCISES,
    STRENGTH_SESSIONS_PER_WEEK,
    WEEKLY_VOLUME_RAMP_CAP,
    _additional_swim_structure,
    _strength_session_structure,
    generate_week,
    scaffold_macro,
)
from swim_coach.store import FileStore

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


def test_generate_week_no_pool_coach_produces_real_structure(short_macro):
    athlete, macro = short_macro
    athlete = athlete.model_copy(update={"has_pool_coach": False})
    week_start = macro.blocks[0].start_date
    week = generate_week(athlete, macro, _iso_week(week_start), week_start)

    pool_sessions = [s for s in week.sessions if s.sport == "swim_pool"]
    assert len(pool_sessions) == 3
    assert {s.date.weekday() for s in pool_sessions} == {1, 3, 4}  # tue, thu, fri
    for s in pool_sessions:
        assert s.source == "ai_coach"
        assert s.status == "planned"
        assert s.distance_m == POOL_SESSION_EST_M
        assert s.duration_min == DEFAULT_POOL_SESSION_MIN
        assert s.structure is not None
        assert s.structure.strip() != ""
        assert "Warm-up" in s.structure
        assert "Main set" in s.structure
        assert "Cool-down" in s.structure


def test_generate_week_no_pool_coach_leaves_other_sessions_unaffected(short_macro):
    # Only the pool_schedule sessions change -- long swim, strength, and
    # recovery sessions (and pool_total_m's volume accounting) are identical
    # regardless of has_pool_coach.
    athlete, macro = short_macro
    week_start = macro.blocks[0].start_date
    week_with_coach = generate_week(athlete, macro, _iso_week(week_start), week_start)
    week_without_coach = generate_week(
        athlete.model_copy(update={"has_pool_coach": False}), macro, _iso_week(week_start), week_start
    )

    def _non_pool_shape(week):
        return [
            (s.sport, s.date, s.distance_m, s.duration_min, s.purpose)
            for s in week.sessions
            if s.sport != "swim_pool"
        ]

    assert _non_pool_shape(week_with_coach) == _non_pool_shape(week_without_coach)
    assert week_with_coach.target_volume_m == week_without_coach.target_volume_m


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
