"""Timing noise of the course-section edges, estimated from the laps themselves.

Each section edge is read from 1 Hz GPS by position, so every lap's edge time carries some jitter. A
late edge makes one section longer and the NEXT one shorter, so the lap-to-lap deviations of adjacent
sections are negatively correlated, and -cov(d_k, d_k+1) is the variance of the shared edge. (Real
lap-to-lap variation is independent between neighbouring sections, so it adds nothing to that
covariance.) A section's timing sigma is sqrt(sigma_in^2 + sigma_out^2); the lap start/end edges are the
canonical lap edges; the lap mark's own jitter is read the same way across consecutive laps.

Loss vs. the best pass is biased upward by noise alone: with n laps the expected mean-minus-minimum of
pure noise is e_n * sigma, e_n the expected maximum of n standard normals. A section is only a finding
when its loss clears that floor.

Constants are Coach judgment except `_EXPECTED_MAX_NORMAL` (Harter 1961, expected values of normal order statistics).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

FALLBACK_EDGE_NOISE_S = 0.3  # Coach judgment: measured edge sigma on the 2026-10-18 CX race (0.29 s) when the laps are too few to estimate it
MIN_MARK_PAIRS = 3  # Coach judgment: the lap-mark covariance needs this many consecutive lap pairs, else the pooled edge sigma stands in
MIN_LAPS_FOR_NOISE = 4  # Coach judgment: a covariance from fewer laps is not an estimate
EDGE_SIGNIFICANCE = 2.0  # Coach judgment: a per-edge estimate is used when it is this many standard errors above zero

# E[max of n standard normals] = E[mean - min]: Harter (1961), n = 1..12
_EXPECTED_MAX_NORMAL = (0.0, 0.0, 0.5642, 0.8463, 1.0294, 1.1630, 1.2672, 1.3522, 1.4236, 1.4850, 1.5388, 1.5864, 1.6292)


def expected_max_normal(n: int) -> float:
    if n < len(_EXPECTED_MAX_NORMAL):
        return _EXPECTED_MAX_NORMAL[max(n, 0)]
    return math.sqrt(2 * math.log(n)) - (math.log(math.log(n)) + math.log(4 * math.pi)) / (2 * math.sqrt(2 * math.log(n)))


def loss_noise_floor(sigma_s: float, n_laps: int) -> float:
    """The mean loss vs. the best pass that timing noise alone produces."""
    return expected_max_normal(n_laps) * sigma_s


@dataclass(frozen=True)
class SectionNoise:
    edge_s: list[float]  # sigma of each of the m+1 edges (first and last: the lap mark)
    pooled_edge_s: float
    section_s: list[float]  # sigma of each section's time


def _from_edges(edge_s: list[float], pooled: float) -> SectionNoise:
    sections = [math.hypot(edge_s[k], edge_s[k + 1]) for k in range(len(edge_s) - 1)]
    return SectionNoise(edge_s=edge_s, pooled_edge_s=pooled, section_s=sections)


def _mark_sigma(rows: Sequence[Sequence[float]], chain: Sequence[bool], pooled: float) -> float:
    """Sigma of the lap-mark edge: it ends one lap and starts the next, so a late mark lengthens the
    last section of lap l and shortens the first of lap l+1 (same covariance trick, across laps)."""
    n, m = len(rows), len(rows[0])
    means = [sum(r[k] for r in rows) / n for k in (0, m - 1)]
    prods = [(rows[l][m - 1] - means[1]) * (rows[l + 1][0] - means[0]) for l in range(n - 1) if chain[l]]
    if len(prods) < MIN_MARK_PAIRS:
        return pooled
    return math.sqrt(max(-sum(prods) / (len(prods) - 1), 0.0))


def section_sigmas(all_times_by_lap: Sequence[Sequence[float]], skip: int | None = None, chain: Sequence[bool] | None = None) -> SectionNoise:
    """Edge and section timing sigmas from `times_by_lap[lap][section]` (seconds). `skip`: the row of
    the REFERENCE lap, left out of the interior estimate -- its section edges are defined by its own
    sample times, so it carries no alignment jitter and would understate the noise the other laps
    have. `chain[l]`: lap l+1 starts where lap l ends (their shared lap mark has its own jitter)."""
    times_by_lap = [row for i, row in enumerate(all_times_by_lap) if i != skip]
    n = len(times_by_lap)
    m = len(times_by_lap[0]) if n else 0
    interior = max(m - 1, 0)
    if n < MIN_LAPS_FOR_NOISE or m < 2:
        return _from_edges([FALLBACK_EDGE_NOISE_S] + [FALLBACK_EDGE_NOISE_S] * interior + [FALLBACK_EDGE_NOISE_S], FALLBACK_EDGE_NOISE_S)
    means = [sum(row[k] for row in times_by_lap) / n for k in range(m)]
    dev = [[row[k] - means[k] for k in range(m)] for row in times_by_lap]
    var_est, sig = [], []
    for j in range(1, m):
        prods = [d[j - 1] * d[j] for d in dev]
        cov = sum(prods) / (n - 1)
        se = math.sqrt(sum((p - sum(prods) / n) ** 2 for p in prods) / (n - 1) / n)
        var_est.append(-cov)
        sig.append(se)
    pooled = math.sqrt(max(sum(var_est) / len(var_est), 0.0))
    edge = [math.sqrt(v) if v > 0 and v > EDGE_SIGNIFICANCE * s else pooled for v, s in zip(var_est, sig)]
    mark = _mark_sigma(all_times_by_lap, chain, pooled) if chain is not None else 0.0
    return _from_edges([mark, *edge, mark], pooled)
