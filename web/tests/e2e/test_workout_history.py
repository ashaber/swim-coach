"""e2e coverage for the Log tab's workout history section (Slice 2).

Same mocked-backend conventions as test_log_checkin.py / test_feedback.py --
no real backend is ever contacted, every network call is intercepted via
Playwright routes with CORS headers attached.
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

# Real fixture data from the task brief: andrew's 2026-07-09 cross_train
# (rich analytics, no distance since it's not a swim) and his 2026-03-14
# swim_pool (SWOLF example). A third, older manual entry with analytics:
# null proves the section still renders fine without it.
CROSS_TRAIN_WORKOUT = {
    'id': 'w-cross', 'date': '2026-07-09', 'sport': 'cross_train', 'source': 'fit',
    'distance_m': None, 'duration_min': 303.3, 'avg_pace_s_per_100m': None, 'rpe': 6, 'notes': None,
    'avg_hr': None, 'max_hr': None, 'sport_detail': 'cycling/mountain',
    'analytics': {
        'cardiac_drift_pct': -13.77, 'split_label': None,
        'first_half_pace_s_per_100m': None, 'second_half_pace_s_per_100m': None,
        'elapsed_min': 303.3, 'moving_min': 303.3, 'pause_total_min': 0, 'pause_count': 0,
        'swolf_first_quarter': None, 'swolf_last_quarter': None, 'swolf_degradation_pct': None,
    },
}

POOL_SWIM_WORKOUT = {
    'id': 'w-pool', 'date': '2026-03-14', 'sport': 'swim_pool', 'source': 'fit',
    'distance_m': 3200, 'duration_min': 65, 'avg_pace_s_per_100m': 95, 'rpe': 5, 'notes': None,
    'avg_hr': None, 'max_hr': None,
    'analytics': {
        'cardiac_drift_pct': None, 'split_label': 'positive',
        'first_half_pace_s_per_100m': 90, 'second_half_pace_s_per_100m': 100,
        'elapsed_min': None, 'moving_min': None, 'pause_total_min': None, 'pause_count': None,
        'swolf_first_quarter': 40.96, 'swolf_last_quarter': 43.41, 'swolf_degradation_pct': 6.0,
    },
}

OLD_MANUAL_WORKOUT = {
    'id': 'w-old', 'date': '2025-11-02', 'sport': 'swim_pool', 'source': 'manual',
    'distance_m': 2000, 'duration_min': 40, 'avg_pace_s_per_100m': None, 'rpe': None, 'notes': 'easy recovery',
    'avg_hr': None, 'max_hr': None, 'analytics': None,
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
    """Same shape as test_log_checkin.py's `page` fixture: signed in but
    deliberately not pre-configured with a backend, and /api/athlete
    stubbed since Settings' profile-edit section fetches it as soon as
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


def test_history_renders_workouts_including_analytics_line(page):
    workouts = [CROSS_TRAIN_WORKOUT, POOL_SWIM_WORKOUT, OLD_MANUAL_WORKOUT]
    page.route('**/api/workouts*', _cors_route(200, 'application/json', json.dumps(workouts)))

    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('.hist-row')

    content = page.content()
    assert 'Recent workouts' in content
    # Sport labels for all three, including cross_train's label -- with its
    # sport_detail pretty suffix (MTB, from raw "cycling/mountain").
    assert 'Cross-train · MTB' in content
    assert 'Pool swim' in content
    # The cross_train workout's cardiac-drift analytics line.
    assert 'drift -13.8%' in content
    # The pool swim's SWOLF analytics line (real andrew fixture numbers).
    assert 'SWOLF 41.0' in content
    assert '43.4' in content
    assert '+6.0%' in content
    # Non-manual source badge shows; manual source doesn't add one.
    assert page.locator('.hist-row').count() == 3
    assert 'RPE 6' in content


def test_history_shows_empty_state_when_no_workouts_logged(page):
    page.route('**/api/workouts*', _cors_route(200, 'application/json', '[]'))
    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    # .hist-section alone also matches the "Loading history…" render, so wait
    # for the settled empty state -- asserting right after the bare selector
    # races the (mocked) fetch on slow runners.
    page.wait_for_selector('.hist-section:has-text("No workouts logged yet.")')
    assert 'No workouts logged yet.' in page.content()


def test_history_shows_error_and_retry_on_fetch_failure(page):
    page.route('**/api/workouts*', _cors_route(500, 'application/json', '{"error": "boom"}'))
    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('[data-a="history:retry"]')
    assert "Couldn't load your workout history" in page.content()

    # Retry re-fetches; make it succeed this time.
    page.route('**/api/workouts*', _cors_route(200, 'application/json', json.dumps([OLD_MANUAL_WORKOUT])))
    page.click('[data-a="history:retry"]')
    page.wait_for_selector('.hist-row')
    assert 'Pool swim' in page.content()


def test_history_refreshes_after_a_successful_manual_log_submit(page):
    # First load: empty history. After a successful log submit, the list
    # should include the newly logged workout (refetched, not just appended
    # client-side -- see main.js's handleSubmitLog calling loadHistory()).
    state = {'submitted': False}

    def workouts_handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        if route.request.method == 'POST':
            state['submitted'] = True
            route.fulfill(status=200, content_type='application/json', body='{"id": "w-new", "date": "2026-07-11"}', headers=CORS_HEADERS)
            return
        body = json.dumps([OLD_MANUAL_WORKOUT]) if state['submitted'] else '[]'
        route.fulfill(status=200, content_type='application/json', body=body, headers=CORS_HEADERS)

    page.route('**/api/workouts*', workouts_handler)

    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    # Settled empty state, not the bare section (which matches the loading
    # render too) -- also ensures the history fetch's re-render has landed
    # before the fills below, so they can't hit a detached form node.
    page.wait_for_selector('.hist-section:has-text("No workouts logged yet.")')
    assert 'No workouts logged yet.' in page.content()

    page.fill('[data-form="log"][data-field="distance_m"]', '3000')
    page.fill('[data-form="log"][data-field="duration_min"]', '60')
    page.click('[data-a="log:submit"]')

    page.wait_for_selector('.conn-result.ok')
    page.wait_for_selector('.hist-row')
    assert 'Pool swim' in page.content()


def test_log_tab_still_loads_offline_with_a_quiet_history_notice(page):
    _configure_backend(page)

    ctx = page.context
    ctx.set_offline(True)
    try:
        # Wait for the app's own online/offline listener (main.js's
        # updateOnlineState) to actually observe the transition before
        # navigating -- otherwise there's a race where the Log tab click
        # lands while state.online is still stale `true`, and the app would
        # attempt (and fail) a real fetch instead of skipping it quietly.
        page.wait_for_function('() => !navigator.onLine')
        page.click('[data-a="tab:log"]')
        page.wait_for_selector('.hist-section')
        content = page.content()
        # The app itself keeps working offline (form still renders); history
        # just quietly declines to claim "no workouts" when it never fetched.
        assert page.locator('[data-form="log"][data-field="distance_m"]').count() == 1
        assert 'reconnect' in content.lower()
        assert 'No workouts logged yet.' not in content
    finally:
        ctx.set_offline(False)


def test_history_list_has_no_horizontal_overflow_on_narrow_viewport(page):
    # A worst-case row: every analytics sub-field populated at once, plus a
    # long source/rpe combo, to stress-test wrapping at the narrowest
    # viewport this suite covers (390x844, the webkit/iOS-Safari proxy --
    # see conftest.BROWSERS).
    dense_workout = {
        **CROSS_TRAIN_WORKOUT,
        'id': 'w-dense',
        'analytics': {
            'cardiac_drift_pct': 8.4, 'split_label': 'positive',
            'first_half_pace_s_per_100m': 88, 'second_half_pace_s_per_100m': 102,
            'elapsed_min': 320.0, 'moving_min': 303.3, 'pause_total_min': 16.7, 'pause_count': 4,
            'swolf_first_quarter': 38.2, 'swolf_last_quarter': 44.9, 'swolf_degradation_pct': 17.5,
        },
    }
    page.route('**/api/workouts*', _cors_route(200, 'application/json', json.dumps([dense_workout])))

    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('.hist-row')

    overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
    assert overflow <= 1, f'page overflows horizontally by {overflow}px'


def test_tab_bar_still_includes_log(page):
    page.wait_for_selector('.tabbar')
    assert page.locator('[data-a="tab:log"]').count() == 1
