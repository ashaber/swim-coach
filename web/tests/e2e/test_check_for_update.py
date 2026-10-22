"""e2e coverage for Settings -> "App version" (Check for update).

`navigator.serviceWorker.register` is stubbed with a fake registration whose
`update()` finds nothing newer, so vite-plugin-pwa's registerSW hands main.js a
registration without a real service worker (real ones are blocked in e2e).
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

FAKE_SW_SCRIPT = """
(() => {
  const reg = new EventTarget();
  Object.assign(reg, {
    installing: null, waiting: null, scope: '/',
    active: { state: 'activated', scriptURL: '/sw.js', addEventListener() {}, removeEventListener() {} },
    update() {
      window.__updateCalls = (window.__updateCalls || 0) + 1;
      return new Promise((resolve) => setTimeout(resolve, 400));
    },
  });
  const fakeRegister = () => Promise.resolve(reg);
  ServiceWorkerContainer.prototype.register = fakeRegister;
  Object.defineProperty(navigator.serviceWorker, 'register', { value: fakeRegister, configurable: true });
})();
"""


def _cors_json(body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=200, content_type='application/json', body=body, headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        seed_settings(ctx)
        ctx.add_init_script(FAKE_SW_SCRIPT)
        ctx.route('**/api/plan/load*', _cors_json(json.dumps({'athlete': 'renee', 'weeks': 12, 'ctl_atl_tsb': []})))
        ctx.route('**/api/plan*', _cors_json(json.dumps({
            'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [],
        })))
        ctx.route('**/api/athlete*', _cors_json('{"slug": "renee", "name": "Renee"}'))
        ctx.route('**/api/grants*', _cors_json('[]'))
        ctx.route('**/api/grants/*', _cors_json('[]'))
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            yield pg, ctx
        finally:
            ctx.close()
            browser.close()


def _open_settings(pg):
    pg.click('[data-a="tab:settings"]')
    pg.wait_for_selector('[data-update-check="idle"]')


def test_check_reports_latest_version_with_reload_anyway(page):
    pg, _ = page
    _open_settings(pg)
    pg.click('[data-a="pwa:check"]')
    assert pg.locator('[data-a="pwa:check"]').is_disabled()
    assert 'Checking' in pg.locator('[data-update-check="checking"]').inner_text()
    pg.wait_for_selector('[data-update-check="latest"]')
    text = pg.locator('[data-update-check="latest"]').inner_text()
    assert "You're on the latest version" in text
    assert 'UTC' in text
    assert pg.locator('[data-a="pwa:reload-anyway"]').count() == 1
    assert pg.evaluate('window.__updateCalls') >= 1


def test_check_button_disabled_offline(page):
    pg, ctx = page
    _open_settings(pg)
    ctx.set_offline(True)
    pg.wait_for_selector('text=Needs a connection')
    assert pg.locator('[data-a="pwa:check"]').is_disabled()
    ctx.set_offline(False)
    pg.wait_for_function("!document.querySelector('[data-a=\"pwa:check\"]').disabled")
