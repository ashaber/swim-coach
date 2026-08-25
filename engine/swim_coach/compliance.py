"""Per-workout planned-vs-actual matching and compliance interpretation.

Two pure functions, no I/O, no LLM calls:

- `match_workout_to_session` finds the one `Session` (if any) a given
  `Workout` should be compared against. Server-side port of
  `web/src/history.js`'s `findWorkoutForSession`, with the match direction
  flipped -- the JS original takes one session and searches many workouts
  (the History feed needs, for each planned session, "was this done?"); this
  takes one workout and searches many sessions (a compliance caller has one
  freshly-logged workout and needs "which planned session was this for?").
  The matching semantics are identical, only the iteration direction
  differs: exact `planned_session_id` match wins outright; otherwise fall
  back to same-sport/same-date among sessions with no linked id. See that
  function's docstring for the dangling-id edge case this port preserves.

- `workout_compliance` INTERPRETS already-computed data (workout fields,
  `WorkoutAnalytics`, the matched `Session`'s planned targets) -- it never
  recomputes anything `load.py`, `zones.py`, or `analytics.py` already own.

This is deliberately NOT the same concept as `load.compliance()`
(load.py, ~line 207): that function is an AGGREGATE weekly-volume
percentage -- summed planned distance vs. summed completed distance across
many sessions/workouts over a period (e.g. one week). `workout_compliance`
here is a PER-WORKOUT interpretation of one workout against the one session
it was (or wasn't) planned against -- distance/duration delta percentages,
an intensity-match verdict, and a quality-flag summary. They share the
English word "compliance" because both answer "did the athlete do what was
planned," but at different granularities and for different callers; neither
calls the other.

Known Phase-1 gap: `intensity_match` can only ever return "unknown" today.
Comparing a workout's *actual* training zone against `session.intensity`'s
*planned* zone would require classifying the workout's actual pace/HR into
a Z1-Z5 zone, and no such classification function exists yet anywhere in
this codebase -- `zones.py` only builds the CSS-anchored zone table
(`zone_table`) and infers an open-water pace estimate (`infer_ow_pace`); it
has no "given this pace/HR, which zone was this" classifier. Inventing one
here would be exactly the kind of un-cited physiology threshold CLAUDE.md's
evidence-discipline rule prohibits, so this module deliberately does not.
"""

from __future__ import annotations

from swim_coach.analytics import CARDIAC_DRIFT_FLAG_PCT
from swim_coach.models import Session, Workout, WorkoutAnalytics, WorkoutCompliance

SWOLF_DEGRADATION_FLAG_PCT = 5.0
# Coach judgment: a first-quarter-to-last-quarter SWOLF increase of 5% or
# more (i.e. `WorkoutAnalytics.swolf_degradation_pct >=
# SWOLF_DEGRADATION_FLAG_PCT`) is treated as a notable within-session
# stroke-efficiency drop, worth surfacing in the compliance quality summary.
# No library/ source calibrates a specific magnitude for this athlete
# population yet. Chosen to match CARDIAC_DRIFT_FLAG_PCT's magnitude
# (analytics.py, 5.0%) since both are first-half/first-quarter vs.
# second-half/last-quarter degradation checks over a single session, not a
# validated swim-specific cutoff -- see library/11-workout-analytics.md's
# "SWOLF as a stroke-efficiency proxy" section, which explicitly names
# SWOLF-vs-independent-efficiency-measure validation as an open gap
# (analytics.py's module docstring "provisional pending a full research
# pass" framing, inherited here).


def match_workout_to_session(workout: Workout, sessions: list[Session]) -> Session | None:
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
    3. Otherwise, `None`.

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
    return None


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


def workout_compliance(workout: Workout, session: Session | None) -> WorkoutCompliance:
    """Interpret `workout` against its matched `session` (from
    `match_workout_to_session`, or `None` if nothing matched).

    Does NOT recompute anything -- reads `workout`/`session` fields and
    `workout.analytics` (already produced by `analytics.compute_analytics`)
    as-is. See module docstring for how this differs from `load.compliance
    ()`'s aggregate weekly number, and for the Phase-1 `intensity_match`
    gap.

    If `session is None` there is nothing to compare against: returns
    `matched=False` with every delta/quality field `None`
    (`intensity_match="unknown"`, since that field can't itself be `None`).
    This applies even when `workout.analytics` is populated -- an unmatched
    workout gets no quality summary either, by design (see the class
    docstring / this function's None-session branch): a quality summary is
    part of a compliance READING against a plan, not a standalone workout
    report.
    """
    if session is None:
        return WorkoutCompliance(
            matched=False,
            distance_delta_pct=None,
            duration_delta_pct=None,
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

    quality_summary = _quality_summary(workout.analytics) if workout.analytics is not None else None

    return WorkoutCompliance(
        matched=True,
        distance_delta_pct=distance_delta_pct,
        duration_delta_pct=duration_delta_pct,
        intensity_match="unknown",  # see module docstring: Phase-1 gap, no zone classifier exists
        quality_summary=quality_summary,
    )
