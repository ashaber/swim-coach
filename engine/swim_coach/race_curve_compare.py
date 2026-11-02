"""Prior-race average power curve for the race view -- pure, no I/O.

Compares a race's power curve with the athlete's earlier races of the same discipline: the pointwise mean
of their stored mean-maximal curves (`swim_coach.power_curve`, one `PowerCurvePoint` list per ride; nothing
is recomputed from the streams).

Which races: earlier ones (dated before this race; this race and same-day races are never included, since
workouts carry no reliable start time), `effective_kind == "race"`, same discipline. Races on the current
macro plan win; with none there, races from the prior year; with none, no line and a note saying why.

Discipline is `Workout.sport_detail` (e.g. `cycling/cyclocross`), the same key the race-start comparison
uses. `cycling/mountain` splits again by length: a race of `ULTRA_MIN` or more is "ultra MTB", shorter is
"MTB" (Coach judgment: the athlete's ultra MTB races must never be averaged with short XC ones). A race
with no `sport_detail` cannot be classified and is left out, never guessed.

Each race contributes its race-window curve (`WorkoutAnalytics.race_power_curve`, warm-up excluded) when it
has one, else its whole-file curve; the latter are counted in `left_out` so the fallback is visible.

The mean at a duration uses only races long enough to have that duration; the line stops where fewer than
two races contribute, unless only one race exists (then it is shown as that single race).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Sequence

from swim_coach.models import PriorRaceCurve, PriorRaceCurvePoint, Workout

ULTRA_MIN = 240  # Coach judgment: a 4 h+ mountain-bike race is an ultra; shorter ones are XC
PRIOR_YEAR_DAYS = 365  # Coach judgment: the fallback reaches back one year from the race
MIN_RACES_PER_POINT = 2  # Coach judgment: one race is not an average

_DISCIPLINE_NAMES = {
    "cycling/cyclocross": "CX",
    "cycling/road": "road",
    "cycling/gravel_cycling": "gravel",
    "cycling/indoor_cycling": "indoor",
}


def discipline_of(w: Workout) -> str | None:
    """The race's discipline key, or None when it cannot be told."""
    if not w.sport_detail:
        return None
    if w.sport_detail == "cycling/mountain":
        return "ultra MTB" if (w.duration_min or 0) >= ULTRA_MIN else "MTB"
    return _DISCIPLINE_NAMES.get(w.sport_detail, w.sport_detail.rsplit("/", 1)[-1].replace("_", " "))


def _earlier(w: Workout, current: Workout) -> bool:
    if w.date != current.date:
        return w.date < current.date
    return bool(w.started_at and current.started_at and w.started_at < current.started_at)


def _none(discipline: str | None, note: str, left_out: list[str]) -> PriorRaceCurve:
    return PriorRaceCurve(basis="none", discipline=discipline, label="Prior-race average", note=note, left_out=left_out)


def _curve_of(w: Workout) -> list:
    """The race's curve for the average: its race-window curve when it has one (a warm-up in the same file
    stays out), else the whole-file curve."""
    return w.analytics.race_power_curve or w.analytics.power_curve


def _mean_points(races: Sequence[Workout]) -> list[PriorRaceCurvePoint]:
    by_duration: dict[int, list[int]] = {}
    for w in races:
        for p in _curve_of(w):
            by_duration.setdefault(p.duration_s, []).append(p.watts)
    floor = 1 if len(races) == 1 else MIN_RACES_PER_POINT
    return [
        PriorRaceCurvePoint(duration_s=d, watts=int(round(sum(v) / len(v))), n=len(v))
        for d, v in sorted(by_duration.items())
        if len(v) >= floor
    ]


def _label(discipline: str, races: Sequence[Workout], basis: str) -> str:
    if len(races) == 1:
        return f"Prior {discipline} race ({races[0].date.isoformat()})"
    suffix = " (prior year)" if basis == "prior_year" else ""
    return f"Avg of {len(races)} prior {discipline} races{suffix}"


def prior_race_curve(
    current: Workout,
    workouts: Sequence[Workout],
    plan_range: tuple[date, date] | None,
    history_start: date | None = None,
) -> PriorRaceCurve:
    """The prior-race average for `current`. `workouts` is whatever the store holds (the caller's lookup);
    `plan_range` the macro plan's first and last date; `history_start` the earliest logged workout."""
    discipline = discipline_of(current)
    if discipline is None:
        return _none(None, "This race has no discipline set, so it cannot be compared with earlier races.", [])
    earlier = [
        w for w in workouts
        if w.id != current.id and w.sport == current.sport and w.effective_kind == "race" and _earlier(w, current)
    ]
    left_out: list[str] = []
    unclassified = [w for w in earlier if discipline_of(w) is None]
    if unclassified:
        left_out.append(f"{len(unclassified)} earlier race(s) with no discipline set")
    same = [w for w in earlier if discipline_of(w) == discipline]
    usable = [w for w in same if w.analytics is not None and w.analytics.power_curve]
    if len(same) > len(usable):
        left_out.append(f"{len(same) - len(usable)} earlier {discipline} race(s) with no power data")
    usable.sort(key=lambda w: (w.date, w.started_at.timestamp() if w.started_at else 0.0))

    on_plan = [w for w in usable if plan_range and plan_range[0] <= w.date <= plan_range[1]]
    year_start = current.date - timedelta(days=PRIOR_YEAR_DAYS)
    chosen, basis = (on_plan, "plan") if on_plan else ([w for w in usable if w.date >= year_start], "prior_year")
    if not chosen:
        note = f"No earlier {discipline} races on this plan or in the prior year to compare with."
        if history_start is not None and history_start > year_start:
            note += f" Logged history starts {history_start.isoformat()}."
        return _none(discipline, note, left_out)
    whole_file = [w for w in chosen if not w.analytics.race_power_curve]
    if whole_file:
        left_out.append(f"{len(whole_file)} earlier {discipline} race(s) averaged from the whole file (no race start detected)")
    return PriorRaceCurve(
        basis=basis, discipline=discipline, count=len(chosen), single=len(chosen) == 1,
        label=_label(discipline, chosen, basis), dates=[w.date for w in chosen],
        points=_mean_points(chosen), left_out=left_out,
    )
