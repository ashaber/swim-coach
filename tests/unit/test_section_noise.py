"""Timing noise of the section edges, estimated from the laps themselves."""

from __future__ import annotations

import random

import pytest

from swim_coach.section_noise import (
    FALLBACK_EDGE_NOISE_S,
    MIN_LAPS_FOR_NOISE,
    expected_max_normal,
    loss_noise_floor,
    section_sigmas,
)


def _laps_with_jitter(n_laps: int, true_s: list[float], sigma: float, seed: int = 7, quiet_edges: dict[int, float] | None = None) -> list[list[float]]:
    """Section times of `n_laps` laps whose interior edges are late/early by N(0, sigma) -- a late edge
    lengthens one section and shortens the next, exactly what a misplaced edge does."""
    rng = random.Random(seed)
    m = len(true_s)
    rows = []
    for _ in range(n_laps):
        jitter = [0.0] + [rng.gauss(0, (quiet_edges or {}).get(j, sigma)) for j in range(1, m)] + [0.0]
        rows.append([true_s[k] + jitter[k + 1] - jitter[k] for k in range(m)])
    return rows


def test_estimator_recovers_the_edge_jitter_that_went_in() -> None:
    rows = _laps_with_jitter(60, [10.0] * 9, 0.4)
    noise = section_sigmas(rows)
    assert noise.pooled_edge_s == pytest.approx(0.4, abs=0.08)
    # interior section: two noisy edges; first/last section: one noisy edge (lap edges are fixed)
    assert noise.section_s[4] == pytest.approx(0.4 * 2 ** 0.5, abs=0.15)
    assert noise.section_s[0] == pytest.approx(0.4, abs=0.12)


def test_a_significantly_noisier_edge_gets_its_own_estimate() -> None:
    rows = _laps_with_jitter(80, [10.0] * 8, 0.2, quiet_edges={4: 0.8})
    noise = section_sigmas(rows)
    assert noise.edge_s[4] == pytest.approx(0.8, abs=0.2)
    assert noise.edge_s[2] == pytest.approx(noise.pooled_edge_s, abs=1e-9) or noise.edge_s[2] < 0.4
    assert noise.section_s[3] > noise.section_s[1]


def test_too_few_laps_fall_back_to_the_constant() -> None:
    rows = _laps_with_jitter(MIN_LAPS_FOR_NOISE - 1, [10.0] * 5, 0.9)
    noise = section_sigmas(rows)
    assert noise.pooled_edge_s == FALLBACK_EDGE_NOISE_S
    assert noise.section_s[2] == pytest.approx(FALLBACK_EDGE_NOISE_S * 2 ** 0.5)


def test_expected_max_normal_matches_the_order_statistic_tables() -> None:
    assert expected_max_normal(7) == pytest.approx(1.352, abs=0.002)
    assert expected_max_normal(2) == pytest.approx(0.564, abs=0.002)
    assert expected_max_normal(1) == 0.0


def test_noise_floor_is_the_expected_mean_loss_of_pure_noise() -> None:
    assert loss_noise_floor(0.5, 7) == pytest.approx(0.5 * 1.352, abs=0.002)


def test_the_reference_lap_is_left_out_of_the_estimate() -> None:
    # The reference lap's edges are its own sample times: no jitter at all. Counting it dilutes the estimate.
    rows = _laps_with_jitter(7, [10.0] * 9, 0.4, seed=3)
    with_ref = [[10.0] * 9, *rows]
    assert section_sigmas(with_ref, skip=0).pooled_edge_s == section_sigmas(rows).pooled_edge_s
    assert section_sigmas(with_ref).pooled_edge_s != section_sigmas(rows).pooled_edge_s
