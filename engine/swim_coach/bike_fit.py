"""Bike geometry from tape distances: a measuring and comparison tool, never a fit prescription.

The athlete measures straight-line distances between marked points on the bike's LEFT side; the
engine turns them into positions by trilateration, so nothing depends on the bike being level or
on an ambiguous definition. Sides are fixed from the known bike layout (never guessed): FA forward
of BB, BC and ST above, RA behind, H forward of ST. No real solution -> `BikeFitError`.

Points (mm; BB origin):
  BB  center of the left crank bolt (outer face)   FA  center of the left front axle end
  RA  center of the left rear axle end             BC  bar clamp, where the stem clamps the bar, on the centerline
  ST  saddle tip, on the centerline
  S   sit-bone point: a tape mark on the saddle's top centerline at `sit_point_from_tip_mm` from the tip
        (no standard exists for the location: use the fitter's)
  H   hand point: the midpoint of a string stretched between the
        left and right contact points (drop bar: top center of each hood where the palm sits; MTB: center of
        each grip where the palm sits), so it lies on the centerline and has no lateral offset

Ground direction comes from the axle line (RA to FA) corrected by the floor-to-axle height
difference (unequal wheel radius). Every constant below rests on `library/47-bike-fit-measurement.md`
(`Coach judgment:`); that file is the method statement and the limits. There are no fit targets
anywhere in this module. The saddle midpoint of earlier versions is gone: every saddle figure uses
the measured S, because saddles are concave and a point computed along a tilt line is not on the
surface. Saddle tilt and saddle length are recorded only.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel

from swim_coach.models import BikeFitInputs, BikeFitSnapshot, BikeType

# Source: library/47-bike-fit-measurement.md -- every constant in this block is coach
# judgment, stated there, and editable here.
TAPE_SIGMA_MM = 1.0  # assumed 1 standard deviation of one tape or floor-height reading
# A check's |computed minus measured| warns at max(CLOSURE_WARN_MM, CLOSURE_WARN_SIGMA x its own
# expected sd) and is flagged "likely bad" beyond max(CLOSURE_BAD_MM, CLOSURE_BAD_SIGMA x sd): the
# sd of the FA-H check at 1 mm tape error is about 2.5 mm, so a flat 3 / 6 mm would false-alarm
# often. Never rejects. False-alarm rates at 1 mm tape error are in library 47.
CLOSURE_WARN_MM = 3.0
CLOSURE_BAD_MM = 6.0
CLOSURE_WARN_SIGMA = 2.5
CLOSURE_BAD_SIGMA = 4.0
TILT_ADVISORY_DEG = 4.0  # |net saddle tilt| above this shows a neutral "check the measurement" note; library 47, Coach judgment
PEDAL_STACK_SIGMA_MM = 3.0  # stated assumption, per snapshot, independent of tape error: library 47, Coach judgment
COMPARE_SIGMA_FACTOR = 2.0  # a difference is "beyond error" past 2 x its combined 1-sigma
JACOBIAN_STEP_MM = 0.01  # central-difference step for error propagation (deterministic)
DEPENDS_MIN = 0.05  # |d output / d tape| (per mm) at or above which an output "depends on" a tape
SUSPECT_MIN_FIT = 0.9  # cosine between the failed-check pattern and a tape's pattern to name it a suspect
SUSPECT_MIN_NORM = 0.3  # a tape must move the checks at least this much per mm to be named
MAX_SUSPECTS = 4
WIDTH_ERROR_MM = 5.0  # stated width error used for the lateral-assumption note

# Source: library/47-bike-fit-measurement.md. Widths, mm, measured end to end across the bike;
# each lateral offset from the centerline is half the width. These are FALLBACK ASSUMPTIONS used
# only when a width is blank: crank bolt face to face (a labelled default), and the nominal hub
# widths (drop bar 100/142, boost MTB 110/148).
WIDTH_DEFAULTS_MM: dict[str, dict[str, float]] = {
    "drop_bar": {"crank": 120.0, "fa": 100.0, "ra": 142.0},
    "mtb": {"crank": 140.0, "fa": 110.0, "ra": 148.0},
}

LIMITS_STATEMENT = (
    "This records and compares bike geometry. It does not recommend fit changes, give medical "
    "advice, or state target angles; take changes to a fitter, and report pain through the normal "
    "stop-and-assess rule. The +/- is one standard deviation of tape and floor-height reading "
    f"error only (assumed {TAPE_SIGMA_MM:g} mm each): saddle tilt and length (recorded only), crank "
    "length, the sit-bone mark distance and any width left blank are taken as entered or assumed. "
    "Outputs are reference points on the bike, not body positions; no standard exists for the "
    "sit-bone location, so use your fitter's and keep it consistent. Only the hand point on the "
    "hoods or grips is measured; the drops are out of scope for now."
)

CHECKS_NOT_COVERED = (
    "The six checks cannot see the floor heights, saddle tilt, saddle length, crank length, "
    "string length or the three widths, or errors that happen to cancel."
)

SEATED_ASSUMPTION = (
    "Seated results rotate the unweighted bike about the BB by the change in the BB-to-BC line "
    "angle between the unweighted and seated floor heights. The BB, BC, saddle and hand points are "
    "treated as one rigid front triangle; fork compression and any rear-suspension geometry change "
    "are not modelled."
)

FRAME_STACK_REACH_NOTE = (
    "Bar stack and reach are measured at the bar clamp and hand reach and drop at the hand point H. "
    "Frame stack and reach are defined at the head tube top, which is not measured here; the maker's "
    "figures, if entered, are recorded only."
)

PEDAL_STACK_NOTE = (
    "Pedal stack (pedal axle center to shoe sole, shoe clipped in) is hard to measure and its "
    "accuracy is limited. The same shoes cancel out between bikes, so only the pedal difference "
    f"matters. The uncertainty shown is a stated assumption of {PEDAL_STACK_SIGMA_MM:g} mm per "
    "snapshot, independent of tape error. No shoe or cleat fields are recorded."
)

COMPARE_SETBACK_NOTE = (
    "Compare sit-point setback, not saddle rail position: the seat tube angle differs between bikes, "
    "so the same rail position gives a different setback."
)

MTB_UNWEIGHTED_NOTE = (
    "Unweighted numbers only: rear sag normally rotates the frame back, so unweighted numbers "
    "may understate how upright he actually rides this bike. Add the seated floor heights "
    "(helper needed) to see the orientation under load."
)

MEASURE_LABELS: dict[str, str] = {
    "bb_fa": "BB-FA", "bb_bc": "BB-BC", "fa_bc": "FA-BC", "bb_st": "BB-ST", "bc_st": "BC-ST",
    "bb_s": "BB-S", "bc_s": "BC-S", "ra_s": "RA-S", "sit_tip": "tip-to-S mark",
    "ra_bb": "RA-BB", "ra_st": "RA-ST", "bb_h": "BB-H", "st_h": "ST-H", "bc_h": "BC-H",
    "ra_fa": "RA-FA", "fa_h": "FA-H", "ra_bc": "RA-BC",
    "floor_fa": "floor to FA", "floor_ra": "floor to RA",
    "seat_bb": "seated floor to BB", "seat_bc": "seated floor to BC",
}
_TAPE_DIST_KEYS = ["bb_fa", "bb_bc", "fa_bc", "bb_st", "bc_st", "bb_s", "bc_s", "ra_bb", "ra_st", "bb_h", "st_h",
                   "bc_h", "ra_fa", "fa_h", "ra_bc", "ra_s"]
_TAPE_KEYS = _TAPE_DIST_KEYS + ["floor_fa", "floor_ra"]
# Entered readings that can be named as a suspect: the tapes plus the tip-to-S mark distance.
_DIST_KEYS = _TAPE_DIST_KEYS + ["sit_tip"]
_BASE_KEYS = _TAPE_KEYS + ["sit_tip"]
# The checks: five tapes compared with the solved geometry instead of used to build it, plus the
# solved tip-to-S straight line against the entered mark distance (no tape added). RA-S exists
# because BB-S is almost the saddle height itself: a BB-S typo barely moves the tip-to-S line.
CHECK_KEYS = ["ra_fa", "fa_h", "ra_bc", "bc_h", "ra_s", "tip_s"]
CHECK_LABELS = {"ra_fa": "RA-FA (wheelbase)", "fa_h": "FA-H", "ra_bc": "RA-BC", "bc_h": "BC-H", "ra_s": "RA-S",
                "tip_s": "ST-S vs entered mark distance"}

# key -> (label, unit, definition). Order is display order.
OUTPUT_SPECS: dict[str, tuple[str, str, str]] = {
    "setback_tip_mm": ("Saddle setback, tip", "mm",
                       "Horizontal distance from the BB back to the saddle tip (ST); positive is behind the BB. "
                       "Fitters quote setback from the nose, so it stays alongside the sit-point figure."),
    "setback_sit_mm": ("Saddle setback, sit point", "mm",
                       "Horizontal distance from the BB back to the measured sit-bone point (S); positive is behind "
                       "the BB. This, not saddle rail position, is what compares bikes."),
    "saddle_height_mm": ("Saddle height, BB to sit point (straight line)", "mm",
                         "Straight-line distance from the BB center to the measured sit-bone point (S). The seat "
                         "tube is not measured, so this is not a height along the seat tube."),
    "sit_to_pedal_down_mm": ("Sit point to pedal axle, crank down on the seat line", "mm",
                             "Geometric value, not leg extension: saddle height plus crank length, i.e. the distance "
                             "from the sit-bone point to the pedal axle with the crank pointing down along the "
                             "line from S through the BB. Pedal stack is not included."),
    "sit_to_pedal_up_mm": ("Sit point to pedal axle, crank up on the seat line", "mm",
                           "Geometric value, not leg clearance: saddle height minus crank length, i.e. the distance "
                           "from the sit-bone point to the pedal axle with the crank pointing up along the "
                           "line from the BB to S. Pedal stack is not included."),
    "saddle_tip_height_mm": ("Saddle tip height above BB", "mm", "Vertical height of the saddle tip (ST) above the BB."),
    "effective_seat_angle_deg": ("Effective seat angle", "deg",
                                 "Angle of the line from the BB to the sit-bone point (S), from horizontal, "
                                 "measured behind the BB. A measured value, not a target."),
    "reach_bc_mm": ("Bar reach (at clamp)", "mm",
                    "Horizontal distance from the BB forward to the bar clamp (BC). Not frame reach, which is "
                    "defined at the head tube top."),
    "reach_hand_mm": ("Hand reach (at H)", "mm", "Horizontal distance from the BB forward to the hand point (H), not the clamp."),
    "stack_bc_mm": ("Bar stack (at clamp)", "mm",
                    "Vertical height of the bar clamp (BC) above the BB. Not frame stack, which is defined at the "
                    "head tube top."),
    "stack_hand_mm": ("Hand drop (at H), height above BB", "mm",
                      "Vertical height of the hand point (H) above the BB, not the clamp."),
    "clamp_to_hands_horizontal_mm": ("Clamp to hands, horizontal", "mm",
                                     "Horizontal distance from the bar clamp (BC) forward to the hand point (H), "
                                     "relative to the ground; negative means the hands are behind the clamp."),
    "clamp_to_hands_vertical_mm": ("Clamp to hands, vertical", "mm",
                                   "Vertical distance from the bar clamp (BC) up to the hand point (H), relative to "
                                   "the ground; negative means the hands are below the clamp."),
    "clamp_to_hands_mm": ("Clamp to hands, straight line", "mm",
                          "Straight-line distance from the bar clamp (BC) to the hand point (H): the effective reach "
                          "from clamp to hands, including bar sweep and hood offset."),
    "saddle_to_hand_reach_mm": ("Saddle-to-hand reach", "mm",
                                "Horizontal distance from the sit-bone point (S) forward to the hand point."),
    "saddle_to_hand_drop_mm": ("Saddle-to-hand drop", "mm",
                               "Vertical drop from the sit-bone point (S) down to the hand point; negative means "
                               "the hand is higher than the sit point."),
    "bb_to_hand_mm": ("BB to hand", "mm", "Straight-line distance from the BB to the hand point."),
    "wheelbase_mm": ("Wheelbase", "mm",
                     "Measured RA-FA distance, with the lateral gap removed, projected onto the ground."),
    "bb_drop_mm": ("BB drop", "mm",
                   "How far the BB sits below the line through the two axle centers, vertically at the BB's position."),
}
_SEATED_KEYS_OUT = [k for k in OUTPUT_SPECS if k not in ("wheelbase_mm", "bb_drop_mm")]


class BikeFitError(ValueError):
    """The measurements cannot describe a real bike (or a tape is shorter than its lateral gap)."""


class FitValue(BaseModel):
    key: str
    label: str
    unit: str
    value: float
    sigma: float
    definition: str
    depends_on: list[str]  # tape measures this output is sensitive to (MEASURE_LABELS keys)


class Suspect(BaseModel):
    """A hint only: the tape whose error would best explain which checks failed."""

    measure: str
    label: str
    estimated_error_mm: float  # how far off that tape would have to be to explain the residuals
    fit: float  # 0..1 agreement between the failed-check pattern and that tape's pattern


class CheckResult(BaseModel):
    key: str
    label: str
    computed_mm: float
    measured_mm: float
    residual_mm: float  # computed minus measured
    sigma_mm: float  # expected sd of this residual from tape error alone
    warn_mm: float
    bad_mm: float
    status: Literal["ok", "warn", "bad"]


class Closure(BaseModel):
    status: Literal["ok", "warn", "bad"]  # the worst of the four checks
    checks: list[CheckResult]
    message: str
    not_checked: str
    suspects: list[Suspect]
    affected_outputs: list[str]


class SeatedResult(BaseModel):
    rotation_deg: float
    rotation_sigma_deg: float
    assumption: str
    outputs: list[FitValue]
    points: dict[str, list[float]]  # seated level-frame points, BB origin (for drawing only)


class Coordinate(BaseModel):
    key: str
    label: str
    x: float  # forward of the BB
    y: float  # above the BB
    sigma_x: float
    sigma_y: float


class FitResult(BaseModel):
    bike_type: str
    outputs: list[FitValue]
    points: dict[str, list[float]]  # level-frame points, BB origin, x forward / y up (for drawing only)
    coordinates: list[Coordinate]  # standard BB-origin X/Y: saddle tip, S, bar clamp, hand point
    recorded: dict  # entered values that move no output (saddle, frame, pedal stack, crank)
    tilt_deg: float  # saddle reading minus the floor reading (nose up positive); recorded, advisory only
    axle_heights_mm: dict[str, float]  # floor to FA / RA axle center, as entered (about the wheel radius)
    seated: SeatedResult | None
    closure: Closure
    ground_pitch_deg: float  # axle line vs level ground implied by the wheel-radius difference
    radius_difference_mm: float  # floor-to-FA minus floor-to-RA
    assumptions: dict
    lateral_effect: dict
    constants: dict
    notes: list[str]
    limits: str


class CompareRow(BaseModel):
    key: str
    label: str
    unit: str
    a: float
    b: float
    diff: float  # b minus a
    sigma_a: float
    sigma_b: float
    sigma_diff: float
    exceeds_error: bool


class SaddleCompare(BaseModel):
    model_a: str
    model_b: str
    same: bool  # compared ignoring case and surrounding space


class CrankCompare(BaseModel):
    a_mm: float
    b_mm: float
    diff_mm: float  # b minus a
    pedal_down_effect_mm: float  # the crank-length part of the change in sit point to pedal, crank down
    pedal_up_effect_mm: float  # the crank-length part of the change in sit point to pedal, crank up


class PedalStackCompare(BaseModel):
    a_mm: float
    b_mm: float
    diff_mm: float  # b minus a
    adjusted_pedal_down_diff_mm: float  # sit point to pedal, crank down, difference plus the stack difference
    sigma_each_mm: float
    sigma_diff_mm: float
    exceeds_error: bool
    note: str


class Comparison(BaseModel):
    factor: float
    saddle: SaddleCompare
    crank: CrankCompare
    pedal_stack: PedalStackCompare | None
    unweighted: list[CompareRow]
    seated: list[CompareRow] | None
    notes: list[str]


def _lateral(inputs: BikeFitInputs, bike_type: str) -> dict:
    """Lateral offsets from the centerline: half of each measured width, else the labelled fallback."""
    d = WIDTH_DEFAULTS_MM[bike_type]
    given = {"crank": inputs.crank_bolt_width_mm, "fa": inputs.front_axle_width_mm, "ra": inputs.rear_axle_width_mm}
    widths = {k: (given[k] if given[k] is not None else d[k]) for k in d}
    return {
        "bb_mm": widths["crank"] / 2, "fa_mm": widths["fa"] / 2, "ra_mm": widths["ra"] / 2,
        "widths_mm": {"crank_bolt": widths["crank"], "front_axle": widths["fa"], "rear_axle": widths["ra"]},
        "defaulted": [k for k in d if given[k] is None],
        "note": "Each lateral offset is half the measured width between the left and right faces. "
                "Widths left blank use the bike-type fallback and are flagged. The hand point H is the "
                "midpoint of the string, on the centerline, so it has no lateral offset.",
    }


def _planar(tape: float, lat_a: float, lat_b: float, name: str) -> float:
    gap = lat_a - lat_b
    if tape <= abs(gap):
        raise BikeFitError(
            f"{name} ({tape:g} mm) is not longer than the lateral gap between its points ({abs(gap):g} mm); "
            "recheck the measurement or the widths"
        )
    return math.sqrt(tape * tape - gap * gap)


def _circles(p0: tuple[float, float], r0: float, p1: tuple[float, float], r1: float,
             names: str, side: Literal["left", "right"]) -> tuple[float, float]:
    """The intersection of two circles on the given side of the line p0 -> p1."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    d = math.hypot(dx, dy)
    if d == 0:
        raise BikeFitError(f"{names}: the two reference points coincide")
    a = (r0 * r0 - r1 * r1 + d * d) / (2 * d)
    h2 = r0 * r0 - a * a
    if h2 < 0:
        raise BikeFitError(
            f"{names} cannot form a triangle (the longest side is longer than the other two together); "
            "recheck those tape measures"
        )
    h = math.sqrt(h2) * (1 if side == "left" else -1)
    ex, ey = dx / d, dy / d
    return (p0[0] + a * ex - h * ey, p0[1] + a * ey + h * ex)


def _rot(p: tuple[float, float], ang: float) -> tuple[float, float]:
    c, s = math.cos(ang), math.sin(ang)
    return (p[0] * c - p[1] * s, p[0] * s + p[1] * c)


def _positions(p: dict[str, float], lat: dict) -> dict:
    """Level-frame points (x forward, y up, BB origin) plus the ground pitch, from a tape vector."""
    b, f, r = lat["bb_mm"], lat["fa_mm"], lat["ra_mm"]
    d = {
        "bb_fa": _planar(p["bb_fa"], b, f, "BB-FA"),
        "bb_bc": _planar(p["bb_bc"], b, 0.0, "BB-BC"),
        "fa_bc": _planar(p["fa_bc"], f, 0.0, "FA-BC"),
        "bb_st": _planar(p["bb_st"], b, 0.0, "BB-ST"),
        "bc_st": _planar(p["bc_st"], 0.0, 0.0, "BC-ST"),
        "bb_s": _planar(p["bb_s"], b, 0.0, "BB-S"),
        "bc_s": _planar(p["bc_s"], 0.0, 0.0, "BC-S"),
        "ra_bb": _planar(p["ra_bb"], r, b, "RA-BB"),
        "ra_st": _planar(p["ra_st"], r, 0.0, "RA-ST"),
        "bb_h": _planar(p["bb_h"], b, 0.0, "BB-H"),
        "st_h": _planar(p["st_h"], 0.0, 0.0, "ST-H"),
        "bc_h": _planar(p["bc_h"], 0.0, 0.0, "BC-H"),
        "ra_fa": _planar(p["ra_fa"], r, f, "RA-FA"),
        "fa_h": _planar(p["fa_h"], f, 0.0, "FA-H"),
        "ra_bc": _planar(p["ra_bc"], r, 0.0, "RA-BC"),
        "ra_s": _planar(p["ra_s"], r, 0.0, "RA-S"),
    }
    bb = (0.0, 0.0)
    fa = (d["bb_fa"], 0.0)
    bc = _circles(bb, d["bb_bc"], fa, d["fa_bc"], "BB-FA, BB-BC and FA-BC", "left")
    st = _circles(bb, d["bb_st"], bc, d["bc_st"], "BB-BC, BB-ST and BC-ST", "left")
    s = _circles(bb, d["bb_s"], bc, d["bc_s"], "BB-BC, BB-S and BC-S", "left")
    ra = _circles(bb, d["ra_bb"], st, d["ra_st"], "BB-ST, RA-BB and RA-ST", "left")
    h = _circles(bb, d["bb_h"], st, d["st_h"], "BB-ST, BB-H and ST-H", "right")
    vx, vy = fa[0] - ra[0], fa[1] - ra[1]
    length = math.hypot(vx, vy)
    rise = p["floor_fa"] - p["floor_ra"]
    if length == 0 or abs(rise) >= length:
        raise BikeFitError("the axle heights are inconsistent with the solved wheelbase; recheck RA-FA and the floor heights")
    pitch = math.asin(rise / length)
    ang = math.atan2(vy, vx) - pitch  # the frame angle of "level forward"
    pts = {n: _rot(q, -ang) for n, q in (("bb", bb), ("fa", fa), ("ra", ra), ("bc", bc), ("st", st), ("s", s), ("h", h))}
    computed = {
        "ra_fa": length, "fa_h": math.dist(fa, h), "ra_bc": math.dist(ra, bc), "bc_h": math.dist(bc, h),
        "ra_s": math.dist(ra, s), "tip_s": math.dist(st, s),
    }
    d["tip_s"] = p["sit_tip"]  # entered along the saddle top; compared with the solved straight line
    return {"pts": pts, "pitch": pitch, "d": d, "computed": computed}


def _metrics(pts: dict, crank_mm: float) -> dict[str, float]:
    st, srp, bc, h = pts["st"], pts["s"], pts["bc"], pts["h"]
    height = math.hypot(*srp)
    return {
        "setback_tip_mm": -st[0],
        "setback_sit_mm": -srp[0],
        "saddle_height_mm": height,
        "sit_to_pedal_down_mm": height + crank_mm,
        "sit_to_pedal_up_mm": height - crank_mm,
        "saddle_tip_height_mm": st[1],
        "effective_seat_angle_deg": math.degrees(math.atan2(srp[1], -srp[0])),
        "reach_bc_mm": bc[0],
        "reach_hand_mm": h[0],
        "stack_bc_mm": bc[1],
        "stack_hand_mm": h[1],
        "clamp_to_hands_horizontal_mm": h[0] - bc[0],
        "clamp_to_hands_vertical_mm": h[1] - bc[1],
        "clamp_to_hands_mm": math.dist(bc, h),
        "saddle_to_hand_reach_mm": h[0] - srp[0],
        "saddle_to_hand_drop_mm": srp[1] - h[1],
        "bb_to_hand_mm": math.hypot(*h),
    }


def _point_lists(pts: dict) -> dict[str, list[float]]:
    return {name.upper(): [q[0], q[1]] for name, q in pts.items()}


COORD_POINTS = {"st": "Saddle tip (ST)", "s": "Sit-bone point (S)", "bc": "Bar clamp (BC)", "h": "Hand point (H)"}


def _everything(p: dict[str, float], lat: dict, crank_mm: float) -> dict[str, float]:
    """Every scalar the engine reports, as one flat function of the tape vector (for the Jacobian)."""
    sol = _positions(p, lat)
    pts = sol["pts"]
    out = {f"u.{k}": v for k, v in _metrics(pts, crank_mm).items()}
    for name in COORD_POINTS:
        out[f"c.{name}_x"], out[f"c.{name}_y"] = pts[name]
    ra, fa = pts["ra"], pts["fa"]
    out["u.wheelbase_mm"] = sol["d"]["ra_fa"] * math.cos(sol["pitch"])
    out["u.bb_drop_mm"] = ra[1] + (fa[1] - ra[1]) * (0 - ra[0]) / (fa[0] - ra[0])
    for key in CHECK_KEYS:
        out[f"check.{key}"] = sol["computed"][key] - sol["d"][key]
    if "seat_bb" in p:
        bc = pts["bc"]
        dist = sol["d"]["bb_bc"]
        dz = p["seat_bc"] - p["seat_bb"]
        if abs(dz) >= dist:
            raise BikeFitError("seated floor heights differ by more than the BB-BC distance; recheck them")
        rho = math.asin(dz / dist) - math.atan2(bc[1], bc[0])
        out["rotation_deg"] = math.degrees(rho)
        seated = {n: _rot(q, rho) for n, q in pts.items()}
        out.update({f"s.{k}": v for k, v in _metrics(seated, crank_mm).items()})
    return out


def _jacobian_sigma(base: dict[str, float], p: dict[str, float], lat: dict, crank: float) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Per-output sigma and per-output per-tape sensitivity, by central differences."""
    jac: dict[str, dict[str, float]] = {k: {} for k in base}
    for name in p:
        up = _everything({**p, name: p[name] + JACOBIAN_STEP_MM}, lat, crank)
        dn = _everything({**p, name: p[name] - JACOBIAN_STEP_MM}, lat, crank)
        for k in base:
            jac[k][name] = (up[k] - dn[k]) / (2 * JACOBIAN_STEP_MM)
    sigma = {k: TAPE_SIGMA_MM * math.sqrt(sum(v * v for v in row.values())) for k, row in jac.items()}
    return sigma, jac


def _value(key: str, value: float, sigma: float, row: dict[str, float]) -> FitValue:
    label, unit, definition = OUTPUT_SPECS[key]
    deps = [m for m in row if abs(row[m]) >= DEPENDS_MIN and m in MEASURE_LABELS]
    return FitValue(key=key, label=label, unit=unit, value=value, sigma=sigma, definition=definition,
                    depends_on=deps)


def _thresholds(sigma: float) -> tuple[float, float]:
    return max(CLOSURE_WARN_MM, CLOSURE_WARN_SIGMA * sigma), max(CLOSURE_BAD_MM, CLOSURE_BAD_SIGMA * sigma)


def _status(residual: float, warn: float, bad: float) -> Literal["ok", "warn", "bad"]:
    size = abs(residual)
    return "bad" if size > bad else "warn" if size >= warn else "ok"


def _suspects(residuals: list[float], jac: dict[str, dict[str, float]]) -> list[Suspect]:
    """Rank the tapes whose error would produce this pattern of failed checks (a hint only)."""
    rnorm = math.sqrt(sum(r * r for r in residuals))
    if rnorm == 0:
        return []
    found: list[Suspect] = []
    for m in _DIST_KEYS:
        col = [jac[f"check.{c}"][m] for c in CHECK_KEYS]
        jnorm = math.sqrt(sum(v * v for v in col))
        if jnorm < SUSPECT_MIN_NORM:
            continue
        dot = sum(r * v for r, v in zip(residuals, col))
        fit = abs(dot) / (rnorm * jnorm)
        if fit >= SUSPECT_MIN_FIT:
            found.append(Suspect(measure=m, label=MEASURE_LABELS[m], estimated_error_mm=dot / (jnorm * jnorm), fit=fit))
    found.sort(key=lambda s: -s.fit)
    return found[:MAX_SUSPECTS]


def _closure(base: dict[str, float], sigma: dict[str, float], jac: dict[str, dict[str, float]],
             sol: dict) -> Closure:
    checks = []
    for k in CHECK_KEYS:
        warn, bad = _thresholds(sigma[f"check.{k}"])
        checks.append(CheckResult(
            key=k, label=CHECK_LABELS[k], computed_mm=sol["computed"][k], measured_mm=sol["d"][k],
            residual_mm=base[f"check.{k}"], sigma_mm=sigma[f"check.{k}"], warn_mm=warn, bad_mm=bad,
            status=_status(base[f"check.{k}"], warn, bad),
        ))
    order = ["ok", "warn", "bad"]
    status = max((c.status for c in checks), key=order.index)
    suspects: list[Suspect] = []
    affected: list[str] = []
    if status != "ok":
        suspects = _suspects([c.residual_mm for c in checks], jac)
        names = {s.measure for s in suspects}
        affected = [k.split(".", 1)[1] for k in jac if k.startswith("u.")
                    and any(abs(jac[k][m]) >= DEPENDS_MIN for m in names)]
    failed = ", ".join(c.label for c in checks if c.status != "ok")
    verdict = {
        "ok": "All six checks close within tolerance.",
        "warn": f"A little off the solved geometry ({failed}): recheck the likely tapes below.",
        "bad": f"Disagrees with the solved geometry by more than a tape error ({failed}): a measurement is likely wrong.",
    }[status]
    return Closure(
        status=status, checks=checks, message=verdict,
        not_checked=CHECKS_NOT_COVERED, suspects=suspects, affected_outputs=affected,
    )


def _lateral_effect(p: dict[str, float], lat: dict, crank: float, base: dict[str, float]) -> dict:
    """How far a +/- WIDTH_ERROR_MM error in each measured width moves the largest mm output."""
    per_width = {}
    for name, key in (("crank_bolt", "bb_mm"), ("front_axle", "fa_mm"), ("rear_axle", "ra_mm")):
        worst = 0.0
        for sign in (1, -1):
            moved = {**lat, key: lat[key] + sign * WIDTH_ERROR_MM / 2}
            try:
                alt = _everything(p, moved, crank)
            except BikeFitError:
                continue
            worst = max(worst, max(abs(alt[k] - base[k]) for k in base
                                   if k.startswith("u.") and not k.endswith("_deg")))
        per_width[name] = worst
    return {"width_error_mm": WIDTH_ERROR_MM, "max_output_change_mm": max(per_width.values()), "per_width_mm": per_width}


def compute_fit(inputs: BikeFitInputs, bike_type: BikeType | str) -> FitResult:
    """Derived geometry, +/- and closure checks for one snapshot's raw inputs."""
    if bike_type not in WIDTH_DEFAULTS_MM:
        raise BikeFitError(f"unknown bike type {bike_type!r}")
    lat = _lateral(inputs, bike_type)
    tilt = inputs.saddle_tilt_deg - (inputs.floor_tilt_deg or 0.0)
    crank = inputs.crank_length_mm
    p = {k: getattr(inputs.tape, k) for k in _TAPE_KEYS}
    p["sit_tip"] = inputs.sit_point_from_tip_mm
    if inputs.seated_floor_bb_mm is not None:
        p["seat_bb"], p["seat_bc"] = inputs.seated_floor_bb_mm, inputs.seated_floor_bc_mm
    base = _everything(p, lat, crank)
    sigma, jac = _jacobian_sigma(base, p, lat, crank)
    sol = _positions({k: p[k] for k in _BASE_KEYS}, lat)
    outputs = [_value(k, base[f"u.{k}"], sigma[f"u.{k}"], jac[f"u.{k}"]) for k in OUTPUT_SPECS]
    seated = None
    if "seat_bb" in p:
        seated = SeatedResult(
            rotation_deg=base["rotation_deg"], rotation_sigma_deg=sigma["rotation_deg"],
            assumption=SEATED_ASSUMPTION,
            outputs=[_value(k, base[f"s.{k}"], sigma[f"s.{k}"], jac[f"s.{k}"]) for k in _SEATED_KEYS_OUT],
            points=_point_lists({n: _rot(q, math.radians(base["rotation_deg"])) for n, q in sol["pts"].items()}),
        )
    notes = []
    if abs(tilt) > TILT_ADVISORY_DEG:
        notes.append(f"Tilt beyond \u00b1{TILT_ADVISORY_DEG:g}\u00b0: check the measurement. Not a target; "
                     "it does not block saving or change any result.")
    if bike_type == "mtb" and seated is None:
        notes.append(MTB_UNWEIGHTED_NOTE)
    if lat["defaulted"]:
        names = {"crank": "crank bolt width", "fa": "front axle width", "ra": "rear axle width"}
        notes.append("Assumed (blank width, bike-type fallback): " + ", ".join(names[k] for k in lat["defaulted"])
                     + ". Values that depend on them carry that assumption.")
    return FitResult(
        bike_type=bike_type, outputs=outputs, seated=seated, closure=_closure(base, sigma, jac, sol),
        points=_point_lists(sol["pts"]),
        coordinates=[Coordinate(key=k, label=label, x=base[f"c.{k}_x"], y=base[f"c.{k}_y"],
                                sigma_x=sigma[f"c.{k}_x"], sigma_y=sigma[f"c.{k}_y"])
                     for k, label in COORD_POINTS.items()],
        recorded={
            "saddle_model": inputs.saddle_model, "saddle_rail_note": inputs.saddle_rail_note,
            "saddle_length_mm": inputs.saddle_length_mm, "saddle_tilt_deg": inputs.saddle_tilt_deg,
            "floor_tilt_deg": inputs.floor_tilt_deg, "sit_point_from_tip_mm": inputs.sit_point_from_tip_mm,
            "crank_length_mm": crank, "frame_stack_mm": inputs.frame_stack_mm,
            "frame_reach_mm": inputs.frame_reach_mm, "pedal_stack_mm": inputs.pedal_stack_mm,
            "pedal_stack_source": inputs.pedal_stack_source,
        },
        tilt_deg=tilt,
        axle_heights_mm={"front": inputs.tape.floor_fa, "rear": inputs.tape.floor_ra},
        ground_pitch_deg=math.degrees(sol["pitch"]),
        radius_difference_mm=inputs.tape.floor_fa - inputs.tape.floor_ra,
        assumptions=lat, lateral_effect=_lateral_effect(p, lat, crank, base),
        constants={
            "tape_sigma_mm": TAPE_SIGMA_MM, "tilt_advisory_deg": TILT_ADVISORY_DEG,
            "pedal_stack_sigma_mm": PEDAL_STACK_SIGMA_MM,
            "closure_warn_mm": CLOSURE_WARN_MM, "closure_bad_mm": CLOSURE_BAD_MM,
            "closure_warn_sigma": CLOSURE_WARN_SIGMA, "closure_bad_sigma": CLOSURE_BAD_SIGMA,
            "compare_sigma_factor": COMPARE_SIGMA_FACTOR,
        },
        notes=notes, limits=LIMITS_STATEMENT,
    )


def _rows(a: list[FitValue], b: list[FitValue]) -> list[CompareRow]:
    by_b = {v.key: v for v in b}
    rows = []
    for va in a:
        vb = by_b.get(va.key)
        if vb is None:
            continue
        sd = math.hypot(va.sigma, vb.sigma)
        diff = vb.value - va.value
        rows.append(CompareRow(
            key=va.key, label=va.label, unit=va.unit, a=va.value, b=vb.value, diff=diff, sigma_a=va.sigma,
            sigma_b=vb.sigma, sigma_diff=sd, exceeds_error=abs(diff) > COMPARE_SIGMA_FACTOR * sd,
        ))
    return rows


def _same_saddle(a: str, b: str) -> bool:
    return " ".join(a.lower().split()) == " ".join(b.lower().split())


def _pedal_stack(a: FitResult, b: FitResult, down_diff: float, down_sigma: float) -> PedalStackCompare | None:
    sa, sb = a.recorded["pedal_stack_mm"], b.recorded["pedal_stack_mm"]
    if sa is None or sb is None:
        return None
    sigma = math.hypot(down_sigma, math.sqrt(2) * PEDAL_STACK_SIGMA_MM)
    adjusted = down_diff + (sb - sa)
    return PedalStackCompare(
        a_mm=sa, b_mm=sb, diff_mm=sb - sa, adjusted_pedal_down_diff_mm=adjusted,
        sigma_each_mm=PEDAL_STACK_SIGMA_MM, sigma_diff_mm=sigma,
        exceeds_error=abs(adjusted) > COMPARE_SIGMA_FACTOR * sigma, note=PEDAL_STACK_NOTE,
    )


def compare_fits(a: FitResult, b: FitResult) -> Comparison:
    """Difference (b minus a) per output, flagged when it exceeds the combined error. Seated rows
    only when both snapshots have them. Comparisons use the measured sit-bone point S; the tip rows
    stay visible. Also: the saddle model match, the crank-length difference and its pedal effect,
    and the pedal-stack difference when both snapshots have one. Nothing here recommends a change."""
    notes = [COMPARE_SETBACK_NOTE]
    for label, r in (("A", a), ("B", b)):
        if r.bike_type == "mtb" and r.seated is None:
            notes.append(f"Snapshot {label} is an MTB with unweighted results only. " + MTB_UNWEIGHTED_NOTE)
    ma, mb = a.recorded["sit_point_from_tip_mm"], b.recorded["sit_point_from_tip_mm"]
    if abs(ma - mb) > 1e-9:
        notes.append(f"The tip-to-S mark distance differs ({ma:g} vs {mb:g} mm), so the sit-point rows compare "
                     "different spots on the saddle; the same mark distance on both bikes is cleaner.")
    same = _same_saddle(a.recorded["saddle_model"], b.recorded["saddle_model"])
    notes.append("The saddle model matches, so the sit-point comparison is cleaner." if same
                 else "The saddle models differ, so sit-point rows also reflect the saddle shape.")
    rows = _rows(a.outputs, b.outputs)
    seated = _rows(a.seated.outputs, b.seated.outputs) if a.seated and b.seated else None
    by_key = {r.key: r for r in rows}
    ca, cb = a.recorded["crank_length_mm"], b.recorded["crank_length_mm"]
    crank = CrankCompare(a_mm=ca, b_mm=cb, diff_mm=cb - ca, pedal_down_effect_mm=cb - ca,
                         pedal_up_effect_mm=-(cb - ca))
    down = by_key["sit_to_pedal_down_mm"]
    return Comparison(
        factor=COMPARE_SIGMA_FACTOR,
        saddle=SaddleCompare(model_a=a.recorded["saddle_model"], model_b=b.recorded["saddle_model"], same=same),
        crank=crank, pedal_stack=_pedal_stack(a, b, down.diff, down.sigma_diff),
        unweighted=rows, seated=seated, notes=notes,
    )


def snapshot_view(snapshot: BikeFitSnapshot) -> dict:
    """A stored snapshot as API data: the raw record plus values recomputed from it now (so a
    method fix reaches old snapshots). An unsolvable record reports `derived: None` and an `error`."""
    view = snapshot.model_dump(mode="json")
    try:
        view["derived"] = compute_fit(snapshot.inputs, snapshot.bike_type).model_dump(mode="json")
        view["error"] = None
    except BikeFitError as exc:
        view["derived"] = None
        view["error"] = str(exc)
    return view


def resolve_snapshot(snapshots: list[BikeFitSnapshot], ref: str) -> BikeFitSnapshot | None:
    """A snapshot by id, or the newest non-retired one for a bike name (case-insensitive)."""
    ref = ref.strip()
    for s in snapshots:
        if str(s.id) == ref:
            return s
    named = [s for s in snapshots if s.bike_name.lower() == ref.lower() and not s.retired]
    return max(named, key=lambda s: s.date) if named else None
