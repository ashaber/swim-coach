"""e2e coverage for the Log tab's primary "Sync from watch" action (Phase 3).

Same mocked-backend conventions as test_workout_upload.py: no real backend is
ever contacted, every network call is intercepted via Playwright routes with
CORS headers attached. `POST /api/workouts/sync` is the new endpoint under
test here -- see backend/app/routes/workouts.py's sync_workouts route and
app/sync.py's sync_on_demand, the same on-demand-sync code path the coach
chat's sync_workouts tool uses server-side (tests/api/test_workouts_sync_route.py
covers that route directly; this file covers the PWA's button/state wiring).
"""

from __future__ import annotations

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


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Same shape as test_workout_upload.py's `page` fixture: signed in but
    deliberately not pre-configured with a backend, /api/athlete stubbed for
    the Settings tab's profile section, and a default empty GET /api/workouts
    for the Log tab's history section (opening the tab always fires that
    fetch -- see main.js's loadHistory). Registered at the *context* level so
    a test's own page.route('**/api/workouts*', ...) handler still takes
    precedence; the glob's trailing '*' never crosses a '/', so this default
    does NOT match /api/workouts/sync -- each test's own sync mock is
    unaffected (same reasoning as that file's docstring re: /ingest)."""
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
        ctx.route(
            '**/api/workouts*',
            _cors_route(200, 'application/json', '[]'),
        )
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
    """The '#settings-token' paste field is gone -- session tokens now come
    only from a real Google sign-in exchange (see identity.js's signIn /
    api.js's exchangeGoogleToken), which these tests don't drive (no real
    Google script). Seeds the session token directly into localStorage the
    way a real exchange would leave it (`version` stamped to match
    settings.js's SETTINGS_SCHEMA_VERSION, or loadSettings() would treat it
    as a stale pre-cutover value and drop it), then reloads and drives the
    real Settings UI for the base URL + Save button, same as before."""
    page.evaluate(
        "(t) => window.localStorage.setItem("
        "'swimcoach_settings', JSON.stringify({baseUrl: '', token: t, version: 2}))",
        token,
    )
    page.reload()
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('#settings-base-url')
    page.fill('#settings-base-url', base_url)
    page.click('[data-a="settings:save"]')


def _open_log_tab(page):
    """Opens the Log tab and waits for the history section's fetch to
    settle (an empty list in every test here) before interacting with the
    sync button -- same settle-before-interact discipline as
    test_workout_upload.py's own _open_log_tab."""
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('text=No workouts logged yet.')


def test_sync_button_happy_path_shows_result_and_refreshes_history(page):
    sync_calls = []

    def sync_handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        sync_calls.append(route.request.url)
        route.fulfill(
            status=200, content_type='application/json',
            body=json.dumps({'listed': 1, 'new': 1, 'saved': 1, 'failed': 0}),
            headers=CORS_HEADERS,
        )

    page.route('**/api/workouts/sync*', sync_handler)

    # After a successful sync (saved > 0), main.js refetches history -- serve
    # an updated list on the *next* GET so the refresh is observable.
    history_state = {'synced': False}

    def workouts_handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        body = json.dumps([{
            'id': 'w-new', 'date': '2026-07-12', 'sport': 'swim_pool', 'source': 'fit',
            'distance_m': 3000, 'duration_min': 55, 'avg_pace_s_per_100m': None, 'rpe': None,
            'notes': None, 'avg_hr': None, 'max_hr': None, 'analytics': None,
        }]) if history_state['synced'] else '[]'
        route.fulfill(status=200, content_type='application/json', body=body, headers=CORS_HEADERS)

    page.route('**/api/workouts*', workouts_handler)

    _configure_backend(page)
    _open_log_tab(page)

    history_state['synced'] = True  # the next GET /api/workouts returns the synced workout
    page.click('[data-a="sync:start"]')

    page.wait_for_selector('.conn-result.ok')
    assert '1 new workout synced' in page.content()
    page.wait_for_selector('.hist-row')
    assert 'Pool swim' in page.content()
    assert len(sync_calls) == 1
    assert 'athlete=renee' in sync_calls[0]


def test_sync_button_nothing_new_shows_up_to_date(page):
    page.route(
        '**/api/workouts/sync*',
        _cors_route(200, 'application/json', json.dumps({'listed': 0, 'new': 0, 'saved': 0, 'failed': 0})),
    )

    _configure_backend(page)
    _open_log_tab(page)
    page.click('[data-a="sync:start"]')

    page.wait_for_selector('.conn-result.ok')
    assert 'Everything up to date' in page.content()


def test_sync_button_not_configured_shows_error_verbatim(page):
    page.route(
        '**/api/workouts/sync*',
        _cors_route(409, 'application/json', '{"error": "sync not configured for this athlete"}'),
    )

    _configure_backend(page)
    _open_log_tab(page)
    page.click('[data-a="sync:start"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'sync not configured for this athlete' in page.content()


def test_sync_button_disabled_offline_with_notice(page):
    _configure_backend(page)
    _open_log_tab(page)

    ctx = page.context
    ctx.set_offline(True)
    try:
        page.wait_for_function('() => !navigator.onLine')
        page.wait_for_selector('.chat-banner')
        assert 'offline' in page.content().lower()
        assert page.locator('[data-a="sync:start"]').is_disabled()
    finally:
        ctx.set_offline(False)
