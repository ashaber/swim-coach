"""CSS derivation, zone table, and open-water pace inference.

All zone-offset constants cite `library/04-css-intensity-anchors.md`
(file to be authored — this module is its designated home for now).
All open-water correction constants are PROVISIONAL and cite
`library/05-open-water-pace-inference.md` (also to be authored); they must
be calibrated against logged OW swims once enough data exists.
"""

from __future__ import annotations

# --- Zone offsets (seconds per 100m relative to CSS pace) --------------------
# Source: library/04-css-intensity-anchors.md — CSS-anchored 5-zone model,
# derived from critical velocity theory (Wakayoshi et al., 1992) and adapted
# to a training zone table. `None` marks an open (unbounded) end of a zone.

Z1_LO_OFFSET_S: float | None = 10.0  # library/04-css-intensity-anchors.md
Z1_HI_OFFSET_S: float | None = None  # library/04-css-intensity-anchors.md

Z2_LO_OFFSET_S: float = 5.0  # library/04-css-intensity-anchors.md
Z2_HI_OFFSET_S: float = 9.0  # library/04-css-intensity-anchors.md

Z3_LO_OFFSET_S: float = 2.0  # library/04-css-intensity-anchors.md
Z3_HI_OFFSET_S: float = 4.0  # library/04-css-intensity-anchors.md

Z4_LO_OFFSET_S: float = -1.0  # library/04-css-intensity-anchors.md
Z4_HI_OFFSET_S: float = 1.0  # library/04-css-intensity-anchors.md

Z5_LO_OFFSET_S: float | None = None  # library/04-css-intensity-anchors.md
Z5_HI_OFFSET_S: float | None = -2.0  # library/04-css-intensity-anchors.md

# --- Open-water pace correction constants (PROVISIONAL) ----------------------
# Source: library/05-open-water-pace-inference.md — every value here is a
# starting guess to be calibrated against 3-5+ logged OW swims per athlete.

WETSUIT_ADJ_S: float = -4.5
# PROVISIONAL: midpoint of the commonly cited -3..-6 s/100m wetsuit buoyancy
# assist range. library/05-open-water-pace-inference.md
# Confidence: low until calibrated against this athlete's wetsuit OW swims.

CONDITIONS_ADJ_S: dict[str, float] = {
    "calm": 2.0,  # PROVISIONAL: baseline sighting/no-wall penalty vs. pool.
    "moderate": 5.0,  # PROVISIONAL: moderate chop/sighting penalty.
    "rough": 8.0,  # PROVISIONAL: heavy chop/sighting penalty.
}
# library/05-open-water-pace-inference.md
# Confidence: low until calibrated against this athlete's logged OW swims
# across a range of conditions.

COLD_WATER_THRESHOLD_C: float = 16.0
# PROVISIONAL: below this water temperature, extra neuromuscular/thermal cost
# is assumed. library/05-open-water-pace-inference.md

COLD_WATER_ADJ_S: float = 2.0
# PROVISIONAL: additional seconds/100m penalty for water colder than
# COLD_WATER_THRESHOLD_C. library/05-open-water-pace-inference.md
# Confidence: low — not yet calibrated.


def css_from_test(t400_s: float, t200_s: float) -> float:
    """Critical Swim Speed pace (seconds per 100m) from a 400m/200m time trial.

    CSS = (t400 - t200) / 2, per Wakayoshi et al. (1992) critical velocity
    derivation. Requires t400_s > t200_s (otherwise the athlete swam the
    400m faster per-100m than the 200m, which is not a valid test result).
    """
    if t400_s <= t200_s:
        raise ValueError(
            f"t400_s ({t400_s}) must be greater than t200_s ({t200_s}) "
            "for a valid CSS test"
        )
    return (t400_s - t200_s) / 2


def zone_table(css: float) -> dict[str, dict[str, float | str | None]]:
    """Build the Z1-Z5 training zone table anchored to a CSS pace.

    Each zone entry has: name, lo_offset, hi_offset (seconds relative to
    css; None = open-ended), and the resolved pace bounds pace_lo_s /
    pace_hi_s (None where the offset is open-ended).
    """

    def _zone(name: str, lo_offset: float | None, hi_offset: float | None) -> dict:
        return {
            "name": name,
            "lo_offset": lo_offset,
            "hi_offset": hi_offset,
            "pace_lo_s": css + lo_offset if lo_offset is not None else None,
            "pace_hi_s": css + hi_offset if hi_offset is not None else None,
        }

    return {
        "Z1": _zone("Z1", Z1_LO_OFFSET_S, Z1_HI_OFFSET_S),
        "Z2": _zone("Z2", Z2_LO_OFFSET_S, Z2_HI_OFFSET_S),
        "Z3": _zone("Z3", Z3_LO_OFFSET_S, Z3_HI_OFFSET_S),
        "Z4": _zone("Z4", Z4_LO_OFFSET_S, Z4_HI_OFFSET_S),
        "Z5": _zone("Z5", Z5_LO_OFFSET_S, Z5_HI_OFFSET_S),
    }


# --- Cycling power-based training zones (Coggan/Allen 7-zone %FTP model) ---
# Source: library/23-cycling-training.md ("Power-based training zones
# (Coggan 7-zone model)"), `[EVIDENCE: cycling]` -- directly evidenced for
# cycling's own native use (Allen H., Coggan A. (2010), Training and Racing
# with a Power Meter), not an adaptation across disciplines the way this
# module's swim zone offsets above cite an adjacent one.
#
# Zone-boundary convention (per that library file's own explicit engineering
# decision, resolving the source table's whole-number gaps): boundaries are
# INCLUSIVE ON THE UPPER END and continuous, not restricted to whole
# numbers. A %FTP value falls in the first zone whose stated upper bound is
# >= that value. Z7 has no upper bound (short, maximal sprint efforts).

BIKE_Z1_HI_PCT_FTP: float = 55.0  # Active Recovery -- library/23-cycling-training.md
BIKE_Z2_HI_PCT_FTP: float = 75.0  # Endurance -- library/23-cycling-training.md
BIKE_Z3_HI_PCT_FTP: float = 90.0  # Tempo -- library/23-cycling-training.md
BIKE_Z4_HI_PCT_FTP: float = 105.0  # Lactate Threshold -- library/23-cycling-training.md
BIKE_Z5_HI_PCT_FTP: float = 120.0  # VO2max -- library/23-cycling-training.md
BIKE_Z6_HI_PCT_FTP: float = 150.0  # Anaerobic Capacity -- library/23-cycling-training.md
# Z7 (Neuromuscular Power): > BIKE_Z6_HI_PCT_FTP, no upper cap --
# library/23-cycling-training.md.

# (zone name, upper %FTP bound or None for open-ended) -- ordered ascending,
# both `bike_zone_table` and `bike_zone_for_pct` walk this same list so the
# boundary convention above is implemented in exactly one place.
_BIKE_ZONE_BOUNDS: list[tuple[str, float | None]] = [
    ("Z1", BIKE_Z1_HI_PCT_FTP),
    ("Z2", BIKE_Z2_HI_PCT_FTP),
    ("Z3", BIKE_Z3_HI_PCT_FTP),
    ("Z4", BIKE_Z4_HI_PCT_FTP),
    ("Z5", BIKE_Z5_HI_PCT_FTP),
    ("Z6", BIKE_Z6_HI_PCT_FTP),
    ("Z7", None),
]


def bike_zone_for_pct(pct_of_ftp: float) -> str:
    """Which Coggan/Allen zone (Z1-Z7) a given %FTP value falls into, per
    the inclusive-upper-bound convention documented above and stated
    explicitly in library/23-cycling-training.md. Returns the FIRST zone
    (in ascending order) whose upper bound is >= `pct_of_ftp`; Z7 (the
    final entry, upper bound `None`) always matches whatever falls through
    every prior zone, so this never raises.
    """
    for name, hi_pct in _BIKE_ZONE_BOUNDS:
        if hi_pct is None or pct_of_ftp <= hi_pct:
            return name
    return _BIKE_ZONE_BOUNDS[-1][0]  # unreachable: Z7's hi_pct is None


def bike_zone_table(ftp_watts: float) -> dict[str, dict[str, float | str | None]]:
    """Build the Z1-Z7 Coggan/Allen %FTP power-zone table anchored to an
    athlete's FTP (watts) -- the cycling-native counterpart to `zone_table`
    above, same shape (per-zone name/bounds), but %FTP-based rather than a
    CSS-pace-offset table, since cycling zones anchor to a directly
    measurable power output rather than an inferred pace (see
    library/23-cycling-training.md's own note on this structural
    difference).

    Each zone entry has: name, lo_pct_ftp, hi_pct_ftp (None = open-ended),
    and the resolved watts_lo / watts_hi (None where the %FTP bound is
    open-ended).
    """
    table: dict[str, dict[str, float | str | None]] = {}
    lo_pct = 0.0
    for name, hi_pct in _BIKE_ZONE_BOUNDS:
        table[name] = {
            "name": name,
            "lo_pct_ftp": lo_pct,
            "hi_pct_ftp": hi_pct,
            "watts_lo": ftp_watts * lo_pct / 100.0,
            "watts_hi": ftp_watts * hi_pct / 100.0 if hi_pct is not None else None,
        }
        if hi_pct is not None:
            lo_pct = hi_pct
    return table


def infer_ow_pace(
    css: float,
    wetsuit: bool,
    conditions: str,
    water_temp_c: float | None,
) -> float:
    """Infer an open-water pace (s/100m) from CSS plus provisional corrections.

    Applies, in order: wetsuit buoyancy assist, condition-based
    chop/sighting penalty, and a cold-water penalty below
    COLD_WATER_THRESHOLD_C. All correction constants are provisional —
    see module docstring.
    """
    if conditions not in CONDITIONS_ADJ_S:
        raise ValueError(
            f"unknown conditions: {conditions!r}, must be one of "
            f"{sorted(CONDITIONS_ADJ_S)}"
        )
    pace = css
    if wetsuit:
        pace += WETSUIT_ADJ_S
    pace += CONDITIONS_ADJ_S[conditions]
    if water_temp_c is not None and water_temp_c < COLD_WATER_THRESHOLD_C:
        pace += COLD_WATER_ADJ_S
    return pace
