"""e2e coverage for web/resources-hotfix fix 1: a saved identity from BEFORE
the Resources/library-admin deploy never became admin, because
`isLibraryAdmin`/`coachFor` were only ever written into localStorage at
Google sign-in time. main.js now calls GET /api/me once at app boot
(best-effort) and merges any change into the saved identity -- this proves
a saved non-admin identity actually becomes admin once /api/me reports it,
without the athlete having to sign out and back in.

Same mocked-backend / CORS-preflight conventions as test_resources.py.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'
PLAN_LOAD_STUB = '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'

# Saved BEFORE the Resources/library-admin deploy -- isLibraryAdmin: false,
# same as a real pre-existing identity.js localStorage value would default
# to (see identity.js's loadIdentity doc comment).
NON_ADMIN_IDENTITY = {'name': 'Renee', 'athlete': 'renee', 'role': 'athlete', 'coachFor': [], 'isLibraryAdmin': False}

ME_RESPONSE_ADMIN = json.dumps({
    'athlete': 'renee', 'name': 'Renee', 'role': 'athlete', 'coach_for': [], 'is_library_admin': True,
})


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _make_ctx(pw, cfg):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx, identity=NON_ADMIN_IDENTITY)
    seed_settings(ctx)
    ctx.route('**/api/me*', _cors_route(200, 'application/json', ME_RESPONSE_ADMIN))
    ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
    ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
    ctx.route('**/api/athlete*', _cors_route(200, 'application/json', '{"slug": "renee", "name": "Renee"}'))
    ctx.route('**/api/grants*', _cors_route(200, 'application/json', '[]'))
    ctx.route('**/api/library/cards*', _cors_route(200, 'application/json', '[]'))
    return browser, ctx


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    cfg = request.param
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg)
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


def test_saved_non_admin_identity_becomes_admin_after_api_me_refresh(page):
    # Before the boot-time /api/me refresh resolves, the saved identity is
    # still non-admin -- the Resources tab's admin-only Approvals section
    # (views.js's renderApprovalsSection, gated on isAdmin) is absent.
    page.wait_for_selector('.tabbar')
    page.click('[data-a="tab:resources"]')
    page.wait_for_selector('.s-head')
    # The best-effort /api/me refresh (main.js's maybeRefreshIdentityAdminFlags,
    # fired once at boot) resolves asynchronously -- poll for the
    # admin-only "Approvals" heading to appear once it does, rather than
    # asserting an instantaneous state.
    page.wait_for_selector('h2:has-text("Approvals")', timeout=5000)
    assert page.locator('h2:has-text("Approvals")').count() == 1

    # And the refreshed flag survives a reload (persisted via saveIdentity).
    page.reload()
    page.wait_for_selector('.tabbar')
    page.click('[data-a="tab:resources"]')
    page.wait_for_selector('h2:has-text("Approvals")', timeout=5000)
