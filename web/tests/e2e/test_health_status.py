"""e2e coverage for the coach roster's health-status section
(backend/health-status-record build) -- the durable injury/illness record
built after a real, undetected athlete health incident exposed that this
system had no durable trace of health status anywhere (see
engine/swim_coach/models.HealthStatus's docstring for the full rationale).

Scoped narrowly to this one new section: a coach can see an athlete's
current active status prominently, see the honest "nothing on file" state
when there is none, submit a new status directly, and mark the active one
resolved -- all against a mocked backend. Everything else about the roster
view (workouts, feedback, load chart, training plan) is already covered by
test_coach_roster.py; this file does not re-test it.

Same mocked-backend / CORS-preflight conventions as test_coach_roster.py:
these are cross-origin GETs/POSTs/PATCHes carrying an Authorization header,
so WebKit enforces a strict CORS preflight even against a mocked response.
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

COACH_IDENTITY = {'name': 'Andrew', 'athlete': 'andrew', 'role': 'coach', 'coachFor': ['renee']}

ATHLETES_STUB = json.dumps([{'slug': 'renee', 'name': 'Renee'}])
EMPTY_STUB = json.dumps([])

PLAN_STUB = json.dumps({
    'slug': 'andrew', 'athlete': {'name': 'Andrew'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [],
})
PLAN_LOAD_STUB = json.dumps({'athlete': 'andrew', 'weeks': 12, 'ctl_atl_tsb': []})
COACH_LOAD_STUB = json.dumps({'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': []})
COACH_PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [],
})

ACTIVE_ENTRY = {
    'id': 'h1',
    'description': 'Sharp right shoulder pain on catch-up drills since Tuesday.',
    'restriction': 'light_only',
    'source': 'self_reported',
    'reported_by': 'athlete',
    'reported_at': '2026-08-30T09:00:00Z',
    'resolved': False,
    'resolved_at': None,
    'expected_review_date': None,
}
RESOLVED_ENTRY = {
    'id': 'h0',
    'description': 'Old resolved calf tightness.',
    'restriction': 'light_only',
    'source': 'self_reported',
    'reported_by': 'athlete',
    'reported_at': '2026-07-01T09:00:00Z',
    'resolved': True,
    'resolved_at': '2026-07-10T09:00:00Z',
    'expected_review_date': None,
}
CREATED_ENTRY = {
    'id': 'h2',
    'description': 'Physio cleared pool work, no OW for 2 weeks.',
    'restriction': 'light_only',
    'source': 'practitioner',
    'reported_by': 'coach',
    'reported_at': '2026-09-01T09:00:00Z',
    'resolved': False,
    'resolved_at': None,
    'expected_review_date': '2026-09-13',
}
RESOLVED_ACTIVE_ENTRY = {**ACTIVE_ENTRY, 'resolved': True, 'resolved_at': '2026-09-01T10:00:00Z'}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _health_status_handler(get_body, *, post_response=None, patch_response=None, calls=None):
    """Serves GET with `get_body`; POST/PATCH (when given) record their JSON
    body into `calls` and respond with the given fixture -- mirrors
    test_coach_roster.py's `_reply_handler` shape for the feedback PATCH
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
        if method == 'PATCH' and patch_response is not None:
            if calls is not None:
                calls.append(json.loads(route.request.post_data))
            route.fulfill(
                status=200, content_type='application/json',
                body=json.dumps(patch_response), headers=CORS_HEADERS,
            )
            return
        route.fulfill(status=200, content_type='application/json', body=get_body, headers=CORS_HEADERS)
    return handler


def _make_ctx(pw, cfg, *, health_status_route=None, health_status_id_route=None):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx, identity=COACH_IDENTITY)
    seed_settings(ctx)
    ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
    ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
    ctx.route('**/api/coach/athletes/renee/workouts*', _cors_route(200, 'application/json', EMPTY_STUB))
    ctx.route('**/api/coach/athletes/renee/feedback*', _cors_route(200, 'application/json', EMPTY_STUB))
    ctx.route('**/api/coach/athletes/renee/load*', _cors_route(200, 'application/json', COACH_LOAD_STUB))
    ctx.route('**/api/coach/athletes/renee/plan*', _cors_route(200, 'application/json', COACH_PLAN_STUB))
    # PATCH .../health-status/<id> registered FIRST (Playwright matches the
    # more specific, longer-path pattern -- '*' never crosses a '/', same
    # rule test_coach_roster.py's own comment documents for its feedback
    # PATCH route) so a resolve click's id-scoped PATCH doesn't fall through
    # to the plain list GET/POST route below.
    if health_status_id_route is not None:
        ctx.route('**/api/coach/athletes/renee/health-status/*', health_status_id_route)
    ctx.route(
        '**/api/coach/athletes/renee/health-status*',
        health_status_route or _cors_route(200, 'application/json', EMPTY_STUB),
    )
    ctx.route('**/api/coach/athletes*', _cors_route(200, 'application/json', ATHLETES_STUB))
    ctx.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
    return browser, ctx


def _open_roster_and_select_renee(page):
    page.wait_for_selector('[data-a="tab:roster"]')
    page.click('[data-a="tab:roster"]')
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('.health-status-active, .health-status-empty')


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


def test_no_active_status_shows_an_honest_nothing_on_file_message(page):
    _open_roster_and_select_renee(page)
    content = page.content()
    assert 'No active health status on file' in content
    assert 'NOT a confirmation' in content


@pytest.mark.parametrize('cfg', BROWSERS)
def test_active_status_renders_prominently(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(
            pw, cfg,
            health_status_route=_cors_route(200, 'application/json', json.dumps([ACTIVE_ENTRY])),
        )
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            _open_roster_and_select_renee(pg)
            pg.wait_for_selector('.health-status-active')
            content = pg.content()
            assert 'Sharp right shoulder pain' in content
            assert 'Light training only' in content
            assert 'data-a="roster:health-status-resolve"' in content
        finally:
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_resolved_only_history_shows_no_active_status(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(
            pw, cfg,
            health_status_route=_cors_route(200, 'application/json', json.dumps([RESOLVED_ENTRY])),
        )
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            _open_roster_and_select_renee(pg)
            content = pg.content()
            assert 'No active health status on file' in content
            # Still visible in the history list below, never silently lost.
            assert 'Old resolved calf tightness' in content
        finally:
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_coach_can_submit_a_new_health_status_end_to_end(cfg, base_url):
    calls = []
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(
            pw, cfg,
            health_status_route=_health_status_handler(EMPTY_STUB, post_response=CREATED_ENTRY, calls=calls),
        )
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            _open_roster_and_select_renee(pg)
            pg.wait_for_selector('[data-form="roster-health-status"][data-field="description"]')

            pg.fill(
                '[data-form="roster-health-status"][data-field="description"]',
                'Physio cleared pool work, no OW for 2 weeks.',
            )
            pg.select_option('[data-form="roster-health-status"][data-field="restriction"]', 'light_only')
            pg.select_option('[data-form="roster-health-status"][data-field="source"]', 'practitioner')
            pg.click('[data-a="roster:health-status-submit"]')

            pg.wait_for_selector('text=Physio cleared pool work, no OW for 2 weeks.')

            assert len(calls) == 1
            assert calls[0]['description'] == 'Physio cleared pool work, no OW for 2 weeks.'
            assert calls[0]['restriction'] == 'light_only'
            assert calls[0]['source'] == 'practitioner'

            # The newly logged entry becomes the prominent active status.
            content = pg.content()
            assert 'health-status-active' in content
        finally:
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_coach_can_mark_the_active_status_resolved(cfg, base_url):
    calls = []
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(
            pw, cfg,
            health_status_route=_cors_route(200, 'application/json', json.dumps([ACTIVE_ENTRY])),
            health_status_id_route=_health_status_handler(
                json.dumps([ACTIVE_ENTRY]), patch_response=RESOLVED_ACTIVE_ENTRY, calls=calls,
            ),
        )
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            _open_roster_and_select_renee(pg)
            pg.wait_for_selector('[data-a="roster:health-status-resolve"]')
            pg.click('[data-a="roster:health-status-resolve"]')

            pg.wait_for_selector('.health-status-empty')
            assert len(calls) == 1
            assert calls[0] == {'resolved': True}
            content = pg.content()
            assert 'No active health status on file' in content
            # Still shown in the history below, now marked resolved.
            assert 'Sharp right shoulder pain' in content
        finally:
            ctx.close()
            browser.close()
