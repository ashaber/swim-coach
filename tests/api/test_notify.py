"""backend/app/notify.py -- best-effort coach-notification emails (Resend)
fired when an athlete submits feedback.

No real HTTP: every Resend call is served by an `httpx.MockTransport`
handler injected via `notify_coaches_of_feedback`'s `client=` param (same
"no network in tests" convention as `tests/api/test_sync.py`'s
`IntervalsClient(transport=...)`).

Uses a real `FileStore(base_dir=tmp_path)` (cheap, and proves the real
grant->email resolution logic end to end) rather than mocking the store
itself -- seeded with real `Athlete`/`AllowedEmail`/`CoachGrant` data via
`tests/store_contract.py`'s existing `_coach_athlete()`/`_coach_grant()`/
`_feedback()` helpers, adapted the same way `test_store_contract.py` already
does.

`backend/app` isn't on `sys.path` by default outside `tests/api` (whose
`conftest.py` inserts it) -- this file does the same insertion itself so it
can run standalone under `tests/unit`.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from swim_coach.models import Athlete, Feedback  # noqa: E402
from swim_coach.store import FileStore  # noqa: E402

from app.config import Settings  # noqa: E402
from app.notify import (  # noqa: E402
    RESEND_API_URL,
    notify_athlete_of_coach_reply,
    notify_coaches_of_feedback,
)

SLUG = "renee"


def _settings(**overrides) -> Settings:
    fields: dict = dict(
        anthropic_api_key="sk-ant-test-not-real",
        api_token_hash="deadbeef",
        claude_model="claude-sonnet-5",
        claude_thinking="adaptive",
        allowed_origins=["https://ashaber.github.io"],
        athletes_dir=Path("../athletes"),
        library_dir=Path("../library"),
        research_dir=Path("../research"),
        port=8000,
        chat_rate_per_min=20,
        store_backend="file",
        database_url=None,
        google_client_id="test-client-id.apps.googleusercontent.com",
        session_ttl_days=30,
        chat_daily_cap_per_athlete=50,
        resend_api_key="re_test_key_not_real",
        resend_from_email="onboarding@resend.dev",
    )
    fields.update(overrides)
    return Settings(**fields)


def _athlete() -> Athlete:
    return Athlete(id=uuid.uuid4(), slug=SLUG, name="Renee Example")


def _coach_athlete(
    slug: str = "tim", name: str = "Tim Coach", *, email_notifications_enabled: bool = True
) -> Athlete:
    return Athlete(
        id=uuid.uuid4(),
        slug=slug,
        name=name,
        email_notifications_enabled=email_notifications_enabled,
    )


def _feedback(athlete_id: uuid.UUID, **overrides) -> Feedback:
    data: dict = dict(
        id=uuid.uuid4(),
        athlete_id=athlete_id,
        type="feature_request",
        source="athlete",
        body="Would love a swim-cap-color-coded interval clock.",
        context={},
        status="open",
        created_at=datetime.now(timezone.utc),
    )
    data.update(overrides)
    return Feedback(**data)


def _seeded_store(tmp_path: Path) -> tuple[FileStore, Athlete]:
    """A FileStore with just the athlete saved -- no coaches/grants yet."""
    store = FileStore(base_dir=tmp_path)
    athlete = _athlete()
    store.save_athlete(athlete)
    return store, athlete


def _grant_coach(
    store: FileStore,
    athlete: Athlete,
    *,
    slug: str,
    name: str,
    email: str,
    email_notifications_enabled: bool = True,
) -> Athlete:
    """Saves a coach athlete, allowlists their email, and grants them active
    coach access to `athlete` -- the full real path a live coach goes
    through, exercised end to end (same as require_auth's own resolution)."""
    coach = _coach_athlete(slug=slug, name=name, email_notifications_enabled=email_notifications_enabled)
    store.save_athlete(coach)
    store.add_allowed_email(email, athlete=coach.slug)
    store.create_coach_grant(coach_slug=coach.slug, athlete_slug=athlete.slug)
    return coach


def _handler_ok(captured: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": json.loads(request.content),
            }
        )
        return httpx.Response(200, json={"id": "resend-id-123"})

    return handler


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- no api key configured --------------------------------------------------


def test_no_api_key_makes_no_http_call(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    _grant_coach(store, athlete, slug="tim", name="Tim Coach", email="tim@example.com")
    feedback = _feedback(athlete.id)

    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    settings = _settings(resend_api_key=None)
    notify_coaches_of_feedback(
        store, settings, feedback, SLUG, client=_client(handler)
    )

    assert called == []


# --- no active coaches -------------------------------------------------------


def test_no_active_coach_grants_makes_no_http_call(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    feedback = _feedback(athlete.id)

    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    settings = _settings()
    notify_coaches_of_feedback(store, settings, feedback, SLUG, client=_client(handler))

    assert called == []


def test_revoked_grant_is_not_notified(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    coach = _grant_coach(store, athlete, slug="tim", name="Tim Coach", email="tim@example.com")
    grant = store.list_coach_grants(athlete_slug=SLUG, status="active")[0]
    store.revoke_coach_grant(grant.id)
    feedback = _feedback(athlete.id)

    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    notify_coaches_of_feedback(store, _settings(), feedback, SLUG, client=_client(handler))

    assert called == []


# --- one active coach, happy path -------------------------------------------


def test_one_active_coach_sends_one_email(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    _grant_coach(store, athlete, slug="tim", name="Tim Coach", email="tim@example.com")
    feedback = _feedback(athlete.id, body="the plan tab is broken on iOS")

    captured: list[dict] = []
    settings = _settings()
    notify_coaches_of_feedback(
        store, settings, feedback, SLUG, client=_client(_handler_ok(captured))
    )

    assert len(captured) == 1
    call = captured[0]
    assert call["url"] == RESEND_API_URL
    assert call["headers"]["authorization"] == f"Bearer {settings.resend_api_key}"
    assert call["body"]["from"] == settings.resend_from_email
    assert call["body"]["to"] == ["tim@example.com"]
    assert call["body"]["subject"] == "New feedback from Renee Example"
    assert "the plan tab is broken on iOS" in call["body"]["text"]


# --- multiple coaches, one failing -------------------------------------------


def test_multiple_coaches_all_notified_even_if_one_fails(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    _grant_coach(store, athlete, slug="tim", name="Tim Coach", email="tim@example.com")
    _grant_coach(store, athlete, slug="andrew", name="Andrew Shaber", email="andrew@example.com")
    feedback = _feedback(athlete.id)

    captured: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        body = json.loads(request.content)
        if body["to"] == ["tim@example.com"]:
            raise httpx.ConnectError("boom", request=request)
        captured.append(body)
        return httpx.Response(200, json={"id": "ok"})

    notify_coaches_of_feedback(store, _settings(), feedback, SLUG, client=_client(handler))

    assert len(captured) == 1
    assert captured[0]["to"] == ["andrew@example.com"]


# --- non-2xx from resend -----------------------------------------------------


def test_non_2xx_response_is_logged_and_does_not_raise(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    _grant_coach(store, athlete, slug="tim", name="Tim Coach", email="tim@example.com")
    feedback = _feedback(athlete.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "invalid from address"})

    # Must not raise.
    notify_coaches_of_feedback(store, _settings(), feedback, SLUG, client=_client(handler))


# --- coach grant with no matching allowlist email ---------------------------


def test_coach_with_no_allowlist_entry_is_skipped_not_crashed(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    # A coach athlete + grant exist, but the coach was never added to the
    # allowlist (shouldn't normally happen -- defensive case).
    coach = _coach_athlete(slug="tim", name="Tim Coach")
    store.save_athlete(coach)
    store.create_coach_grant(coach_slug=coach.slug, athlete_slug=athlete.slug)
    feedback = _feedback(athlete.id)

    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    # Must not raise, and must not call out for the unresolvable coach.
    notify_coaches_of_feedback(store, _settings(), feedback, SLUG, client=_client(handler))

    assert called == []


def test_unresolvable_coach_does_not_block_a_resolvable_one(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    # One coach with no allowlist entry...
    ghost = _coach_athlete(slug="ghost", name="Ghost Coach")
    store.save_athlete(ghost)
    store.create_coach_grant(coach_slug=ghost.slug, athlete_slug=athlete.slug)
    # ...and one coach that resolves fully.
    _grant_coach(store, athlete, slug="tim", name="Tim Coach", email="tim@example.com")
    feedback = _feedback(athlete.id)

    captured: list[dict] = []
    notify_coaches_of_feedback(
        store, _settings(), feedback, SLUG, client=_client(_handler_ok(captured))
    )

    assert len(captured) == 1
    assert captured[0]["body"]["to"] == ["tim@example.com"]


# --- coach's own email_notifications_enabled gate ---------------------------
#
# `notify_coaches_of_feedback`'s first real behavior change (A4): a coach who
# has toggled their own Settings-tab email notifications off must never be
# emailed, independent of the athlete's own toggle (that's the athlete-
# facing `notify_athlete_of_coach_reply` gate below, tested separately).


def test_coach_with_notifications_disabled_is_skipped(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    _grant_coach(
        store,
        athlete,
        slug="tim",
        name="Tim Coach",
        email="tim@example.com",
        email_notifications_enabled=False,
    )
    feedback = _feedback(athlete.id)

    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    notify_coaches_of_feedback(store, _settings(), feedback, SLUG, client=_client(handler))

    assert called == []


def test_coach_with_notifications_enabled_is_notified(tmp_path) -> None:
    # Explicit true/true case (the default, but asserted explicitly here per
    # this build's true/true, false-skips, mixed test matrix).
    store, athlete = _seeded_store(tmp_path)
    _grant_coach(
        store,
        athlete,
        slug="tim",
        name="Tim Coach",
        email="tim@example.com",
        email_notifications_enabled=True,
    )
    feedback = _feedback(athlete.id)

    captured: list[dict] = []
    notify_coaches_of_feedback(
        store, _settings(), feedback, SLUG, client=_client(_handler_ok(captured))
    )

    assert len(captured) == 1
    assert captured[0]["body"]["to"] == ["tim@example.com"]


def test_mixed_coach_notification_toggles_only_notifies_the_enabled_one(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    _grant_coach(
        store,
        athlete,
        slug="tim",
        name="Tim Coach",
        email="tim@example.com",
        email_notifications_enabled=False,
    )
    _grant_coach(
        store,
        athlete,
        slug="andrew",
        name="Andrew Shaber",
        email="andrew@example.com",
        email_notifications_enabled=True,
    )
    feedback = _feedback(athlete.id)

    captured: list[dict] = []
    notify_coaches_of_feedback(
        store, _settings(), feedback, SLUG, client=_client(_handler_ok(captured))
    )

    assert len(captured) == 1
    assert captured[0]["body"]["to"] == ["andrew@example.com"]


# --- notify_athlete_of_coach_reply (A4's new athlete-facing notifier) -------
#
# The mirror direction: an ATHLETE is notified when a coach replies to their
# own submitted question (`coach_reply_to_feedback`, routes/coach.py). Same
# never-raises/no-api-key-no-op/client-injection conventions as
# `notify_coaches_of_feedback` above, gated on the ATHLETE's own
# `email_notifications_enabled` (not any coach's).


def _replied_feedback(athlete_id: uuid.UUID, **overrides) -> Feedback:
    return _feedback(
        athlete_id,
        type="question",
        body="how should I fuel a 4hr swim?",
        coach_reply="60-90g carbs/hr, start early.",
        coach_reply_at=datetime.now(timezone.utc),
        **overrides,
    )


def test_athlete_notify_no_api_key_makes_no_http_call(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    store.add_allowed_email("renee@example.com", athlete=athlete.slug)
    feedback = _replied_feedback(athlete.id)

    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    settings = _settings(resend_api_key=None)
    notify_athlete_of_coach_reply(store, settings, feedback, SLUG, client=_client(handler))

    assert called == []


def test_athlete_notify_disabled_toggle_makes_no_http_call(tmp_path) -> None:
    store = FileStore(base_dir=tmp_path)
    athlete = Athlete(
        id=uuid.uuid4(), slug=SLUG, name="Renee Example", email_notifications_enabled=False
    )
    store.save_athlete(athlete)
    store.add_allowed_email("renee@example.com", athlete=athlete.slug)
    feedback = _replied_feedback(athlete.id)

    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    notify_athlete_of_coach_reply(store, _settings(), feedback, SLUG, client=_client(handler))

    assert called == []


def test_athlete_notify_enabled_toggle_sends_email(tmp_path) -> None:
    # Explicit true case -- default, but asserted explicitly per this
    # build's true/true, false-skips, mixed test matrix.
    store, athlete = _seeded_store(tmp_path)
    assert athlete.email_notifications_enabled is True
    store.add_allowed_email("renee@example.com", athlete=athlete.slug)
    feedback = _replied_feedback(athlete.id)

    captured: list[dict] = []
    notify_athlete_of_coach_reply(
        store, _settings(), feedback, SLUG, client=_client(_handler_ok(captured))
    )

    assert len(captured) == 1
    call = captured[0]
    assert call["url"] == RESEND_API_URL
    assert call["body"]["to"] == ["renee@example.com"]
    assert call["body"]["from"] == _settings().resend_from_email
    assert "60-90g carbs/hr, start early." in call["body"]["text"]


def test_athlete_notify_missing_allowlist_email_is_skipped_not_crashed(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    # No add_allowed_email call at all -- defensive case, shouldn't normally
    # happen since every athlete signs in via the allowlist.
    feedback = _replied_feedback(athlete.id)

    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(request)
        return httpx.Response(200, json={})

    # Must not raise.
    notify_athlete_of_coach_reply(store, _settings(), feedback, SLUG, client=_client(handler))

    assert called == []


def test_athlete_notify_non_2xx_response_is_logged_and_does_not_raise(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    store.add_allowed_email("renee@example.com", athlete=athlete.slug)
    feedback = _replied_feedback(athlete.id)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"message": "invalid from address"})

    # Must not raise.
    notify_athlete_of_coach_reply(store, _settings(), feedback, SLUG, client=_client(handler))


def test_athlete_notify_transport_error_does_not_raise(tmp_path) -> None:
    store, athlete = _seeded_store(tmp_path)
    store.add_allowed_email("renee@example.com", athlete=athlete.slug)
    feedback = _replied_feedback(athlete.id)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    # Must not raise.
    notify_athlete_of_coach_reply(store, _settings(), feedback, SLUG, client=_client(handler))
