"""Regression: a chat composer must keep what the athlete is typing (text, focus, caret) when a
background request lands and render() rebuilds the DOM -- at app launch several loads (plan,
workouts, feedback, ...) resolve one after another, and each used to wipe the textarea.

Reuses test_workout_chat.py's fixtures/helpers (mocked backend, signed-in identity). Held
requests are fulfilled by the test AFTER typing, so the render is deterministic.
"""

import json

from playwright.sync_api import Page

from test_workout_chat import (  # noqa: F401  (page is a fixture)
    RICH_FIT_WORKOUT, _configure_backend, _cors_route, page,
)

PLAN_BODY = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'
TYPED = 'how should I fuel a 4 hour swim?'


def _hold_route(page: Page, pattern: str, body: str, held: list) -> None:
    """Answers CORS preflights at once but parks the real request until the test releases it."""
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers={
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type',
            })
            return
        if '/api/plan/load' in route.request.url:
            route.fulfill(status=200, content_type='application/json', headers={'Access-Control-Allow-Origin': '*'},
                          body='{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}')
            return
        held.append(route)
    page.route(pattern, handler)


def _release(held: list, body: str) -> None:
    for route in held:
        route.fulfill(
            status=200, content_type='application/json', body=body,
            headers={'Access-Control-Allow-Origin': '*'},
        )
    held.clear()


def test_ai_coach_composer_keeps_text_and_focus_when_a_late_load_renders(page):
    _configure_backend(page)
    page.click('[data-a="tab:coach"]')
    page.wait_for_selector('#chat-input')

    held: list = []
    _hold_route(page, '**/api/plan*', PLAN_BODY, held)
    page.reload()
    page.wait_for_selector('#chat-input')

    page.click('#chat-input')
    page.keyboard.type(TYPED)
    page.wait_for_timeout(300)  # let the held plan request actually reach the route
    assert held, 'expected the plan request to be parked'

    _release(held, PLAN_BODY)
    page.wait_for_timeout(500)  # plan landed -> render() ran

    assert page.input_value('#chat-input') == TYPED
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == 'chat-input'

    page.keyboard.type(' ok')  # the caret survived too: typing continues at the end
    assert page.input_value('#chat-input') == TYPED + ' ok'


def test_workout_composer_keeps_text_and_focus_when_a_late_load_renders(page):
    page.route('**/api/workouts*', _cors_route(200, 'application/json', json.dumps([RICH_FIT_WORKOUT])))
    _configure_backend(page)
    held: list = []
    _hold_route(page, '**/api/feedback*', '[]', held)
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-row')
    page.click('.hist-row')
    page.wait_for_selector('#workout-chat-input')

    page.click('#workout-chat-input')
    page.keyboard.type(TYPED)
    page.wait_for_timeout(300)
    assert held, 'expected the feedback request to be parked'

    _release(held, '[]')
    page.wait_for_timeout(500)

    assert page.input_value('#workout-chat-input') == TYPED
    assert page.evaluate("() => document.activeElement && document.activeElement.id") == 'workout-chat-input'

