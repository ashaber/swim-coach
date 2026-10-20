"""Per-pass efficiency of a repeated course section: terrain, extra watts, free speed.

Pure functions, no I/O. In a corner or on a descent, speed is not bought with watts: a pass that was
as fast as another on fewer watts shows the saved watts were spent for nothing ("extra watts"). On a
climb or a sprint straight power does buy speed, so efficiency does not apply there.

Constants are Coach judgment, tuned on the 2026-10-18 CX race file (7 laps, 13 sections).
"""

from __future__ import annotations

from statistics import median
from typing import Literal, Mapping, Sequence

from swim_coach.models import FreeSpeed, SectorPass

Terrain = Literal["descent", "climb", "flat"]

TERRAIN_MIN_CHANGE_M = 2.0  # Coach judgment: a barometric altitude change under 2 m across a section is noise, not slope
EFFICIENCY_MIN_DESCENT_S = 10.0  # Coach judgment: a descent shorter than this is a drop, not a stretch to coast and save watts
# "As fast" means within the section's own timing sigma (`section_noise`), not a fixed number of seconds.
FREE_SPEED_MIN_SAVED_W = 30.0  # Coach judgment: under 30 W less is within pass-to-pass variation of a section average
FREE_SPEED_MIN_SECTION_S = 10.0  # Coach judgment: on a section shorter than this the timing sigma is a large share of the time (same minimum as a drill-down piece)
FREE_SPEED_MAX_TOL_S = 0.3  # Coach judgment: "as fast" for free speed never allows more than 0.3 s, whatever the section sigma
FREE_SPEED_MAX = 3  # Coach judgment: the debrief names the three biggest, not every pair


def terrain_of(altitude_change_m: float | None) -> Terrain:
    """Descent / climb from the net altitude change across the section; flat without altitude."""
    if altitude_change_m is None:
        return "flat"
    if altitude_change_m <= -TERRAIN_MIN_CHANGE_M:
        return "descent"
    if altitude_change_m >= TERRAIN_MIN_CHANGE_M:
        return "climb"
    return "flat"


def efficiency_applies(kind: str | None, terrain: Terrain, mean_time_s: float) -> bool:
    """Corner sections, and descents lasting EFFICIENCY_MIN_DESCENT_S or more."""
    return kind == "corners" or (terrain == "descent" and mean_time_s >= EFFICIENCY_MIN_DESCENT_S)


def pass_extras(passes: Sequence[tuple[float, float | None]], tol_s: float) -> list[float | None]:
    """For each `(time_s, power_w)` pass: its power minus the lowest power of any pass at least as
    fast (time within `tol_s`, the section's timing sigma). Never negative; None where the pass has no power."""
    out: list[float | None] = []
    for time_s, power in passes:
        if power is None:
            out.append(None)
            continue
        faster = [p for t, p in passes if p is not None and t <= time_s + tol_s]
        out.append(round(power - min(faster), 1))
    return out


def _best_pair(label: str, passes: Sequence[SectorPass], tol_s: float) -> FreeSpeed | None:
    """The pass that saved the most watts against a pass it matched on time (ties: lowest laps)."""
    best: FreeSpeed | None = None
    for mine in passes:
        for other in passes:
            if mine.lap == other.lap or mine.avg_power_w is None or other.avg_power_w is None:
                continue
            saved = other.avg_power_w - mine.avg_power_w
            if mine.time_s > other.time_s + tol_s or saved < FREE_SPEED_MIN_SAVED_W:
                continue
            if best is None or saved > best.watts_saved or (saved == best.watts_saved and (mine.lap, other.lap) < (best.lap, best.vs_lap)):
                best = FreeSpeed(label=label, lap=mine.lap, time_s=mine.time_s, power_w=mine.avg_power_w, vs_lap=other.lap,
                                 vs_time_s=other.time_s, vs_power_w=other.avg_power_w, watts_saved=round(saved, 1))
    return best


def free_speed(passes_by_label: Mapping[str, Sequence[SectorPass]], tol_by_label: Mapping[str, float]) -> list[FreeSpeed]:
    """Up to FREE_SPEED_MAX free-speed passes, largest `watts_saved` first, one per section. The
    caller passes efficiency sections only."""
    found = [
        pair for label, passes in passes_by_label.items()
        if median(p.time_s for p in passes) >= FREE_SPEED_MIN_SECTION_S
        and (pair := _best_pair(label, passes, min(tol_by_label[label], FREE_SPEED_MAX_TOL_S)))
    ]
    return sorted(found, key=lambda f: -f.watts_saved)[:FREE_SPEED_MAX]
