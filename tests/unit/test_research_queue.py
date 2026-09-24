"""Tests for swim_coach.research_queue -- pure functions over StoreInterface
closing the loop on logged `Feedback(type="research_question")` rows.

No LLM calls, no network, no DB -- the file-backed `FileStore` in a tmp dir,
same style as test_cli.py/test_library_review.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from swim_coach.models import Feedback
from swim_coach.research_queue import (
    ResearchQueueError,
    dismiss,
    list_open_research_questions,
    resolve,
)
from swim_coach.store import FileStore

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_LIBRARY_DIR = REPO_ROOT / "library"


def _feedback(
    *,
    type: str = "research_question",
    status: str = "open",
    body: str = "some research question",
    context: dict | None = None,
    athlete_id: uuid.UUID | None = None,
) -> Feedback:
    return Feedback(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        type=type,
        source="coach",
        body=body,
        context=context or {},
        status=status,
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture
def store(tmp_path) -> FileStore:
    return FileStore(base_dir=tmp_path)


# --- list_open_research_questions -------------------------------------------


def test_list_open_research_questions_filters_type_and_status(store: FileStore) -> None:
    open_rq = _feedback(context={"topic": "strength"})
    resolved_rq = _feedback(status="resolved", context={"topic": "strength"})
    bug = _feedback(type="bug")
    for f in (open_rq, resolved_rq, bug):
        store.save_feedback(f)

    result = list_open_research_questions(store)

    assert [f.id for f in result] == [open_rq.id]


def test_list_open_research_questions_grouped_by_topic(store: FileStore) -> None:
    strength_1 = _feedback(context={"topic": "strength"})
    strength_2 = _feedback(context={"topic": "strength"})
    nutrition = _feedback(context={"topic": "nutrition"})
    untagged = _feedback(context={})
    for f in (strength_1, strength_2, nutrition, untagged):
        store.save_feedback(f)

    grouped = list_open_research_questions(store, group_by_topic=True)

    assert {f.id for f in grouped["strength"]} == {strength_1.id, strength_2.id}
    assert [f.id for f in grouped["nutrition"]] == [nutrition.id]
    assert [f.id for f in grouped["untagged"]] == [untagged.id]


# --- resolve -----------------------------------------------------------------


def test_resolve_sets_status_resolved_and_merges_context(store: FileStore) -> None:
    rq = _feedback(context={"topic": "strength"})
    store.save_feedback(rq)

    updated = resolve(
        store,
        rq.id,
        library_files=["07-strength-dryland.md"],
        note="answered in 34-kettlebell-strength-programming.md",
        pr=241,
        library_dir=REAL_LIBRARY_DIR,
    )

    assert updated.status == "resolved"
    assert updated.context["topic"] == "strength"  # original key preserved
    assert updated.context["resolution"] == "answered in 34-kettlebell-strength-programming.md"
    assert updated.context["resolved_by"] == {
        "library_files": ["07-strength-dryland.md"],
        "pr": 241,
    }
    assert "resolved_at" in updated.context
    # Round-trips through the store, not just the return value.
    assert store.get_feedback(rq.id).status == "resolved"


def test_resolve_pr_is_optional(store: FileStore) -> None:
    rq = _feedback()
    store.save_feedback(rq)

    updated = resolve(
        store,
        rq.id,
        library_files=["07-strength-dryland.md"],
        note="answered",
        library_dir=REAL_LIBRARY_DIR,
    )

    assert updated.context["resolved_by"]["pr"] is None


def test_resolve_refuses_missing_library_file(store: FileStore) -> None:
    rq = _feedback()
    store.save_feedback(rq)

    with pytest.raises(ResearchQueueError, match="does not exist|do not exist"):
        resolve(
            store,
            rq.id,
            library_files=["99-does-not-exist.md"],
            note="answered",
            library_dir=REAL_LIBRARY_DIR,
        )

    # Refused before any write -- still open.
    assert store.get_feedback(rq.id).status == "open"


def test_resolve_refuses_non_research_question_row(store: FileStore) -> None:
    bug = _feedback(type="bug")
    store.save_feedback(bug)

    with pytest.raises(ResearchQueueError, match="research_question"):
        resolve(
            store,
            bug.id,
            library_files=["07-strength-dryland.md"],
            note="n/a",
            library_dir=REAL_LIBRARY_DIR,
        )


def test_resolve_refuses_already_resolved_row(store: FileStore) -> None:
    rq = _feedback(status="resolved")
    store.save_feedback(rq)

    with pytest.raises(ResearchQueueError, match="open"):
        resolve(
            store,
            rq.id,
            library_files=["07-strength-dryland.md"],
            note="n/a",
            library_dir=REAL_LIBRARY_DIR,
        )


def test_resolve_refuses_dismissed_row(store: FileStore) -> None:
    rq = _feedback(status="dismissed")
    store.save_feedback(rq)

    with pytest.raises(ResearchQueueError, match="open"):
        resolve(
            store,
            rq.id,
            library_files=["07-strength-dryland.md"],
            note="n/a",
            library_dir=REAL_LIBRARY_DIR,
        )


def test_resolve_unknown_id_raises(store: FileStore) -> None:
    with pytest.raises(ResearchQueueError, match="no feedback"):
        resolve(
            store,
            uuid.uuid4(),
            library_files=["07-strength-dryland.md"],
            note="n/a",
            library_dir=REAL_LIBRARY_DIR,
        )


# --- dismiss -------------------------------------------------------------


def test_dismiss_sets_status_and_context(store: FileStore) -> None:
    rq = _feedback(context={"topic": "cold-water/hypothermia"})
    store.save_feedback(rq)

    updated = dismiss(store, rq.id, reason="duplicate", note="same as another open row")

    assert updated.status == "dismissed"
    assert updated.context["topic"] == "cold-water/hypothermia"  # preserved
    assert updated.context["dismissal_reason"] == "duplicate"
    assert updated.context["dismissal_note"] == "same as another open row"
    assert store.get_feedback(rq.id).status == "dismissed"


def test_dismiss_with_duplicate_of(store: FileStore) -> None:
    original = _feedback()
    dup = _feedback()
    store.save_feedback(original)
    store.save_feedback(dup)

    updated = dismiss(
        store, dup.id, reason="duplicate", note="dupe", duplicate_of=original.id
    )

    assert updated.context["duplicate_of"] == str(original.id)


def test_dismiss_refuses_non_open_row(store: FileStore) -> None:
    rq = _feedback(status="resolved")
    store.save_feedback(rq)

    with pytest.raises(ResearchQueueError, match="open"):
        dismiss(store, rq.id, reason="obsolete", note="n/a")


def test_dismiss_refuses_non_research_question_row(store: FileStore) -> None:
    feature = _feedback(type="feature_request")
    store.save_feedback(feature)

    with pytest.raises(ResearchQueueError, match="research_question"):
        dismiss(store, feature.id, reason="not_research", note="n/a")
