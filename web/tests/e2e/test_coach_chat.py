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
    """
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
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
    """Drives the real Settings UI (not localStorage injection) so the
    save path itself is exercised."""
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('#settings-base-url')
    page.fill('#settings-base-url', base_url)
    page.fill('#settings-token', token)
    page.click('[data-a="settings:save"]')


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
    assert 'Backend connection' in page.content()
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


def test_settings_save_and_mocked_health_check(page):
    page.route('**/health', _cors_route(200, 'application/json', '{"status": "ok"}'))

    _configure_backend(page)
    page.wait_for_selector('#settings-base-url')
    assert page.input_value('#settings-base-url') == BASE_URL

    page.click('[data-a="settings:test"]')
    page.wait_for_selector('.conn-result.ok')
    assert 'Connected' in page.locator('.conn-result').inner_text()


def test_settings_test_connection_reports_failure(page):
    page.route('**/health', _cors_route(401, 'application/json', '{"error": "invalid token"}'))

    _configure_backend(page)
    page.click('[data-a="settings:test"]')
    page.wait_for_selector('.conn-result.fail')


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


def test_coach_chat_error_event_shows_error_state(page):
    page.route('**/api/chat', _cors_route(401, 'application/json', '{"error": "invalid token"}'))

    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    page.fill('#chat-input', 'hello')
    page.click('[data-a="chat:send"]')

    page.wait_for_selector('.chat-bubble.is-error')
    assert 'token' in page.content().lower()


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
