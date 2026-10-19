import { describe, it, expect } from 'vitest';
import { renderWorkoutDetail } from '../../src/views.js';
import { buildMasterLaps, buildDeviceLaps, buildRawAnalysis, buildRaceEfficiency, buildPacingEffort, buildMtbDynamics, buildCourseSectors } from '../../src/analysis.js';

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

const PACING = {
  status: 'ready', error: null,
  data: {
    race_execution: null, race_phases: { phases: [{ name: 'start', start_s: 0, end_s: 60, normalized_power_w: 400, avg_speed_mps: 4, vs_phase_1_pct: null }] },
    gps_laps: { laps: CANONICAL.map((l) => ({ lap_n: l.n, start_lap: l.start_lap, comparable: l.comparable, duration_s: l.duration_s, normalized_power_w: l.avg_power_w + 5, avg_speed_mps: 3, total_work_kj: 30 + l.n, variability_index: 1.1, coasting_s: 3 })) },
  },
};
const MTB = { laps: [{ lap: 1, avg_flow: 5, grit: 10, jumps: 2 }, { lap: 2, avg_flow: 6, grit: 11, jumps: 3 }] };
const WITH_BLOCKS = { ...WORKOUT, analytics: { ...WORKOUT.analytics, mtb_dynamics: MTB } };
const rawPart = (html) => html.slice(html.indexOf('class="detail-section raw-analysis"'));
const mainPart = (html) => html.slice(0, html.indexOf('class="detail-section raw-analysis"'));

describe('master lap table (Raw analysis)', () => {
  it('has one row per canonical lap, labelled, with every lap metric that exists', () => {
    const m = buildMasterLaps(WITH_BLOCKS, PACING);
    expect(m.rows.map((r) => r[0])).toEqual(['1 (start)', '2', '3', '4 (partial)']);
    expect(m.columns).toEqual(expect.arrayContaining(['Lap', 'Source', 'Start', 'Dist', 'Time', 'Speed', 'Avg W', 'NP', 'HR', 'EF', 'VI', 'Coasting', 'Work (kJ)', 'Grit', 'Flow', 'Jumps']));
    const row = Object.fromEntries(m.columns.map((c, i) => [c, m.rows[1][i]]));
    expect(row).toMatchObject({ Source: 'merged', Start: '10:30', Dist: '600 m', Time: '3:20', 'Avg W': '240 W', NP: '240 W', HR: '172', Grit: '11', Flow: '6', Jumps: '3', VI: '1.1', 'Work (kJ)': '32' });
    expect(row.EF).toBe('1.40');
  });

  it('leaves out columns nothing fills, and is null without canonical laps', () => {
    const m = buildMasterLaps(WORKOUT, undefined);
    expect(m.columns).not.toContain('Grit');
    expect(m.columns).not.toContain('VI');
    expect(buildMasterLaps({ ...WORKOUT, analytics: {} }, undefined)).toBeNull();
  });

  it('puts the master table and the device laps in Raw analysis, scrollable with a sticky first column', () => {
    const closed = renderWorkoutDetail(WITH_BLOCKS, { rawAnalysisOpen: false, pacing: PACING });
    expect(closed).not.toContain('master-laps');
    expect(closed).not.toContain('<h4>Laps (');
    const open = renderWorkoutDetail(WITH_BLOCKS, { rawAnalysisOpen: true, pacing: PACING });
    expect(mainPart(open)).not.toContain('master-laps');
    const raw = rawPart(open);
    expect(raw).toContain('master-laps-table');
    expect(raw).toContain('1 (start)');
    expect(raw).toContain('Device laps (3, as recorded)');
    expect(raw.indexOf('master-laps-table')).toBeLessThan(raw.indexOf('Device laps (3'));
  });

  it('keeps device laps in Raw only for a bike ride without canonical laps, and no lap table in the main view', () => {
    const plain = { ...WORKOUT, kind: 'workout', analytics: {} };
    const open = renderWorkoutDetail(plain, { rawAnalysisOpen: true });
    expect(mainPart(open)).not.toContain('laps-table');
    expect(rawPart(open)).toContain('Device laps (3, as recorded)');
    expect(buildRawAnalysis(plain, undefined).deviceLaps.rows).toHaveLength(3);
  });

  it('still shows a swim\'s device laps in the main view', () => {
    const swim = { ...WORKOUT, sport: 'swim', analytics: {} };
    const html = renderWorkoutDetail(swim, { rawAnalysisOpen: null });
    expect(html).toContain('<h4>Laps (3)</h4>');
  });
});

describe('focused bike tables share no columns but Lap', () => {
  it('lap efficiency: Lap, Time, +best, NP, HR, EF with the start lap marked and no +best for it', () => {
    const re = buildRaceEfficiency(WORKOUT);
    expect(re.laps.columns).toEqual(['Lap', 'Time', '+best', 'NP', 'HR', 'EF']);
    expect(re.laps.rows.map((r) => r[0])).toEqual(['1 (start)', '2', '3']);
    expect(re.laps.rows[0][2]).toBe('—');
    expect(re.laps.rows[1][2]).toBe('best');
    expect(re.laps.rows[2][2]).toBe('best'); // equal times
  });

  it('handling and terrain: Lap, Flow, Grit, Jumps, lap labels as in the master table', () => {
    const m = buildMtbDynamics(WITH_BLOCKS);
    expect(m.laps.columns).toEqual(['Lap', 'Flow', 'Grit', 'Jumps']);
    expect(m.laps.rows.map((r) => r[0])).toEqual(['1 (start)', '2']);
  });

  it('pacing and effort: phases plus Lap, VI, Coasting, Work (kJ)', () => {
    const m = buildPacingEffort(WORKOUT, PACING);
    expect(m.laps.columns).toEqual(['Lap', 'VI', 'Coasting', 'Work (kJ)']);
    expect(m.laps.rows[0]).toEqual(['1 (start)', '1.1', '0:03', '31']);
    expect(m.phases.rows).toHaveLength(1);
  });

  it('where the time went: no separate lap table, the grid stays', () => {
    const cs = { sector_count: 2, best_lap: 1, fade: { time_change_pct: 1 }, laps: [{ lap: 1, time_s: 100, time_vs_best_s: 0, sector_times_s: [50, 50] }], sectors: [] };
    const m = buildCourseSectors({ analytics: { course_sectors: cs } });
    expect(m.laps).toBeUndefined();
    expect(m.grid.rows).toHaveLength(1);
  });

  it('the main view renders no lap table other than the focused ones', () => {
    const html = renderWorkoutDetail(WITH_BLOCKS, { rawAnalysisOpen: null, pacing: PACING });
    expect(html).toContain('Lap efficiency');
    expect(html).toContain('Handling &amp; terrain');
    expect(html).not.toContain('<h4>Race efficiency</h4>');
    expect(html).not.toContain('<h4>Mountain bike dynamics</h4>');
  });
});
