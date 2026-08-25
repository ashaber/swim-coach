"""e2e coverage for coach mode Phase 1's "My Athletes" (roster) tab --
the coach-side view: list the athletes who've granted this signed-in
identity coach access, then that athlete's logged workouts (each with a
nested planned-vs-actual `compliance` object, see
engine/swim_coach/compliance.py) and durable feedback log, with a reply box
for entries that don't have a coach_reply yet.

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

ATHLETES_STUB = json.dumps([{'slug': 'renee', 'name': 'Renee'}])

WORKOUT_STUB = json.dumps([{
    'id': 'w1', 'date': '2026-08-20', 'sport': 'swim_pool', 'source': 'fit',
    'distance_m': 2100, 'duration_min': 47.0, 'rpe': 6, 'avg_pace_s_per_100m': 95.0,
    'avg_hr': None, 'max_hr': None, 'notes': None, 'analytics': None, 'laps': [], 'pauses': [],
    'compliance': {
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
    ctx.route('**/api/coach/athletes/renee/workouts*', _cors_route(200, 'application/json', WORKOUT_STUB))
    ctx.route('**/api/coach/athletes/renee/feedback/f1', _reply_handler(reply_calls))
    ctx.route('**/api/coach/athletes/renee/feedback*', _cors_route(200, 'application/json', FEEDBACK_STUB))
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
    page.wait_for_selector('[data-a="roster:back"]')

    content = page.content()
    # Workout row: sport, distance/duration, and the nested compliance line
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

    page.wait_for_selector('text=Start with 70g/hr and adjust from there.')
    assert len(reply_calls) == 1
    assert reply_calls[0] == {'coach_reply': 'Start with 70g/hr and adjust from there.'}
    # The reply box is gone now that a coach_reply exists on the entry.
    assert page.locator('[data-form="roster-reply"]').count() == 0


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
