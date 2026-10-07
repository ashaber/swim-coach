"""e2e: the workout SHAPE chart (planned session detail + completed ride matched to its plan) and the
read-only "Raw analysis" panel on the workout detail view (execution-score breakdown, efforts table).

Same mocked-backend conventions as test_workout_detail.py: no real backend, every call intercepted."""

import json
import re
from datetime import date, timedelta
from pathlib import Path

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

FIXTURE = json.loads(
    (Path(__file__).resolve().parents[3] / 'tests' / 'fixtures' / 'ride_2026_09_29_vo2_40_20.json').read_text()
)
# The Plan tab only shows the current/next week expanded (older weeks collapse into "past weeks"), so the
# planned session must sit in the week the test actually runs in, not the fixture ride's own 2026-W40.
_TODAY = date.today()
_ISO_YEAR, _ISO_WEEK, _ = _TODAY.isocalendar()
_SESSION_DATE = _TODAY - timedelta(days=_TODAY.weekday()) + timedelta(days=1)
SESSION = {
    **FIXTURE['planned_session'], 'date': _SESSION_DATE.isoformat(), 'title': '3x6 VO2 40/20', 'target_load_au': 90,
}
SESSION_ID = SESSION['id']

PLAN = {
    'slug': 'renee',
    'name': 'Renee',
    'athlete': {'name': 'Renee', 'ftp_watts': 276},
    'events': [],
    'macro': {'blocks': []},
    'weeks': [{
        'iso_week': f'{_ISO_YEAR}-W{_ISO_WEEK:02d}', 'meso_block': 'build', 'focus': 'VO2', 'target_volume_m': 0,
        'sessions': [SESSION],
    }],
}
PLAN_NO_FTP = {**PLAN, 'athlete': {'name': 'Renee'}}

EXECUTION = {
    'kind': 'workout', 'score': 91.5, 'reason': None,
    'components': [
        {'name': 'intensity', 'score': 100.0, 'weight': 0.5, 'detail': '100% of completed reps inside the band'},
        {'name': 'completion', 'score': 100.0, 'weight': 0.3, 'detail': '18/18 reps'},
        {'name': 'consistency', 'score': 57.0, 'weight': 0.2, 'detail': 'worst fade 11%'},
    ],
}
EFFORTS = [{
    'n': i + 1, 'start_s': 900 + i * 60, 'duration_s': 40, 'avg_w': 308.0, 'avg_hr': 150 + i,
    'target_w': 310.5, 'fade_pct': 1.0, 'hr_drift_bpm': 1.5, 'verdict': 'on target',
    'in_target_band': True, 'round_n': 1, 'rep_in_round': i + 1,
} for i in range(3)]
WORKOUT = {
    'id': 'w-ride', 'date': '2026-09-29', 'sport': 'bike', 'source': 'fit', 'distance_m': 27824,
    'duration_min': 55.5, 'rpe': 6, 'avg_hr': 142, 'max_hr': 173, 'planned_session_id': SESSION_ID,
    'analytics': {
        'avg_power_w': 186, 'normalized_power_w': 212,
        'intervals': {
            'efforts_detected': 3, 'detection_basis': 'power', 'matched_to_prescription': True,
            'prescribed_count': 18, 'detection_source': 'laps', 'reps_completed': 18,
            'reps_in_band_pct': 100.0, 'fade_across_reps_pct': 0.4, 'fade_across_rounds_pct': 0.1,
            'target_zone': 'Z5', 'target_band_w': [289.8, 331.2], 'efforts': EFFORTS,
            'rounds': [{'n': 1, 'reps_prescribed': 6, 'reps_completed': 6, 'avg_w': 307.9, 'avg_hr': 150,
                        'reps_in_band': 6, 'fade_within_pct': 0.5}],
        },
    },
    'quality': {'matched': True, 'intensity_match': 'match', 'execution': EXECUTION},
    'laps': [{'index': 0, 'duration_s': 900, 'start_offset_s': 0, 'avg_power_w': 189, 'distance_m': 7777, 'avg_hr': 131}],
    'lengths': [], 'pauses': [], 'notes': None,
}
PACING = {
    'workout_id': 'w-ride', 'gps_laps': {'detected': 0, 'laps': [], 'truncated': False, 'note': 'No laps detected'},
    'race_phases': {'phases': [], 'significance_threshold_pct': 5.0},
    'race_execution': {'kind': 'race', 'score': None, 'reason': 'not scored: too short', 'components': []},
    'power_profile': [[t, 300 if 900 <= t < 1000 else 150] for t in range(0, 3300, 30)],
}


def _cors_route(status, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type='application/json', body=json.dumps(body), headers=CORS_HEADERS)
    return handler


def _make_page(request, base_url, plan):
    cfg = request.param
    pw = sync_playwright().start()
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pw.stop()
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx)
    ctx.route('**/api/athlete*', _cors_route(200, {'slug': 'renee', 'name': 'Renee', 'race_debriefs': []}))
    ctx.route('**/api/grants*', _cors_route(200, []))
    ctx.route('**/api/plan*', _cors_route(200, plan))
    ctx.route('**/api/plan/load*', _cors_route(200, {'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': []}))
    ctx.route('**/api/feedback*', _cors_route(200, []))
    ctx.route('**/api/workouts*', _cors_route(200, [WORKOUT]))
    ctx.route(re.compile(r'/api/workouts/[^/]+/pacing'), _cors_route(200, PACING))
    pg = ctx.new_page()
    errors: list[str] = []
    pg.on('pageerror', lambda e: errors.append(str(e)))
    pg.goto(base_url)
    return pw, browser, ctx, pg, errors


def _finish(pw, browser, ctx, errors):
    real = [e for e in errors if 'sw.js load failed' not in e and 'Importing a module script failed' not in e]
    ctx.close()
    browser.close()
    pw.stop()
    assert not real, f'Uncaught JS errors: {real}'


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    pw, browser, ctx, pg, errors = _make_page(request, base_url, PLAN)
    try:
        yield pg
    finally:
        _finish(pw, browser, ctx, errors)


@pytest.fixture(params=BROWSERS)
def page_no_ftp(request, base_url):
    pw, browser, ctx, pg, errors = _make_page(request, base_url, PLAN_NO_FTP)
    try:
        yield pg
    finally:
        _finish(pw, browser, ctx, errors)


def _configure_backend(page):
    page.evaluate(
        "(cfg) => window.localStorage.setItem("
        "'swimcoach_settings', JSON.stringify({baseUrl: cfg.baseUrl, token: cfg.token, version: 2}))",
        {'baseUrl': BASE_URL, 'token': TOKEN},
    )
    page.reload()


def _open_session(page):
    _configure_backend(page)
    page.wait_for_selector(f'[data-a="session:open"][data-id="{SESSION_ID}"]')
    page.click(f'[data-a="session:open"][data-id="{SESSION_ID}"]')
    page.wait_for_selector('[data-a="session:back"]')


def _open_ride(page):
    _configure_backend(page)
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-row')
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')


def _no_horizontal_scroll(page):
    return page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')


def test_planned_session_detail_draws_the_shape_in_zone_colours(page):
    _open_session(page)
    page.wait_for_selector('svg.shape-chart')
    # 1 warm-up + 18 hard + 18 easy + 2 recoveries + cool-down = 40 planned bars
    assert page.locator('svg.shape-chart polygon').count() >= 38
    legend = page.locator('.shape-legend').inner_text()
    assert 'Z5' in legend and 'VO2max' in legend and '290-331 W' in legend
    assert page.locator('svg.shape-chart polyline').count() == 0  # nothing ridden on a plan
    assert _no_horizontal_scroll(page)


def test_planned_session_without_ftp_explains_instead_of_drawing(page_no_ftp):
    _open_session(page_no_ftp)
    assert page_no_ftp.locator('svg.shape-chart').count() == 0
    assert 'Set your FTP in Settings' in page_no_ftp.content()


def test_matched_ride_overlays_actual_power_on_the_plan(page):
    _open_ride(page)
    page.wait_for_selector('svg.shape-chart polyline', state='attached')
    assert 'Plan vs ridden' in page.content()
    assert page.locator('svg.shape-chart polygon').count() >= 38
    assert page.locator('.shape-legend .shape-legend-item').count() >= 3
    assert _no_horizontal_scroll(page)


def test_raw_analysis_button_opens_the_breakdown_and_works_offline(page):
    _open_ride(page)
    button = page.locator('[data-a="workout:raw-analysis-toggle"]')
    assert button.inner_text() == 'Raw analysis'
    assert page.locator('.raw-analysis').count() == 0

    page.context.set_offline(True)  # rendered from the cached workout, no network needed
    button.click()
    page.wait_for_selector('.raw-analysis')
    text = page.locator('.raw-analysis').inner_text().lower()
    assert 'execution score' in text and '92 / 100' in text
    assert 'consistency' in text and 'worst fade 11%' in text
    assert 'target band' in text and '289.8-331.2 w' in text
    assert page.locator('.raw-analysis table.raw-table').count() >= 2
    efforts = page.locator('.raw-analysis table.raw-table').nth(1)
    assert efforts.locator('tbody tr').count() == 3
    assert '290-331 w' in efforts.locator('tbody tr').first.inner_text().lower()
    assert 'on target' in efforts.inner_text()
    assert _no_horizontal_scroll(page)

    page.locator('[data-a="workout:raw-analysis-toggle"]').click()
    page.wait_for_selector('.raw-analysis', state='detached')
