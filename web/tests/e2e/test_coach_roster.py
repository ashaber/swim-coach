"""e2e coverage for coach mode Phase 1's "My Athletes" (roster) tab --
the coach-side view: list the athletes who've granted this signed-in
identity coach access, then that athlete's logged workouts (each with a
nested planned-vs-actual `quality` object, see
engine/swim_coach/quality.py -- named `quality`, not `compliance`, to avoid
colliding with the engine's other, authoritative weekly-aggregate
`compliance` number; see IDEAS.md's resolved IDEA 006) and durable feedback
log, with a reply box for entries that don't have a coach_reply yet.

Deliberately scoped to the roster surface only (see the branch brief) --
the direct-to-coach chat UI and the workout-comment box are a separate,
later piece and are NOT covered here.

Same mocked-backend / CORS-preflight conventions as test_history_tab.py:
these are cross-origin GETs/PATCHes carrying an Authorization header, so
WebKit enforces a strict CORS preflight even against a mocked response.
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

# The signed-in identity coaching 'renee' -- coach mode Phase 1's `coachFor`
# field (see identity.js's loadIdentity / signIn, which fills this in from
# GET /api/me after the Google exchange in the real flow -- seeded directly
# here, same as every other e2e test seeds a resolved identity).
COACH_IDENTITY = {'name': 'Andrew', 'athlete': 'andrew', 'role': 'coach', 'coachFor': ['renee']}
NO_GRANTS_IDENTITY = {'name': 'Andrew', 'athlete': 'andrew', 'role': 'athlete', 'coachFor': []}

PLAN_STUB = json.dumps({
    'slug': 'andrew', 'athlete': {'name': 'Andrew'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [],
})
PLAN_LOAD_STUB = json.dumps({'athlete': 'andrew', 'weeks': 12, 'ctl_atl_tsb': []})

# The coach roster's own training-load chart data -- a real, non-empty
# series so test_coach_roster's assertions can prove the chart actually
# renders (see the "training load chart" tests below), not just that the
# workouts/feedback lists still work.
COACH_LOAD_STUB = json.dumps({
    'athlete': 'renee', 'weeks': 12,
    'ctl_atl_tsb': [
        ['2026-08-18', 10.0, 8.0, 2.0],
        ['2026-08-19', 10.5, 7.0, 3.5],
        ['2026-08-20', 11.0, 6.5, 4.5],
    ],
})

ATHLETES_STUB = json.dumps([{'slug': 'renee', 'name': 'Renee'}])

# GET /api/coach/athletes/renee/plan (Build 2's new coach-plan route) --
# main.js's loadCoachPlan fires unconditionally the moment an athlete is
# selected, feeding the Training Plan sub-tab's weeks/macro sections and the
# Workouts + Dashboard sub-tab's skip-derivation. A real macro block + one
# planned-but-never-done session so this file's Training Plan and
# missed-session-derivation tests have something real to assert against.
ROSTER_PLAN_STUB = json.dumps({
    'slug': 'renee', 'name': 'Renee', 'athlete': {'name': 'Renee'}, 'events': [],
    'macro': {
        'blocks': [{
            'name': 'Base', 'start_date': '2026-08-01', 'end_date': '2026-08-31',
            'weekly_volume_target_m': 15000,
        }],
    },
    'weeks': [{
        'iso_week': '2026-W33',
        'focus': 'Base building', 'target_volume_m': 2000,
        'sessions': [{
            'id': 'sess-1', 'date': '2026-08-10', 'sport': 'swim_pool',
            'duration_min': 45, 'distance_m': 2000, 'status': 'planned',
            # `purpose` is a required Session field in the real engine
            # (classifySession/deriveSessionTitle -- views.js's
            # renderSession/renderWeeksSection -- read it unconditionally,
            # no optional-chaining) -- must be present here too, or the
            # Training Plan sub-tab throws while rendering this fixture.
            'purpose': 'Aerobic base',
        }],
    }],
})

WORKOUT_STUB = json.dumps([{
    'id': 'w1', 'date': '2026-08-20', 'sport': 'swim_pool', 'source': 'fit',
    'distance_m': 2100, 'duration_min': 47.0, 'rpe': 6, 'avg_pace_s_per_100m': 95.0,
    'avg_hr': None, 'max_hr': None, 'notes': None, 'analytics': None, 'laps': [], 'pauses': [],
    'quality': {
        'matched': True, 'distance_delta_pct': 5.2, 'duration_delta_pct': -2.1,
        'intensity_match': 'unknown', 'quality_summary': 'No notable quality flags.',
    },
}])

FEEDBACK_STUB = json.dumps([{
    'id': 'f1', 'type': 'question', 'source': 'athlete',
    'body': 'How much fueling for a 4hr swim?', 'status': 'open',
    'created_at': '2026-08-20T12:00:00Z', 'needs_human_review': False,
    'ai_provisional_answer': 'Aim for 60-90g carbs/hr.', 'coach_reply': None,
}])

REPLIED_FEEDBACK = {
    'id': 'f1', 'type': 'question', 'source': 'athlete',
    'body': 'How much fueling for a 4hr swim?', 'status': 'answered',
    'created_at': '2026-08-20T12:00:00Z', 'needs_human_review': False,
    'ai_provisional_answer': 'Aim for 60-90g carbs/hr.',
    'coach_reply': 'Start with 70g/hr and adjust from there.',
}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _make_ctx(pw, cfg, *, identity=COACH_IDENTITY, reply_calls=None):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx, identity=identity)
    seed_settings(ctx)
    ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
    # GET /api/plan/load fires unconditionally at boot alongside GET
    # /api/plan (main.js's loadPlanLoad) -- same CORS-preflight treatment.
    ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
    ctx.route('**/api/coach/athletes/renee/workouts*', _cors_route(200, 'application/json', WORKOUT_STUB))
    ctx.route('**/api/coach/athletes/renee/feedback/f1', _reply_handler(reply_calls))
    ctx.route('**/api/coach/athletes/renee/feedback*', _cors_route(200, 'application/json', FEEDBACK_STUB))
    # GET /api/coach/athletes/renee/load -- the roster tab's own training-load
    # chart fetch (main.js's loadCoachLoad, fired once an athlete is selected;
    # see views.js's renderLoadChart). Registered before the broad
    # '**/api/coach/athletes*' route below so both can coexist (Playwright
    # matches the more specific, longer-path pattern -- '*' never crosses a
    # '/', same rule test_coach_grants_settings.py's _route_grants relies on).
    ctx.route('**/api/coach/athletes/renee/load*', _cors_route(200, 'application/json', COACH_LOAD_STUB))
    # GET /api/coach/athletes/renee/plan (Build 2) -- fires unconditionally
    # the moment an athlete is selected (main.js's loadCoachPlan), same
    # unmocked-route hazard as every other coach-athletes/renee/* route here.
    ctx.route('**/api/coach/athletes/renee/plan*', _cors_route(200, 'application/json', ROSTER_PLAN_STUB))
    ctx.route('**/api/coach/athletes*', _cors_route(200, 'application/json', ATHLETES_STUB))
    return browser, ctx


def _reply_handler(reply_calls):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        if route.request.method == 'PATCH':
            if reply_calls is not None:
                reply_calls.append(json.loads(route.request.post_data))
            route.fulfill(
                status=200, content_type='application/json',
                body=json.dumps(REPLIED_FEEDBACK), headers=CORS_HEADERS,
            )
            return
        route.fulfill(status=200, content_type='application/json', body=FEEDBACK_STUB, headers=CORS_HEADERS)
    return handler


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


def _open_roster(page):
    page.wait_for_selector('[data-a="tab:roster"]')
    page.click('[data-a="tab:roster"]')
    page.wait_for_selector('.hist-section')


# --- Tab visibility: only shown when coachFor is non-empty ------------------

def test_roster_tab_shown_when_identity_has_coach_grants(page):
    page.wait_for_selector('.tabbar')
    assert page.locator('[data-a="tab:roster"]').count() == 1


@pytest.mark.parametrize('cfg', BROWSERS)
def test_roster_tab_absent_when_identity_has_no_coach_grants(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, identity=NO_GRANTS_IDENTITY)
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            pg.wait_for_selector('.tabbar')
            assert pg.locator('[data-a="tab:roster"]').count() == 0
        finally:
            ctx.close()
            browser.close()


# --- Athlete list + selection -------------------------------------------------

def test_roster_lists_coached_athletes(page):
    _open_roster(page)
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    assert 'Renee' in page.content()


def test_selecting_athlete_shows_workouts_with_compliance_and_feedback(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    # `roster:back` renders synchronously as soon as an athlete is selected,
    # before the workouts/feedback fetches resolve (each is a separate async
    # load, see main.js's loadCoachWorkouts/loadCoachFeedback) -- wait for
    # markers that only exist once each has actually rendered, or this races
    # under slow/cold CI runners.
    page.wait_for_selector('[data-a="roster:open-workout"]')
    page.wait_for_selector('[data-form="roster-reply"]')

    content = page.content()
    # Workout row: sport, distance/duration, and the nested quality line
    # rendered plainly.
    assert 'Pool swim' in content
    assert '2.1 km' in content
    assert '+5.2%' in content
    assert 'unknown intensity' in content
    assert 'No notable quality flags.' in content

    # Feedback entry: body + AI provisional answer, no coach_reply yet so a
    # reply box is present.
    assert 'How much fueling for a 4hr swim?' in content
    assert 'Aim for 60-90g carbs/hr.' in content
    assert page.locator('[data-form="roster-reply"]').count() == 1


def test_back_button_returns_to_the_athlete_list(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:back"]')
    page.click('[data-a="roster:back"]')
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    assert page.locator('[data-a="roster:back"]').count() == 0


# --- Workout detail click-through ---------------------------------------------

def test_clicking_a_workout_opens_its_read_only_detail_view(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:open-workout"]')
    page.click('[data-a="roster:open-workout"]')
    page.wait_for_selector('[data-a="roster:close-workout"]')

    content = page.content()
    assert 'Pool swim' in content
    assert '2.1 km' in content
    # No embedded "ask your coach" chat -- that's an athlete-only feature.
    assert 'Ask your coach about this workout' not in content
    # The honest, non-functional coach-conversation placeholder (Build 2) IS
    # shown here -- distinct from the athlete-only AI chat just excluded.
    assert page.locator('#coach-conversation').count() == 1
    assert 'coming soon' in content
    # The workouts/feedback list sections are gone while the detail is open.
    assert page.locator('[data-a="roster:open-workout"]').count() == 0
    assert page.locator('[data-a="roster:back"]').count() == 0


def test_closing_workout_detail_returns_to_the_workouts_and_feedback_lists(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:open-workout"]')
    page.click('[data-a="roster:open-workout"]')
    page.wait_for_selector('[data-a="roster:close-workout"]')
    page.click('[data-a="roster:close-workout"]')
    page.wait_for_selector('[data-a="roster:back"]')

    assert page.locator('[data-a="roster:open-workout"]').count() == 1
    assert 'How much fueling for a 4hr swim?' in page.content()


def test_hardware_back_closes_workout_detail_not_the_app(page):
    # Mirrors test_workout_detail.py's test_hardware_back_closes_detail_not_app
    # for the Log tab's own workout-detail view: opening a coached athlete's
    # workout from the roster used to have no in-app history entry at all
    # (see main.js's handleOpenCoachWorkoutDetail before this fix), so a
    # hardware/gesture back press navigated the PWA away entirely instead of
    # just closing the detail. page.go_back() is Playwright's proxy for that
    # hardware/gesture back press.
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:open-workout"]')
    page.click('[data-a="roster:open-workout"]')
    page.wait_for_selector('[data-a="roster:close-workout"]')

    page.go_back()
    page.wait_for_selector('[data-a="roster:open-workout"]')
    assert page.locator('[data-a="roster:close-workout"]').count() == 0
    assert 'How much fueling for a 4hr swim?' in page.content()
    # Prove the app didn't navigate away entirely -- the tab bar (and the
    # rest of the app chrome) must still be there, not a blank/exited page.
    assert page.locator('.tabbar').count() == 1
    assert page.locator('[data-a="tab:roster"]').count() == 1


# --- Replying to feedback -----------------------------------------------------

def test_replying_to_feedback_patches_and_updates_the_row(page):
    reply_calls = []
    page.context.route(
        '**/api/coach/athletes/renee/feedback/f1', _reply_handler(reply_calls),
    )
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-form="roster-reply"]')

    page.fill('[data-form="roster-reply"]', 'Start with 70g/hr and adjust from there.')
    page.click('[data-a="roster:reply-submit"]')

    # The still-open form's own textarea already contains this exact text
    # (via `fill`), so waiting on it as a `text=` selector can match before
    # the async PATCH resolves -- wait for the form itself to be replaced
    # instead, which only happens once the reply lands.
    page.wait_for_selector('[data-form="roster-reply"]', state='detached')
    assert 'Start with 70g/hr and adjust from there.' in page.content()
    assert len(reply_calls) == 1
    assert reply_calls[0] == {'coach_reply': 'Start with 70g/hr and adjust from there.'}
    # The reply box is gone now that a coach_reply exists on the entry.
    assert page.locator('[data-form="roster-reply"]').count() == 0


# --- Sub-tabs (Build 2: Conversations / Workouts + Dashboard / Training Plan) -

def test_sub_tab_bar_shows_all_three_options(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:subtab:dashboard"]')
    assert page.locator('[data-a="roster:subtab:conversations"]').count() == 1
    assert page.locator('[data-a="roster:subtab:dashboard"]').count() == 1
    assert page.locator('[data-a="roster:subtab:plan"]').count() == 1


def test_defaults_to_workouts_and_dashboard_sub_tab(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:open-workout"]')
    assert 'active' in page.locator('[data-a="roster:subtab:dashboard"]').get_attribute('class')


def test_conversations_sub_tab_shows_an_honest_non_functional_placeholder(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:subtab:conversations"]')
    page.click('[data-a="roster:subtab:conversations"]')
    page.wait_for_selector('text=coming soon')

    content = page.content()
    assert 'Conversations' in content
    # Not wired to anything -- no real workouts/feedback content or actions.
    assert page.locator('[data-a="roster:open-workout"]').count() == 0
    assert page.locator('[data-a="roster:reply-submit"]').count() == 0
    assert page.locator('[data-a="roster:subtab:conversations"]').get_attribute('class').find('active') != -1


def test_training_plan_sub_tab_shows_weeks_and_macro_without_the_load_chart(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:subtab:plan"]')
    page.click('[data-a="roster:subtab:plan"]')
    # The macro block from ROSTER_PLAN_STUB -- `.macro .ph` (the block-name
    # element), not a generic `text=Base` locator: that substring also
    # matches the week's "focus" ("Base building") and the session's
    # "purpose" ("Aerobic base"), one copy of which sits inside the
    # collapsed-by-default `<details class="all-weeks">` accordion (the
    # planned week here is in the past relative to "today", so it renders
    # only via that accordion, not the This-week/Next-week cards) -- an
    # ambiguous locator can resolve to a non-visible element there and hang
    # `wait_for_selector`'s default visible-state wait forever.
    page.wait_for_selector('.macro .ph')

    content = page.content()
    # The planned session from ROSTER_PLAN_STUB, inside the all-weeks
    # accordion (it's in the past relative to "today", so it isn't a
    # This-week/Next-week card) -- renderSession's day-row title is derived
    # from the session's `purpose` text, not its sport label, so "Aerobic
    # base" (not "Pool swim") is what actually appears here.
    assert 'Aerobic base' in content
    assert 'Base building' in content  # the week's `focus`
    # No load chart in this sub-tab -- that stays in Workouts + Dashboard.
    assert page.locator('svg').count() == 0


def test_workouts_and_dashboard_sub_tab_shows_missed_sessions_now_that_plan_data_exists(page):
    """Build 2's whole point for this sub-tab: the new coach-plan endpoint
    means missed (skipped) sessions can now be derived on the coach side too,
    not just completed workouts (Build 1's deliberately narrower scope)."""
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:open-workout"]')
    assert 'Skipped' in page.content()


def test_switching_sub_tabs_and_back_preserves_the_athlete_context(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:subtab:plan"]')
    page.click('[data-a="roster:subtab:plan"]')
    page.wait_for_selector('.macro .ph')
    page.click('[data-a="roster:subtab:dashboard"]')
    page.wait_for_selector('[data-a="roster:open-workout"]')
    assert 'Renee' in page.content()


# --- Offline / mobile viewport standards --------------------------------------

@pytest.mark.parametrize('cfg', BROWSERS)
def test_roster_offline_shows_a_notice_rather_than_a_blank_tab(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg)
        pg = ctx.new_page()
        pg.goto(base_url)
        pg.wait_for_selector('[data-a="tab:roster"]')
        ctx.set_offline(True)
        try:
            pg.click('[data-a="tab:roster"]')
            pg.wait_for_selector('.hist-section')
            body = pg.locator('.hist-section').text_content()
            assert body.strip(), 'Roster tab rendered an empty section while offline'
        finally:
            ctx.set_offline(False)
            ctx.close()
            browser.close()


def test_roster_tab_does_not_overflow_horizontally(page):
    _open_roster(page)
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:back"]')
    overflow = page.evaluate(
        'document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1, f'horizontal overflow of {overflow}px'
