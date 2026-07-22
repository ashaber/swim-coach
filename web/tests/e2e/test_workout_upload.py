"""e2e coverage for the Log tab's .fit/.tcx/.csv file upload (Phase 3).

Same mocked-backend conventions as test_log_checkin.py: no real backend is
ever contacted, every network call is intercepted via Playwright routes with
CORS headers attached. The two-step design under test: picking a file POSTs
multipart to `**/api/workouts/ingest*` (mocked here to return a canned
`WorkoutDraft`), which pre-fills the Log form as a *review* card -- nothing
is saved until the athlete sets RPE (never present in a file) and clicks
Save/Confirm, which is the existing `POST /api/workouts` call test_log_checkin.py
already covers the JSON shape of.
"""

from __future__ import annotations

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity

BASE_URL = 'https://coach-api.test'
TOKEN = 'test-token-123'

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}

PLAN_STUB = '{"slug":"renee","athlete":{"name":"Renee"},"events":[],"weeks":[],"macro":{"blocks":[]}}'


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Same shape as test_log_checkin.py's `page` fixture: signed in, but
    deliberately NOT a configured backend (the "unconfigured" test needs
    that empty state), plus a default mocked GET /api/athlete for the
    Settings tab's profile section and a default empty GET /api/workouts
    for the Log tab's history section (see main.js's loadHistory, which
    fetches it the moment the Log tab opens -- unmocked, that fetch fails
    against this file's fake backend origin, and WebKit reports the failed
    cross-origin request as an uncaught pageerror that trips this fixture's
    teardown assertion). Registered at the *context* level so a test's own
    page.route('**/api/workouts*', ...) handler still takes precedence
    (page routes win over context routes), mirroring how
    test_workout_history.py mocks the same endpoint per-test; and the glob's
    trailing '*' never crosses a '/', so this default does NOT match
    /api/workouts/ingest -- each test's own ingest mock is unaffected."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        ctx.route(
            '**/api/athlete*',
            _cors_route(200, 'application/json', '{"slug": "renee", "name": "Renee"}'),
        )
        # Becoming "configured" (see _configure_backend) makes main.js's
        # boot sequence eagerly fire GET /api/plan (loadPlan, unconditional
        # at boot regardless of active tab) -- unmocked, that fetch fails
        # against this file's fake backend origin and WebKit surfaces it as
        # an uncaught pageerror that trips this fixture's teardown
        # assertion. This file doesn't care about the plan's content.
        ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
        ctx.route(
            '**/api/workouts*',
            _cors_route(200, 'application/json', '[]'),
        )
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
    """The backend-URL/test-connection panel is gone from Settings (paste-
    token-era leftover -- baseUrl now always defaults to prod internally,
    see settings.js's DEFAULT_BASE_URL, with no UI to edit it). Seeds both
    baseUrl and the session token directly into localStorage the way
    settings.js's own storage schema expects (`version` stamped to match
    SETTINGS_SCHEMA_VERSION, or loadSettings() would treat it as a stale
    pre-cutover value and drop the token), then reloads so main.js's boot
    picks it up -- the same pattern conftest.py's own seed_settings
    init-script helper uses, just applied mid-test via page.evaluate instead
    of before the first page load."""
    page.evaluate(
        "(cfg) => window.localStorage.setItem("
        "'swimcoach_settings', JSON.stringify({baseUrl: cfg.baseUrl, token: cfg.token, version: 2}))",
        {'baseUrl': base_url, 'token': token},
    )
    page.reload()
    # Always ends on the Settings tab -- same invariant the old
    # base-url-fill-and-save flow had (it necessarily drove the
    # Settings UI to save), which several tests below rely on (e.g.
    # the profile-edit section only renders on this tab, and
    # visiting it is what triggers main.js's maybeLoadProfile()).
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')


def _open_log_tab(page):
    """Opens the Log tab and waits for the history section's fetch to settle
    (every test in this file sees an empty list -- the fixture's default
    workouts mock or the test's own -- so settled always means the
    empty-state message) before expanding the secondary manual-entry/upload
    section (Phase 3: "Sync from watch" is now the primary action; the file
    input lives behind the "Log manually / upload a file" toggle, collapsed
    by default -- see main.js's state.logManualOpen) and waiting for the
    file input itself. The settle-before-interact ordering matters just as
    much as before: opening the tab fires GET /api/workouts (main.js's
    loadHistory), and its completion render replaces the whole #app subtree
    via innerHTML -- a toggle click or file input resolved before that
    render can hit a detached node, and a change event fired on a detached
    node never bubbles to #app's delegated listener, silently swallowing
    the upload (the intermittent chromium timeout in CI: no .conn-result
    ever renders)."""
    page.click('[data-a="tab:log"]')
    page.wait_for_selector('text=No workouts logged yet.')
    page.click('[data-a="log:toggle-manual"]')
    page.wait_for_selector('[data-a="log:file-select"]')


_DRAFT_WITH_WARNING = {
    'schema_version': 1,
    'date': '2026-07-09',
    'sport': 'cross_train',
    'source': 'fit',
    'distance_m': 5029,
    'duration_min': 181.5,
    'avg_pace_s_per_100m': None,
    'rpe': None,
    'sets': [],
    'planned_session_id': None,
    'raw_ref': '/tmp/upload.fit',
    'notes': None,
    'warnings': [
        "non-swim FIT sport 'kayaking' mapped to cross_train (counts toward sRPE load, not swim volume)",
    ],
}

_DRAFT_TCX_CLEAN = {
    'schema_version': 1,
    'date': '2026-07-06',
    'sport': 'swim_pool',
    'source': 'tcx',
    'distance_m': 2500,
    'duration_min': 45.0,
    'avg_pace_s_per_100m': 108.0,
    'rpe': None,
    'sets': [],
    'planned_session_id': None,
    'raw_ref': None,
    'notes': None,
    'warnings': [],
}


def test_log_tab_shows_file_input_when_configured(page):
    _configure_backend(page)
    _open_log_tab(page)
    assert page.locator('[data-a="log:file-select"]').count() == 1


def test_log_upload_prefills_form_and_shows_warnings(page):
    page.route('**/api/workouts/ingest*', _cors_route(200, 'application/json', json.dumps(_DRAFT_WITH_WARNING)))

    _configure_backend(page)
    _open_log_tab(page)
    page.set_input_files(
        '[data-a="log:file-select"]',
        files=[{'name': 'kayak.fit', 'mimeType': 'application/octet-stream', 'buffer': b'fake fit bytes'}],
    )

    page.wait_for_selector('.conn-result.ok')
    assert page.input_value('[data-form="log"][data-field="date"]') == '2026-07-09'
    assert page.input_value('[data-form="log"][data-field="sport"]') == 'cross_train'
    assert page.input_value('[data-form="log"][data-field="distance_m"]') == '5029'
    assert page.input_value('[data-form="log"][data-field="duration_min"]') == '181.5'
    assert 'kayaking' in page.content()
    assert 'cross_train' in page.content()


def test_log_upload_requires_rpe_before_save_is_enabled(page):
    page.route('**/api/workouts/ingest*', _cors_route(200, 'application/json', json.dumps(_DRAFT_TCX_CLEAN)))

    _configure_backend(page)
    _open_log_tab(page)
    page.set_input_files(
        '[data-a="log:file-select"]',
        files=[{'name': 'swim.tcx', 'mimeType': 'application/octet-stream', 'buffer': b'<fake/>'}],
    )
    page.wait_for_selector('.conn-result.ok')

    save_btn = page.locator('[data-a="log:submit"]')
    assert save_btn.is_disabled()

    page.locator('[data-form="log"][data-field="rpe"]').fill('7')
    assert not save_btn.is_disabled()


def test_log_upload_confirm_save_sends_parsed_source_and_rpe(page):
    page.route('**/api/workouts/ingest*', _cors_route(200, 'application/json', json.dumps(_DRAFT_TCX_CLEAN)))

    captured = {}

    def capture_and_save(route):
        if route.request.method == 'POST':
            captured['body'] = json.loads(route.request.post_data)
            _cors_route(200, 'application/json', '{"id": "w1", "date": "2026-07-06", "source": "tcx"}')(route)
        else:
            _cors_route(200, 'application/json', '[]')(route)

    page.route('**/api/workouts*', capture_and_save)

    _configure_backend(page)
    _open_log_tab(page)
    page.set_input_files(
        '[data-a="log:file-select"]',
        files=[{'name': 'swim.tcx', 'mimeType': 'application/octet-stream', 'buffer': b'<fake/>'}],
    )
    page.wait_for_selector('.conn-result.ok')
    page.locator('[data-form="log"][data-field="rpe"]').fill('6')
    page.click('[data-a="log:submit"]')

    page.wait_for_selector('.conn-result.ok:not(:has-text("Parsed"))')
    assert captured['body']['source'] == 'tcx'
    assert captured['body']['rpe'] == 6
    assert captured['body']['distance_m'] == 2500


def test_log_upload_unsupported_file_type_shows_error_without_network_call(page):
    ingest_calls = []
    page.route('**/api/workouts/ingest*', lambda route: (ingest_calls.append(1), route.abort())[-1])

    _configure_backend(page)
    _open_log_tab(page)
    page.set_input_files(
        '[data-a="log:file-select"]',
        files=[{'name': 'photo.heic', 'mimeType': 'image/heic', 'buffer': b'not a workout'}],
    )

    page.wait_for_selector('.conn-result.fail')
    assert 'unsupported' in page.locator('.conn-result.fail').inner_text().lower()
    assert ingest_calls == []


def test_log_upload_parse_failure_shows_backend_error_message(page):
    page.route(
        '**/api/workouts/ingest*',
        _cors_route(422, 'application/json', '{"error": "could not parse corrupt.fit: bad header"}'),
    )

    _configure_backend(page)
    _open_log_tab(page)
    page.set_input_files(
        '[data-a="log:file-select"]',
        files=[{'name': 'corrupt.fit', 'mimeType': 'application/octet-stream', 'buffer': b'garbage'}],
    )

    page.wait_for_selector('.conn-result.fail')
    assert 'could not parse' in page.locator('.conn-result.fail').inner_text().lower()


def test_log_upload_file_too_large_shows_backend_error_message(page):
    page.route(
        '**/api/workouts/ingest*',
        _cors_route(413, 'application/json', '{"error": "file too large; max 10 MB"}'),
    )

    _configure_backend(page)
    _open_log_tab(page)
    page.set_input_files(
        '[data-a="log:file-select"]',
        files=[{'name': 'huge.csv', 'mimeType': 'text/csv', 'buffer': b'x' * 1024}],
    )

    page.wait_for_selector('.conn-result.fail')
    assert 'too large' in page.locator('.conn-result.fail').inner_text().lower()


def test_log_tab_offline_disables_file_input(page):
    _configure_backend(page)
    _open_log_tab(page)

    ctx = page.context
    ctx.set_offline(True)
    try:
        page.wait_for_selector('.chat-banner', timeout=5000)
        assert 'offline' in page.content().lower()
        assert page.locator('[data-a="log:file-select"]').is_disabled()
    finally:
        ctx.set_offline(False)
