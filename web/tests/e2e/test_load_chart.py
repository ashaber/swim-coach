"""e2e coverage for the CTL/ATL/TSB training-load chart (views.js's
renderLoadChart, fed by plan.js's ctlAtlTsbChartGeometry) -- surfaces
`backend/app/context.py`'s `summarize_rollup` "ctl_atl_tsb" field directly
to the frontend via the new `GET /api/plan/load` (athlete self-access) and
`GET /api/coach/athletes/{slug}/load` (coach access) endpoints, on two
surfaces sharing the same render function: the athlete's own Plan tab
(main.js's loadPlanLoad) and the coach roster's acting-as-athlete view
(main.js's loadCoachLoad).

Same mocked-backend / CORS-preflight conventions as test_plan_session_detail.py
/ test_coach_roster.py: cross-origin GETs carrying an Authorization header,
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


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [],
})

# A real, non-empty series -- an ATL drop with CTL holding steady, the
# "real taper" shape the chart's whole point is to make legible (see
# plan.js's module comment: TSB alone would lose this signal).
REAL_SERIES = [
    ['2026-08-01', 40.0, 38.0, 2.0],
    ['2026-08-08', 41.0, 30.0, 11.0],
    ['2026-08-15', 40.5, 20.0, 20.5],
    ['2026-08-22', 40.0, 15.0, 25.0],
]
PLAN_LOAD_STUB = json.dumps({'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': REAL_SERIES})

COACH_IDENTITY = {'name': 'Andrew', 'athlete': 'andrew', 'role': 'coach', 'coachFor': ['renee']}
COACH_ATHLETES_STUB = json.dumps([{'slug': 'renee', 'name': 'Renee'}])
COACH_WORKOUTS_STUB = json.dumps([])
COACH_FEEDBACK_STUB = json.dumps([])
COACH_LOAD_STUB = json.dumps({'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': REAL_SERIES})


def _make_ctx(pw, cfg, *, identity=None):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx, identity=identity)
    seed_settings(ctx)
    ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
    ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
    ctx.route('**/api/coach/athletes/renee/workouts*', _cors_route(200, 'application/json', COACH_WORKOUTS_STUB))
    ctx.route('**/api/coach/athletes/renee/feedback*', _cors_route(200, 'application/json', COACH_FEEDBACK_STUB))
    ctx.route('**/api/coach/athletes/renee/load*', _cors_route(200, 'application/json', COACH_LOAD_STUB))
    ctx.route('**/api/coach/athletes*', _cors_route(200, 'application/json', COACH_ATHLETES_STUB))
    return browser, ctx


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Signed in as the athlete herself (renee), landing on the Plan tab."""
    cfg = request.param
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg)
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


@pytest.fixture(params=BROWSERS)
def coach_page(request, base_url):
    """Signed in as a coach with a grant over renee."""
    cfg = request.param
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, identity=COACH_IDENTITY)
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


# --- Athlete's own Plan tab ---------------------------------------------------

def test_chart_renders_on_the_plan_tab_with_real_mocked_data(page):
    page.wait_for_selector('.mast h1')
    page.wait_for_selector('.load-chart-svg')
    content = page.content()
    # Clear labels for both athlete and coach.
    assert 'Training load' in content
    assert 'CTL' in content
    assert 'ATL' in content
    assert 'TSB' in content
    # The three lines are present.
    assert page.locator('.load-chart-line-ctl').count() == 1
    assert page.locator('.load-chart-line-atl').count() == 1
    assert page.locator('.load-chart-line-tsb').count() == 1
    # The race-day reference band, honestly captioned.
    assert page.locator('.load-chart-band').count() == 1
    assert 'cycling' in content.lower()
    assert 'not a swim-specific or peer-reviewed target' in content.lower()
    # The provisional-time-constant honesty caveat.
    assert 'not yet verified for swimming' in content.lower()


def test_chart_is_not_buried_in_a_collapsed_section(page):
    # Task requirement: visible on load, not tucked inside an already-
    # collapsed <details> the way the glossary is.
    page.wait_for_selector('.mast h1')
    chart = page.locator('.load-chart-svg')
    chart.wait_for(state='visible')
    assert chart.is_visible()


# --- Coach roster's acting-as-athlete view -------------------------------------

def test_chart_renders_on_the_coach_roster_view_for_a_granted_athlete(coach_page):
    page = coach_page
    page.wait_for_selector('[data-a="tab:roster"]')
    page.click('[data-a="tab:roster"]')
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:back"]')

    page.wait_for_selector('.load-chart-svg')
    content = page.content()
    assert 'CTL' in content
    assert 'ATL' in content
    assert 'TSB' in content
    assert page.locator('.load-chart-line-ctl').count() == 1
    assert page.locator('.load-chart-band').count() == 1


def test_coach_roster_chart_disappears_when_going_back_to_the_athlete_list(coach_page):
    page = coach_page
    page.wait_for_selector('[data-a="tab:roster"]')
    page.click('[data-a="tab:roster"]')
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('.load-chart-svg')

    page.click('[data-a="roster:back"]')
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    assert page.locator('.load-chart-svg').count() == 0


# --- Mobile viewport / overflow standards --------------------------------------

def test_plan_tab_chart_does_not_overflow_horizontally(page):
    page.wait_for_selector('.load-chart-svg')
    overflow = page.evaluate(
        'document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1, f'horizontal overflow of {overflow}px'


def test_coach_roster_chart_does_not_overflow_horizontally(coach_page):
    page = coach_page
    page.wait_for_selector('[data-a="tab:roster"]')
    page.click('[data-a="tab:roster"]')
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('.load-chart-svg')
    overflow = page.evaluate(
        'document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1, f'horizontal overflow of {overflow}px'
