"""Workout analysis dispatch: one public entry point, `Workout.analyze(ctx)`.

Every caller (upload ingest, intervals.icu sync, plan matching, `reanalyze_workout`,
`pull_activity_stream`, the CLI) builds an `AnalysisContext` and calls `workout.analyze(ctx)`.
The context carries the athlete (ALL thresholds come from it: FTP, LTHR, home elevation, ...),
the matched planned session, the workout's `SessionKind`, the stream, and the athlete's earlier
workouts (for the power-curve 42/90-day bests). A per-sport `WorkoutAnalyzer`, looked up in
`ANALYZERS`, decides what to compute; a sport with no analyzer gets `DefaultAnalyzer` (the base
numbers -- pace splits, SWOLF, drift, pauses, power -- with no interval/verdict layer). Adding a
run or swim analyzer is one registry entry; no call site changes.

Behaviour of `BikeAnalyzer` by kind (`models.SessionKind`):
  workout   -- prescription path: the matched session's structure / zone / text steer the reps
  race      -- race path: race-start read and per-lap numbers, no decoupling read
  free_ride -- free effort detection (a repeating work/recovery lap pattern counts as structure)
  warmup    -- base analytics + power curve only: never evaluated or scored
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol, Sequence

from swim_coach.analytics import compute_analytics
from swim_coach.models import Athlete, Event, Session, SessionKind, Workout, WorkoutAnalytics
from swim_coach.power_curve import BEST_WINDOWS_DAYS, annotate_bests

if TYPE_CHECKING:
    from swim_coach.store import StoreInterface

_log = logging.getLogger("swim_coach.analysis")


def _warn(what: str, slug: str, exc: Exception) -> None:
    _log.warning("analysis context: %s lookup failed for %s: %s", what, slug, exc)


@dataclass(frozen=True)
class AnalysisContext:
    """Everything an analyzer may need besides the workout itself."""

    athlete: Athlete | None = None
    session: Session | None = None
    kind: SessionKind = "free_ride"
    series: dict | None = None
    # Coach-supplied per-interval power target (reanalyze_workout), for a file with no structure.
    target_w: float | None = None
    # Wall-clock minutes when the caller has them from a fresh parse; else the workout's own.
    elapsed_min: float | None = None
    # The athlete's other workouts, for the power curve's 42/90-day bests.
    prior_workouts: Sequence[Workout] = field(default_factory=tuple)


class WorkoutAnalyzer(Protocol):
    def analyze(self, workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics: ...


def _elapsed_min(workout: Workout, ctx: AnalysisContext) -> float | None:
    if ctx.elapsed_min is not None:
        return ctx.elapsed_min
    return workout.analytics.elapsed_min if workout.analytics else None


def _planned_zone(session: Session | None) -> str | None:
    zone = (session.intensity or {}).get("zone") if session else None
    return zone if isinstance(zone, str) else None


def _session_text(session: Session | None) -> str | None:
    if session is None:
        return None
    return " ".join(t for t in (session.purpose, session.structure) if t) or None


def _base_analytics(workout: Workout, ctx: AnalysisContext, **interval_kwargs) -> WorkoutAnalytics:
    return compute_analytics(
        laps=workout.laps,
        lengths=workout.lengths,
        pauses=workout.pauses,
        series=ctx.series,
        elapsed_min=_elapsed_min(workout, ctx),
        moving_min=workout.duration_min,
        sport=workout.sport,
        **interval_kwargs,
    )


def annotate_power_curve_bests(workout: Workout, analytics: WorkoutAnalytics, ctx: AnalysisContext) -> WorkoutAnalytics:
    """Fill the curve's 42/90-day-best comparison from the athlete's earlier rides' stored
    curves (rides without a curve are skipped)."""
    if not analytics.power_curve:
        return analytics
    since = workout.date - timedelta(days=max(BEST_WINDOWS_DAYS))
    prior = [
        ((workout.date - w.date).days, w.analytics.power_curve)
        for w in ctx.prior_workouts
        if w.id != workout.id
        and since <= w.date < workout.date
        and w.analytics is not None
        and w.analytics.power_curve
    ]
    return analytics.model_copy(update={"power_curve": annotate_bests(analytics.power_curve, prior)})


class DefaultAnalyzer:
    """Every sport without its own analyzer: the base numbers, no interval/verdict layer."""

    def analyze(self, workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics:
        return annotate_power_curve_bests(workout, _base_analytics(workout, ctx, with_intervals=False), ctx)


class BikeAnalyzer:
    """Rides: base analytics + interval analysis + power curve + bests; the interval layer
    follows `ctx.kind` (see the module docstring)."""

    def analyze(self, workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics:
        if ctx.kind == "warmup":
            return annotate_power_curve_bests(workout, _base_analytics(workout, ctx, with_intervals=False), ctx)
        athlete, session = ctx.athlete, ctx.session
        analytics = _base_analytics(
            workout,
            ctx,
            interval_target_w=ctx.target_w,
            # a coach-supplied target replaces the prescription (reanalyze_workout)
            prescribed_structure=session.structured if session and ctx.target_w is None else None,
            planned_zone=_planned_zone(session),
            home_elevation_m=athlete.home_elevation_m if athlete else None,
            ftp_watts=athlete.ftp_watts if athlete else None,
            lthr_bpm=athlete.lthr_bpm if athlete else None,
            race=ctx.kind == "race",
            session_text=_session_text(session),
        )
        return annotate_power_curve_bests(workout, analytics, ctx)


ANALYZERS: dict[str, WorkoutAnalyzer] = {"bike": BikeAnalyzer()}
DEFAULT_ANALYZER: WorkoutAnalyzer = DefaultAnalyzer()


def analyzer_for(sport: str) -> WorkoutAnalyzer:
    return ANALYZERS.get(sport, DEFAULT_ANALYZER)


def has_detailed_analyzer(sport: str) -> bool:
    return sport in ANALYZERS


def analyze_workout(workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics:
    """Target of `Workout.analyze`."""
    return analyzer_for(workout.sport).analyze(workout, ctx)


# --- kind derivation ----------------------------------------------------------------------


def _event_sport(workout_sport: str) -> str | None:
    if workout_sport.startswith("swim"):
        return "swim"
    return workout_sport if workout_sport == "bike" else None


def derive_workout_kind(workout: Workout, session: Session | None, events: Sequence[Event]) -> SessionKind:
    """The matched session's explicit kind; else an athlete event on that date in the workout's
    sport -> race (this also rescues a not-yet-backfilled untagged session); else the session's
    default ("workout"), or free_ride with no session. (`kind_override` is applied by the caller, see
    `Workout.effective_kind`.)"""
    if session is not None and session.kind is not None:
        return session.kind
    sport = _event_sport(workout.sport)
    if sport is not None and any(e.event_date == workout.date and e.primary_sport == sport for e in events):
        return "race"
    return session.effective_kind if session is not None else "free_ride"


def build_analysis_context(
    store: "StoreInterface",
    slug: str,
    workout: Workout,
    *,
    session: Session | None = None,
    series: dict | None = None,
    target_w: float | None = None,
    elapsed_min: float | None = None,
) -> AnalysisContext:
    """Load the athlete, events and prior workouts from `store` and derive the kind. Stamps the
    derived kind on `workout.kind` (the override, if any, still wins in the returned context).
    Every lookup is best-effort: a failure leaves that piece out rather than blocking analytics.
    """
    try:
        athlete = store.load_athlete(slug)
    except Exception as exc:  # noqa: BLE001 - analytics must still compute without thresholds
        _warn("athlete", slug, exc)
        athlete = None
    try:
        events = store.load_events(slug)
    except Exception as exc:  # noqa: BLE001 - a missing event list reads as "not a race"
        _warn("events", slug, exc)
        events = []
    prior: tuple[Workout, ...] = ()
    if series and series.get("power_w"):  # only a power stream has a curve to compare
        try:
            since = workout.date - timedelta(days=max(BEST_WINDOWS_DAYS))
            prior = tuple(w for w in store.list_workouts(slug, since=since) if w.id != workout.id)
        except Exception as exc:  # noqa: BLE001 - the curve is still valid without the comparison
            _warn("prior_workouts", slug, exc)
    workout.kind = derive_workout_kind(workout, session, events)
    return AnalysisContext(
        athlete=athlete,
        session=session,
        kind=workout.effective_kind or workout.kind,
        series=series,
        target_w=target_w,
        elapsed_min=elapsed_min,
        prior_workouts=prior,
    )
