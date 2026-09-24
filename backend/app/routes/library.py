"""GET /api/library/cards, GET /api/library/files/{name}, POST
/api/library/reviews -- the PWA's Resources tab research-library reviewer
(web/resources-tab-library-review build, `docs/library-review.md`).

Replaces today's flow of tracing a topic file's markdown for the UNREVIEWED
marker, hand-editing it, and re-uploading -- an admin now reads a small card
per `##` section (`GET /api/library/cards`), can jump to the full section
text (`GET /api/library/files/{name}`), and accepts/flags it
(`POST /api/library/reviews`) without ever touching the repo directly.
Applying an accepted decision back into the repo (stripping the marker) is a
SEPARATE step -- `library-review-apply` (`engine/swim_coach/cli.py`), run by
Andrew, reviewed as a diff, and committed via PR -- this route only ever
records a decision, never edits `library/*.md` itself.

Card CONTENT (`summary`/`recommendation`) is authored, versioned YAML
(`library/review-cards/<stem>.yaml`), never a DB row -- everything else a
card shows (confidence, tags, source count, review status, staleness) is
DERIVED at request time from `library_review.section_evidence` /
`library_cards.is_stale`, same "never hand-typed, always computed" discipline
`library_review.py`'s own module docstring already establishes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from swim_coach.library_cards import (
    card_path_for,
    in_scope_topic_files,
    is_stale,
    load_card_file,
    section_text,
    topic_sections,
)
from swim_coach.library_review import parse_reference_list, section_evidence
from swim_coach.models import Feedback, LibraryReview

from app.auth import Principal, require_auth, require_library_admin, resolve_athlete
from app.context import filter_files_by_sport_scope
from app.logging_config import get_logger
from app.store_factory import make_store

router = APIRouter()
log = get_logger("app.routes.library")


def _ref_entries(library_dir) -> list:
    path = library_dir / "reference_list.md"
    if not path.exists():
        return []
    return parse_reference_list(path.read_text(encoding="utf-8"))


@router.get("/api/library/cards")
async def list_library_cards(
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> list[dict]:
    """Every review card for a section this athlete's own sport scope may
    see, each carrying its authored summary/recommendation plus every
    derived field a reviewer needs: `confidence` (lowest among the
    section's tagged claims), `tags`, `source_count`/`weak_source_count`,
    `dossier`, `reviewed` (is an UNREVIEWED marker still covering this
    section), `needs_judgment`, `stale` (has the section's text drifted
    since the card was authored), and `latest_review` (this card's most
    recent accept/flag decision, or null if never reviewed)."""
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)
    athlete_profile = store.load_athlete(athlete)

    library_dir = settings.library_dir
    topic_files = in_scope_topic_files(library_dir)
    allowed_names = set(
        filter_files_by_sport_scope(
            [p.name for p in topic_files], athlete_profile.effective_sports
        )
    )

    ref_entries = _ref_entries(library_dir)
    dossiers_dir = library_dir / "research-dossiers"

    # Most-recent-first (StoreInterface.list_library_reviews's own
    # contract) -- the first entry seen per (file, section) IS the current
    # verdict, so a single pass builds the "latest decision" lookup without
    # a query per card.
    latest_by_key: dict[tuple[str, str], LibraryReview] = {}
    for review in store.list_library_reviews():
        key = (review.file, review.section)
        if key not in latest_by_key:
            latest_by_key[key] = review

    cards: list[dict] = []
    for topic_path in topic_files:
        if topic_path.name not in allowed_names:
            continue
        card_path = card_path_for(library_dir, topic_path.name)
        if not card_path.exists():
            # A topic file with no authored cards yet (docs/library-review.md
            # asks every research build to add them) -- skip rather than 500.
            continue
        card_file = load_card_file(card_path)
        text = topic_path.read_text(encoding="utf-8")
        sections_by_slug = {s.slug: s for s in topic_sections(text)}

        for card in card_file.cards:
            section = sections_by_slug.get(card.section)
            if section is None:
                # The topic file changed shape since the card was authored
                # (a heading renamed/removed) -- surface it as maximally
                # stale rather than crashing the whole list.
                stale = True
                evidence = None
            else:
                stale = is_stale(card, section_text(text, section))
                evidence = section_evidence(
                    text, section.start, section.end, ref_entries, dossiers_dir
                )

            latest = latest_by_key.get((topic_path.name, card.section))
            cards.append(
                {
                    "file": topic_path.name,
                    "section": card.section,
                    "heading": card.heading,
                    "summary": card.summary,
                    "recommendation": card.recommendation,
                    "confidence": evidence.lowest_confidence if evidence else None,
                    "tags": list(evidence.tags) if evidence else [],
                    "source_count": evidence.source_count if evidence else 0,
                    "weak_source_count": evidence.weak_source_count if evidence else 0,
                    "dossier": evidence.dossier if evidence else None,
                    "reviewed": evidence.reviewed if evidence else False,
                    "needs_judgment": evidence.needs_judgment if evidence else False,
                    "stale": stale,
                    "latest_review": latest.model_dump(mode="json") if latest else None,
                }
            )
    return cards


@router.get("/api/library/files/{name}")
async def get_library_file(
    name: str,
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    """One topic file's full markdown, for the "Read full section" jump-to-
    anchor flow off a card. `name` is checked against a strict allow-list
    (every in-scope topic file's own real filename, per
    `library_cards.in_scope_topic_files`) -- no path traversal, and no
    exposure of `library/review-cards/`, `research-dossiers/`, or any other
    non-topic-file content this route was never meant to serve."""
    settings = request.app.state.settings
    athlete = resolve_athlete(principal, athlete)
    store = make_store(settings)
    athlete_profile = store.load_athlete(athlete)

    library_dir = settings.library_dir
    allowed = {p.name: p for p in in_scope_topic_files(library_dir)}
    path = allowed.get(name)
    if path is None:
        raise HTTPException(status_code=404, detail=f"no such library file: {name}")

    permitted_names = set(
        filter_files_by_sport_scope([name], athlete_profile.effective_sports)
    )
    if name not in permitted_names:
        # Same 404 (not 403) as an unknown name -- a swim-only athlete must
        # never learn a bike-scoped file exists at all, matching
        # context.py's own sport-scope guarantee for chat.
        raise HTTPException(status_code=404, detail=f"no such library file: {name}")

    return {"file": name, "content": path.read_text(encoding="utf-8")}


@router.post("/api/library/reviews")
async def create_library_review(
    payload: dict[str, Any],
    request: Request,
    athlete: str | None = Query(None),
    principal: Principal = Depends(require_auth),
) -> dict:
    """Admin-only: records one accept/flag decision on a review card.
    Server-side-enforced on every call (`require_library_admin`) -- never
    trusts a client-sent admin flag. A `"flagged"` decision also creates a
    `Feedback` row (`type="research_question"`, `source="coach"`) so it
    lands in the same research queue every other unresolved gap does."""
    settings = request.app.state.settings
    reviewer_slug = require_library_admin(request, principal, athlete)
    store = make_store(settings)
    reviewer = store.load_athlete(reviewer_slug)

    file = payload.get("file")
    section = payload.get("section")
    content_hash = payload.get("content_hash")
    decision = payload.get("decision")
    note = payload.get("note")

    if not isinstance(file, str) or not file:
        raise HTTPException(status_code=422, detail="file must be a non-empty string")
    if not isinstance(section, str) or not section:
        raise HTTPException(status_code=422, detail="section must be a non-empty string")
    if not isinstance(content_hash, str) or not content_hash:
        raise HTTPException(status_code=422, detail="content_hash must be a non-empty string")
    if decision not in ("accepted", "flagged"):
        raise HTTPException(status_code=422, detail="decision must be 'accepted' or 'flagged'")
    if note is not None and not isinstance(note, str):
        raise HTTPException(status_code=422, detail="note must be a string")
    if decision == "flagged" and not note:
        raise HTTPException(status_code=422, detail="note is required when flagging")

    library_dir = settings.library_dir
    card_path = card_path_for(library_dir, file)
    if not card_path.exists():
        raise HTTPException(status_code=404, detail=f"no such library file: {file}")
    card_file = load_card_file(card_path)
    if not any(c.section == section for c in card_file.cards):
        raise HTTPException(status_code=404, detail=f"no such section: {file}#{section}")

    review = LibraryReview(
        id=uuid4(),
        file=file,
        section=section,
        content_hash=content_hash,
        decision=decision,
        note=note,
        reviewed_by=reviewer.id,
        created_at=datetime.now(timezone.utc),
    )
    store.save_library_review(review)
    log.info(
        "library_review.recorded",
        file=file,
        section=section,
        decision=decision,
        reviewer=reviewer_slug,
    )

    if decision == "flagged":
        feedback = Feedback(
            id=uuid4(),
            athlete_id=None,
            type="research_question",
            source="coach",
            body=note,
            context={"topic": "library-review", "file": file, "section": section},
            status="open",
            created_at=datetime.now(timezone.utc),
        )
        store.save_feedback(feedback)

    return review.model_dump(mode="json")
