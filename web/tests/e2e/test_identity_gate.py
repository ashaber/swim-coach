"""e2e coverage for the Google-Sign-In identity gate (Phase 2.5) and the
session-token login switch on top of it (see api.js's exchangeGoogleToken /
identity.js's signIn).

Deliberately avoids exercising the real Google Identity Services script --
that would need either real network access to accounts.google.com or a
heavyweight mock of `window.google`, and the priority for this feature is
the vitest unit coverage of the pure identity logic (see
tests/unit/identity.test.js for localStorage persistence, and
tests/unit/api.test.js's `exchangeGoogleToken` describe block for the
POST /api/auth/google exchange itself, mocked at the `fetch` level). This
file only covers what's cheap and valuable to check with real browsers:

1. Signed out, the app shows a sign-in gate rather than defaulting to any
   particular athlete's data (the bug this feature replaces -- see
   CLAUDE.md: the app used to hardcode athlete 'renee').
2. Once a resolved identity is present -- seeded directly into localStorage,
   the same persistence identity.js itself writes after a real sign-in --
   the app targets that identity's athlete slug on its API calls.
3. A non-allowlisted Google account (POST /api/auth/google -> 403) shows a
   "request access" message and never configures the app -- driven by
   stubbing `window.google.accounts.id` (a minimal fake of the real GSI
   object, just enough to capture the credential callback identity.js
   registers) and mocking the exchange response, since the real Google
   popup can't be automated here.
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
    # one: write {name, athlete, role} to localStorage under
    # 'swimcoach_identity', then reload (restore-on-load, per identity.js's
    # currentIdentity()). No 'email' field -- the backend's exchange response
    # (POST /api/auth/google) never includes one (see api.js's
    # exchangeGoogleToken), so identity.js no longer persists one either.
    page.evaluate(
        "(identity) => window.localStorage.setItem('swimcoach_identity', JSON.stringify(identity))",
        {'name': 'Andrew', 'athlete': 'andrew', 'role': 'coach'},
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
    assert 'Andrew' in content
    assert 'andrew' in content


# --- Unauthorized Google account ("request access") -------------------------
# A minimal fake of window.google.accounts.id -- just enough surface for
# identity.js's signIn() to call .initialize({callback}) and .renderButton()
# without error, and for this test to grab the registered callback and fire
# it manually with a fake credential (standing in for a real Google popup
# completing). Installed via add_init_script so it exists before main.js's
# module-level code runs and identity.js's loadGsiScript() checks for
# `window.google?.accounts?.id` (finding this stub, it resolves immediately
# without ever touching the network for the real GSI script).
_FAKE_GSI_INIT_SCRIPT = """
(() => {
  window.google = {
    accounts: {
      id: {
        initialize: (opts) => { window.__gsiCallback = opts.callback; },
        renderButton: () => {},
        prompt: () => {},
        disableAutoSelect: () => {},
      },
    },
  };
})();
"""


@pytest.fixture(params=BROWSERS)
def fake_gsi_page(request, base_url):
    """A fresh, signed-out context with the fake GSI stub installed and the
    real Google script network blocked (belt-and-suspenders -- the stub
    already makes identity.js skip loading it, see loadGsiScript)."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        ctx.route('https://accounts.google.com/**', lambda route: route.abort())
        ctx.add_init_script(_FAKE_GSI_INIT_SCRIPT)
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            yield pg
        finally:
            ctx.close()
            browser.close()


def test_unauthorized_email_shows_request_access_and_stays_signed_out(fake_gsi_page):
    page = fake_gsi_page
    page.route(
        '**/api/auth/google',
        _cors_route(403, 'application/json', '{"error": "request access"}'),
    )

    page.wait_for_selector('.settings-wrap')
    assert page.locator('.tab-btn.active').get_attribute('data-a') == 'tab:settings'
    page.wait_for_function('() => typeof window.__gsiCallback === "function"')

    # Fires the fake credential callback identity.js registered -- standing
    # in for a real Google popup handing back an ID token.
    page.evaluate("() => window.__gsiCallback({credential: 'fake-id-token'})")

    page.wait_for_selector('.conn-result.fail')
    assert 'not authorized' in page.content().lower()

    # Still on the sign-in gate -- no identity, no configured app.
    assert page.locator('.tab-btn.active').get_attribute('data-a') == 'tab:settings'
    assert 'signed in as' not in page.content().lower()
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector('.chat-empty')
    assert 'sign in' in page.content().lower()
