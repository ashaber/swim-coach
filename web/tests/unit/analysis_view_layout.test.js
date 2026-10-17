import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { renderWorkoutDetail } from '../../src/views.js';
import { buildRawAnalysis } from '../../src/analysis.js';

const ride = JSON.parse(readFileSync(new URL('../../../tests/fixtures/ride_2026_09_29_vo2_40_20.json', import.meta.url), 'utf8'));

const CURVE = [
  { duration_s: 1, watts: 900, best_42d_w: 800, best_90d_w: 850, is_best_42d: true, is_best_90d: true },
  { duration_s: 60, watts: 353, best_42d_w: 340, best_90d_w: 350, is_best_42d: true, is_best_90d: true },
  { duration_s: 300, watts: 290, best_42d_w: 280, best_90d_w: 285, is_best_42d: true, is_best_90d: true },
];
const FREE_RIDE = {
  power_zones: [{ zone: 'Z1', seconds: 600, pct: 40 }, { zone: 'Z2', seconds: 900, pct: 60 }],
  coasting_pct: 10, steady_drift: [{ duration_min: 25, start_offset_s: 600, avg_w: 150, drift_pct: 2.1 }],
  data_quality_notes: [],
};
const PAUSES = [{ start_offset_s: 754, duration_s: 90, source: 'gap' }];
const WORKOUT = {
  id: 'w1', date: '2026-09-29', sport: 'bike', source: 'fit', distance_m: 40000, duration_min: 90, laps: [],
  pauses: PAUSES,
  analytics: { cardiac_drift_pct: 6.4, pause_count: 1, pause_total_min: 1.5, power_curve: CURVE, free_ride: FREE_RIDE },
};
const SESSION = { ...ride.planned_session, date: '2026-09-29' };
const detail = (workout, extra = {}) => renderWorkoutDetail(workout, { ftpWatts: 276, rawAnalysisOpen: true, ...extra });
const section = (html, cls) => html.slice(html.indexOf(`class="detail-section ${cls}`));

describe('workout analysis layout', () => {
  it('puts the power curve in the main view, not in Raw analysis', () => {
    const html = detail(WORKOUT);
    const raw = section(html, 'raw-analysis');
    expect(html.indexOf('class="detail-section power-curve"')).toBeGreaterThan(-1);
    expect(html.indexOf('class="detail-section power-curve"')).toBeLessThan(html.indexOf('class="detail-section raw-analysis"'));
    expect(raw).not.toContain('power-curve');
    expect(buildRawAnalysis({ analytics: { power_curve: CURVE } }, undefined)).toBeNull();
  });

  it('keeps drift, pauses and steady drift in Raw analysis only', () => {
    const closed = detail(WORKOUT, { rawAnalysisOpen: false });
    expect(closed).not.toContain('drift +6.4%');
    expect(closed).not.toContain('Steady 25 min');
    expect(closed).not.toContain('pauses-list');
    const open = section(detail(WORKOUT), 'raw-analysis');
    expect(open).toContain('1 pause · 2 min stopped');
    expect(open).toContain('Steady 25 min');
    expect(open).toContain('0:12:34');
    expect(open).not.toContain('drift +6.4%'); // a free ride has no whole-ride drift verdict
    const swim = section(detail({ ...WORKOUT, analytics: { ...WORKOUT.analytics, free_ride: undefined } }), 'raw-analysis');
    expect(swim).toContain('drift +6.4%');
  });

  it('shows the zone colour key once when the workout graph already has it', () => {
    const withGraph = detail(WORKOUT, { weeks: [{ sessions: [SESSION] }] });
    expect(withGraph).toContain('data-zone-key');
    const bar = withGraph.slice(withGraph.indexOf('<ul class="free-ride-legend">'), withGraph.indexOf('</ul>', withGraph.indexOf('free-ride-legend')));
    expect(bar).not.toContain('<i style');
    expect(bar).toContain('Z1 Recovery 10 min (40%)');
    const alone = detail(WORKOUT);
    expect(alone).not.toContain('data-zone-key');
    expect(alone.slice(alone.indexOf('<ul class="free-ride-legend">'))).toContain('<i style');
  });
});

describe('course sectors section', () => {
  const cs = {
    sector_count: 2, best_lap: 1, fade: { time_change_pct: 2 },
    laps: [
      { lap: 1, time_s: 50, time_vs_best_s: 0, sector_times_s: [30, 24] },
      { lap: 2, time_s: 52, time_vs_best_s: 2, sector_times_s: [32, 20] },
    ],
    track: { sectors: [
      { sector: 1, points: [[0, 0], [100, 0]], label: [50, 0] },
      { sector: 2, points: [[100, 0], [100, 80]], label: [100, 40] },
    ] },
    sectors: [
      { sector: 1, best_time_s: 30, mean_loss_s: 0, total_loss_s: 0 },
      { sector: 2, best_time_s: 20, mean_loss_s: 4, total_loss_s: 4 },
    ],
    top_loss_sectors: [2],
  };
  const w = { ...WORKOUT, analytics: { course_sectors: cs } };

  it('draws the map with labels, a start marker and tappable sectors and rows', () => {
    const html = detail(w, { selectedSector: 2 });
    expect(html).toContain('class="cs-map"');
    expect(html).toContain('cs-seg--hot cs-seg--selected');
    expect(html).toContain('cs-seg--neutral cs-seg--dim');
    expect(html).toContain('Start / finish');
    expect(html).toContain('aria-label="Sector 2, loses 4.0 s in total"');
    expect(html).toContain('class="cs-col cs-col--selected" scope="col" data-a="workout:sector-select" data-sector="2"');
    expect(html).toContain('class="cs-grid"');
    expect(html).toContain('cs-heat-4');
    expect(html).toContain('cs-cell--best');
    expect(html).toContain('Each cell: seconds slower than your best time through that sector.');
    expect(html).not.toContain('http'); // no tiles, no external requests
  });

  it('draws no map without a track', () => {
    expect(detail({ ...w, analytics: { course_sectors: { ...cs, track: undefined } } })).not.toContain('cs-map');
  });
});
