"""e2e coverage for the Plan tab's per-session "Push to Garmin" button.

The athlete's actual requirement: get a planned workout onto the watch
wirelessly (USB-copying the `.fit` export was tried and rejected), from the
app itself rather than only through a chat tool. The button POSTs to
`/api/sessions/{id}/push-intervals` (backend/app/routes/garmin.py), which
writes the workout to her intervals.icu calendar for intervals.icu's own
Garmin Connect integration to forward on.

Same page-fixture convention as test_plan_session_detail.py: signed in +
configured, `**/api/plan*` stubbed with this file's own fixture sessions, and
the push route stubbed per-test so no real network is ever touched.
"""

import json
import re

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

# A regex, deliberately NOT a glob. `'**/api/sessions/*/push-intervals*'`
# matched under Chromium but silently did NOT under WebKit, so the request
# escaped to the real network -- which made the failure-path test pass for
# entirely the wrong reason (an unreachable backend renders the same error
# state a stubbed 409 does). Every test below also asserts the stub was
# actually hit, so a matcher that stops matching can never again masquerade
# as a passing test.
PUSH_ROUTE = re.compile(r'/api/sessions/[^/]+/push-intervals')

# The push is a cross-origin POST carrying an Authorization header, so the
# browser sends a CORS preflight first. WebKit enforces it strictly: without
# an OPTIONS answer the preflight fails and the real POST is never sent at
# all. Same handling (and header set) as test_workout_sync.py's own
# `_cors_route`, which exists for exactly this reason.
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

ISO_WEEK = '2099-W01'
MONDAY = '2098-12-29'
TUESDAY = '2098-12-30'

# Has `structured` -- pushable.
PUSHABLE_SESSION = {
    'id': 's-pushable', 'date': MONDAY, 'sport': 'swim_pool', 'source': 'ai_coach',
    'duration_min': 40, 'distance_m': 1600, 'intensity': {'zone': 'Z3'},
    'purpose': 'Threshold set', 'structure': 'Main set: 4 x 200m @ Z3',
    'structured': {
        'items': [
            {
                'kind': 'step', 'label': '4 x 200m @ Z3', 'role': 'interval',
                'duration_kind': 'distance_m', 'duration_value': 800, 'target': None,
                'load': None, 'modality': 'swim', 'stroke': None, 'equipment': [],
                'exercise_name': None, 'reference_url': None,
            },
        ],
    },
    'status': 'planned',
}

# Prose only, no `structured` -- nothing real to push, so no button.
PROSE_ONLY_SESSION = {
    'id': 's-prose-only', 'date': TUESDAY, 'sport': 'swim_pool', 'source': 'pool_coach',
    'duration_min': 90, 'distance_m': None, 'intensity': {},
    'purpose': 'coached USMS pool — content assigned by coach',
    'structure': None, 'structured': None, 'status': 'planned',
}

WEEK = {
    'iso_week': ISO_WEEK, 'meso_block': 'base', 'focus': 'aerobic base',
    'target_volume_m': 12000, 'adaptation_rationale': None,
    'sessions': [PUSHABLE_SESSION, PROSE_ONLY_SESSION],
}

PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [],
    'macro': {'blocks': []}, 'weeks': [WEEK],
})


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        # `service_workers='block'` matches test_workout_sync.py's fixture,
        # the other file that drives a cross-origin POST. Without it the PWA's
        # service worker intercepts the push request before Playwright's own
        # route can, and under WebKit it escapes to the real network -- which
        # silently turned the failure-path test into a test of an unreachable
        # backend rather than of the stubbed 409.
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        seed_settings(ctx)
        ctx.route('**/api/plan*', lambda route: route.fulfill(
            status=200, content_type='application/json', body=PLAN_STUB))
        # GET /api/plan/load fires unconditionally at boot alongside GET
        # /api/plan (main.js's loadPlanLoad) -- same treatment as the stub
        # just above.
        ctx.route('**/api/plan/load*', lambda route: route.fulfill(
            status=200, content_type='application/json',
            body='{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'))
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


def _open_session_detail(page, session_id):
    page.wait_for_selector(f'[data-a="session:open"][data-id="{session_id}"]')
    page.click(f'[data-a="session:open"][data-id="{session_id}"]')
    page.wait_for_selector('[data-a="session:back"]')


def test_push_button_renders_for_a_session_with_structured_data(page):
    _open_session_detail(page, 's-pushable')
    button = page.locator('[data-a="session:push-intervals"]')
    assert button.count() == 1
    assert 'Push to Garmin' in button.text_content()


def test_push_button_is_absent_for_a_prose_only_session(page):
    # A prose-only session has no structured workout, so there is nothing
    # real to send -- offering the button would push garbage to a watch.
    _open_session_detail(page, 's-prose-only')
    assert page.locator('[data-a="session:push-intervals"]').count() == 0
    # ...and the download button is absent for the same reason, unchanged.
    assert page.locator('[data-a="session:garmin-download"]').count() == 0


def _stub_push(page, requests, *, status=200, body=None):
    """Stubs the push route, recording every intercepted request so each test
    can prove the stub -- not the real network -- served it."""
    payload = body if body is not None else {'pushed': 1, 'skipped': 0, 'failed': 0, 'results': []}

    def handler(route, request):
        if request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        requests.append(f'{request.method} {request.url}')
        route.fulfill(status=status, content_type='application/json',
                      body=json.dumps(payload), headers=CORS_HEADERS)

    page.route(PUSH_ROUTE, handler)


def test_clicking_push_issues_the_request_and_shows_a_success_message(page):
    requests: list[str] = []
    _stub_push(page, requests)

    _open_session_detail(page, 's-pushable')
    page.click('[data-a="session:push-intervals"]')
    page.wait_for_selector('.conn-result.ok')

    assert len(requests) == 1
    assert requests[0].startswith('POST ')
    assert '/api/sessions/s-pushable/push-intervals' in requests[0]
    assert 'athlete=renee' in requests[0]
    assert 'Intervals.icu calendar' in page.locator('.conn-result.ok').text_content()


def test_a_failed_push_shows_an_error_state_not_a_silent_no_op(page):
    requests: list[str] = []
    _stub_push(page, requests, status=409,
               body={'detail': 'sync not configured for this athlete'})

    _open_session_detail(page, 's-pushable')
    page.click('[data-a="session:push-intervals"]')
    page.wait_for_selector('.conn-result.fail')

    # Proves the 409 stub served this, not an unreachable backend -- an
    # offline backend renders the identical error state.
    assert len(requests) == 1
    assert page.locator('.conn-result.fail').count() == 1
    # The success message must NOT appear alongside the failure.
    assert page.locator('.conn-result.ok').count() == 0


def test_push_result_does_not_leak_onto_another_session(page):
    requests: list[str] = []
    _stub_push(page, requests)

    _open_session_detail(page, 's-pushable')
    page.click('[data-a="session:push-intervals"]')
    page.wait_for_selector('.conn-result.ok')
    assert len(requests) == 1

    # Back out and open a different session -- the previous result must not
    # follow it (the state is a single {id, ...}, scoped by id in views.js).
    page.click('[data-a="session:back"]')
    _open_session_detail(page, 's-prose-only')
    assert page.locator('.conn-result').count() == 0


def test_push_button_does_not_introduce_horizontal_overflow(page):
    _open_session_detail(page, 's-pushable')
    overflow = page.evaluate(
        'document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1, f'horizontal overflow of {overflow}px'
