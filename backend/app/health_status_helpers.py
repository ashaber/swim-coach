"""Shared "make sure a human sees this" linking logic for a just-saved
`HealthStatus` row.

Factored out of `app/tools.py`'s `_handle_record_health_status` (the AI
chat tool path) so `app/routes/health_status.py`'s new athlete self-service
POST route (web/coach-health-nav-and-athlete-self-log) can guarantee the
exact same coach-visibility contract without duplicating the linking logic
itself: a coach should be notified when the athlete logs a health status
through EITHER path, for the same "a human will actually see this" reason.

See `HealthStatus`'s own docstring (engine/swim_coach/models.py) and
`tools.py`'s original inline version (before this factor-out) for the full
rationale on why this exists as a SEPARATE guarantee from the HealthStatus
write itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from swim_coach.models import Feedback, HealthStatus
from swim_coach.store import StoreInterface

from app.logging_config import get_logger

log = get_logger(__name__)


def link_health_status_feedback(
    store: StoreInterface,
    *,
    slug: str,
    athlete_id: uuid.UUID,
    status: HealthStatus,
) -> tuple[str | None, str | None]:
    """Creates a linked `needs_human_review=True` Feedback row for `status`,
    reusing the same durable seam `_handle_flag_for_coach_review` already
    writes through (the coach roster's existing Feedback section, its
    `needs_human_review` chip, and the unread-count badge all already
    surface this with no new plumbing needed).

    Returns `(feedback_id, notify_error)` -- exactly one is `None`. NEVER
    raises: `status` is assumed to already be durably saved by the caller
    before this is invoked, so ANY failure here must not look like the
    calling operation failed outright, but must be logged loudly rather than
    silently swallowed. Callers surface a non-`None` `notify_error` back to
    whoever is reading their own result (a chat reply, an HTTP response
    body) so the failure is visible there too, even though the health
    record itself is safe either way.
    """
    try:
        feedback = Feedback(
            id=uuid.uuid4(),
            athlete_id=athlete_id,
            type="coach_review",
            source="coach",
            body=status.description,
            context={
                "health_status_id": str(status.id),
                "restriction": status.restriction,
                "health_status_source": status.source,
            },
            status="open",
            created_at=datetime.now(timezone.utc),
            needs_human_review=True,
        )
        store.save_feedback(feedback)
        return str(feedback.id), None
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring above.
        notify_error = str(exc)
        log.error(
            "health status recorded but coach-notification write failed",
            athlete=slug,
            health_status_id=str(status.id),
            error=notify_error,
        )
        return None, notify_error
