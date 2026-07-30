"""e2e coverage for the Plan tab's session detail view: tapping a planned
session opens an in-tab detail view showing its full authored structure
(warm-up/main-set/cool-down or strength bullets) -- previously dead code,
see plan.js's sessionDisplay doc comment for the suppression bug this fixes.

Also covers this feature's follow-up fixes: block-parsed rendering (Warm-up/
Main set/Cool-down/Why as visually distinct `.detail-section`s, with Main
set's content additionally split into numbered interval items -- see
plan.js's parseStructureBlocks/parseMainSetIntervals), the real, block-aware
`purpose` text and real citations engine-side (plan.py's
_no_coach_pool_purpose / the trailing `Why:` line replacing internal
`library/*.md` path citations), and the scroll-to-top fix on opening a
detail view (main.js's handleOpenSessionDetail).

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

# Real generated-text shapes, post-fix: _additional_swim_structure's Main-set
# line no longer ends with an internal `library/14-swim-set-structure.md`
# citation -- a trailing `Why:` line carries the real rationale/citation
# instead (see plan.py's _additional_swim_structure docstring).
MAIN_SET_STRUCTURE = (
    'Warm-up: 600m easy, building to Z2 pace (1:35-1:39/100m) by the end.\n'
    'Main set: 8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume (base-block emphasis).\n'
    'Cool-down: 200m easy choice of stroke.\n'
    'Why: continuous aerobic-volume emphasis (base-block phase).'
)

# Post-fix: _strength_session_structure's own trailing `Why:` line carries
# the real citations (Hibberd 2012; Manske 2015; Tavares et al. 2025)
# previously jammed into the `purpose` field as an internal-path citation
# ("(library/07-strength-dryland.md)").
STRENGTH_STRUCTURE = (
    'Rotator-cuff / scapular-stability core (2 sets x 10 reps each):\n'
    '  - Band external rotation\n'
    '  - Prone Y-raise\n'
    'Why: rotator-cuff strength/balance, reduces shoulder-injury risk '
    '(Hibberd 2012; Manske 2015; Tavares et al. 2025).'
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
    # Post-fix: the real, block-aware purpose (_no_coach_pool_purpose('base')),
    # not the old generic dev-note text ("pool practice -- no pool coach on
    # hand, structure authored below").
    'purpose': 'Continuous aerobic volume — base-block emphasis',
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
    # the purpose detail with nothing actually shown below it -- the real
    # warm-up/main-set/cool-down content was dead code. Confirms the title is
    # still derived from the Main set line, and that the Purpose section now
    # shows the real training-purpose text, not the old generic dev-note text
    # ("no pool coach on hand, structure authored below").
    # (The purpose string's convention is "title — detail" for race-tagged
    # sessions, but `_no_coach_pool_purpose` purposes like this one are a
    # SINGLE complete statement that merely contains an em-dash as internal
    # punctuation -- the title in the header is Main-set-derived, not
    # purpose-derived, so the Purpose section below renders the session's
    # full, un-split purpose text, not just the post-dash fragment.)
    _open_session_detail(page, 's-main-set')
    content = page.content()
    assert '8 x 300m @ Z2 (1:35-1:39/100m)' in content  # derived title
    assert 'Continuous aerobic volume — base-block emphasis' in content  # full purpose, un-split
    assert 'no pool coach on hand' not in content  # old dev-note text, gone
    assert 'Warm-up' in content
    assert '600m easy, building to Z2 pace' in content
    assert '8 x 300m @ Z2 (1:35-1:39/100m), 15s rest' in content
    assert 'Cool-down' in content
    assert '200m easy choice of stroke.' in content
    # The row list itself is gone while in detail view.
    assert page.locator('[data-a="session:open"]').count() == 0


def test_session_detail_renders_visually_distinct_blocks(page):
    # Part 2's core UI fix: Warm-up/Main set/Cool-down/Why must render as
    # their own titled `.detail-section`s (see views.js's renderStructureBlock)
    # instead of one flat pre-wrap blob. Compared case-insensitively --
    # `.detail-section h4` is styled `text-transform: uppercase`, which
    # Playwright's innerText-based text extraction reflects.
    _open_session_detail(page, 's-main-set')
    headings = [h.lower() for h in page.locator('.detail-section h4').all_text_contents()]
    assert 'warm-up' in headings
    assert 'main set' in headings
    assert 'cool-down' in headings
    assert 'training rationale' in headings  # the Why: block's distinct heading
    assert headings.index('warm-up') < headings.index('main set') < headings.index('cool-down')


def test_session_detail_main_set_shows_a_distinct_interval_item(page):
    # Today's real engine output only ever emits one line under "Main set:",
    # which must still render as its own distinct numbered interval item
    # (not silently collapsed into the section's heading) -- proving the
    # forward-compatible interval parsing is wired all the way to the DOM.
    _open_session_detail(page, 's-main-set')
    assert page.locator('.detail-interval').count() == 1
    assert page.locator('.detail-interval-label').text_content().strip() == 'Interval 1'


def test_session_detail_training_rationale_shows_real_citation_not_a_library_path(page):
    # The other half of the reported bug: any citation shown must be a real,
    # verifiable source name, never this project's own internal
    # `library/*.md` config-file path.
    _open_session_detail(page, 's-main-set')
    content = page.content()
    assert 'library/' not in content
    assert 'González-Ravé' in content or 'continuous aerobic-volume emphasis (base-block phase)' in content


def test_strength_session_bullets_render_with_indentation_intact(page):
    _open_session_detail(page, 's-strength')
    content = page.content()
    assert 'Rotator-cuff / scapular-stability core' in content
    assert '  - Band external rotation' in content
    assert '  - Prone Y-raise' in content
    # Its own Why: block, with the real citations, not a library/ path.
    headings = [h.lower() for h in page.locator('.detail-section h4').all_text_contents()]
    assert 'training rationale' in headings
    assert 'Hibberd 2012' in content
    assert 'library/' not in content


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
        assert '8 x 300m @ Z2' in page.content()
    finally:
        ctx.set_offline(False)
        page.wait_for_function('() => navigator.onLine')


def test_detail_view_has_no_horizontal_overflow_on_narrow_viewport(page):
    _open_session_detail(page, 's-main-set')
    overflow = page.evaluate('document.documentElement.scrollWidth - window.innerWidth')
    assert overflow <= 1, f'page overflows horizontally by {overflow}px'


def test_opening_session_detail_scrolls_to_top_of_the_content(page):
    # Regression test for the reported bug: opening a session's detail view
    # used to leave the page at its prior scroll position (e.g. scrolled
    # down near the macro section) instead of landing on the detail content
    # immediately -- see main.js's handleOpenSessionDetail / scrollToTop.
    page.wait_for_selector('[data-a="session:open"]')
    # Scroll well down the page first, past the session list, so there's
    # somewhere real to scroll back up from.
    page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
    scrolled_down = page.evaluate('window.scrollY')
    assert scrolled_down > 0, 'page fixture is too short to prove a scroll regression against'

    page.click(f'[data-a="session:open"][data-id="{MAIN_SET_SESSION["id"]}"]')
    page.wait_for_selector('[data-a="session:back"]')
    assert page.evaluate('window.scrollY') == 0
