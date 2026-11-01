"""e2e: rendered WCAG contrast guard (Chromium, 390x844, mocked backend).

Walks every visible element with direct text, resolves its effective background by walking up to the
first non-transparent background-color, and fails on text under 4.5:1 (3:1 for large text: >=24px, or
>=18.66px and bold). Elements whose own or ancestor background is an image/gradient are skipped and
listed in the failure/skip report. Companion to tests/unit/theme_no_raw_colours.test.js.

Coverage rule: a view is only guarded if a test here OPENS it with realistic data (tables with several
rows, odd and even; a race brief/debrief; a markdown table). The first version missed the raw-analysis
panel, the "Pacing & effort" / race-debrief details and markdown tables because none was ever rendered.
EXTEND this file whenever a new view is added.
"""

import json
import re

import pytest

from conftest import seed_identity  # noqa: F401  (fixture setup lives in the imported fixtures)
from test_race_day_checklist import env, _open_overlay  # noqa: F401
from test_race_view import race  # noqa: F401

SCAN_JS = r"""
(rootSel) => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
  const lin = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const L = (c) => 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b);
  const over = (top, bot) => ({ r: top.r * top.a + bot.r * (1 - top.a), g: top.g * top.a + bot.g * (1 - top.a), b: top.b * top.a + bot.b * (1 - top.a), a: 1 });
  const sel = (el) => { const parts = []; for (let e = el; e && e !== document.body && parts.length < 3; e = e.parentElement)
    parts.unshift(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (typeof e.className === 'string' && e.className.trim() ? '.' + e.className.trim().split(/\s+/).slice(0, 2).join('.') : '')); return parts.join(' > '); };
  const fails = [], skipped = [];
  const seen = new Set();
  for (const el of (rootSel ? document.querySelector(rootSel) : document.body).querySelectorAll('*')) {
    if (['SCRIPT', 'STYLE', 'SVG', 'PATH'].includes(el.tagName.toUpperCase()) || el.closest('svg')) continue;
    if (el.closest(':disabled, [aria-disabled="true"]')) continue;  // WCAG exempts inactive controls
    const text = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.textContent.trim()).join(' ').trim();
    if (!text) continue;
    const cs = getComputedStyle(el);
    const rect = el.getBoundingClientRect();
    if (cs.visibility === 'hidden' || cs.display === 'none' || rect.width === 0 || rect.height === 0) continue;
    let op = 1; for (let e = el; e; e = e.parentElement) op *= parseFloat(getComputedStyle(e).opacity);
    if (op === 0) continue;
    let bg = { r: 0, g: 0, b: 0, a: 0 }, image = false;
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.backgroundImage !== 'none') { image = true; break; }
      const c = parse(s.backgroundColor);
      if (c && c.a > 0) { layers.push(c); if (c.a === 1) break; }
    }
    if (image) { skipped.push(sel(el) + ' "' + text.slice(0, 30) + '"'); continue; }
    bg = { r: 255, g: 255, b: 255, a: 1 };
    for (const c of layers.reverse()) bg = over(c, bg);
    let fg = parse(cs.color); if (!fg) continue;
    fg = over({ ...fg, a: fg.a * op }, bg);
    const l1 = L(fg), l2 = L(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const px = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight, 10) >= 700;
    const need = px >= 24 || (px >= 18.66 && bold) ? 3 : 4.5;
    if (ratio < need) {
      const key = sel(el) + text;
      if (seen.has(key)) continue; seen.add(key);
      fails.push(`${sel(el)} "${text.slice(0, 30)}" color=${cs.color} bg=rgb(${Math.round(bg.r)}, ${Math.round(bg.g)}, ${Math.round(bg.b)}) ratio=${ratio.toFixed(2)} need=${need}`);
    }
  }
  return { fails, skipped };
}
"""


def assert_contrast(page, view, root=None):
    res = page.evaluate(SCAN_JS, root)
    if res['skipped']:
        print(f'[{view}] skipped (gradient/image background): {res["skipped"]}')
    assert not res['fails'], f'[{view}] low-contrast text:\n' + '\n'.join(res['fails'])


def test_plan_session_and_chat_contrast(env):
    page, _, _ = env
    page.set_viewport_size({'width': 390, 'height': 844})
    page.wait_for_selector('.rw-chip')
    assert_contrast(page, 'plan tab')
    page.click('[data-a="session:open"][data-id="race1"]')
    page.wait_for_selector('[data-a="session:back"]')
    assert_contrast(page, 'session detail')
    page.click('[data-a="session:back"]')
    page.click('[data-a="tab:coach"]')
    page.wait_for_timeout(300)
    assert_contrast(page, 'chat tab')


def test_race_day_overlay_contrast(env):
    page, _, _ = env
    page.set_viewport_size({'width': 390, 'height': 844})
    _open_overlay(page)
    assert_contrast(page, 'race-day checklist', '#race-overlay')
    page.click('.rd-tab[data-tab="timeline"]')
    page.fill('#raceday-start', '15:15')
    page.wait_for_selector('.rd-tl-row:has-text("Lunch")')
    assert_contrast(page, 'race-day timeline (read)', '#race-overlay')
    page.click('[data-a="raceday:tl-edit"]')
    page.wait_for_selector('.rd-tl-edit')
    assert_contrast(page, 'race-day timeline (edit)', '#race-overlay')


def test_race_view_contrast(race):
    page, _, _ = race
    if page.viewport_size['width'] != 390:
        pytest.skip('contrast scan runs at 390x844 only')
    assert_contrast(page, 'race view')
    page.click('[data-a="race:more-toggle"]')
    assert_contrast(page, 'race view (more numbers)')
    page.locator('details.rv-fold > summary', has_text='Power curve').click()
    page.locator('details.curve-prior-dates > summary').click()
    assert_contrast(page, 'race view (power curve and prior-race average)')
    page.click('[aria-label="Section analysis"] [data-a="race:section-open"][data-label="C5"]')
    page.wait_for_selector('#section-drill')
    assert_contrast(page, 'section drill-down', '#section-drill')


# --- Views the first version never rendered: raw analysis, race brief/debrief, striped tables, markdown ---

from test_workout_shape_and_analysis import (  # noqa: E402
    PLAN, WORKOUT, PACING, _make_page, _finish, _open_ride, _configure_backend,
)

CHROMIUM_390 = type('Cfg', (), {'param': {'name': 'chromium', 'vp': {'width': 390, 'height': 844}}})()
CORS = {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Authorization, Content-Type'}
CANONICAL_LAPS = [
    {'n': i + 1, 'start_lap': i == 0, 'comparable': i > 0, 'source': 'gps', 'start_s': i * 600,
     'duration_s': 600, 'distance_m': 6000 + i * 100, 'avg_power_w': 200 + i * 5, 'avg_hr': 140 + i}
    for i in range(6)
]
DEVICE_LAPS = [
    {'index': i, 'duration_s': 600, 'start_offset_s': i * 600, 'avg_power_w': 190 + i, 'distance_m': 6000, 'avg_hr': 140 + i}
    for i in range(1, 6)
]
RACE_PACING = {
    **PACING,
    'gps_laps': {'detected': 5, 'truncated': False, 'note': None, 'laps': [
        {'lap_n': i + 1, 'variability_index': 1.05 + i / 100, 'coasting_s': 30 + i, 'total_work_kj': 300 + i,
         'start_lap': i == 0} for i in range(5)]},
    'race_phases': {'significance_threshold_pct': 5.0, 'phases': [
        {'name': f'Phase {i + 1}', 'start_s': i * 900, 'end_s': (i + 1) * 900, 'normalized_power_w': 250 - i * 5,
         'avg_speed_mps': 7.0 - i / 10, 'vs_phase_1_pct': -2.0 * i, 'vs_phase_1_significant': i == 3}
        for i in range(4)]},
}
RACE_WORKOUT = {
    **WORKOUT, 'id': 'w-race', 'kind': 'race', 'planned_session_id': None, 'laps': DEVICE_LAPS,
    'analytics': {**WORKOUT['analytics'], 'laps': CANONICAL_LAPS},
}
DEBRIEF = {
    'event_date': '2026-09-29', 'event_name': 'Sunday race', 'result': '12th of 40', 'went_well': 'Start and sector 3',
    'work_on': 'Pacing the second half', 'data_findings': ['NP fell 6% after phase 3', 'Coasting rose in the last lap'],
    'training_implication': 'More threshold volume', 'tactical_note': 'Go harder before the climb',
}
MD_ROWS = '\\n'.join(f'| D{i} | 2026-07-{20 + i} | swim_pool | {3000 + i * 500}m |' for i in range(6))
MD_TABLE = f'### Week 2026-W30\\n\\n| Day | Date | Sport | Distance |\\n| --- | --- | --- | --- |\\n{MD_ROWS}'


def _json_route(body):
    return lambda r: r.fulfill(status=200, content_type='application/json', body=json.dumps(body), headers=CORS)


@pytest.fixture
def race_detail(base_url):
    pw, browser, ctx, pg, errors = _make_page(CHROMIUM_390, base_url, PLAN, workouts=[RACE_WORKOUT])
    ctx.route(re.compile(r'/api/workouts/[^/]+/pacing'), _json_route(RACE_PACING))
    ctx.route('**/api/athlete*', _json_route({'slug': 'renee', 'name': 'Renee', 'race_debriefs': [DEBRIEF]}))
    try:
        yield pg
    finally:
        _finish(pw, browser, ctx, errors)


def test_race_brief_and_raw_analysis_contrast(race_detail):
    page = race_detail
    _open_ride(page)
    page.wait_for_selector('.race-analysis')
    page.locator('.race-analysis > summary').click()
    page.locator('.race-debrief > summary').click()
    assert page.locator('.race-analysis table tbody tr').count() >= 4
    assert_contrast(page, 'workout detail: pacing & effort + race debrief (open)')
    page.locator('[data-a="workout:raw-analysis-toggle"]').click()
    page.wait_for_selector('.raw-analysis table.master-laps-table')
    assert page.locator('.raw-analysis table.master-laps-table tbody tr').count() >= 4  # odd AND even rows
    assert page.locator('.raw-analysis table.raw-table').count() >= 3
    assert_contrast(page, 'workout detail: raw analysis (open)')


def test_markdown_table_in_coach_chat_contrast(base_url):
    pw, browser, ctx, pg, errors = _make_page(CHROMIUM_390, base_url, PLAN)
    try:
        sse = f'data: {{"type":"text","text":"{MD_TABLE}"}}\n\ndata: {{"type":"done","stop_reason":"end_turn"}}\n\n'

        def chat(route):
            if route.request.method == 'OPTIONS':
                route.fulfill(status=204, headers={**CORS, 'Access-Control-Allow-Methods': 'POST'})
            else:
                route.fulfill(status=200, content_type='text/event-stream', body=sse, headers=CORS)

        ctx.route('**/api/chat', chat)
        _configure_backend(pg)
        pg.click('[data-a="tab:coach"]')
        pg.wait_for_selector('#chat-input')
        pg.fill('#chat-input', 'show the week')
        pg.click('[data-a="chat:send"]')
        pg.wait_for_selector('.chat-row.coach table tbody tr:nth-child(6)')
        assert_contrast(pg, 'coach chat markdown table')
    finally:
        _finish(pw, browser, ctx, errors)
