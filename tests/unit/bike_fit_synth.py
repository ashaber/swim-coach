"""Synthetic bike geometry: a known bike in a level frame -> the tape distances a person would read."""

from __future__ import annotations

import math
from dataclasses import dataclass

from swim_coach.models import BikeFitInputs, BikeFitTape


@dataclass(frozen=True)
class Truth:
    """A bike in a LEVEL frame: x forward, y up, BB at the origin, mm. `floor_y` is the floor."""

    bike_type: str
    ra: tuple[float, float]
    fa: tuple[float, float]
    bc: tuple[float, float]
    st: tuple[float, float]
    h: tuple[float, float]
    s: tuple[float, float]
    floor_y: float
    tilt_deg: float = 0.0
    saddle_len: float = 270.0
    string_len: float = 420.0
    lat_bb: float = 60.0
    lat_fa: float = 50.0
    lat_ra: float = 71.0


CX = Truth("drop_bar", ra=(-419, 72), fa=(601, 64), bc=(480, 640), st=(-5, 705), h=(560, 650),
           s=(-140, 703), floor_y=-268)
MTB = Truth("mtb", ra=(-445, 40), fa=(645, 60), bc=(540, 660), st=(-90, 720), h=(600, 700),
            s=(-222, 714), floor_y=-330, tilt_deg=2.0, saddle_len=265, string_len=780, lat_bb=70, lat_fa=55, lat_ra=74)


def _d(p, q, lp, lq) -> float:
    return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (lp - lq) ** 2)


def tapes_for(t: Truth) -> dict[str, float]:
    bb = (0.0, 0.0)
    return {
        "bb_fa": _d(bb, t.fa, t.lat_bb, t.lat_fa),
        "bb_bc": _d(bb, t.bc, t.lat_bb, 0),
        "fa_bc": _d(t.fa, t.bc, t.lat_fa, 0),
        "bb_st": _d(bb, t.st, t.lat_bb, 0),
        "bc_st": _d(t.bc, t.st, 0, 0),
        "bb_s": _d(bb, t.s, t.lat_bb, 0),
        "bc_s": _d(t.bc, t.s, 0, 0),
        "ra_bb": _d(t.ra, bb, t.lat_ra, t.lat_bb),
        "ra_st": _d(t.ra, t.st, t.lat_ra, 0),
        "bb_h": _d(bb, t.h, t.lat_bb, 0),
        "st_h": _d(t.st, t.h, 0, 0),
        "bc_h": _d(t.bc, t.h, 0, 0),
        "fa_h": _d(t.fa, t.h, t.lat_fa, 0),
        "ra_bc": _d(t.ra, t.bc, t.lat_ra, 0),
        "ra_s": _d(t.ra, t.s, t.lat_ra, 0),
        "ra_fa": _d(t.ra, t.fa, t.lat_ra, t.lat_fa),
        "floor_fa": t.fa[1] - t.floor_y,
        "floor_ra": t.ra[1] - t.floor_y,
    }


def inputs_for(t: Truth, **over) -> BikeFitInputs:
    tape = {**tapes_for(t), **over.pop("tape", {})}
    fields = dict(
        tape=BikeFitTape(**tape), sit_point_from_tip_mm=_d(t.st, t.s, 0, 0), saddle_model="Test saddle",
        saddle_tilt_deg=t.tilt_deg, saddle_length_mm=t.saddle_len,
        crank_length_mm=172.5, string_length_mm=t.string_len,
        crank_bolt_width_mm=2 * t.lat_bb, front_axle_width_mm=2 * t.lat_fa, rear_axle_width_mm=2 * t.lat_ra,
    )
    return BikeFitInputs(**{**fields, **over})
