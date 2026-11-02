"""Bike geometry from tape distances: a measuring and comparison tool, never a fit prescription.

The athlete measures straight-line distances between marked points on the bike's LEFT side; the
engine turns them into positions by trilateration, so nothing depends on the bike being level or
on an ambiguous definition. Sides are fixed from the known bike layout (never guessed): FA forward
of BB, BC and ST above, RA behind, H forward of ST. No real solution -> `BikeFitError`.

Points (mm; BB origin):
  BB  center of the left crank bolt (outer face)   FA  center of the left front axle end
  RA  center of the left rear axle end             BC  bar clamp, where the stem clamps the bar, on the centerline
  ST  saddle tip, on the centerline                H   hand point: the midpoint of a string stretched between the
        left and right contact points (drop bar: top center of each hood where the palm sits; MTB: center of
        each grip where the palm sits), so it lies on the centerline and has no lateral offset

Ground direction comes from the axle line (RA to FA) corrected by the floor-to-axle height
difference (unequal wheel radius). Every constant below rests on `library/45-bike-race-setup.md`
section 10 ("Measuring bike geometry", `Coach judgment:`); that section is the method statement
and the limits. There are no fit targets anywhere in this module.
"""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel

from swim_coach.models import BikeFitInputs, BikeFitSnapshot, BikeType

# Source: library/45-bike-race-setup.md section 10 -- every constant in this block is coach
# judgment, stated there, and editable here.
TAPE_SIGMA_MM = 1.0  # assumed 1 standard deviation of one tape or floor-height reading
# A check's |computed minus measured| warns at max(CLOSURE_WARN_MM, CLOSURE_WARN_SIGMA x its own
# expected sd) and is flagged "likely bad" beyond max(CLOSURE_BAD_MM, CLOSURE_BAD_SIGMA x sd): the
# sd of the FA-H check at 1 mm tape error is about 2.5 mm, so a flat 3 / 6 mm would false-alarm
# often. Never rejects. False-alarm rates at 1 mm tape error are in library 45 section 10.
CLOSURE_WARN_MM = 3.0
CLOSURE_BAD_MM = 6.0
CLOSURE_WARN_SIGMA = 2.5
CLOSURE_BAD_SIGMA = 4.0
SIT_FRACTION = 0.5  # sit reference point: midpoint of the saddle, tip to tail
COMPARE_SIGMA_FACTOR = 2.0  # a difference is "beyond error" past 2 x its combined 1-sigma
JACOBIAN_STEP_MM = 0.01  # central-difference step for error propagation (deterministic)
DEPENDS_MIN = 0.05  # |d output / d tape| (per mm) at or above which an output "depends on" a tape
SUSPECT_MIN_FIT = 0.9  # cosine between the failed-check pattern and a tape's pattern to name it a suspect
SUSPECT_MIN_NORM = 0.3  # a tape must move the checks at least this much per mm to be named
MAX_SUSPECTS = 4
WIDTH_ERROR_MM = 5.0  # stated width error used for the lateral-assumption note

# Source: library/45-bike-race-setup.md section 10. Widths, mm, measured end to end across the bike;
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
    f"error only (assumed {TAPE_SIGMA_MM:g} mm each): saddle tilt, saddle length, crank length and "
    "any width left blank are taken as entered or assumed. Outputs are reference points on the "
    "bike, not body positions. Only the hand point on the hoods or grips is measured; the drops "
    "are out of scope for now."
)

CHECKS_NOT_COVERED = (
    "The four checks cannot see the floor heights, saddle tilt, saddle length, crank length, "
    "string length or the three widths, or errors that happen to cancel."
)

SEATED_ASSUMPTION = (
    "Seated results rotate the unweighted bike about the BB by the change in the BB-to-BC line "
    "angle between the unweighted and seated floor heights. The BB, BC, saddle and hand points are "
    "treated as one rigid front triangle; fork compression and any rear-suspension geometry change "
    "are not modelled."
)

MTB_UNWEIGHTED_NOTE = (
    "Unweighted numbers only: rear sag normally rotates the frame back, so unweighted numbers "
    "may understate how upright he actually rides this bike. Add the seated floor heights "
    "(helper needed) to see the orientation under load."
)

MEASURE_LABELS: dict[str, str] = {
    "bb_fa": "BB-FA", "bb_bc": "BB-BC", "fa_bc": "FA-BC", "bb_st": "BB-ST", "bc_st": "BC-ST",
    "ra_bb": "RA-BB", "ra_st": "RA-ST", "bb_h": "BB-H", "st_h": "ST-H", "bc_h": "BC-H",
    "ra_fa": "RA-FA", "fa_h": "FA-H", "ra_bc": "RA-BC",
    "floor_fa": "floor to FA", "floor_ra": "floor to RA",
    "seat_bb": "seated floor to BB", "seat_bc": "seated floor to BC",
}
_DIST_KEYS = ["bb_fa", "bb_bc", "fa_bc", "bb_st", "bc_st", "ra_bb", "ra_st", "bb_h", "st_h", "bc_h",
              "ra_fa", "fa_h", "ra_bc"]
_TAPE_KEYS = _DIST_KEYS + ["floor_fa", "floor_ra"]
# The four tapes that are compared with the solved geometry instead of used to build it.
CHECK_KEYS = ["ra_fa", "fa_h", "ra_bc", "bc_h"]
CHECK_LABELS = {"ra_fa": "RA-FA (wheelbase)", "fa_h": "FA-H", "ra_bc": "RA-BC", "bc_h": "BC-H"}

# key -> (label, unit, definition). Order is display order.
OUTPUT_SPECS: dict[str, tuple[str, str, str]] = {
    "setback_tip_mm": ("Saddle setback, tip", "mm",
                       "Horizontal distance from the BB back to the saddle tip (ST); positive is behind the BB."),
    "setback_sit_mm": ("Saddle setback, sit point", "mm",
                       "Horizontal distance from the BB back to the sit reference point (midpoint of the saddle, "
                       "tip to tail, along the saddle's tilt); positive is behind the BB."),
    "saddle_height_mm": ("Saddle height, BB to sit point", "mm",
                         "Straight-line distance from the BB to the sit reference point."),
    "sit_to_pedal_down_mm": ("Sit point to pedal axle, crank down on the seat line", "mm",
                             "Geometric value, not leg extension: saddle height plus crank length, i.e. the distance "
                             "from the sit reference point to the pedal axle with the crank pointing down along the "
                             "line from the sit point through the BB."),
    "sit_to_pedal_up_mm": ("Sit point to pedal axle, crank up on the seat line", "mm",
                           "Geometric value, not leg clearance: saddle height minus crank length, i.e. the distance "
                           "from the sit reference point to the pedal axle with the crank pointing up along the "
                           "line from the BB to the sit point."),
    "saddle_tip_height_mm": ("Saddle tip height above BB", "mm", "Vertical height of the saddle tip (ST) above the BB."),
    "effective_seat_angle_deg": ("Effective seat angle", "deg",
                                 "Angle of the line from the BB to the sit reference point, from horizontal, "
                                 "measured behind the BB. A measured value, not a target."),
    "reach_bc_mm": ("Reach, BC", "mm", "Horizontal distance from the BB forward to the bar clamp (BC)."),
    "reach_hand_mm": ("Reach, hand", "mm", "Horizontal distance from the BB forward to the hand point (H)."),
    "stack_bc_mm": ("Stack, BC", "mm", "Vertical height of the bar clamp (BC) above the BB."),
    "stack_hand_mm": ("Stack, hand", "mm", "Vertical height of the hand point (H) above the BB."),
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
                                "Horizontal distance from the sit reference point forward to the hand point."),
    "saddle_to_hand_drop_mm": ("Saddle-to-hand drop", "mm",
                               "Vertical drop from the sit reference point down to the hand point; negative means "
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


class FitResult(BaseModel):
    bike_type: str
    outputs: list[FitValue]
    points: dict[str, list[float]]  # level-frame points, BB origin, x forward / y up (for drawing only)
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


class Comparison(BaseModel):
    factor: float
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


def _positions(p: dict[str, float], lat: dict, tilt_deg: float, saddle_len: float) -> dict:
    """Level-frame points (x forward, y up, BB origin) plus the ground pitch, from a tape vector."""
    b, f, r = lat["bb_mm"], lat["fa_mm"], lat["ra_mm"]
    d = {
        "bb_fa": _planar(p["bb_fa"], b, f, "BB-FA"),
        "bb_bc": _planar(p["bb_bc"], b, 0.0, "BB-BC"),
        "fa_bc": _planar(p["fa_bc"], f, 0.0, "FA-BC"),
        "bb_st": _planar(p["bb_st"], b, 0.0, "BB-ST"),
        "bc_st": _planar(p["bc_st"], 0.0, 0.0, "BC-ST"),
        "ra_bb": _planar(p["ra_bb"], r, b, "RA-BB"),
        "ra_st": _planar(p["ra_st"], r, 0.0, "RA-ST"),
        "bb_h": _planar(p["bb_h"], b, 0.0, "BB-H"),
        "st_h": _planar(p["st_h"], 0.0, 0.0, "ST-H"),
        "bc_h": _planar(p["bc_h"], 0.0, 0.0, "BC-H"),
        "ra_fa": _planar(p["ra_fa"], r, f, "RA-FA"),
        "fa_h": _planar(p["fa_h"], f, 0.0, "FA-H"),
        "ra_bc": _planar(p["ra_bc"], r, 0.0, "RA-BC"),
    }
    bb = (0.0, 0.0)
    fa = (d["bb_fa"], 0.0)
    bc = _circles(bb, d["bb_bc"], fa, d["fa_bc"], "BB-FA, BB-BC and FA-BC", "left")
    st = _circles(bb, d["bb_st"], bc, d["bc_st"], "BB-BC, BB-ST and BC-ST", "left")
    ra = _circles(bb, d["ra_bb"], st, d["ra_st"], "BB-ST, RA-BB and RA-ST", "left")
    h = _circles(bb, d["bb_h"], st, d["st_h"], "BB-ST, BB-H and ST-H", "right")
    vx, vy = fa[0] - ra[0], fa[1] - ra[1]
    length = math.hypot(vx, vy)
    rise = p["floor_fa"] - p["floor_ra"]
    if length == 0 or abs(rise) >= length:
        raise BikeFitError("the axle heights are inconsistent with the solved wheelbase; recheck RA-FA and the floor heights")
    pitch = math.asin(rise / length)
    ang = math.atan2(vy, vx) - pitch  # the frame angle of "level forward"
    pts = {n: _rot(q, -ang) for n, q in (("bb", bb), ("fa", fa), ("ra", ra), ("bc", bc), ("st", st), ("h", h))}
    tilt = math.radians(tilt_deg)
    k = SIT_FRACTION * saddle_len
    pts["srp"] = (pts["st"][0] - k * math.cos(tilt), pts["st"][1] - k * math.sin(tilt))
    computed = {
        "ra_fa": length, "fa_h": math.dist(fa, h), "ra_bc": math.dist(ra, bc), "bc_h": math.dist(bc, h),
    }
    return {"pts": pts, "pitch": pitch, "d": d, "computed": computed}


def _metrics(pts: dict, crank_mm: float) -> dict[str, float]:
    st, srp, bc, h = pts["st"], pts["srp"], pts["bc"], pts["h"]
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


def _everything(p: dict[str, float], lat: dict, tilt_deg: float, saddle_len: float, crank_mm: float
                ) -> dict[str, float]:
    """Every scalar the engine reports, as one flat function of the tape vector (for the Jacobian)."""
    sol = _positions(p, lat, tilt_deg, saddle_len)
    pts = sol["pts"]
    out = {f"u.{k}": v for k, v in _metrics(pts, crank_mm).items()}
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


def _jacobian_sigma(base: dict[str, float], p: dict[str, float], lat: dict, tilt: float, slen: float,
                    crank: float) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Per-output sigma and per-output per-tape sensitivity, by central differences."""
    jac: dict[str, dict[str, float]] = {k: {} for k in base}
    for name in p:
        up = _everything({**p, name: p[name] + JACOBIAN_STEP_MM}, lat, tilt, slen, crank)
        dn = _everything({**p, name: p[name] - JACOBIAN_STEP_MM}, lat, tilt, slen, crank)
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
        "ok": "All four checks close within tolerance.",
        "warn": f"A little off the solved geometry ({failed}): recheck the likely tapes below.",
        "bad": f"Disagrees with the solved geometry by more than a tape error ({failed}): a measurement is likely wrong.",
    }[status]
    return Closure(
        status=status, checks=checks, message=verdict,
        not_checked=CHECKS_NOT_COVERED, suspects=suspects, affected_outputs=affected,
    )


def _lateral_effect(p: dict[str, float], lat: dict, tilt: float, slen: float, crank: float,
                    base: dict[str, float]) -> dict:
    """How far a +/- WIDTH_ERROR_MM error in each measured width moves the largest mm output."""
    per_width = {}
    for name, key in (("crank_bolt", "bb_mm"), ("front_axle", "fa_mm"), ("rear_axle", "ra_mm")):
        worst = 0.0
        for sign in (1, -1):
            moved = {**lat, key: lat[key] + sign * WIDTH_ERROR_MM / 2}
            try:
                alt = _everything(p, moved, tilt, slen, crank)
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
    slen = inputs.saddle_length_mm
    p = {k: getattr(inputs.tape, k) for k in _TAPE_KEYS}
    if inputs.seated_floor_bb_mm is not None:
        p["seat_bb"], p["seat_bc"] = inputs.seated_floor_bb_mm, inputs.seated_floor_bc_mm
    base = _everything(p, lat, tilt, slen, crank)
    sigma, jac = _jacobian_sigma(base, p, lat, tilt, slen, crank)
    sol = _positions({k: p[k] for k in _TAPE_KEYS}, lat, tilt, slen)
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
    if bike_type == "mtb" and seated is None:
        notes.append(MTB_UNWEIGHTED_NOTE)
    if lat["defaulted"]:
        names = {"crank": "crank bolt width", "fa": "front axle width", "ra": "rear axle width"}
        notes.append("Assumed (blank width, bike-type fallback): " + ", ".join(names[k] for k in lat["defaulted"])
                     + ". Values that depend on them carry that assumption.")
    return FitResult(
        bike_type=bike_type, outputs=outputs, seated=seated, closure=_closure(base, sigma, jac, sol),
        points=_point_lists(sol["pts"]),
        axle_heights_mm={"front": inputs.tape.floor_fa, "rear": inputs.tape.floor_ra},
        ground_pitch_deg=math.degrees(sol["pitch"]),
        radius_difference_mm=inputs.tape.floor_fa - inputs.tape.floor_ra,
        assumptions=lat, lateral_effect=_lateral_effect(p, lat, tilt, slen, crank, base),
        constants={
            "tape_sigma_mm": TAPE_SIGMA_MM, "sit_fraction": SIT_FRACTION,
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


def compare_fits(a: FitResult, b: FitResult) -> Comparison:
    """Difference (b minus a) per output, flagged when it exceeds the combined error. Seated rows
    only when both snapshots have them. Comparisons use the sit point; the tip rows stay visible."""
    notes = []
    for label, r in (("A", a), ("B", b)):
        if r.bike_type == "mtb" and r.seated is None:
            notes.append(f"Snapshot {label} is an MTB with unweighted results only. " + MTB_UNWEIGHTED_NOTE)
    seated = _rows(a.seated.outputs, b.seated.outputs) if a.seated and b.seated else None
    return Comparison(factor=COMPARE_SIGMA_FACTOR, unweighted=_rows(a.outputs, b.outputs), seated=seated, notes=notes)


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
