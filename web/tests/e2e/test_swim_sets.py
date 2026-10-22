"""e2e: a pool swim's detail view headlines moving pace in the pool unit, then elapsed pace and
rest, and lists the sets (expandable to reps) with the segmentation note. A swim stored before
the engine produced these fields renders as before. Reuses test_workout_detail's mocked-backend
`page` fixture (signed in, all boot routes stubbed; runs at the conftest mobile viewports)."""

from test_workout_detail import BARE_MANUAL_WORKOUT, _open_log_tab_with_workouts, page  # noqa: F401

POOL_SWIM = {
    'id': 'w-pool', 'date': '2026-10-22', 'sport': 'swim_pool', 'source': 'fit',
    'distance_m': 2766, 'duration_min': 58.9, 'avg_pace_s_per_100m': 127.7, 'rpe': 6,
    'avg_hr': None, 'max_hr': None, 'notes': None,
    'analytics': {
        'elapsed_min': 58.9, 'moving_min': 55.1, 'pause_total_min': 3.7, 'pause_count': 2,
        'pool_unit': 'yd', 'pool_length_m': 22.86,
        'moving_pace_s_per_100m': 119.6, 'elapsed_pace_s_per_100m': 127.7,
        'moving_pace_s_per_100_unit': 109.4, 'elapsed_pace_s_per_100_unit': 116.8,
        'rest_total_s': 224,
        'segmentation_note': "Only 2 rests were recorded; rest at the wall without pressing lap/rest isn't visible.",
        'swim_sets': [
            {
                'count': 1, 'rep_distance': 1100, 'stroke': 'free', 'avg_pace_s_per_100': 104.0,
                'total_distance': 1100, 'description': '1100 free @ 1:44/100',
                'reps': [{
                    'start_offset_s': 0, 'distance': 1100, 'swim_time_s': 1144, 'pace_s_per_100': 104.0,
                    'stroke': 'free', 'rest_after_s': 102,
                }],
            },
            {
                'count': 10, 'rep_distance': 100, 'stroke': 'free', 'send_off_s': 105,
                'avg_pace_s_per_100': 80.0, 'avg_rest_s': 25.0, 'total_distance': 1000,
                'description': '10×100 free on 1:45 @ 1:20/100 (rest ~0:25)', 'reps': [],
            },
        ],
    },
    'laps': [], 'lengths': [], 'pauses': [],
}


def test_pool_swim_shows_moving_pace_and_sets(page):  # noqa: F811
    _open_log_tab_with_workouts(page, [POOL_SWIM])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')

    stats = page.locator('.detail-stats').inner_text()
    assert '1:49 /100yd' in stats
    assert '1:57 /100yd' in stats
    assert 'moving' in stats.lower() and 'elapsed' in stats.lower()
    assert '3:44' in stats

    sets = page.locator('#swim-sets')
    assert '1100 free @ 1:44/100' in sets.inner_text()
    assert '10×100 free on 1:45 @ 1:20/100 (rest ~0:25)' in sets.inner_text()
    assert 'Only 2 rests were recorded' in sets.inner_text()
    sets.locator('summary').first.click()
    assert 'in 19:04' in sets.locator('.swim-reps').first.inner_text()


def test_sets_section_sits_on_a_paper_card(page):  # noqa: F811
    # The generic card rule skips sections holding <details>; the Sets section must still be a
    # card, or its dark text lands on the dark page ground.
    _open_log_tab_with_workouts(page, [POOL_SWIM])
    page.click('.hist-row')
    page.wait_for_selector('#swim-sets')
    card = page.eval_on_selector('#swim-sets', 'e => getComputedStyle(e).backgroundColor')
    analytics = page.eval_on_selector(
        '.detail-section:has(.detail-analytics-list)', 'e => getComputedStyle(e).backgroundColor'
    )
    assert card == analytics
    assert card not in ('rgba(0, 0, 0, 0)', 'transparent')


def test_old_swim_without_new_fields_renders_as_before(page):  # noqa: F811
    _open_log_tab_with_workouts(page, [{**BARE_MANUAL_WORKOUT, 'avg_pace_s_per_100m': 120}])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')
    assert '2:00 /100m' in page.locator('.detail-stats').inner_text()
    assert page.locator('#swim-sets').count() == 0


SUSPECT_SWIM = {
    **{k: v for k, v in POOL_SWIM.items() if k != 'analytics'},
    'id': 'w-suspect', 'avg_pace_s_per_100m': 70,
    'analytics': {
        'elapsed_min': 40, 'moving_min': 38, 'pool_unit': 'm',
        'data_quality_note': 'Pool length or turn count looks wrong — paces hidden.',
    },
}


def test_suspect_swim_hides_paces_and_shows_note(page):  # noqa: F811
    _open_log_tab_with_workouts(page, [SUSPECT_SWIM])
    page.click('.hist-row')
    page.wait_for_selector('[data-a="history:back"]')
    assert 'paces hidden' in page.locator('#swim-sets').inner_text()
    assert '/100' not in page.locator('.detail-stats').inner_text()
