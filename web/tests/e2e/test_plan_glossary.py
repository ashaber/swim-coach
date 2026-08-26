"""e2e coverage for the Plan tab's "Terms & zones" glossary (views.js's
renderGlossaryPanel): a compact, collapsed-by-default zone/terms reference
addressing the athlete's reported feedback that the plan's workouts "don't
make sense" without a coach walking through the vocabulary in person.

Same page-fixture convention as test_plan_weeks_view.py: signed in +
configured, **/api/plan* stubbed with a minimal fixture plan.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings

# A far-future week (so it's never "stale" regardless of the wall clock the
# suite runs under) purely so the all-weeks accordion also exists in this
# fixture's DOM -- needed to prove the two accordions track independent
# open/closed state (see test_toggling_the_glossary_does_not_affect_the_
# unrelated_all_weeks_accordion below).
WEEK = {
    'iso_week': '2099-W01', 'meso_block': 'base', 'focus': 'aerobic base',
    'target_volume_m': 10000, 'adaptation_rationale': None,
    'sessions': [{
        'id': 's-1', 'date': '2098-12-29', 'sport': 'swim_pool', 'source': 'ai_coach',
        'duration_min': 60, 'distance_m': 2000, 'intensity': {'zone': 'Z2'},
        'purpose': 'aerobic swim', 'structure': 'Main set: 8 x 200m @ Z2.', 'status': 'planned',
    }],
}

PLAN_STUB = json.dumps({
    'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [],
    'macro': {'blocks': []}, 'weeks': [WEEK],
})


@pytest.fixture(params=BROWSERS)
def page(request, base_url):
    cfg = request.param
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'])
        seed_identity(ctx)
        seed_settings(ctx)
        ctx.route('**/api/plan*', lambda route: route.fulfill(
            status=200, content_type='application/json', body=PLAN_STUB))
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            yield pg
        finally:
            ctx.close()
            browser.close()


def test_glossary_is_present_but_collapsed_by_default(page):
    page.wait_for_selector('[data-a="glossary:toggle"]')
    assert page.locator('[data-a="glossary:toggle"]').text_content().strip() == 'Terms & zones'
    assert page.locator('details.glossary').get_attribute('open') is None
    # Content exists in the DOM (native <details>) but isn't visible collapsed.
    assert not page.locator('.glossary-content').is_visible()


def test_expanding_the_glossary_shows_real_zone_and_term_definitions(page):
    page.click('[data-a="glossary:toggle"]')
    page.wait_for_selector('.glossary-content >> visible=true')
    content = page.content()
    # Real CSS-relative zone table (engine/swim_coach/zones.py), not invented.
    assert 'Z1' in content and 'Z2' in content and 'Z5' in content
    assert 'Aerobic endurance' in content
    assert 'Above critical velocity' in content
    # Real abbreviations/terms used elsewhere in this app's own rendering.
    assert 'CSS' in content
    assert 'RPE' in content
    assert 'EMOM' in content
    assert 'AMRAP' in content


def test_glossary_stays_open_across_a_re_render(page):
    """Same regression class as test_plan_weeks_view.py's all-weeks
    accordion test -- native <details> state lives in the DOM, which every
    render() rebuilds, so main.js must mirror it (state.glossaryOpen) and
    re-emit the `open` attribute rather than silently snapping shut."""
    page.click('[data-a="glossary:toggle"]')
    page.wait_for_selector('.glossary-content >> visible=true')

    page.context.set_offline(True)
    page.context.set_offline(False)
    page.wait_for_timeout(200)

    assert page.locator('details.glossary').get_attribute('open') is not None
    assert page.locator('.glossary-content').is_visible()


def test_toggling_the_glossary_does_not_affect_the_unrelated_all_weeks_accordion(page):
    """Regression: the two accordions must track independent state -- see
    main.js's toggle listener doc comment."""
    all_weeks = page.locator('details.all-weeks')
    all_weeks.wait_for()
    page.click('[data-a="glossary:toggle"]')
    page.wait_for_selector('.glossary-content >> visible=true')
    assert all_weeks.get_attribute('open') is None


def test_glossary_does_not_introduce_horizontal_overflow(page):
    page.click('[data-a="glossary:toggle"]')
    page.wait_for_selector('.glossary-content >> visible=true')
    overflow = page.evaluate(
        'document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1, f'horizontal overflow of {overflow}px'
