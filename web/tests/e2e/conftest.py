import json
import os
import subprocess
import threading
import http.server
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

# rootpath for this pytest.ini is web/ (pytest sets config.rootpath to the
# directory containing pytest.ini automatically).
BROWSERS = [
    pytest.param({'name': 'chromium', 'vp': {'width': 412, 'height': 915}}, id='chromium'),
    pytest.param({'name': 'webkit',   'vp': {'width': 390, 'height': 844}}, id='webkit'),
]

# A signed-in identity pre-seeded into localStorage (under the same
# 'swimcoach_identity' key src/identity.js itself writes after a real Google
# Sign-In) so most e2e tests exercise the app in its normal signed-in state
# rather than the sign-in gate added in Phase 2.5 -- this is a *test*
# fixture, not real auth (see identity.js's module docstring: identity is
# client-side-only / UX, never a security boundary). 'renee' is used here
# (not 'andrew') so it lines up with the real exported plan data
# (public/data/renee.json / dist/data/renee.json) that test_app.py asserts
# against.
MOCK_IDENTITY = {'email': 'renee_email_placeholder@gmail.com', 'athlete': 'renee', 'role': 'athlete'}

# A pre-configured backend, seeded the same way. Only the base `page` fixture
# below seeds this by default -- test_coach_chat.py / test_log_checkin.py
# override `page` and deliberately do NOT seed settings, so their
# "unconfigured" test cases (no backend URL/token yet) still exercise that
# empty state; they configure it themselves via the real Settings UI
# (`_configure_backend`) when a test needs it.
MOCK_SETTINGS = {'baseUrl': 'https://mock-backend.test', 'token': 'test-e2e-token'}


def _web_root(config: pytest.Config) -> str:
    return str(config.rootpath)


def seed_identity(ctx, identity=None) -> None:
    """Seeds a resolved identity into localStorage via an init script, run
    before every page load in this browser context -- the same restore-on-
    load path identity.js's currentIdentity() itself uses, just skipping the
    real (network-dependent) Google Sign-In flow."""
    ctx.add_init_script(
        f"window.localStorage.setItem('swimcoach_identity', {json.dumps(json.dumps(identity or MOCK_IDENTITY))});",
    )


def seed_settings(ctx, settings=None) -> None:
    """Same idea as seed_identity, for the backend URL + token (settings.js's
    STORAGE_KEY)."""
    ctx.add_init_script(
        f"window.localStorage.setItem('swimcoach_settings', {json.dumps(json.dumps(settings or MOCK_SETTINGS))});",
    )


def mock_plan_route(ctx, root: str) -> None:
    """Mocks GET **/api/plan* with the real exported Renee plan JSON (the
    same file the old static-file-reading Plan tab used to load directly),
    so Plan-tab tests keep exercising real plan data end-to-end even though
    the Plan tab now fetches it live from the backend instead of a baked
    data/<slug>.json (see main.js's loadPlan / api.js's fetchPlan)."""
    body = (Path(root) / 'dist' / 'data' / 'renee.json').read_text()

    def handler(route):
        route.fulfill(status=200, content_type='application/json', body=body)

    ctx.route('**/api/plan*', handler)


class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, root: str, **kwargs):
        super().__init__(*args, directory=os.path.join(root, 'dist'), **kwargs)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture(scope='session')
def web_root(pytestconfig: pytest.Config) -> str:
    return _web_root(pytestconfig)


@pytest.fixture(scope='session')
def base_url(web_root: str) -> str:
    subprocess.run(['npm', 'run', 'build'], cwd=web_root, check=True)

    def handler_factory(*args, **kwargs):
        return _Handler(*args, root=web_root, **kwargs)

    httpd = http.server.HTTPServer(('127.0.0.1', 0), handler_factory)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    # 'localhost' (not the bare IP) is what WebKit treats as a trustworthy
    # origin for service-worker registration under plain HTTP.
    yield f'http://localhost:{port}'
    httpd.shutdown()


@pytest.fixture(params=BROWSERS)
def page(request, base_url: str, web_root: str):
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'])
        # This base `page` fixture (used by test_app.py) starts fully signed
        # in and configured, with a mocked live /api/plan -- test_app.py is
        # about Plan-tab rendering of real data, not the identity gate itself
        # (see test_identity_gate.py for that).
        seed_identity(ctx)
        seed_settings(ctx)
        mock_plan_route(ctx, web_root)
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
