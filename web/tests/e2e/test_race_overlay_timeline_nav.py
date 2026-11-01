"""e2e: race-day overlay timeline follow (row before "now" pinned under the tabs) and Checklist/Timeline swipe.

Chromium only here (WebKit runs in CI). Time is mocked with Playwright's clock; swipes are synthetic
TouchEvents because Playwright has no touch-drag primitive.
"""

import re

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings
from test_race_day_checklist import CORS, Backend

NOW = '2099-01-03T08:10:00'  # start 10:00: "Pre-start 2" (08:00) is current, "Pre-start 1" (07:30) the anchor
LATER = 90 * 60 * 1000  # ms


def _timeline():
    race = [(f'e{i}', f'Event {i}', -300 + i * 30) for i in range(1, 10)]
    rows = [{'id': 'dinner', 'label': 'Dinner', 'day': 'eve', 'at': '19:00', 'offset_min': None, 'is_start': False}]
    rows += [{'id': i, 'label': label, 'day': 'race', 'at': None, 'offset_min': off, 'is_start': False}
             for i, label, off in race]
    rows.append({'id': 'start', 'label': 'Start', 'day': 'race', 'at': None, 'offset_min': 0, 'is_start': True})
    for n in range(1, 9):
        rows.append({'id': f'post{n}', 'label': f'After {n}', 'day': 'race', 'at': None, 'offset_min': n * 20,
                     'is_start': False})
    return rows


@pytest.fixture
def env(base_url):
    cfg = BROWSERS[0].values[0]
    with sync_playwright() as pw:
        browser = getattr(pw, cfg['name']).launch()
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, has_touch=True)
        seed_identity(ctx)
        seed_settings(ctx)
        backend = Backend()
        backend.plan['start_time'] = '10:00'
        backend.plan['timeline'] = _timeline()
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
        pg.clock.install(time=NOW)
        pg.goto(base_url)
        try:
            yield pg, backend
            real = [e for e in errors if 'sw.js load failed' not in e and 'Importing a module script failed' not in e]
            assert not real, f'Uncaught JS errors: {real}'
        finally:
            ctx.close()
            browser.close()


SWIPE_JS = """(el, [x0, y0, x1, y1]) => {
  const mk = (x, y) => new Touch({ identifier: 1, target: el, clientX: x, clientY: y });
  const fire = (type, x, y) => {
    const t = mk(x, y);
    el.dispatchEvent(new TouchEvent(type, { bubbles: true, cancelable: true,
      touches: type === 'touchend' ? [] : [t], targetTouches: type === 'touchend' ? [] : [t], changedTouches: [t] }));
  };
  fire('touchstart', x0, y0);
  fire('touchmove', (x0 + x1) / 2, (y0 + y1) / 2);
  fire('touchmove', x1, y1);
  fire('touchend', x1, y1);
}"""


def _swipe(page, sel, x0, y0, x1, y1):
    page.locator(sel).first.evaluate(SWIPE_JS, [x0, y0, x1, y1])


def _open_timeline(page):
    page.wait_for_selector('[data-a="raceday:open"]')
    page.click('[data-a="raceday:open"]')
    page.wait_for_selector('#race-overlay .rd-item')
    page.click('.rd-tab[data-tab="timeline"]')
    page.wait_for_selector('.rd-tl-row[data-anchor]')


def _gap(page):
    """Distance from the bottom of the sticky tabs to the top of the anchor row, in px."""
    return page.evaluate("""() => {
      const row = document.querySelector('.rd-tl-row[data-anchor]');
      const tabs = document.getElementById('race-overlay-tabs');
      return row.getBoundingClientRect().top - tabs.getBoundingClientRect().bottom;
    }""")


def _scroll_top(page):
    return page.evaluate("() => document.getElementById('race-overlay-body').scrollTop")


def test_anchor_is_row_before_current_and_sits_under_tabs(env):
    page, _ = env
    _open_timeline(page)
    assert page.get_attribute('.rd-tl-row[data-anchor]', 'data-tl') == 'e5'  # 07:30; current e6 is 08:00
    assert page.get_attribute('.rd-tl-row.current', 'data-tl') == 'e6'
    assert abs(_gap(page)) <= 1
    assert _scroll_top(page) > 100


def test_tabs_stay_reachable_after_locking(env):
    page, _ = env
    _open_timeline(page)
    top = page.evaluate("() => document.querySelector('.rd-tab[data-tab=\"list\"]').getBoundingClientRect().top")
    assert 0 <= top < 200
    page.click('.rd-tab[data-tab="list"]')
    page.wait_for_selector('.rd-item')


def test_user_scroll_up_sticks_and_reopen_relocks(env):
    page, _ = env
    _open_timeline(page)
    page.mouse.move(195, 500)
    page.mouse.wheel(0, -100)
    page.wait_for_timeout(150)
    page.evaluate("() => { document.getElementById('race-overlay-body').scrollTop = 0; }")
    page.wait_for_function('() => document.getElementById("race-overlay-body").scrollTop === 0', polling=100)
    page.clock.run_for(2 * 60 * 1000)  # two interval ticks: must not pull the view back
    page.wait_for_timeout(200)
    assert _scroll_top(page) == 0
    page.click('#race-overlay .rd-x')
    page.wait_for_selector('#race-overlay', state='detached')
    _open_timeline(page)
    assert abs(_gap(page)) <= 1


def test_switching_tabs_relocks_after_user_scrolled(env):
    page, _ = env
    _open_timeline(page)
    page.mouse.move(195, 500)
    page.mouse.wheel(0, -100)
    page.wait_for_timeout(150)
    page.evaluate("() => { document.getElementById('race-overlay-body').scrollTop = 0; }")
    page.wait_for_function('() => document.getElementById("race-overlay-body").scrollTop === 0', polling=100)
    page.click('.rd-tab[data-tab="list"]')
    page.click('.rd-tab[data-tab="timeline"]')
    page.wait_for_selector('.rd-tl-row[data-anchor]')
    assert abs(_gap(page)) <= 1


def test_follows_as_events_pass_when_not_scrolled(env):
    page, _ = env
    _open_timeline(page)
    first = page.get_attribute('.rd-tl-row[data-anchor]', 'data-tl')
    page.clock.set_system_time('2099-01-03T09:10:00')
    page.clock.run_for(60 * 1000)
    page.wait_for_function('(a) => document.querySelector(".rd-tl-row[data-anchor]").dataset.tl !== a', arg=first, polling=100)
    assert abs(_gap(page)) <= 1


def test_rerender_does_not_jump_scroll_once_user_scrolled(env):
    page, _ = env
    _open_timeline(page)
    page.mouse.move(195, 500)
    page.mouse.wheel(0, 150)
    page.wait_for_timeout(150)
    before = _scroll_top(page)
    page.evaluate("() => { document.querySelector('.rd-tl-row').dataset.mark = '1'; }")
    page.clock.run_for(60 * 1000)  # the interval re-renders the overlay
    page.wait_for_function("() => !document.querySelector('.rd-tl-row').dataset.mark", polling=100)
    assert abs(_scroll_top(page) - before) <= 1


def test_last_row_can_reach_the_top(env):
    page, _ = env
    _open_timeline(page)
    page.evaluate("""() => {
      const body = document.getElementById('race-overlay-body');
      body.scrollTop = body.scrollHeight;
    }""")
    page.wait_for_timeout(100)
    gap = page.evaluate("""() => {
      const rows = document.querySelectorAll('.rd-tl-row');
      const tabs = document.getElementById('race-overlay-tabs');
      return rows[rows.length - 1].getBoundingClientRect().top - tabs.getBoundingClientRect().bottom;
    }""")
    assert gap <= 2


def test_swipe_left_and_right_switch_tabs(env):
    page, _ = env
    page.wait_for_selector('[data-a="raceday:open"]')
    page.click('[data-a="raceday:open"]')
    page.wait_for_selector('#race-overlay .rd-item')
    _swipe(page, '.rd-item', 300, 600, 100, 610)
    page.wait_for_selector('.rd-tab[data-tab="timeline"].on')
    page.wait_for_selector('.rd-tl-row[data-anchor]')
    assert abs(_gap(page)) <= 1
    _swipe(page, '.rd-tl-row', 100, 600, 300, 590)
    page.wait_for_selector('.rd-tab[data-tab="list"].on')
    page.wait_for_selector('.rd-item')


def test_vertical_drag_and_edge_start_do_not_switch_tabs(env):
    page, _ = env
    page.wait_for_selector('[data-a="raceday:open"]')
    page.click('[data-a="raceday:open"]')
    page.wait_for_selector('#race-overlay .rd-item')
    _swipe(page, '.rd-item', 200, 600, 190, 300)
    _swipe(page, '.rd-item', 5, 600, 250, 600)
    _swipe(page, '.rd-item', 200, 600, 100, 700)
    page.wait_for_timeout(200)
    assert page.locator('.rd-tab[data-tab="list"].on').count() == 1


def test_swipe_does_not_toggle_item_but_tap_does(env):
    page, _ = env
    page.wait_for_selector('[data-a="raceday:open"]')
    page.click('[data-a="raceday:open"]')
    page.wait_for_selector('#race-overlay .rd-item')
    page.wait_for_selector('.rd-item:has-text("Shoes")')
    _swipe(page, '.rd-item:has-text("Shoes")', 300, 600, 100, 600)
    page.wait_for_selector('.rd-tab[data-tab="timeline"].on')
    page.click('.rd-tab[data-tab="list"]')
    page.wait_for_selector('.rd-item:has-text("Shoes")')
    page.wait_for_timeout(500)
    assert page.locator('.rd-item.checked:has-text("Shoes")').count() == 0
    page.click('.rd-item:has-text("Shoes")')
    page.wait_for_selector('.rd-item.checked:has-text("Shoes")')


def test_swipe_ignored_in_edit_mode_and_on_inputs(env):
    page, _ = env
    _open_timeline(page)
    _swipe(page, '#raceday-start', 300, 300, 100, 300)
    page.wait_for_timeout(150)
    assert page.locator('.rd-tab[data-tab="timeline"].on').count() == 1
    page.click('[data-a="raceday:tl-edit"]')
    page.wait_for_selector('.rd-tl-edit')
    _swipe(page, '.rd-tl-edit', 100, 600, 300, 600)
    page.wait_for_timeout(150)
    assert page.locator('.rd-tab[data-tab="timeline"].on').count() == 1
