"""e2e coverage for the Log and Check-in tabs.

Same mocked-backend conventions as test_coach_chat.py (see its `page`
fixture docstring for why the service worker is blocked here): no real
backend is ever contacted, and every network call is intercepted via
Playwright routes with CORS headers attached (the mocked backend is a
different origin, exactly like the real GitHub Pages / Cloud Run split).
"""

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
    """Seeds a signed-in identity (past the Phase 2.5 sign-in gate) but
    deliberately NOT a configured backend -- see test_coach_chat.py's `page`
    fixture docstring; same reasoning applies here (the "unconfigured" tests
    below need that empty state).

    Also mocks a default `GET /api/athlete` response -- see
    test_coach_chat.py's `page` fixture docstring for why (the Settings
    tab's profile-edit section fetches it as soon as `_configure_backend`
    lands back on that tab). test_profile_edit.py covers that section's own
    behavior.

    Likewise mocks a default empty `GET /api/workouts` -- opening the Log
    tab while configured fires that fetch for the history section (see
    main.js's loadHistory), and unmocked it fails against this file's fake
    backend origin, which WebKit reports as an uncaught pageerror that trips
    this fixture's teardown assertion (same fix as test_workout_upload.py's
    fixture). Registered at the *context* level so the submit tests' own
    page.route('**/api/workouts*', ...) handlers still take precedence, and
    the glob's trailing '*' never crosses '/', so ingest-style subpaths are
    unaffected. test_workout_history.py covers the history section's own
    behavior."""
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
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('#settings-base-url')
    page.fill('#settings-base-url', base_url)
    page.fill('#settings-token', token)
    page.click('[data-a="settings:save"]')


def test_log_tab_shows_backend_needed_notice_when_unconfigured(page):
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('.chat-empty')
    assert 'backend URL and token' in page.content()


def test_log_tab_renders_form_fields_when_configured(page):
    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('[data-form="log"][data-field="date"]')
    assert page.locator('[data-form="log"][data-field="sport"]').count() == 1
    assert page.locator('[data-form="log"][data-field="distance_m"]').count() == 1
    assert page.locator('[data-form="log"][data-field="duration_min"]').count() == 1
    assert page.locator('[data-form="log"][data-field="rpe"]').count() == 1


def test_log_submit_success_shows_saved_and_resets_form(page):
    page.route('**/api/workouts*', _cors_route(200, 'application/json', '{"id": "w1", "date": "2026-07-07"}'))

    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('[data-form="log"][data-field="distance_m"]')
    page.fill('[data-form="log"][data-field="distance_m"]', '3000')
    page.fill('[data-form="log"][data-field="duration_min"]', '60')
    page.fill('[data-form="log"][data-field="notes"]', 'felt smooth')
    page.click('[data-a="log:submit"]')

    page.wait_for_selector('.conn-result.ok')
    assert 'Saved' in page.locator('.conn-result').inner_text()
    # Form resets to defaults after a successful save.
    assert page.input_value('[data-form="log"][data-field="distance_m"]') == ''


def test_log_submit_failure_shows_error_message(page):
    page.route('**/api/workouts*', _cors_route(422, 'application/json', '{"error": "invalid sport"}'))

    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('[data-form="log"][data-field="distance_m"]')
    page.fill('[data-form="log"][data-field="distance_m"]', '3000')
    page.fill('[data-form="log"][data-field="duration_min"]', '60')
    page.click('[data-a="log:submit"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'invalid sport' in page.locator('.conn-result').inner_text()


def test_checkin_tab_renders_form_fields_when_configured(page):
    _configure_backend(page)
    page.click('[data-a="tab:checkin"]')
    page.wait_for_selector('[data-form="checkin"][data-field="date"]')
    assert page.locator('[data-form="checkin"][data-field="sleep_quality"]').count() == 1
    assert page.locator('[data-form="checkin"][data-field="sleep_hours"]').count() == 1
    assert page.locator('[data-form="checkin"][data-field="stress"]').count() == 1
    assert page.locator('[data-form="checkin"][data-field="soreness"]').count() == 1
    assert page.locator('[data-form="checkin"][data-field="motivation"]').count() == 1


def test_checkin_submit_success_shows_saved(page):
    page.route('**/api/wellness*', _cors_route(200, 'application/json', '{"id": "we1", "date": "2026-07-07"}'))

    _configure_backend(page)
    page.click('[data-a="tab:checkin"]')
    page.wait_for_selector('[data-form="checkin"][data-field="sleep_hours"]')
    page.fill('[data-form="checkin"][data-field="sleep_hours"]', '7.5')
    page.click('[data-a="checkin:submit"]')

    page.wait_for_selector('.conn-result.ok')
    assert 'Saved' in page.locator('.conn-result').inner_text()


def test_tab_bar_includes_log_and_checkin(page):
    page.wait_for_selector('.tabbar')
    assert page.locator('[data-a="tab:log"]').count() == 1
    assert page.locator('[data-a="tab:checkin"]').count() == 1
