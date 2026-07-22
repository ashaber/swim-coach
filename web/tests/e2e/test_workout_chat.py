"""e2e coverage for the workout detail view's embedded scoped chat (Phase C
slice 1: "Ask your coach about this workout").

Same mocked-backend conventions as test_coach_chat.py (SSE body mocked via
Playwright routes with CORS headers -- see that file's docstring for the
CORS/preflight and service-worker-blocking rationale) on the same page
fixture shape as test_workout_detail.py (signed in, not pre-configured,
/api/athlete stubbed). No real backend is ever contacted.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity

BASE_URL = 'https://coach-api.test'
TOKEN = 'test-token-123'

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'

RICH_FIT_WORKOUT = {
    'id': 'w-rich', 'date': '2026-06-01', 'sport': 'swim_ow', 'source': 'fit',
    'distance_m': 5000, 'duration_min': 95, 'avg_pace_s_per_100m': 114, 'rpe': 7,
    'notes': 'Choppy back half, felt strong.',
    'avg_hr': 132, 'max_hr': 158,
    'analytics': {
        'cardiac_drift_pct': 6.4, 'split_label': 'positive',
        'first_half_pace_s_per_100m': 108, 'second_half_pace_s_per_100m': 120,
        'elapsed_min': 98, 'moving_min': 95, 'pause_total_min': 3, 'pause_count': 2,
        'swolf_first_quarter': 38.2, 'swolf_last_quarter': 44.9, 'swolf_degradation_pct': 17.5,
    },
    'laps': [],
    'lengths': [],
    'pauses': [],
}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Same shape as test_workout_detail.py's `page` fixture: signed in but
    deliberately not pre-configured with a backend, and /api/athlete stubbed
    since Settings' profile-edit section fetches it as soon as
    `_configure_backend` lands back on that tab."""
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
        js_errors: list[str] = []
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


def _open_workout_detail(page):
    """Configures the backend, opens the Log tab, waits for the history
    fetch to settle (the row is the settled marker), then opens the rich
    workout's detail view and waits for its own settled marker (the back
    button plus the chat section's input)."""
    page.route('**/api/workouts*', _cors_route(200, 'application/json', json.dumps([RICH_FIT_WORKOUT])))
    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('.hist-row')
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')
    page.wait_for_selector('#workout-chat-input')


def test_detail_shows_scoped_chat_section_with_about_label(page):
    _open_workout_detail(page)
    content = page.content()
    assert 'Ask your coach about this workout' in content
    assert 'About: Jun 1 Open water swim' in content


def test_send_message_renders_mocked_scoped_reply(page):
    sse_body = (
        'data: {"type":"text","text":"That positive split came from "}\n\n'
        'data: {"type":"text","text":"the choppy back half -- solid effort."}\n\n'
        'data: {"type":"done","stop_reason":"end_turn"}\n\n'
    )
    captured = {}

    def chat_handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        captured['body'] = json.loads(route.request.post_data)
        route.fulfill(status=200, content_type='text/event-stream', body=sse_body, headers=CORS_HEADERS)

    page.route('**/api/chat', chat_handler)

    _open_workout_detail(page)
    page.fill('#workout-chat-input', 'why was the second half slower?')
    page.click('[data-a="workout-chat:send"]')

    # User bubble renders immediately; reply streams in and finalizes.
    page.wait_for_selector('#workout-chat .chat-row.me .chat-bubble')
    page.wait_for_function(
        "() => { const b = document.querySelectorAll('#workout-chat .chat-row.coach .chat-bubble'); "
        "return b.length > 0 && b[b.length-1].textContent.includes('solid effort'); }",
        timeout=5000,
    )

    # The request was scoped to this exact workout.
    assert captured['body']['workout_id'] == 'w-rich'
    assert captured['body']['message'] == 'why was the second half slower?'

    # Composer re-enables after 'done'.
    send_btn = page.locator('[data-a="workout-chat:send"]')
    assert send_btn.inner_text().strip() == 'Send'
    assert not send_btn.is_disabled()


def test_thread_is_ephemeral_cleared_when_detail_closes(page):
    sse_body = (
        'data: {"type":"text","text":"A strong swim."}\n\n'
        'data: {"type":"done","stop_reason":"end_turn"}\n\n'
    )
    page.route('**/api/chat', _cors_route(200, 'text/event-stream', sse_body))

    _open_workout_detail(page)
    page.fill('#workout-chat-input', 'quick thoughts?')
    page.click('[data-a="workout-chat:send"]')
    page.wait_for_selector('#workout-chat .chat-row.coach .chat-bubble')

    # Back to the list, then reopen the same workout -- the thread is gone.
    page.click('[data-a="history:back"]')
    page.wait_for_selector('.hist-row')
    page.click('.hist-row')
    page.wait_for_selector('#workout-chat-input')
    assert 'quick thoughts?' not in page.content()
    assert 'A strong swim.' not in page.content()


def test_back_button_still_returns_to_history_list(page):
    _open_workout_detail(page)
    page.click('[data-a="history:back"]')
    page.wait_for_selector('.hist-row')
    assert page.locator('[data-a="history:back"]').count() == 0
    assert 'Recent workouts' in page.content()


def test_chat_error_response_shows_error_bubble(page):
    page.route('**/api/chat', _cors_route(404, 'application/json', '{"error": "no workout matching id"}'))

    _open_workout_detail(page)
    page.fill('#workout-chat-input', 'hello?')
    page.click('[data-a="workout-chat:send"]')

    page.wait_for_selector('#workout-chat .chat-bubble.is-error')
    assert 'no workout matching id' in page.content()


def test_offline_disables_scoped_chat_input_with_notice(page):
    _open_workout_detail(page)

    ctx = page.context
    ctx.set_offline(True)
    try:
        page.wait_for_function('() => !navigator.onLine')
        page.wait_for_selector('#workout-chat .chat-banner', timeout=5000)
        assert page.locator('#workout-chat-input').is_disabled()
        assert page.locator('[data-a="workout-chat:send"]').is_disabled()
    finally:
        ctx.set_offline(False)
