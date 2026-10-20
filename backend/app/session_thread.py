"""A planned session's own chat thread: reading it (with the old single-turn "Ask coach" Q&A
imported), appending to it, and carrying it onto the completed workout.

Storage is `StoreInterface.append_session_message` / `list_session_messages` (see
`swim_coach.models.SessionChatMessage`). Three rules live here so every caller agrees:

* The thread a session turn sees as history is ONLY this one -- never the Coach tab's.
* Old `Feedback` questions linked to the session (`type="question"`) are shown as the thread's
  earlier messages by a READ-TIME import: nothing is migrated or deleted, ids are derived from the
  feedback id (uuid5) so they are stable across reads, and the rows stay in the feedback log (and
  the coach's review queue) exactly as before.
* On a workout match the thread is COPIED onto `Workout.chat_messages` (same ids, so a re-run
  never duplicates and later messages are picked up). The session thread stays readable; the
  workout thread is the continuation of the conversation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from swim_coach.models import Feedback, Session, SessionChatMessage, Workout, WorkoutChatMessage
from swim_coach.store import StoreInterface

from app.logging_config import get_logger

log = get_logger("app.session_thread")

# An imported answer is stamped just after its question so the pair sorts question-first even
# when the feedback row has no separate reply time.
_ANSWER_OFFSET = timedelta(milliseconds=1)


def _feedback_belongs_to(entry: Feedback, session: Session) -> bool:
    """Same rule the PWA's `feedbackForSession` uses: a row stamped with a session id belongs to
    exactly that session; an older row falls back to (date, sport)."""
    if entry.session_id is not None:
        return entry.session_id == session.id
    return entry.session_date == session.date and entry.session_sport == session.sport


def _imported_pair(entry: Feedback, athlete_id: uuid.UUID, session_id: uuid.UUID) -> list[SessionChatMessage]:
    def make(suffix: str, role: str, body: str, at: datetime) -> SessionChatMessage:
        return SessionChatMessage(
            id=uuid.uuid5(entry.id, suffix), athlete_id=athlete_id, session_id=session_id,
            sender_role=role, body=body, created_at=at,
        )

    messages = [make("question", "athlete", entry.body, entry.created_at)]
    if entry.ai_provisional_answer:
        messages.append(make("ai-answer", "ai_coach", entry.ai_provisional_answer, entry.created_at + _ANSWER_OFFSET))
    if entry.coach_reply:
        replied_at = entry.coach_reply_at or entry.created_at + 2 * _ANSWER_OFFSET
        messages.append(make("coach-reply", "coach", entry.coach_reply, replied_at))
    return messages


def imported_feedback_messages(store: StoreInterface, slug: str, session: Session) -> list[SessionChatMessage]:
    """The session's old Q&A (Feedback rows) as thread messages -- read-only, never persisted."""
    athlete_id = store.load_athlete(slug).id
    out: list[SessionChatMessage] = []
    for entry in store.list_feedback(athlete=slug):
        if entry.type == "question" and entry.workout_id is None and _feedback_belongs_to(entry, session):
            out.extend(_imported_pair(entry, athlete_id, session.id))
    return out


def thread_messages(store: StoreInterface, slug: str, session: Session) -> list[SessionChatMessage]:
    """The whole thread, oldest first: imported old Q&A merged with the stored messages."""
    merged = imported_feedback_messages(store, slug, session) + store.list_session_messages(slug, session.id)
    return sorted(merged, key=lambda m: (m.created_at, str(m.id)))


def append_message(
    store: StoreInterface, athlete: str, session_id: uuid.UUID, sender_role: str, body: str,
    tool_trace: str | None = None,
) -> None:
    """Appends one message to the session's thread. Logs and swallows a save failure: losing the
    persisted copy of a message the athlete already saw stream by must never become a 500 on an
    otherwise-successful chat turn (same policy as the workout and conversation threads)."""
    try:
        store.append_session_message(
            athlete,
            SessionChatMessage(
                id=uuid.uuid4(), athlete_id=store.load_athlete(athlete).id, session_id=session_id,
                sender_role=sender_role, body=body, tool_trace=tool_trace,
                created_at=datetime.now(timezone.utc),
            ),
        )
    except Exception:  # noqa: BLE001
        log.error(
            "session thread message save failed", athlete=athlete, session_id=str(session_id),
            sender_role=sender_role, exc_info=True,
        )


def carry_over_to_workout(workout: Workout, store: StoreInterface, slug: str, session: Session) -> Workout:
    """`workout` with the session's thread folded into its `chat_messages` (deduplicated by id,
    kept in time order). Returns `workout` unchanged when the session has no thread."""
    messages = thread_messages(store, slug, session)
    if not messages:
        return workout
    existing = {m.id for m in workout.chat_messages}
    added = [
        WorkoutChatMessage(
            id=m.id, sender_role=m.sender_role, body=m.body, tool_trace=m.tool_trace, created_at=m.created_at,
        )
        for m in messages
        if m.id not in existing
    ]
    if not added:
        return workout
    merged = sorted([*workout.chat_messages, *added], key=lambda m: (m.created_at, str(m.id)))
    return workout.model_copy(update={"chat_messages": merged})
