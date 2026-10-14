"""An event group renders as ONE masthead item listing its member races, peak marked."""

import copy
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

from conftest import BROWSERS, _launch, mock_plan_route, seed_identity, seed_settings

import pytest


def _grouped_plan(web_root: str) -> str:
    plan = json.loads((Path(web_root) / 'dist' / 'data' / 'renee.json').read_text())
    day_one = plan['events'][0]
    day_two = copy.deepcopy(day_one)
    day_two.update({'id': 'group-day-two', 'name': 'Stage 2', 'event_date': '2026-09-19'})
    group = {'group_id': 'g1', 'group_name': 'Skopelos Stage Swim', 'group_type': 'stage_race'}
    day_one.update({**group, 'group_peak': False})
    day_two.update({**group, 'group_peak': True})
    plan['events'].append(day_two)
    plan['macro']['event_id'] = day_one['id']  # macro names day 1; the masthead aims at the peak
    return json.dumps(plan)


@pytest.fixture(params=BROWSERS)
def grouped_page(request, base_url: str, web_root: str):
    with sync_playwright() as pw:
        browser, ctx = _launch(pw, request.param)
        seed_identity(ctx)
        seed_settings(ctx)
        mock_plan_route(ctx, web_root)
        body = _grouped_plan(web_root)
        ctx.route('**/api/plan*', lambda route: route.fulfill(status=200, content_type='application/json', body=body))
        pg = ctx.new_page()
        pg.goto(base_url)
        try:
            yield pg
        finally:
            ctx.close()
            browser.close()


def test_group_is_one_masthead_item_with_peak_marked(grouped_page):
    group = grouped_page.locator('[data-testid="event-group"]')
    group.wait_for()
    assert 'Skopelos Stage Swim' in group.inner_text()
    assert group.locator('.eg-race').count() == 2
    assert 'peak' in group.locator('.eg-peak').inner_text().lower()
    assert 'Stage 2' in group.locator('.eg-peak').inner_text()
