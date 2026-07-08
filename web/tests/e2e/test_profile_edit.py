"""e2e coverage for the self-service profile-edit form (Phase 2.5), a section
within the Settings tab (see views.js's renderProfilePanel / main.js's
loadProfile/handleSubmitProfile).

Same mocked-backend conventions as test_log_checkin.py (see its module
docstring): no real backend is ever contacted, and every network call is
intercepted via Playwright routes with CORS headers attached (the mocked
backend is a different origin, exactly like the real GitHub Pages / Cloud
Run split) -- WebKit enforces the CORS preflight strictly even against a
mocked/fulfilled response, hence the OPTIONS branch below.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity

BASE_URL = 'https://coach-api.test'
TOKEN = 'test-token-123'

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PATCH, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PROFILE_FIXTURE = {
    'schema_version': 1,
    'id': '19250c9f-945e-4578-b6c7-550a89553577',
    'slug': 'renee',
    'name': 'Renee',
    'css_pace_s_per_100m': 90.0,
    'zones': None,
    'constraints': {},
    'pool_schedule': ['monday', 'wednesday', 'friday'],
    'dob': '1990-05-01',
    'sex': 'female',
    'height_cm': 168.0,
    'weight_kg': 60.0,
}


def _athlete_route(get_body=None, patch_status=200, patch_body=None):
    """A single `**/api/athlete*` handler covering GET (prefill), PATCH
    (save) and the CORS preflight OPTIONS -- registering one route per test
    (rather than re-registering the same pattern with a second handler)
    avoids relying on Playwright's route-precedence ordering."""
    get_json = json.dumps(get_body if get_body is not None else PROFILE_FIXTURE)
    patch_json = json.dumps(patch_body if patch_body is not None else PROFILE_FIXTURE)

    def handler(route):
        method = route.request.method
        if method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
        elif method == 'GET':
            route.fulfill(status=200, content_type='application/json', body=get_json, headers=CORS_HEADERS)
        elif method == 'PATCH':
            route.fulfill(status=patch_status, content_type='application/json', body=patch_json, headers=CORS_HEADERS)
        else:
            route.fulfill(status=404, headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Seeds a signed-in identity (past the Phase 2.5 sign-in gate) but
    deliberately NOT a configured backend -- see test_log_checkin.py's `page`
    fixture docstring; same reasoning applies here (the "unconfigured" test
    below needs that empty state)."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
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


def _configure_backend(page, base_url=BASE_URL, token=TOKEN):
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('#settings-base-url')
    page.fill('#settings-base-url', base_url)
    page.fill('#settings-token', token)
    page.click('[data-a="settings:save"]')


def test_profile_panel_hidden_until_backend_configured(page):
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')
    assert page.locator('[data-form="profile"]').count() == 0


def test_profile_form_prefills_from_get_athlete(page):
    page.route('**/api/athlete*', _athlete_route())

    _configure_backend(page)
    page.wait_for_selector('[data-form="profile"][data-field="name"]')

    assert page.input_value('[data-form="profile"][data-field="name"]') == 'Renee'
    assert page.input_value('[data-form="profile"][data-field="dob"]') == '1990-05-01'
    assert page.locator('[data-form="profile"][data-field="sex"]').input_value() == 'female'
    assert page.input_value('[data-form="profile"][data-field="heightFeet"]') == '5'
    assert page.input_value('[data-form="profile"][data-field="heightInches"]') == '6'
    assert page.input_value('[data-form="profile"][data-field="weightLb"]') == '132.3'
    assert page.input_value('[data-form="profile"][data-field="cssPace"]') == '1:30'
    assert page.is_checked('[data-form="profile"][data-day="monday"]')
    assert page.is_checked('[data-form="profile"][data-day="wednesday"]')
    assert page.is_checked('[data-form="profile"][data-day="friday"]')
    assert not page.is_checked('[data-form="profile"][data-day="tuesday"]')


def test_profile_save_success_shows_saved_and_updates_form(page):
    updated = {**PROFILE_FIXTURE, 'name': 'Renee Kline'}
    page.route('**/api/athlete*', _athlete_route(patch_body=updated))

    _configure_backend(page)
    page.wait_for_selector('[data-form="profile"][data-field="name"]')

    page.fill('[data-form="profile"][data-field="name"]', 'Renee Kline')
    page.click('[data-a="profile:submit"]')

    page.wait_for_selector('.conn-result.ok')
    assert 'Saved' in page.locator('.conn-result.ok').inner_text()
    assert page.input_value('[data-form="profile"][data-field="name"]') == 'Renee Kline'


def test_profile_save_failure_shows_error_message(page):
    page.route('**/api/athlete*', _athlete_route(
        patch_status=422, patch_body={'error': 'invalid sex'},
    ))

    _configure_backend(page)
    page.wait_for_selector('[data-form="profile"][data-field="name"]')

    page.click('[data-a="profile:submit"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'invalid sex' in page.locator('.conn-result.fail').inner_text()


def test_settings_tab_includes_profile_fields_when_configured(page):
    page.route('**/api/athlete*', _athlete_route())

    _configure_backend(page)
    page.wait_for_selector('[data-form="profile"][data-field="name"]')
    assert page.locator('[data-form="profile"][data-field="dob"]').count() == 1
    assert page.locator('[data-form="profile"][data-field="sex"]').count() == 1
    assert page.locator('[data-form="profile"][data-field="cssPace"]').count() == 1
    assert page.locator('[data-a="profile:submit"]').count() == 1
