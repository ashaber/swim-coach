"""e2e: rendered WCAG contrast guard (Chromium, 390x844, mocked backend).

Walks every visible element with direct text, resolves its effective background by walking up to the
first non-transparent background-color, and fails on text under 4.5:1 (3:1 for large text: >=24px, or
>=18.66px and bold). Elements whose own or ancestor background is an image/gradient are skipped and
listed in the failure/skip report. Companion to tests/unit/theme_no_raw_colours.test.js.
"""

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
    page.click('[aria-label="Section analysis"] [data-a="race:section-open"][data-label="C5"]')
    page.wait_for_selector('#section-drill')
    assert_contrast(page, 'section drill-down', '#section-drill')
