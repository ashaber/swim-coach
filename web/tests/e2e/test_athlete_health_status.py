"""e2e coverage for the athlete's OWN self-service health-status logging
(web/coach-health-nav-and-athlete-self-log) -- the Dashboard tab's new
"Log health condition" action, a THIRD action alongside "Sync from watch"
and "Log manually / upload a file". POSTs/GETs the new self-scoped
`/api/health-status` route (backend/app/routes/health_status.py), never the
coach-scoped `/api/coach/athletes/<slug>/health-status` one this file's
sibling, test_health_status.py, already covers.

Before this build, the ONLY ways to log a HealthStatus were a coach typing
directly into the roster's form or the AI chat tool -- there was no
athlete-facing UI path at all; this fixes that reported gap.

Same mocked-backend / CORS-preflight conventions as test_coach_roster.py /
test_health_status.py: cross-origin GETs/POSTs carrying an Authorization
header, so WebKit enforces a strict CORS preflight even against a mocked
response.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'
PLAN_LOAD_STUB = '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'
EMPTY_STUB = '[]'

EXISTING_ENTRY = {
    'id': 'h0',
    'description': 'Old calf tightness, since resolved',
    'restriction': 'light_only',
    'source': 'self_reported',
    'reported_by': 'athlete',
    'reported_at': '2026-08-01T09:00:00Z',
    'resolved': True,
    'resolved_at': '2026-08-10T09:00:00Z',
    'expected_review_date': None,
}
CREATED_ENTRY = {
    'id': 'h1',
    'description': 'Sharp shoulder pain on catch-up drills',
    'restriction': 'light_only',
    'source': 'self_reported',
    'reported_by': 'athlete',
    'reported_at': '2026-09-01T09:00:00Z',
    'resolved': False,
    'resolved_at': None,
    'expected_review_date': None,
}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _health_status_handler(get_body, *, post_response=None, calls=None):
    """Serves GET with `get_body`; POST (when given) records its JSON body
    into `calls` and responds with `post_response` -- mirrors
    test_health_status.py's identically-shaped helper for the coach-scoped
    route."""
    def handler(route):
        method = route.request.method
        if method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        if method == 'POST' and post_response is not None:
            if calls is not None:
                calls.append(json.loads(route.request.post_data))
            route.fulfill(
                status=200, content_type='application/json',
                body=json.dumps(post_response), headers=CORS_HEADERS,
            )
            return
        route.fulfill(status=200, content_type='application/json', body=get_body, headers=CORS_HEADERS)
    return handler


def _make_ctx(pw, cfg, *, health_status_route=None):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx)
    seed_settings(ctx)
    ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
    ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
    ctx.route('**/api/workouts*', _cors_route(200, 'application/json', EMPTY_STUB))
    ctx.route(
        '**/api/health-status*',
        health_status_route or _cors_route(200, 'application/json', EMPTY_STUB),
    )
    return browser, ctx


def _open_dashboard(page):
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('text=Nothing logged or missed yet.')


def _open_dashboard_and_expand_health_form(page):
    _open_dashboard(page)
    page.click('[data-a="health-status:toggle"]')
    page.wait_for_selector('[data-form="health-status"][data-field="description"]')


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, request.param)
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


def test_log_health_condition_action_is_collapsed_by_default(page):
    _open_dashboard(page)
    assert page.locator('text=Log health condition').count() == 1
    assert page.locator('[data-form="health-status"][data-field="description"]').count() == 0


def test_log_health_condition_appears_after_sync_and_manual_entry(page):
    _open_dashboard(page)
    sync_box = page.locator('[data-a="sync:start"]').bounding_box()
    manual_toggle = page.locator('[data-a="log:toggle-manual"]').bounding_box()
    health_toggle = page.locator('[data-a="health-status:toggle"]').bounding_box()
    assert sync_box['y'] < manual_toggle['y'] < health_toggle['y']


def test_expanding_the_form_shows_fields_and_existing_history(page):
    page.route(
        '**/api/health-status*',
        _cors_route(200, 'application/json', json.dumps([EXISTING_ENTRY])),
    )
    _open_dashboard_and_expand_health_form(page)
    page.wait_for_selector('text=Old calf tightness, since resolved')

    content = page.content()
    assert 'Your recent entries' in content
    assert 'data-field="restriction"' in content
    assert 'data-field="source"' in content
    assert 'data-a="health-status:submit"' in content


def test_validation_error_shown_when_description_is_empty(page):
    _open_dashboard_and_expand_health_form(page)
    page.click('[data-a="health-status:submit"]')
    page.wait_for_selector('text=Add a description first.')


@pytest.mark.parametrize('cfg', BROWSERS)
def test_athlete_can_submit_a_health_status_end_to_end(cfg, base_url):
    calls = []
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(
            pw, cfg,
            health_status_route=_health_status_handler(EMPTY_STUB, post_response=CREATED_ENTRY, calls=calls),
        )
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            _open_dashboard_and_expand_health_form(pg)

            pg.fill(
                '[data-form="health-status"][data-field="description"]',
                'Sharp shoulder pain on catch-up drills',
            )
            pg.select_option('[data-form="health-status"][data-field="restriction"]', 'light_only')
            pg.select_option('[data-form="health-status"][data-field="source"]', 'self_reported')
            pg.click('[data-a="health-status:submit"]')

            pg.wait_for_selector('text=Sharp shoulder pain on catch-up drills')
            # Wait for the actual text this test asserts on next, not just a
            # proxy for "the submit succeeded" -- both render from the same
            # synchronous call in practice, but a CI-only, non-locally-
            # reproducible flake surfaced here waiting only on the entry's
            # own description text before snapshotting page.content() (same
            # class of fix as web/tests/e2e/test_feedback.py's own unread-
            # badge race: wait for the real assertion target directly,
            # rather than an element that merely tends to appear alongside
            # it in the common case).
            pg.wait_for_selector('text=Your recent entries')

            assert len(calls) == 1
            assert calls[0]['description'] == 'Sharp shoulder pain on catch-up drills'
            assert calls[0]['restriction'] == 'light_only'
            assert calls[0]['source'] == 'self_reported'

            content = pg.content()
            assert 'Your recent entries' in content
        finally:
            ctx.close()
            browser.close()


def test_never_renders_the_coach_rosters_own_health_status_markup(page):
    _open_dashboard_and_expand_health_form(page)
    content = page.content()
    assert 'data-form="roster-health-status"' not in content
    assert 'data-a="roster:health-status-submit"' not in content
