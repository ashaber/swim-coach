"""Bike geometry from tape distances: a measuring and comparison tool, never a fit prescription.

The athlete measures straight-line distances between marked points on the bike's LEFT side; the
engine turns them into positions by trilateration, so nothing depends on the bike being level or
on an ambiguous definition. Sides are fixed from the known bike layout (never guessed): FA forward
of BB, BC and ST above, RA behind, H forward of ST. No real solution -> `BikeFitError`.

Points (mm; BB origin):
  BB  center of the left crank bolt            FA  center of the left front axle end
  RA  center of the left rear axle end         BC  bar clamp, where the stem clamps the bar, on the centerline
  ST  saddle tip, on the centerline            H   hand point: drop bar = top center of the left hood,
                                                   MTB = center of the left grip

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
CLOSURE_WARN_MM = 3.0  # |computed RA-FA minus measured RA-FA| at or above: warn
CLOSURE_BAD_MM = 6.0  # beyond: likely a bad measurement (still never rejected)
SIT_FRACTION = 0.5  # sit reference point: midpoint of the saddle, tip to tail
COMPARE_SIGMA_FACTOR = 2.0  # a difference is "beyond error" past 2 x its combined 1-sigma
JACOBIAN_STEP_MM = 0.01  # central-difference step for error propagation (deterministic)
DEPENDS_MIN = 0.05  # |d output / d tape| (per mm) at or above which an output "depends on" a tape
SUSPECT_MIN = 0.2  # |d residual / d tape| at or above which a tape is named a closure suspect

# Source: library/45-bike-race-setup.md section 10. Lateral offsets from the centerline, mm,
# ASSUMPTIONS (editable per snapshot): axle ends at half hub width (drop bar 100/142, boost
# MTB 110/148); BB bolt is a labelled default (crank arm plus bolt, not a measured value).
LATERAL_DEFAULTS_MM: dict[str, dict[str, float]] = {
    "drop_bar": {"bb": 60.0, "fa": 50.0, "ra": 71.0},
    "mtb": {"bb": 70.0, "fa": 55.0, "ra": 74.0},
}

LIMITS_STATEMENT = (
    "This records and compares bike geometry. It does not recommend fit changes, give medical "
    "advice, or state target angles; take changes to a fitter, and report pain through the normal "
    "stop-and-assess rule. The +/- is one standard deviation of tape and floor-height reading "
    f"error only (assumed {TAPE_SIGMA_MM:g} mm each): lateral offsets, saddle tilt and saddle "
    "length are taken as entered. Outputs are reference points on the bike, not body positions."
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
    "ra_bb": "RA-BB", "ra_st": "RA-ST", "bb_h": "BB-H", "st_h": "ST-H", "ra_fa": "RA-FA",
    "floor_fa": "floor to FA", "floor_ra": "floor to RA",
    "seat_bb": "seated floor to BB", "seat_bc": "seated floor to BC",
}
_TAPE_KEYS = ["bb_fa", "bb_bc", "fa_bc", "bb_st", "bc_st", "ra_bb", "ra_st", "bb_h", "st_h", "ra_fa",
              "floor_fa", "floor_ra"]
_SEATED_KEYS = ["seat_bb", "seat_bc"]
# The tapes the closure chain (FA <- BC <- ST <- RA) passes through, plus the direct RA-FA tape.
_CLOSURE_KEYS = ["bb_fa", "bb_bc", "fa_bc", "bb_st", "bc_st", "ra_bb", "ra_st", "ra_fa"]

# key -> (label, unit, definition). Order is display order.
OUTPUT_SPECS: dict[str, tuple[str, str, str]] = {
    "setback_tip_mm": ("Saddle setback, tip", "mm",
                       "Horizontal distance from the BB back to the saddle tip (ST); positive is behind the BB."),
    "setback_sit_mm": ("Saddle setback, sit point", "mm",
                       "Horizontal distance from the BB back to the sit reference point (midpoint of the saddle, "
                       "tip to tail, along the saddle's tilt); positive is behind the BB."),
    "saddle_height_mm": ("Saddle height, BB to sit point", "mm",
                         "Straight-line distance from the BB to the sit reference point."),
    "saddle_tip_height_mm": ("Saddle tip height above BB", "mm", "Vertical height of the saddle tip (ST) above the BB."),
    "effective_seat_angle_deg": ("Effective seat angle", "deg",
                                 "Angle of the line from the BB to the sit reference point, from horizontal, "
                                 "measured behind the BB. A measured value, not a target."),
    "reach_bc_mm": ("Reach, BC", "mm", "Horizontal distance from the BB forward to the bar clamp (BC)."),
    "reach_hand_mm": ("Reach, hand", "mm", "Horizontal distance from the BB forward to the hand point (H)."),
    "stack_bc_mm": ("Stack, BC", "mm", "Vertical height of the bar clamp (BC) above the BB."),
    "stack_hand_mm": ("Stack, hand", "mm", "Vertical height of the hand point (H) above the BB."),
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
    measure: str
    label: str
    sensitivity: float  # d(closure residual) / d(this tape), mm per mm


class Closure(BaseModel):
    status: Literal["ok", "warn", "bad"]
    computed_mm: float
    measured_mm: float
    residual_mm: float
    warn_mm: float
    bad_mm: float
    message: str
    suspects: list[Suspect]
    affected_outputs: list[str]


class SeatedResult(BaseModel):
    rotation_deg: float
    rotation_sigma_deg: float
    assumption: str
    outputs: list[FitValue]


class FitResult(BaseModel):
    bike_type: str
    outputs: list[FitValue]
    seated: SeatedResult | None
    closure: Closure
    ground_pitch_deg: float  # axle line vs level ground implied by the wheel-radius difference
    radius_difference_mm: float  # floor-to-FA minus floor-to-RA
    assumptions: dict
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
    d = LATERAL_DEFAULTS_MM[bike_type]
    given = {"bb": inputs.lateral_bb_mm, "fa": inputs.lateral_fa_mm, "ra": inputs.lateral_ra_mm}
    used = {k: (given[k] if given[k] is not None else d[k]) for k in d}
    return {
        "bb_mm": used["bb"], "fa_mm": used["fa"], "ra_mm": used["ra"], "h_mm": inputs.bar_width_mm / 2,
        "defaulted": [k for k in d if given[k] is None],
        "note": "Lateral offsets from the centerline are assumptions unless entered; H is half the bar width.",
    }


def _planar(tape: float, lat_a: float, lat_b: float, name: str) -> float:
    gap = lat_a - lat_b
    if tape <= abs(gap):
        raise BikeFitError(
            f"{name} ({tape:g} mm) is not longer than the lateral gap between its points ({abs(gap):g} mm); "
            "recheck the measurement or the lateral offsets"
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
    d = {
        "bb_fa": _planar(p["bb_fa"], lat["bb_mm"], lat["fa_mm"], "BB-FA"),
        "bb_bc": _planar(p["bb_bc"], lat["bb_mm"], 0.0, "BB-BC"),
        "fa_bc": _planar(p["fa_bc"], lat["fa_mm"], 0.0, "FA-BC"),
        "bb_st": _planar(p["bb_st"], lat["bb_mm"], 0.0, "BB-ST"),
        "bc_st": p["bc_st"],
        "ra_bb": _planar(p["ra_bb"], lat["ra_mm"], lat["bb_mm"], "RA-BB"),
        "ra_st": _planar(p["ra_st"], lat["ra_mm"], 0.0, "RA-ST"),
        "bb_h": _planar(p["bb_h"], lat["bb_mm"], lat["h_mm"], "BB-H"),
        "st_h": _planar(p["st_h"], 0.0, lat["h_mm"], "ST-H"),
        "ra_fa": _planar(p["ra_fa"], lat["ra_mm"], lat["fa_mm"], "RA-FA"),
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
    return {"pts": pts, "pitch": pitch, "d": d, "computed_ra_fa": length}


def _metrics(pts: dict) -> dict[str, float]:
    st, srp, bc, h = pts["st"], pts["srp"], pts["bc"], pts["h"]
    return {
        "setback_tip_mm": -st[0],
        "setback_sit_mm": -srp[0],
        "saddle_height_mm": math.hypot(*srp),
        "saddle_tip_height_mm": st[1],
        "effective_seat_angle_deg": math.degrees(math.atan2(srp[1], -srp[0])),
        "reach_bc_mm": bc[0],
        "reach_hand_mm": h[0],
        "stack_bc_mm": bc[1],
        "stack_hand_mm": h[1],
        "saddle_to_hand_reach_mm": h[0] - srp[0],
        "saddle_to_hand_drop_mm": srp[1] - h[1],
        "bb_to_hand_mm": math.hypot(*h),
    }


def _everything(p: dict[str, float], lat: dict, tilt_deg: float, saddle_len: float) -> dict[str, float]:
    """Every scalar the engine reports, as one flat function of the tape vector (for the Jacobian)."""
    sol = _positions(p, lat, tilt_deg, saddle_len)
    pts = sol["pts"]
    out = {f"u.{k}": v for k, v in _metrics(pts).items()}
    ra, fa = pts["ra"], pts["fa"]
    out["u.wheelbase_mm"] = sol["d"]["ra_fa"] * math.cos(sol["pitch"])
    axle_y = ra[1] + (fa[1] - ra[1]) * (0 - ra[0]) / (fa[0] - ra[0])
    out["u.bb_drop_mm"] = axle_y
    out["closure.residual_mm"] = sol["computed_ra_fa"] - sol["d"]["ra_fa"]
    if "seat_bb" in p:
        bc = pts["bc"]
        dist = sol["d"]["bb_bc"]
        dz = p["seat_bc"] - p["seat_bb"]
        if abs(dz) >= dist:
            raise BikeFitError("seated floor heights differ by more than the BB-BC distance; recheck them")
        rho = math.asin(dz / dist) - math.atan2(bc[1], bc[0])
        out["rotation_deg"] = math.degrees(rho)
        seated = {n: _rot(q, rho) for n, q in pts.items()}
        out.update({f"s.{k}": v for k, v in _metrics(seated).items()})
    return out


def _jacobian_sigma(base: dict[str, float], p: dict[str, float], lat: dict, tilt: float, slen: float
                    ) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    """Per-output sigma and per-output per-tape sensitivity, by central differences."""
    jac: dict[str, dict[str, float]] = {k: {} for k in base}
    for name in p:
        up = _everything({**p, name: p[name] + JACOBIAN_STEP_MM}, lat, tilt, slen)
        dn = _everything({**p, name: p[name] - JACOBIAN_STEP_MM}, lat, tilt, slen)
        for k in base:
            jac[k][name] = (up[k] - dn[k]) / (2 * JACOBIAN_STEP_MM)
    sigma = {k: TAPE_SIGMA_MM * math.sqrt(sum(v * v for v in row.values())) for k, row in jac.items()}
    return sigma, jac


def _value(key: str, value: float, sigma: float, row: dict[str, float]) -> FitValue:
    label, unit, definition = OUTPUT_SPECS[key]
    deps = [m for m in row if abs(row[m]) >= DEPENDS_MIN and m in MEASURE_LABELS]
    return FitValue(key=key, label=label, unit=unit, value=value, sigma=sigma, definition=definition,
                    depends_on=deps)


def _closure(residual: float, row: dict[str, float], jac: dict[str, dict[str, float]],
             computed: float, measured: float) -> Closure:
    size = abs(residual)
    status: Literal["ok", "warn", "bad"] = "bad" if size > CLOSURE_BAD_MM else "warn" if size >= CLOSURE_WARN_MM else "ok"
    suspects: list[Suspect] = []
    affected: list[str] = []
    if status != "ok":
        suspects = sorted(
            (Suspect(measure=m, label=MEASURE_LABELS[m], sensitivity=row[m])
             for m in _CLOSURE_KEYS if abs(row[m]) >= SUSPECT_MIN),
            key=lambda s: -abs(s.sensitivity),
        )
        names = {s.measure for s in suspects}
        affected = [k.split(".", 1)[1] for k in jac if k.startswith("u.")
                    and any(abs(jac[k][m]) >= DEPENDS_MIN for m in names)]
    verdict = {
        "ok": "RA-FA closes within tolerance. This check is blind to BB-H, ST-H, the floor heights and "
              "errors that cancel along the chain.",
        "warn": "RA-FA is a little off the solved value: recheck the listed measures.",
        "bad": "RA-FA disagrees with the solved value by more than a tape error: a measurement is likely wrong.",
    }[status]
    return Closure(
        status=status, computed_mm=computed, measured_mm=measured, residual_mm=residual,
        warn_mm=CLOSURE_WARN_MM, bad_mm=CLOSURE_BAD_MM, message=verdict, suspects=suspects,
        affected_outputs=affected,
    )


def compute_fit(inputs: BikeFitInputs, bike_type: BikeType | str) -> FitResult:
    """Derived geometry, +/- and closure for one snapshot's raw inputs."""
    if bike_type not in LATERAL_DEFAULTS_MM:
        raise BikeFitError(f"unknown bike type {bike_type!r}")
    lat = _lateral(inputs, bike_type)
    tilt = inputs.saddle_tilt_deg - (inputs.floor_tilt_deg or 0.0)
    p = {k: getattr(inputs.tape, k) for k in _TAPE_KEYS}
    if inputs.seated_floor_bb_mm is not None:
        p["seat_bb"], p["seat_bc"] = inputs.seated_floor_bb_mm, inputs.seated_floor_bc_mm
    base = _everything(p, lat, tilt, inputs.saddle_length_mm)
    sigma, jac = _jacobian_sigma(base, p, lat, tilt, inputs.saddle_length_mm)
    sol = _positions({k: p[k] for k in _TAPE_KEYS}, lat, tilt, inputs.saddle_length_mm)
    outputs = [_value(k, base[f"u.{k}"], sigma[f"u.{k}"], jac[f"u.{k}"]) for k in OUTPUT_SPECS]
    seated = None
    if "seat_bb" in p:
        seated = SeatedResult(
            rotation_deg=base["rotation_deg"], rotation_sigma_deg=sigma["rotation_deg"],
            assumption=SEATED_ASSUMPTION,
            outputs=[_value(k, base[f"s.{k}"], sigma[f"s.{k}"], jac[f"s.{k}"]) for k in _SEATED_KEYS_OUT],
        )
    closure = _closure(base["closure.residual_mm"], jac["closure.residual_mm"], jac,
                       sol["computed_ra_fa"], sol["d"]["ra_fa"])
    notes = []
    if bike_type == "mtb" and seated is None:
        notes.append(MTB_UNWEIGHTED_NOTE)
    return FitResult(
        bike_type=bike_type, outputs=outputs, seated=seated, closure=closure,
        ground_pitch_deg=math.degrees(sol["pitch"]),
        radius_difference_mm=inputs.tape.floor_fa - inputs.tape.floor_ra,
        assumptions=lat,
        constants={
            "tape_sigma_mm": TAPE_SIGMA_MM, "sit_fraction": SIT_FRACTION,
            "closure_warn_mm": CLOSURE_WARN_MM, "closure_bad_mm": CLOSURE_BAD_MM,
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
