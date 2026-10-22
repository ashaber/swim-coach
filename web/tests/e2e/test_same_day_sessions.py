"""e2e: a race day with TWO same-sport sessions (a warm-up ride and the race ride). Both render as
tiles ordered warm-up first, each opens its own detail, the race tile carries the Checklist button,
and ask-the-coach posts the right `session_id` (sessions are addressed by id, not date + sport).

Same mocked-backend conventions as test_ask_coach.py -- no real backend is contacted.
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

ISO_WEEK = '2099-W01'
RACE_DAY = '2099-01-02'  # the Friday of 2099-W01 (Monday is 2098-12-29)


def _ride(session_id, kind, purpose, minutes):
    return {
        'id': session_id, 'date': RACE_DAY, 'sport': 'bike', 'source': 'ai_coach', 'kind': kind,
        'duration_min': minutes, 'distance_m': None, 'intensity': {'zone': 'Z2'},
        'purpose': purpose, 'structure': None, 'structured': None, 'status': 'planned',
    }


WARM = _ride('s-warm', 'warmup', 'Warm-up spin before the start', 30)
RACE = _ride('s-race', 'race', 'Criterium race', 60)

PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []},
    'weeks': [{
        'iso_week': ISO_WEEK, 'meso_block': 'race', 'focus': 'race day', 'target_volume_m': 0,
        # race listed BEFORE the warm-up on purpose: the view must order them, not trust list order
        'sessions': [RACE, WARM], 'adaptation_rationale': None,
    }],
})


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _thread_route(threads):
    """GET /api/sessions/<id>/thread over a dict {session_id: [messages]}."""
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        sid = route.request.url.split('/api/sessions/')[1].split('/')[0]
        route.fulfill(
            status=200, content_type='application/json', headers=CORS_HEADERS,
            body=json.dumps({'session_id': sid, 'ai_muted': False, 'messages': threads.get(sid, [])}),
        )
    return handler


def _chat_route(sent, threads):
    """POST /api/chat: streams a reply and persists the exchange into `threads`, as the backend does,
    so the post-send thread refetch still shows it."""
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        payload = json.loads(route.request.post_data or '{}')
        sent.append(payload)
        sid = payload.get('session_id')
        threads.setdefault(sid, []).extend([
            _message(sid, payload.get('message'), 'athlete'),
            _message(sid, 'Spin easy for twenty minutes.', 'ai_coach'),
        ])
        body = ('data: {"type":"text","text":"Spin easy for twenty minutes."}\n\n'
                'data: {"type":"done","stop_reason":"end_turn"}\n\n')
        route.fulfill(status=200, content_type='text/event-stream', body=body, headers=CORS_HEADERS)
    return handler


def _message(sid, body, role='athlete'):
    return {'id': f'm-{sid}-{role}', 'athlete_id': 'a', 'session_id': sid, 'sender_role': role, 'body': body,
            'tool_trace': None, 'created_at': '2099-01-01T12:00:00Z'}


def _open_thread(page):
    page.wait_for_selector('.thread-btn')
    page.click('[data-a="thread-sheet:open"]')
    page.wait_for_selector('#session-thread-input')


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
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
        ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'))
        ctx.route('**/api/workouts*', _cors_route(200, 'application/json', '[]'))
        ctx.route('**/api/grants*', _cors_route(200, 'application/json', '[]'))
        ctx.route('**/api/athlete*', _cors_route(200, 'application/json', '{"race_debriefs": []}'))
        pg = ctx.new_page()
        js_errors: list[str] = []
        pg.on('pageerror', lambda e: js_errors.append(str(e)))
        pg.goto(base_url)
        try:
            yield pg
            real_errors = [e for e in js_errors
                           if 'sw.js load failed' not in e and 'Importing a module script failed' not in e]
            assert not real_errors, f'Uncaught JS errors: {real_errors}'
        finally:
            ctx.close()
            browser.close()


def _open_plan(page):
    page.wait_for_selector('[data-a="tab:plan"]')
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector('[data-a="session:open"][data-id="s-race"]')


def test_both_rides_render_warmup_first(page):
    page.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
    _open_plan(page)
    ids = page.eval_on_selector_all(
        f'.day-row:has([data-id="s-race"]) [data-a="session:open"]', 'els => els.map(e => e.dataset.id)')
    assert ids == ['s-warm', 's-race']
    # Only the race tile offers the checklist.
    assert page.locator('[data-a="raceday:open"]').count() == 1
    assert page.locator('[data-a="raceday:open"]').get_attribute('data-id') == 's-race'


def test_each_ride_opens_its_own_detail(page):
    page.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
    _open_plan(page)
    page.click('[data-a="session:open"][data-id="s-warm"]')
    page.wait_for_selector('.thread-btn')
    assert 'Warm-up spin before the start' in page.content()
    page.click('[data-a="session:back"]')
    page.wait_for_selector('[data-a="session:open"][data-id="s-race"]')
    page.click('[data-a="session:open"][data-id="s-race"]')
    page.wait_for_selector('.thread-btn')
    assert 'Criterium race' in page.content()


@pytest.mark.parametrize('session_id', ['s-warm', 's-race'])
def test_session_chat_posts_the_right_session_id(page, session_id):
    sent, threads = [], {}
    page.route('**/api/sessions/*/thread*', _thread_route(threads))
    page.route('**/api/chat', _chat_route(sent, threads))
    page.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
    _open_plan(page)
    page.click(f'[data-a="session:open"][data-id="{session_id}"]')
    _open_thread(page)
    page.fill('#session-thread-input', 'How should I ride this?')
    page.click('[data-a="session-thread:send"]')
    page.wait_for_selector('text=Spin easy for twenty minutes.')
    assert len(sent) == 1
    assert sent[0]['session_id'] == session_id
    assert sent[0]['history'] == []


def test_a_question_asked_about_the_race_does_not_show_on_the_warmup(page):
    page.route('**/api/sessions/*/thread*', _thread_route({'s-race': [_message('s-race', 'Gearing for the crit?')]}))
    page.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
    _open_plan(page)
    page.click('[data-a="session:open"][data-id="s-warm"]')
    _open_thread(page)
    assert 'Gearing for the crit?' not in page.content()
    page.click('.thread-close')
    page.wait_for_selector('.thread-sheet-root', state='detached')
    page.click('[data-a="session:back"]')
    page.click('[data-a="session:open"][data-id="s-race"]')
    page.wait_for_function("() => document.querySelector('.thread-btn-count')?.textContent === '1'")
    _open_thread(page)
    assert 'Gearing for the crit?' in page.content()
