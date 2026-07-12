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
from uuid import uuid4

from swim_coach.analytics import compute_analytics
from swim_coach.parse_files import WorkoutDraft
from swim_coach.store import StoreInterface

from app.logging_config import get_logger

log = get_logger("app.enrich")


def enrich_draft(
    draft: WorkoutDraft,
    *,
    store: StoreInterface,
    athlete: str,
    tmp_path: Path,
) -> WorkoutDraft:
    """Fills in `draft.raw_ref`/`draft.series_ref`/`draft.analytics` in
    place (and returns it, for chaining) exactly like `swim_coach.cli`'s
    `ingest --save` does.

    Raw-file/series persistence is `FileStore`-only until Phase 2.5's
    Supabase-Storage-backed store lands (ROADMAP.md) -- a db-backed deploy
    (`STORE_BACKEND=db`) has nowhere durable to put the bytes, so both refs
    are skipped rather than raising, with a warning appended to
    `draft.warnings` and analytics still computed (pure functions over the
    in-memory parse).

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
        # No Workout id exists yet at this point in either caller (the route
        # hasn't saved one; the sync job assigns one after this returns) --
        # save_series only needs *a* UUID to build a recognizable sidecar
        # filename (see its docstring), so a fresh one here is fine; it
        # doesn't have to match the id the eventually-saved Workout gets.
        draft.series_ref = store.save_series(athlete, draft.date, draft.sport, uuid4(), draft.series)

    draft.analytics = compute_analytics(
        laps=draft.laps,
        lengths=draft.lengths,
        pauses=draft.pauses,
        series=draft.series,
        elapsed_min=draft.elapsed_min,
        moving_min=draft.duration_min,
    )
    return draft
