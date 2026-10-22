"""e2e for the scoped-thread bottom sheet on a planned session (Plan tab) and a logged workout
(Dashboard tab): a "Chat with coach" button pinned above the tab bar opens a full-screen sheet
over the dimmed page; the chat panel inside keeps the composer fixed at the bottom; closing (x,
Esc, device back) returns to the page at the same scroll position.

A planned session's thread is persisted server side (GET/PATCH /api/sessions/<id>/thread,
POST /api/chat with session_id); the old single-turn "Ask coach" Q&A rows arrive as the thread's
earlier messages. Same mocked-backend conventions as the rest of the suite: every network call is
intercepted with CORS headers attached.
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

# A far-future week so src/plan.js's pickCurrentAndNextWeek reliably shows it.
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
    'laps': [], 'lengths': [], 'pauses': [], 'chat_messages': [],
}


def _message(i, role, body):
    return {
        'id': f'm{i}', 'athlete_id': 'a', 'session_id': PLANNED_SESSION['id'], 'sender_role': role,
        'body': body, 'tool_trace': None, 'created_at': f'2026-10-20T08:{i:02d}:00Z',
    }


def _long_thread(n=14):
    out = []
    for i in range(n):
        out.append(_message(2 * i, 'athlete', f'question {i} about this session'))
        out.append(_message(2 * i + 1, 'ai_coach', f'Answer {i}. ' + 'A reasonably long reply that wraps. ' * 4))
    return out


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _thread_route(state):
    """GET/PATCH /api/sessions/<id>/thread over a mutable `state` dict."""
    def handler(route):
        request = route.request
        if request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        if request.method == 'PATCH':
            state['ai_muted'] = json.loads(request.post_data or '{}')['ai_muted']
            state.setdefault('patches', []).append(state['ai_muted'])
        route.fulfill(
            status=200, content_type='application/json', headers=CORS_HEADERS,
            body=json.dumps({'session_id': PLANNED_SESSION['id'], 'ai_muted': state['ai_muted'], 'messages': state['messages']}),
        )
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, service_workers='block')
        seed_identity(ctx)
        seed_settings(ctx, {'baseUrl': BASE_URL, 'token': TOKEN, 'version': 2})
        ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
        ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
        ctx.route('**/api/workouts*', _cors_route(200, 'application/json', json.dumps([COMPLETED_WORKOUT])))
        ctx.route('**/api/grants*', _cors_route(200, 'application/json', '[]'))
        ctx.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
        ctx.route('**/api/athlete*', _cors_route(200, 'application/json', '{"race_debriefs": []}'))
        pg = ctx.new_page()
        js_errors = []
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


def _open_session(page, messages=None, muted=False):
    state = {'messages': messages if messages is not None else [], 'ai_muted': muted}
    page.route(f'**/api/sessions/{PLANNED_SESSION["id"]}/thread*', _thread_route(state))
    page.wait_for_selector('[data-a="tab:plan"]')
    page.click('[data-a="tab:plan"]')
    page.wait_for_selector(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.click(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.wait_for_selector('.thread-btn')
    return state


def _open_sheet(page):
    page.click('[data-a="thread-sheet:open"]')
    page.wait_for_selector('.thread-sheet')


def test_session_detail_has_the_pinned_button_with_a_count_and_no_old_ask_box(page):
    _open_session(page, messages=[_message(0, 'athlete', 'first'), _message(1, 'ai_coach', 'reply')])
    page.wait_for_function("() => document.querySelector('.thread-btn-count')?.textContent === '2'")
    assert page.locator('#ask-coach').count() == 0
    assert page.locator('.thread-sheet').count() == 0
    box = page.locator('.thread-btn').bounding_box()
    tab = page.locator('.tabbar').bounding_box()
    assert box['y'] + box['height'] <= tab['y'] + 1 and box['height'] >= 44


def test_button_opens_the_sheet_over_a_dimmed_page_with_earlier_messages(page):
    _open_session(page, messages=[_message(0, 'athlete', 'How hard should this feel?'), _message(1, 'ai_coach', 'Keep it aerobic.')])
    _open_sheet(page)
    text = page.inner_text('.thread-sheet')
    assert 'this session only' in text.lower()
    assert 'How hard should this feel?' in text and 'Keep it aerobic.' in text
    sheet = page.locator('.thread-sheet').bounding_box()
    assert sheet['y'] == pytest.approx(36, abs=2) and sheet['y'] + sheet['height'] >= 843
    assert page.locator('.thread-backdrop').is_visible()
    assert page.locator('.thread-close').bounding_box()['height'] >= 44


def test_composer_stays_visible_with_a_long_thread(page):
    _open_session(page, messages=_long_thread())
    _open_sheet(page)
    m = page.evaluate("""() => {
      const l = document.getElementById('session-thread-messages');
      const c = document.querySelector('.thread-sheet .chat-composer').getBoundingClientRect();
      return { overflow: l.scrollHeight > l.clientHeight * 2, distance: l.scrollHeight - l.scrollTop - l.clientHeight,
               cTop: c.top, cBottom: c.bottom, inner: window.innerHeight, send: document.querySelector('[data-a="session-thread:send"]').getBoundingClientRect().height };
    }""")
    assert m['overflow'] and m['distance'] <= 80
    assert m['cBottom'] <= m['inner'] + 1 and m['cTop'] > 100 and m['send'] >= 44
    page.evaluate("() => { document.getElementById('session-thread-messages').scrollTop = 0; }")
    page.wait_for_timeout(80)
    assert page.locator('.thread-sheet .chat-composer').is_visible()


def test_closing_restores_the_page_scroll_position(page):
    _open_session(page)
    page.evaluate("() => { const s = document.createElement('div'); s.id = 'tall'; s.style.height = '3000px'; document.body.appendChild(s); }")
    page.evaluate("() => window.scrollTo(0, 400)")
    page.wait_for_timeout(100)
    before = page.evaluate("() => window.scrollY")
    assert before > 100
    _open_sheet(page)
    page.click('.thread-close')
    page.wait_for_selector('.thread-sheet-root', state='detached')
    page.wait_for_timeout(100)
    assert page.evaluate("() => window.scrollY") == pytest.approx(before, abs=2)
    assert page.locator('[data-a="session:back"]').count() >= 1  # still on the session detail


def test_device_back_closes_the_sheet_but_not_the_detail(page):
    _open_session(page)
    _open_sheet(page)
    page.go_back()
    page.wait_for_selector('.thread-sheet-root', state='detached')
    assert page.locator('.thread-btn').count() == 1
    assert page.locator('[data-a="session:back"]').count() >= 1


def test_escape_closes_the_sheet(page):
    _open_session(page)
    _open_sheet(page)
    page.keyboard.press('Escape')
    page.wait_for_selector('.thread-sheet-root', state='detached')
    assert page.locator('.thread-btn').count() == 1


def test_sending_streams_a_reply_scoped_to_the_session_and_sends_no_coach_tab_history(page):
    sent = []

    def chat_handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        sent.append(json.loads(route.request.post_data or '{}'))
        body = ('data: {"type":"text","text":"Go for three rounds."}\n\n'
                'data: {"type":"done","stop_reason":"end_turn"}\n\n')
        route.fulfill(status=200, content_type='text/event-stream', body=body, headers=CORS_HEADERS)

    page.route('**/api/chat', chat_handler)
    state = _open_session(page)
    _open_sheet(page)
    page.fill('#session-thread-input', 'how many rounds?')
    # The server persists both turns; the refetch after the stream shows them.
    state['messages'] = [_message(0, 'athlete', 'how many rounds?'), _message(1, 'ai_coach', 'Go for three rounds.')]
    page.click('[data-a="session-thread:send"]')
    page.wait_for_function("() => document.querySelector('.thread-sheet')?.textContent.includes('Go for three rounds.')")
    assert sent and sent[0]['session_id'] == PLANNED_SESSION['id']
    assert sent[0]['history'] == [] and sent[0]['message'] == 'how many rounds?'
    page.wait_for_function("() => document.querySelector('.thread-btn-count')?.textContent === '2'")


def test_mute_toggle_patches_the_thread(page):
    state = _open_session(page)
    _open_sheet(page)
    assert page.locator('[data-a="session-thread:mute-toggle"]').inner_text().strip() == 'Mute AI'
    page.click('[data-a="session-thread:mute-toggle"]')
    page.wait_for_selector('text=The AI coach is muted in this thread')
    assert state['patches'] == [True]
    assert page.locator('[data-a="session-thread:mute-toggle"]').inner_text().strip() == 'Unmute AI'


def test_offline_keeps_the_saved_thread_readable_and_disables_sending(page):
    _open_session(page, messages=[_message(0, 'athlete', 'saved question')])
    _open_sheet(page)
    ctx = page.context
    ctx.set_offline(True)
    try:
        page.wait_for_function('() => !navigator.onLine')
        page.wait_for_selector('.thread-sheet .chat-banner', timeout=5000)
        assert page.locator('[data-a="session-thread:send"]').is_disabled()
        assert 'saved question' in page.inner_text('.thread-sheet')
    finally:
        ctx.set_offline(False)


def test_workout_sheet_closes_with_device_back_and_stays_on_the_workout(page):
    page.wait_for_selector('[data-a="tab:dashboard"]')
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-row')
    page.click('.hist-row')
    page.wait_for_selector('[data-a="thread-sheet:open"]')
    _open_sheet(page)
    assert 'this workout only' in page.inner_text('.thread-sheet').lower()
    page.go_back()
    page.wait_for_selector('.thread-sheet-root', state='detached')
    assert page.locator('[data-a="history:back"]').count() == 1


def test_a_failed_thread_load_shows_a_message_not_an_uncaught_error(page):
    def failing(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=500, content_type='application/json', body='{"error": "boom"}', headers=CORS_HEADERS)

    page.route(f'**/api/sessions/{PLANNED_SESSION["id"]}/thread*', failing)
    page.wait_for_selector('[data-a="tab:plan"]')
    page.click('[data-a="tab:plan"]')
    page.click(f'[data-a="session:open"][data-id="{PLANNED_SESSION["id"]}"]')
    page.wait_for_selector('.thread-btn')
    _open_sheet(page)
    page.wait_for_selector("text=Couldn't load this chat")
    assert page.locator('#session-thread-input').count() == 1


def test_content_can_scroll_clear_of_the_pinned_button(page):
    page.wait_for_selector('[data-a="tab:dashboard"]')
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-row')
    page.click('.hist-row')
    page.wait_for_selector('.thread-btn')
    page.evaluate("() => { const s = document.createElement('div'); s.style.height = '2000px'; document.querySelector('.thread-btn-spacer').before(s); }")
    page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
    page.wait_for_timeout(100)
    gap = page.evaluate("""() => {
      const sp = document.querySelector('.thread-btn-spacer').getBoundingClientRect();
      const btn = document.querySelector('.thread-btn').getBoundingClientRect();
      return btn.top - sp.top;  // the spacer's top edge must sit above the button: content ends before it
    }""")
    assert gap >= 0
