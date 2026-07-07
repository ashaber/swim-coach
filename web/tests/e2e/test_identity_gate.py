"""e2e coverage for the Google-Sign-In identity gate (Phase 2.5).

Deliberately avoids exercising the real Google Identity Services script --
that would need either real network access to accounts.google.com or a
heavyweight mock of `window.google`, and the priority for this feature is
the vitest unit coverage of the pure identity logic (see
tests/unit/identity.test.js, which covers JWT-payload decoding, email
resolution, and localStorage persistence directly). This file only covers
the two things that are cheap and valuable to check with real browsers:

1. Signed out, the app shows a sign-in gate rather than defaulting to any
   particular athlete's data (the bug this feature replaces -- see
   CLAUDE.md: the app used to hardcode athlete 'renee').
2. Once a resolved identity is present -- seeded directly into localStorage,
   the same persistence identity.js itself writes after a real sign-in --
   the app targets that identity's athlete slug on its API calls.
"""

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, MOCK_SETTINGS, seed_settings

# Same CORS-preflight-aware mocking convention as test_coach_chat.py /
# test_log_checkin.py (see their module docstrings): the mocked backend is a
# different origin than the app itself, so the app's Authorization header
# triggers a real CORS preflight (OPTIONS) that WebKit enforces strictly even
# against a mocked/fulfilled response.
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def signed_out_page(request, base_url):
    """A fresh context with NO identity and NO settings seeded -- and the
    real Google Identity Services script blocked, since these tests never
    need it to actually load (see module docstring)."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        ctx.route('https://accounts.google.com/**', lambda route: route.abort())
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            yield pg
        finally:
            ctx.close()
            browser.close()


def test_signed_out_shows_sign_in_gate_not_an_athlete_default(signed_out_page):
    page = signed_out_page
    # Forced onto Settings (the sign-in gate) rather than defaulting to Plan.
    page.wait_for_selector('.settings-wrap')
    assert page.locator('.tab-btn.active').get_attribute('data-a') == 'tab:settings'
    assert 'sign in' in page.content().lower()

    # Every other tab shows the same "needs sign-in" notice, not a default
    # athlete's data.
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector('.chat-empty')
    assert 'sign in' in page.content().lower()


def test_mocked_identity_targets_its_own_athlete_on_api_calls(signed_out_page):
    page = signed_out_page
    plan_request_urls = []
    plan_body = '{"slug":"andrew","athlete":{"name":"Andrew"},"events":[],"weeks":[],"macro":{"blocks":[]}}'
    cors_handler = _cors_route(200, 'application/json', plan_body)

    def handle_plan(route):
        plan_request_urls.append(route.request.url)
        cors_handler(route)

    page.route('**/api/plan*', handle_plan)

    # Simulate a completed sign-in the same way identity.js itself persists
    # one: write {email, athlete, role} to localStorage under
    # 'swimcoach_identity', then reload (restore-on-load, per identity.js's
    # currentIdentity()).
    page.evaluate(
        "(identity) => window.localStorage.setItem('swimcoach_identity', JSON.stringify(identity))",
        {'email': 'andrewshaber@gmail.com', 'athlete': 'andrew', 'role': 'coach'},
    )
    seed_settings(page.context, MOCK_SETTINGS)
    page.reload()

    page.wait_for_selector('.mast h1')
    assert plan_request_urls, 'expected the app to call GET /api/plan at least once'
    assert any('athlete=andrew' in url for url in plan_request_urls)

    # Settings reflects the resolved identity, not a hardcoded athlete.
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')
    content = page.content()
    assert 'andrewshaber@gmail.com' in content
    assert 'andrew' in content
