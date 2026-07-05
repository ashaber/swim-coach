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
