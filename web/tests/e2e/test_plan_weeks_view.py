"""e2e coverage for the Plan tab's week selection: the honest stale/empty
state, and the browsable "all planned weeks" accordion.

Reproduces the 2026-08-18 defect end to end -- the athlete's plan data
stopped at 2026-W29 while the wall clock had moved on to W34, and the Plan
tab rendered the five-week-old W29 under a "This week" heading. With only
already-elapsed weeks on file the tab must now say the plan has run out
(and never label a past week "This week"), while still letting the athlete
page back through everything that WAS planned via the accordion.

Same page-fixture convention as test_plan_session_detail.py: signed in +
configured, **/api/plan* stubbed with this file's own fixture weeks so the
wall clock the suite runs under can't change the outcome.
"""

import json

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity, seed_settings


def _week(iso_week, monday_date, volume, session_id):
    """One minimal but complete week -- a single session is enough to prove
    the card rendered (renderWeekCard emits a day row per day regardless)."""
    return {
        'iso_week': iso_week, 'meso_block': 'base', 'focus': f'focus {iso_week}',
        'target_volume_m': volume, 'adaptation_rationale': None,
        'sessions': [{
            'id': session_id, 'date': monday_date, 'sport': 'swim_pool',
            'source': 'ai_coach', 'duration_min': 60, 'distance_m': 2000,
            'intensity': {'zone': 'Z2'}, 'purpose': f'session in {iso_week}',
            'structure': 'Main set: 8 x 200m @ Z2.', 'status': 'planned',
        }],
    }


# Deep-past weeks (verified Mondays) so every one has certainly elapsed no
# matter when the suite runs.
PAST_WEEKS = [
    _week('2020-W01', '2019-12-30', 11000, 's-past-1'),
    _week('2020-W02', '2020-01-06', 12000, 's-past-2'),
]

# Far-future weeks, so the first is always "This week" and the second "Next".
FUTURE_WEEKS = [
    _week('2099-W01', '2098-12-29', 13000, 's-future-1'),
    _week('2099-W02', '2099-01-05', 14000, 's-future-2'),
]


def _plan_body(weeks):
    return json.dumps({
        'slug': 'renee', 'athlete': {'name': 'Renee'}, 'events': [],
        'macro': {'blocks': []}, 'weeks': weeks,
    })


def _make_page(pw, cfg, weeks):
    try:
        browser = getattr(pw, cfg['name']).launch()
    except Exception as e:
        pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
    ctx = browser.new_context(viewport=cfg['vp'])
    seed_identity(ctx)
    seed_settings(ctx)
    body = _plan_body(weeks)
    ctx.route('**/api/plan*', lambda route: route.fulfill(
        status=200, content_type='application/json', body=body))
    # GET /api/plan/load fires unconditionally at boot alongside GET
    # /api/plan (main.js's loadPlanLoad) -- same treatment as the stub above.
    ctx.route('**/api/plan/load*', lambda route: route.fulfill(
        status=200, content_type='application/json',
        body='{"athlete":"renee","weeks":12,"ctl_atl_tsb":[]}'))
    return browser, ctx


@pytest.fixture(params=BROWSERS)
def stale_page(request, base_url):
    """A plan whose every week has already elapsed -- the reported defect."""
    with sync_playwright() as pw:
        browser, ctx = _make_page(pw, request.param, PAST_WEEKS)
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            yield pg
        finally:
            ctx.close()
            browser.close()


@pytest.fixture(params=BROWSERS)
def current_page(request, base_url):
    """A plan with a live current + next week (the healthy case)."""
    with sync_playwright() as pw:
        browser, ctx = _make_page(pw, request.param, FUTURE_WEEKS + PAST_WEEKS)
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            yield pg
        finally:
            ctx.close()
            browser.close()


@pytest.fixture(params=BROWSERS)
def empty_page(request, base_url):
    """No weeks at all -- distinct from "the plan ran out"."""
    with sync_playwright() as pw:
        browser, ctx = _make_page(pw, request.param, [])
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            yield pg
        finally:
            ctx.close()
            browser.close()


def test_all_past_weeks_shows_an_honest_gap_not_a_stale_this_week(stale_page):
    stale_page.wait_for_selector('[data-a="weeks:toggle-all"]')
    content = stale_page.content()
    assert 'No plan generated for this week yet' in content
    # The defect itself: a five-week-old week rendered under "This week".
    assert 'This week ·' not in content
    assert 'Next week ·' not in content


def test_past_weeks_stay_browsable_behind_the_accordion(stale_page):
    summary = stale_page.locator('[data-a="weeks:toggle-all"]')
    summary.wait_for()
    assert summary.text_content().strip() == 'All planned weeks (2)'
    # Collapsed by default -- the week cards are not visible until opened.
    assert not stale_page.locator('details.all-weeks').get_attribute('open')
    assert stale_page.locator('.week').count() == 2  # in the DOM, collapsed
    assert not stale_page.locator('.week').first.is_visible()

    summary.click()
    stale_page.wait_for_selector('.week >> visible=true')
    assert stale_page.locator('.week').first.is_visible()
    body = stale_page.content()
    assert '2020-W01' in body
    assert '2020-W02' in body


def test_accordion_stays_open_across_a_re_render(stale_page):
    """The accordion is native <details>, so its open state lives in the DOM
    -- which every render() rebuilds from scratch. It used to snap shut on
    any unrelated re-render (a background load landing, an online/offline
    flip) while the athlete was mid-read; this showed up first as a flaky
    failure of the test above. main.js now mirrors the state and re-emits
    the `open` attribute. Driven here by an offline/online flip, which is a
    real re-render trigger the athlete hits on a phone."""
    summary = stale_page.locator('[data-a="weeks:toggle-all"]')
    summary.wait_for()
    summary.click()
    stale_page.wait_for_selector('.week >> visible=true')

    stale_page.context.set_offline(True)
    stale_page.context.set_offline(False)
    stale_page.wait_for_timeout(200)  # let any re-render settle

    assert stale_page.locator('details.all-weeks').get_attribute('open') is not None
    assert stale_page.locator('.week').first.is_visible()


def test_current_and_next_cards_still_render_alongside_the_accordion(current_page):
    current_page.wait_for_selector('.week')
    content = current_page.content()
    assert 'This week ·' in content
    assert 'Next week ·' in content
    assert 'No plan generated for this week yet' not in content
    # Accordion lists every week on file -- the two future ones and the two past.
    assert current_page.locator('[data-a="weeks:toggle-all"]').text_content().strip() \
        == 'All planned weeks (4)'


def test_no_weeks_at_all_reads_differently_and_offers_no_accordion(empty_page):
    empty_page.wait_for_selector('.wrap')
    content = empty_page.content()
    assert 'No weeks planned yet' in content
    assert 'No plan generated for this week yet' not in content
    assert empty_page.locator('[data-a="weeks:toggle-all"]').count() == 0


def test_accordion_does_not_introduce_horizontal_overflow(stale_page):
    """Mobile-viewport guard, same check the other Plan-tab e2e files make."""
    stale_page.locator('[data-a="weeks:toggle-all"]').click()
    stale_page.wait_for_selector('.week >> visible=true')
    overflow = stale_page.evaluate(
        'document.documentElement.scrollWidth - document.documentElement.clientWidth')
    assert overflow <= 1, f'horizontal overflow of {overflow}px'
