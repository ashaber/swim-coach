"""Shared per-workout AU load computation.

Used by `routes/workouts.py` (the `GET`/`POST /api/workouts` HTTP response),
`tools.py`'s `get_workouts` tool (what the AI coach reads), and
`context.py`'s `render_focused_workout` (the workout-scoped chat context) --
so all three report the exact same `load_au`/`load_tier` for a given
workout, computed the exact same way, instead of the coach chat having no
real number at all and having to guess.

**Real bug this fixes, reported live**: an athlete asked the coach about a
load spike; the coach could see `rpe`/`avg_hr`/`max_hr` on each workout
(via `_summarize_workout`/`render_focused_workout`) but never the actual
computed tiered load or which tier produced it -- neither function called
`session_load` at all. For a workout with `rpe=None` but real `avg_hr`
data (should reach tier 2, HR-based TRIMP), the coach had nothing to read
except the raw fields and confabulated a plausible-sounding but wrong
explanation ("assumed a recovery ride, sRPE=1") instead of reporting the
real tier/value. The `/api/workouts` HTTP response already got this right
(engine/workouts-route-hr-trimp) -- this module extends the same fix to
every other place a workout's load gets described.
"""

from __future__ import annotations

from typing import Any

from swim_coach.load import estimate_hr_rest, session_load
from swim_coach.models import Athlete, Workout


def workout_load_au(
    workout: Workout, *, athlete: Athlete, hr_max: float | None, wellness: list[Any]
) -> tuple[float, str]:
    """`(load_au, load_tier)` for one workout -- the same `session_load`
    call `routes/workouts.py`'s `_attach_load` already made, factored out
    here so every caller reports the identical number. `hr_max` is
    estimated ONCE by the caller from the athlete's full workout history
    (`swim_coach.load.estimate_hr_max`) -- never recomputed per workout,
    since it's the same estimate regardless of which workout is being
    scored. `hr_rest` is estimated here per-workout since it's genuinely
    date-dependent (`estimate_hr_rest`'s `as_of` parameter). `lthr_bpm`
    (when the athlete has set one -- see `engine/swim_coach/load.py`'s
    `_normalize_trimp_to_lthr_hour`/`library/15-tiered-session-load.md`)
    rescales tier 2's raw TRIMP onto TSS's own "100 = one hour at
    threshold" convention; a no-op when unset, same as `session_load`
    itself."""
    hr_rest = estimate_hr_rest(wellness, workout.date)
    sl = session_load(
        workout,
        hr_max=hr_max,
        hr_rest=hr_rest,
        sex=athlete.sex,
        css_pace_s_per_100m=athlete.css_pace_s_per_100m,
        lthr_bpm=athlete.lthr_bpm,
    )
    return round(sl.value, 1), sl.tier
