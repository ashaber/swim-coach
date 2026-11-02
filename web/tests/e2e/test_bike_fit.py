"""e2e: Settings > Bike geometry (measurement form, diagram highlight, draft, save, compare).

Mocked backend only (same conventions as test_profile_edit.py): GET/POST/PATCH **/api/bike-fit* and
GET **/api/bike-fit/compare. The derived numbers in the fixtures are canned: the engine's maths is
covered by tests/unit/test_bike_fit.py, this file covers the browser flows.
"""

import json
import re
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import sync_playwright

from conftest import BROWSERS, seed_identity
from test_profile_edit import (
    BASE_URL, TOKEN, CORS_HEADERS, _plan_route, _plan_load_route, _grants_route, _athlete_route,
)

LIMITS = ('This records and compares bike geometry. It does not recommend fit changes, give medical advice, '
          'or state target angles.')

TAPES = {'bb_fa': 612, 'bb_bc': 760, 'fa_bc': 590, 'bb_st': 705, 'bc_st': 640, 'ra_bb': 430, 'ra_st': 800,
         'bb_h': 870, 'st_h': 700, 'ra_fa': 1025, 'floor_fa': 335, 'floor_ra': 330}


def _output(key, label, unit, value, sigma):
    return {'key': key, 'label': label, 'unit': unit, 'value': value, 'sigma': sigma,
            'definition': f'definition of {label}', 'depends_on': []}


def _derived(bike_type, seated):
    mtb = bike_type == 'mtb'
    outputs = [
        _output('setback_tip_mm', 'Saddle setback, tip', 'mm', 90.0 if mtb else 5.0, 1.8),
        _output('setback_sit_mm', 'Saddle setback, sit point', 'mm', 225.0 if mtb else 140.0, 1.8),
        _output('saddle_height_mm', 'Saddle height, BB to sit point', 'mm', 735.0 if mtb else 718.8, 1.1),
        _output('reach_hand_mm', 'Reach, hand', 'mm', 561.0 if mtb else 560.0, 2.0),
        _output('effective_seat_angle_deg', 'Effective seat angle', 'deg', 77.0 if mtb else 78.8, 0.14),
    ]
    out = {
        'bike_type': bike_type, 'outputs': outputs,
        'points': {'BB': [0, 0], 'FA': [600, 70], 'RA': [-420, 70], 'BC': [480, 640], 'ST': [-5, 705],
                   'H': [560, 650], 'SRP': [-140, 705]},
        'axle_heights_mm': {'front': 335, 'rear': 330},
        'seated': None,
        'closure': {'status': 'ok', 'computed_mm': 1025.2, 'measured_mm': 1025.0, 'residual_mm': 0.2,
                    'warn_mm': 3, 'bad_mm': 6, 'message': 'RA-FA closes within tolerance.', 'suspects': [],
                    'affected_outputs': []},
        'ground_pitch_deg': 0.28, 'radius_difference_mm': 5.0,
        'assumptions': {'bb_mm': 60, 'fa_mm': 50, 'ra_mm': 71, 'h_mm': 210, 'defaulted': ['bb', 'fa', 'ra']},
        'constants': {'tape_sigma_mm': 1.0, 'sit_fraction': 0.5},
        'notes': [] if (seated or not mtb) else [
            'Unweighted numbers only: rear sag normally rotates the frame back, so unweighted numbers may '
            'understate how upright he actually rides this bike.'],
        'limits': LIMITS,
    }
    if seated:
        out['seated'] = {'rotation_deg': 2.1, 'rotation_sigma_deg': 0.1, 'assumption': 'rigid front triangle',
                         'outputs': outputs[:3], 'points': out['points']}
    return out


class BikeFitBackend:
    """A stateful stand-in for /api/bike-fit*: keeps saved snapshots, records POST bodies."""

    def __init__(self):
        self.snapshots = []
        self.posts = []
        self.fail_next_post = None
        self.closure_status = 'ok'

    def snapshot(self, payload):
        seated = payload['inputs'].get('seated_floor_bb_mm') is not None
        snap = {**payload, 'id': f'snap-{len(self.snapshots) + 1}', 'retired': False,
                'derived': _derived(payload['bike_type'], seated), 'error': None}
        if self.closure_status != 'ok':
            snap['derived']['closure'].update(
                status=self.closure_status, residual_mm=-4.0 if self.closure_status == 'warn' else -9.0,
                message='recheck the listed measures', affected_outputs=['setback_tip_mm'],
                suspects=[{'measure': 'bb_fa', 'label': 'BB-FA', 'sensitivity': 1.0}])
        return snap

    def handler(self, route):
        req = route.request
        path = req.url.split('?')[0]
        if req.method == 'OPTIONS':
            route.fulfill(status=204, headers=CORS_HEADERS)
            return
        if path.endswith('/api/bike-fit/compare'):
            query = parse_qs(urlparse(req.url).query)
            a, b = (next(s for s in self.snapshots if s['id'] == query[k][0]) for k in ('a', 'b'))
            rows = []
            for oa, ob in zip(a['derived']['outputs'], b['derived']['outputs']):
                diff = ob['value'] - oa['value']
                sd = (oa['sigma'] ** 2 + ob['sigma'] ** 2) ** 0.5
                rows.append({'key': oa['key'], 'label': oa['label'], 'unit': oa['unit'], 'a': oa['value'],
                             'b': ob['value'], 'diff': diff, 'sigma_a': oa['sigma'], 'sigma_b': ob['sigma'],
                             'sigma_diff': sd, 'exceeds_error': abs(diff) > 2 * sd})
            body = {'a': a, 'b': b, 'factor': 2.0, 'unweighted': rows, 'seated': None,
                    'notes': ['Snapshot B is an MTB with unweighted results only.']}
        elif req.method == 'POST':
            payload = json.loads(req.post_data or '{}')
            self.posts.append(payload)
            if self.fail_next_post:
                status, message = self.fail_next_post
                self.fail_next_post = None
                route.fulfill(status=status, content_type='application/json', headers=CORS_HEADERS,
                              body=json.dumps({'error': message}))
                return
            snap = self.snapshot(payload)
            self.snapshots.append(snap)
            body = snap
        elif req.method == 'PATCH':
            sid = path.rsplit('/', 1)[1]
            snap = next(s for s in self.snapshots if s['id'] == sid)
            snap['retired'] = json.loads(req.post_data)['retired']
            body = snap
        else:
            body = {'snapshots': self.snapshots, 'limits': LIMITS,
                    'defaults': {'lateral_mm': {}, 'tape_sigma_mm': 1.0}}
        route.fulfill(status=200, content_type='application/json', body=json.dumps(body), headers=CORS_HEADERS)


@pytest.fixture(params=BROWSERS)
def bikefit_env(request, base_url):
    cfg = request.param
    backend = BikeFitBackend()
    with sync_playwright() as pw:
        try:
            browser = getattr(pw, cfg['name']).launch()
        except Exception as e:  # noqa: BLE001
            pytest.skip(f'{cfg["name"]} unavailable in this environment: {e}')
        ctx = browser.new_context(viewport=cfg['vp'], service_workers='block')
        seed_identity(ctx)
        ctx.route('**/api/plan*', _plan_route)
        ctx.route('**/api/plan/load*', _plan_load_route)
        ctx.route('**/api/grants*', _grants_route)
        ctx.route('**/api/athlete*', _athlete_route())
        ctx.route(re.compile(r'/api/bike-fit'), backend.handler)
        pg = ctx.new_page()
        js_errors = []
        pg.on('pageerror', lambda e: js_errors.append(str(e)))
        pg.goto(base_url)
        pg.evaluate(
            "(cfg) => window.localStorage.setItem('swimcoach_settings', "
            "JSON.stringify({baseUrl: cfg.baseUrl, token: cfg.token, version: 2}))",
            {'baseUrl': BASE_URL, 'token': TOKEN},
        )
        pg.reload()
        pg.click('[data-a="tab:settings"]')
        pg.wait_for_selector('#bikefit-entry')
        try:
            yield pg, ctx, backend
            real = [e for e in js_errors if 'sw.js load failed' not in e and 'Importing a module script failed' not in e]
            assert not real, f'Uncaught JS errors: {real}'
        finally:
            ctx.close()
            browser.close()


def open_bike_fit(page):
    page.click('[data-a="bikefit:open"]')
    page.wait_for_selector('.bf-svg')


def field(page, name):
    return page.locator(f'[data-form="bikefit"][data-field="{name}"]')


def fill_bike(page, name, bike_type, extra=None):
    page.select_option('[data-field="bikeType"]', bike_type)
    field(page, 'name').fill(name)
    for key, value in TAPES.items():
        field(page, key).fill(str(value))
    field(page, 'tiltMag').fill('0')
    field(page, 'saddleLength').fill('270')
    field(page, 'crankLength').fill('172.5')
    field(page, 'barWidth').fill('420' if bike_type == 'drop_bar' else '780')
    for key, value in (extra or {}).items():
        field(page, key).fill(str(value))


def save(page):
    page.click('[data-a="bikefit:save"]')
    page.wait_for_selector('[data-results]')


def test_reachable_from_settings_with_the_plain_statement(bikefit_env):
    page, _, _ = bikefit_env
    open_bike_fit(page)
    text = page.inner_text('.bf-wrap')
    assert 'records geometry and doesn’t recommend changes' in text
    assert page.locator('[data-a="bikefit:close"]').count() == 1
    page.click('[data-a="bikefit:close"]')
    page.wait_for_selector('#bikefit-entry')


def test_mobile_layout_has_no_horizontal_scroll_and_numeric_keyboards(bikefit_env):
    page, _, _ = bikefit_env
    open_bike_fit(page)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 1')
    assert field(page, 'bb_fa').get_attribute('inputmode') == 'numeric'
    assert field(page, 'bb_fa').get_attribute('aria-label') == 'BB to FA in mm'
    assert page.locator('.bf-svg').first.bounding_box()['width'] <= page.viewport_size['width']


def test_focus_highlights_two_points_the_tape_line_and_exact_definitions(bikefit_env):
    page, _, _ = bikefit_env
    open_bike_fit(page)
    assert page.locator('.bf-pt.is-active').count() == 0
    field(page, 'bb_bc').focus()
    assert page.locator('.bf-pt.is-active').count() == 2
    assert page.locator('.bf-pt.is-active').evaluate_all('els => els.map(e => e.dataset.point)') == ['BB', 'BC']
    assert page.locator('.bf-tape').count() == 1
    defs = page.inner_text('#bf-diagram .bf-defs')
    assert 'center of the left crank bolt' in defs
    assert "bar clamp, center of where the stem clamps the bar, on the bike's centerline" in defs
    # the form was not re-rendered: the focused input is still the active element
    assert page.evaluate('document.activeElement.dataset.field') == 'bb_bc'
    field(page, 'bb_h').focus()
    assert 'top center of the left hood' in page.inner_text('#bf-diagram .bf-defs')
    page.select_option('[data-field="bikeType"]', 'mtb')
    field(page, 'bb_h').focus()
    assert 'center of the left grip' in page.inner_text('#bf-diagram .bf-defs')
    field(page, 'floor_ra').focus()
    assert page.locator('.bf-pt.is-active').count() == 1
    assert page.locator('.bf-tape').count() == 1


def test_all_point_definitions_are_on_the_page_for_both_bikes(bikefit_env):
    page, _, _ = bikefit_env
    open_bike_fit(page)
    seen = set()
    for key in ['bb_fa', 'bb_bc', 'bb_st', 'ra_bb', 'bb_h']:
        field(page, key).focus()
        seen.add(page.inner_text('#bf-diagram .bf-defs'))
    joined = ' '.join(seen)
    for text in ['center of the left crank bolt', 'center of the left front axle end', 'center of the left rear axle end',
                 'saddle tip, on the centerline', 'top center of the left hood']:
        assert text in joined


def test_missing_fields_are_listed_and_nothing_is_posted(bikefit_env):
    page, _, backend = bikefit_env
    open_bike_fit(page)
    field(page, 'name').fill('CX')
    page.click('[data-a="bikefit:save"]')
    page.wait_for_selector('.bf-errors')
    assert 'BB to FA' in page.inner_text('.bf-errors')
    assert backend.posts == []


def test_draft_survives_reload_and_offline(bikefit_env):
    page, ctx, backend = bikefit_env
    open_bike_fit(page)
    field(page, 'name').fill('Half done')
    field(page, 'bb_fa').fill('611')
    ctx.set_offline(True)
    page.evaluate("window.dispatchEvent(new Event('offline'))")
    page.wait_for_selector('text=You are offline')
    assert page.locator('[data-a="bikefit:save"]').is_disabled()
    assert field(page, 'bb_fa').input_value() == '611'
    field(page, 'bb_bc').fill('755')
    ctx.set_offline(False)
    page.evaluate("window.dispatchEvent(new Event('online'))")
    page.reload()
    page.click('[data-a="tab:settings"]')
    open_bike_fit(page)
    assert field(page, 'name').input_value() == 'Half done'
    assert field(page, 'bb_fa').input_value() == '611'
    assert field(page, 'bb_bc').input_value() == '755'
    assert backend.posts == []


def test_enter_both_bikes_save_and_compare(bikefit_env):
    page, _, backend = bikefit_env
    open_bike_fit(page)
    fill_bike(page, 'CX', 'drop_bar')
    field(page, 'tireFront').fill('28')
    save(page)
    assert backend.posts[0]['bike_type'] == 'drop_bar'
    assert backend.posts[0]['inputs']['tape']['bb_fa'] == 612
    assert backend.posts[0]['inputs']['lateral_fa_mm'] == 50
    results = page.inner_text('[data-results]')
    assert '±1.8' in results and 'Closure OK' in results
    # the form was reset after saving; draft cleared
    assert field(page, 'name').input_value() == ''

    fill_bike(page, 'Trail', 'mtb', {'sagFront': '20', 'sagRear': '30'})
    assert field(page, 'latFa').input_value() == '55'  # MTB lateral defaults replaced the untouched ones
    save(page)
    assert backend.posts[1]['inputs']['sag_rear_pct'] == 30
    assert 'Unweighted numbers only' in page.inner_text('[data-results]')

    page.wait_for_selector('#bf-compare select')
    page.select_option('[data-form="bikefit-compare"][data-field="a"]', 'snap-1')
    page.select_option('[data-form="bikefit-compare"][data-field="b"]', 'snap-2')
    page.click('[data-a="bikefit:compare"]')
    page.wait_for_selector('table.bf-compare')
    tip = page.locator('table.bf-compare tr[data-key="setback_tip_mm"]')
    assert 'Exceeds error' in tip.inner_text()
    assert page.locator('table.bf-compare tr[data-key="saddle_height_mm"]:has-text("Exceeds error")').count() == 1
    assert page.locator('.bf-overlay .bf-ov-a').count() > 0 and page.locator('.bf-overlay .bf-ov-b').count() > 0
    assert 'unweighted results only' in page.inner_text('#bf-compare')


def test_a_rejected_save_keeps_the_draft_and_shows_the_error(bikefit_env):
    page, _, backend = bikefit_env
    open_bike_fit(page)
    fill_bike(page, 'CX', 'drop_bar')
    backend.fail_next_post = (422, 'BB-BC, BB-ST and BC-ST cannot form a triangle')
    page.click('[data-a="bikefit:save"]')
    page.wait_for_selector('.conn-result.fail')
    assert 'cannot form a triangle' in page.inner_text('.conn-result.fail')
    assert field(page, 'bb_fa').input_value() == '612'


def test_retire_marks_a_snapshot_without_deleting_it(bikefit_env):
    page, _, backend = bikefit_env
    open_bike_fit(page)
    fill_bike(page, 'CX', 'drop_bar')
    save(page)
    page.click('[data-a="bikefit:retire"]')
    page.wait_for_selector('.bf-item.is-retired')
    assert backend.snapshots[0]['retired'] is True
    assert re.search('Restore', page.inner_text('.bf-item'))
