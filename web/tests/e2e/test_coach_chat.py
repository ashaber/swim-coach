"""e2e coverage for the Phase-2 tab bar, Coach Chat tab, and Settings tab.

Runs on the same `page` fixture as test_app.py (chromium 412x915 / webkit
390x844, against the real built dist/), but the chat backend does not exist
yet -- every network call to /api/chat or /health is mocked via Playwright
route interception. No real backend is ever contacted.

The mocked backend URL is a different origin than the app itself, exactly
like a real deployment (PWA on GitHub Pages, backend on Cloud Run) -- the
app's fetch() calls carry a custom Authorization header, which makes the
browser send a CORS preflight (OPTIONS) before the real request. Both the
preflight and the real response need CORS headers or the browser's fetch()
throws a network error before our code ever sees the mocked body (this
bit engines differently: Chromium's route interception is lenient, WebKit
enforces CORS strictly even against a fulfilled/mocked response) -- see
`_cors_route`.
"""

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity

BASE_URL = 'https://coach-api.test'
TOKEN = 'test-token-123'


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Overrides conftest's `page` fixture for this file only: identical
    browsers/viewports, but with `service_workers='block'`.

    Once the app's service worker (installed for the offline Plan tab)
    activates, it intercepts every fetch -- including cross-origin ones --
    before Playwright's `page.route()` ever sees them, at least in WebKit
    (Chromium's CDP-based interception isn't affected, but WebKit's is).
    Since these tests rely on route interception to mock the backend, the
    service worker is disabled here; it isn't needed to exercise the tab
    bar / chat / settings UI.

    Seeds a signed-in identity (so tests land past the Phase 2.5 sign-in
    gate) but deliberately NOT a configured backend -- several tests below
    exercise the "not configured yet" empty state and drive Settings
    themselves via `_configure_backend`.

    Also gives every test in this file a default mocked `GET /api/athlete`
    response: the Settings tab's profile-edit section (Phase 2.5) fetches it
    the moment the backend becomes configured (see main.js's
    maybeLoadProfile), and every test here that calls `_configure_backend`
    lands back on the Settings tab -- without this, that fetch would hit the
    real (mocked-origin, unmocked-path) backend and fail on CORS, which
    surfaces as exactly the kind of uncaught error this fixture's teardown
    asserts against. Tests that care about the profile section's own
    behavior live in test_profile_edit.py instead.
    """
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        ctx.route(
            '**/api/athlete*',
            _cors_route(200, 'application/json', '{"slug": "renee", "name": "Renee"}'),
        )
        # Becoming "configured" (see _configure_backend) makes main.js's
        # boot sequence eagerly fire GET /api/plan (loadPlan, unconditional
        # at boot regardless of active tab) -- unmocked, that fetch fails
        # against this file's fake backend origin and WebKit surfaces it as
        # an uncaught pageerror that trips this fixture's teardown
        # assertion. This file doesn't care about the plan's content.
        ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
        pg = ctx.new_page()
        js_errors = []
        pg.on('pageerror', lambda e: js_errors.append(str(e)))
        pg.goto(base_url)
        try:
            yield pg
            real_errors = [e for e in js_errors
                           if 'sw.js load failed' not in e
                           and 'Importing a module script failed' not in e]
            assert not real_errors, f'Uncaught JS errors: {real_errors}'
        finally:
            ctx.close()
            browser.close()

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'


def _cors_route(status, content_type, body):
    """Builds a Playwright route handler that answers the CORS preflight
    (OPTIONS) with a bare 204 + CORS headers, and the real request with
    the given canned response (also CORS-headered)."""
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _configure_backend(page, base_url=BASE_URL, token=TOKEN):
    """The backend-URL/test-connection panel is gone from Settings (paste-
    token-era leftover -- baseUrl now always defaults to prod internally,
    see settings.js's DEFAULT_BASE_URL, with no UI to edit it). Seeds both
    baseUrl and the session token directly into localStorage the way
    settings.js's own storage schema expects (`version` stamped to match
    SETTINGS_SCHEMA_VERSION, or loadSettings() would treat it as a stale
    pre-cutover value and drop the token), then reloads so main.js's boot
    picks it up -- the same pattern conftest.py's own seed_settings
    init-script helper uses, just applied mid-test via page.evaluate instead
    of before the first page load."""
    page.evaluate(
        "(cfg) => window.localStorage.setItem("
        "'swimcoach_settings', JSON.stringify({baseUrl: cfg.baseUrl, token: cfg.token, version: 2}))",
        {'baseUrl': base_url, 'token': token},
    )
    page.reload()
    # Always ends on the Settings tab -- same invariant the old
    # base-url-fill-and-save flow had (it necessarily drove the
    # Settings UI to save), which several tests below rely on (e.g.
    # the profile-edit section only renders on this tab, and
    # visiting it is what triggers main.js's maybeLoadProfile()).
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')


def test_tab_bar_switches_between_plan_coach_settings(page):
    page.wait_for_selector('.tabbar')
    assert page.locator('.tab-btn.active .tab-label').inner_text().strip().lower() == 'plan'

    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('.chat-wrap')
    assert 'Ask your coach' in page.content()
    assert page.locator('.tab-btn.active').get_attribute('data-a') == 'tab:coach'

    # The Plan tab now needs a configured backend (see main.js's loadPlan) --
    # mock GET /api/plan before driving Settings so the tab actually renders
    # rather than showing the "needs setup" notice.
    page.route(
        '**/api/plan*',
        _cors_route(
            200, 'application/json',
            '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}',
        ),
    )
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')
    assert 'Signed in as' in page.content()
    _configure_backend(page)

    page.click('[data-a="tab:plan"]')
    page.wait_for_selector('.mast h1')
    assert page.locator('.tab-btn.active').get_attribute('data-a') == 'tab:plan'


def test_active_tab_persists_across_reload(page):
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('.chat-wrap')
    page.reload()
    page.wait_for_selector('.tabbar')
    assert page.locator('.tab-btn.active').get_attribute('data-a') == 'tab:coach'


def test_coach_tab_empty_state_links_to_settings_when_unconfigured(page):
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('.chat-empty')
    assert 'backend URL and token' in page.content()
    page.click('.chat-empty [data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')


def test_coach_chat_streams_mocked_reply_with_tool_chip(page):
    sse_body = (
        'data: {"type":"tool_use","name":"get_plan_summary","input":{}}\n\n'
        'data: {"type":"text","text":"This week "}\n\n'
        'data: {"type":"text","text":"is an easy week before the long swim."}\n\n'
        'data: {"type":"done","stop_reason":"end_turn"}\n\n'
    )
    page.route('**/api/chat', _cors_route(200, 'text/event-stream', sse_body))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')

    page.fill('#chat-input', 'What does this week look like?')
    page.click('[data-a="chat:send"]')

    # user bubble renders immediately
    page.wait_for_selector('.chat-row.me .chat-bubble')
    assert 'What does this week look like?' in page.content()

    # tool-use status chip appears
    page.wait_for_selector('.chat-chip')
    assert 'consulting the plan' in page.content().lower()

    # streamed reply renders in full once the turn finalizes
    page.wait_for_function(
        "() => { const b = document.querySelectorAll('.chat-row.coach .chat-bubble'); "
        "return b.length > 0 && b[b.length-1].textContent.includes('easy week before the long swim'); }",
        timeout=5000,
    )

    # composer re-enables after 'done'
    send_btn = page.locator('[data-a="chat:send"]')
    assert send_btn.inner_text().strip() == 'Send'
    assert not send_btn.is_disabled()


def test_coach_chat_refusal_renders_safety_message(page):
    page.route('**/api/chat', _cors_route(200, 'text/event-stream', 'data: {"type": "refusal"}\n\n'))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    page.fill('#chat-input', 'My shoulder has sharp pain, should I swim through it?')
    page.click('[data-a="chat:send"]')

    page.wait_for_selector('.chat-bubble.is-refusal')
    assert 'coach' in page.content().lower() or 'clinician' in page.content().lower()


def test_coach_chat_non_401_error_event_shows_error_state(page):
    page.route('**/api/chat', _cors_route(422, 'application/json', '{"error": "malformed request"}'))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    page.fill('#chat-input', 'hello')
    page.click('[data-a="chat:send"]')

    page.wait_for_selector('.chat-bubble.is-error')
    assert 'malformed request' in page.content().lower()


def test_coach_chat_401_signs_out_and_shows_reauth_gate(page):
    # A 401 means the session token is no longer valid (expired, or revoked
    # elsewhere) -- main.js treats this as "session expired": clears
    # identity + token and routes back to the sign-in gate, rather than
    # showing an in-chat error bubble (there is no refresh endpoint by
    # design, see identity.js). Blocks the real GSI script network -- once
    # signed out, the Settings tab tries to mount the real sign-in button
    # (see main.js's mountGoogleSignIn), and this test doesn't need it to
    # actually load.
    page.context.route('https://accounts.google.com/**', lambda route: route.abort())
    page.route('**/api/chat', _cors_route(401, 'application/json', '{"error": "invalid token"}'))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    page.fill('#chat-input', 'hello')
    page.click('[data-a="chat:send"]')

    page.wait_for_selector('.settings-wrap')
    assert page.locator('.tab-btn.active').get_attribute('data-a') == 'tab:settings'
    assert 'expired' in page.content().lower()


def test_coach_chat_new_conversation_clears_history(page):
    sse_body = 'data: {"type":"text","text":"hi there"}\n\ndata: {"type":"done","stop_reason":"end_turn"}\n\n'
    page.route('**/api/chat', _cors_route(200, 'text/event-stream', sse_body))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    page.fill('#chat-input', 'hello coach')
    page.click('[data-a="chat:send"]')
    page.wait_for_selector('.chat-row.coach .chat-bubble')

    page.click('[data-a="chat:clear"]')
    page.wait_for_selector('.chat-empty')
    assert 'hello coach' not in page.content()


def test_coach_tab_shows_offline_state(page):
    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')

    ctx = page.context
    ctx.set_offline(True)
    try:
        # re-render is triggered by the browser's offline event
        page.wait_for_selector('.chat-banner', timeout=5000)
        assert 'offline' in page.content().lower()
        assert page.locator('[data-a="chat:send"]').is_disabled()
    finally:
        ctx.set_offline(False)
