"""e2e coverage for coach mode Phase 1's Settings-tab "Coach access" section
-- the ATHLETE side of coach mode: granting/revoking who may coach you (see
backend/app/routes/grants.py). Distinct from test_coach_roster.py, which
covers the COACH side (the "My Athletes" tab).

Same mocked-backend / CORS-preflight conventions as test_feedback.py /
test_workout_sync.py: cross-origin GETs/POSTs/PATCHes carrying an
Authorization header, so WebKit enforces a strict CORS preflight even
against a mocked/fulfilled response.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [],
})
PLAN_LOAD_STUB = json.dumps({'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': []})

EXISTING_GRANT = {
    'id': 'g1', 'coach_athlete_id': 'abcdef12-3456-7890-abcd-ef1234567890',
    'status': 'active', 'chat_visibility': 'shared_only',
    'granted_at': '2026-08-01T00:00:00Z', 'revoked_at': None,
}
GRANTS_STUB = json.dumps([EXISTING_GRANT])

NEW_GRANT = {
    'id': 'g2', 'coach_athlete_id': '11112222-3333-4444-5555-666677778888',
    'status': 'active', 'chat_visibility': 'shared_only',
    'granted_at': '2026-08-24T00:00:00Z', 'revoked_at': None,
}

REVOKED_GRANT = {**EXISTING_GRANT, 'status': 'revoked', 'revoked_at': '2026-08-24T00:00:00Z'}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _route_grants(ctx_or_page, handler):
    """Registers `handler` for both grant URL shapes -- Playwright's glob
    `*` never crosses a `/` (see test_workout_sync.py's `page` fixture doc
    comment for the same rule applied elsewhere), so `/api/grants[?...]`
    (list GET / create POST) and `/api/grants/{id}[?...]` (PATCH revoke)
    need two distinct patterns to both be covered by one handler."""
    ctx_or_page.route('**/api/grants*', handler)
    ctx_or_page.route('**/api/grants/*', handler)


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """A signed-in, configured, ordinary athlete identity (no `coachFor`
    needed -- this file is about the athlete GRANTING access, not
    receiving it). `/api/athlete` and `/api/plan` are stubbed with harmless
    responses since main.js's boot sequence + Settings-tab visit fire both
    regardless of what this file cares about (same reasoning as
    test_feedback.py's own `page` fixture doc comment). `/api/grants`
    defaults to a single existing (active) grant; individual tests override
    this route where they need different behavior."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        seed_settings(ctx)
        ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
        # GET /api/plan/load fires unconditionally at boot alongside GET
        # /api/plan (main.js's loadPlanLoad, feeding views.js's
        # renderLoadChart) -- unmocked, it fails on CORS the same way.
        ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
        ctx.route(
            '**/api/athlete*',
            _cors_route(200, 'application/json', '{"slug": "renee", "name": "Renee"}'),
        )
        _route_grants(ctx, _grants_handler())
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


def _grants_handler(*, list_body=GRANTS_STUB, post_body=None, patch_body=None, calls=None):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        if route.request.method == 'POST':
            if calls is not None:
                calls.append(json.loads(route.request.post_data))
            body = post_body if post_body is not None else json.dumps(NEW_GRANT)
            route.fulfill(status=200, content_type='application/json', body=body, headers=CORS_HEADERS)
            return
        if route.request.method == 'PATCH':
            if calls is not None:
                calls.append(json.loads(route.request.post_data))
            body = patch_body if patch_body is not None else json.dumps(REVOKED_GRANT)
            route.fulfill(status=200, content_type='application/json', body=body, headers=CORS_HEADERS)
            return
        route.fulfill(status=200, content_type='application/json', body=list_body, headers=CORS_HEADERS)
    return handler


def _open_settings(page):
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')
    page.wait_for_selector('text=Coach access')


def test_coach_access_panel_shows_existing_grants(page):
    _open_settings(page)
    content = page.content()
    assert 'active' in content
    assert page.locator('[data-a="grants:revoke"]').count() == 1


def test_coach_access_panel_shows_empty_state_with_no_grants(page):
    _route_grants(page.context, _grants_handler(list_body='[]'))
    _open_settings(page)
    assert "haven't granted anyone coach access yet" in page.content()
    assert page.locator('[data-a="grants:revoke"]').count() == 0


def test_submitting_the_grant_form_posts_and_the_new_grant_appears(page):
    calls = []
    _route_grants(page.context, _grants_handler(calls=calls))
    _open_settings(page)

    page.fill('[data-form="grants"][data-field="coachSlug"]', 'tim')
    page.click('[data-a="grants:submit"]')

    page.wait_for_function(
        "() => document.querySelectorAll('[data-a=\"grants:revoke\"]').length === 2",
    )
    assert len(calls) == 1
    assert calls[0] == {'coach_slug': 'tim'}
    # The form clears after a successful submit.
    assert page.input_value('[data-form="grants"][data-field="coachSlug"]') == ''


def test_grant_submit_failure_shows_an_error_message(page):
    # POST needs to actually fail (non-2xx) -- _grants_handler's POST branch
    # always fulfills 200, so this test wires its own status-aware handler.
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        if route.request.method == 'POST':
            route.fulfill(
                status=404, content_type='application/json',
                body='{"error": "no such coach: nobody"}', headers=CORS_HEADERS,
            )
            return
        route.fulfill(status=200, content_type='application/json', body=GRANTS_STUB, headers=CORS_HEADERS)
    _route_grants(page.context, handler)

    _open_settings(page)
    page.fill('[data-form="grants"][data-field="coachSlug"]', 'nobody')
    page.click('[data-a="grants:submit"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'no such coach: nobody' in page.locator('.conn-result.fail').inner_text()


def test_revoking_a_grant_patches_and_the_row_updates_to_revoked(page):
    calls = []
    _route_grants(page.context, _grants_handler(calls=calls))
    _open_settings(page)
    page.wait_for_selector('[data-a="grants:revoke"]')

    page.click('[data-a="grants:revoke"]')

    page.wait_for_function(
        "() => document.querySelectorAll('[data-a=\"grants:revoke\"]').length === 0",
    )
    assert len(calls) == 1
    assert 'revoked' in page.content()


def test_settings_tab_does_not_overflow_horizontally(page):
    _open_settings(page)
    overflow = page.evaluate(
        'document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1, f'horizontal overflow of {overflow}px'
