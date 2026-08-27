"""e2e coverage for the History tab.

Andrew's ask: "history - should show workouts completed with actual stats
and planned workout skipped." One reverse-chronological feed of both, where
"skipped" is DERIVED (a past planned session with no matching workout)
rather than read from `Session.status`, which nothing in the codebase
actually writes — see web/src/history.js's module docstring.

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
    page.wait_for_selector('[data-a="tab:history"]')
    page.click('[data-a="tab:history"]')
    page.wait_for_selector('.hist-section')


def test_history_tab_is_reachable_from_the_tab_bar(page):
    page.wait_for_selector('[data-a="tab:history"]')
    assert page.locator('[data-a="tab:history"]').count() == 1
    _open_history(page)
    assert 'History' in page.locator('[data-a="tab:history"]').text_content()


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
        pg.wait_for_selector('[data-a="tab:history"]')
        ctx.set_offline(True)
        try:
            pg.click('[data-a="tab:history"]')
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
            pg.wait_for_selector('[data-a="tab:history"]')
            pg.click('[data-a="tab:history"]')
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
