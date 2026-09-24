"""e2e coverage for the Resources tab (research-library review cards,
web/resources-tab-library-review) -- plus proof that the retired Check-in
and Feedback tabs are actually gone from the nav, and that a stale saved
active-tab value for either falls back gracefully to Plan.

Same mocked-backend conventions as the rest of this suite: no real backend
is ever contacted, and every network call is intercepted via Playwright
routes with CORS headers attached.
"""

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
PLAN_LOAD_STUB = '{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'

REVIEWED_CARD = {
    'file': '07-strength-dryland.md',
    'section': 'session-duration-45-minutes',
    'heading': 'Session duration: 45 minutes',
    'summary': 'A 45-minute strength session fits a real stimulus without crowding the rest of the week.',
    'recommendation': 'none -- background only',
    'confidence': 'high',
    'tags': ['[EVIDENCE: swim]'],
    'source_count': 2,
    'weak_source_count': 0,
    'dossier': None,
    'reviewed': True,
    'needs_judgment': False,
    'stale': False,
    'content_hash': 'reviewedhash',
    'latest_review': None,
}
UNREVIEWED_CARD = {
    'file': '13-reds-energy-availability.md',
    'section': 'gaps-stated-bluntly',
    'heading': 'Gaps, stated bluntly',
    'summary': 'Lists what remains unstudied for this population.',
    'recommendation': 'none -- background only',
    'confidence': 'medium',
    'tags': [],
    'source_count': 0,
    'weak_source_count': 0,
    'dossier': None,
    'reviewed': False,
    'needs_judgment': True,
    'stale': False,
    'content_hash': 'unreviewedhash',
    'latest_review': None,
}
CARDS_JSON = json.dumps([REVIEWED_CARD, UNREVIEWED_CARD])
# Both cards' headings appear in this one mocked file body (the mocked route
# below serves it for any requested filename), with a tall filler block
# between them -- long enough that "scrolled to the heading" and "scrolled
# to the top" are actually distinguishable by window.scrollY (web/
# resources-hotfix fix 2's own scroll-position tests rely on this).
FILE_CONTENT = (
    '# Strength & dryland programming\n\n'
    '## Session duration: 45 minutes\n\nReal section body text.\n\n'
    + ('Filler paragraph text to create scroll height.\n\n' * 120)
    + '## Gaps, stated bluntly\n\nApproval section body text.\n'
)
FILE_BODY = json.dumps({'file': '07-strength-dryland.md', 'content': FILE_CONTENT})

ADMIN_IDENTITY = {'name': 'Andrew', 'athlete': 'andrew', 'role': 'athlete', 'coachFor': [], 'isLibraryAdmin': True}
NON_ADMIN_IDENTITY = {'name': 'Renee', 'athlete': 'renee', 'role': 'athlete', 'coachFor': [], 'isLibraryAdmin': False}


def _cors_route(status, content_type, body):
    def handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        route.fulfill(status=status, content_type=content_type, body=body, headers=CORS_HEADERS)
    return handler


def _make_ctx(pw, cfg, *, identity=None, seed_cards_cache=None, seed_file_cache=None):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
    seed_identity(ctx, identity or NON_ADMIN_IDENTITY)
    ctx.add_init_script(
        "window.localStorage.setItem('swimcoach_settings', "
        f"{json.dumps(json.dumps({'baseUrl': BASE_URL, 'token': TOKEN, 'version': 2}))});",
    )
    if seed_cards_cache is not None:
        ctx.add_init_script(
            "window.localStorage.setItem('swimcoach_library_cards_cache', "
            f"{json.dumps(json.dumps(seed_cards_cache))});",
        )
    if seed_file_cache is not None:
        ctx.add_init_script(
            "window.localStorage.setItem('swimcoach_library_files_cache', "
            f"{json.dumps(json.dumps(seed_file_cache))});",
        )
    ctx.route('**/api/athlete*', _cors_route(200, 'application/json', '{"slug": "renee", "name": "Renee"}'))
    ctx.route('**/api/grants*', _cors_route(200, 'application/json', '[]'))
    ctx.route('**/api/plan*', _cors_route(200, 'application/json', PLAN_STUB))
    ctx.route('**/api/plan/load*', _cors_route(200, 'application/json', PLAN_LOAD_STUB))
    ctx.route('**/api/library/cards*', _cors_route(200, 'application/json', CARDS_JSON))
    ctx.route('**/api/library/files/*', _cors_route(200, 'application/json', FILE_BODY))
    return browser, ctx


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Signed in as a non-admin athlete, backend already configured (no
    separate _configure_backend step needed -- settings are seeded via
    init script here, unlike the other e2e files, since every test in
    this module needs a configured backend from the start)."""
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


@pytest.fixture(params=BROWSERS)
def admin_page(request, base_url):
    """Same as `page`, signed in as a library admin instead."""
    cfg = request.param
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, identity=ADMIN_IDENTITY)
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


# --- proof the old tabs are gone ------------------------------------------------

def test_resources_tab_is_in_the_nav_checkin_and_feedback_are_not(page):
    page.wait_for_selector('.tabbar')
    assert page.locator('[data-a="tab:resources"]').count() == 1
    assert page.locator('[data-a="tab:checkin"]').count() == 0
    assert page.locator('[data-a="tab:feedback"]').count() == 0
    assert 'Check-in' not in page.content()


@pytest.mark.parametrize('stale_tab', ['checkin', 'feedback'])
def test_stale_saved_tab_falls_back_to_plan(page, stale_tab):
    page.evaluate("(t) => window.localStorage.setItem('swimcoach_active_tab', t)", stale_tab)
    page.reload()
    page.wait_for_selector('.tabbar')
    active = page.locator('.tab-btn.active')
    assert active.get_attribute('data-a') == 'tab:plan'


# --- Research library section -----------------------------------------------

def test_resources_tab_renders_cards_with_badges(page):
    page.click('[data-a="tab:resources"]')
    page.wait_for_selector('.library-card')
    content = page.content()
    assert 'Session duration: 45 minutes' in content
    assert 'high confidence' in content
    assert 'Reviewed' in content
    assert 'Unreviewed' in content
    assert 'Gaps, stated bluntly' in content


def test_resources_filter_chips_narrow_the_list(page):
    page.click('[data-a="tab:resources"]')
    page.wait_for_selector('.library-card')
    page.click('[data-filter="needs_review"]')
    page.wait_for_selector('text=Gaps, stated bluntly')
    assert 'Session duration: 45 minutes' not in page.content()


def test_resources_read_full_section_opens_file_and_back_returns(page):
    page.click('[data-a="tab:resources"]')
    page.wait_for_selector('.library-card')
    page.locator('[data-a="library:open-file"]').first.click()
    page.wait_for_selector('#library-file-content')
    assert 'Real section body text.' in page.content()

    page.click('[data-a="library:close-file"]')
    page.wait_for_selector('.library-card')


# --- Detail-view scroll position (web/resources-hotfix fix 2) ---------------
# Opening a file from the Research library list should land at the top;
# opening it from an Approvals card (a specific to-be-reviewed section)
# should land scrolled to that section's heading. Before this fix, both
# just kept whatever scroll position the card grid happened to have.

def test_opening_from_the_research_library_list_scrolls_to_top(page):
    page.click('[data-a="tab:resources"]')
    page.wait_for_selector('.library-card')
    # Scroll down first, so landing at the top is actually observable.
    page.evaluate('window.scrollTo(0, 400)')
    assert page.evaluate('window.scrollY') > 0
    page.locator('[data-a="library:open-file"]').first.click()
    page.wait_for_selector('#library-file-content')
    assert page.evaluate('window.scrollY') == 0


def test_opening_from_an_approvals_card_scrolls_to_its_heading(admin_page):
    admin_page.click('[data-a="tab:resources"]')
    admin_page.wait_for_selector('.library-card')
    admin_page.wait_for_selector('h2:has-text("Approvals")')
    # The Approvals card's own "Read full section" button (UNREVIEWED_CARD,
    # heading "Gaps, stated bluntly" -- far down FILE_CONTENT's filler
    # block, well past a scroll-to-top position).
    approvals = admin_page.locator('section', has=admin_page.locator('h2', has_text='Approvals'))
    approvals.locator('[data-a="library:open-file"]').click()
    admin_page.wait_for_selector('#library-file-content')
    admin_page.wait_for_function('() => window.scrollY > 200')


# --- Hardware/gesture back (web/resources-hotfix fix 3) ---------------------
# The library detail view had no history entry at all before this fix, so a
# hardware/gesture back press closed the whole PWA instead of just the
# detail. page.go_back() is Playwright's proxy for that back press -- same
# pattern as test_coach_roster.py's test_hardware_back_closes_workout_detail_
# not_the_app / test_workout_detail.py's own hardware-back test.

def test_hardware_back_closes_library_detail_not_the_app(page):
    page.click('[data-a="tab:resources"]')
    page.wait_for_selector('.library-card')
    page.locator('[data-a="library:open-file"]').first.click()
    page.wait_for_selector('#library-file-content')

    page.go_back()
    page.wait_for_selector('.library-card')
    assert page.locator('#library-file-content').count() == 0
    # Prove the app didn't navigate away entirely -- the tab bar is still
    # there, not a blank/exited page.
    assert page.locator('.tabbar').count() == 1
    assert page.locator('[data-a="tab:resources"]').count() == 1


# --- Approvals (admin-only) --------------------------------------------------

def test_resources_hides_approvals_for_non_admin(page):
    page.click('[data-a="tab:resources"]')
    page.wait_for_selector('.library-card')
    # Scoped to #app (not the whole page.content(), which also contains
    # this file's own inline <style> block -- and the word "Approvals" in
    # one of its comments).
    assert 'Approvals' not in page.locator('#app').inner_text()


def test_resources_shows_approvals_for_admin(admin_page):
    admin_page.click('[data-a="tab:resources"]')
    admin_page.wait_for_selector('.library-card')
    content = admin_page.content()
    assert 'Approvals' in content
    # Only the unreviewed card shows in Approvals.
    assert 'Needs judgment' in content


def test_resources_accept_flow_refreshes_the_card(admin_page):
    accepted = dict(UNREVIEWED_CARD)
    accepted['reviewed'] = True
    accepted['latest_review'] = {'decision': 'accepted', 'note': None}

    state = {'accepted': False}

    def cards_handler(route):
        body = json.dumps([REVIEWED_CARD, accepted if state['accepted'] else UNREVIEWED_CARD])
        route.fulfill(status=200, content_type='application/json', body=body, headers=CORS_HEADERS)

    def review_handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        state['accepted'] = True
        route.fulfill(
            status=200, content_type='application/json',
            body='{"id": "r1", "decision": "accepted"}', headers=CORS_HEADERS,
        )

    admin_page.route('**/api/library/cards*', cards_handler)
    admin_page.route('**/api/library/reviews*', review_handler)

    admin_page.click('[data-a="tab:resources"]')
    admin_page.wait_for_selector('.library-card')
    admin_page.click('[data-a="library:review:accept"]')

    # The accept succeeds and triggers loadLibraryCards() to refetch -- the
    # mocked route now serves the accepted version, so the card drops out
    # of Approvals (no longer unreviewed/stale).
    admin_page.wait_for_selector('text=Nothing waiting on review.')


def test_resources_flag_requires_a_note(admin_page):
    admin_page.click('[data-a="tab:resources"]')
    admin_page.wait_for_selector('.library-card')
    admin_page.click('[data-a="library:review:flag"]')
    admin_page.wait_for_selector('text=Add a note before flagging.')


def test_resources_flag_with_note_posts_the_decision(admin_page):
    posted = {}

    def review_handler(route):
        if route.request.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        posted.update(json.loads(route.request.post_data))
        route.fulfill(
            status=200, content_type='application/json',
            body='{"id": "r1", "decision": "flagged"}', headers=CORS_HEADERS,
        )

    admin_page.route('**/api/library/reviews*', review_handler)
    admin_page.click('[data-a="tab:resources"]')
    admin_page.wait_for_selector('.library-card')
    note_field = '[data-form="library-review"][data-field="note"]'
    admin_page.fill(note_field, 'the citation looks weak')
    admin_page.click('[data-a="library:review:flag"]')

    # Success clears the just-submitted card's draft note -- the textarea
    # goes back to empty once the re-render lands (see main.js's
    # handleSubmitLibraryReview: `delete state.libraryReviewDrafts[key]`).
    admin_page.wait_for_function(
        "(sel) => { const el = document.querySelector(sel); return el === null || el.value === ''; }",
        arg=note_field,
    )
    assert posted['file'] == UNREVIEWED_CARD['file']
    assert posted['section'] == UNREVIEWED_CARD['section']
    assert posted['decision'] == 'flagged'
    assert posted['note'] == 'the citation looks weak'


# --- Offline (localStorage cache fallback) -----------------------------------
# The card/file caches are pre-seeded via an init script (localStorage
# writes, not a network fetch, so they land before the app ever boots) and
# the browser context is taken offline before the very first visit to the
# Resources tab -- this exercises main.js's "no connection, read the cache"
# branch directly and deterministically, without depending on the real
# service worker's own asset caching to survive a full offline reload (see
# test_history_tab.py's own set_offline-after-first-load convention, which
# this intentionally does NOT need here since the whole point is the
# localStorage fallback, not SW asset caching).

@pytest.mark.parametrize('cfg', BROWSERS)
def test_resources_shows_cached_cards_when_offline(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, seed_cards_cache=[REVIEWED_CARD, UNREVIEWED_CARD])
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            ctx.set_offline(True)
            pg.wait_for_function('() => !navigator.onLine')
            pg.click('[data-a="tab:resources"]')
            pg.wait_for_selector('.library-card')
            content = pg.content()
            assert 'Session duration: 45 minutes' in content
            assert 'Offline' in content
        finally:
            ctx.set_offline(False)
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_resources_shows_cached_file_when_offline(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(
            pw, cfg,
            seed_cards_cache=[REVIEWED_CARD],
            seed_file_cache={'07-strength-dryland.md': '# Strength\n\n## Session duration: 45 minutes\n\nCached body text.'},
        )
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            ctx.set_offline(True)
            pg.wait_for_function('() => !navigator.onLine')
            pg.click('[data-a="tab:resources"]')
            pg.wait_for_selector('.library-card')
            pg.locator('[data-a="library:open-file"]').first.click()
            pg.wait_for_selector('#library-file-content')
            assert 'Cached body text.' in pg.content()
        finally:
            ctx.set_offline(False)
            ctx.close()
            browser.close()


@pytest.mark.parametrize('cfg', BROWSERS)
def test_resources_approvals_disabled_offline_with_a_message(cfg, base_url):
    with sync_playwright() as pw:
        browser, ctx = _make_ctx(pw, cfg, identity=ADMIN_IDENTITY, seed_cards_cache=[UNREVIEWED_CARD])
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            ctx.set_offline(True)
            pg.wait_for_function('() => !navigator.onLine')
            pg.click('[data-a="tab:resources"]')
            pg.wait_for_selector('.library-card')
            content = pg.content()
            assert 'Approvals' in content
            assert 'Offline' in content
            assert pg.locator('[data-a="library:review:accept"]').first.is_disabled()
            assert pg.locator('[data-a="library:review:flag"]').first.is_disabled()
        finally:
            ctx.set_offline(False)
            ctx.close()
            browser.close()
