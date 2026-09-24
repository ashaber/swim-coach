"""Close the loop on logged `Feedback(type="research_question")` rows.

Context: the in-app coach logs a research gap it can't answer as a
`Feedback` row (`models.py`'s `Feedback`, `type="research_question"`,
`status` a free string that has only ever been "open" or, for a small
handful of already-answered rows, "resolved"/"dismissed" set by hand).
Nothing has ever closed one programmatically, so the same questions get
re-logged by the coach every time an athlete asks again. This module is
the pure-function core of the manual close-out workflow: triage
(`list_open_research_questions`), and the two terminal actions
(`resolve`/`dismiss`), each a thin, validated wrapper over
`StoreInterface.update_feedback`'s existing shallow-context-merge contract
-- see `docs/research-workflow.md` for the end-to-end research cycle this
plugs into (step 6, "close the loop").

Every function here takes a `StoreInterface` (never constructs its own
store) so it works unchanged against `FileStore` (tests, local dev) or
`DbStore` (prod) -- same seam every other engine module uses. No network,
no LLM calls; this is deterministic bookkeeping over already-collected
data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import UUID

from swim_coach.models import Feedback
from swim_coach.store import StoreInterface

RESEARCH_QUESTION_TYPE = "research_question"

DismissReason = Literal["duplicate", "not_research", "obsolete"]


class ResearchQueueError(ValueError):
    """Raised when an operation is refused: wrong `Feedback.type`, a row
    that isn't `status="open"`, an unknown id, or (for `resolve`) a
    `library_files` entry that doesn't exist on disk."""


def list_open_research_questions(
    store: StoreInterface, *, group_by_topic: bool = False
) -> list[Feedback] | dict[str, list[Feedback]]:
    """Every open `research_question` row, most-recent-first (the order
    `StoreInterface.list_feedback` already returns).

    `group_by_topic=True` buckets by `context["topic"]` (the free-text
    field every real research_question row carries -- see
    `backend/app/tools.py`'s `flag_for_coach_review`), falling back to the
    literal string `"untagged"` for a row with no `topic` key at all,
    never silently dropping it from the result.
    """
    all_feedback = store.list_feedback()
    open_rows = [
        f for f in all_feedback if f.type == RESEARCH_QUESTION_TYPE and f.status == "open"
    ]
    if not group_by_topic:
        return open_rows

    grouped: dict[str, list[Feedback]] = {}
    for f in open_rows:
        topic = f.context.get("topic") or "untagged"
        grouped.setdefault(topic, []).append(f)
    return grouped


def _require_open_research_question(store: StoreInterface, feedback_id: UUID) -> Feedback:
    """Fetch `feedback_id` and refuse (raising `ResearchQueueError`) unless
    it exists, is a `research_question`, and is currently `status="open"`.
    Shared precondition for both `resolve` and `dismiss` -- neither should
    silently no-op or clobber a row that's already been actioned."""
    feedback = store.get_feedback(feedback_id)
    if feedback is None:
        raise ResearchQueueError(f"no feedback row with id {feedback_id!s}")
    if feedback.type != RESEARCH_QUESTION_TYPE:
        raise ResearchQueueError(
            f"{feedback_id!s} is type {feedback.type!r}, not "
            f"{RESEARCH_QUESTION_TYPE!r} -- refusing to act on it"
        )
    if feedback.status != "open":
        raise ResearchQueueError(
            f"{feedback_id!s} has status {feedback.status!r}, not 'open' -- "
            "refusing to act on an already-resolved/dismissed row"
        )
    return feedback


def resolve(
    store: StoreInterface,
    feedback_id: UUID,
    *,
    library_files: list[str],
    note: str,
    pr: int | None = None,
    library_dir: Path = Path("library"),
) -> Feedback:
    """Mark an open `research_question` row `status="resolved"`.

    Merges `context.resolution` (the human-readable answer summary),
    `context.resolved_by` (`{"library_files": [...], "pr": pr}`), and
    `context.resolved_at` (UTC ISO timestamp) into the row's existing
    context -- the same shallow-merge `update_feedback` already does for
    every other caller, so `topic` and any other pre-existing context key
    survive untouched. Every entry in `library_files` must exist under
    `library_dir` (default: `library/` relative to cwd) -- a typo'd
    filename here would silently mark an athlete's question "answered" by
    a file that was never actually written, which is worse than leaving it
    open. Refuses (no write at all) if `feedback_id` doesn't resolve to an
    open `research_question` row, or if any `library_files` entry is
    missing.

    Per `docs/research-workflow.md`: only call this AFTER the answering
    library content has been merged to main AND deployed (the library
    ships inside the backend image; a merged-but-undeployed PR is invisible
    to the coach) -- this function has no way to check that itself, so the
    caller (a human, via the CLI's `--dry-run` and their own judgment) is
    the actual gate.
    """
    _require_open_research_question(store, feedback_id)

    missing = [f for f in library_files if not (library_dir / f).exists()]
    if missing:
        raise ResearchQueueError(
            f"library file(s) do not exist under {library_dir!s}: {missing} -- "
            "refusing to mark this row resolved by a file that doesn't exist"
        )

    updated = store.update_feedback(
        feedback_id,
        status="resolved",
        context={
            "resolution": note,
            "resolved_by": {"library_files": library_files, "pr": pr},
            "resolved_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert updated is not None  # _require_open_research_question already confirmed existence
    return updated


def dismiss(
    store: StoreInterface,
    feedback_id: UUID,
    *,
    reason: DismissReason,
    note: str,
    duplicate_of: UUID | None = None,
) -> Feedback:
    """Mark an open `research_question` row `status="dismissed"` --
    triage's other terminal action, for a row that was never a real
    research gap in the first place (a duplicate of another open row, a
    bug report mis-logged as `research_question`, or a question the
    library has already answered elsewhere / is no longer relevant).

    Merges `context.dismissal_reason`, `context.dismissal_note`, and (when
    `reason="duplicate"`) `context.duplicate_of` (stored as a string, since
    `Feedback.context` is a plain JSON-shaped dict) into the row's existing
    context, same shallow-merge contract as `resolve`. Refuses (no write)
    if `feedback_id` doesn't resolve to an open `research_question` row.
    """
    _require_open_research_question(store, feedback_id)

    context: dict[str, object] = {"dismissal_reason": reason, "dismissal_note": note}
    if duplicate_of is not None:
        context["duplicate_of"] = str(duplicate_of)

    updated = store.update_feedback(feedback_id, status="dismissed", context=context)
    assert updated is not None  # _require_open_research_question already confirmed existence
    return updated
