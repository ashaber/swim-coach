"""Swim moving pace, pool-unit inference and set segmentation (`swim_coach.swim_sets`),
plus the `moving_min` fix in `swim_coach.analysis`. Synthetic lengths only; the one fixture
test uses the real pool-swim FIT."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest

from swim_coach.analysis import AnalysisContext, analytics_for_coach
from swim_coach.models import Workout, WorkoutLength, WorkoutPause
from swim_coach.parse_files import parse_fit
from swim_coach.swim_sets import fmt_mmss, infer_pool, segment_swim, swim_pace_block

YD = 0.9144
POOL_YD_M = 25 * YD
FIT_POOL = Path(__file__).parent / "fixtures" / "fit" / "real_swim.fit"


def build(reps: list[tuple[int, float, float]], *, offsets: bool = False):
    """reps = (n_lengths, seconds_per_length, rest_after_s). Returns (lengths, idle pauses)."""
    lengths: list[WorkoutLength] = []
    pauses: list[WorkoutPause] = []
    t = 0.0
    for n, per, rest in reps:
        for _ in range(n):
            lengths.append(
                WorkoutLength(
                    index=len(lengths), duration_s=per, stroke="freestyle", strokes=18, swolf=per + 18,
                    start_offset_s=t if offsets else None,
                )
            )
            t += per
        if rest:
            pauses.append(WorkoutPause(start_offset_s=t, duration_s=rest, source="idle_length"))
            t += rest
    return lengths, pauses


def pool_sets(reps, *, offsets=False):
    lengths, pauses = build(reps, offsets=offsets)
    return segment_swim(lengths, pauses, pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=None)


@pytest.mark.parametrize("offsets", [False, True])
def test_warmup_main_set_cooldown_become_three_sets(offsets):
    reps = [(20, 33.75, 30)] + [(4, 20.0, 25)] * 10 + [(8, 30.0, 0)]
    sets, note = pool_sets(reps, offsets=offsets)
    assert [s.count for s in sets] == [1, 10, 1]
    warm, main, cool = sets
    assert warm.rep_distance == 500 and warm.avg_pace_s_per_100 == pytest.approx(135.0)
    assert warm.description == "500 free @ 2:15/100"
    assert main.rep_distance == 100 and main.total_distance == 1000
    assert main.send_off_s == 105
    assert main.avg_pace_s_per_100 == pytest.approx(80.0)
    assert main.avg_rest_s == pytest.approx(25.0)
    assert main.description == "10×100 free on 1:45 @ 1:20/100 (rest ~0:25)"
    assert cool.rep_distance == 200
    assert cool.send_off_s is None
    assert note is None


def test_no_recorded_rest_is_one_rep_with_note():
    lengths, pauses = build([(80, 30.0, 0)])
    sets, note = segment_swim(lengths, pauses, pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=2400)
    assert len(sets) == 1 and sets[0].count == 1
    assert sets[0].rep_distance == 2000
    assert note is not None and "rest" in note


def test_renee_like_swim_paces_sets_and_note():
    # 121 lengths, two idle rests (102 s at 998 s, 122 s later): 3 reps; ~28 min unbroken.
    first = 998.0 / 36
    mid = 110.0 / 4
    last = (3308.0 - 998.0 - 110.0) / 81
    lengths, pauses = build([(36, first, 102), (4, mid, 122), (81, last, 0)])
    assert len(lengths) == 121 and pauses[0].start_offset_s == pytest.approx(998.0)
    sets, note = segment_swim(lengths, pauses, pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=3532)
    assert [s.count for s in sets] == [1, 1, 1]
    assert note is not None and "Only 2 rests were recorded" in note
    pace = swim_pace_block(moving_s=3308.0, elapsed_s=3532.0, distance_m=2766, pool_unit="yd")
    assert pace["moving_pace_s_per_100_unit"] == pytest.approx(109.4, abs=0.2)
    assert pace["elapsed_pace_s_per_100_unit"] == pytest.approx(116.8, abs=0.2)
    assert pace["moving_pace_s_per_100m"] == pytest.approx(119.6, abs=0.2)
    assert pace["elapsed_pace_s_per_100m"] == pytest.approx(127.7, abs=0.2)
    assert pace["rest_total_s"] == pytest.approx(224.0)


@pytest.mark.parametrize(
    "distance_m,n,expected",
    [
        (2766.0, 121, (22.86, "yd")),
        (3025.0, 121, (25.0, "m")),
        (2000.0, 40, (50.0, "m")),
        (1828.8, 40, (45.72, "yd")),
        (1234.0, 77, (None, "m")),
    ],
)
def test_infer_pool(distance_m, n, expected):
    length_m, unit = infer_pool(distance_m, n)
    assert unit == expected[1]
    if expected[0] is None:
        assert length_m is None
    else:
        assert length_m == pytest.approx(expected[0], abs=0.01)


def test_fmt_mmss_carries_seconds():
    assert fmt_mmss(79.6) == "1:20"
    assert fmt_mmss(119.7) == "2:00"


def _workout(draft) -> Workout:
    return draft.to_workout(athlete_id=uuid4())


def test_real_pool_fixture_gets_paces_and_sets():
    draft = parse_fit(FIT_POOL)
    assert draft.pool_unit == "yd" and draft.pool_length_m == pytest.approx(22.86)
    assert all(length.start_offset_s is not None for length in draft.lengths)
    workout = _workout(draft)
    analytics = workout.analyze(AnalysisContext(elapsed_min=draft.elapsed_min))
    assert analytics.pool_unit == "yd"
    assert analytics.moving_pace_s_per_100_unit and analytics.elapsed_pace_s_per_100_unit
    assert analytics.moving_pace_s_per_100_unit <= analytics.elapsed_pace_s_per_100_unit
    assert analytics.swim_sets
    assert analytics.moving_min == pytest.approx(sum(l.duration_s for l in draft.lengths) / 60)
    view = analytics_for_coach(analytics, "swim_pool")
    assert view["swim_sets"] and all(isinstance(s, str) for s in view["swim_sets"])
    assert "moving_pace_s_per_100_unit" in view


def test_stored_workout_without_unit_infers_yards():
    lengths, pauses = build([(121, 27.3, 0)])
    w = Workout(
        id=uuid4(), athlete_id=uuid4(), date=date(2026, 10, 22), sport="swim_pool", source="fit",
        distance_m=2766, duration_min=58.9, lengths=lengths, pauses=pauses,
    )
    a = w.analyze(AnalysisContext(elapsed_min=58.9))
    assert a.pool_unit == "yd" and a.swim_sets


def test_bike_moving_min_excludes_pauses():
    w = Workout(
        id=uuid4(), athlete_id=uuid4(), date=date(2026, 10, 1), sport="bike", source="fit",
        distance_m=100000, duration_min=444.6,
        pauses=[
            WorkoutPause(start_offset_s=600, duration_s=300, source="timer"),
            WorkoutPause(start_offset_s=700, duration_s=100, source="stationary"),  # overlaps the first
            WorkoutPause(start_offset_s=5000, duration_s=120, source="timer"),
        ],
    )
    a = w.analyze(AnalysisContext(elapsed_min=444.6))
    assert a.elapsed_min == pytest.approx(444.6)
    assert a.moving_min == pytest.approx(444.6 - (300 + 120) / 60)
    assert w.duration_min == 444.6


def test_moving_min_unchanged_without_elapsed():
    w = Workout(
        id=uuid4(), athlete_id=uuid4(), date=date(2026, 10, 1), sport="bike", source="fit",
        distance_m=1000, duration_min=30.0,
        pauses=[WorkoutPause(start_offset_s=60, duration_s=120, source="timer")],
    )
    assert w.analyze(AnalysisContext()).moving_min == pytest.approx(30.0)
