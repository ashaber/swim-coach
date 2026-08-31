"""Best-effort email notification to a coach when an athlete submits
feedback (Andrew found out his wife had submitted feedback through the app
only by manually checking the coach-mode roster -- there was no
notification at all).

Fires from `routes/feedback.py`'s `create_feedback`/`ask_question`, scheduled
via FastAPI `BackgroundTasks` AFTER the athlete's own request has already
been persisted and responded to -- see that module for the wiring. This
module's own job is narrow: given a just-saved athlete-sourced `Feedback`
row, look up every ACTIVE coach of that athlete and email each one via
Resend (resend.com, a simple REST API -- one POST per email, no SDK).

`notify_coaches_of_feedback` NEVER raises. A misconfigured or failing
notification must never be allowed to break (or even slow down, given the
BackgroundTasks wiring) the feedback submission it's attached to -- so
every failure mode here is caught and logged, never propagated. This is the
one function in this module allowed a broad `except Exception` (see
CLAUDE.md/the global standard's "catch specific types higher in the stack" --
this IS the boundary: a background task with no caller left to observe a
raised exception).

No API key configured (`RESEND_API_KEY` unset -- the common case for local
dev/CI, and for prod before Andrew finishes signing up for Resend) means
this module makes NO HTTP call at all; it just logs that it skipped and
returns. `RESEND_API_KEY` is intentionally NOT in `config.py`'s
`_REQUIRED_VARS` for exactly this reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from app.auth import hash_token
from app.logging_config import get_logger

if TYPE_CHECKING:
    from swim_coach.models import Feedback
    from swim_coach.store import StoreInterface

    from app.config import Settings

log = get_logger("app.notify")

RESEND_API_URL = "https://api.resend.com/emails"
# A transactional-email API call has no business taking long -- this is a
# blocking call from this function's point of view, but it runs from a
# BackgroundTask (see routes/feedback.py), well after the athlete's own
# request already got its response, so a slow Resend response never makes
# the athlete wait. Deliberately short and with NO retry (unlike
# sync.py's `_request_with_retry`) -- a notification is best-effort; if it
# fails once, log and move on to the next coach rather than holding up the
# batch retrying an email.
_HTTP_TIMEOUT_S = 5.0
_SUCCESS_STATUS_CODES = (200, 202)


def _build_email(coach_email: str, athlete_name: str, feedback: "Feedback") -> dict:
    text = (
        f"{athlete_name} just submitted new feedback ({feedback.type}) through the app:\n\n"
        f"{feedback.body}\n\n"
        "Open the app's My Athletes tab to view the full entry and reply -- "
        "there's no direct link to it yet."
    )
    return {
        "to": [coach_email],
        "subject": f"New feedback from {athlete_name}",
        "text": text,
    }


def _send_one(
    client: httpx.Client,
    settings: "Settings",
    coach_email: str,
    athlete_name: str,
    feedback: "Feedback",
) -> None:
    """One coach's email. Its own try/except so one coach's send failing
    (network error, non-2xx from Resend, anything) never stops the rest of
    the batch from being notified -- see module docstring."""
    email_hash = hash_token(coach_email)  # never log a raw email -- see app/auth.py's hash_token
    payload = {"from": settings.resend_from_email, **_build_email(coach_email, athlete_name, feedback)}
    try:
        response = client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
    except Exception as exc:  # noqa: BLE001 - any transport error, this send just failed
        log.error(
            "notify.send_failed",
            coach_email_hash=email_hash,
            feedback_id=str(feedback.id),
            error=str(exc),
        )
        return

    if response.status_code not in _SUCCESS_STATUS_CODES:
        log.error(
            "notify.send_failed",
            coach_email_hash=email_hash,
            feedback_id=str(feedback.id),
            status_code=response.status_code,
            error=response.text[:500],
        )
        return

    log.info(
        "notify.sent",
        coach_email_hash=email_hash,
        feedback_id=str(feedback.id),
        status_code=response.status_code,
    )


def _notify_coaches_of_feedback(
    store: "StoreInterface",
    settings: "Settings",
    feedback: "Feedback",
    athlete_slug: str,
    *,
    client: httpx.Client | None,
) -> None:
    if not settings.resend_api_key:
        log.info("notify.skipped_no_api_key", athlete=athlete_slug, feedback_id=str(feedback.id))
        return

    grants = store.list_coach_grants(athlete_slug=athlete_slug, status="active")
    if not grants:
        log.info("notify.no_active_coaches", athlete=athlete_slug, feedback_id=str(feedback.id))
        return

    # Resolve each grant's coach_athlete_id (a UUID) back to a real email --
    # the SAME id->slug resolution require_auth (app/auth.py) already does
    # for Principal.coach_for, mirrored here rather than diverging: build the
    # id->slug map from list_allowed_emails() (the only existing capability
    # that enumerates every provisioned athlete's slug), then look up each
    # slug's own allowlisted email.
    allowed_emails = store.list_allowed_emails()
    email_by_slug = {
        entry.athlete_slug: entry.email for entry in allowed_emails if entry.athlete_slug is not None
    }
    slug_by_id = {store.load_athlete(slug).id: slug for slug in email_by_slug}

    athlete = store.load_athlete(athlete_slug)

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=_HTTP_TIMEOUT_S)
    try:
        for grant in grants:
            coach_slug = slug_by_id.get(grant.coach_athlete_id)
            coach_email = email_by_slug.get(coach_slug) if coach_slug is not None else None
            if coach_email is None:
                # Shouldn't normally happen (every coach signs in via the
                # same allowlist every athlete does) -- defensive, not fatal.
                log.warn(
                    "notify.coach_missing_allowlist_email",
                    athlete=athlete_slug,
                    grant_id=str(grant.id),
                )
                continue
            # The coach's OWN Settings-tab toggle -- independent of the
            # athlete's own toggle (that gates `notify_athlete_of_coach_reply`
            # below, the other direction). A coach who's opted out is simply
            # skipped, same "skip + log, never error" shape as the missing-
            # allowlist-email case just above.
            coach_profile = store.load_athlete(coach_slug)
            if not coach_profile.email_notifications_enabled:
                log.info(
                    "notify.coach_email_notifications_disabled",
                    athlete=athlete_slug,
                    coach_slug=coach_slug,
                    grant_id=str(grant.id),
                )
                continue
            _send_one(client, settings, coach_email, athlete.name, feedback)
    finally:
        if owns_client:
            client.close()


def notify_coaches_of_feedback(
    store: "StoreInterface",
    settings: "Settings",
    feedback: "Feedback",
    athlete_slug: str,
    *,
    client: httpx.Client | None = None,
) -> None:
    """Best-effort email notification to every ACTIVE coach of
    `athlete_slug` when a new athlete-submitted `Feedback` row is created.

    NEVER raises -- a failed/misconfigured notification must never break the
    actual feedback submission it's attached to. No-ops (with a log line) if
    `settings.resend_api_key` is unset.

    `client`, when given, is used as-is and NOT closed by this function --
    exists purely for test injection (an `httpx.Client` built over
    `httpx.MockTransport`, same convention as `app/sync.py`'s
    `IntervalsClient`). When omitted, a real short-lived `httpx.Client` is
    constructed and closed before returning.
    """
    try:
        _notify_coaches_of_feedback(store, settings, feedback, athlete_slug, client=client)
    except Exception as exc:  # noqa: BLE001 - this IS the boundary; see module docstring
        log.error(
            "notify.unexpected_failure",
            athlete=athlete_slug,
            feedback_id=str(feedback.id),
            error=str(exc),
        )


# --- athlete-facing mirror: coach reply -> athlete email --------------------
#
# `notify_athlete_of_coach_reply` fires from `coach_reply_to_feedback`
# (`backend/app/routes/coach.py`), scheduled via FastAPI `BackgroundTasks`
# AFTER `store.update_feedback` has already persisted the reply -- same
# "schedule after save, never block the request" discipline
# `notify_coaches_of_feedback`'s own callers use. This is the OTHER
# direction of the same Resend wiring: an athlete notified their own
# question got answered, gated on the ATHLETE's own
# `email_notifications_enabled` (not any coach's -- that gate lives in
# `_notify_coaches_of_feedback` above).


def _build_reply_email(athlete_name: str, feedback: "Feedback") -> dict:
    text = (
        f"Hi {athlete_name}, your coach just replied to your question on the app:\n\n"
        f"{feedback.coach_reply}\n\n"
        "Open the app's Feedback tab to see the full conversation."
    )
    return {
        "subject": "Your coach replied to your question",
        "text": text,
    }


def _send_reply_email(
    client: httpx.Client,
    settings: "Settings",
    athlete_email: str,
    athlete_name: str,
    feedback: "Feedback",
) -> None:
    """One athlete's coach-reply email. Same try/except-per-send shape as
    `_send_one` above; distinct `notify.reply_*` log event names so the two
    notification directions are never ambiguous in logs."""
    email_hash = hash_token(athlete_email)  # never log a raw email -- see app/auth.py's hash_token
    payload = {
        "from": settings.resend_from_email,
        "to": [athlete_email],
        **_build_reply_email(athlete_name, feedback),
    }
    try:
        response = client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
    except Exception as exc:  # noqa: BLE001 - any transport error, this send just failed
        log.error(
            "notify.reply_send_failed",
            athlete_email_hash=email_hash,
            feedback_id=str(feedback.id),
            error=str(exc),
        )
        return

    if response.status_code not in _SUCCESS_STATUS_CODES:
        log.error(
            "notify.reply_send_failed",
            athlete_email_hash=email_hash,
            feedback_id=str(feedback.id),
            status_code=response.status_code,
            error=response.text[:500],
        )
        return

    log.info(
        "notify.reply_sent",
        athlete_email_hash=email_hash,
        feedback_id=str(feedback.id),
        status_code=response.status_code,
    )


def _notify_athlete_of_coach_reply(
    store: "StoreInterface",
    settings: "Settings",
    feedback: "Feedback",
    athlete_slug: str,
    *,
    client: httpx.Client | None,
) -> None:
    if not settings.resend_api_key:
        log.info(
            "notify.reply_skipped_no_api_key", athlete=athlete_slug, feedback_id=str(feedback.id)
        )
        return

    athlete = store.load_athlete(athlete_slug)
    if not athlete.email_notifications_enabled:
        log.info(
            "notify.reply_skipped_notifications_disabled",
            athlete=athlete_slug,
            feedback_id=str(feedback.id),
        )
        return

    # Same id/slug->email resolution `_notify_coaches_of_feedback` uses
    # above, just looked up for this one already-known `athlete_slug`
    # directly rather than resolved via a coach grant.
    allowed_emails = store.list_allowed_emails()
    email_by_slug = {
        entry.athlete_slug: entry.email for entry in allowed_emails if entry.athlete_slug is not None
    }
    athlete_email = email_by_slug.get(athlete_slug)
    if athlete_email is None:
        # Shouldn't normally happen (every athlete signs in via the same
        # allowlist every coach does) -- defensive, not fatal.
        log.warn(
            "notify.reply_athlete_missing_allowlist_email",
            athlete=athlete_slug,
            feedback_id=str(feedback.id),
        )
        return

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=_HTTP_TIMEOUT_S)
    try:
        _send_reply_email(client, settings, athlete_email, athlete.name, feedback)
    finally:
        if owns_client:
            client.close()


def notify_athlete_of_coach_reply(
    store: "StoreInterface",
    settings: "Settings",
    feedback: "Feedback",
    athlete_slug: str,
    *,
    client: httpx.Client | None = None,
) -> None:
    """Best-effort email notification to `athlete_slug` when a coach replies
    to their own submitted `Feedback` question (`coach_reply_to_feedback`,
    `backend/app/routes/coach.py`) -- the athlete-facing mirror of
    `notify_coaches_of_feedback` above.

    NEVER raises -- same reasoning as `notify_coaches_of_feedback`: a
    failed/misconfigured notification must never break (or slow down) the
    coach's reply it's attached to. No-ops (with a log line) if
    `settings.resend_api_key` is unset, or if `athlete_slug`'s own
    `email_notifications_enabled` is False.

    `client`, same test-injection convention as `notify_coaches_of_feedback`
    -- used as-is and NOT closed by this function when given.
    """
    try:
        _notify_athlete_of_coach_reply(store, settings, feedback, athlete_slug, client=client)
    except Exception as exc:  # noqa: BLE001 - this IS the boundary; see module docstring
        log.error(
            "notify.reply_unexpected_failure",
            athlete=athlete_slug,
            feedback_id=str(feedback.id),
            error=str(exc),
        )
