"""e2e: the Plan tab checks for a changed plan with a conditional request (If-None-Match) when it
is switched to, instead of keeping whatever loaded at boot (a coach edit never showed up until a
restart) or fully re-downloading every time. Reuses test_plan_session_detail's far-future week
constants; service workers are blocked so only the app's own fetch logic is under test."""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings
from test_plan_session_detail import MONDAY, TUESDAY, WEEK


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        seed_settings(ctx)
        ctx.route('**/api/plan/load*', lambda route: route.fulfill(
            status=200, content_type='application/json', body='{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'))
        ctx.route('**/api/athlete*', lambda route: route.fulfill(
            status=200, content_type='application/json', body='{"race_debriefs": []}'))
        pg = ctx.new_page()
        errors: list[str] = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto(base_url)
        try:
            yield pg
            assert not errors, f'Uncaught JS errors: {errors}'
        finally:
            ctx.close()
            browser.close()

CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type, If-None-Match',
    'Access-Control-Expose-Headers': 'ETag',
    'Cache-Control': 'private, no-cache',
}


def _session(sid, date, purpose):
    return {
        'id': sid, 'date': date, 'sport': 'swim_pool', 'source': 'ai_coach', 'duration_min': 45,
        'distance_m': 2000, 'intensity': {'zone': 'Z2'}, 'purpose': purpose, 'structure': None, 'status': 'planned',
    }


def _plan(*sessions):
    return json.dumps({
        'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []},
        'weeks': [{**WEEK, 'sessions': list(sessions)}],
    })


def test_switching_to_the_plan_tab_checks_for_changes_and_applies_only_real_ones(page):
    if page.context.browser.browser_type.name == 'webkit':
        pytest.skip('Playwright WebKit cannot fulfill a route with status 304; the 304 path is covered '
                    'by vitest (apiConditional) and this test on Chromium')
    versions = {
        'v1': (_plan(_session('s-alpha', MONDAY, 'aerobic alpha')), 'W/"v1"'),
        'v2': (_plan(_session('s-alpha', MONDAY, 'aerobic alpha'), _session('s-beta', TUESDAY, 'tempo beta')),
               'W/"v2"'),
    }
    current = {'v': 'v1'}
    sent_headers = []

    def plan_route(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS)
            return
        body, etag = versions[current['v']]
        sent = route.request.headers.get('if-none-match')
        sent_headers.append(sent)
        if sent == etag:
            route.fulfill(status=304, headers={**CORS, 'ETag': etag})
            return
        route.fulfill(status=200, content_type='application/json', body=body, headers={**CORS, 'ETag': etag})

    page.route('**/api/plan*', plan_route)
    page.reload()
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector('[data-a="session:open"][data-id="s-alpha"]')

    # Unchanged: the next visit replays the remembered ETag, gets a 304, and the view is unchanged.
    page.click('[data-a="tab:resources"]')
    page.click('[data-a="tab:plan"]')
    page.wait_for_timeout(500)
    assert 'W/"v1"' in sent_headers
    assert page.locator('[data-a="session:open"][data-id="s-alpha"]').count() == 1
    assert page.locator('[data-a="session:open"][data-id="s-beta"]').count() == 0

    # The coach changed the plan: the next visit picks it up.
    current['v'] = 'v2'
    page.click('[data-a="tab:resources"]')
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector('[data-a="session:open"][data-id="s-beta"]')
