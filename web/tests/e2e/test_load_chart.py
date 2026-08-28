"""e2e coverage for the CTL/ATL/TSB training-load chart (views.js's
renderLoadChart, fed by plan.js's ctlAtlTsbChartGeometry) plus its
resting-HR/HRV baseline-deviation cross-check (views.js's
renderWellnessBaselineDeviation, fed by plan.js's
describeWellnessBaselineDeviation) -- surfaces `backend/app/context.py`'s
`summarize_rollup` "ctl_atl_tsb" and "wellness_baseline_deviation" fields
directly to the frontend via the new `GET /api/plan/load` (athlete
self-access) and `GET /api/coach/athletes/{slug}/load` (coach access)
endpoints, on two surfaces sharing the same render function: the athlete's
own Dashboard tab (main.js's loadPlanLoad -- Build 1 of the wellness-
ingestion + training-dashboard plan relocated this chart off the Plan tab
and into the merged Log+History Dashboard tab) and the coach roster's
acting-as-athlete view (main.js's loadCoachLoad).

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
# A real, non-null wellness_baseline_deviation -- an elevated resting HR
# (bad) alongside a suppressed HRV (also bad, but opposite raw sign) so a
# single stub exercises both fields' "concerning" framing at once.
REAL_WELLNESS_DEVIATION = {'resting_hr_pct_deviation': 8.5, 'hrv_pct_deviation': -11.2}
NULL_WELLNESS_DEVIATION = {'resting_hr_pct_deviation': None, 'hrv_pct_deviation': None}

PLAN_LOAD_STUB = json.dumps({
    'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': REAL_SERIES,
    'wellness_baseline_deviation': REAL_WELLNESS_DEVIATION,
})
PLAN_LOAD_NULL_WELLNESS_STUB = json.dumps({
    'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': REAL_SERIES,
    'wellness_baseline_deviation': NULL_WELLNESS_DEVIATION,
})

COACH_IDENTITY = {'name': 'Andrew', 'athlete': 'andrew', 'role': 'coach', 'coachFor': ['renee']}
COACH_ATHLETES_STUB = json.dumps([{'slug': 'renee', 'name': 'Renee'}])
COACH_WORKOUTS_STUB = json.dumps([])
COACH_FEEDBACK_STUB = json.dumps([])
COACH_LOAD_STUB = json.dumps({
    'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': REAL_SERIES,
    'wellness_baseline_deviation': REAL_WELLNESS_DEVIATION,
})


def _make_ctx(pw, cfg, *, identity=None, plan_load_body=PLAN_LOAD_STUB, coach_load_body=COACH_LOAD_STUB):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx, identity=identity)
    seed_settings(ctx)
    ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
    ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', plan_load_body))
    # The athlete-self workouts feed (GET /api/workouts, main.js's
    # loadHistory) -- unlike the old Plan tab, the merged Dashboard tab
    # (Build 1) fetches this too the moment it's opened (_open_dashboard),
    # to build the completed+missed feed alongside the chart. Distinct from
    # `**/api/coach/athletes/renee/workouts*` below (the coach-side route,
    # a completely different endpoint path). Left unmocked before this,
    # every _open_dashboard visit fired a real, unmocked fetch to this
    # fake-origin backend -- normally swallowed quietly by api.js's own
    # try/catch, but WebKit can surface the resulting network/access-control
    # failure as an actual `pageerror` event once the page stays open long
    # enough for the slow real-network failure to land (e.g. a test that
    # clicks a disclosure and waits on a CSS transition) -- exactly the
    # intermittent `page` fixture teardown failure this mock fixes.
    ctx.route('**/api/workouts*', _cors_route(200, 'application/json', '[]'))
    ctx.route('**/api/coach/athletes/renee/workouts*', _cors_route(200, 'application/json', COACH_WORKOUTS_STUB))
    ctx.route('**/api/coach/athletes/renee/feedback*', _cors_route(200, 'application/json', COACH_FEEDBACK_STUB))
    ctx.route('**/api/coach/athletes/renee/load*', _cors_route(200, 'application/json', coach_load_body))
    ctx.route('**/api/coach/athletes*', _cors_route(200, 'application/json', COACH_ATHLETES_STUB))
    return browser, ctx


def _open_dashboard(page):
    """Navigates to the merged Dashboard tab (Build 1: Log+History) -- the
    chart's real home now, after moving off the Plan tab's default landing
    view."""
    page.wait_for_selector('[data-a="tab:dashboard"]')
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-section')


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Signed in as the athlete herself (renee), landing on the Plan tab
    (the chart itself now lives on the Dashboard tab -- see
    _open_dashboard)."""
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
def null_wellness_page(request, base_url):
    """Same as `page`, except `GET /api/plan/load` reports no wellness data
    (both `wellness_baseline_deviation` fields `null`) -- the normal state
    for an athlete who hasn't logged `resting_hr`/`hrv` recently."""
    cfg = request.param
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, plan_load_body=PLAN_LOAD_NULL_WELLNESS_STUB)
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


# --- Athlete's own Dashboard tab (Build 1 relocated the chart here) -----------

def test_chart_renders_on_the_dashboard_tab_with_real_mocked_data(page):
    _open_dashboard(page)
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


def test_chart_uses_an_independent_right_axis_for_atl_readability_fix(page):
    # Build 1's readability fix: CTL/TSB share the left axis, ATL plots
    # against its own independent right axis (the chart's math was verified
    # NOT buggy -- CTL's 42-day-EWMA range is just inherently tiny next to
    # ATL's 7-day-EWMA range on any real data, which made CTL look flat on
    # one shared axis). Assert the second axis's tick labels actually render
    # and are visually distinct (colored to match the ATL line).
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-svg')
    secondary_ticks = page.locator('.load-chart-axis-label-secondary')
    assert secondary_ticks.count() > 0
    content = page.content()
    assert 'right axis' in content.lower()
    assert 'left axis' in content.lower()


def test_wellness_baseline_deviation_renders_with_real_mocked_data(page):
    _open_dashboard(page)
    page.wait_for_selector('.wellness-baseline-deviation')
    content = page.content()
    assert 'Resting HR' in content
    assert 'HRV' in content
    assert '+8.5%' in content
    assert '-11.2%' in content
    # Both fields are "bad" here (elevated RHR, suppressed HRV) despite
    # opposite raw signs -- both rendered as concerning callouts.
    assert page.locator('.wellness-stat--concerning').count() == 2
    assert page.locator('.wellness-stat--no-data').count() == 0
    # The independent-cross-check framing is visible, not buried.
    assert 'independent' in content.lower()


def test_wellness_baseline_deviation_null_data_shows_honest_not_enough_data_state(null_wellness_page):
    page = null_wellness_page
    _open_dashboard(page)
    page.wait_for_selector('.wellness-baseline-deviation')
    content = page.content()
    # Honest per-field "not enough data" -- never a hidden element, never
    # a bare 0.0%.
    assert page.locator('.wellness-stat--no-data').count() == 2
    assert page.locator('.wellness-stat--concerning').count() == 0
    assert page.locator('.wellness-stat--good').count() == 0
    assert 'not enough data' in content.lower()
    assert '0.0%' not in content


def test_chart_is_not_buried_in_a_collapsed_section(page):
    # Task requirement: visible on load, not tucked inside an already-
    # collapsed <details> the way the glossary is.
    _open_dashboard(page)
    chart = page.locator('.load-chart-svg')
    chart.wait_for(state='visible')
    assert chart.is_visible()


def test_ctl_atl_tsb_trend_narrative_renders_prominently_below_the_chart(page):
    # views.js's renderCtlAtlTsbNarrative / plan.js's describeCtlAtlTsbTrend
    # -- the computed, athlete-specific "what the numbers say" guidance
    # this feature adds, quoting Andrew's own framing: "this is the useful
    # coach guidance below the load graph."
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-narrative')
    narrative = page.locator('.load-chart-narrative')
    assert narrative.is_visible()
    text = narrative.inner_text()
    # The heading renders visually uppercase (CSS text-transform), which
    # Playwright's inner_text reflects -- compare case-insensitively.
    assert 'what the numbers say' in text.lower()
    # REAL_SERIES spans only 22 days -- well short of the cold-start
    # threshold -- so the narrative must lead with that honesty caveat
    # rather than presenting an early trend at full confidence.
    assert 'provisional' in text.lower()
    assert 'CTL (fitness)' in text
    assert 'TSB (form)' in text


def test_methodology_caption_moved_behind_a_collapsed_by_default_disclosure(page):
    # Task requirement: the old always-visible methodology paragraph now
    # lives inside a native <details>, collapsed by default, with its
    # caveats still one click away rather than deleted.
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-methodology')
    details = page.locator('.load-chart-methodology')
    summary = details.locator('summary')
    note = details.locator('.load-chart-note')

    assert 'How this chart works' in summary.inner_text()
    assert details.get_attribute('open') is None
    assert not note.is_visible()

    summary.click()
    note.wait_for(state='visible')
    assert note.is_visible()
    assert 'not yet verified for swimming' in note.inner_text().lower()


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


def test_wellness_baseline_deviation_renders_on_the_coach_roster_view(coach_page):
    page = coach_page
    page.wait_for_selector('[data-a="tab:roster"]')
    page.click('[data-a="tab:roster"]')
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('.wellness-baseline-deviation')
    content = page.content()
    assert '+8.5%' in content
    assert '-11.2%' in content
    assert page.locator('.wellness-stat--concerning').count() == 2


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

def test_dashboard_tab_chart_does_not_overflow_horizontally(page):
    _open_dashboard(page)
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
