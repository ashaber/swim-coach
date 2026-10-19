import { describe, it, expect } from 'vitest';
import { renderWorkoutDetail } from '../../src/views.js';
import { buildCanonicalLaps, buildDeviceLaps, buildRawAnalysis, buildRaceEfficiency } from '../../src/analysis.js';

const CANONICAL = [
  { n: 1, start_s: 480, end_s: 630, duration_s: 150, distance_m: 450, avg_power_w: 250, avg_hr: 170, source: 'split_at_start', start_lap: true, comparable: false },
  { n: 2, start_s: 630, end_s: 830, duration_s: 200, distance_m: 600, avg_power_w: 240, avg_hr: 172, source: 'merged', start_lap: false, comparable: true },
  { n: 3, start_s: 830, end_s: 1030, duration_s: 200, distance_m: 600, avg_power_w: 238, avg_hr: 173, source: 'gps_filled', start_lap: false, comparable: true },
  { n: 4, start_s: 1030, end_s: 1090, duration_s: 60, distance_m: 180, avg_power_w: 100, avg_hr: 170, source: 'device', start_lap: false, comparable: false },
];
const DEVICE = [
  { index: 0, start_offset_s: 0, duration_s: 630, distance_m: 2000, avg_power_w: 120, avg_hr: 110 },
  { index: 1, start_offset_s: 630, duration_s: 183, distance_m: 550, avg_power_w: 240, avg_hr: 172 },
  { index: 2, start_offset_s: 813, duration_s: 17, distance_m: 50, avg_power_w: 260, avg_hr: 172 },
];
const WORKOUT = {
  id: 'w1', date: '2026-10-17', sport: 'bike', source: 'fit', kind: 'race', distance_m: 5000, duration_min: 25, laps: DEVICE, pauses: [],
  analytics: {
    laps: CANONICAL,
    intervals: { efforts_detected: 0, detection_basis: 'power', matched_to_prescription: false, efforts: [], race_laps: [] },
    race_efficiency: {
      verdict: 'Efficiency held', trend: {},
      laps: [
        { lap: 1, start_lap: true, time_s: 150, np_w: 250, avg_hr: 170, ef: 1.47 },
        { lap: 2, time_s: 200, np_w: 240, avg_hr: 172, ef: 1.4 },
        { lap: 3, time_s: 200, np_w: 238, avg_hr: 173, ef: 1.38 },
      ],
    },
  },
};

describe('canonical laps view', () => {
  it('labels the start lap and the laps left out of comparisons', () => {
    const m = buildCanonicalLaps(WORKOUT);
    expect(m.rows.map((r) => r[0])).toEqual(['1 (start)', '2', '3', '4 (partial)']);
    expect(m.rows[0].slice(1)).toEqual(['450 m', '2:30', '250 W', '170']);
  });

  it('has no canonical table without canonical laps, and no device table either', () => {
    const plain = { ...WORKOUT, analytics: {} };
    expect(buildCanonicalLaps(plain)).toBeNull();
    expect(buildDeviceLaps(plain)).toBeNull();
  });

  it('puts the device laps in Raw analysis only, and the canonical laps in the main view', () => {
    const closed = renderWorkoutDetail(WORKOUT, { rawAnalysisOpen: false });
    expect(closed).toContain('canonical-laps');
    expect(closed).toContain('1 (start)');
    expect(closed).not.toContain('as recorded');
    const open = renderWorkoutDetail(WORKOUT, { rawAnalysisOpen: true });
    const raw = open.slice(open.indexOf('class="detail-section raw-analysis"'));
    expect(raw).toContain('Device laps (3, as recorded)');
    expect(open.slice(0, open.indexOf('class="detail-section raw-analysis"'))).not.toContain('Device laps');
  });

  it('shows the device laps table as before when the analysis has no canonical laps', () => {
    const html = renderWorkoutDetail({ ...WORKOUT, analytics: {} }, { rawAnalysisOpen: null });
    expect(html).toContain('<h4>Laps (3)</h4>');
    expect(html).not.toContain('canonical-laps');
  });

  it('numbers the race analysis laps like the canonical laps and marks the start lap', () => {
    const pacing = {
      status: 'ready', error: null,
      data: {
        race_execution: null, race_phases: { phases: [] },
        gps_laps: { laps: CANONICAL.map((l) => ({ lap_n: l.n, start_lap: l.start_lap, comparable: l.comparable, duration_s: l.duration_s, normalized_power_w: l.avg_power_w, avg_speed_mps: 4, total_work_kj: 1, variability_index: 1.1, coasting_s: 3 })) },
      },
    };
    const m = buildRawAnalysis(WORKOUT, pacing);
    expect(m.race.laps.map((r) => r[0])).toEqual(['1 (start)', '2', '3', '4 (partial)']);
    expect(m.race.laps[0][1]).toBe('2:30');
  });

  it('marks the start lap in the efficiency table', () => {
    const re = buildRaceEfficiency(WORKOUT);
    expect(re.laps.rows.map((r) => r[0])).toEqual(['1 (start)', '2', '3']);
  });
});
