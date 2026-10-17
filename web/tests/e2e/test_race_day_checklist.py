"""e2e: race-week per-day item strips and the race-day checklist overlay (mocked backend).

Chromium only here (WebKit runs in CI). The mocked backend is stateful so a reload / offline replay
is checked against what the "server" actually received.
"""

import json
import re

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

ISO_WEEK = '2099-W01'
MONDAY, TUESDAY, SATURDAY = '2098-12-29', '2098-12-30', '2099-01-03'
CORS = {'Access-Control-Allow-Origin': '*'}


def _new_server_plan():
    return {
        'id': 'plan1', 'date': SATURDAY, 'name': 'Wafflecross Day 1', 'session_id': 'race1',
        'start_time': None, 'active_tags': [], 'checked': ['helmet'], 'notes': None,
        'sections': [
            {'id': 'kit', 'title': 'Kit', 'items': [
                {'id': 'helmet', 'text': 'Helmet', 'tags': [], 'default_checked': True},
                {'id': 'shoes', 'text': 'Shoes', 'tags': [], 'default_checked': False},
                {'id': 'covers', 'text': 'Shoe covers', 'tags': ['wet'], 'default_checked': False},
            ]},
            {'id': 'bike', 'title': 'Bike prep', 'items': [
                {'id': 'tires', 'text': 'Swap to mud tires', 'tags': ['mud'], 'default_checked': False},
            ]},
        ],
        'timeline': [
            {'id': 'dinner', 'label': 'Dinner', 'day': 'eve', 'at': '19:00', 'offset_min': None, 'is_start': False},
            {'id': 'wake', 'label': 'Wake up', 'day': 'race', 'at': None, 'offset_min': -315, 'is_start': False,
             'not_later_than': '07:00'},
            {'id': 'lunch', 'label': 'Lunch', 'day': 'race', 'at': None, 'offset_min': -180, 'is_start': False,
             'only_if_start_after': '12:00'},
            {'id': 'start', 'label': 'Start', 'day': 'race', 'at': None, 'offset_min': 0, 'is_start': True},
        ],
    }


TEMPLATE_TIMELINE = _new_server_plan()['timeline']


def _plan_json(week_items):
    week = {
        'iso_week': ISO_WEEK, 'meso_block': 'race', 'focus': 'race weekend', 'target_volume_m': 0,
        'adaptation_rationale': None,
        'sessions': [{
            'id': 'race1', 'date': SATURDAY, 'sport': 'bike', 'source': 'ai_coach', 'duration_min': 45,
            'distance_m': None, 'intensity': {'zone': 'Z5'}, 'purpose': 'Wafflecross Day 1 -- race',
            'title': 'Wafflecross Day 1', 'kind': 'race', 'status': 'planned', 'structure': None,
        }],
        'race_week_checklist': week_items,
    }
    return json.dumps({'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [week]})


class Backend:
    """Stateful stand-in for the race-day + race-week routes."""

    def __init__(self):
        self.plan = _new_server_plan()
        self.week_items = [
            {'id': 'w1', 'date': MONDAY, 'category': 'bike', 'label': 'Clean bike', 'done': False, 'note': None},
            {'id': 'w2', 'date': TUESDAY, 'category': 'gear', 'label': 'Pack kit', 'done': True, 'note': None},
            {'id': 'w3', 'date': '2099-01-05', 'category': 'recovery', 'label': 'Easy spin', 'done': False, 'note': None},
        ]
        self.requests = []

    def _json(self, route, body, status=200):
        route.fulfill(status=status, content_type='application/json', body=json.dumps(body), headers=CORS)

    def handle(self, route):
        req = route.request
        if req.method == 'OPTIONS':
            route.fulfill(status=204, headers={
                **CORS, 'Access-Control-Allow-Methods': 'GET, PATCH, OPTIONS',
                'Access-Control-Allow-Headers': 'Authorization, Content-Type',
            })
            return
        path = req.url.split('?')[0]
        body = req.post_data_json if req.post_data else None
        self.requests.append((req.method, path.split('.test')[-1], body))
        if path.endswith('/api/race-day'):
            self._json(route, self.plan)
        elif path.endswith('/items'):
            for item_id, on in body['states'].items():
                checked = [c for c in self.plan['checked'] if c != item_id]
                self.plan['checked'] = checked + ([item_id] if on else [])
            self._json(route, self.plan)
        elif path.endswith('/checklist'):
            gone = set(body.get('remove', []))
            for sec in self.plan['sections']:
                sec['items'] = [i for i in sec['items'] if i['id'] not in gone]
            self.plan['checked'] = [c for c in self.plan['checked'] if c not in gone]
            self._json(route, self.plan)
        elif path.endswith('/timeline'):
            if body.get('reset'):
                self.plan['timeline'] = json.loads(json.dumps(TEMPLATE_TIMELINE))
                self.plan['timeline_edited'] = False
            else:
                self.plan['timeline'] = body['timeline']
                self.plan['timeline_edited'] = True
            self._json(route, self.plan)
        elif '/race-day/' in path:
            self.plan.update(body)
            self._json(route, self.plan)
        else:  # race-week item
            item = next(i for i in self.week_items if path.endswith(f'/{i["id"]}'))
            item['done'] = body['done']
            self._json(route, item)

    def plan_route(self, route):
        route.fulfill(status=200, content_type='application/json', body=_plan_json(self.week_items), headers=CORS)


@pytest.fixture
def env(base_url):
    cfg = BROWSERS[0].values[0]  # chromium only
    with sync_playwright() as pw:
        browser = getattr(pw, cfg['name']).launch()
        ctx = browser.new_context(viewport=cfg['vp'])
        seed_identity(ctx)
        seed_settings(ctx)
        backend = Backend()
        ctx.route('**/api/plan*', backend.plan_route)
        ctx.route('**/api/plan/load*', lambda r: r.fulfill(
            status=200, content_type='application/json', headers=CORS,
            body='{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'))
        ctx.route(re.compile(r'/api/race-day'), backend.handle)
        ctx.route(re.compile(r'/api/plan/weeks/'), backend.handle)
        for pattern in ('**/api/feedback*', '**/api/athlete*'):
            ctx.route(pattern, lambda r: r.fulfill(status=200, content_type='application/json', body='[]', headers=CORS))
        pg = ctx.new_page()
        errors = []
        pg.on('pageerror', lambda e: errors.append(str(e)))
        pg.goto(base_url)
        try:
            yield pg, ctx, backend
            real = [e for e in errors if 'sw.js load failed' not in e and 'Importing a module script failed' not in e]
            assert not real, f'Uncaught JS errors: {real}'
        finally:
            ctx.close()
            browser.close()


def _open_overlay(page):
    page.wait_for_selector('[data-a="raceday:open"]')
    page.click('[data-a="raceday:open"]')
    page.wait_for_selector('#race-overlay .rd-item')


def test_race_week_day_strips_render_and_toggle(env):
    page, _, backend = env
    page.wait_for_selector('.rw-chip')
    assert 'Race week: 3 items, 1 done' in page.text_content('.race-week-checklist')
    # the in-week items sit in their day rows; the out-of-week one in the header summary
    assert page.locator('.day-row .rw-strip .rw-chip').count() == 2
    assert page.locator('.race-week-checklist .rw-chip').count() == 1
    page.click('.rw-chip:has-text("Clean bike")')
    page.wait_for_selector('text=Race week: 3 items, 2 done')
    assert ('PATCH', '/api/plan/weeks/2099-W01/race-week-items/w1', {'done': True}) in [
        (m, p.replace('?athlete=renee', ''), b) for m, p, b in backend.requests]
    assert backend.week_items[0]['done'] is True


def test_overlay_check_tag_filter_and_progress(env):
    page, _, backend = env
    _open_overlay(page)
    assert page.locator('.rd-item:has-text("Shoe covers")').count() == 0
    page.click('.rd-tag[data-tag="wet"]')
    page.wait_for_selector('.rd-item:has-text("Shoe covers")')
    assert page.locator('.rd-item:has-text("Swap to mud tires")').count() == 0
    page.click('.rd-item:has-text("Shoes")')
    page.wait_for_selector('.rd-item.checked:has-text("Shoes")')
    page.wait_for_function('() => document.querySelector(".rd-tab.on").innerText.includes("2/3")')
    page.wait_for_timeout(300)
    assert 'shoes' in backend.plan['checked'] and backend.plan['active_tags'] == ['wet']


def test_remove_item_persists_and_is_a_separate_tap_target(env):
    page, _, backend = env
    _open_overlay(page)
    page.click('.rd-tag[data-tag="wet"]')
    page.wait_for_selector('.rd-item:has-text("Shoe covers")')
    box = page.locator('[aria-label="Remove Shoe covers"]').bounding_box()
    assert box['width'] >= 44 and box['height'] >= 44
    page.click('[aria-label="Remove Shoe covers"]')
    page.wait_for_selector('.rd-item:has-text("Shoe covers")', state='detached')
    page.wait_for_timeout(300)
    assert ('PATCH', '/api/race-day/plan1/checklist', {'remove': ['covers']}) in backend.requests
    assert 'covers' not in [i['id'] for s in backend.plan['sections'] for i in s['items']]
    page.reload()
    page.wait_for_selector('#race-overlay .rd-item')
    assert page.locator('.rd-item:has-text("Shoe covers")').count() == 0


def test_checked_items_move_to_completed_and_back(env):
    page, _, _ = env
    _open_overlay(page)
    # helmet starts checked: it sits under Completed, not under Kit
    page.wait_for_selector('.rd-completed .rd-item:has-text("Helmet")')
    assert page.locator('.rd-section:not(.rd-completed) .rd-item:has-text("Helmet")').count() == 0
    page.click('.rd-section:not(.rd-completed) .rd-item:has-text("Shoes")')
    page.wait_for_selector('.rd-completed .rd-item:has-text("Shoes")')
    page.click('.rd-completed .rd-item:has-text("Helmet")')
    page.wait_for_selector('.rd-section:not(.rd-completed) .rd-item:has-text("Helmet")')
    assert page.locator('.rd-completed .rd-item:has-text("Helmet")').count() == 0


def test_reload_keeps_overlay_open_with_checks_and_back_closes_it(env):
    page, _, backend = env
    _open_overlay(page)
    page.click('.rd-item:has-text("Shoes")')
    page.wait_for_selector('.rd-item.checked:has-text("Shoes")')
    page.reload()
    page.wait_for_selector('#race-overlay .rd-item.checked:has-text("Shoes")')
    assert page.locator('#race-overlay').is_visible()
    page.go_back()
    page.wait_for_selector('#race-overlay', state='detached')
    assert page.locator('[data-a="raceday:open"]').count() == 1  # still in the app, on the plan
    page.reload()
    page.wait_for_selector('[data-a="raceday:open"]')
    assert page.locator('#race-overlay').count() == 0  # closed state persisted too


def test_close_button_closes_overlay(env):
    page, _, _ = env
    _open_overlay(page)
    page.click('#race-overlay .rd-x')
    page.wait_for_selector('#race-overlay', state='detached')


def test_start_time_drives_timeline_clock_times(env):
    page, _, backend = env
    _open_overlay(page)
    page.click('.rd-tab[data-tab="timeline"]')
    assert 'Set a start time' in page.text_content('#race-overlay-body')
    page.fill('#raceday-start', '09:00')
    page.wait_for_selector('text=3:45 AM')
    assert '7:00 PM' in page.inner_text('#race-overlay-body')  # evening-before item at its own clock time
    page.fill('#raceday-start', '10:30')
    page.wait_for_selector('text=5:15 AM')
    page.wait_for_timeout(300)
    assert backend.plan['start_time'] == '10:30'


def test_offline_checks_queue_then_sync_when_back_online(env):
    page, ctx, backend = env
    _open_overlay(page)
    ctx.set_offline(True)
    page.click('.rd-item:has-text("Shoes")')
    page.wait_for_selector('.rd-item.checked:has-text("Shoes")')
    assert 'Offline' in page.text_content('#race-overlay')
    assert 'shoes' not in backend.plan['checked']
    assert 'swimcoach_raceday_queue' in page.evaluate('() => Object.keys(localStorage).join(",")')
    ctx.set_offline(False)
    page.wait_for_function('() => !localStorage.getItem("swimcoach_raceday_queue")')
    assert 'shoes' in backend.plan['checked']
    # replaying is idempotent: the server list has no duplicates
    assert backend.plan['checked'].count('shoes') == 1


def test_no_horizontal_scroll_at_390(env):
    page, _, _ = env
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_selector('.rw-chip')
    assert page.evaluate('() => document.documentElement.scrollWidth <= document.documentElement.clientWidth')
    _open_overlay(page)
    page.click('.rd-tag[data-tag="wet"]')
    assert page.evaluate('() => document.documentElement.scrollWidth <= document.documentElement.clientWidth')
    assert page.evaluate('() => { const b = document.getElementById("race-overlay-body"); return b.scrollWidth <= b.clientWidth; }')


def _timeline_texts(page):
    return page.inner_text('#race-overlay-body')


def test_start_time_1515_adds_lunch_and_keeps_normal_wake(env):
    page, _, backend = env
    _open_overlay(page)
    page.click('.rd-tab[data-tab="timeline"]')
    page.fill('#raceday-start', '11:15')
    page.wait_for_selector('text=6:00 AM')
    assert 'Lunch' not in _timeline_texts(page)
    page.fill('#raceday-start', '15:15')
    page.wait_for_selector('.rd-tl-row:has-text("Lunch")')
    assert '12:15 PM' in _timeline_texts(page)
    assert page.locator('.rd-tl-row[data-tl="wake"] .rd-tl-time').inner_text() == '7:00 AM'


def test_edit_timeline_item_persists_across_reload_and_reset_restores(env):
    page, _, backend = env
    _open_overlay(page)
    page.click('.rd-tab[data-tab="timeline"]')
    page.fill('#raceday-start', '15:15')
    page.wait_for_selector('.rd-tl-row:has-text("Lunch")')
    page.click('[data-a="raceday:tl-edit"]')
    page.fill('input[data-tl="wake"][data-field="label"]', 'Get up')
    page.press('input[data-tl="wake"][data-field="label"]', 'Tab')
    page.wait_for_function('() => document.querySelector("input[data-tl=wake][data-field=label]").value === "Get up"')
    page.wait_for_timeout(300)
    assert backend.plan['timeline_edited'] is True
    assert backend.plan['timeline'][1]['label'] == 'Get up'
    page.reload()
    page.wait_for_selector('#race-overlay .rd-tl-row:has-text("Get up")')
    page.click('[data-a="raceday:tl-edit"]')
    page.click('[data-a="raceday:tl-reset"]')
    page.wait_for_function('() => document.querySelector("input[data-tl=wake][data-field=label]").value === "Wake up"')
    assert backend.plan['timeline_edited'] is False


def test_offline_timeline_edit_syncs_when_back_online(env):
    page, ctx, backend = env
    _open_overlay(page)
    page.click('.rd-tab[data-tab="timeline"]')
    page.click('[data-a="raceday:tl-edit"]')
    ctx.set_offline(True)
    page.click('[data-a="raceday:tl-add"]')
    page.wait_for_selector('li[data-tl="custom-1"]')
    assert len(backend.plan['timeline']) == 4  # not synced yet
    ctx.set_offline(False)
    page.wait_for_function('() => !localStorage.getItem("swimcoach_raceday_queue")')
    assert [t['id'] for t in backend.plan['timeline']][-1] == 'custom-1'
