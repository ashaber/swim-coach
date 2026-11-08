"""Graded rating of a completed work rep: how its average landed against the target band AND
the athlete's power zones.

The binary in-band call (`IntervalEffort.in_target_band`) says a rep at 90% of target "missed".
A coach reads it differently: a VO2 rep ridden at 106% FTP is under the 320-335 W band but is
still in the VO2 zone (most of the stimulus is delivered); the same rep ridden at 102% FTP has
dropped into threshold, a different stimulus. This module adds that grade, never replacing the
in-band call. Pure functions, no I/O, no LLM; zone boundaries are the engine's own Coggan/Allen
%FTP table (`zones.bike_zone_for_pct`, library/23-cycling-training.md) -- none are invented here.

Classes (`RepClass`):
  in_band             average inside the band
  below_band_in_zone  under the band, still in the prescribed zone (or higher)
  dropped_zone        under the band AND in a lower zone than prescribed
  above_band          over the band's top

Coach judgment: the prescribed zone is the rep's own zone when it has one, else the zone of the
band midpoint (a watts-only prescription such as "40s 320-335W" carries no zone). See
library/26-activity-stream-interval-analysis.md ("Graded rep rating").
"""

from __future__ import annotations

from typing import Literal

from swim_coach.models import RepRatingSummary
from swim_coach.zones import bike_zone_for_pct

RepClass = Literal["in_band", "below_band_in_zone", "dropped_zone", "above_band"]

# Coach judgment: plain-English names for the summary line, from the zone names in
# library/23-cycling-training.md (Coggan/Allen).
ZONE_LABELS: dict[str, str] = {
    "Z1": "recovery",
    "Z2": "endurance",
    "Z3": "tempo",
    "Z4": "threshold",
    "Z5": "VO2",
    "Z6": "anaerobic",
    "Z7": "sprint",
}


def _zone_rank(zone: str) -> int:
    return int(zone[1:])


def zone_of_watts(watts: float, ftp_watts: float) -> str:
    return bike_zone_for_pct(watts / ftp_watts * 100.0)


def prescribed_zone(
    zone: str | None, low_w: float | None, high_w: float | None, ftp_watts: float | None
) -> str | None:
    """The rep's own zone, else the zone of its band midpoint (needs FTP), else `None`."""
    if zone and zone.upper() in ZONE_LABELS:
        return zone.upper()
    if not ftp_watts or low_w is None:
        return None
    mid = (low_w + high_w) / 2 if high_w is not None else low_w
    return zone_of_watts(mid, ftp_watts)


def classify_rep(
    avg_w: float,
    *,
    low_w: float | None,
    high_w: float | None,
    zone: str | None,
    ftp_watts: float | None,
) -> tuple[RepClass, str] | None:
    """`(class, zone the average landed in)`, or `None` without a band or FTP to rate against."""
    if low_w is None or not ftp_watts:
        return None
    landed = zone_of_watts(avg_w, ftp_watts)
    if avg_w < low_w:
        target = prescribed_zone(zone, low_w, high_w, ftp_watts)
        if target is not None and _zone_rank(landed) < _zone_rank(target):
            return "dropped_zone", landed
        return "below_band_in_zone", landed
    if high_w is not None and avg_w > high_w:
        return "above_band", landed
    return "in_band", landed


def _label(zone: str) -> str:
    return f"{ZONE_LABELS[zone]} ({zone})"


def summarize_ratings(
    rows: list[tuple[int | None, RepClass, float, str]],
    *,
    low_w: float | None,
    high_w: float | None,
    zone: str | None,
    ftp_watts: float | None,
) -> RepRatingSummary | None:
    """Session-level counts and the plain-English line from `(round_n, class, avg_w, landed_zone)`
    per rated rep. `low_w`/`high_w`/`zone` describe the (single) prescription band, when there is one."""
    if not rows:
        return None
    n = len(rows)
    count = {c: sum(1 for r in rows if r[1] == c) for c in
             ("in_band", "below_band_in_zone", "dropped_zone", "above_band")}
    target = prescribed_zone(zone, low_w, high_w, ftp_watts)
    held = n - count["dropped_zone"]
    band = f"{low_w:g}-{high_w:g} W" if low_w is not None and high_w is not None else None
    where = f" {_label(target)}" if target else " the prescribed zone"
    parts = [f"{held} of {n} reps held{where}"]
    below = [r for r in rows if r[1] == "below_band_in_zone"]
    if below and low_w:
        gaps = [low_w - r[2] for r in below]
        lo_g, hi_g = max(1, round(min(gaps))), max(1, round(max(gaps)))
        span = f"{lo_g}" if lo_g == hi_g else f"{lo_g}-{hi_g}"
        who = "all" if len(below) == n else f"{len(below)}"
        parts.append(f"{who} {span} W under the {band} band" if band else f"{who} {span} W under the band")
    if count["dropped_zone"]:
        dropped = [r for r in rows if r[1] == "dropped_zone"]
        landed = sorted({r[3] for r in dropped}, key=_zone_rank)
        names = " / ".join(_label(z) for z in landed)
        rounds = sorted({r[0] for r in dropped if r[0] is not None})
        loc = f" in round{'s' if len(rounds) > 1 else ''} {', '.join(map(str, rounds))}" if rounds else ""
        parts.append(f"{count['dropped_zone']} dropped to {names}{loc}")
    if count["above_band"]:
        parts.append(f"{count['above_band']} over the band")
    if count["in_band"] and (below or count["dropped_zone"] or count["above_band"]):
        parts.append(f"{count['in_band']} in band")
    return RepRatingSummary(
        rated=n,
        **count,
        held_zone_pct=round(held / n * 100, 1),
        prescribed_zone=target,
        summary="; ".join(parts),
    )
