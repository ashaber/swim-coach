"""POST/GET /api/workouts -- logging and listing completed workouts, plus
POST /api/workouts/ingest -- parsing a `.fit`/`.tcx`/`.csv` watch export.

This is the write half of the seam `plan.py` reads through: everything goes
via `make_store(settings)` (`FileStore` locally, `DbStore` in prod behind
`STORE_BACKEND=db`) so a workout logged here reaches the live coach with no
redeploy. The server assigns `id` (uuid4), `athlete_id` (from the athlete's
own profile) and `schema_version`. Input is validated by constructing the
pydantic `Workout` model directly (never hand-computed) -- a
`pydantic.ValidationError` becomes a 422 with the app's standard
`{"error": ...}` shape (same `HTTPException` -> `StarletteHTTPException`
handler `app.main` already installs for every other route).

Two-step upload (Phase 3, "make .fit upload actually reachable by the
athlete"): `POST /api/workouts/ingest` parses an uploaded file **in memory**
and returns the resulting `WorkoutDraft` (including `warnings`) WITHOUT
saving a `Workout` record -- a parsed file can be wrong (a kayak mapped to
cross_train; a bad date) and RPE is never knowable from the file, so
auto-saving would risk silently corrupting the athlete's training log. The
PWA renders the draft as a review card, the athlete adds RPE/notes and
confirms, and only THEN does it call this same `POST /api/workouts` below --
with `source` set to the draft's real source (`fit`/`tcx`/`csv`), not a
fabricated "manual". `source` is therefore no longer server-hardcoded; it's
client-settable but restricted to `_CLIENT_SETTABLE_SOURCES` (excludes
`coach_text`, which is still CLI/skill-only -- see `_cmd_ingest` in
`engine/swim_coach/cli.py`).

Even though the ingest step itself doesn't save a `Workout`, it DOES run the
same enrichment `swim_coach.cli`'s `ingest --save` does -- a durable raw-file
copy (`FileStore.save_raw_file`), a time-series sidecar when the parser
produced one (`FileStore.save_series`), and `swim_coach.analytics.
compute_analytics` -- and folds `raw_ref`/`series_ref`/`analytics` into the
returned draft. `web/src/forms.js`'s `logFormFromDraft` carries those fields
through the review form, so the confirm-time `POST /api/workouts` call below
(which passes arbitrary draft fields straight into the `Workout` model)
persists a workout with the exact same laps/pauses/analytics an equivalent
CLI ingest would have produced -- a web-uploaded .fit is never a
second-class citizen next to one ingested on Andrew's machine.
"""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from pydantic import ValidationError
from swim_coach.analytics import compute_analytics
from swim_coach.models import Workout
from swim_coach.parse_files import PARSERS_BY_EXTENSION

from app.auth import require_auth
from app.logging_config import get_logger
from app.store_factory import make_store

router = APIRouter()
log = get_logger("app.routes.workouts")

# Fields the server assigns itself -- stripped from the client payload before
# constructing the model so a client-supplied value can never collide with
# (or spoof) an id/athlete_id/schema_version.
_SERVER_ASSIGNED_FIELDS = {"id", "athlete_id", "schema_version"}

# `source` isn't server-assigned any more (see module docstring) but it also
# isn't a free-for-all -- "coach_text" is only ever produced by the
# CLI/skill ingest path, never by a client of this JSON endpoint, so it's
# deliberately excluded here even though `Workout.source` accepts it as a
# valid Literal value.
_CLIENT_SETTABLE_SOURCES = {"manual", "fit", "tcx", "csv"}

# Module constant so it's a one-line change if a real .fit ever needs more --
# Garmin/watch exports for a single session are typically well under 1 MB;
# 10 MB is generous headroom while still bounding memory use per upload
# (the whole file is read into memory -- see ingest_workout below).
_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/api/workouts")
async def create_workout(
    payload: dict[str, Any],
    request: Request,
    athlete: str = Query("renee"),
    _token: str = Depends(require_auth),
) -> dict:
    settings = request.app.state.settings
    store = make_store(settings)
    try:
        profile = store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    client_fields = {k: v for k, v in payload.items() if k not in _SERVER_ASSIGNED_FIELDS}
    source = client_fields.pop("source", None) or "manual"
    if source not in _CLIENT_SETTABLE_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source must be one of {sorted(_CLIENT_SETTABLE_SOURCES)}",
        )

    try:
        workout = Workout(
            id=uuid4(),
            athlete_id=profile.id,
            schema_version=1,
            source=source,
            **client_fields,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    store.save_workout(athlete, workout)
    return workout.model_dump(mode="json")


@router.post("/api/workouts/ingest")
async def ingest_workout(
    request: Request,
    file: UploadFile = File(...),
    athlete: str = Query("renee"),
    _token: str = Depends(require_auth),
) -> dict:
    """Parses an uploaded `.fit`/`.tcx`/`.csv` file, enriches it exactly like
    `swim_coach.cli`'s `ingest` command does, and returns the resulting
    `WorkoutDraft` as JSON. Never saves a `Workout` record -- see module
    docstring for the two-step upload/review/confirm rationale, and for why
    the enrichment (raw-file copy, series sidecar, analytics) still happens
    here rather than waiting for confirm.

    Validation at the boundary, in order: auth -> known athlete -> extension
    allowlist (case-insensitive, matched off the client-supplied filename --
    never used as a filesystem path, only to look up an extension) -> size
    cap -> non-empty -> parse. The raw file is written into a dedicated temp
    directory (rather than `NamedTemporaryFile`) under its own basename --
    `parse_fit`/`parse_tcx`/`parse_csv` need a real path (fitdecode in
    particular seeks), and `store.save_raw_file` copies by path too, so
    giving the temp file the athlete's own (sanitized) filename means the
    durable copy under `athletes/<slug>/logs/files/` is one a human can
    recognize, the same way a CLI ingest's copy is. The temp directory is
    always removed in a `finally`, even on parse/enrichment failure.
    """
    start = time.monotonic()
    settings = request.app.state.settings
    store = make_store(settings)
    try:
        store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    filename = file.filename or ""
    ext = Path(filename).suffix.lower()
    parser_fn = PARSERS_BY_EXTENSION.get(ext)
    if parser_fn is None:
        raise HTTPException(
            status_code=415,
            detail=f"unsupported file extension {ext!r}; expected one of {sorted(PARSERS_BY_EXTENSION)}",
        )

    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"file too large; max {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )
    if not contents:
        raise HTTPException(status_code=400, detail="uploaded file is empty")

    # `Path(...).name` drops any directory components a hostile filename
    # might carry, matching the "never used as a filesystem path" property
    # the extension lookup above already relies on.
    safe_name = Path(filename).name or f"upload{ext}"
    tmp_dir = Path(tempfile.mkdtemp(prefix="swimcoach-ingest-"))
    tmp_path = tmp_dir / safe_name
    try:
        tmp_path.write_bytes(contents)
        try:
            draft = parser_fn(tmp_path)
        except Exception as exc:  # noqa: BLE001 - parse_files' parsers are best-effort
            # against real-world exports and have only ever been validated
            # against two real files (see parse_files.py's module docstring and
            # the PR that added this route) -- a malformed/unexpected file must
            # come back as a clean, specific 4xx, never a raw traceback and
            # never a generic 500. File contents/GPS data are never logged, only
            # the failure and the extension.
            log.warn(
                "workouts.ingest_parse_failed",
                athlete=athlete,
                ext=ext,
                error=str(exc),
            )
            raise HTTPException(status_code=422, detail=f"could not parse {filename or 'file'}: {exc}") from exc

        # Mirror `_cmd_ingest`'s save path (engine/swim_coach/cli.py) so an
        # uploaded .fit gets the same durable raw-file copy, series sidecar,
        # and derived analytics a CLI ingest gets -- computed once here so
        # `POST /api/workouts` (confirm) doesn't need the original bytes
        # again, since the browser's file input can't hand them back.
        #
        # Raw-file/series persistence is FileStore-only until Phase 2.5's
        # uploaded_files table + Supabase Storage land (ROADMAP.md) -- a
        # db-backed deploy (STORE_BACKEND=db) has nowhere durable to put the
        # bytes, so it skips both refs rather than 500ing, tells the athlete
        # via `warnings`, and still computes analytics (pure functions over
        # the in-memory parse).
        if hasattr(store, "save_raw_file"):
            try:
                draft.raw_ref = store.save_raw_file(athlete, tmp_path)
            except FileExistsError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        else:
            log.warn("workouts.ingest_raw_ref_skipped", athlete=athlete, store=type(store).__name__)
            # The parser pre-fills raw_ref with its source path -- here that's
            # the about-to-be-deleted temp file, a meaningless server path that
            # must not reach the client.
            draft.raw_ref = None
            draft.warnings.append(
                "This backend doesn't retain the original file yet -- keep your export; analytics were still computed."
            )

        if draft.series is not None and hasattr(store, "save_series"):
            # No Workout id exists yet (nothing is saved until confirm) --
            # save_series only needs *a* UUID to build a recognizable sidecar
            # filename (see its docstring), so a fresh one here is fine; it
            # doesn't have to match the id the confirmed Workout eventually
            # gets.
            draft.series_ref = store.save_series(athlete, draft.date, draft.sport, uuid4(), draft.series)

        draft.analytics = compute_analytics(
            laps=draft.laps,
            lengths=draft.lengths,
            pauses=draft.pauses,
            series=draft.series,
            elapsed_min=draft.elapsed_min,
            moving_min=draft.duration_min,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    draft_dump = draft.model_dump(mode="json")
    # `series` (a per-record time-series payload -- thousands of samples for
    # a multi-hour .fit) is never returned over the wire, same convention as
    # cli.py's `ingest` command -- it's already been persisted to the series
    # sidecar above (series_ref) and would otherwise dwarf every other field
    # in this response.
    draft_dump.pop("series", None)

    duration_ms = round((time.monotonic() - start) * 1000, 2)
    log.info(
        "workouts.ingest_parsed",
        athlete=athlete,
        ext=ext,
        sport=draft.sport,
        distance_m=draft.distance_m,
        duration_min=draft.duration_min,
        warning_count=len(draft.warnings),
        has_analytics=draft.analytics is not None,
        duration_ms=duration_ms,
    )
    return draft_dump


@router.get("/api/workouts")
async def list_workouts(
    request: Request,
    athlete: str = Query("renee"),
    _token: str = Depends(require_auth),
) -> list[dict]:
    settings = request.app.state.settings
    store = make_store(settings)
    try:
        store.load_athlete(athlete)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"no such athlete: {athlete}") from exc

    workouts = store.list_workouts(athlete)
    return [w.model_dump(mode="json") for w in workouts]
