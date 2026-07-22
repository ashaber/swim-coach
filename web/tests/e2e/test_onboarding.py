"""e2e coverage for the first-login self-service onboarding form (Slice 3 of
self-service in-app onboarding -- docs/design-self-service-onboarding.md;
stacks on Slice 1 #67's onboarding-scoped sessions and Slice 2 #68's
POST /api/onboard).

Same "never exercise the real GSI script" convention as
test_identity_gate.py -- these tests stub `window.google.accounts.id` (see
that file's `_FAKE_GSI_INIT_SCRIPT`/`fake_gsi_page` fixture, replicated here)
and fire the credential callback manually with a fake ID token, standing in
for a real Google popup. `POST /api/auth/google` is mocked to return the
ONBOARDING branch (`{onboarding: true, athlete: null, token, ...}` -- see
backend/app/routes/auth.py's doc comment) rather than an ordinary
athlete-bound session, so these tests exercise exactly the branch
test_identity_gate.py's own fixtures don't cover.
"""

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS

CORS_HEADERS = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Authorization, Content-Type',
}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


PLAN_STUB = '{"slug":"jamie","athlete":{"name":"Jamie"},"events":[],"weeks":[],"macro":{"blocks":[]}}'
ONBOARDING_SESSION = (
    '{"token":"onboard-tok-abc","athlete":null,"onboarding":true,'
    '"role":"onboarding","expires_at":"2026-08-01T00:00:00Z"}'
)
ATHLETE_SESSION = (
    '{"token":"athlete-tok-xyz","athlete":"jamie","name":"Jamie",'
    '"role":"athlete","expires_at":"2026-08-01T00:00:00Z"}'
)

# A minimal fake of window.google.accounts.id -- same stub
# test_identity_gate.py installs, just duplicated here (each e2e file is
# self-contained about what browser/network surface it needs, per this
# repo's existing convention -- see e.g. test_profile_edit.py's own
# _athlete_route rather than importing test_log_checkin.py's).
_FAKE_GSI_INIT_SCRIPT = """
(() => {
  window.google = {
    accounts: {
      id: {
        initialize: (opts) => { window.__gsiCallback = opts.callback; },
        renderButton: () => {},
        prompt: () => {},
        disableAutoSelect: () => {},
      },
    },
  };
})();
"""


@pytest.fixture(params=BROWSERS)
def fake_gsi_page(request, base_url):
    """A fresh, signed-out context with the fake GSI stub installed and the
    real Google script network blocked -- see test_identity_gate.py's
    identical fixture for the full rationale."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        ctx.route('https://accounts.google.com/**', lambda route: route.abort())
        ctx.add_init_script(_FAKE_GSI_INIT_SCRIPT)
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


def _sign_in_to_onboarding(page):
    """Drives the fake GSI callback through a mocked POST /api/auth/google
    that resolves to the onboarding branch -- the shared setup every test
    below needs before it can see the onboarding form at all."""
    page.route('**/api/auth/google', _cors_route(200, 'application/json', ONBOARDING_SESSION))
    page.wait_for_selector('.settings-wrap')
    page.wait_for_function('() => typeof window.__gsiCallback === "function"')
    page.evaluate("() => window.__gsiCallback({credential: 'fake-id-token'})")


def _fill_required_fields(page):
    page.fill('[data-form="onboard"][data-field="name"]', 'Jamie')
    page.fill('[data-form="onboard"][data-field="cssPace"]', '1:40')
    page.fill('[data-form="onboard"][data-field="eventName"]', 'Catalina Channel')
    page.fill('[data-form="onboard"][data-field="eventDate"]', '2027-08-01')
    page.fill('[data-form="onboard"][data-field="eventDistanceM"]', '33300')


def test_onboarding_session_shows_the_form_not_the_normal_tabs(fake_gsi_page):
    page = fake_gsi_page
    _sign_in_to_onboarding(page)

    page.wait_for_selector('[data-form="onboard"][data-field="name"]')
    assert "let's set up your plan" in page.content().lower()
    # No tab bar at all -- onboarding is a full-screen gate, not one more tab
    # (see main.js's render(), which returns early before renderTabBar()).
    assert page.locator('.tabbar').count() == 0
    # The onboarding token was persisted, but NOT as a finished sign-in --
    # no identity was ever saved, so isConfigured() (and everything gated on
    # it) stays false.
    identity = page.evaluate("() => window.localStorage.getItem('swimcoach_identity')")
    assert identity is None
    token = page.evaluate(
        "() => JSON.parse(window.localStorage.getItem('swimcoach_settings') || '{}').token",
    )
    assert token == 'onboard-tok-abc'


def test_onboarding_submit_blocked_client_side_until_required_fields_are_filled(fake_gsi_page):
    page = fake_gsi_page
    _sign_in_to_onboarding(page)
    page.wait_for_selector('[data-form="onboard"][data-field="name"]')

    onboard_calls = []

    def handle_onboard(route):
        onboard_calls.append(1)
        route.abort()

    page.route('**/api/onboard', handle_onboard)

    page.click('[data-a="onboard:submit"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'name is required' in page.content().lower()
    # Client-side validation caught it -- POST /api/onboard was never called.
    assert not onboard_calls


def test_onboarding_submit_success_transitions_into_the_app(fake_gsi_page):
    page = fake_gsi_page
    _sign_in_to_onboarding(page)
    page.wait_for_selector('[data-form="onboard"][data-field="name"]')

    onboard_request_bodies = []

    def handle_onboard(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        onboard_request_bodies.append(route.request.post_data)
        route.fulfill(status=200, content_type='application/json', body=ATHLETE_SESSION, headers=CORS_HEADERS)

    page.route('**/api/onboard', handle_onboard)
    page.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
    page.route('**/api/athlete*', _cors_route(200, 'application/json', '{"slug":"jamie","name":"Jamie"}'))

    _fill_required_fields(page)
    page.click('[data-a="onboard:submit"]')

    # Lands on the ordinary tabbed app, straight on the newly-provisioned
    # athlete's Plan tab -- the onboarding form (and its full-screen gate)
    # is gone.
    page.wait_for_selector('.mast h1')
    assert page.locator('.tab-btn.active').get_attribute('data-a') == 'tab:plan'
    assert page.locator('[data-form="onboard"]').count() == 0
    assert onboard_request_bodies, 'expected POST /api/onboard to have fired'

    # The athlete-bound session replaced the onboarding one.
    identity = page.evaluate(
        "() => JSON.parse(window.localStorage.getItem('swimcoach_identity') || '{}')",
    )
    assert identity == {'name': 'Jamie', 'athlete': 'jamie', 'role': 'athlete'}
    token = page.evaluate(
        "() => JSON.parse(window.localStorage.getItem('swimcoach_settings') || '{}').token",
    )
    assert token == 'athlete-tok-xyz'
    # The "mid-onboarding" flag is cleared -- a reload must not bounce back
    # into the onboarding form now that there's a real athlete.
    onboarding_flag = page.evaluate(
        "() => window.localStorage.getItem('swimcoach_onboarding_active')",
    )
    assert onboarding_flag is None

    # Settings reflects the newly-provisioned athlete, same as an ordinary
    # sign-in would (see test_identity_gate.py's equivalent assertion).
    page.click('[data-a="tab:settings"]')
    page.wait_for_selector('.settings-wrap')
    assert 'Jamie' in page.content()


def test_onboarding_conflict_shows_error_and_keeps_entered_data(fake_gsi_page):
    page = fake_gsi_page
    _sign_in_to_onboarding(page)
    page.wait_for_selector('[data-form="onboard"][data-field="name"]')

    page.route(
        '**/api/onboard',
        _cors_route(409, 'application/json', '{"error": "this invite has already been completed"}'),
    )

    _fill_required_fields(page)
    page.click('[data-a="onboard:submit"]')

    page.wait_for_selector('.conn-result.fail')
    assert 'already been completed' in page.content().lower()
    # Still on the onboarding form (not bounced to the sign-in gate), and the
    # athlete's entered data survived the failed submit -- they shouldn't
    # have to retype everything.
    assert page.locator('.tabbar').count() == 0
    assert page.input_value('[data-form="onboard"][data-field="name"]') == 'Jamie'
    assert page.input_value('[data-form="onboard"][data-field="eventName"]') == 'Catalina Channel'


def test_onboarding_state_survives_a_reload(fake_gsi_page):
    """A reload mid-form-fill (e.g. the PWA getting backgrounded and killed)
    must still show the onboarding form, not silently drop back to the
    plain sign-in gate with no explanation -- see src/onboarding.js's
    saveOnboardingActive/loadOnboardingActive doc comment."""
    page = fake_gsi_page
    _sign_in_to_onboarding(page)
    page.wait_for_selector('[data-form="onboard"][data-field="name"]')

    page.reload()

    page.wait_for_selector('[data-form="onboard"][data-field="name"]')
    assert page.locator('.tabbar').count() == 0
