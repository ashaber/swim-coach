import { describe, it, expect } from 'vitest';
import { buildRawAnalysis, powerCurveView, raceCurveOf } from '../../src/analysis.js';

describe('power curve and race starts', () => {
  const curve = [
    { duration_s: 1, watts: 1100, best_42d_w: 1000, best_90d_w: 1050, is_best_42d: true, is_best_90d: true },
    { duration_s: 5, watts: 956, best_42d_w: 900, best_90d_w: 980, is_best_42d: true, is_best_90d: false },
    { duration_s: 60, watts: 353, best_42d_w: null, best_90d_w: null, is_best_42d: null, is_best_90d: null },
    { duration_s: 300, watts: 290, best_42d_w: null, best_90d_w: null, is_best_42d: null, is_best_90d: null },
  ];

  it('builds the curve table with prior bests and new-best flags', () => {
    const m = powerCurveView(curve);
    expect(m.rows[0]).toEqual(['1s', '1100 W', '1000 W', '1050 W', 'new 90-day best']);
    expect(m.rows[1]).toEqual(['5s', '956 W', '900 W', '980 W', 'new 42-day best']);
    expect(m.rows[2]).toEqual(['1min', '353 W', '—', '—', '']);
  });

  it('puts duration on a log axis and draws the 90-day line only where it exists', () => {
    const g = powerCurveView(curve).geometry;
    const xs = g.ride.split(' ').map((p) => Number(p.split(',')[0]));
    expect(xs[0]).toBe(g.plotLeft);
    expect(xs[xs.length - 1]).toBe(g.plotRight);
    // 5s -> 60s spans log10(12), 60s -> 300s spans log10(5)
    expect((xs[2] - xs[1]) / (xs[3] - xs[2])).toBeCloseTo(Math.log10(12) / Math.log10(5), 1);
    expect(g.hasBest).toBe(true);
    expect(g.bestLabel).toBe('90-day best');
    expect(g.best.split(' ')).toHaveLength(2);
    expect(g.race).toBe(false);
    expect(g.hasPrior).toBe(false);
  });

  describe('race-window curve', () => {
    const windowed = [{ duration_s: 1, watts: 900 }, { duration_s: 60, watts: 300 }];

    it('is the race view source when present, else the whole-file curve (old rows lack the field)', () => {
      expect(raceCurveOf({ power_curve: curve, race_power_curve: windowed })).toBe(windowed);
      expect(raceCurveOf({ power_curve: curve })).toBe(curve);
      expect(raceCurveOf({ power_curve: curve, race_power_curve: null })).toBe(curve);
      expect(raceCurveOf({ power_curve: curve, race_power_curve: [] })).toBe(curve);
      expect(raceCurveOf(undefined)).toBeUndefined();
    });

    it('shows no duration longer than the race window in the race table', () => {
      const m = powerCurveView(raceCurveOf({ power_curve: curve, race_power_curve: windowed }), null);
      expect(m.rows.map((r) => r[0])).toEqual(['1s', '1min']);
      expect(m.rows[0][1]).toBe('900 W');
    });
  });

  describe('race view', () => {
    const prior = {
      basis: 'plan', count: 4, single: false, label: 'Avg of 4 prior CX races', discipline: 'CX',
      dates: ['2026-10-17', '2026-10-18'], left_out: [],
      points: [{ duration_s: 1, watts: 1000, n: 4 }, { duration_s: 5, watts: 900, n: 4 }, { duration_s: 60, watts: 340, n: 3 }],
    };

    it('swaps the 90-day line for the 42-day best and adds the prior-race average', () => {
      const m = powerCurveView(curve, prior);
      expect(m.columns).toEqual(['Duration', 'This race', '42-day best', 'Prior-race avg', '']);
      expect(m.rows[0]).toEqual(['1s', '1100 W', '1000 W', '1000 W', 'new 42-day best']);
      expect(m.rows[2]).toEqual(['1min', '353 W', '—', '340 W', '']);
      expect(m.rows[3]).toEqual(['5min', '290 W', '—', '—', '']);
      expect(m.rows.flat().join(' ')).not.toMatch(/90-day/);
      expect(m.columns.join(' ')).not.toMatch(/90-day/);
      const g = m.geometry;
      expect(g.race).toBe(true);
      expect(g.bestLabel).toBe('42-day best');
      expect(g.best.split(' ')).toHaveLength(2); // 1s and 5s have a 42-day best
      expect(g.hasPrior).toBe(true);
      expect(g.prior.split(' ')).toHaveLength(3); // stops where the engine stopped
      expect(m.prior.label).toBe('Avg of 4 prior CX races');
      expect(m.prior.dates).toEqual(['2026-10-17', '2026-10-18']);
    });

    it('draws no prior line and shows the engine note when there is none', () => {
      const none = { basis: 'none', count: 0, label: 'Prior-race average', points: [], dates: [], note: 'No earlier CX races on this plan or in the prior year to compare with.' };
      const m = powerCurveView(curve, none);
      expect(m.geometry.hasPrior).toBe(false);
      expect(m.geometry.prior).toBe('');
      expect(m.prior.hasLine).toBe(false);
      expect(m.prior.note).toMatch(/No earlier CX races/);
    });

    it('draws a single prior race as a marker, not a line', () => {
      const one = { basis: 'plan', count: 1, single: true, label: 'Prior CX race (2026-10-03)', dates: ['2026-10-03'], points: [{ duration_s: 5, watts: 900, n: 1 }] };
      const m = powerCurveView(curve, one);
      expect(m.geometry.hasPrior).toBe(false);
      expect(m.geometry.priorDot).not.toBeNull();
      expect(m.prior.hasLine).toBe(true);
      expect(m.prior.single).toBe(true);
    });

    it('treats a race analysed before the field existed as no comparison', () => {
      const m = powerCurveView(curve, null);
      expect(m.geometry.race).toBe(true);
      expect(m.prior.hasLine).toBe(false);
      expect(m.prior.note).toMatch(/re-analyse|No earlier/i);
    });
  });

  it('says so when no earlier ride has a curve, and has no panel for a ride without one', () => {
    const bare = curve.map((p) => ({ ...p, is_best_42d: null, is_best_90d: null }));
    expect(powerCurveView(bare).note).toMatch(/No earlier rides/);
    expect(powerCurveView(undefined)).toBeNull();
    expect(buildRawAnalysis({ analytics: { power_curve: curve } }, undefined)).toBeNull(); // the curve is no longer a raw-panel item
  });

  it('builds the starts table with held seconds and the weak-start note', () => {
    const iv = {
      efforts_detected: 0, detection_basis: 'power', efforts: [],
      starts_flag: 'start 3 off (likely execution) -- skill rep, not fatigue',
      starts: [
        { n: 1, prescribed_s: 30, burst_start_s: 1474, burst_s: 13, peak_w: 1079, s_to_peak: 3, best_5s_w: 956, avg_w: 700, drop_vs_best_pct: null, verdict: 'peak 1079 W (reference start)' },
        { n: 3, prescribed_s: 30, burst_start_s: 1975, burst_s: 21, peak_w: 919, s_to_peak: 2, best_5s_w: 805, avg_w: 600, drop_vs_best_pct: 15.8, held_s: 21, intended_s: 30, verdict: 'x' },
      ],
    };
    const m = buildRawAnalysis({ analytics: { intervals: iv } }, undefined);
    expect(m.starts.flag).toMatch(/start 3/);
    expect(m.starts.rows[0].slice(0, 8)).toEqual(['1', '24:34', '13 s (of 30)', '1079 W', '3 s', '956 W', '700 W', '—']);
    expect(m.starts.rows[1][7]).toBe('-16%');
    expect(m.starts.rows[1][2]).toBe('21 of 30 s');
  });
});
