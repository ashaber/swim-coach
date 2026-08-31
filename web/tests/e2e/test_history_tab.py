"""e2e coverage for the merged Dashboard tab's feed (Build 1: Log+History).

Andrew's ask: "history - should show workouts completed with actual stats
and planned workout skipped." One reverse-chronological feed of both, where
"skipped" is DERIVED (a past planned session with no matching workout)
rather than read from `Session.status`, which nothing in the codebase
actually writes — see web/src/history.js's module docstring. This feed now
lives on the merged Dashboard tab (`tab:dashboard`, retiring the standalone
Log/History tabs) alongside the CTL/ATL/TSB load chart and the sync/manual-
entry actions -- see web/src/views.js's renderDashboardTab/
renderTrainingDashboardBody.

Stubs both halves the feed needs: `**/api/workouts*` (completed) and
`**/api/plan*` (the weeks skips are derived from), so the assertions don't
depend on real athlete data or on the wall clock.
"""

import json
from datetime import date, timedelta

import pytest
from playwright.sync_api import expect, sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

# Dates relative to "now" so the derivation's past/today/future rules are
# exercised for real, whenever the suite happens to run.
TODAY = date.today()
DONE_DAY = TODAY - timedelta(days=3)
MISSED_DAY = TODAY - timedelta(days=2)
REST_DAY = TODAY - timedelta(days=1)
FUTURE_DAY = TODAY + timedelta(days=2)


def _iso(d):
    return d.isoformat()


COMPLETED_WORKOUT = {
    'id': 'w-done', 'date': _iso(DONE_DAY), 'sport': 'swim_pool', 'source': 'fit',
    'distance_m': 2050, 'duration_min': 61.0, 'rpe': 6, 'avg_pace_s_per_100m': 95.0,
    'avg_hr': 142, 'max_hr': 165, 'planned_session_id': None, 'notes': None,
    'analytics': None, 'laps': [], 'pauses': [],
}

WORKOUTS_STUB = json.dumps([COMPLETED_WORKOUT])


def _session(sid, day, sport, purpose, duration=45.0, distance=None):
    return {
        'id': sid, 'date': _iso(day), 'sport': sport, 'source': 'ai_coach',
        'duration_min': duration, 'distance_m': distance, 'intensity': {},
        'purpose': purpose, 'structure': None, 'structured': None, 'status': 'planned',
    }


PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []},
    'weeks': [{
        'iso_week': '2026-W34', 'meso_block': 'base', 'focus': 'aerobic base',
        'target_volume_m': 12000, 'adaptation_rationale': None,
        'sessions': [
            # Matches COMPLETED_WORKOUT on date+sport -> completed, not skipped.
            _session('s-done', DONE_DAY, 'swim_pool', 'Threshold set', 60.0, 2000),
            # No workout -> the skip we expect to see.
            _session('s-missed', MISSED_DAY, 'strength', 'Dryland shoulder strength', 45.0),
            # Rest day -> never a skip (see SKIP_EXEMPT_SPORTS).
            _session('s-rest', REST_DAY, 'recovery', 'Mobility / full rest', 20.0),
            # Future -> not skipped yet.
            _session('s-future', FUTURE_DAY, 'swim_ow', 'Long open-water swim', 90.0, 4000),
        ],
    }],
})


# These are cross-origin GETs carrying an Authorization header, so the
# browser sends a CORS preflight first and WebKit enforces it strictly:
# without an OPTIONS answer the preflight fails and the real request never
# happens, so the stub silently never runs. Same handling (and header set) as
# test_workout_sync.py's `_cors_route`, which exists for exactly this reason.
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}


def _cors_json(body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=200, content_type='application/json',
                      body=body, headers=CORS_HEADERS)
    return handler


def _make_ctx(pw, cfg, *, workouts=WORKOUTS_STUB, plan=PLAN_STUB):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    # `service_workers='block'` matches test_workout_sync.py: the PWA's
    # service worker otherwise intercepts these fetches before Playwright's
    # route can, and under WebKit they escape to the real network.
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx)
    seed_settings(ctx)
    ctx.route('**/api/plan*', _cors_json(plan))
    # GET /api/plan/load fires unconditionally at boot alongside GET
    # /api/plan (main.js's loadPlanLoad) -- same CORS-preflight treatment.
    ctx.route('**/api/plan/load*', _cors_json('{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'))
    ctx.route('**/api/workouts*', _cors_json(workouts))
    # Coach-mode Q&A build: opening a workout detail now lazily fetches
    # GET /api/feedback (main.js's maybeLoadFeedback) so the new
    # Ask-the-coach section has data to filter -- unmocked, it fails on
    # CORS the moment any test in this file opens a detail view, the same
    # hazard every other route above already documents.
    ctx.route('**/api/feedback*', _cors_json('[]'))
    return browser, ctx


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, request.param)
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


def _open_history(page):
    page.wait_for_selector('[data-a="tab:dashboard"]')
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-section')


def test_history_tab_is_reachable_from_the_tab_bar(page):
    page.wait_for_selector('[data-a="tab:dashboard"]')
    assert page.locator('[data-a="tab:dashboard"]').count() == 1
    _open_history(page)
    assert 'Dashboard' in page.locator('[data-a="tab:dashboard"]').text_content()


def test_completed_workout_shows_its_actual_logged_stats(page):
    _open_history(page)
    page.wait_for_selector('.hist-row:not(.hist-row-skipped)')
    row = page.locator('.hist-row:not(.hist-row-skipped)').first.text_content()
    assert 'Pool swim' in row
    # The ACTUAL logged 2050m ("2.1 km"), not the plan's 2000m target.
    assert '2.1 km' in row
    assert 'RPE 6' in row


def test_skipped_planned_session_is_shown_and_clearly_marked(page):
    _open_history(page)
    page.wait_for_selector('.hist-row-skipped')
    skipped = page.locator('.hist-row-skipped')
    assert skipped.count() == 1
    text = skipped.first.text_content()
    assert 'Skipped' in text
    assert 'Strength' in text
    assert 'Dryland shoulder strength' in text  # what was planned


def test_rest_days_and_future_sessions_are_not_reported_as_skipped(page):
    _open_history(page)
    page.wait_for_selector('.hist-row')
    body = page.locator('.hist-section').text_content()
    assert 'Mobility / full rest' not in body  # recovery is exempt
    assert 'Long open-water swim' not in body  # still in the future


def test_feed_is_newest_first_with_the_skip_above_the_older_completed(page):
    _open_history(page)
    page.wait_for_selector('.hist-row')
    rows = page.locator('.hist-row').all_text_contents()
    assert len(rows) == 2
    assert 'Skipped' in rows[0]      # MISSED_DAY is more recent
    assert 'Pool swim' in rows[1]    # DONE_DAY is older


def test_completed_row_opens_a_detail_view_but_skipped_row_is_not_tappable(page):
    _open_history(page)
    page.wait_for_selector('.hist-row')
    # Only the completed row carries the open action.
    assert page.locator('[data-a="history:open"]').count() == 1
    assert page.locator('.hist-row-skipped[data-a="history:open"]').count() == 0

    page.click('[data-a="history:open"]')
    page.wait_for_selector('[data-a="history:back"]')
    detail = page.locator('.wrap').text_content()
    assert 'Distance' in detail
    assert 'Avg HR' in detail

    page.click('[data-a="history:back"]')
    page.wait_for_selector('.hist-row')
    assert page.locator('[data-a="history:open"]').count() == 1


def test_history_survives_a_reload(page, base_url):
    """The active tab is persisted (main.js's saveActiveTab), so a reload
    should land back on History with the same feed, per this repo's
    localStorage-persistence e2e standard."""
    _open_history(page)
    page.wait_for_selector('.hist-row-skipped')
    page.reload()
    page.wait_for_selector('.hist-row-skipped')
    assert page.locator('.hist-row').count() == 2


def test_history_tab_does_not_overflow_horizontally(page):
    """Seven tabs now share the bottom bar -- the mobile viewports this
    fixture runs (390x844 / 412x915) must not scroll sideways."""
    _open_history(page)
    page.wait_for_selector('.hist-row')
    overflow = page.evaluate(
        'document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1, f'horizontal overflow of {overflow}px'


@pytest.mark.parametrize('cfg', BROWSERS)
def test_history_offline_shows_a_connection_notice_rather_than_a_blank_tab(cfg, base_url):
    """Per this repo's e2e standard, the feature must behave sensibly with
    the network offline. With nothing cached, History can't derive anything
    -- it must say so rather than render an empty, unexplained tab."""
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg)
        pg = ctx.new_page()
        pg.goto(base_url)
        pg.wait_for_selector('[data-a="tab:dashboard"]')
        ctx.set_offline(True)
        try:
            pg.click('[data-a="tab:dashboard"]')
            pg.wait_for_selector('.hist-section')
            body = pg.locator('.hist-section').text_content()
            # Either the connection notice (nothing loaded) or a real feed
            # from cache -- never a silently blank section.
            assert body.strip(), 'History rendered an empty section while offline'
        finally:
            ctx.set_offline(False)
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_history_with_no_data_at_all_explains_itself(cfg, base_url):
    empty_plan = json.dumps({
        'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [],
        'macro': {'blocks': []}, 'weeks': [],
    })
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, workouts='[]', plan=empty_plan)
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            pg.wait_for_selector('[data-a="tab:dashboard"]')
            pg.click('[data-a="tab:dashboard"]')
            # `.hist-section` exists in BOTH the "Loading history…" and
            # settled states (see web/src/views.js's status=='loading'
            # branch), so a one-shot wait_for_selector()-then-text_content()
            # races the async plan/workouts fetch this test itself stubs --
            # it can read "Loading history…" before the stub resolves,
            # exactly the "waited for present, not for ready" gap
            # mtb-skills' reload_and_wait() was written to close for its own
            # WebKit reloads. `expect(...).to_contain_text()` polls/retries
            # until the settled text appears (or times out), so it's the
            # right replacement here even though this route stays this
            # test's -- no shared conftest reload helper needed since
            # there's no reload() in this flow.
            expect(pg.locator('.hist-section')).to_contain_text('Nothing logged or missed yet')
            assert pg.locator('.hist-row').count() == 0
        finally:
            ctx.close()
            browser.close()


# --- Folded in from the retired test_workout_history.py (the old, capped,
# completed-only Log-tab history section) -- coverage that isn't a straight
# duplicate of anything above: real analytics-line rendering, error/retry,
# the sync/manual-entry actions refreshing the feed, actions' offline
# behavior, and a dense-row overflow stress test. See the Build 1 e2e-impact
# table: "real restructuring -- fold any non-duplicate coverage into
# test_history_tab.py, delete the rest as superseded."

EMPTY_PLAN = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [],
})

# Real fixture data: andrew's 2026-07-09 cross_train (rich analytics, no
# distance since it's not a swim) and his 2026-03-14 swim_pool (SWOLF
# example).
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


@pytest.mark.parametrize('cfg', BROWSERS)
def test_dashboard_renders_workouts_including_analytics_line(cfg, base_url):
    workouts = json.dumps([CROSS_TRAIN_WORKOUT, POOL_SWIM_WORKOUT, OLD_MANUAL_WORKOUT])
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, workouts=workouts, plan=EMPTY_PLAN)
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            _open_history(pg)
            pg.wait_for_selector('.hist-row')
            content = pg.content()
            # Sport labels for all three, including cross_train's label --
            # with its sport_detail pretty suffix (MTB, from raw
            # "cycling/mountain").
            assert 'Cross-train · MTB' in content
            assert 'Pool swim' in content
            # The cross_train workout's cardiac-drift analytics line.
            assert 'drift -13.8%' in content
            # The pool swim's SWOLF analytics line (real andrew fixture numbers).
            assert 'SWOLF 41.0' in content
            assert '43.4' in content
            assert '+6.0%' in content
            assert pg.locator('.hist-row').count() == 3
            assert 'RPE 6' in content
        finally:
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_dashboard_shows_error_and_retry_on_workouts_fetch_failure(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, workouts='[]', plan=EMPTY_PLAN)
        pg = ctx.new_page()
        js_errors: list[str] = []
        pg.on('pageerror', lambda e: js_errors.append(str(e)))

        def failing_workouts(route):
            if route.request.method == 'OPTIONS':
                route.fulfill(status=204, headers=CORS_HEADERS)
                return
            route.fulfill(status=500, content_type='application/json', body='{"error": "boom"}', headers=CORS_HEADERS)

        ctx.route('**/api/workouts*', failing_workouts)
        pg.goto(base_url)
        try:
            pg.wait_for_selector('[data-a="tab:dashboard"]')
            pg.click('[data-a="tab:dashboard"]')
            pg.wait_for_selector('[data-a="history:retry"]')
            assert "Couldn't load your training history" in pg.content()

            # Retry re-fetches; make it succeed this time.
            ctx.route('**/api/workouts*', _cors_json(json.dumps([OLD_MANUAL_WORKOUT])))
            pg.click('[data-a="history:retry"]')
            pg.wait_for_selector('.hist-row')
            assert 'Pool swim' in pg.content()
        finally:
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_dashboard_actions_refresh_feed_after_a_successful_manual_log_submit(cfg, base_url):
    """The Dashboard tab's sync/manual-entry actions (ported verbatim from
    the original Log tab) still work once relocated, and a successful
    manual save refreshes the merged feed to include it (main.js's
    handleSubmitLog calling loadHistory())."""
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

    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, workouts='[]', plan=EMPTY_PLAN)
        pg = ctx.new_page()
        ctx.route('**/api/workouts*', workouts_handler)
        pg.goto(base_url)
        try:
            pg.wait_for_selector('[data-a="tab:dashboard"]')
            pg.click('[data-a="tab:dashboard"]')
            pg.wait_for_selector('.hist-section:has-text("Nothing logged or missed yet")')

            # Phase 3: the manual form is collapsed behind a secondary
            # toggle ("Sync from watch" is the primary action) -- expand it
            # before filling.
            pg.click('[data-a="log:toggle-manual"]')
            pg.wait_for_selector('[data-form="log"][data-field="distance_m"]')
            pg.fill('[data-form="log"][data-field="distance_m"]', '3000')
            pg.fill('[data-form="log"][data-field="duration_min"]', '60')
            pg.click('[data-a="log:submit"]')

            pg.wait_for_selector('.conn-result.ok')
            pg.wait_for_selector('.hist-row')
            assert 'Pool swim' in pg.content()
        finally:
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_dashboard_still_loads_offline_with_a_quiet_feed_notice(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, workouts='[]', plan=EMPTY_PLAN)
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            pg.wait_for_selector('[data-a="tab:dashboard"]')
            ctx.set_offline(True)
            # Wait for the app's own online/offline listener (main.js's
            # updateOnlineState) to actually observe the transition before
            # navigating -- otherwise there's a race where the Dashboard
            # tab click lands while state.online is still stale `true`,
            # and the app would attempt (and fail) a real fetch instead of
            # skipping it quietly.
            pg.wait_for_function('() => !navigator.onLine')
            pg.click('[data-a="tab:dashboard"]')
            pg.wait_for_selector('.hist-section')
            # The primary sync action is disabled offline (Phase 3) -- and
            # the manual form still renders fine once expanded; the feed
            # just quietly declines to claim "nothing logged" when it never
            # fetched.
            assert pg.locator('[data-a="sync:start"]').is_disabled()
            pg.click('[data-a="log:toggle-manual"]')
            pg.wait_for_selector('[data-form="log"][data-field="distance_m"]')
            assert pg.locator('[data-form="log"][data-field="distance_m"]').count() == 1
            content = pg.content()
            assert 'reconnect' in content.lower()
            assert 'Nothing logged or missed yet' not in content
        finally:
            ctx.set_offline(False)
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_dashboard_feed_has_no_horizontal_overflow_with_dense_analytics_row(cfg, base_url):
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
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, workouts=json.dumps([dense_workout]), plan=EMPTY_PLAN)
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            _open_history(pg)
            pg.wait_for_selector('.hist-row')
            overflow = pg.evaluate('document.documentElement.scrollWidth - window.innerWidth')
            assert overflow <= 1, f'page overflows horizontally by {overflow}px'
        finally:
            ctx.close()
            browser.close()
