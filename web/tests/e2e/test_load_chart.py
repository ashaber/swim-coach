"""e2e coverage for the two-panel CTL/ATL/TSB training-load chart (web/
two-panel-load-chart -- views.js's renderLoadChart, fed by plan.js's
ctlAtlTsbChartGeometry) plus its resting-HR/HRV baseline-deviation
cross-check (views.js's renderWellnessBaselineDeviation, fed by plan.js's
describeWellnessBaselineDeviation) -- surfaces `backend/app/context.py`'s
`summarize_rollup` "ctl_atl_tsb" and "wellness_baseline_deviation" fields
directly to the frontend via the new `GET /api/plan/load` (athlete
self-access) and `GET /api/coach/athletes/{slug}/load` (coach access)
endpoints, on two surfaces sharing the same render function: the athlete's
own Dashboard tab (main.js's loadPlanLoad) and the coach roster's
acting-as-athlete view (main.js's loadCoachLoad).

Two-panel rebuild: CTL and ATL now share one 0-anchored axis in a top
panel; TSB gets its own fixed-domain panel below, self-labeled reference
bands, a zero line, a one-line plain-text verdict, window-selector pills,
and (on the athlete's own Dashboard only) the wellness cross-check moved
out to the Check-in tab instead of rendering inline here -- see
test_checkin.py for that half of the resolved-decision coverage.

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
# GET /api/coach/athletes/renee/plan (Build 2's new coach-plan route) --
# main.js's loadCoachPlan fires unconditionally the moment an athlete is
# selected (handleSelectCoachedAthlete), alongside workouts/feedback/load,
# regardless of which roster sub-tab is active. Left unmocked, every
# roster:select-athlete click in this file would fire a real, unmocked fetch
# against this fake-origin backend -- exactly the intermittent WebKit-only
# `page` fixture teardown failure the `**/api/workouts*` mock above already
# had to fix once tonight.
COACH_PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [],
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
    ctx.route('**/api/coach/athletes/renee/plan*', _cors_route(200, 'application/json', COACH_PLAN_STUB))
    ctx.route('**/api/coach/athletes*', _cors_route(200, 'application/json', COACH_ATHLETES_STUB))
    return browser, ctx


def _open_dashboard(page):
    """Navigates to the merged Dashboard tab (Build 1: Log+History) -- the
    chart's real home now, after moving off the Plan tab's default landing
    view."""
    page.wait_for_selector('[data-a="tab:dashboard"]')
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-section')


def _open_checkin(page):
    """Navigates to the Check-in tab -- opens the Dashboard tab FIRST so
    `state.planLoad` (main.js's loadPlanLoad) actually has data by the time
    Check-in renders (web/two-panel-load-chart's resolved decision: the
    Check-in tab reuses that already-fetched state rather than firing its
    own GET /api/plan/load -- see views.js's renderCheckinTab doc
    comment)."""
    _open_dashboard(page)
    page.click('[data-a="tab:checkin"]')
    page.wait_for_selector('[data-form="checkin"][data-field="date"]')


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


# --- Athlete's own Dashboard tab: two-panel chart -----------------------------

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
    # Both reference bands (race-ready, productive training), self-labeled
    # inline (design spec 3.2) and honestly captioned in the methodology.
    assert page.locator('.load-chart-band').count() == 2
    assert page.locator('.load-chart-band-race').count() == 1
    assert page.locator('.load-chart-band-productive').count() == 1
    assert 'productive' in content.lower()
    assert 'race-ready' in content.lower()
    assert 'cycling' in content.lower()
    assert 'not a swim-specific or peer-reviewed target' in content.lower()
    # The provisional-time-constant honesty caveat.
    assert 'not yet verified for swimming' in content.lower()


def test_chart_is_two_panels_with_a_shared_x_axis_and_no_dual_axis_leftovers(page):
    # web/two-panel-load-chart: CTL/ATL now share ONE axis (top panel); the
    # old dual-axis readability fix (a second, independently-scaled ATL
    # axis) is retired entirely -- its markup must be gone.
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-svg')
    assert page.locator('.load-chart-axis-label-secondary').count() == 0
    content = page.content()
    assert 'right axis' not in content.lower()
    assert 'left axis' not in content.lower()
    # TSB's own panel gets a zero line and the two unnamed-zone edge labels.
    assert page.locator('.load-chart-zero-line').count() == 1
    assert 'transitional' in content.lower()
    assert 'high risk' in content.lower()


def test_chart_shows_a_one_line_verdict_and_the_currently_occupied_band_is_emphasized(page):
    # Design spec 3.6: the single most useful line on the panel, directly
    # under the chart. REAL_SERIES' last point is TSB 25.0 -- inside the
    # race-ready band.
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-verdict')
    verdict = page.locator('.load-chart-verdict').inner_text()
    assert 'race-ready' in verdict.lower()
    assert 'Form' in verdict
    # The race-ready band (the one the athlete is actually in) is the one
    # bumped to higher opacity, not the productive band.
    assert page.locator('.load-chart-band-race.load-chart-band-active').count() == 1
    assert page.locator('.load-chart-band-productive.load-chart-band-active').count() == 0


def test_chart_has_a_three_way_window_selector_defaulting_to_6_weeks(page):
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-window-controls')
    pills = page.locator('.load-chart-window-controls .subtab-btn')
    assert pills.count() == 3
    texts = [pills.nth(i).inner_text() for i in range(3)]
    assert texts == ['6 weeks', '12 weeks', 'Season']
    assert 'active' in pills.nth(0).get_attribute('class')


def test_selecting_a_different_window_switches_the_active_pill_and_re_renders_the_chart(page):
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-window-controls')
    page.click('[data-a="load-chart:window:season"]')
    page.wait_for_selector('[data-a="load-chart:window:season"].active')
    assert 'active' not in page.locator('[data-a="load-chart:window:42"]').get_attribute('class')
    # Chart still renders (didn't break on the window switch).
    assert page.locator('.load-chart-svg').count() == 1


def test_wellness_baseline_deviation_no_longer_renders_inline_on_the_athletes_own_dashboard(page):
    # Resolved decision (web/two-panel-load-chart): moved to the Check-in
    # tab instead -- see test_log_checkin.py's own coverage of that half.
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-svg')
    assert page.locator('.wellness-baseline-deviation').count() == 0


def test_wellness_baseline_deviation_renders_on_the_checkin_tab_with_real_mocked_data(page):
    _open_checkin(page)
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


def test_wellness_baseline_deviation_null_data_shows_honest_not_enough_data_state_on_checkin(null_wellness_page):
    page = null_wellness_page
    _open_checkin(page)
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


def test_ctl_atl_tsb_trend_narrative_is_truncated_to_first_line_with_a_more_toggle(page):
    # views.js's renderCtlAtlTsbNarrative / plan.js's describeCtlAtlTsbTrend
    # -- the computed, athlete-specific "what the numbers say" guidance
    # this feature adds, quoting Andrew's own framing: "this is the useful
    # coach guidance below the load graph." Design spec 3.6: only the first
    # line shows by default now that the verdict line carries the headline.
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-narrative')
    narrative = page.locator('.load-chart-narrative')
    assert narrative.is_visible()
    text = narrative.inner_text()
    assert 'what the numbers say' in text.lower()
    # REAL_SERIES spans only 22 days -- well short of the cold-start
    # threshold -- so the narrative must lead with that honesty caveat
    # rather than presenting an early trend at full confidence.
    assert 'provisional' in text.lower()
    assert 'CTL (fitness)' not in text  # behind "more" still

    more_button = page.locator('.load-chart-narrative-more')
    more_button.click()
    page.wait_for_selector('.load-chart-narrative-more', state='detached')
    expanded_text = narrative.inner_text()
    assert 'CTL (fitness)' in expanded_text
    assert 'TSB (form)' in expanded_text


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
    assert page.locator('.load-chart-band').count() == 2


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


def test_window_control_pills_fit_on_one_line_at_mobile_widths(page):
    # Task requirement: the three pills fit without wrapping awkwardly at
    # both mandated mobile viewports (this fixture's own 390x844/412x915,
    # see conftest.py's BROWSERS). All three sharing the same bounding-box
    # top y is proof they're on one row, not wrapped onto two.
    _open_dashboard(page)
    page.wait_for_selector('.load-chart-window-controls')
    pills = page.locator('.load-chart-window-controls .subtab-btn')
    tops = [pills.nth(i).bounding_box()['y'] for i in range(3)]
    assert max(tops) - min(tops) < 2, f'window pills wrapped onto multiple lines: {tops}'
