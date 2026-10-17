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
from datetime import timedelta
from uuid import UUID, uuid4

from swim_coach.analysis import AnalysisContext
from swim_coach.analysis import build_analysis_context as engine_build_analysis_context
from swim_coach.models import Session, Workout
from swim_coach.parse_files import WorkoutDraft
from swim_coach.quality import match_workout_to_session
from swim_coach.store import StoreInterface

from app.logging_config import get_logger

log = get_logger("app.enrich")


def build_analysis_context(
    store: StoreInterface,
    slug: str,
    workout: Workout,
    *,
    series: dict | None,
    target_w: float | None = None,
    elapsed_min: float | None = None,
    session: Session | None = None,
    match_session: bool = False,
) -> AnalysisContext:
    """The `AnalysisContext` for `workout.analyze(...)`: thresholds from the athlete, the
    workout's kind (stamped on `workout.kind`), prior workouts for the power-curve bests.
    `match_session=True` looks up the planned session this workout matches (best-effort: a
    lookup failure logs and analyses without it); an explicit `session` skips the lookup."""
    if session is None and match_session:
        try:
            session = find_planned_session(store, slug, workout)
        except Exception as exc:  # noqa: BLE001 - never block analysis on the plan lookup
            log.warn("workouts.plan_match_failed", athlete=slug, error=str(exc))
    return engine_build_analysis_context(
        store, slug, workout, session=session, series=series, target_w=target_w, elapsed_min=elapsed_min
    )


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

    workout = draft.to_workout(athlete_id=uuid4(), workout_id=workout_id)
    ctx = build_analysis_context(store, athlete, workout, series=draft.series, elapsed_min=draft.elapsed_min)
    draft.analytics = workout.analyze(ctx)
    draft.kind = workout.kind
    return draft


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


def attach_planned_session(workout: Workout, *, store: StoreInterface, slug: str, series: dict | None) -> Workout:
    """Link `workout` to its planned session and re-run its analyzer WITH that session in the
    context (prescription, zone, kind, thresholds from the athlete). Returns the workout
    unchanged when nothing matches. Best-effort: a lookup/analysis failure logs and leaves the
    workout as-is.

    An existing `planned_session_id` (athlete/coach-set, or an earlier match) is never replaced,
    but the workout is still re-analysed with THAT session: skipping it left a re-analysed race
    tagged free_ride (prod 2026-10-17)."""
    try:
        session = find_planned_session(store, slug, workout)
    except Exception as exc:  # noqa: BLE001 - never block ingest on the plan lookup
        log.warn("workouts.plan_match_failed", athlete=slug, error=str(exc))
        return workout
    if session is None:
        return workout
    already_linked = workout.planned_session_id is not None
    if already_linked and session.id != workout.planned_session_id:
        return workout
    linked = workout.model_copy(update={"planned_session_id": session.id})
    ctx = build_analysis_context(store, slug, linked, series=series, session=session)  # also stamps kind
    if series:
        linked.analytics = linked.analyze(ctx)
    if not already_linked:
        log.info("workouts.plan_matched", athlete=slug, workout_id=str(workout.id), session_id=str(session.id))
    return linked
