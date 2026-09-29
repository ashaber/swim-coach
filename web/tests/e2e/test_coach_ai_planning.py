"""e2e coverage for the coach-ai-planning build:

- the roster's Training Plan sub-tab shows an "Ask the AI coach" chat panel
  (Andrew's decision 2 -- lives here, not the Conversations sub-tab), streams
  a mocked reply against POST /api/coach/athletes/<slug>/chat, and renders
  the detailed plan view (macro week table, architecture, red-team review);
- the athlete's own Plan tab renders that same detailed plan view.

Same mocked-backend / CORS-preflight conventions as test_coach_roster.py /
test_coach_chat.py: cross-origin requests carrying an Authorization header
trip a CORS preflight WebKit enforces strictly even against a mocked
response, so every route mock answers OPTIONS with a 204 + CORS headers too.
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

COACH_IDENTITY = {'name': 'Andrew', 'athlete': 'andrew', 'role': 'coach', 'coachFor': ['renee']}

ATHLETES_STUB = json.dumps([{'slug': 'renee', 'name': 'Renee'}])

# A macro plan carrying the newer coach-authored fields renderMacroSection alone never showed
# (weeks/architecture/red_team, plus a meso-detailed block) -- what the detailed-plan-view test
# below asserts against.
DETAILED_MACRO_PLAN_STUB = json.dumps({
    'slug': 'renee', 'name': 'Renee', 'athlete': {'name': 'Renee'}, 'events': [],
    'macro': {
        'blocks': [{
            'name': 'base', 'start_date': '2026-08-01', 'end_date': '2026-08-31',
            'weekly_volume_target_m': 15000, 'focus': 'aerobic base',
            'purpose': 'fade resistance', 'limiter': 'late-race fade',
            'key_sessions': ['over/unders: 3x8 -> 3x10'], 'hard_days_per_week': 2,
            'intensity_distribution': 'polarized: 2 hard, rest easy', 'closing_test': 'FTP re-test',
        }],
        'weeks': [{
            'week_start': '2026-08-03', 'phase': 'Base', 'focus': 'aerobic base',
            'hours': 8, 'load_tss': 420, 'ctl_target': 40,
            'key_sessions': ['Tue: over/unders 3x8min'], 'recovery': False,
        }],
        'architecture': 'Base then build toward Greece, one dedicated A-race block.',
        'red_team': [{
            'id': 'confirm-volume-jump', 'severity': 'high',
            'evidence': 'Week 2 hours drop with no logged reason.',
            'consequence': 'Could mask an unplanned deload as a real recovery week.',
            'fix': 'Tag the week recovery=true or explain the drop.',
            'decision': 'keep_as_is', 'decision_reason': 'known gap, coach reviewed',
            'athlete_words': "coach confirming this on the athlete's behalf",
            'confirmed_by_role': 'coach', 'confirmed_by_id': 'tim',
        }],
    },
    'weeks': [{
        'iso_week': '2026-W32', 'focus': 'aerobic base', 'target_volume_m': 2000,
        'sessions': [{
            'id': 'sess-1', 'date': '2026-08-03', 'sport': 'swim_pool',
            'duration_min': 45, 'distance_m': 2000, 'status': 'planned',
            'purpose': 'Aerobic base',
        }],
    }],
})

PLAN_LOAD_STUB = json.dumps({'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': []})


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _make_coach_ctx(pw, cfg):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx, identity=COACH_IDENTITY)
    seed_settings(ctx)
    # The coach's own Plan tab (self-access) -- unmocked, this fails on CORS the moment
    # main.js's boot-time loadPlan/loadPlanLoad fire, same hazard every coach-roster e2e file
    # documents.
    ctx.route('**/api/plan*', _cors_route(200, 'application/json', '{"slug":"andrew","athlete":{"name":"Andrew"},"events":[],"weeks":[],"macro":{"blocks":[]}}'))
    ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
    ctx.route('**/api/coach/athletes/renee/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
    ctx.route('**/api/coach/athletes/renee/workouts*', _cors_route(200, 'application/json', '[]'))
    ctx.route('**/api/coach/athletes/renee/feedback*', _cors_route(200, 'application/json', '[]'))
    ctx.route('**/api/coach/athletes/renee/health-status*', _cors_route(200, 'application/json', '[]'))
    ctx.route('**/api/coach/athletes/renee/plan*', _cors_route(200, 'application/json', DETAILED_MACRO_PLAN_STUB))
    ctx.route('**/api/coach/athletes*', _cors_route(200, 'application/json', ATHLETES_STUB))
    ctx.route('**/api/feedback*', _cors_route(200, 'application/json', '[]'))
    ctx.route('**/api/athlete*', _cors_route(200, 'application/json', '{"race_debriefs": []}'))
    return browser, ctx


@pytest.fixture(params=BROWSERS)
def coach_page(request, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_coach_ctx(pw, request.param)
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


def _open_roster_plan_subtab(page):
    page.wait_for_selector('[data-a="tab:roster"]')
    page.click('[data-a="tab:roster"]')
    page.wait_for_selector('[data-a="roster:select-athlete"]')
    page.click('[data-a="roster:select-athlete"]')
    page.wait_for_selector('[data-a="roster:subtab:plan"]')
    page.click('[data-a="roster:subtab:plan"]')
    page.wait_for_selector('[data-a="roster:chat:send"]')


def test_roster_plan_subtab_shows_the_ask_ai_coach_panel(coach_page):
    _open_roster_plan_subtab(coach_page)
    content = coach_page.content()
    assert 'Ask the AI coach' in content
    assert coach_page.locator('#roster-chat-input').count() == 1
    assert coach_page.locator('[data-a="roster:chat:send"]').count() == 1


def test_roster_plan_subtab_streams_a_mocked_ai_reply(coach_page):
    _open_roster_plan_subtab(coach_page)
    sse_body = (
        'data: {"type":"text","text":"Here is next week for Renee."}\n\n'
        'data: {"type":"done","stop_reason":"end_turn"}\n\n'
    )
    coach_page.route(
        '**/api/coach/athletes/renee/chat', _cors_route(200, 'text/event-stream', sse_body),
    )
    coach_page.fill('#roster-chat-input', 'draft next week for renee')
    coach_page.click('[data-a="roster:chat:send"]')
    coach_page.wait_for_selector('text=Here is next week for Renee.')


def test_roster_plan_subtab_renders_the_detailed_plan_view(coach_page):
    _open_roster_plan_subtab(coach_page)
    coach_page.wait_for_selector('text=Plan detail & reasoning')
    content = coach_page.content()
    assert 'Base then build toward Greece' in content  # architecture
    assert 'fade resistance' in content  # meso block detail
    assert 'FTP re-test' in content
    assert 'Confirmed by coach' in content  # red-team finding attribution
    assert 'tim' in content


@pytest.fixture(params=BROWSERS)
def athlete_page(request, base_url):
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, request.param['name']).launch()
        except Exception as e:
            pytest.skip(f'{request.param["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=request.param['vp'], service_workers='block')
        seed_identity(ctx, identity={'name': 'Renee', 'athlete': 'renee', 'role': 'athlete'})
        seed_settings(ctx)
        ctx.route('**/api/plan*', _cors_route(200, 'application/json', DETAILED_MACRO_PLAN_STUB))
        ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
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


def test_athlete_plan_tab_renders_the_detailed_plan_view(athlete_page):
    athlete_page.wait_for_selector('[data-a="tab:plan"]')
    athlete_page.click('[data-a="tab:plan"]')
    athlete_page.wait_for_selector('text=Plan detail & reasoning')
    content = athlete_page.content()
    assert 'Base then build toward Greece' in content
    assert 'fade resistance' in content
    assert 'Confirmed by coach' in content
