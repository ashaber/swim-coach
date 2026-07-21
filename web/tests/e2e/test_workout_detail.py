"""e2e coverage for the Log tab's workout detail view (Slice 2): tapping a
history row opens an in-tab detail view; a back action returns to the list.

Same mocked-backend conventions as test_workout_history.py -- no real
backend is ever contacted, every network call is intercepted via Playwright
routes with CORS headers attached, and the `page` fixture below mirrors
test_workout_history.py's own (signed in, not pre-configured with a
backend, /api/athlete stubbed).
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

# A rich .fit workout carrying laps + pauses + full analytics + avg/max HR --
# everything the detail view can render. Realistic shapes per
# engine/swim_coach/models.py's WorkoutLap/WorkoutPause/WorkoutAnalytics.
RICH_FIT_WORKOUT = {
    'id': 'w-rich', 'date': '2026-06-01', 'sport': 'swim_ow', 'source': 'fit',
    'distance_m': 5000, 'duration_min': 95, 'avg_pace_s_per_100m': 114, 'rpe': 7,
    'notes': 'Choppy back half, felt strong.',
    'avg_hr': 132, 'max_hr': 158,
    'analytics': {
        'cardiac_drift_pct': 6.4, 'split_label': 'positive',
        'first_half_pace_s_per_100m': 108, 'second_half_pace_s_per_100m': 120,
        'elapsed_min': 98, 'moving_min': 95, 'pause_total_min': 3, 'pause_count': 2,
        'swolf_first_quarter': 38.2, 'swolf_last_quarter': 44.9, 'swolf_degradation_pct': 17.5,
    },
    'laps': [
        {
            'index': 0, 'start_offset_s': 0, 'duration_s': 1830, 'distance_m': 2500,
            'avg_hr': 128, 'max_hr': 145, 'avg_pace_s_per_100m': 108,
            'stroke': 'freestyle', 'num_lengths': None,
        },
        {
            'index': 1, 'start_offset_s': 1830, 'duration_s': 1980, 'distance_m': 2500,
            'avg_hr': 136, 'max_hr': 158, 'avg_pace_s_per_100m': 120,
            'stroke': 'freestyle', 'num_lengths': None,
        },
    ],
    'lengths': [],
    'pauses': [
        {'start_offset_s': 754, 'duration_s': 45, 'source': 'gap'},
        {'start_offset_s': 2600, 'duration_s': 90, 'source': 'timer'},
    ],
}

# An old manual entry with none of laps/pauses/lengths/analytics -- proves
# the detail view still renders cleanly (summary stats only) for pre-.fit
# logged workouts.
BARE_MANUAL_WORKOUT = {
    'id': 'w-bare', 'date': '2025-11-02', 'sport': 'swim_pool', 'source': 'manual',
    'distance_m': 2000, 'duration_min': 40, 'avg_pace_s_per_100m': None, 'rpe': None,
    'notes': 'easy recovery', 'avg_hr': None, 'max_hr': None, 'analytics': None,
    'laps': [], 'lengths': [], 'pauses': [],
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
    """Same shape as test_workout_history.py's `page` fixture: signed in
    but deliberately not pre-configured with a backend, and /api/athlete
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
    """The '#settings-token' paste field is gone -- session tokens now come
    only from a real Google sign-in exchange (see identity.js's signIn /
    api.js's exchangeGoogleToken), which these tests don't drive (no real
    Google script). Seeds the session token directly into localStorage the
    way a real exchange would leave it (`version` stamped to match
    settings.js's SETTINGS_SCHEMA_VERSION, or loadSettings() would treat it
    as a stale pre-cutover value and drop it), then reloads and drives the
    real Settings UI for the base URL + Save button, same as before."""
    page.evaluate(
        "(t) => window.localStorage.setItem("
        "'swimcoach_settings', JSON.stringify({baseUrl: '', token: t, version: 2}))",
        token,
    )
    page.reload()
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('#settings-base-url')
    page.fill('#settings-base-url', base_url)
    page.click('[data-a="settings:save"]')


def _open_log_tab_with_workouts(page, workouts):
    page.route('**/api/workouts*', _cors_route(200, 'application/json', json.dumps(workouts)))
    _configure_backend(page)
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('.hist-row')


def test_open_detail_from_row_shows_all_sections(page):
    _open_log_tab_with_workouts(page, [RICH_FIT_WORKOUT])
    page.click('.hist-row')
    # Settled marker for the detail view -- the back button only exists there.
    page.wait_for_selector('[data-a="history:back"]')

    content = page.content()
    # Header: date/sport/source badge.
    assert 'Open water swim' in content
    assert 'fit' in content
    # Summary stats.
    assert '5 km' in content
    assert '1 h 35 min' in content
    assert '1:54 /100m' in content
    assert '7/10' in content
    assert '132 bpm' in content
    assert '158 bpm' in content
    # Full analytics block.
    assert 'drift +6.4% ⚠' in content
    assert 'positive split' in content
    assert 'SWOLF 38.2' in content
    assert '2 pauses · 3 min stopped' in content
    # Laps table.
    assert page.locator('table.laps-table').count() == 1
    assert page.locator('table.laps-table tbody tr').count() == 2
    # Pauses list (offset in h:mm:ss).
    assert '0:12:34' in content
    assert 'gap' in content
    assert 'timer' in content
    # Notes verbatim.
    assert 'Choppy back half, felt strong.' in content
    # The list itself is gone while in detail view.
    assert page.locator('[data-a="history:open"]').count() == 0


def test_back_returns_to_list(page):
    _open_log_tab_with_workouts(page, [RICH_FIT_WORKOUT])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')

    page.click('[data-a="history:back"]')
    page.wait_for_selector('.hist-row')
    assert page.locator('[data-a="history:back"]').count() == 0
    assert 'Open water swim' in page.content()  # back in the list row


def test_hardware_back_closes_detail_not_app(page):
    # Reproduces the athlete's second reported bug: opening a workout detail
    # and then pressing the phone's hardware/gesture back button used to
    # navigate the PWA away entirely (no in-app history entry existed for
    # the detail view) instead of just closing the detail. page.go_back()
    # is Playwright's proxy for that hardware/gesture back press.
    _open_log_tab_with_workouts(page, [RICH_FIT_WORKOUT])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')

    page.go_back()
    page.wait_for_selector('.hist-row')
    assert page.locator('[data-a="history:back"]').count() == 0
    assert 'Open water swim' in page.content()  # back in the list row
    # Prove the app didn't navigate away entirely -- the tab bar (and the
    # rest of the app chrome) must still be there, not a blank/exited page.
    assert page.locator('.tabbar').count() == 1
    assert page.locator('[data-a="tab:log"]').count() == 1


def test_bare_manual_workout_renders_without_analytics_or_laps_sections(page):
    _open_log_tab_with_workouts(page, [BARE_MANUAL_WORKOUT])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')

    content = page.content()
    assert 'Pool swim' in content
    assert '2 km' in content
    assert '40 min' in content
    assert 'easy recovery' in content
    assert page.locator('table.laps-table').count() == 0
    assert page.locator('.pauses-list').count() == 0
    assert page.locator('.detail-analytics-list').count() == 0


def test_detail_survives_a_background_render(page):
    # Toggling network state triggers main.js's updateOnlineState -> render()
    # while the Log tab is active (see TABS_SENSITIVE_TO_ONLINE_STATE) -- a
    # cheap way to force an unrelated full re-render and confirm the detail
    # view (fully state-driven) survives it, per the task brief.
    _open_log_tab_with_workouts(page, [RICH_FIT_WORKOUT])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')

    ctx = page.context
    ctx.set_offline(True)
    try:
        page.wait_for_function('() => !navigator.onLine')
        assert page.locator('[data-a="history:back"]').count() == 1
        assert 'Choppy back half, felt strong.' in page.content()
    finally:
        ctx.set_offline(False)
        page.wait_for_function('() => navigator.onLine')


def test_offline_mode_can_still_open_detail_from_already_loaded_history(page):
    # History is fetched once while online; going offline afterwards must
    # not block opening a detail view from what's already in state (no new
    # network call is made -- see views.js's module docstring).
    _open_log_tab_with_workouts(page, [RICH_FIT_WORKOUT])

    ctx = page.context
    ctx.set_offline(True)
    try:
        page.wait_for_function('() => !navigator.onLine')
        page.click('.hist-row')
        page.wait_for_selector('[data-a="history:back"]')
        assert 'Choppy back half, felt strong.' in page.content()
    finally:
        ctx.set_offline(False)


def test_reload_returns_to_list_without_errors(page):
    # A reload with settings already configured also re-triggers main.js's
    # unconditional init-time loadPlan() -- mock it too (same fix
    # test_coach_chat.py's test_active_tab_persists_across_reload needed),
    # otherwise the real (unmocked) fetch to the fake coach-api.test origin
    # surfaces as an uncaught page error the `page` fixture's teardown
    # would otherwise legitimately flag.
    page.route(
        '**/api/plan*',
        _cors_route(
            200, 'application/json',
            '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}',
        ),
    )
    _open_log_tab_with_workouts(page, [RICH_FIT_WORKOUT])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')

    page.reload()
    # Fresh in-memory state on reload -- workoutDetailId resets to null, so
    # the Log tab (persisted as the active tab via ACTIVE_TAB_KEY) lands back
    # on the list, not the detail view. The boot sequence now also lazily
    # loads history itself (see main.js's boot-time shouldLoadHistoryNow()
    # check) since the persisted active tab is 'log' and settings/identity
    # are already configured -- so the settled state here is the list
    # (re-fetched via the still-registered **/api/workouts* route), not the
    # idle/empty notice.
    page.wait_for_selector('.hist-row')
    assert page.locator('[data-a="history:back"]').count() == 0
    assert page.locator('table.laps-table').count() == 0
    assert 'Open water swim' in page.content()


def test_history_loads_at_boot_without_tab_switch(page):
    # Reproduces the athlete's first reported bug: reopening the PWA while
    # the Log tab was the last-active tab used to leave history stuck on
    # "idle" forever, because only a tab *switch* (setTab) ever triggered
    # loadHistory() -- and a page reload restores the persisted tab without
    # going through setTab at all. The whole point of this test is that
    # history must render WITHOUT clicking the Log tab again after reload.
    page.route(
        '**/api/plan*',
        _cors_route(
            200, 'application/json',
            '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}',
        ),
    )
    _open_log_tab_with_workouts(page, [RICH_FIT_WORKOUT])
    # active tab ('log') is now persisted in localStorage (ACTIVE_TAB_KEY),
    # same as the real app after any tab click -- see main.js's setTab.

    page.reload()
    # No `page.click('[data-a="tab:log"]')` here -- that's the whole point.
    # Settings/identity are already configured (persisted in localStorage
    # from _configure_backend), and the persisted active tab is 'log', so
    # the boot sequence itself must lazily load history.
    page.wait_for_selector('.hist-row')
    assert 'Open water swim' in page.content()
    assert page.locator('.tabbar').count() == 1


def test_detail_view_has_no_horizontal_overflow_on_narrow_viewport(page):
    # The laps table is the widest element in the detail view -- it must
    # scroll inside its own container, never the page itself, at the
    # narrowest viewport this suite covers (390x844 -- see conftest.BROWSERS).
    _open_log_tab_with_workouts(page, [RICH_FIT_WORKOUT])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')

    overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
    assert overflow <= 1, f'page overflows horizontally by {overflow}px'
