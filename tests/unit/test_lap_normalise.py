"""Double-trigger lap normalisation: auto-lap-by-position firing twice per lap (out, hairpin, back over the mark)."""

from __future__ import annotations

from swim_coach.canonical_laps import build_canonical_laps
from swim_coach.course_sectors import SECTOR_COUNT, build_course_sectors
from swim_coach.lap_normalise import merge_double_trigger_laps
from swim_coach.models import Workout, WorkoutLap

MARK = (47.0, 8.0)
FAR = (47.01, 8.01)  # ~1.4 km from the mark (synthetic coordinates)
LONG_S, LONG_M, SHORT_S, SHORT_M = 320.0, 1850.0, 17.0, 100.0


def _laps(pattern: list[tuple[float, float]], power: float = 300.0) -> list[WorkoutLap]:
    out, t = [], 0.0
    for i, (dur, dist) in enumerate(pattern, 1):
        out.append(WorkoutLap(index=i, start_offset_s=t, duration_s=dur, distance_m=dist, avg_power_w=power, avg_hr=170))
        t += dur
    return out


def _alternating(n: int = 4) -> list[tuple[float, float]]:
    return [(LONG_S, LONG_M), (SHORT_S, SHORT_M)] * n


def _series(laps: list[WorkoutLap], at_mark: set[int]) -> dict:
    """1 Hz GPS series: at the start offsets in `at_mark` the rider is on the mark, anywhere else far away."""
    end = int(laps[-1].start_offset_s + laps[-1].duration_s)
    pts = [MARK if t in at_mark else FAR for t in range(end + 1)]
    return {
        "t_s": [float(t) for t in range(end + 1)],
        "lat": [p[0] for p in pts],
        "lng": [p[1] for p in pts],
    }


def _mark_starts(laps: list[WorkoutLap], fragments_at_mark: bool) -> set[int]:
    return {int(l.start_offset_s) for l in laps if fragments_at_mark or l.duration_s > 100}


def test_alternating_pattern_without_gps_merges_into_full_laps():
    merged = merge_double_trigger_laps(_laps(_alternating()))
    assert [round(l.duration_s) for l in merged] == [337] * 4
    assert [round(l.distance_m) for l in merged] == [1950] * 4
    assert [l.start_offset_s for l in merged] == [0.0, 337.0, 674.0, 1011.0]
    assert merged[0].avg_power_w == 300.0


def test_merged_power_is_duration_weighted():
    laps = _laps(_alternating(3))
    for i in range(1, len(laps), 2):
        laps[i] = laps[i].model_copy(update={"avg_power_w": 100.0})
    merged = merge_double_trigger_laps(laps)
    assert round(merged[0].avg_power_w) == round((300 * LONG_S + 100 * SHORT_S) / (LONG_S + SHORT_S))


def test_raw_laps_are_not_mutated():
    laps = _laps(_alternating(3))
    merge_double_trigger_laps(laps)
    assert len(laps) == 6 and laps[0].duration_s == LONG_S


def test_single_genuine_short_lap_without_gps_is_not_swallowed():
    laps = _laps([(LONG_S, LONG_M)] * 2 + [(SHORT_S, SHORT_M)] + [(LONG_S, LONG_M)] * 2)
    assert len(merge_double_trigger_laps(laps)) == 5


def test_two_occurrences_without_gps_are_not_enough():
    assert len(merge_double_trigger_laps(_laps(_alternating(2)))) == 4


def test_with_gps_at_the_mark_a_single_fragment_merges():
    laps = _laps([(LONG_S, LONG_M), (SHORT_S, SHORT_M), (LONG_S, LONG_M), (LONG_S, LONG_M)])
    series = _series(laps, _mark_starts(laps, fragments_at_mark=True))
    assert len(merge_double_trigger_laps(laps, series)) == 3


def test_with_gps_away_from_the_mark_a_repeating_pattern_is_not_merged():
    laps = _laps(_alternating(4))
    series = _series(laps, _mark_starts(laps, fragments_at_mark=False))
    assert len(merge_double_trigger_laps(laps, series)) == 8


def test_trailing_finish_remainder_is_kept_and_last_fragment_merges():
    merged = merge_double_trigger_laps(_laps(_alternating(4) + [(31.0, 86.0)]))
    assert [round(l.duration_s) for l in merged] == [337, 337, 337, 337, 31]


def test_warmup_style_short_laps_between_short_laps_are_untouched():
    laps = _laps([(900.0, 5400.0), (20.0, 170.0), (100.0, 540.0), (20.0, 170.0), (100.0, 600.0), (20.0, 200.0), (100.0, 700.0)])
    assert len(merge_double_trigger_laps(laps)) == 7


def test_course_sectors_cover_the_hairpin_after_merging():
    laps = _laps(_alternating(3))
    t_s = [float(t) for t in range(int(sum(l.duration_s for l in laps)))]
    dist = [(t + 1) * (LONG_M + SHORT_M) / (LONG_S + SHORT_S) for t in range(len(t_s))]
    series = {"t_s": t_s, "dist_m": dist, "power_w": [300.0] * len(t_s)}
    cs = build_course_sectors(build_canonical_laps(laps, series), series)
    assert cs is not None and len(cs.laps) == 3 and cs.sector_count == SECTOR_COUNT
    assert all(336 <= l.time_s <= 337 for l in cs.laps)  # 1 Hz fencepost; the raw long piece alone would be 320
    assert 336 <= cs.ideal_lap_s <= 337


def test_with_gps_first_trigger_a_little_short_of_the_mark_still_merges():
    laps = _laps(_alternating(2))
    finish_s = int(laps[-1].start_offset_s + laps[-1].duration_s)
    series = _series(laps, _mark_starts(laps, fragments_at_mark=True) | {finish_s})
    for lap in laps[1::2]:  # first trigger fires ~28 m before the mark on the approach
        series["lat"][int(lap.start_offset_s)] = MARK[0] + 0.00025
    assert len(merge_double_trigger_laps(laps, series)) == 2
