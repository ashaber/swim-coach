"""e2e coverage for the coach-mode Q&A build's Ask-the-coach feature (Part B):
asking a question about a planned session (Plan tab) or a completed workout
(Dashboard tab), and seeing that session/workout's own Ask-the-coach section
reflect a coach's reply. See web/src/views.js's renderAskCoachSection (the
shared component) and web/src/api.js's askAboutSession/askAboutWorkout (both
POST /api/feedback/questions -- backend/app/routes/feedback.py's
ask_question). The athlete's own durable Feedback TAB used to also show
this; it was retired (web/resources-tab-library-review) -- the data path
(state.feedbackEntries) is unchanged and still backs this section.

Same mocked-backend conventions as test_workout_detail.py/
test_plan_session_detail.py -- no real backend is ever contacted, every
network call is intercepted via Playwright routes with CORS headers
attached.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

BASE_URL = 'https://coach-api.test'
TOKEN = 'test-token-123'

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PLAN_LOAD_STUB = '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'

# A far-future week so src/plan.js's pickCurrentAndNextWeek reliably shows
# it regardless of the real wall clock the suite runs under -- same fixture
# convention test_plan_session_detail.py already established (verified
# there against isoWeekMonday's own algorithm).
ISO_WEEK = '2099-W01'
MONDAY = '2098-12-29'

PLANNED_SESSION = {
    'id': 's-planned', 'date': MONDAY, 'sport': 'swim_pool', 'source': 'ai_coach',
    'duration_min': 60, 'distance_m': 2200, 'intensity': {'zone': 'Z2'},
    'purpose': 'Aerobic base', 'structure': None, 'structured': None, 'status': 'planned',
}

PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []},
    'weeks': [{
        'iso_week': ISO_WEEK, 'meso_block': 'base', 'focus': 'aerobic base', 'target_volume_m': 8000,
        'sessions': [PLANNED_SESSION], 'adaptation_rationale': None,
    }],
})

COMPLETED_WORKOUT = {
    'id': 'w-done', 'date': '2026-06-01', 'sport': 'swim_ow', 'source': 'fit',
    'distance_m': 5000, 'duration_min': 95, 'avg_pace_s_per_100m': 114, 'rpe': 7,
    'notes': None, 'avg_hr': None, 'max_hr': None, 'analytics': None,
    'laps': [], 'lengths': [], 'pauses': [],
}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _questions_route(created_ref):
    """Mocks POST /api/feedback/questions -- echoes back a real-shaped
    Feedback row (id, the body/linkage the athlete just sent, and a fixed AI
    provisional answer), same "one-shot AI answer, persisted synchronously"
    contract the real route has (see backend/app/routes/feedback.py's
    ask_question doc comment). `created_ref` (a mutable list) records the
    request body so a test can assert what was actually sent."""
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        body = json.loads(route.request.post_data or '{}')
        created_ref.append(body)
        created = {
            'id': 'f-new',
            'type': 'question',
            'source': 'athlete',
            'body': body.get('body'),
            'status': 'open',
            'created_at': '2026-08-20T12:00:00Z',
            'workout_id': body.get('workout_id'),
            'session_date': body.get('session_date'),
            'session_sport': body.get('session_sport'),
            'needs_human_review': False,
            'ai_provisional_answer': 'Keep it aerobic -- Zone 2 the whole way.',
            'coach_reply': None,
        }
        route.fulfill(status=200, content_type='application/json', body=json.dumps(created), headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Signed in and configured (seed_identity + seed_settings, same
    convention as conftest.py's own base `page` fixture) -- every test in
    this file needs a real backend interaction (asking a question), unlike
    test_workout_detail.py/test_plan_session_detail.py's deliberately
    unconfigured default."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        seed_settings(ctx, {'baseUrl': BASE_URL, 'token': TOKEN, 'version': 2})
        ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
        ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
        ctx.route('**/api/workouts*', _cors_route(200, 'application/json', json.dumps([COMPLETED_WORKOUT])))
        ctx.route('**/api/grants*', _cors_route(200, 'application/json', '[]'))
        # maybeLoadRaceDebriefs fires GET /api/athlete on opening a session/workout detail
        # (race-debrief-interview build) -- unmocked, it's a real cross-origin fetch that
        # WebKit logs as a CORS console/page error even though app code catches it cleanly.
        ctx.route('**/api/athlete*', _cors_route(200, 'application/json', '{"race_debriefs": []}'))
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


def test_ask_a_question_on_a_planned_session_end_to_end(page):
    created_ref = []
    page.route('**/api/feedback/questions*', _questions_route(created_ref))
    page.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))

    page.wait_for_selector('[data-a="tab:plan"]')
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.click(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.wait_for_selector('#ask-coach')
    assert 'Nothing asked yet.' in page.content()

    page.fill('[data-form="askCoach"][data-field="body"]', 'How hard should this one feel?')
    page.click('[data-a="ask-coach:submit"]')

    page.wait_for_selector('text=Keep it aerobic -- Zone 2 the whole way.')
    content = page.content()
    assert 'How hard should this one feel?' in content
    assert 'AI provisional answer' in content
    # The request was linked by (session_date, session_sport), not workout_id.
    assert len(created_ref) == 1
    assert created_ref[0]['session_date'] == MONDAY
    assert created_ref[0]['session_sport'] == 'swim_pool'
    assert 'workout_id' not in created_ref[0]
    # The draft input is cleared after a successful submit.
    assert page.input_value('[data-form="askCoach"][data-field="body"]') == ''


# IDEA 016 removed the OLD workout-linked ask-coach path entirely: the completed-workout
# detail view's single-turn Feedback Q&A box is gone, replaced by the persisted three-party
# thread covered in test_workout_chat.py/test_coach_roster.py instead. The SESSION-linked path
# (renderAskCoachSection on a PLANNED session, tested above) is untouched -- this build never
# touched sessions -- so the "submit error keeps the draft" coverage below moved onto that
# still-real surface instead of being lost when the workout-linked test it used to ride on was
# deleted.


def test_submit_error_shows_inline_and_keeps_the_draft(page):
    page.route(
        '**/api/feedback/questions*',
        _cors_route(502, 'application/json', '{"error": "the coach could not answer that just now"}'),
    )
    page.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))

    page.wait_for_selector('[data-a="tab:plan"]')
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.click(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.wait_for_selector('#ask-coach')

    page.fill('[data-form="askCoach"][data-field="body"]', 'a question')
    page.click('[data-a="ask-coach:submit"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'the coach could not answer that just now' in page.locator('.conn-result.fail').inner_text()
    # The draft is preserved so the athlete can retry without retyping.
    assert page.input_value('[data-form="askCoach"][data-field="body"]') == 'a question'


def test_session_ask_coach_section_reflects_a_coach_reply(page):
    # The athlete's own durable Feedback tab used to also show this
    # (retired, web/resources-tab-library-review) -- the session-scoped
    # Ask-the-coach section (B1, renderAskCoachSection) is the one surface
    # left for it, so this asserts the same coach-reply-wins-over-AI
    # behavior there instead. Linked to PLANNED_SESSION by (session_date,
    # session_sport), the same linkage `feedbackForSession` (views.js)
    # filters on.
    entries = json.dumps([{
        'id': 'f1', 'type': 'question', 'source': 'athlete', 'body': 'How much fueling for this one?',
        'status': 'answered', 'created_at': '2026-08-20T12:00:00Z',
        'ai_provisional_answer': 'Aim for 60-90g carbs/hr.',
        'coach_reply': 'Start with 70g/hr and adjust from there.',
        'needs_human_review': False,
        'session_date': MONDAY, 'session_sport': 'swim_pool',
    }])
    page.route('**/api/feedback*', _cors_route(200, 'application/json', entries))

    page.wait_for_selector('[data-a="tab:plan"]')
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.click(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.wait_for_selector('#ask-coach')

    content = page.content()
    assert 'How much fueling for this one?' in content
    assert 'Your coach replied' in content
    assert 'Start with 70g/hr and adjust from there.' in content
    # The coach reply wins over the AI provisional answer once both exist.
    assert 'Aim for 60-90g carbs/hr.' not in content


def test_session_ask_coach_waiting_on_coach_state_when_flagged_for_review(page):
    entries = json.dumps([{
        'id': 'f1', 'type': 'question', 'source': 'athlete', 'body': 'Is this safe with my shoulder?',
        'status': 'open', 'created_at': '2026-08-20T12:00:00Z',
        'ai_provisional_answer': None, 'coach_reply': None, 'needs_human_review': True,
        'session_date': MONDAY, 'session_sport': 'swim_pool',
    }])
    page.route('**/api/feedback*', _cors_route(200, 'application/json', entries))

    page.wait_for_selector('[data-a="tab:plan"]')
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.click(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.wait_for_selector('#ask-coach')

    assert 'Waiting on your coach to reply.' in page.content()
