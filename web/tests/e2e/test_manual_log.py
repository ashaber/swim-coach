"""e2e coverage for the Dashboard tab's manual-log-entry section ("Log
manually / upload a file", Phase 3's secondary action alongside "Sync from
watch") and the Dashboard chart's inline wellness-deviation cross-check.

Split out of the former test_log_checkin.py (web/resources-tab-library-
review): that file mixed this still-live Dashboard-tab coverage with the
now-removed Check-in tab's own tests. The wellness-deviation cross-check
used to be moved OUT of this chart and into the Check-in tab instead; now
that tab is gone, it stays inline here again (see views.js's
renderTrainingDashboardBody / renderLoadChart doc comments and
test_resources.py for the Check-in-tab-is-gone assertions).

Same mocked-backend conventions as test_coach_chat.py (see its `page`
fixture docstring for why the service worker is blocked here): no real
backend is ever contacted, and every network call is intercepted via
Playwright routes with CORS headers attached.
"""

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

PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'
PLAN_LOAD_STUB = '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'
# A real, non-null wellness_baseline_deviation -- proves real values reach
# the Dashboard chart inline (see module docstring above).
PLAN_LOAD_WITH_WELLNESS_STUB = (
    '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[["2026-08-01",40.0,38.0,2.0]],'
    '"wellness_baseline_deviation":{"resting_hr_pct_deviation":6.5,"hrv_pct_deviation":-9.0}}'
)


def _set_range_value(page, selector, value):
    """Playwright's `fill()` doesn't support `<input type="range">` -- set
    the value directly and dispatch a real `input` event (bubbling, so
    main.js's delegated `onAppInput` listener on #app picks it up), the same
    event a manual slider drag fires."""
    page.eval_on_selector(
        selector,
        "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); }",
        value,
    )


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Seeds a signed-in identity (past the Phase 2.5 sign-in gate) but
    deliberately NOT a configured backend -- the "unconfigured" test below
    needs that empty state.

    Also mocks a default `GET /api/athlete` response -- the Settings tab's
    profile-edit section fetches it as soon as `_configure_backend` lands
    back on that tab. test_profile_edit.py covers that section's own
    behavior.

    Likewise mocks a default empty `GET /api/workouts` -- opening the
    Dashboard tab while configured fires that fetch for the history
    section (see main.js's loadHistory), and unmocked it fails against
    this file's fake backend origin, which WebKit reports as an uncaught
    pageerror that trips this fixture's teardown assertion. Registered at
    the *context* level so the submit tests' own page.route(...) handlers
    still take precedence."""
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
        ctx.route('**/api/grants*', _cors_route(200, 'application/json', '[]'))
        ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
        ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
        ctx.route('**/api/workouts*', _cors_route(200, 'application/json', '[]'))
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
    """Seeds baseUrl + session token directly into localStorage (settings.js's
    storage schema -- `version` must match SETTINGS_SCHEMA_VERSION), then
    reloads so main.js's boot picks it up. Always ends on the Settings tab."""
    page.evaluate(
        "(cfg) => window.localStorage.setItem("
        "'swimcoach_settings', JSON.stringify({baseUrl: cfg.baseUrl, token: cfg.token, version: 2}))",
        {'baseUrl': base_url, 'token': token},
    )
    page.reload()
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')


def _open_manual_log(page):
    """Opens the Dashboard tab, waits for the feed's fetch to settle, then
    expands the secondary "Log manually / upload a file" section (collapsed
    by default -- see main.js's state.logManualOpen) before waiting for a
    form field, so a fill()/click() below never races a detached
    pre-toggle node."""
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-section')
    page.click('[data-a="log:toggle-manual"]')
    page.wait_for_selector('[data-form="log"][data-field="date"]')


def test_dashboard_tab_shows_backend_needed_notice_when_unconfigured(page):
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.chat-empty')
    assert 'backend URL and token' in page.content()


def test_dashboard_tab_shows_sync_button_when_configured(page):
    _configure_backend(page)
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('[data-a="sync:start"]')
    assert 'Sync from watch' in page.content()


def test_manual_log_renders_form_fields_when_configured(page):
    _configure_backend(page)
    _open_manual_log(page)
    assert page.locator('[data-form="log"][data-field="sport"]').count() == 1
    assert page.locator('[data-form="log"][data-field="distance_m"]').count() == 1
    assert page.locator('[data-form="log"][data-field="duration_min"]').count() == 1
    assert page.locator('[data-form="log"][data-field="rpe"]').count() == 1


def test_log_rpe_slider_uses_the_cr10_zero_to_ten_scale(page):
    # A6a: the old bare slider was min="1" -- 0 ("Rest / Nothing at all") is
    # now a legitimate response (library/19-srpe-protocol.md's Foster CR-10
    # scale), not an unreachable floor.
    _configure_backend(page)
    _open_manual_log(page)
    rpe_slider = page.locator('[data-form="log"][data-field="rpe"]')
    assert rpe_slider.get_attribute('min') == '0'
    assert rpe_slider.get_attribute('max') == '10'


def test_log_rpe_slider_shows_the_live_cr10_anchor_caption(page):
    _configure_backend(page)
    _open_manual_log(page)
    _set_range_value(page, '[data-form="log"][data-field="rpe"]', '0')
    assert 'Rest / Nothing at all' in page.content()
    _set_range_value(page, '[data-form="log"][data-field="rpe"]', '6')
    # 6 is deliberately unanchored in Foster's own published scale -- an
    # em-dash, never fabricated text.
    assert '—' in page.content()


def test_manual_log_submit_success_shows_saved_and_resets_form(page):
    page.route('**/api/workouts*', _cors_route(200, 'application/json', '{"id": "w1", "date": "2026-07-07"}'))

    _configure_backend(page)
    _open_manual_log(page)
    page.fill('[data-form="log"][data-field="distance_m"]', '3000')
    page.fill('[data-form="log"][data-field="duration_min"]', '60')
    page.fill('[data-form="log"][data-field="notes"]', 'felt smooth')
    page.click('[data-a="log:submit"]')

    page.wait_for_selector('.conn-result.ok')
    assert 'Saved' in page.locator('.conn-result').inner_text()
    # Form resets to defaults after a successful save.
    assert page.input_value('[data-form="log"][data-field="distance_m"]') == ''


def test_manual_log_submit_failure_shows_error_message(page):
    page.route('**/api/workouts*', _cors_route(422, 'application/json', '{"error": "invalid sport"}'))

    _configure_backend(page)
    _open_manual_log(page)
    page.fill('[data-form="log"][data-field="distance_m"]', '3000')
    page.fill('[data-form="log"][data-field="duration_min"]', '60')
    page.click('[data-a="log:submit"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'invalid sport' in page.locator('.conn-result').inner_text()


# --- Dashboard chart's inline wellness cross-check (web/resources-tab-library-review) ---
# The Check-in tab used to hold this block instead; now that it's gone,
# showWellnessInline reverts to its `true` default on the Dashboard chart.

def test_dashboard_chart_shows_the_wellness_cross_check_inline(page):
    page.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_WITH_WELLNESS_STUB))
    _configure_backend(page)
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.wellness-baseline-deviation')
    content = page.content()
    assert '+6.5%' in content
    assert '-9.0%' in content
