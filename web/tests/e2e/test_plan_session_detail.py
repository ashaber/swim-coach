"""e2e coverage for the Plan tab's session detail view: tapping a planned
session opens an in-tab detail view showing its full authored structure
(warm-up/main-set/cool-down or strength bullets) -- previously dead code,
see plan.js's sessionDisplay doc comment for the suppression bug this fixes.

Mirrors test_workout_detail.py's exact structure: same page-fixture shape
(signed in + configured, no real backend ever contacted), same
back-button / hardware-back / offline / no-horizontal-overflow checks --
just stubbing **/api/plan* with sessions carrying real generated-text shapes
instead of **/api/workouts*.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

# Real generated-text shapes from the task brief.
MAIN_SET_STRUCTURE = (
    'Warm-up: 600m easy, building to Z2 pace (1:35-1:39/100m) by the end.\n'
    'Main set: 8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume for the week.\n'
    'Cool-down: 200m easy choice of stroke.'
)

STRENGTH_STRUCTURE = (
    'Rotator-cuff / scapular-stability core (2 sets x 10 reps each):\n'
    '  - Band external rotation\n'
    '  - Prone Y-raise'
)

# A far-future week so src/plan.js's pickCurrentAndNextWeek always treats it
# as "This week", regardless of the real wall clock the suite runs under.
# Mon/Tue/Wed of ISO week 2099-W01 (verified against isoWeekMonday's own
# algorithm, not guessed) -- sessions must land on the exact date
# sessionsByDay computes for the week to show up in a day row at all.
ISO_WEEK = '2099-W01'
MONDAY = '2098-12-29'
TUESDAY = '2098-12-30'
WEDNESDAY = '2098-12-31'

MAIN_SET_SESSION = {
    'id': 's-main-set', 'date': MONDAY, 'sport': 'swim_pool', 'source': 'ai_coach',
    'duration_min': 65, 'distance_m': 2400, 'intensity': {'zone': 'Z2'},
    'purpose': 'pool practice — no pool coach on hand, structure authored below',
    'structure': MAIN_SET_STRUCTURE, 'status': 'planned',
}

STRENGTH_SESSION = {
    'id': 's-strength', 'date': TUESDAY, 'sport': 'strength', 'source': 'ai_coach',
    'duration_min': 30, 'distance_m': None, 'intensity': {},
    'purpose': 'dryland shoulder strength — moderate (2 days before the 5-hour swim)',
    'structure': STRENGTH_STRUCTURE, 'status': 'planned',
}

NO_STRUCTURE_SESSION = {
    'id': 's-coach-pool', 'date': WEDNESDAY, 'sport': 'swim_pool', 'source': 'pool_coach',
    'duration_min': 90, 'distance_m': None, 'intensity': {},
    'purpose': 'coached USMS pool — content assigned by coach',
    'structure': None, 'status': 'planned',
}

WEEK = {
    'iso_week': ISO_WEEK, 'meso_block': 'base', 'focus': 'aerobic base', 'target_volume_m': 12000,
    'sessions': [MAIN_SET_SESSION, STRENGTH_SESSION, NO_STRUCTURE_SESSION],
    'adaptation_rationale': None,
}

PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [], 'macro': {'blocks': []}, 'weeks': [WEEK],
})


def _plan_route(route):
    route.fulfill(status=200, content_type='application/json', body=PLAN_STUB)


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    """Signed in and configured (same seed_identity/seed_settings convention
    as conftest.py's own base `page` fixture), but with **/api/plan* stubbed
    with this file's own fixture sessions instead of the real exported
    renee.json -- gives full control over the exact structure/purpose text
    shapes this feature needs to prove render correctly."""
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'])
        seed_identity(ctx)
        seed_settings(ctx)
        ctx.route('**/api/plan*', _plan_route)
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


def _open_session_detail(page, session_id):
    page.wait_for_selector(f'[data-a="session:open"][data-id="{session_id}"]')
    page.click(f'[data-a="session:open"][data-id="{session_id}"]')
    page.wait_for_selector('[data-a="session:back"]')


def test_open_main_set_session_shows_real_structure_not_the_old_dead_end(page):
    # Reproduces the athlete's reported bug: the only visible text used to be
    # the purpose detail ("no pool coach on hand, structure authored below")
    # with nothing actually shown below it -- the real warm-up/main-set/
    # cool-down content was dead code. Confirms the title is now derived from
    # the Main set line too, not the generic "pool practice" label.
    _open_session_detail(page, 's-main-set')
    content = page.content()
    assert '8 x 300m @ Z2 (1:35-1:39/100m)' in content  # derived title
    assert 'Warm-up: 600m easy, building to Z2 pace' in content
    assert 'Main set: 8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume' in content
    assert 'Cool-down: 200m easy choice of stroke.' in content
    # The row list itself is gone while in detail view.
    assert page.locator('[data-a="session:open"]').count() == 0


def test_strength_session_bullets_render_with_indentation_intact(page):
    _open_session_detail(page, 's-strength')
    content = page.content()
    assert 'Rotator-cuff / scapular-stability core' in content
    assert '  - Band external rotation' in content
    assert '  - Prone Y-raise' in content


def test_no_structure_session_shows_a_sensible_non_blank_detail(page):
    # A pool-coach placeholder with no authored structure at all -- must
    # still show something real (the purpose-derived title + detail), never
    # a blank detail view.
    _open_session_detail(page, 's-coach-pool')
    content = page.content()
    assert 'Coached USMS pool' in content
    assert 'content assigned by coach' in content


def test_back_button_closes_detail(page):
    _open_session_detail(page, 's-main-set')
    page.click('[data-a="session:back"]')
    page.wait_for_selector('[data-a="session:open"]')
    assert page.locator('[data-a="session:back"]').count() == 0


def test_hardware_back_closes_detail_not_app(page):
    _open_session_detail(page, 's-main-set')
    page.go_back()
    page.wait_for_selector('[data-a="session:open"]')
    assert page.locator('[data-a="session:back"]').count() == 0
    # Prove the app didn't navigate away entirely.
    assert page.locator('.tabbar').count() == 1
    assert page.locator('[data-a="tab:plan"]').count() == 1


def test_detail_works_offline(page):
    _open_session_detail(page, 's-main-set')
    ctx = page.context
    ctx.set_offline(True)
    try:
        page.wait_for_function('() => !navigator.onLine')
        assert page.locator('[data-a="session:back"]').count() == 1
        assert 'Main set: 8 x 300m @ Z2' in page.content()
    finally:
        ctx.set_offline(False)
        page.wait_for_function('() => navigator.onLine')


def test_detail_view_has_no_horizontal_overflow_on_narrow_viewport(page):
    _open_session_detail(page, 's-main-set')
    overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
    assert overflow <= 1, f'page overflows horizontally by {overflow}px'
