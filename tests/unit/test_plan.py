"""Tests for swim_coach.plan: macro scaffold + weekly plan generation.

No LLM calls, no network access -- pure arithmetic + model validation.
"""

import uuid
import warnings
from datetime import date, timedelta

import pytest

from swim_coach.models import Athlete, Event
from swim_coach.plan import (
    LONG_SWIM_SHARE,
    STRENGTH_SESSIONS_PER_WEEK,
    WEEKLY_VOLUME_RAMP_CAP,
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
