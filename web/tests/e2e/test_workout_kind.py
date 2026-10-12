"""e2e: the workout detail shows the workout's kind, keeps the race pacing panel for races only, lets
the athlete retag the kind (POST /api/workouts/{id}/kind), and draws a sparkline per race start.

Same mocked-backend conventions as test_workout_shape_and_analysis.py: no real backend."""

import json
import re

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity

BASE_URL = 'https://coach-api.test'
TOKEN = 'test-token-123'
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

TRACE = [0, 187, 302, 649, 864, 1100, 721, 843, 925, 883, 857, 830, 765, 668, 639, 711, 704, 707, 694, 655, 603,
         5, 22, 365, 445, 547, 543, 498, 67, 2, 2, 2, 5, 1, 0, 0, 0]
START = {
    'n': 4, 'prescribed_s': 30, 'intended_s': 30, 'burst_start_s': 2246, 'burst_s': 18, 'peak_w': 1100,
    's_to_peak': 2, 'best_5s_w': 894, 'avg_w': 768, 'drop_vs_best_pct': None, 'weak_start': False,
    'trace_w': TRACE, 'trace_t0': 0, 'launch_s': 5, 'stopped_at_s': 21, 'stopped_early_s': 9,
    'verdict': 'peak 1100 W, best 5 s 894 W; dip to 721 W at 6 s (likely shift/bobble); stopped at 21 s, 9 s before the 30 s mark',
}
RIDE = {
    'id': 'w-ride', 'date': '2026-10-10', 'sport': 'bike', 'source': 'fit', 'distance_m': 40000,
    'duration_min': 90, 'rpe': 7, 'avg_hr': 150, 'max_hr': 175, 'planned_session_id': None, 'kind': 'workout',
    'analytics': {'avg_power_w': 200, 'intervals': {'efforts_detected': 1, 'starts': [START]}},
    'laps': [], 'lengths': [], 'pauses': [], 'notes': None,
}
PACING = {
    'workout_id': 'w-ride', 'gps_laps': {'detected': 0, 'laps': [], 'truncated': False, 'note': 'No laps detected'},
    'race_phases': {'phases': [], 'significance_threshold_pct': 5.0},
    'race_execution': {'kind': 'race', 'score': None, 'reason': 'not scored: too short', 'components': []},
}


def _json(route, status, body):
    if route.request.method == 'OPTIONS':
        route.fulfill(status=204, headers=CORS_HEADERS)
        return
    route.fulfill(status=status, content_type='application/json', body=json.dumps(body), headers=CORS_HEADERS)


@pytest.fixture(params=BROWSERS)
def ride_page(request, base_url):
    cfg = request.param
    pw = sync_playwright().start()
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pw.stop()
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx)
    state = {'ride': RIDE, 'pacing_calls': 0, 'kind_posts': []}

    def kind_route(route):
        if route.request.method == 'POST':
            kind = json.loads(route.request.post_data)['kind']
            state['kind_posts'].append(kind)
            state['ride'] = {**state['ride'], 'kind_override': kind, 'load_au': 50}
            _json(route, 200, state['ride'])
        else:
            _json(route, 204, {})

    def pacing_route(route):
        state['pacing_calls'] += 1
        _json(route, 200, PACING)

    ctx.route('**/api/athlete*', lambda r: _json(r, 200, {'slug': 'renee', 'name': 'Renee', 'race_debriefs': []}))
    ctx.route('**/api/grants*', lambda r: _json(r, 200, []))
    ctx.route('**/api/plan*', lambda r: _json(r, 200, {
        'slug': 'renee', 'name': 'Renee', 'athlete': {'name': 'Renee', 'ftp_watts': 276}, 'events': [],
        'macro': {'blocks': []}, 'weeks': [],
    }))
    ctx.route('**/api/plan/load*', lambda r: _json(r, 200, {'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': []}))
    ctx.route('**/api/feedback*', lambda r: _json(r, 200, []))
    ctx.route('**/api/workouts*', lambda r: _json(r, 200, [state['ride']]))
    ctx.route(re.compile(r'/api/workouts/[^/]+/pacing'), pacing_route)
    ctx.route(re.compile(r'/api/workouts/[^/]+/kind'), kind_route)
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base_url)
    pg.evaluate(
        "(cfg) => window.localStorage.setItem("
        "'swimcoach_settings', JSON.stringify({baseUrl: cfg.baseUrl, token: cfg.token, version: 2}))",
        {'baseUrl': BASE_URL, 'token': TOKEN},
    )
    pg.reload()
    pg.click('[data-a="tab:dashboard"]')
    pg.wait_for_selector('.hist-row')
    pg.click('.hist-row')
    pg.wait_for_selector('[data-a="history:back"]')
    try:
        yield pg, state
    finally:
        real = [e for e in errors if 'sw.js load failed' not in e and 'Importing a module script failed' not in e]
        ctx.close()
        browser.close()
        pw.stop()
        assert not real, f'Uncaught JS errors: {real}'


def _no_horizontal_scroll(page):
    return page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')


def test_workout_detail_shows_kind_and_no_race_panel_or_pacing_fetch(ride_page):
    page, state = ride_page
    assert page.locator('.kind-label').inner_text() == 'Workout'
    assert page.locator('select[data-a="workout:kind-select"]').input_value() == 'workout'
    page.wait_for_timeout(300)
    assert page.locator('details.race-analysis').count() == 0
    assert state['pacing_calls'] == 0
    assert _no_horizontal_scroll(page)


def test_retag_to_race_posts_the_kind_and_shows_the_race_panel(ride_page):
    page, state = ride_page
    page.select_option('select[data-a="workout:kind-select"]', 'race')
    page.wait_for_selector('details.race-analysis')
    assert state['kind_posts'] == ['race']
    assert page.locator('.kind-label').inner_text() == 'Race'
    assert page.locator('select[data-a="workout:kind-select"]').input_value() == 'race'
    assert state['pacing_calls'] >= 1
    page.select_option('select[data-a="workout:kind-select"]', 'workout')
    page.wait_for_selector('details.race-analysis', state='detached')
    assert state['kind_posts'] == ['race', 'workout']
    assert _no_horizontal_scroll(page)


def test_raw_analysis_draws_a_sparkline_per_start_without_horizontal_scroll(ride_page):
    page, _state = ride_page
    page.click('[data-a="workout:raw-analysis-toggle"]')
    page.wait_for_selector('.start-traces')
    assert page.locator('.start-trace svg polyline').count() == 1
    text = page.locator('.start-trace-text').inner_text()
    assert 'likely shift/bobble' in text and '9 s before the 30 s mark' in text
    assert _no_horizontal_scroll(page)
