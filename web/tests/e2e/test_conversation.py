"""e2e coverage for the athlete<->coach conversation (IDEA 016 Part 2): the athlete's "My coach"
pane inside the Coach tab (unread badge, thread, send with a streamed AI reply, mute, polling,
offline read-only) and the coach roster's Conversations sub-tab (thread, send, mute, unread badge,
polling, offline). No real backend: a small stateful `FakeThread` serves both sides' routes via
Playwright (the most-recently-registered route wins, so these override conftest's empty default).
Polling is driven deterministically by firing `visibilitychange` (main.js's poll tick listens for
it) instead of waiting out the 20 s interval.
"""

import json
import re

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings
from test_coach_roster import COACH_IDENTITY, _cors_route, _make_ctx, _open_roster

CORS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}
COACH_ID = 'coach-uuid-1'
PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'


def _msg(id_, role, body, minute):
    return {
        'id': id_, 'sender_role': role, 'body': body, 'coach_athlete_id': COACH_ID,
        'created_at': f'2026-09-29T10:{minute:02d}:00+00:00',
    }


class FakeThread:
    """One thread's server state plus the request log the tests assert on."""

    def __init__(self, messages=None, muted=False, ai_reply='Ease off today.'):
        self.messages = list(messages or [])
        self.muted = muted
        self.ai_reply = ai_reply
        self.posts = []
        self.patches = []
        self._n = 0

    def add(self, role, body, minute):
        self._n += 1
        self.messages.append(_msg(f'srv-{self._n}', role, body, minute))

    def _json(self, route, payload):
        route.fulfill(status=200, content_type='application/json', body=json.dumps(payload), headers=CORS)

    def _snapshot(self, since):
        msgs = [m for m in self.messages if since is None or m['created_at'] >= since]
        return {'coach_athlete_id': COACH_ID, 'ai_muted': self.muted, 'messages': msgs}

    @staticmethod
    def _since(url):
        match = re.search(r'since=([^&]+)', url)
        return match.group(1).replace('%3A', ':').replace('%2B', '+') if match else None

    # athlete side ---------------------------------------------------------------------------
    def athlete_list(self, route):
        if route.request.method == 'OPTIONS':
            return route.fulfill(status=204, headers=CORS)
        return self._json(route, [{'coach_athlete_id': COACH_ID, 'ai_muted': self.muted}])

    def athlete_thread(self, route):
        request = route.request
        if request.method == 'OPTIONS':
            return route.fulfill(status=204, headers=CORS)
        if request.method == 'PATCH':
            self.muted = json.loads(request.post_data)['ai_muted']
            self.patches.append(self.muted)
            return self._json(route, {'coach_athlete_id': COACH_ID, 'ai_muted': self.muted})
        if request.method == 'POST':
            body = json.loads(request.post_data)['message']
            self.posts.append(body)
            self.add('athlete', body, 30)
            sse = ''
            if not self.muted:
                self.add('ai_coach', self.ai_reply, 31)
                sse = (
                    f'data: {json.dumps({"type": "text", "text": self.ai_reply})}\n\n'
                    'data: {"type":"done","stop_reason":"end_turn"}\n\n'
                )
            return route.fulfill(status=200, content_type='text/event-stream', body=sse, headers=CORS)
        return self._json(route, self._snapshot(self._since(request.url)))

    # coach side -------------------------------------------------------------------------------
    def coach_thread(self, route):
        request = route.request
        if request.method == 'OPTIONS':
            return route.fulfill(status=204, headers=CORS)
        if request.method == 'PATCH':
            self.muted = json.loads(request.post_data)['ai_muted']
            self.patches.append(self.muted)
            return self._json(route, {'coach_athlete_id': COACH_ID, 'ai_muted': self.muted})
        if request.method == 'POST':
            body = json.loads(request.post_data)['body']
            self.posts.append(body)
            self.add('coach', body, 40)
            return self._json(route, self.messages[-1])
        return self._json(route, self._snapshot(self._since(request.url)))


ATHLETE_LIST_URL = re.compile(r'/api/conversations(\?|$)')
ATHLETE_THREAD_URL = re.compile(r'/api/conversations/[^/]+(/messages)?(\?|$)')
COACH_THREAD_URL = re.compile(r'/api/coach/athletes/renee/conversation(/messages)?(\?|$)')


def _poll(page):
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")


def _launch(pw, cfg):
    try:
        return getattr(pw, cfg['name']).launch()
    except Exception as e:  # noqa: BLE001
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')


@pytest.fixture(params=BROWSERS)
def athlete_session(request, base_url):
    """`open(thread)` -> a signed-in, configured athlete page whose conversation routes are served
    by `thread` (None = the athlete has no coach thread)."""
    with sync_playwright() as pw:
        opened = []

        def open_(thread):
            browser = _launch(pw, request.param)
            ctx = browser.new_context(viewport=request.param['vp'], service_workers='block')
            opened.append((browser, ctx))
            seed_identity(ctx)
            seed_settings(ctx)
            ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
            ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'))
            ctx.route('**/api/athlete*', _cors_route(200, 'application/json', '{"slug":"renee","name":"Renee"}'))
            ctx.route('**/api/grants*', _cors_route(200, 'application/json', '[]'))
            ctx.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
            if thread is None:
                ctx.route(ATHLETE_LIST_URL, _cors_route(200, 'application/json', '[]'))
            else:
                ctx.route(ATHLETE_LIST_URL, thread.athlete_list)
                ctx.route(ATHLETE_THREAD_URL, thread.athlete_thread)
            page = ctx.new_page()
            page.goto(base_url)
            return page

        try:
            yield open_
        finally:
            for browser, ctx in opened:
                ctx.close()
                browser.close()


@pytest.fixture(params=BROWSERS)
def coach_session(request, base_url):
    """`open(thread)` -> the roster open on renee's Conversations sub-tab, served by `thread`."""
    with sync_playwright() as pw:
        opened = []

        def open_(thread, *, sub_tab='conversations'):
            browser, ctx = _make_ctx(pw, request.param, identity=COACH_IDENTITY)
            opened.append((browser, ctx))
            ctx.route(COACH_THREAD_URL, thread.coach_thread)
            page = ctx.new_page()
            page.goto(base_url)
            _open_roster(page)
            page.click('[data-a="roster:select-athlete"]')
            page.wait_for_selector('[data-a="roster:subtab:conversations"]')
            if sub_tab == 'conversations':
                page.click('[data-a="roster:subtab:conversations"]')
            return page

        try:
            yield open_
        finally:
            for browser, ctx in opened:
                ctx.close()
                browser.close()


# --- athlete: "My coach" inside the Coach tab ---------------------------------------------------


def test_no_coach_means_the_coach_tab_is_just_the_ai_chat(athlete_session):
    page = athlete_session(None)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')
    assert page.locator('[data-a="coach:view:coach"]').count() == 0


def test_unread_badge_on_coach_tab_clears_once_my_coach_is_open(athlete_session):
    thread = FakeThread([
        _msg('a1', 'athlete', 'how is my taper?', 0),
        _msg('c1', 'coach', 'taper looks right, trust it', 5),
    ])
    page = athlete_session(thread)
    page.wait_for_selector('[data-a="tab:coach"] .badge-count')
    assert page.locator('[data-a="tab:coach"] .badge-count').text_content().strip() == '1'

    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('[data-a="coach:view:coach"] .badge-count')
    assert page.locator('#chat-input').count() == 1  # AI pane stays the default
    page.click('[data-a="coach:view:coach"]')
    page.wait_for_selector('#my-coach-messages')
    assert 'taper looks right, trust it' in page.locator('#my-coach-messages').text_content()
    assert page.locator('[data-a="tab:coach"] .badge-count').count() == 0
    assert page.locator('[data-a="coach:view:coach"] .badge-count').count() == 0


def test_athlete_send_posts_streams_the_ai_reply_and_clears_the_composer(athlete_session):
    thread = FakeThread([_msg('c1', 'coach', 'welcome', 0)], ai_reply='Keep it easy.')
    page = athlete_session(thread)
    page.click('[data-a="tab:coach"]')
    page.click('[data-a="coach:view:coach"]')
    page.fill('#my-coach-input', 'legs are heavy')
    page.click('[data-a="my-coach:send"]')
    page.wait_for_function("document.querySelector('#my-coach-messages')?.textContent.includes('Keep it easy.')")
    text = page.locator('#my-coach-messages').text_content()
    assert 'legs are heavy' in text
    assert thread.posts == ['legs are heavy']
    assert page.locator('#my-coach-input').input_value() == ''


def test_muted_thread_send_saves_without_an_ai_reply(athlete_session):
    thread = FakeThread([_msg('c1', 'coach', 'welcome', 0)], muted=True)
    page = athlete_session(thread)
    page.click('[data-a="tab:coach"]')
    page.click('[data-a="coach:view:coach"]')
    assert page.locator('.chat-mute-btn').text_content().strip() == 'Unmute AI'
    page.fill('#my-coach-input', 'just for my coach')
    page.click('[data-a="my-coach:send"]')
    page.wait_for_function("document.querySelector('#my-coach-messages')?.textContent.includes('just for my coach')")
    assert thread.posts == ['just for my coach']
    assert 'Ease off today.' not in page.locator('#my-coach-messages').text_content()


def test_athlete_toggles_mute(athlete_session):
    thread = FakeThread([_msg('c1', 'coach', 'welcome', 0)])
    page = athlete_session(thread)
    page.click('[data-a="tab:coach"]')
    page.click('[data-a="coach:view:coach"]')
    page.click('[data-a="my-coach:mute-toggle"]')
    page.wait_for_function("document.querySelector('.chat-mute-btn')?.textContent.trim() === 'Unmute AI'")
    assert thread.patches == [True]


def test_poll_brings_in_a_new_coach_message_and_keeps_the_draft(athlete_session):
    thread = FakeThread([_msg('c1', 'coach', 'welcome', 0)])
    page = athlete_session(thread)
    page.click('[data-a="tab:coach"]')
    page.click('[data-a="coach:view:coach"]')
    page.fill('#my-coach-input', 'half typed message')
    thread.add('coach', 'new advice from coach', 20)
    _poll(page)
    page.wait_for_function("document.querySelector('#my-coach-messages')?.textContent.includes('new advice from coach')")
    assert page.locator('#my-coach-input').input_value() == 'half typed message'
    # viewing the thread, so it never turns into an unread badge
    assert page.locator('[data-a="tab:coach"] .badge-count').count() == 0


def test_new_coach_message_while_elsewhere_badges_the_coach_tab(athlete_session):
    thread = FakeThread([_msg('c1', 'coach', 'welcome', 0)])
    page = athlete_session(thread)
    page.click('[data-a="tab:coach"]')
    page.click('[data-a="coach:view:coach"]')
    page.click('[data-a="tab:settings"]')
    thread.add('coach', 'ping while away', 20)
    _poll(page)
    page.wait_for_selector('[data-a="tab:coach"] .badge-count')
    assert page.locator('[data-a="tab:coach"] .badge-count').text_content().strip() == '1'


def test_offline_shows_cached_messages_read_only(athlete_session):
    thread = FakeThread([_msg('c1', 'coach', 'saved for offline', 0)])
    page = athlete_session(thread)
    page.click('[data-a="tab:coach"]')
    page.click('[data-a="coach:view:coach"]')
    page.wait_for_selector('#my-coach-messages')
    page.context.set_offline(True)
    page.wait_for_selector('text=Offline -- showing saved messages')
    assert 'saved for offline' in page.locator('#my-coach-messages').text_content()
    assert page.locator('#my-coach-input').is_disabled()
    assert page.locator('[data-a="my-coach:send"]').is_disabled()


# --- coach: roster Conversations sub-tab ---------------------------------------------------------


def test_coach_sees_the_thread_replaces_the_placeholder_and_sends(coach_session):
    thread = FakeThread([
        _msg('a1', 'athlete', 'shoulder tight today', 0),
        _msg('i1', 'ai_coach', 'ease the volume', 1),
    ])
    page = coach_session(thread)
    page.wait_for_selector('#roster-conversation-messages')
    content = page.content()
    assert 'coming soon' not in content
    assert 'shoulder tight today' in content
    page.fill('#roster-conversation-input', 'skip the pull set')
    page.click('[data-a="roster:conversation:send"]')
    page.wait_for_function("document.querySelector('#roster-conversation-messages')?.textContent.includes('skip the pull set')")
    assert thread.posts == ['skip the pull set']
    assert page.locator('#roster-conversation-input').input_value() == ''


def test_coach_toggles_mute(coach_session):
    thread = FakeThread([_msg('a1', 'athlete', 'hi', 0)])
    page = coach_session(thread)
    page.click('[data-a="roster:conversation:mute-toggle"]')
    page.wait_for_function("document.querySelector('.chat-mute-btn')?.textContent.trim() === 'Unmute AI'")
    assert thread.patches == [True]


def test_athlete_message_badges_the_conversations_sub_tab_until_opened(coach_session):
    thread = FakeThread([_msg('a1', 'athlete', 'are we swimming tomorrow?', 0)])
    page = coach_session(thread, sub_tab='dashboard')
    badge = '[data-a="roster:subtab:conversations"] .badge-count'
    page.wait_for_selector(badge)
    assert page.locator(badge).text_content().strip() == '1'
    page.click('[data-a="roster:subtab:conversations"]')
    page.wait_for_selector('#roster-conversation-messages')
    assert page.locator(badge).count() == 0


def test_coach_poll_picks_up_a_new_athlete_message_and_keeps_the_draft(coach_session):
    thread = FakeThread([_msg('a1', 'athlete', 'hello', 0)])
    page = coach_session(thread)
    page.wait_for_selector('#roster-conversation-messages')
    page.fill('#roster-conversation-input', 'drafting a reply')
    thread.add('athlete', 'one more thing', 20)
    _poll(page)
    page.wait_for_function("document.querySelector('#roster-conversation-messages')?.textContent.includes('one more thing')")
    assert page.locator('#roster-conversation-input').input_value() == 'drafting a reply'


def test_coach_offline_is_read_only(coach_session):
    thread = FakeThread([_msg('a1', 'athlete', 'visible offline', 0)])
    page = coach_session(thread)
    page.wait_for_selector('#roster-conversation-messages')
    page.context.set_offline(True)
    page.wait_for_selector('text=Offline -- showing saved messages')
    assert 'visible offline' in page.locator('#roster-conversation-messages').text_content()
    assert page.locator('[data-a="roster:conversation:send"]').is_disabled()
