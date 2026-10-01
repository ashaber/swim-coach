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

from datetime import timedelta
from typing import TYPE_CHECKING, Literal

import httpx

from app.auth import hash_token
from app.logging_config import get_logger

if TYPE_CHECKING:
    from swim_coach.models import ConversationMessage, Feedback, WorkoutChatMessage
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


# --- workout chat thread (IDEA 016): human coach -> athlete email --------------------------
#
# `notify_athlete_of_workout_chat_message` fires from the coach-side send route
# (`backend/app/routes/coach.py`), scheduled via BackgroundTasks AFTER the message has already
# been persisted onto the workout -- same "schedule after save, never block the request"
# discipline every other notifier in this module uses. Deliberately its OWN functions, not a
# reuse of `notify_athlete_of_coach_reply` above: that one hardcodes `Feedback`'s own
# `coach_reply`/subject line, and a workout chat message has neither.


def _build_workout_chat_email(athlete_name: str, message: "WorkoutChatMessage") -> dict:
    text = (
        f"Hi {athlete_name}, your coach just commented on one of your workouts:\n\n"
        f"{message.body}\n\n"
        "Open the app to see the full conversation."
    )
    return {"subject": "Your coach commented on a workout", "text": text}


def _send_workout_chat_email(
    client: httpx.Client, settings: "Settings", athlete_email: str, athlete_name: str,
    message: "WorkoutChatMessage",
) -> None:
    email_hash = hash_token(athlete_email)
    payload = {
        "from": settings.resend_from_email,
        "to": [athlete_email],
        **_build_workout_chat_email(athlete_name, message),
    }
    try:
        response = client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
    except Exception as exc:  # noqa: BLE001 - any transport error, this send just failed
        log.error(
            "notify.workout_chat_send_failed", athlete_email_hash=email_hash,
            message_id=str(message.id), error=str(exc),
        )
        return

    if response.status_code not in _SUCCESS_STATUS_CODES:
        log.error(
            "notify.workout_chat_send_failed", athlete_email_hash=email_hash,
            message_id=str(message.id), status_code=response.status_code, error=response.text[:500],
        )
        return

    log.info(
        "notify.workout_chat_sent", athlete_email_hash=email_hash,
        message_id=str(message.id), status_code=response.status_code,
    )


def _notify_athlete_of_workout_chat_message(
    store: "StoreInterface", settings: "Settings", message: "WorkoutChatMessage",
    athlete_slug: str, *, client: httpx.Client | None,
) -> None:
    if not settings.resend_api_key:
        log.info("notify.workout_chat_skipped_no_api_key", athlete=athlete_slug, message_id=str(message.id))
        return

    athlete = store.load_athlete(athlete_slug)
    if not athlete.email_notifications_enabled:
        log.info(
            "notify.workout_chat_skipped_notifications_disabled",
            athlete=athlete_slug, message_id=str(message.id),
        )
        return

    allowed_emails = store.list_allowed_emails()
    email_by_slug = {
        entry.athlete_slug: entry.email for entry in allowed_emails if entry.athlete_slug is not None
    }
    athlete_email = email_by_slug.get(athlete_slug)
    if athlete_email is None:
        log.warn(
            "notify.workout_chat_athlete_missing_allowlist_email",
            athlete=athlete_slug, message_id=str(message.id),
        )
        return

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=_HTTP_TIMEOUT_S)
    try:
        _send_workout_chat_email(client, settings, athlete_email, athlete.name, message)
    finally:
        if owns_client:
            client.close()


def notify_athlete_of_workout_chat_message(
    store: "StoreInterface", settings: "Settings", message: "WorkoutChatMessage",
    athlete_slug: str, *, client: httpx.Client | None = None,
) -> None:
    """Best-effort email notification to `athlete_slug` when a human coach comments in one of
    her workout's chat threads (IDEA 016). NEVER raises -- same reasoning as every other
    notifier in this module. No-ops (with a log line) if `settings.resend_api_key` is unset, or
    if `athlete_slug`'s own `email_notifications_enabled` is False.

    `client`, same test-injection convention as the rest of this module -- used as-is and NOT
    closed by this function when given.
    """
    try:
        _notify_athlete_of_workout_chat_message(store, settings, message, athlete_slug, client=client)
    except Exception as exc:  # noqa: BLE001 - this IS the boundary; see module docstring
        log.error(
            "notify.workout_chat_unexpected_failure",
            athlete=athlete_slug, message_id=str(message.id), error=str(exc),
        )


# --- coach-ai-planning: human coach confirmed a plan change -> athlete email ---------------
#
# `notify_athlete_of_coach_plan_change` fires from `app/tools.py`'s `_confirm_author_macro_plan`/
# `_confirm_author_week_plan`, called DIRECTLY (not via FastAPI `BackgroundTasks` -- tool
# handlers run inside the streaming generator, with no `BackgroundTasks` object reachable from
# there) immediately after the plan change has already been persisted -- same "notify after
# save, never before" discipline every other notifier in this module uses, just without the
# BackgroundTasks indirection. Best-effort, NEVER raises, same as every notifier above --
# see `_handle_author_macro_plan`/`_handle_author_week_plan`'s own callers: a failed
# notification must never turn an otherwise-successful coach-confirmed plan write into an
# error response.


def _build_plan_change_email(
    athlete_name: str, coach_name: str, plan_kind: "Literal['macro', 'week']", words: str
) -> dict:
    what = "your macro training plan" if plan_kind == "macro" else "one of your weekly plans"
    text = (
        f"Hi {athlete_name}, your coach {coach_name} just confirmed a change to {what} on your "
        f"behalf, in their own words:\n\n{words}\n\n"
        "Open the app's Plan tab to see the full updated plan and the reasoning behind it."
    )
    return {"subject": "Your coach updated your training plan", "text": text}


def _send_plan_change_email(
    client: httpx.Client, settings: "Settings", athlete_email: str, athlete_name: str,
    coach_name: str, plan_kind: "Literal['macro', 'week']", words: str,
) -> None:
    email_hash = hash_token(athlete_email)
    payload = {
        "from": settings.resend_from_email,
        "to": [athlete_email],
        **_build_plan_change_email(athlete_name, coach_name, plan_kind, words),
    }
    try:
        response = client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
    except Exception as exc:  # noqa: BLE001 - any transport error, this send just failed
        log.error(
            "notify.plan_change_send_failed", athlete_email_hash=email_hash,
            plan_kind=plan_kind, error=str(exc),
        )
        return

    if response.status_code not in _SUCCESS_STATUS_CODES:
        log.error(
            "notify.plan_change_send_failed", athlete_email_hash=email_hash,
            plan_kind=plan_kind, status_code=response.status_code, error=response.text[:500],
        )
        return

    log.info(
        "notify.plan_change_sent", athlete_email_hash=email_hash,
        plan_kind=plan_kind, status_code=response.status_code,
    )


def _notify_athlete_of_coach_plan_change(
    store: "StoreInterface", settings: "Settings", athlete_slug: str, coach_slug: str,
    plan_kind: "Literal['macro', 'week']", words: str, *, client: httpx.Client | None,
) -> None:
    if not settings.resend_api_key:
        log.info("notify.plan_change_skipped_no_api_key", athlete=athlete_slug, plan_kind=plan_kind)
        return

    athlete = store.load_athlete(athlete_slug)
    if not athlete.email_notifications_enabled:
        log.info(
            "notify.plan_change_skipped_notifications_disabled",
            athlete=athlete_slug, plan_kind=plan_kind,
        )
        return

    allowed_emails = store.list_allowed_emails()
    email_by_slug = {
        entry.athlete_slug: entry.email for entry in allowed_emails if entry.athlete_slug is not None
    }
    athlete_email = email_by_slug.get(athlete_slug)
    if athlete_email is None:
        log.warn(
            "notify.plan_change_athlete_missing_allowlist_email",
            athlete=athlete_slug, plan_kind=plan_kind,
        )
        return

    # Best-effort coach display name -- falls back to the coach's own slug if, for whatever
    # reason, their athlete profile can't be loaded (never fatal to the notification itself).
    try:
        coach_name = store.load_athlete(coach_slug).name if coach_slug else "your coach"
    except Exception:  # noqa: BLE001 - a missing/unloadable coach profile never blocks the email
        coach_name = "your coach"

    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=_HTTP_TIMEOUT_S)
    try:
        _send_plan_change_email(client, settings, athlete_email, athlete.name, coach_name, plan_kind, words)
    finally:
        if owns_client:
            client.close()


def notify_athlete_of_coach_plan_change(
    store: "StoreInterface", settings: "Settings", athlete_slug: str, coach_slug: str,
    plan_kind: "Literal['macro', 'week']", words: str, *, client: httpx.Client | None = None,
) -> None:
    """Best-effort email notification to `athlete_slug` when their human coach confirms a
    macro/week plan change on their behalf (coach-ai-planning build, Andrew's decision 1).
    NEVER raises -- same reasoning as every other notifier in this module. No-ops (with a log
    line) if `settings.resend_api_key` is unset, or if `athlete_slug`'s own
    `email_notifications_enabled` is False.

    `words` is the coach's own confirmation words (or a short summary of them) -- surfaced
    directly in the email so the athlete sees what was actually said, not a paraphrase.

    `client`, same test-injection convention as the rest of this module -- used as-is and NOT
    closed by this function when given.
    """
    try:
        _notify_athlete_of_coach_plan_change(store, settings, athlete_slug, coach_slug, plan_kind, words, client=client)
    except Exception as exc:  # noqa: BLE001 - this IS the boundary; see module docstring
        log.error(
            "notify.plan_change_unexpected_failure",
            athlete=athlete_slug, plan_kind=plan_kind, error=str(exc),
        )


# --- athlete<->coach conversation (IDEA 016 Part 2) -> email, both directions ---------------
#
# Email is the out-of-app counterpart of the in-app unread badge (src/unread.js): it reaches
# someone who has the app closed. Fires from `routes/conversation.py` via BackgroundTasks after
# the message is saved (coach -> athlete) or after the athlete's streamed turn is accepted
# (athlete -> coach). Throttled: a message is NOT emailed if the same sender already sent one
# in this thread within `_CONVERSATION_EMAIL_THROTTLE` -- a back-and-forth chat must not become
# one email per message. Same best-effort, never-raises contract as every notifier above.

_CONVERSATION_EMAIL_THROTTLE = timedelta(minutes=10)


def _conversation_recently_notified(
    store: "StoreInterface", athlete_slug: str, message: "ConversationMessage"
) -> bool:
    window_start = message.created_at - _CONVERSATION_EMAIL_THROTTLE
    recent = store.list_conversation_messages(
        athlete_slug, message.coach_athlete_id, since=window_start
    )
    return any(m.id != message.id and m.sender_role == message.sender_role for m in recent)


def _send_conversation_email(
    client: httpx.Client, settings: "Settings", to_email: str, subject: str, text: str,
    message: "ConversationMessage",
) -> None:
    email_hash = hash_token(to_email)
    payload = {
        "from": settings.resend_from_email, "to": [to_email], "subject": subject, "text": text,
    }
    try:
        response = client.post(
            RESEND_API_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
            json=payload,
        )
    except Exception as exc:  # noqa: BLE001 - any transport error, this send just failed
        log.error(
            "notify.conversation_send_failed", to_email_hash=email_hash,
            message_id=str(message.id), error=str(exc),
        )
        return
    if response.status_code not in _SUCCESS_STATUS_CODES:
        log.error(
            "notify.conversation_send_failed", to_email_hash=email_hash,
            message_id=str(message.id), status_code=response.status_code, error=response.text[:500],
        )
        return
    log.info(
        "notify.conversation_sent", to_email_hash=email_hash,
        message_id=str(message.id), status_code=response.status_code,
    )


def _notify_conversation_recipient(
    store: "StoreInterface", settings: "Settings", message: "ConversationMessage",
    athlete_slug: str, *, to_coach: bool, client: httpx.Client | None,
) -> None:
    if not settings.resend_api_key:
        log.info("notify.conversation_skipped_no_api_key", athlete=athlete_slug, message_id=str(message.id))
        return

    allowed = store.list_allowed_emails()
    email_by_slug = {e.athlete_slug: e.email for e in allowed if e.athlete_slug is not None}
    athlete = store.load_athlete(athlete_slug)
    if to_coach:
        slug_by_id = {store.load_athlete(s).id: s for s in email_by_slug}
        recipient_slug = slug_by_id.get(message.coach_athlete_id)
    else:
        recipient_slug = athlete_slug
    recipient_email = email_by_slug.get(recipient_slug) if recipient_slug is not None else None
    if recipient_email is None:
        log.warn("notify.conversation_missing_allowlist_email", athlete=athlete_slug, message_id=str(message.id))
        return
    recipient = store.load_athlete(recipient_slug)
    if not recipient.email_notifications_enabled:
        log.info("notify.conversation_skipped_notifications_disabled", athlete=athlete_slug, message_id=str(message.id))
        return
    if _conversation_recently_notified(store, athlete_slug, message):
        log.info("notify.conversation_skipped_throttled", athlete=athlete_slug, message_id=str(message.id))
        return

    if to_coach:
        subject = f"New message from {athlete.name}"
        text = (
            f"Hi {recipient.name}, {athlete.name} sent a message in your conversation:\n\n"
            f"{message.body}\n\nOpen the app's My Athletes tab, Conversations, to reply."
        )
    else:
        subject = "Your coach sent you a message"
        text = (
            f"Hi {athlete.name}, your coach sent you a message:\n\n{message.body}\n\n"
            "Open the app's Coach tab to reply."
        )
    owns_client = client is None
    if client is None:
        client = httpx.Client(timeout=_HTTP_TIMEOUT_S)
    try:
        _send_conversation_email(client, settings, recipient_email, subject, text, message)
    finally:
        if owns_client:
            client.close()


def notify_athlete_of_conversation_message(
    store: "StoreInterface", settings: "Settings", message: "ConversationMessage",
    athlete_slug: str, *, client: httpx.Client | None = None,
) -> None:
    """Best-effort, throttled email to `athlete_slug` when their human coach posts in the
    conversation thread. NEVER raises. Gated on the athlete's own
    `email_notifications_enabled`; no-ops without `settings.resend_api_key`."""
    try:
        _notify_conversation_recipient(
            store, settings, message, athlete_slug, to_coach=False, client=client)
    except Exception as exc:  # noqa: BLE001 - this IS the boundary; see module docstring
        log.error(
            "notify.conversation_unexpected_failure",
            athlete=athlete_slug, message_id=str(message.id), error=str(exc),
        )


def notify_coach_of_conversation_message(
    store: "StoreInterface", settings: "Settings", message: "ConversationMessage",
    athlete_slug: str, *, client: httpx.Client | None = None,
) -> None:
    """Mirror of `notify_athlete_of_conversation_message`: best-effort, throttled email to the
    thread's coach (`message.coach_athlete_id`) when the athlete posts. NEVER raises. Gated on
    the COACH's own `email_notifications_enabled`."""
    try:
        _notify_conversation_recipient(
            store, settings, message, athlete_slug, to_coach=True, client=client)
    except Exception as exc:  # noqa: BLE001 - this IS the boundary; see module docstring
        log.error(
            "notify.conversation_unexpected_failure",
            athlete=athlete_slug, message_id=str(message.id), error=str(exc),
        )
