"""e2e: the redesigned race view and its section drill-down (mocked backend, fixture from a trimmed real race)."""

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from conftest import seed_identity

BASE_URL = 'https://coach-api.test'
TOKEN = 'test-token-123'
CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}
FIXTURE = json.loads((Path(__file__).resolve().parents[1] / 'fixtures' / 'race_view_sunday.json').read_text())
WORKOUT = FIXTURE['workout']
SECTIONS = FIXTURE['sections']
PLAN = {'slug': 'renee', 'name': 'Renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': []}
VIEWPORTS = [
    pytest.param({'width': 390, 'height': 844}, id='390x844'),
    pytest.param({'width': 412, 'height': 915}, id='412x915'),
    pytest.param({'width': 360, 'height': 740}, id='360x740'),
]
SHOTS = os.environ.get('RACE_SHOTS_DIR')


def _cors(status, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type='application/json', body=json.dumps(body), headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=VIEWPORTS)
def race(request, base_url):
    calls = {'sections': 0, 'patch': [], 'split': []}
    pw = sync_playwright().start()
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport=request.param, service_workers='block')
    seed_identity(ctx)
    ctx.route('**/api/athlete*', _cors(200, {'slug': 'renee', 'name': 'Renee', 'race_debriefs': []}))
    ctx.route('**/api/grants*', _cors(200, []))
    ctx.route('**/api/plan*', _cors(200, PLAN))
    ctx.route('**/api/plan/load*', _cors(200, {'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': []}))
    ctx.route('**/api/feedback*', _cors(200, []))

    def workouts(route):
        req = route.request
        if req.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
        elif req.method == 'PATCH':
            calls['patch'].append(json.loads(req.post_data))
            route.fulfill(status=200, content_type='application/json', body=json.dumps(WORKOUT), headers=CORS_HEADERS)
        else:
            route.fulfill(status=200, content_type='application/json', body=json.dumps([WORKOUT]), headers=CORS_HEADERS)
    ctx.route('**/api/workouts?*', workouts)
    ctx.route(re.compile(r'/api/workouts/[^/?]+\?'), workouts)

    def sections(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        calls['sections'] += 1
        route.fulfill(status=200, content_type='application/json', body=json.dumps(SECTIONS), headers=CORS_HEADERS)
    ctx.route(re.compile(r'/api/workouts/[^/]+/sections'), sections)

    def split(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        calls['split'].append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type='application/json', body=json.dumps(WORKOUT), headers=CORS_HEADERS)
    ctx.route(re.compile(r'/api/workouts/[^/]+/section-splits'), split)
    ctx.route(re.compile(r'/api/workouts/[^/]+/pacing'), _cors(422, {'error': 'no series'}))
    page = ctx.new_page()
    errors: list[str] = []
    page.on('pageerror', lambda e: errors.append(str(e)))
    page.goto(base_url)
    page.evaluate(
        "(cfg) => window.localStorage.setItem('swimcoach_settings', JSON.stringify({baseUrl: cfg.baseUrl, token: cfg.token, version: 2}))",
        {'baseUrl': BASE_URL, 'token': TOKEN},
    )
    page.reload()
    page.click('[data-a="tab:dashboard"]')
    page.wait_for_selector('.hist-row')
    page.click('.hist-row')
    page.wait_for_selector('[aria-label="Section analysis"]')
    try:
        yield page, ctx, calls
    finally:
        real = [e for e in errors if 'sw.js load failed' not in e and 'Importing a module script failed' not in e]
        ctx.close()
        browser.close()
        pw.stop()
        assert not real, f'Uncaught JS errors: {real}'


def _shot(page, name):
    if SHOTS:
        Path(SHOTS).mkdir(parents=True, exist_ok=True)
        size = page.viewport_size
        page.screenshot(path=f'{SHOTS}/{name}-{size["width"]}x{size["height"]}.png', full_page=name.startswith('race'))


def _no_horizontal_scroll(page):
    return page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')


def test_cards_render_in_order_without_horizontal_scroll(race):
    page, _, _ = race
    labels = page.eval_on_selector_all('section.rv-card', 'els => els.map(e => e.getAttribute("aria-label"))')
    assert labels == ['Race summary', 'Start', 'Section analysis', 'Free speed', 'Laps', 'Efficiency', 'All sections']
    assert 'Finish sprint' not in page.content()
    assert _no_horizontal_scroll(page)
    _shot(page, 'race-view')


def test_more_numbers_toggle(race):
    page, _, _ = race
    button = page.locator('[data-a="race:more-toggle"]')
    assert button.get_attribute('aria-expanded') == 'false'
    button.click()
    assert page.locator('[data-a="race:more-toggle"]').get_attribute('aria-expanded') == 'true'
    assert 'max HR' in page.locator('.rv-more').inner_text()


def test_map_metric_toggle_greys_power_sections(race):
    page, _, _ = race
    page.click('[data-a="race:metric"][data-metric="eff"]')
    assert 'power section' in page.locator('[aria-label="Section analysis"] .rv-legend').inner_text()
    assert page.locator('[data-a="race:metric"][data-metric="eff"]').get_attribute('aria-pressed') == 'true'


def test_probe_shows_readout_and_keeps_vertical_scroll(race):
    page, _, _ = race
    wrap = page.locator('.rv-probe').first
    assert wrap.evaluate('e => getComputedStyle(e).touchAction') == 'pan-y'
    box = wrap.bounding_box()
    page.mouse.move(box['x'] + box['width'] * 0.2, box['y'] + 20)
    text = page.locator('#rv-start-read').inner_text()
    assert ' W' in text and 'Sun' in text and 'Sat' in text


def test_drill_down_opens_lazily_and_changes_mode_and_lap(race):
    page, _, calls = race
    assert calls['sections'] == 0
    page.click('[aria-label="Section analysis"] [data-a="race:section-open"][data-label="C5"]')
    page.wait_for_selector('#section-drill')
    page.click('#section-drill [data-a="race:section-tab"][data-label="C4"]')
    page.wait_for_selector('#section-drill svg.rv-drillmap')
    assert calls['sections'] == 1
    assert page.locator('#section-drill .rv-lapchip.on').count() == 1
    page.click('#section-drill [data-a="race:drill-mode"][data-mode="power"]')
    assert '< 100 W' in page.locator('#section-drill .rv-legend').inner_text()
    page.click('#section-drill [data-a="race:drill-lap"] >> nth=0')
    assert page.locator('#section-drill .rv-lapchip.on').inner_text().startswith('L2')
    assert _no_horizontal_scroll(page)
    _shot(page, 'drill-down')
    page.click('#section-drill [data-a="race:drill-close"] >> nth=0')
    page.wait_for_selector('#section-drill', state='detached')
    page.click('[aria-label="Section analysis"] [data-a="race:section-open"][data-label="C5"]')
    page.wait_for_selector('#section-drill svg.rv-drillmap')
    assert calls['sections'] == 1  # cached for the session


def test_section_note_is_saved(race):
    page, _, calls = race
    page.click('[aria-label="Section analysis"] [data-a="race:section-open"][data-label="C5"]')
    page.wait_for_selector('#race-section-note')
    page.fill('#race-section-note', 'off-camber after the barriers')
    page.click('[data-a="race:note-save"]')
    page.wait_for_selector('text=Saved.')
    assert calls['patch'] == [{'section_notes': {'C5': 'off-camber after the barriers'}}]


def test_long_section_split_posts_the_splits(race):
    page, _, calls = race
    page.click('[data-a="race:split"][data-label="C3"]')
    page.wait_for_function('() => !document.querySelector("[data-a=\\"race:split\\"][disabled]")')
    assert calls['split'] == [{'splits': {'C3': 3}}]


def test_drill_down_offline_shows_course_map_and_note(race):
    page, ctx, calls = race
    ctx.set_offline(True)
    page.click('[aria-label="Section analysis"] [data-a="race:section-open"][data-label="C5"]')
    page.wait_for_selector('#section-drill')
    assert 'needs a connection' in page.locator('#section-drill').inner_text()
    assert page.locator('#section-drill svg.rv-map').count() == 1
    assert calls['sections'] == 0


ROW_OVERFLOW_JS = """(sel) => [...document.querySelectorAll(sel)].flatMap((row) => {
  const kids = [...row.children];
  const bad = [];
  kids.forEach((k, i) => {
    if (k.scrollWidth > k.clientWidth + 1) bad.push('overflow:' + k.textContent.trim());
    const next = kids[i + 1];
    if (next && k.getBoundingClientRect().right > next.getBoundingClientRect().left + 1) bad.push('overlap:' + k.textContent.trim());
  });
  if (row.scrollWidth > row.clientWidth + 1) bad.push('row-overflow');
  return bad;
})"""


def test_lap_rows_do_not_overflow_or_overlap(race):
    page, _, _ = race
    assert page.evaluate(ROW_OVERFLOW_JS, '.rv-laprow') == []
    page.click('[aria-label="Section analysis"] [data-a="race:section-open"][data-label="C5"]')
    page.wait_for_selector('#section-drill svg.rv-drillmap')
    assert page.evaluate(ROW_OVERFLOW_JS, '.rv-drillrow') == []


def test_selected_chip_uses_the_accent_fill(race):
    page, _, _ = race
    fill = page.locator('[data-a="race:metric"].on').evaluate('e => getComputedStyle(e).backgroundColor')
    accent = page.evaluate('getComputedStyle(document.documentElement).getPropertyValue("--accent").trim()')
    js = '(c) => { const d = document.createElement("div"); d.style.color = c; document.body.appendChild(d); const v = getComputedStyle(d).color; d.remove(); return v; }'
    assert fill == page.evaluate(js, accent)
