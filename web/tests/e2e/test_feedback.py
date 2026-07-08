"""e2e coverage for the Feedback tab (durable feedback log).

Same mocked-backend conventions as test_log_checkin.py -- no real backend is
ever contacted, every network call is intercepted via Playwright routes with
CORS headers attached.
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
    """Seeds a signed-in identity but deliberately NOT a configured backend --
    see test_log_checkin.py's `page` fixture docstring; same reasoning
    applies here (the "unconfigured" test below needs that empty state)."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
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


def test_feedback_tab_shows_backend_needed_notice_when_unconfigured(page):
    page.click('[data-a="tab:feedback"]')
    page.wait_for_selector('.chat-empty')
    assert 'backend URL and token' in page.content()


def test_feedback_tab_renders_form_fields_when_configured(page):
    page.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
    _configure_backend(page)
    page.click('[data-a="tab:feedback"]')
    page.wait_for_selector('[data-form="feedback"][data-field="type"]')
    assert page.locator('[data-form="feedback"][data-field="body"]').count() == 1


def test_feedback_submit_success_shows_saved_and_resets_form(page):
    page.route(
        '**/api/feedback*',
        lambda route: (
            _cors_route(200, 'application/json', '{"id": "f1", "type": "feature_request", "body": "a pace calculator"}')(route)
            if route.request.method == 'POST'
            else _cors_route(200, 'application/json', '[]')(route)
        ),
    )

    _configure_backend(page)
    page.click('[data-a="tab:feedback"]')
    page.wait_for_selector('[data-form="feedback"][data-field="body"]')
    page.fill('[data-form="feedback"][data-field="body"]', 'a pace calculator')
    page.click('[data-a="feedback:submit"]')

    page.wait_for_selector('.conn-result.ok')
    assert 'Saved' in page.locator('.conn-result').inner_text()
    assert page.input_value('[data-form="feedback"][data-field="body"]') == ''


def test_feedback_submit_failure_shows_error_message(page):
    page.route(
        '**/api/feedback*',
        lambda route: (
            _cors_route(422, 'application/json', '{"error": "research_question is coach-only"}')(route)
            if route.request.method == 'POST'
            else _cors_route(200, 'application/json', '[]')(route)
        ),
    )

    _configure_backend(page)
    page.click('[data-a="tab:feedback"]')
    page.wait_for_selector('[data-form="feedback"][data-field="body"]')
    page.fill('[data-form="feedback"][data-field="body"]', 'a bug report')
    page.click('[data-a="feedback:submit"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'coach-only' in page.locator('.conn-result').inner_text()


def test_feedback_tab_lists_logged_entries_including_coach_research_questions(page):
    entries = (
        '[{"id": "f1", "type": "research_question", "source": "coach", '
        '"body": "is taper research swim-specific?", "status": "open", '
        '"created_at": "2026-07-07T12:00:00Z"},'
        '{"id": "f2", "type": "feature_request", "source": "athlete", '
        '"body": "add a pace calculator", "status": "open", '
        '"created_at": "2026-07-06T12:00:00Z"}]'
    )
    page.route(
        '**/api/feedback*',
        lambda route: _cors_route(200, 'application/json', entries)(route),
    )

    _configure_backend(page)
    page.click('[data-a="tab:feedback"]')
    page.wait_for_selector('.feedback-entry')
    content = page.content()
    assert 'is taper research swim-specific?' in content
    assert 'add a pace calculator' in content
    assert 'coach-logged' in content


def test_tab_bar_includes_feedback(page):
    page.wait_for_selector('.tabbar')
    assert page.locator('[data-a="tab:feedback"]').count() == 1
