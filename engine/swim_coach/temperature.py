"""Temperature unit conversion and indoor-session detection.

Engine rule: the LLM never converts units; every C/F number it shows comes from here.
"""

from __future__ import annotations

INDOOR_SUB_SPORTS: frozenset[str] = frozenset({"indoor_cycling", "virtual_activity", "spin", "indoor_running"})
"""FIT `sub_sport` values whose device temperature is room temperature, not weather. Names are the
FIT SDK enum entries fitdecode emits; they appear as the suffix of `Workout.sport_detail`
("cycling/indoor_cycling")."""


def c_to_f(c: float) -> float:
    return c * 9.0 / 5.0 + 32.0


def f_to_c(f: float) -> float:
    return (f - 32.0) * 5.0 / 9.0


def is_indoor_detail(sport_detail: str | None) -> bool:
    """True when a workout's `sport_detail` ("sport/sub_sport") marks an indoor/trainer session."""
    if not sport_detail or "/" not in sport_detail:
        return False
    return sport_detail.split("/", 1)[1].strip().lower() in INDOOR_SUB_SPORTS


def device_temp_view(
    avg_c: float | None, min_c: float | None, max_c: float | None, sport_detail: str | None = None
) -> dict[str, float | bool] | None:
    """Compact avg/min/max in both units for the coach; None when the device recorded nothing.
    `indoor` is set only for trainer sessions (room temperature, not weather)."""
    out: dict[str, float | bool] = {}
    for name, c in (("avg", avg_c), ("min", min_c), ("max", max_c)):
        if c is not None:
            out[f"{name}_c"] = round(c, 1)
            out[f"{name}_f"] = round(c_to_f(c), 1)
    if not out:
        return None
    if is_indoor_detail(sport_detail):
        out["indoor"] = True
    return out
