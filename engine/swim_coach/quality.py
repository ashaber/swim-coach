"""Per-workout planned-vs-actual matching and execution-quality interpretation.

Two pure functions, no I/O, no LLM calls:

- `match_workout_to_session` finds the one `Session` (if any) a given
  `Workout` should be compared against. Server-side port of
  `web/src/history.js`'s `findWorkoutForSession`, with the match direction
  flipped -- the JS original takes one session and searches many workouts
  (the History feed needs, for each planned session, "was this done?"); this
  takes one workout and searches many sessions (a caller here has one
  freshly-logged workout and needs "which planned session was this for?").
  The matching semantics are identical, only the iteration direction
  differs: exact `planned_session_id` match wins outright; otherwise fall
  back to same-sport/same-date among sessions with no linked id. See that
  function's docstring for the dangling-id edge case this port preserves.

- `workout_quality` INTERPRETS already-computed data (workout fields,
  `WorkoutAnalytics`, the matched `Session`'s planned targets) -- it never
  recomputes anything `load.py`, `zones.py`, or `analytics.py` already own.

Naming history (see `IDEAS.md`'s resolved IDEA 006): this module was
originally named `compliance.py` and its result type `WorkoutCompliance`,
which collided with the pre-existing, library-cited `load.compliance()`
(load.py, ~line 207) -- a genuinely different concept at a different
granularity. `load.compliance()` is the one AGGREGATE weekly-volume
percentage in this codebase -- summed planned distance vs. summed completed
distance across many sessions/workouts over a period (e.g. one week), with
the real 70%/90% thresholds that drive `/adapt`'s repeat/hold/advance
decision. It remains the sole authoritative "compliance" in this codebase.
`workout_quality` here is a PER-WORKOUT interpretation of one workout
against the one session it was (or wasn't) planned against -- distance/
duration delta percentages, an intensity-match verdict, and a quality-flag
summary (cardiac-drift / SWOLF degradation). Different granularity,
different callers; neither calls the other, and neither is a substitute for
the other's number.

`intensity_match` is read from the prescription-aware interval analyzer
(`execution_score.intensity_match`): "match"/"mismatch" from the share of
completed reps whose average power sat in the prescribed band, "unknown"
when no prescription was located or no watts band resolved. It still never
classifies pace/HR into a zone itself -- that would be an un-cited threshold.
`execution` is the 0-100 execution score with its breakdown
(`execution_score.workout_execution_score`), `None` when unmatched.
"""

from __future__ import annotations

from swim_coach.analytics import CARDIAC_DRIFT_FLAG_PCT
from swim_coach.execution_score import intensity_match, workout_execution_score
from swim_coach.load import session_load, session_target_load_au
from swim_coach.models import Athlete, Session, Workout, WorkoutAnalytics, WorkoutQuality

ADJACENT_DAY_WINDOW = 1
# Coach judgment: a workout may belong to a session planned one day either side
# (calendar-day resolution of late-evening rides, or a session moved a day).

SWOLF_DEGRADATION_FLAG_PCT = 5.0
# Coach judgment: a first-quarter-to-last-quarter SWOLF increase of 5% or
# more (i.e. `WorkoutAnalytics.swolf_degradation_pct >=
# SWOLF_DEGRADATION_FLAG_PCT`) is treated as a notable within-session
# stroke-efficiency drop, worth surfacing in the quality summary.
# No library/ source calibrates a specific magnitude for this athlete
# population yet. Chosen to match CARDIAC_DRIFT_FLAG_PCT's magnitude
# (analytics.py, 5.0%) since both are first-half/first-quarter vs.
# second-half/last-quarter degradation checks over a single session, not a
# validated swim-specific cutoff -- see library/11-workout-analytics.md's
# "SWOLF as a stroke-efficiency proxy" section, which explicitly names
# SWOLF-vs-independent-efficiency-measure validation as an open gap
# (analytics.py's module docstring "provisional pending a full research
# pass" framing, inherited here).


def match_workout_to_session(
    workout: Workout,
    sessions: list[Session],
    *,
    other_workouts: list[Workout] | None = None,
) -> Session | None:
    """Find the planned `Session` (if any) this `Workout` should be compared
    against.

    Matching rule (ported from `web/src/history.js`'s
    `findWorkoutForSession`, direction flipped -- see module docstring):

    1. If `workout.planned_session_id` is set, look for a `session` in
       `sessions` whose `id` equals it. If found, that session wins
       outright -- even if some OTHER session in the list would also
       "coincidentally" match on sport+date.
    2. If no `planned_session_id` is set on the workout, fall back to the
       first `session` in `sessions` with matching `sport` and `date`.
    3. Still none: a +-1 day window on the same sport, accepted only when
       EXACTLY ONE unmatched session fits (an evening ride the calendar
       resolved a day off, or a session ridden a day early/late). "Unmatched"
       means no other workout in `other_workouts` (when the caller supplies
       them) links to it by `planned_session_id` or sits on its own date with
       its sport. Two candidates is ambiguous and matches nothing.
    4. Otherwise, `None`.

    Dangling-id edge case (deliberate, matches the JS original): if
    `workout.planned_session_id` IS set but no session in `sessions` carries
    that id (e.g. the plan week was regenerated and the old session no
    longer exists), this returns `None` -- it does NOT fall through to the
    sport+date fallback, even if a same-sport/same-date session happens to
    be present. The JS original's fallback branch is gated on `!w.
    planned_session_id` (the workout having NO linked id at all), so a
    workout that claims a specific (now-missing) session is never silently
    reattached to a different one.
    """
    if workout.planned_session_id is not None:
        for session in sessions:
            if session.id == workout.planned_session_id:
                return session
        return None

    for session in sessions:
        if session.sport == workout.sport and session.date == workout.date:
            return session

    others = [w for w in (other_workouts or []) if w.id != workout.id]
    claimed_ids = {w.planned_session_id for w in others if w.planned_session_id is not None}
    occupied = {(w.sport, w.date) for w in others}
    candidates = [
        s
        for s in sessions
        if s.sport == workout.sport
        and abs((s.date - workout.date).days) <= ADJACENT_DAY_WINDOW
        and s.id not in claimed_ids
        and (s.sport, s.date) not in occupied
    ]
    return candidates[0] if len(candidates) == 1 else None


def _quality_summary(analytics: WorkoutAnalytics) -> str:
    """Short, factual one-or-two-sentence read of `analytics`. Only flags
    what's notable per this module's `Coach judgment:` thresholds; says so
    plainly when nothing is."""
    notes: list[str] = []

    if (
        analytics.cardiac_drift_pct is not None
        and analytics.cardiac_drift_pct >= CARDIAC_DRIFT_FLAG_PCT
    ):
        notes.append(
            f"Cardiac drift was {analytics.cardiac_drift_pct:.1f}%, at or above the "
            f"{CARDIAC_DRIFT_FLAG_PCT:.0f}% aerobic-decoupling flag."
        )

    if (
        analytics.swolf_degradation_pct is not None
        and analytics.swolf_degradation_pct >= SWOLF_DEGRADATION_FLAG_PCT
    ):
        notes.append(
            f"SWOLF degraded {analytics.swolf_degradation_pct:.1f}% from the first to "
            "last quarter of the session, suggesting stroke efficiency dropped late."
        )

    if not notes:
        return "No notable quality flags -- cardiac drift and SWOLF trend both look normal."
    return " ".join(notes)


def workout_quality(workout: Workout, session: Session | None, *, athlete: Athlete) -> WorkoutQuality:
    """Interpret `workout` against its matched `session` (from
    `match_workout_to_session`, or `None` if nothing matched).

    Does NOT recompute anything except `load_delta_pct` (see below) --
    reads `workout`/`session` fields and `workout.analytics` (already
    produced by `analytics.compute_analytics`) as-is. See module docstring
    for how this differs from `load.compliance()`'s aggregate weekly
    number, and for the Phase-1 `intensity_match` gap.

    If `session is None` there is nothing to compare against: returns
    `matched=False` with every delta/quality field `None`
    (`intensity_match="unknown"`, since that field can't itself be `None`).
    This applies even when `workout.analytics` is populated -- an unmatched
    workout gets no quality summary either, by design (see the class
    docstring / this function's None-session branch): a quality summary is
    part of a READING against a plan, not a standalone workout report.

    `athlete` (keyword-only, required) -- new in this build, alongside
    `load_delta_pct` -- is `session_target_load_au`'s required parameter and
    supplies `session_load`'s `sex`/`css_pace_s_per_100m` context for its
    pace-based (tier 3) fallback. **Known, deliberate limitation**: this
    function has no access to this athlete's full workout/wellness history
    (it only ever sees the one `workout` being interpreted), so it can never
    supply `session_load`'s `hr_max`/`hr_rest` kwargs -- tier 2 (HR-based
    TRIMP) is unreachable from here even when the workout has HR data,
    falling through to tier 3 (pace) or tier 4 (duration-only) instead.
    Callers that need the full-fidelity actual load for other purposes
    (e.g. `daily_loads`) should keep calling `session_load` directly with
    real history; `load_delta_pct` here is a best-effort per-workout
    validation signal, not a replacement for that.

    `load_delta_pct` is `None` whenever `matched=False` (nothing to compare
    against), same convention as `distance_delta_pct`/`duration_delta_pct`.
    When matched, it's `(actual - target) / target * 100` rounded to one
    decimal, where `target = session_target_load_au(session, athlete)`
    (always `> 0`, so no zero-division guard is needed) and
    `actual = session_load(workout, sex=athlete.sex,
    css_pace_s_per_100m=athlete.css_pace_s_per_100m).value`. Purely
    informational -- see `cli.py`'s `validate-load-model` diagnostic for
    the aggregate view across an athlete's history, and this module's
    docstring / `library/17-wellness-load-integration.md`'s "Recommendation,
    not yet built" precedent for why this is never wired into `adapt.py`.
    """
    if session is None:
        return WorkoutQuality(
            matched=False,
            distance_delta_pct=None,
            duration_delta_pct=None,
            load_delta_pct=None,
            intensity_match="unknown",
            quality_summary=None,
        )

    distance_delta_pct: float | None = None
    if session.distance_m:
        distance_delta_pct = round(
            (workout.distance_m - session.distance_m) / session.distance_m * 100, 1
        )

    duration_delta_pct = round(
        (workout.duration_min - session.duration_min) / session.duration_min * 100, 1
    )

    target_load_au = session_target_load_au(session, athlete)
    actual_load_au = session_load(
        workout,
        sex=athlete.sex,
        css_pace_s_per_100m=athlete.css_pace_s_per_100m,
        ftp_watts=athlete.ftp_watts,
    ).value
    load_delta_pct = round((actual_load_au - target_load_au) / target_load_au * 100, 1)

    quality_summary = _quality_summary(workout.analytics) if workout.analytics is not None else None
    intervals = workout.analytics.intervals if workout.analytics is not None else None

    return WorkoutQuality(
        matched=True,
        distance_delta_pct=distance_delta_pct,
        duration_delta_pct=duration_delta_pct,
        load_delta_pct=load_delta_pct,
        intensity_match=intensity_match(intervals),
        quality_summary=quality_summary,
        execution=workout_execution_score(intervals, workout, session),
    )
