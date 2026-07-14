"""Google ID token verification -- POST /api/auth/google's crypto boundary.

Wraps `google.oauth2.id_token.verify_oauth2_token` (the `google-auth`
library) so `routes/auth.py` never touches JWKS-fetching/verification
mechanics directly, and so tests can inject a fake verifier -- no LLM/network
calls in tests is a hard repo rule, and this function makes a real HTTPS
call to Google to fetch/cache its signing keys.

`get_google_verifier` is a FastAPI dependency, the same pattern
`routes/chat.py`'s `get_claude_chat` uses: tests override it via
`app.dependency_overrides[get_google_verifier] = lambda: fake_verify`, so no
real network call is ever made in the test suite.
"""

from __future__ import annotations

from typing import Callable

from fastapi import Request
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token

# A verifier is `raw_id_token -> claims dict`. Raises ValueError (the
# google-auth library's own exception type for any verification failure --
# bad signature, wrong audience, wrong issuer, expired) on rejection.
GoogleVerifier = Callable[[str], dict]


def verify_google_id_token(raw_token: str, *, client_id: str) -> dict:
    """Verifies signature (against Google's JWKS), `aud == client_id`,
    issuer, and expiry. Returns the decoded claims dict (includes `email`,
    `email_verified`, `sub`, `exp`, ...) on success; raises ValueError on any
    failure -- callers turn that into a 401, never a 500."""
    return google_id_token.verify_oauth2_token(
        raw_token, google_requests.Request(), client_id
    )


def get_google_verifier(request: Request) -> GoogleVerifier:
    """FastAPI dependency: a `verify(raw_token) -> claims` callable bound to
    this app's configured GOOGLE_CLIENT_ID. Defaults to the real
    verify_google_id_token; overridden in tests (see module docstring)."""
    settings = request.app.state.settings

    def verify(raw_token: str) -> dict:
        return verify_google_id_token(raw_token, client_id=settings.google_client_id)

    return verify
