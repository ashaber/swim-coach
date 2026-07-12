"""Tests for swim_coach.analytics -- pure functions, no I/O, no LLM/network.

Every function is exercised against small, hand-constructed synthetic
inputs with a known expected answer (drift %, split label, pause totals,
SWOLF trend) so the math is pinned independent of any real .fit fixture.
Real-fixture coverage lives in test_parse_files.py.
"""

from __future__ import annotations

import pytest

from swim_coach.analytics import (
    CARDIAC_DRIFT_FLAG_PCT,
    GAP_THRESHOLD_S,
    SPLIT_EVEN_BAND_PCT,
    STATIONARY_MIN_S,
    STATIONARY_SPEED_MPS,
    cardiac_drift,
    pause_summary,
    projected_stop_time_min,
    split_analysis,
    stationary_pauses,
    swolf_trend,
)
from swim_coach.models import WorkoutLap, WorkoutPause

# --- cardiac_drift -----------------------------------------------------------------


def _series(t_s, hr, speed_mps):
    return {"t_s": t_s, "hr": hr, "speed_mps": speed_mps}


def test_cardiac_drift_from_series_flat_speed_rising_hr():
    # Constant speed both halves; HR 10% higher in the second half -> HR:speed
    # ratio rises ~10% -> drift_pct ~= 10.
    n = 20
    t_s = [float(i * 60) for i in range(n)]  # 20 minutes, 1 sample/min
    speed = [2.0] * n
    hr = [100.0] * (n // 2) + [110.0] * (n // 2)
    drift = cardiac_drift(_series(t_s, hr, speed), laps=[])
    assert drift is not None
    assert drift == pytest.approx(10.0)


def test_cardiac_drift_none_when_no_hr():
    t_s = [0.0, 60.0, 120.0]
    drift = cardiac_drift({"t_s": t_s, "speed_mps": [2.0, 2.0, 2.0]}, laps=[])
    assert drift is None


def test_cardiac_drift_none_when_no_series_and_fewer_than_two_laps_with_hr_and_pace():
    lap = WorkoutLap(index=0, duration_s=600.0, distance_m=1000.0, avg_hr=130)
    assert cardiac_drift(None, laps=[lap]) is None


def test_cardiac_drift_from_laps_when_no_series():
    # Two laps, same pace, HR rises 10% -> drift ~10%.
    lap1 = WorkoutLap(index=0, duration_s=600.0, distance_m=1000.0, avg_hr=100)
    lap2 = WorkoutLap(index=1, duration_s=600.0, distance_m=1000.0, avg_hr=110)
    drift = cardiac_drift(None, laps=[lap1, lap2])
    assert drift is not None
    assert drift == pytest.approx(10.0)


def test_cardiac_drift_excludes_pause_spans_from_series():
    # Without excluding the paused span (constant HR/speed, shouldn't affect
    # the real drift signal), a naive halves-split could get skewed. Here the
    # pause sits entirely in the first "real" half; excluding it should not
    # change the answer versus the no-pause case since the paused samples
    # carry HR values matching their neighbors (drift is still ~10%).
    n = 20
    t_s = [float(i * 60) for i in range(n)]
    speed = [2.0] * n
    hr = [100.0] * (n // 2) + [110.0] * (n // 2)
    pauses = [WorkoutPause(start_offset_s=300.0, duration_s=30.0, source="gap")]
    drift = cardiac_drift(_series(t_s, hr, speed), laps=[], pauses=pauses)
    assert drift == pytest.approx(10.0)


# --- split_analysis ----------------------------------------------------------------


def _lap(index, distance_m, duration_s):
    return WorkoutLap(index=index, distance_m=distance_m, duration_s=duration_s)


def test_split_analysis_negative_split():
    # First half slower (higher pace-per-100m), second half faster.
    laps = [_lap(0, 500, 300.0), _lap(1, 500, 270.0)]  # 60s/100m then 54s/100m
    label, first, second = split_analysis(laps)
    assert label == "negative"
    assert first == pytest.approx(60.0)
    assert second == pytest.approx(54.0)


def test_split_analysis_positive_split():
    laps = [_lap(0, 500, 270.0), _lap(1, 500, 300.0)]
    label, first, second = split_analysis(laps)
    assert label == "positive"


def test_split_analysis_even_split_within_band():
    # ~1% difference, inside the +/-2% band.
    laps = [_lap(0, 1000, 600.0), _lap(1, 1000, 606.0)]
    label, first, second = split_analysis(laps)
    assert label == "even"


def test_split_analysis_none_with_fewer_than_two_laps():
    label, first, second = split_analysis([_lap(0, 500, 300.0)])
    assert label is None
    assert first is None
    assert second is None


# --- pause_summary / projected_stop_time_min ----------------------------------------


def test_pause_summary_totals_and_count():
    pauses = [
        WorkoutPause(start_offset_s=100.0, duration_s=30.0, source="gap"),
        WorkoutPause(start_offset_s=500.0, duration_s=90.0, source="timer"),
    ]
    summary = pause_summary(pauses, elapsed_min=60.0, moving_min=58.0)
    assert summary["pause_count"] == 2
    assert summary["pause_total_min"] == pytest.approx(2.0)
    assert summary["elapsed_min"] == 60.0
    assert summary["moving_min"] == 58.0


def test_pause_summary_empty_pauses():
    summary = pause_summary([], elapsed_min=30.0, moving_min=30.0)
    assert summary["pause_count"] == 0
    assert summary["pause_total_min"] == 0.0


def test_projected_stop_time_min_known_example():
    # 2 min feed every 30 min over 10 hours -> 20 feeds * 2 min = 40.0 min.
    assert projected_stop_time_min(30, 2, 10) == 40.0


def test_projected_stop_time_min_zero_hours():
    assert projected_stop_time_min(30, 2, 0) == 0.0


# --- swolf_trend ---------------------------------------------------------------------


def _length(index, swolf):
    from swim_coach.models import WorkoutLength

    return WorkoutLength(index=index, duration_s=25.0, strokes=10, swolf=swolf)


def test_swolf_trend_degrading():
    # 12 lengths, SWOLF rising steadily -> last quartile worse (higher) than
    # first quartile -> positive degradation_pct.
    lengths = [_length(i, 30.0 + i) for i in range(12)]
    result = swolf_trend(lengths)
    assert result is not None
    first_q, last_q, degradation_pct = result
    assert last_q > first_q
    assert degradation_pct > 0


def test_swolf_trend_none_with_fewer_than_eight_lengths():
    lengths = [_length(i, 30.0) for i in range(7)]
    assert swolf_trend(lengths) is None


def test_swolf_trend_stable_near_zero_degradation():
    lengths = [_length(i, 30.0) for i in range(12)]
    first_q, last_q, degradation_pct = swolf_trend(lengths)
    assert degradation_pct == pytest.approx(0.0)


def test_swolf_trend_excludes_duration_outlier_lengths():
    # A device auto-length-detection miss (one huge "length" among normal
    # ones, like the 1136s length in the real pool fixture) must not poison
    # the last-quartile mean: >3x median duration is excluded.
    from swim_coach.models import WorkoutLength

    lengths = [_length(i, 30.0) for i in range(11)]
    lengths.append(
        WorkoutLength(index=11, duration_s=1136.0, strokes=5, swolf=1141.0)
    )
    first_q, last_q, degradation_pct = swolf_trend(lengths)
    assert last_q == pytest.approx(30.0)
    assert degradation_pct == pytest.approx(0.0)


# --- stationary_pauses ----------------------------------------------------------------


def _speed_series(samples: list[tuple[float, float | None]]) -> dict:
    return {"t_s": [t for t, _ in samples], "speed_mps": [s for _, s in samples]}


def test_stationary_pauses_no_speed_channel_returns_empty():
    assert stationary_pauses({}) == []
    assert stationary_pauses({"t_s": [0, 1], "hr": [100, 101]}) == []


def test_stationary_pauses_span_at_exactly_min_duration_counts():
    # Boundary: a span lasting exactly STATIONARY_MIN_S (30.0s) counts --
    # this function's ">=" convention mirrors the brief's own framing,
    # "sustained >= 30s" (see stationary_pauses' docstring).
    samples = [(0.0, 0.2), (30.0, 2.0), (31.0, 2.0)]
    pauses = stationary_pauses(_speed_series(samples))
    assert len(pauses) == 1
    assert pauses[0].start_offset_s == 0.0
    assert pauses[0].duration_s == pytest.approx(30.0)
    assert pauses[0].source == "stationary"


def test_stationary_pauses_span_one_second_under_floor_does_not_count():
    samples = [(0.0, 0.2), (29.0, 2.0), (30.0, 2.0)]
    assert stationary_pauses(_speed_series(samples)) == []


def test_stationary_pauses_speed_exactly_at_threshold_does_not_count_as_stationary():
    # Boundary: a sample sitting exactly at STATIONARY_SPEED_MPS (0.5 m/s)
    # is still "moving" (strictly-below convention) -- held there for 40s
    # produces no pause at all.
    samples = [(0.0, STATIONARY_SPEED_MPS), (40.0, STATIONARY_SPEED_MPS), (41.0, 2.0)]
    assert stationary_pauses(_speed_series(samples)) == []


def test_stationary_pauses_back_to_back_spans_separated_by_spike_stay_separate():
    samples = [
        (0.0, 0.1), (40.0, 0.1),  # first qualifying span
        (41.0, 2.0),  # brief speed spike -- breaks the span
        (42.0, 0.1), (82.0, 0.1),  # second qualifying span
        (83.0, 2.0),
    ]
    pauses = stationary_pauses(_speed_series(samples))
    assert len(pauses) == 2
    assert pauses[0].start_offset_s == 0.0
    assert pauses[0].duration_s == pytest.approx(41.0)
    assert pauses[1].start_offset_s == 42.0
    assert pauses[1].duration_s == pytest.approx(41.0)


def test_stationary_pauses_none_sample_ends_span_without_assuming_either_way():
    # A None speed sample (a gap in the channel) must not be assumed
    # stationary -- it ends whatever span was in progress, producing two
    # separate pauses rather than one continuous one spanning the gap.
    samples = [(0.0, 0.1), (35.0, None), (36.0, 0.1), (70.0, 2.0)]
    pauses = stationary_pauses(_speed_series(samples))
    assert len(pauses) == 2
    assert pauses[0].duration_s == pytest.approx(35.0)
    assert pauses[1].duration_s == pytest.approx(34.0)


def test_stationary_pauses_trailing_span_at_end_of_series_counts():
    samples = [(0.0, 2.0), (5.0, 0.1), (40.0, 0.1)]
    pauses = stationary_pauses(_speed_series(samples))
    assert len(pauses) == 1
    assert pauses[0].start_offset_s == 5.0
    assert pauses[0].duration_s == pytest.approx(35.0)


# --- constants exist and are the documented values ------------------------------------


def test_constants_have_expected_values():
    assert SPLIT_EVEN_BAND_PCT == 2.0
    assert GAP_THRESHOLD_S == 30.0
    assert CARDIAC_DRIFT_FLAG_PCT == 5.0
    assert STATIONARY_SPEED_MPS == 0.5
    assert STATIONARY_MIN_S == 30.0
