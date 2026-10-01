"""e2e: the coach roster's Plan sub-tab opens on the active week.

Empty state when no current/future week exists (never a stale past week),
and active week first + future weeks following + past weeks collapsed when
a plan is set. Reuses test_coach_roster's context builder and overrides only
the coach plan route (the last-registered route wins).
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS
from test_coach_roster import _cors_route, _make_ctx, _open_roster


def _week(iso_week, monday, focus):
    return {
        'iso_week': iso_week, 'focus': focus, 'target_volume_m': 2000,
        'sessions': [{
            'id': f's-{iso_week}', 'date': monday, 'sport': 'swim_pool',
            'duration_min': 45, 'distance_m': 2000, 'status': 'planned',
            'purpose': f'purpose {iso_week}',
        }],
    }


PAST = [_week('2020-W01', '2019-12-30', 'old focus A')]
FUTURE = [_week('2099-W01', '2098-12-29', 'active focus'), _week('2099-W02', '2099-01-05', 'later focus')]


def _plan(weeks):
    return json.dumps({
        'slug': 'renee', 'name': 'Renee', 'athlete': {'name': 'Renee'}, 'events': [],
        'macro': {'blocks': []}, 'weeks': weeks,
    })


@pytest.fixture(params=BROWSERS)
def plan_page_factory(request, base_url):
    with sync_playwright() as pw:
        opened = []

        def make(weeks):
            browser, ctx = _make_ctx(pw, request.param)
            opened.append((browser, ctx))
            ctx.route('**/api/coach/athletes/renee/plan*', _cors_route(200, 'application/json', _plan(weeks)))
            pg = ctx.new_page()
            pg.goto(base_url)
            _open_roster(pg)
            pg.click('[data-a="roster:select-athlete"]')
            pg.wait_for_selector('[data-a="roster:subtab:plan"]')
            pg.click('[data-a="roster:subtab:plan"]')
            return pg

        try:
            yield make
        finally:
            for browser, ctx in opened:
                ctx.close()
                browser.close()


def test_only_past_weeks_shows_empty_state_with_coach_hint(plan_page_factory):
    pg = plan_page_factory(PAST)
    pg.wait_for_selector('text=No current plan yet')
    content = pg.content()
    assert 'Ask the AI coach' in content
    assert 'This week ·' not in content
    assert pg.locator('[data-a="weeks:toggle-all"]').text_content().strip() == 'Past weeks (1)'
    assert not pg.locator('details.past-weeks').get_attribute('open')
    assert not pg.locator('details.past-weeks .week').first.is_visible()


def test_active_week_first_then_future_then_collapsed_past(plan_page_factory):
    pg = plan_page_factory(PAST + FUTURE)
    pg.wait_for_selector('.week >> visible=true')
    assert 'No current plan yet' not in pg.content()
    focuses = pg.locator('.week:visible .focus').all_text_contents()
    assert focuses == ['active focus', 'later focus']
    assert pg.locator('[data-a="weeks:toggle-all"]').text_content().strip() == 'Past weeks (1)'
    assert not pg.locator('details.past-weeks').get_attribute('open')
    assert 'old focus A' in pg.content()
