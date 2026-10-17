"""Workout analysis dispatch: one public entry point, `Workout.analyze(ctx)`.

Every caller (upload ingest, intervals.icu sync, plan matching, `reanalyze_workout`,
`pull_activity_stream`, the CLI) builds an `AnalysisContext` and calls `workout.analyze(ctx)`.
The context carries the athlete (ALL thresholds come from it: FTP, LTHR, home elevation, ...),
the matched planned session, the workout's `SessionKind`, the stream, and the athlete's earlier
workouts (for the power-curve 42/90-day bests). A per-sport `WorkoutAnalyzer`, looked up in
`ANALYZERS`, decides what to compute AND owns its `WorkoutAnalytics` fields and its coach view
(`coach_view`): `BASE_FIELDS` are common to every sport, each analyzer's `fields` are its own.
A sport with no analyzer gets `DefaultAnalyzer` (base numbers, no interval/verdict layer; coach
view = BASE_FIELDS only). Adding a run analyzer is one registry entry; no call site changes.

Behaviour of `BikeAnalyzer` by kind (`models.SessionKind`):
  workout   -- prescription path: the matched session's structure / zone / text steer the reps
  race      -- race path: race-start read and per-lap numbers, no decoupling read
  free_ride -- free effort detection (a repeating work/recovery lap pattern counts as structure),
               plus the `free_ride` read (`free_ride.py`: where the time went, notable efforts,
               matches burned, cost vs the week, steady-stretch drift, data quality). A "workout"
               ride whose matched session carries no structured prescription gets the same read.
  opener / warmup -- base analytics + power curve only: never evaluated or scored
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import TYPE_CHECKING, Protocol, Sequence

from swim_coach.analytics import compute_analytics
from swim_coach.models import Athlete, Event, Session, SessionKind, Workout, WorkoutAnalytics
from swim_coach.bike_coach_view import shape_ride_view
from swim_coach.course_sectors import build_course_sectors
from swim_coach.free_ride import FREE_READ_KINDS, read_free_ride
from swim_coach.mtb_dynamics import build_mtb_dynamics
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
    # Planned sessions on the days around the workout (the free-ride read's cost-vs-week note).
    neighbors: Sequence[Session] = field(default_factory=tuple)


# Sport-agnostic fields every analyzer's coach view keeps.
BASE_FIELDS: frozenset[str] = frozenset(
    {"cardiac_drift_pct", "elapsed_min", "moving_min", "pause_total_min", "pause_count"}
)
SWIM_FIELDS: frozenset[str] = frozenset(
    {
        "split_label",
        "first_half_pace_s_per_100m",
        "second_half_pace_s_per_100m",
        "swolf_first_quarter",
        "swolf_last_quarter",
        "swolf_degradation_pct",
    }
)
BIKE_FIELDS: frozenset[str] = frozenset(
    {"intervals", "avg_power_w", "normalized_power_w", "power_curve", "free_ride", "mtb_dynamics", "course_sectors"}
)


def prune_nulls(x):
    """Drop None values and empty lists/dicts recursively (the coach does not need to read
    what is absent)."""
    if isinstance(x, dict):
        return {
            k: v for k, v in ((k, prune_nulls(v)) for k, v in x.items()) if v is not None and v != [] and v != {}
        }
    if isinstance(x, list):
        return [prune_nulls(v) for v in x]
    return x


class WorkoutAnalyzer(Protocol):
    fields: frozenset[str]
    detailed: bool  # has an interval/verdict layer
    structured_is_key: bool  # a structured session of this sport is a key (interval) session

    def analyze(self, workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics: ...

    def coach_view(self, analytics: WorkoutAnalytics | None) -> dict | None: ...

    def needs_neighbors(self, kind: SessionKind) -> bool:
        """Whether analysing a workout of this kind reads the planned sessions around it
        (`AnalysisContext.neighbors`); the context builder only loads them when asked."""
        ...


class _CoachViewMixin:
    """`coach_view`: the dump restricted to BASE_FIELDS plus this analyzer's own `fields`, shaped by
    `_shape` (identity by default), nulls pruned."""

    fields: frozenset[str] = frozenset()
    detailed: bool = False
    # Whether a structured session of this sport is an interval session that fatigues the
    # neighbouring days (Coach judgment; library/03 load monitoring: hard endurance work, not
    # strength/recovery, is what the next day's quality depends on). Endurance analyzers set True.
    structured_is_key: bool = False

    def needs_neighbors(self, kind: SessionKind) -> bool:
        return False

    def _shape(self, out: dict, analytics: WorkoutAnalytics) -> dict:
        return out

    def coach_view(self, analytics: WorkoutAnalytics | None) -> dict | None:
        if analytics is None:
            return None
        keep = BASE_FIELDS | self.fields
        out = {k: v for k, v in analytics.model_dump(mode="json").items() if k in keep}
        return prune_nulls(self._shape(out, analytics))


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


class DefaultAnalyzer(_CoachViewMixin):
    """Every sport without its own analyzer: the base numbers, no interval/verdict layer."""

    def analyze(self, workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics:
        return annotate_power_curve_bests(workout, _base_analytics(workout, ctx, with_intervals=False), ctx)


COURSE_LAP_KINDS: tuple[SessionKind, ...] = ("race", "opener")  # kinds whose laps are course repeats
GPS_LAP_KINDS: tuple[SessionKind, ...] = ("race",)  # kinds whose laps come from the GPS start marker first
UNSCORED_KINDS: tuple[SessionKind, ...] = ("opener", "warmup")  # load + base analytics + curve only


class SwimAnalyzer(_CoachViewMixin):
    """Pool and open-water swims: the base analytics (pace halves, SWOLF, drift, pauses),
    no interval/verdict layer."""

    fields = SWIM_FIELDS
    structured_is_key = True

    def analyze(self, workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics:
        return annotate_power_curve_bests(workout, _base_analytics(workout, ctx, with_intervals=False), ctx)


class BikeAnalyzer(_CoachViewMixin):
    """Rides: base analytics + interval analysis + power curve + bests; the interval layer
    follows `ctx.kind` (see the module docstring). Coach view: `bike_coach_view`."""

    fields = BIKE_FIELDS
    detailed = True
    structured_is_key = True

    def _shape(self, out: dict, analytics: WorkoutAnalytics) -> dict:
        return shape_ride_view(out, analytics)

    def analyze(self, workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics:
        analytics = self._analyze_by_kind(workout, ctx)
        # Device dynamics are descriptive, so every kind gets them when the data is there. Course
        # sectors compare repeated laps of a course: a race or an unstructured ride, never a
        # structured workout whose laps are its reps.
        found = {
            "mtb_dynamics": build_mtb_dynamics(workout, ctx.series),
            "course_sectors": (
                build_course_sectors(workout, ctx.series, prefer_gps=ctx.kind in GPS_LAP_KINDS)
                if self._compares_course_laps(ctx)
                else None
            ),
        }
        return analytics.model_copy(update={k: v for k, v in found.items() if v is not None})

    def _analyze_by_kind(self, workout: Workout, ctx: AnalysisContext) -> WorkoutAnalytics:
        if ctx.kind in UNSCORED_KINDS:
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
        analytics = annotate_power_curve_bests(workout, analytics, ctx)
        if not self._reads_as_free_ride(ctx):
            return analytics
        read = read_free_ride(
            workout=workout,
            analytics=analytics,
            series=ctx.series,
            ftp_watts=athlete.ftp_watts if athlete else None,
            lthr_bpm=athlete.lthr_bpm if athlete else None,
            intent_zone=_planned_zone(session),
            neighbors=[s for s in ctx.neighbors if is_key_session(s)],
            prior_workouts=ctx.prior_workouts,
        )
        return analytics.model_copy(update={"free_ride": read})

    def needs_neighbors(self, kind: SessionKind) -> bool:
        return kind in FREE_READ_KINDS

    @staticmethod
    def _compares_course_laps(ctx: AnalysisContext) -> bool:
        """Races, pre-race openers (a lap-per-circuit pre-ride) and unstructured rides repeat a
        course; a structured workout's laps are its reps."""
        return ctx.kind in COURSE_LAP_KINDS or BikeAnalyzer._reads_as_free_ride(ctx)

    @staticmethod
    def _reads_as_free_ride(ctx: AnalysisContext) -> bool:
        """A free ride, or a "workout" ride whose session prescribes no structure (nothing to
        score the reps against, so the free-ride read is the useful one)."""
        if ctx.kind == "free_ride":
            return True
        return ctx.kind == "workout" and (ctx.session is None or ctx.session.structured is None)


_SWIM = SwimAnalyzer()
ANALYZERS: dict[str, WorkoutAnalyzer] = {"bike": BikeAnalyzer(), "swim_pool": _SWIM, "swim_ow": _SWIM}
DEFAULT_ANALYZER: WorkoutAnalyzer = DefaultAnalyzer()


def analyzer_for(sport: str) -> WorkoutAnalyzer:
    return ANALYZERS.get(sport, DEFAULT_ANALYZER)


KEY_ZONES: frozenset[str] = frozenset({"Z4", "Z5"})  # a planned workout this hard is "key"


def is_key_session(session: Session) -> bool:
    """A session hurt by fatigue the day before/after: a race, or a planned workout in Z4/Z5, or a
    structured one of a sport whose analyzer says structured work is key (endurance sports;
    strength/recovery never, however structured)."""
    if session.effective_kind == "race":
        return True
    if session.effective_kind != "workout":
        return False
    if (session.intensity or {}).get("zone") in KEY_ZONES:
        return True
    return session.structured is not None and analyzer_for(session.sport).structured_is_key


def has_detailed_analyzer(sport: str) -> bool:
    return analyzer_for(sport).detailed


def analytics_for_coach(analytics: WorkoutAnalytics | None, sport: str) -> dict | None:
    """`WorkoutAnalytics` as the JSON dict the coach reads on per-workout detail surfaces (never
    the always-loaded context): the sport's analyzer decides which fields and in what order."""
    return analyzer_for(sport).coach_view(analytics)


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
    if sport is not None:
        same_sport = [e for e in events if e.primary_sport == sport]
        # any member race date (of a group or not) is a race day; a rest day in a span is not
        if any(e.event_date == workout.date for e in same_sport):
            return "race"
    return session.effective_kind if session is not None else "free_ride"


def _neighbor_sessions(
    store: "StoreInterface", slug: str, workout: Workout, session: Session | None
) -> tuple[Session, ...]:
    """Key sessions (any sport) planned the day before / after the workout (best-effort, like
    every lookup)."""
    found: dict[str, Session] = {}
    for day in (workout.date - timedelta(days=1), workout.date + timedelta(days=1)):
        year, week, _ = day.isocalendar()
        try:
            plan = store.load_week(slug, f"{year}-W{week:02d}")
        except Exception as exc:  # noqa: BLE001 - the cost note reads fine without neighbours
            _warn("neighbor sessions", slug, exc)
            continue
        for s in (plan.sessions if plan else []):
            if s.date == day and (session is None or s.id != session.id) and is_key_session(s):
                found[str(s.id)] = s
    return tuple(found.values())


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
    kind = workout.effective_kind or workout.kind
    return AnalysisContext(
        athlete=athlete,
        session=session,
        kind=kind,
        series=series,
        target_w=target_w,
        elapsed_min=elapsed_min,
        prior_workouts=prior,
        neighbors=_neighbor_sessions(store, slug, workout, session) if analyzer_for(workout.sport).needs_neighbors(kind) else (),
    )
