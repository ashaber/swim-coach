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


# --- detected wall rest, implausible-data guard, stroke labels ---------------------------

# Real length durations (seconds, numbers only) of a 25-yd-pool swim where wall rest was not
# recorded: it is folded into the next length (normal stroke count, inflated time).
UNRECORDED_REST_DURATIONS = [
    24, 26, 26, 26, 28, 34, 29, 30, 27, 30, 24, 24, 15, 28, 26, 25, 20, 19, 29, 20, 24, 25, 33, 21, 36, 25,
    37, 24, 25, 23, 24, 24, 42, 22, 24, 24, 36, 23, 24, 23, 17, 19, 22, 24, 21, 41, 30, 26, 13, 16, 31, 28,
    28, 25, 38, 23, 24, 25, 33, 24, 22, 25, 36, 24, 23, 23, 34, 25, 23, 24, 36, 28, 31, 28, 32, 26, 34, 29,
    45, 23, 23, 25, 32, 28, 23, 23, 35, 23, 22, 25, 32, 20, 25, 24, 25, 44, 34,
]


def lengths_from(durations, *, stroke="freestyle", strokes=12):
    return [
        WorkoutLength(index=i, duration_s=float(d), stroke=stroke, strokes=strokes)
        for i, d in enumerate(durations)
    ]


def test_unrecorded_wall_rest_is_detected_and_splits_reps():
    sets, note = segment_swim(
        lengths_from(UNRECORDED_REST_DURATIONS), [], pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=None
    )
    hundreds = [s for s in sets if s.rep_distance == 100 and s.count >= 4]
    assert hundreds, [s.description for s in sets]
    s = max(hundreds, key=lambda x: x.count)
    assert s.send_off_s == 105
    assert 5 <= s.avg_rest_s <= 15
    assert s.rest_source == "detected"
    assert "(rest ~0:10, detected)" in s.description


def test_steady_continuous_swim_has_no_detected_rest():
    # free median ~27.8 s, max 32.9 s: ordinary variation, not rest
    durations = [27.8, 28.5, 29.7, 27.0, 32.9, 27.5, 28.1, 26.9, 27.8, 29.0] * 8
    sets, note = segment_swim(
        lengths_from(durations), [], pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=sum(durations)
    )
    assert len(sets) == 1 and sets[0].count == 1
    assert note is not None


def test_slow_lengths_with_many_strokes_are_not_rest():
    lengths = lengths_from([25.0] * 40)
    lengths[10] = WorkoutLength(index=10, duration_s=40.0, stroke="freestyle", strokes=24)
    sets, _ = segment_swim(lengths, [], pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=None)
    assert len(sets) == 1 and sets[0].count == 1


def test_stroke_does_not_split_sets_and_unclear_stroke_is_omitted():
    lengths, pauses = build([(4, 22.0, 20)] * 4)
    for i, length in enumerate(lengths):
        length.stroke = "freestyle" if (i // 4) % 2 == 0 else "backstroke"
    for i in range(0, 16, 4):  # each rep half free, half back -> no clear stroke
        lengths[i + 2].stroke = "backstroke" if lengths[i].stroke == "freestyle" else "freestyle"
        lengths[i + 3].stroke = lengths[i + 2].stroke
    sets, _ = segment_swim(lengths, pauses, pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=None)
    assert len(sets) == 1 and sets[0].count == 4
    assert sets[0].stroke is None
    assert "mixed" not in sets[0].description and "free" not in sets[0].description


def test_dominant_stroke_labelled_and_device_im_kept():
    lengths, pauses = build([(10, 25.0, 0)])
    lengths[0].stroke = "backstroke"  # 90% free -> still free
    sets, _ = segment_swim(lengths, pauses, pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=None)
    assert sets[0].stroke == "free"
    im = lengths_from([25.0] * 8, stroke="im")
    sets, _ = segment_swim(im, [], pool_length_m=POOL_YD_M, pool_unit="yd", elapsed_s=None)
    assert sets[0].stroke == "IM" and "IM" in sets[0].description


def test_implausible_pace_hides_paces_and_sets():
    # watch thinks the pool is 50 m but lengths take 23 s: 0:46/100m is impossible
    lengths = lengths_from([23.0] * 40, stroke="backstroke")
    w = Workout(
        id=uuid4(), athlete_id=uuid4(), date=date(2026, 7, 2), sport="swim_pool", source="fit",
        distance_m=2000, duration_min=16.0, pool_length_m=50.0, pool_unit="m", lengths=lengths,
    )
    a = w.analyze(AnalysisContext(elapsed_min=16.0))
    assert a.data_quality_note and "paces hidden" in a.data_quality_note
    assert a.swim_sets == []
    assert a.moving_pace_s_per_100m is None and a.moving_pace_s_per_100_unit is None
    view = analytics_for_coach(a, "swim_pool")
    assert "paces hidden" in view["data_quality_note"] and "swim_sets" not in view
