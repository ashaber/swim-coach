"""Shared enrichment for a freshly parsed `WorkoutDraft`: durable raw-file
copy, time-series sidecar, and derived analytics.

Extracted from `routes/workouts.py::ingest_workout` (the athlete-facing
`.fit`/`.tcx`/`.csv` upload route) so `backend/app/sync.py` (the
intervals.icu auto-sync job) can run the exact same enrichment a manual
upload gets, without either caller duplicating the logic. Both callers are
responsible for constructing/tearing down `tmp_path`'s parent temp
directory themselves -- this function only reads from it.

Deliberately mirrors the pre-extraction inline block byte-for-byte in
behavior: `tests/api/test_workouts_ingest_route.py` is the extraction's
safety net and must keep passing unchanged.
"""

from __future__ import annotations

from pathlib import Path
from datetime import date, timedelta
from uuid import UUID, uuid4

from swim_coach.analytics import compute_analytics
from swim_coach.models import Athlete, Session, Workout, WorkoutAnalytics
from swim_coach.parse_files import WorkoutDraft
from swim_coach.power_curve import BEST_WINDOWS_DAYS, annotate_bests
from swim_coach.quality import match_workout_to_session
from swim_coach.store import StoreInterface

from app.logging_config import get_logger

log = get_logger("app.enrich")


RACE_PURPOSE_PREFIX = "RACE — "


def analysis_context(
    store: StoreInterface,
    slug: str,
    *,
    ride_date: date,
    sport: str | None,
    session: Session | None,
    lthr_bpm: float | None,
) -> dict:
    """Extra `compute_analytics` kwargs for a bike ride: `lthr_bpm`, `race` (the matched
    session is a RACE session, or the athlete has a bike event on that date) and
    `session_text` (the matched session's purpose + structure text). Best-effort: an event
    lookup failure logs and reads as "not a race"."""
    race = bool(session is not None and session.purpose.strip().upper().startswith(RACE_PURPOSE_PREFIX))
    if not race and sport == "bike":
        try:
            race = any(
                ev.event_date == ride_date and ev.primary_sport == "bike" for ev in store.load_events(slug)
            )
        except Exception as exc:  # noqa: BLE001 - a missing event list must not block analytics
            log.warn("workouts.race_event_lookup_failed", athlete=slug, error=str(exc))
    text = " ".join(t for t in ((session.purpose, session.structure) if session else ()) if t) or None
    return {"lthr_bpm": lthr_bpm, "race": race, "session_text": text}


def enrich_draft(
    draft: WorkoutDraft,
    *,
    store: StoreInterface,
    athlete: str,
    tmp_path: Path,
    workout_id: UUID | None = None,
) -> WorkoutDraft:
    """Fills in `draft.raw_ref`/`draft.series_ref`/`draft.analytics` in
    place (and returns it, for chaining) exactly like `swim_coach.cli`'s
    `ingest --save` does.

    Raw-file persistence is still `FileStore`-only until Phase 2.5's
    Supabase-Storage-backed store lands (ROADMAP.md) -- a db-backed deploy
    (`STORE_BACKEND=db`) has nowhere durable to put the original bytes, so
    `raw_ref` is skipped rather than raising, with a warning appended to
    `draft.warnings`. The columnar **series** IS now persisted on every
    backend (`store.save_series` is part of `StoreInterface`, DB-backed by
    the `workout_series` table) -- this is what lets a synced ride's
    interval analytics be recomputed later. `workout_id`, when the caller
    knows it upfront (the intervals.icu sync job does), keys the series row
    to the real Workout id; the athlete-facing upload route assigns the id
    only at its separate confirm step, so it passes `None` and the series
    is keyed to a provisional id until a later `reanalyze_workout` re-keys
    it. Analytics are always computed (pure functions over the in-memory
    parse). Looks up the athlete's `home_elevation_m` (best-effort -- a
    lookup failure logs a warning and falls through to `None` rather than
    blocking ingest) to anchor `interval_analysis`'s altitude-context
    signal on a bike ride; see `library/30-altitude-power-adjustment.md`.

    Raises `FileExistsError` unmodified if `store.save_raw_file` refuses to
    overwrite a same-named-but-different-content file already on disk --
    callers translate that however fits their context (the route turns it
    into an HTTP 409; the sync job's per-activity try/except treats it like
    any other activity failure).
    """
    try:
        profile = store.load_athlete(athlete)
        home_elevation_m, ftp_watts = profile.home_elevation_m, profile.ftp_watts
        lthr_bpm = profile.lthr_bpm
    except Exception as exc:  # noqa: BLE001 - analytics must still compute without it
        log.warn("workouts.enrich_home_elevation_lookup_failed", athlete=athlete, error=str(exc))
        home_elevation_m, ftp_watts, lthr_bpm = None, None, None

    if hasattr(store, "save_raw_file"):
        draft.raw_ref = store.save_raw_file(athlete, tmp_path)
    else:
        log.warn("workouts.ingest_raw_ref_skipped", athlete=athlete, store=type(store).__name__)
        # The parser pre-fills raw_ref with its source path -- here that's
        # the caller's about-to-be-deleted temp file, a meaningless server
        # path that must not reach the client.
        draft.raw_ref = None
        draft.warnings.append(
            "This backend doesn't retain the original file yet -- keep your export; analytics were still computed."
        )

    if draft.series is not None and hasattr(store, "save_series"):
        # `hasattr` guard retained only for a test double that hides the
        # method (tests/api/test_workouts_ingest_route.py); every real
        # store -- FileStore AND DbStore -- now implements it.
        draft.series_ref = store.save_series(
            athlete, draft.date, draft.sport, workout_id or uuid4(), draft.series
        )

    draft.analytics = compute_analytics(
        laps=draft.laps,
        lengths=draft.lengths,
        pauses=draft.pauses,
        series=draft.series,
        elapsed_min=draft.elapsed_min,
        moving_min=draft.duration_min,
        sport=draft.sport,
        home_elevation_m=home_elevation_m,
        ftp_watts=ftp_watts,
        **analysis_context(
            store, athlete, ride_date=draft.date, sport=draft.sport, session=None, lthr_bpm=lthr_bpm
        ),
    )
    draft.analytics = annotate_power_curve_bests(
        draft.analytics, store=store, slug=athlete, ride_date=draft.date, workout_id=workout_id
    )
    return draft


def annotate_power_curve_bests(
    analytics: WorkoutAnalytics | None,
    *,
    store: StoreInterface,
    slug: str,
    ride_date: date,
    workout_id: UUID | None = None,
) -> WorkoutAnalytics | None:
    """Fill the curve's 42/90-day-best comparison from the athlete's earlier rides'
    stored curves (rides without a curve are skipped; older rides need re-analysis to
    get one). Best-effort: a store failure logs and leaves the curve un-annotated."""
    if analytics is None or not analytics.power_curve:
        return analytics
    try:
        since = ride_date - timedelta(days=max(BEST_WINDOWS_DAYS))
        prior = [
            ((ride_date - w.date).days, w.analytics.power_curve)
            for w in store.list_workouts(slug, since=since)
            if w.id != workout_id
            and w.date < ride_date
            and w.analytics is not None
            and w.analytics.power_curve
        ]
    except Exception as exc:  # noqa: BLE001 - the curve is still valid without the comparison
        log.warn("workouts.power_curve_bests_failed", athlete=slug, error=str(exc))
        return analytics
    return analytics.model_copy(update={"power_curve": annotate_bests(analytics.power_curve, prior)})


def _iso_week(d) -> str:
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def find_planned_session(store: StoreInterface, slug: str, workout: Workout) -> Session | None:
    """The planned `Session` this workout matches -- `quality.match_workout_to_session`
    (id, then same sport+date, then the unique +-1 day fit) over the workout's own
    week plus its two neighbours (a ride logged Sunday can belong to the week that
    just rolled over). Other logged workouts around it are passed so a session
    another workout already covers is never stolen."""
    sessions: list[Session] = []
    seen: set[str] = set()
    for delta in (-7, 0, 7):
        iso = _iso_week(workout.date + timedelta(days=delta))
        if iso in seen:
            continue
        seen.add(iso)
        week = store.load_week(slug, iso)
        if week is not None:
            sessions.extend(week.sessions)
    nearby = [
        w for w in store.list_workouts(slug) if abs((w.date - workout.date).days) <= 2 and w.id != workout.id
    ]
    return match_workout_to_session(workout, sessions, other_workouts=nearby)


def planned_intensity_zone(session: Session) -> str | None:
    """The planned session's intensity zone label (e.g. "Z2"), if it set one --
    tells the analyzer an endurance plan is never an all-interval ride."""
    zone = (session.intensity or {}).get("zone")
    return zone if isinstance(zone, str) else None


def attach_planned_session(
    workout: Workout, *, store: StoreInterface, slug: str, profile: Athlete, series: dict | None
) -> Workout:
    """Link `workout` to its planned session and, for a ride, re-run the interval
    analyzer WITH that session's `structured` prescription (zone targets resolved
    against the athlete's FTP). Returns the workout unchanged when nothing matches.
    Best-effort: a lookup/analysis failure logs and leaves the workout as-is."""
    if workout.planned_session_id is not None:
        return workout
    try:
        session = find_planned_session(store, slug, workout)
    except Exception as exc:  # noqa: BLE001 - never block ingest on the plan lookup
        log.warn("workouts.plan_match_failed", athlete=slug, error=str(exc))
        return workout
    if session is None:
        return workout
    updates: dict = {"planned_session_id": session.id}
    planned_zone = planned_intensity_zone(session)
    is_race = session.purpose.strip().upper().startswith(RACE_PURPOSE_PREFIX)
    if (
        workout.sport == "bike"
        and (session.structured is not None or planned_zone is not None or is_race)
        and series
    ):
        analytics = compute_analytics(
            laps=workout.laps,
            lengths=workout.lengths,
            pauses=workout.pauses,
            series=series,
            elapsed_min=workout.analytics.elapsed_min if workout.analytics else None,
            moving_min=workout.duration_min,
            sport=workout.sport,
            prescribed_structure=session.structured,
            home_elevation_m=profile.home_elevation_m,
            ftp_watts=profile.ftp_watts,
            planned_zone=planned_zone,
            **analysis_context(
                store, slug, ride_date=workout.date, sport=workout.sport, session=session,
                lthr_bpm=profile.lthr_bpm,
            ),
        )
        updates["analytics"] = annotate_power_curve_bests(
            analytics, store=store, slug=slug, ride_date=workout.date, workout_id=workout.id
        )
    log.info("workouts.plan_matched", athlete=slug, workout_id=str(workout.id), session_id=str(session.id))
    return workout.model_copy(update=updates)
