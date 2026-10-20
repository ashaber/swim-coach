"""e2e for the Coach tab's full-height chat panel (src/chatPanel.js): the composer is fixed at the
bottom above the tab bar, only the message list scrolls, a streaming reply follows the reader only
while they are at the bottom, and sending scrolls to the bottom.

The chat backend is a REAL local HTTP server that streams SSE chunks on demand (a Playwright
`route.fulfill` can only answer with the whole body at once, which cannot show what happens
BETWEEN deltas). Every other endpoint the app touches at boot is mocked the way
test_coach_chat.py does it.
"""

import http.server
import json
import threading

import pytest
from playwright.sync_api import sync_playwright

from conftest import seed_identity

TOKEN = 'test-token-123'
VIEWPORTS = [
    pytest.param({'width': 390, 'height': 844}, id='390x844'),
    pytest.param({'width': 412, 'height': 915}, id='412x915'),
]
ENGINES = [pytest.param('chromium', id='chromium'), pytest.param('webkit', id='webkit')]

CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}
PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'
PLAN_LOAD_STUB = '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'


def _json_route(body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS)
        else:
            route.fulfill(status=200, content_type='application/json', body=body, headers=CORS)
    return handler


class StreamingChatServer:
    """POST /api/chat answers with an SSE stream whose chunks are released one at a time by the
    test (`release(n)`); everything else is a 404 JSON with CORS headers."""

    def __init__(self):
        self.gate = threading.Semaphore(0)
        self.chunks = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _cors(self):
                for k, v in CORS.items():
                    self.send_header(k, v)

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.end_headers()

            def do_GET(self):
                self.send_response(404)
                self._cors()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"error":"not mocked"}')

            def do_POST(self):
                length = int(self.headers.get('Content-Length') or 0)
                self.rfile.read(length)
                if not self.path.startswith('/api/chat'):
                    self.do_GET()
                    return
                self.send_response(200)
                self._cors()
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                for i, chunk in enumerate(outer.chunks):
                    if i > 0 and not outer.gate.acquire(timeout=20):
                        return
                    self.wfile.write(f'data: {json.dumps(chunk)}\n\n'.encode())
                    self.wfile.flush()

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_address[1]}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def script(self, chunks):
        self.chunks = chunks

    def release(self, n=1):
        for _ in range(n):
            self.gate.release()

    def close(self):
        self.gate.release(50)
        self.httpd.shutdown()
        self.httpd.server_close()


def _long_thread(n=24):
    messages = []
    for i in range(n):
        messages.append({'role': 'user', 'content': f'question number {i} about my training', 'status': 'done'})
        messages.append({
            'role': 'assistant', 'status': 'done',
            'content': f'Answer {i}. ' + 'Here is a fairly long explanation of the week that wraps across lines. ' * 3,
        })
    return {'messages': messages, 'expertMode': False}


# A stand-in for window.visualViewport that a test can shrink to emulate the on-screen keyboard.
FAKE_VISUAL_VIEWPORT = """
(() => {
  const target = new EventTarget();
  const fake = Object.assign(target, { height: window.innerHeight, offsetTop: 0, width: window.innerWidth });
  Object.defineProperty(window, 'visualViewport', { configurable: true, value: fake });
  window.__fakeVV = fake;
})();
"""


@pytest.fixture
def server():
    srv = StreamingChatServer()
    yield srv
    srv.close()


@pytest.fixture(params=ENGINES)
def engine(request):
    return request.param


@pytest.fixture(params=VIEWPORTS)
def viewport(request):
    return request.param


@pytest.fixture
def chat_page(engine, viewport, server, base_url):
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, engine).launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f'{engine} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=viewport, service_workers='block')
        seed_identity(ctx)
        ctx.add_init_script(
            "window.localStorage.setItem('swimcoach_settings', JSON.stringify("
            f"{{baseUrl: '{server.url}', token: '{TOKEN}', version: 2}}));"
            "window.localStorage.setItem('swimcoach_active_tab', 'coach');"
            f"window.localStorage.setItem('swimcoach_chat_renee', {json.dumps(json.dumps(_long_thread()))});"
        )
        ctx.add_init_script(FAKE_VISUAL_VIEWPORT)
        for pattern, body in (
            ('**/api/athlete*', '{"slug": "renee", "name": "Renee"}'),
            ('**/api/grants*', '[]'),
            ('**/api/plan*', PLAN_STUB),
            ('**/api/plan/load*', PLAN_LOAD_STUB),
        ):
            ctx.route(pattern, _json_route(body))
        page = ctx.new_page()
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.goto(base_url)
        page.wait_for_selector('#chat-messages')
        try:
            yield page
            real = [e for e in errors if 'sw.js load failed' not in e and 'Importing a module script failed' not in e]
            assert not real, f'Uncaught JS errors: {real}'
        finally:
            ctx.close()
            browser.close()


def _metrics(page):
    return page.evaluate("""() => {
      const list = document.getElementById('chat-messages');
      const box = (sel) => { const e = document.querySelector(sel); if (!e) return null;
        const r = e.getBoundingClientRect(); return { top: r.top, bottom: r.bottom, height: r.height }; };
      return {
        top: list.scrollTop, height: list.scrollHeight, client: list.clientHeight,
        distance: list.scrollHeight - list.scrollTop - list.clientHeight,
        composer: box('.chat-composer'), tabbar: box('.tabbar'), head: box('.chat-panel-head'),
        listBox: box('#chat-messages'), send: box('[data-a="chat:send"]'), input: box('#chat-input'),
        pageScroll: document.scrollingElement.scrollTop,
        pageOverflow: document.scrollingElement.scrollHeight - window.innerHeight,
        inner: window.innerHeight,
      };
    }""")


def _scroll_list_to(page, top):
    page.evaluate("(t) => { document.getElementById('chat-messages').scrollTop = t; }", top)
    page.wait_for_timeout(60)  # let the scroll event reach ChatScroll


def _send(page, text):
    page.fill('#chat-input', text)
    page.click('[data-a="chat:send"]')


def _bubble_text(page):
    return page.evaluate("""() => {
      const rows = document.querySelectorAll('#chat-messages .chat-row.coach .chat-bubble');
      return rows.length ? rows[rows.length - 1].textContent : '';
    }""")


def test_composer_is_fixed_above_the_tab_bar_with_a_long_thread(chat_page):
    m = _metrics(chat_page)
    assert m['height'] > m['client'] * 2, 'the thread should overflow the list'
    assert m['distance'] <= 80, 'opens scrolled to the latest message'
    # Composer fully on screen, sitting directly above the tab bar; the page itself never scrolls.
    assert 0 <= m['composer']['top'] and m['composer']['bottom'] <= m['tabbar']['top'] + 1
    assert m['tabbar']['bottom'] <= m['inner'] + 1
    assert m['pageOverflow'] <= 1 and m['pageScroll'] == 0
    # Header band on top, list between header and composer.
    assert m['head']['top'] <= 1
    assert m['listBox']['top'] >= m['head']['bottom'] - 1 and m['listBox']['bottom'] <= m['composer']['top'] + 1
    # Touch targets.
    assert m['send']['height'] >= 44 and m['input']['height'] >= 44


def test_composer_stays_visible_and_pinned_after_scrolling_the_list(chat_page):
    before = _metrics(chat_page)['composer']
    _scroll_list_to(chat_page, 0)
    chat_page.mouse.wheel(0, 600)
    after = _metrics(chat_page)
    assert abs(after['composer']['top'] - before['top']) < 1
    assert after['pageScroll'] == 0


def test_composer_rides_above_the_on_screen_keyboard(chat_page, viewport):
    chat_page.evaluate("""() => {
      const vv = window.__fakeVV; vv.height = window.innerHeight - 330; vv.offsetTop = 0;
      vv.dispatchEvent(new Event('resize'));
    }""")
    chat_page.wait_for_function("() => document.body.classList.contains('kb-open')")
    chat_page.wait_for_timeout(100)
    m = _metrics(chat_page)
    keyboard_top = viewport['height'] - 330
    assert m['composer']['bottom'] <= keyboard_top + 1, 'composer must sit above the keyboard'
    assert m['composer']['top'] >= m['head']['bottom'] - 1
    assert m['head']['top'] >= 0
    chat_page.evaluate("() => { const vv = window.__fakeVV; vv.height = window.innerHeight; vv.dispatchEvent(new Event('resize')); }")
    chat_page.wait_for_function("() => !document.body.classList.contains('kb-open')")
    assert _metrics(chat_page)['composer']['bottom'] <= _metrics(chat_page)['tabbar']['top'] + 1


def test_streaming_does_not_move_a_reader_who_scrolled_up_and_shows_the_new_pill(chat_page, server):
    server.script([
        {'type': 'text', 'text': 'First part of the reply. '},
        {'type': 'text', 'text': 'Second part. ' * 20},
        {'type': 'text', 'text': 'Third part. ' * 30},
        {'type': 'done', 'stop_reason': 'end_turn'},
    ])
    _send(chat_page, 'how is my week?')
    chat_page.wait_for_function("() => document.querySelector('#chat-messages .chat-row.coach:last-child .chat-bubble')?.textContent.includes('First part')")
    chat_page.evaluate("() => { window.__list = document.getElementById('chat-messages'); }")

    _scroll_list_to(chat_page, 120)
    top_before = _metrics(chat_page)['top']
    assert top_before == pytest.approx(120, abs=2)

    server.release(2)  # two more deltas land while the reader is up the thread
    chat_page.wait_for_function("() => document.querySelector('#chat-messages .chat-row.coach:last-child .chat-bubble')?.textContent.includes('Third part') || document.querySelector('#chat-messages .chat-row.coach:last-child .chat-bubble')?.textContent.includes('Second part')")
    chat_page.wait_for_timeout(150)
    m = _metrics(chat_page)
    assert m['top'] == pytest.approx(top_before, abs=2), 'the view must not move'
    assert chat_page.is_visible('#chat-new-pill')
    assert chat_page.evaluate("() => document.getElementById('chat-messages') === window.__list"), \
        'the list is a stable container: deltas must not rebuild it'

    server.release(1)  # done
    chat_page.wait_for_function("() => !document.querySelector('[data-a=\"chat:send\"]').disabled")
    m = _metrics(chat_page)
    assert m['top'] == pytest.approx(top_before, abs=2), 'finishing the turn must not move the reader either'
    assert chat_page.is_visible('#chat-new-pill')

    chat_page.click('#chat-new-pill')
    chat_page.wait_for_timeout(100)
    assert _metrics(chat_page)['distance'] <= 80
    assert not chat_page.is_visible('#chat-new-pill')


def test_streaming_follows_the_reply_while_the_reader_is_at_the_bottom(chat_page, server):
    server.script([
        {'type': 'text', 'text': 'Start. '},
        {'type': 'text', 'text': 'Middle sentence. ' * 40},
        {'type': 'done', 'stop_reason': 'end_turn'},
    ])
    _send(chat_page, 'tell me more')
    chat_page.wait_for_function("() => document.querySelector('#chat-messages .chat-row.coach:last-child .chat-bubble')?.textContent.includes('Start.')")
    server.release(1)
    chat_page.wait_for_function("() => document.querySelector('#chat-messages .chat-row.coach:last-child .chat-bubble')?.textContent.includes('Middle sentence')")
    chat_page.wait_for_timeout(100)
    assert _metrics(chat_page)['distance'] <= 80
    assert not chat_page.is_visible('#chat-new-pill')
    server.release(1)


def test_sending_scrolls_to_the_bottom_even_when_scrolled_up(chat_page, server):
    server.script([
        {'type': 'text', 'text': 'Reply. '},
        {'type': 'done', 'stop_reason': 'end_turn'},
    ])
    _scroll_list_to(chat_page, 0)
    assert _metrics(chat_page)['distance'] > 200
    _send(chat_page, 'new question while up the thread')
    chat_page.wait_for_function("() => document.querySelector('#chat-messages .chat-row.me:last-of-type, #chat-messages')")
    chat_page.wait_for_function("() => { const l = document.getElementById('chat-messages'); return l.scrollHeight - l.scrollTop - l.clientHeight <= 80; }")
    assert 'new question while up the thread' in chat_page.inner_text('#chat-messages')
    server.release(1)


def test_offline_keeps_the_layout_and_disables_sending(chat_page):
    ctx = chat_page.context
    ctx.set_offline(True)
    try:
        chat_page.wait_for_selector('.chat-panel > .chat-banner', timeout=5000)
        m = _metrics(chat_page)
        assert chat_page.locator('[data-a="chat:send"]').is_disabled()
        assert m['composer']['bottom'] <= m['tabbar']['top'] + 1
        assert m['listBox']['bottom'] <= m['composer']['top'] + 1
        assert m['height'] > m['client'], 'the saved thread is still readable'
        _scroll_list_to(chat_page, 0)
        assert _metrics(chat_page)['top'] == 0
    finally:
        ctx.set_offline(False)
