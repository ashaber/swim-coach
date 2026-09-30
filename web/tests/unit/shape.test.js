import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  BIKE_ZONES, ZONE_COLORS, zoneForPctFtp, zoneForWatts, zoneBandWatts, resolveTargetWatts,
  expandStructure, actualPoints, sessionForWorkout, shapeChartGeometry,
} from '../../src/shape.js';

const FTP = 276;
const ride = JSON.parse(readFileSync(new URL('../../../tests/fixtures/ride_2026_09_29_vo2_40_20.json', import.meta.url), 'utf8'));
const STRUCTURED = ride.planned_session.structured;

const step = (role, dur, target, extra = {}) => ({
  kind: 'step', label: role, role, duration_kind: 'time_s', duration_value: dur, modality: 'bike', target, ...extra,
});
const zone = (z) => ({ basis: 'zone', zone: z });

describe('zones', () => {
  it('has seven zones with a warm-to-hot colour each', () => {
    expect(BIKE_ZONES.map((z) => z.zone)).toEqual(['Z1', 'Z2', 'Z3', 'Z4', 'Z5', 'Z6', 'Z7']);
    for (const z of BIKE_ZONES) expect(ZONE_COLORS[z.zone]).toMatch(/^#[0-9a-f]{6}$/);
    expect(new Set(Object.values(ZONE_COLORS)).size).toBe(7);
  });

  it('classifies %FTP on the engine boundaries (upper bound inclusive)', () => {
    expect(zoneForPctFtp(55)).toBe('Z1');
    expect(zoneForPctFtp(55.1)).toBe('Z2');
    expect(zoneForPctFtp(105)).toBe('Z4');
    expect(zoneForPctFtp(300)).toBe('Z7');
    expect(zoneForWatts(308, FTP)).toBe('Z5');
    expect(zoneForWatts(100, null)).toBeNull();
  });

  it('resolves Z5 for FTP 276 to 289.8-331.2 W like the engine', () => {
    const band = zoneBandWatts('Z5', FTP);
    expect(band.lo).toBeCloseTo(289.8, 1);
    expect(band.hi).toBeCloseTo(331.2, 1);
  });
});

describe('resolveTargetWatts', () => {
  it('handles zone, power_w band, single power_w, and unresolvable targets', () => {
    expect(resolveTargetWatts(zone('Z2'), FTP).zone).toBe('Z2');
    expect(resolveTargetWatts(zone('Z2'), null)).toBeNull();
    expect(resolveTargetWatts({ basis: 'power_w', low: 250, high: 270 }, FTP)).toMatchObject({ lo: 250, hi: 270, zone: 'Z4' });
    const single = resolveTargetWatts({ basis: 'power_w', low: 200 }, FTP);
    expect(single.lo).toBeCloseTo(190);
    expect(single.hi).toBeCloseTo(210);
    expect(resolveTargetWatts({ basis: 'rpe', low: 5 }, FTP)).toBeNull();
    expect(resolveTargetWatts(null, FTP)).toBeNull();
  });
});

describe('expandStructure', () => {
  it('expands the real 3 x 6 x 40/20 session into the same timeline as the engine', () => {
    const { segments, total_s } = expandStructure(STRUCTURED, FTP);
    const hard = segments.filter((s) => s.role === 'interval');
    expect(hard).toHaveLength(18);
    expect(hard.every((s) => s.dur_s === 40 && s.zone === 'Z5')).toBe(true);
    expect(segments[0].role).toBe('warmup');
    expect(hard[0].start_s).toBe(900);
    // 15 min + 3 x (6 x 60 s + 4 min recovery) less the last recovery + 10 min = 55 min
    expect(total_s).toBeGreaterThan(3200);
    expect(total_s).toBeLessThan(3400);
    expect(segments.at(-1).role).toBe('cooldown');
  });

  it('expands nested repeats and keeps steps in order without gaps', () => {
    const tree = { items: [
      step('warmup', 600, zone('Z2')),
      { kind: 'repeat', repeat_mode: 'count', count: 2, steps: [
        { kind: 'repeat', repeat_mode: 'count', count: 3, steps: [step('interval', 60, zone('Z5')), step('recovery', 60, zone('Z1'))] },
        step('rest', 120, zone('Z1')),
      ] },
    ] };
    const { segments, total_s } = expandStructure(tree, FTP);
    expect(segments).toHaveLength(1 + 2 * (3 * 2 + 1));
    expect(total_s).toBe(600 + 2 * (3 * 120 + 120));
    for (let i = 1; i < segments.length; i += 1) {
      expect(segments[i].start_s).toBe(segments[i - 1].start_s + segments[i - 1].dur_s);
    }
  });

  it('skips non-time and non-power steps but still advances time for time-based ones', () => {
    const tree = { items: [
      step('steady', 300, zone('Z2')),
      step('steady', 300, { basis: 'rpe', low: 4 }),
      { ...step('steady', 1000, zone('Z2')), duration_kind: 'distance_m' },
      { ...step('steady', 10, zone('Z2')), modality: 'strength' },
      step('steady', 300, zone('Z3')),
    ] };
    const { segments, total_s } = expandStructure(tree, FTP);
    expect(segments.map((s) => [s.start_s, s.zone])).toEqual([[0, 'Z2'], [600, 'Z3']]);
    expect(total_s).toBe(900);
  });

  it('draws a ramp from its low to its high power', () => {
    const tree = { items: [step('ramp', 600, { basis: 'power_w', low: 100, high: 300 })] };
    const [seg] = expandStructure(tree, FTP).segments;
    expect(seg.startW).toBe(100);
    expect(seg.endW).toBe(300);
  });

  it('handles EMOM (for_duration) and AMRAP repeats and empty input', () => {
    const emom = { items: [{ kind: 'repeat', repeat_mode: 'for_duration', duration_s: 600, interval_s: 120, steps: [step('interval', 60, zone('Z5'))] }] };
    const r = expandStructure(emom, FTP);
    expect(r.segments).toHaveLength(5);
    expect(r.segments[1].start_s).toBe(120);
    expect(r.total_s).toBe(600);
    const amrap = { items: [{ kind: 'repeat', repeat_mode: 'amrap', duration_s: 600, steps: [step('interval', 100, zone('Z4'))] }] };
    expect(expandStructure(amrap, FTP).segments).toHaveLength(6);
    expect(expandStructure(null, FTP)).toEqual({ segments: [], total_s: 0 });
  });

  it('never returns without a zone->watts conversion when FTP is unknown', () => {
    expect(expandStructure(STRUCTURED, null).segments).toHaveLength(0);
  });
});

describe('actualPoints / sessionForWorkout', () => {
  it('prefers the power profile, falls back to laps, else empty', () => {
    expect(actualPoints([[0, 100], [10, 120]], [])).toEqual([[0, 100], [10, 120]]);
    const laps = [{ start_offset_s: 0, duration_s: 60, avg_power_w: 150 }, { start_offset_s: 60, duration_s: 60 }, { start_offset_s: 120, duration_s: 30, avg_power_w: 300 }];
    expect(actualPoints(null, laps)).toEqual([[0, 150], [60, 150], [120, 300], [150, 300]]);
    expect(actualPoints(null, [])).toEqual([]);
  });

  it('finds the planned session by link, then by same date and sport', () => {
    const weeks = [{ sessions: [{ id: 's1', date: '2026-09-29', sport: 'bike' }, { id: 's2', date: '2026-09-30', sport: 'swim_pool' }] }];
    const linked = { id: 'w1', planned_session_id: 's2', date: '2026-10-05', sport: 'bike' };
    expect(sessionForWorkout(linked, weeks).id).toBe('s2');
    const loose = { id: 'w2', planned_session_id: null, date: '2026-09-29T18:00:00', sport: 'bike' };
    expect(sessionForWorkout(loose, weeks).id).toBe('s1');
    expect(sessionForWorkout({ id: 'w3', date: '2026-01-01', sport: 'bike' }, weeks)).toBeNull();
    expect(sessionForWorkout(null, weeks)).toBeNull();
  });
});

describe('shapeChartGeometry', () => {
  const plan = expandStructure(STRUCTURED, FTP);

  it('is empty without FTP or without anything to draw', () => {
    expect(shapeChartGeometry({ ...plan, ftp: null })).toMatchObject({ isEmpty: true, reason: 'ftp' });
    expect(shapeChartGeometry({ segments: [], total_s: 0, actual: [], ftp: FTP })).toMatchObject({ isEmpty: true, reason: 'nothing' });
  });

  it('lays out planned bars inside the plot, in time order, colour-coded by zone', () => {
    const g = shapeChartGeometry({ ...plan, ftp: FTP });
    expect(g.isEmpty).toBe(false);
    expect(g.bars).toHaveLength(plan.segments.length);
    expect(g.hasActual).toBe(false);
    for (const b of g.bars) {
      expect(b.x).toBeGreaterThanOrEqual(g.plotLeft - 0.001);
      expect(b.x + b.w).toBeLessThanOrEqual(g.plotRight + 0.001);
      expect(b.bandTop).toBeLessThanOrEqual(b.bandBottom);
    }
    const xs = g.bars.map((b) => b.x);
    expect([...xs].sort((a, b) => a - b)).toEqual(xs);
    const z5 = g.bars.find((b) => b.zone === 'Z5');
    const z1 = g.bars.find((b) => b.zone === 'Z1');
    expect(z5.color).toBe(ZONE_COLORS.Z5);
    expect(z5.bandTop).toBeLessThan(z1.bandTop); // hotter zone plots higher (smaller y)
    expect(g.legend.map((l) => l.zone)).toEqual(['Z1', 'Z2', 'Z5']);
    expect(g.legend.find((l) => l.zone === 'Z5').range).toBe('290-331 W');
  });

  it('overlays the actual power split into same-zone runs that join without gaps', () => {
    const actual = [[0, 100], [10, 110], [20, 300], [30, 310], [40, 100]];
    const g = shapeChartGeometry({ ...plan, actual, ftp: FTP });
    expect(g.hasActual).toBe(true);
    expect(g.actualRuns.map((r) => r.zone)).toEqual(['Z1', 'Z5', 'Z1']);
    const lastOfFirst = g.actualRuns[0].points.split(' ').at(-1);
    expect(g.actualRuns[1].points.split(' ')[0]).toBe(lastOfFirst);
  });

  it('extends the time axis to a ride longer than the plan and draws actual-only charts', () => {
    const g = shapeChartGeometry({ segments: [], total_s: 0, actual: [[0, 150], [4000, 160]], ftp: FTP });
    expect(g.totalS).toBe(4000);
    expect(g.hasPlan).toBe(false);
    expect(g.xTicks.length).toBeGreaterThan(2);
    expect(g.yTicks[0].label).toBe('0');
  });
});
