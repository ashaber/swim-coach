"""Setup-log helpers: device-temperature lookup, temperature-window filter, coach-facing view.

All unit conversion is the engine's (`swim_coach.temperature`); the LLM never converts.
"""

from __future__ import annotations

from uuid import UUID

from swim_coach.models import SetupLogEntry, Workout
from swim_coach.temperature import c_to_f, is_outdoor_ride

TEMP_WINDOW_C = 5.0
MAX_ENTRIES = 10


def device_temp_for(
    workouts: list[Workout], *, day, sport: str | None, workout_id: UUID | None
) -> tuple[float | None, float | None, UUID | None]:
    """(low, high, workout_id) from the outdoor workout(s) on `day`; only outdoor bike rides count.
    Several outdoor rides that day merge into one min/max; the id is set only when exactly one."""
    if workout_id is not None:
        pool = [w for w in workouts if w.id == workout_id]
    else:
        pool = [w for w in workouts if w.date == day and (sport is None or w.sport == sport or sport in (w.sport_detail or ""))]
    outdoor = [w for w in pool if is_outdoor_ride(w.sport, w.sport_detail)]
    with_temp = [w for w in outdoor if w.min_temp_c is not None or w.max_temp_c is not None or w.avg_temp_c is not None]
    link = pool[0].id if workout_id is not None and pool else (outdoor[0].id if len(outdoor) == 1 else None)
    if not with_temp:
        return None, None, link
    lows = [w.min_temp_c if w.min_temp_c is not None else w.avg_temp_c if w.avg_temp_c is not None else w.max_temp_c for w in with_temp]
    highs = [w.max_temp_c if w.max_temp_c is not None else w.avg_temp_c if w.avg_temp_c is not None else w.min_temp_c for w in with_temp]
    return min(lows), max(highs), link


def matches_temp(entry: SetupLogEntry, target_c: float) -> bool:
    """True when the entry's logged range overlaps target +/- TEMP_WINDOW_C. No temperature: never."""
    if entry.temp_c_low is None or entry.temp_c_high is None:
        return False
    return entry.temp_c_low <= target_c + TEMP_WINDOW_C and entry.temp_c_high >= target_c - TEMP_WINDOW_C


def entry_view(e: SetupLogEntry) -> dict:
    out: dict = {"date": e.date.isoformat(), "kind": e.kind, "text": e.text, "outcome": e.outcome}
    for name in ("sport", "conditions", "pressure_front_psi", "pressure_rear_psi"):
        if getattr(e, name) is not None:
            out[name] = getattr(e, name)
    if e.temp_c_low is not None and e.temp_c_high is not None:
        out.update(
            temp_c_low=round(e.temp_c_low, 1), temp_c_high=round(e.temp_c_high, 1),
            temp_f_low=round(c_to_f(e.temp_c_low), 1), temp_f_high=round(c_to_f(e.temp_c_high), 1),
            temp_source=e.temp_source,
        )
    return out
