"""Tests for `swim_coach.race_phases` -- real-race phase-pacing analysis.

Real research grounding this module implements (see its own module
docstring for the full citation list, verified by direct fetch, 2026-09-19
research pass): isolating a race's START phase separately from the rest
(Protzen et al. 2026 -- folding it into "early race" inflates measured
pacing variability ~7x), and a real within-athlete significance floor for
phase-to-phase Normalized Power differences (Mateo-March et al. 2025).
"""

from __future__ import annotations

import pytest

from swim_coach.race_phases import (
    DEFAULT_SIGNIFICANCE_THRESHOLD_PCT,
    DEFAULT_START_PHASE_S,
    phase_difference_is_significant,
    split_race_phases,
)


def _synthetic_series(duration_s: float, power_w: float, n_samples: int = 200) -> dict:
    """A flat-power synthetic series (constant power_w/speed_mps every
    second) -- simple enough that NP == power_w exactly (no variability
    for the rolling-average algorithm to weight), so phase NP values are
    hand-verifiable, not just "it returns something"."""
    step = duration_s / n_samples
    t_s = [round(i * step, 3) for i in range(n_samples + 1)]
    power = [power_w] * len(t_s)
    speed = [5.0] * len(t_s)
    return {"t_s": t_s, "power_w": power, "speed_mps": speed}


class TestSplitRacePhases:
    def test_empty_series_returns_empty_list(self):
        assert split_race_phases(None) == []
        assert split_race_phases({}) == []

    def test_series_with_no_t_s_channel_returns_empty_list(self):
        assert split_race_phases({"power_w": [100, 110, 120]}) == []

    def test_series_shorter_than_start_phase_returns_empty_list(self):
        short = _synthetic_series(duration_s=30, power_w=200, n_samples=10)
        assert split_race_phases(short, start_phase_s=90.0) == []

    def test_splits_into_start_plus_default_three_remaining_phases(self):
        series = _synthetic_series(duration_s=2700, power_w=200)  # 45 min
        phases = split_race_phases(series, start_phase_s=90.0)
        assert len(phases) == 4  # start + 3
        assert phases[0].name == "start"
        assert phases[1].name == "phase_1"
        assert phases[2].name == "phase_2"
        assert phases[3].name == "phase_3"

    def test_start_phase_duration_matches_start_phase_s_argument(self):
        series = _synthetic_series(duration_s=2700, power_w=200)
        phases = split_race_phases(series, start_phase_s=90.0)
        assert phases[0].duration_s == pytest.approx(90.0, abs=1.0)

    def test_remaining_phases_are_roughly_equal_length(self):
        series = _synthetic_series(duration_s=2700, power_w=200)
        phases = split_race_phases(series, start_phase_s=90.0, num_remaining_phases=3)
        remaining = phases[1:]
        durations = [p.duration_s for p in remaining]
        # (2700 - 90) / 3 = 870s each
        for d in durations:
            assert d == pytest.approx(870.0, abs=5.0)

    def test_flat_power_series_gives_exact_np_per_phase(self):
        # Constant power -> NP == that power exactly (no variability for
        # the rolling-average/4th-power algorithm to weight up).
        series = _synthetic_series(duration_s=2700, power_w=250)
        phases = split_race_phases(series, start_phase_s=90.0)
        for phase in phases:
            assert phase.normalized_power_w == pytest.approx(250.0, rel=0.01)

    def test_custom_num_remaining_phases(self):
        series = _synthetic_series(duration_s=3600, power_w=200)
        phases = split_race_phases(series, start_phase_s=90.0, num_remaining_phases=5)
        assert len(phases) == 6  # start + 5
        assert [p.name for p in phases[1:]] == [
            "phase_1", "phase_2", "phase_3", "phase_4", "phase_5",
        ]

    def test_zero_remaining_phases_returns_empty_list(self):
        series = _synthetic_series(duration_s=2700, power_w=200)
        assert split_race_phases(series, start_phase_s=90.0, num_remaining_phases=0) == []

    def test_default_start_phase_s_constant_used_when_not_overridden(self):
        series = _synthetic_series(duration_s=2700, power_w=200)
        explicit = split_race_phases(series, start_phase_s=DEFAULT_START_PHASE_S)
        default = split_race_phases(series)
        assert explicit[0].duration_s == default[0].duration_s

    def test_missing_power_channel_yields_none_np_not_a_crash(self):
        series = {"t_s": [i * 13.5 for i in range(201)]}  # 2700s, no power_w
        phases = split_race_phases(series, start_phase_s=90.0)
        assert len(phases) == 4
        for phase in phases:
            assert phase.normalized_power_w is None

    def test_speed_present_and_averaged_per_phase(self):
        series = _synthetic_series(duration_s=2700, power_w=200)
        phases = split_race_phases(series, start_phase_s=90.0)
        for phase in phases:
            assert phase.avg_speed_mps == pytest.approx(5.0, rel=0.01)


class TestPhaseDifferenceIsSignificant:
    def test_large_difference_is_significant(self):
        # 250 -> 200 is a 20% drop, well above the 5% default floor.
        assert phase_difference_is_significant(250.0, 200.0) is True

    def test_small_difference_is_not_significant(self):
        # 250 -> 248 is 0.8%, below the 5% default floor -- normal
        # within-athlete variation per Mateo-March et al. (2025).
        assert phase_difference_is_significant(250.0, 248.0) is False

    def test_exactly_at_default_threshold_counts_as_significant(self):
        # 200 -> 210 is exactly 5%.
        assert phase_difference_is_significant(200.0, 210.0) is True

    def test_custom_threshold_pct(self):
        # 200 -> 204 is 2% -- not significant at the default 5% floor,
        # but IS significant at a tighter 1% floor.
        assert phase_difference_is_significant(200.0, 204.0, threshold_pct=5.0) is False
        assert phase_difference_is_significant(200.0, 204.0, threshold_pct=1.0) is True

    def test_none_inputs_return_none_not_false(self):
        # Missing data must not silently read as "not significant" --
        # that's a real, different claim than "genuinely unknown".
        assert phase_difference_is_significant(None, 200.0) is None
        assert phase_difference_is_significant(200.0, None) is None
        assert phase_difference_is_significant(None, None) is None

    def test_zero_baseline_returns_none_not_a_crash(self):
        assert phase_difference_is_significant(0.0, 200.0) is None

    def test_default_significance_threshold_constant_value(self):
        # Pin the real, cited value -- Mateo-March et al. (2025).
        assert DEFAULT_SIGNIFICANCE_THRESHOLD_PCT == 5.0
