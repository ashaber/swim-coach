import { describe, it, expect } from 'vitest';
import { buildRawAnalysis, scoreView, EFFORT_COLUMNS } from '../../src/analysis.js';

const effort = (n, extra = {}) => ({
  n, start_s: 900 + (n - 1) * 60, duration_s: 40, avg_w: 308.4, avg_hr: 150, target_w: 310.5,
  hr_drift_bpm: 2.2, fade_pct: 1.2, verdict: 'in band', in_target_band: true, round_n: 1, rep_in_round: n, ...extra,
});

const INTERVALS = {
  efforts_detected: 2, detection_basis: 'power', matched_to_prescription: true, prescribed_count: 2,
  detection_source: 'laps', reps_completed: 2, reps_in_band_pct: 100, fade_across_reps_pct: 0.4,
  fade_across_rounds_pct: null, target_zone: 'Z5', target_band_w: [289.8, 331.2],
  decoupling_tightened_pct: 20.8, decoupling_note: 'measured on working time', baseline_altitude_m: 823,
  baseline_altitude_source: 'home_elevation',
  efforts: [effort(1), effort(2, { in_target_band: false, avg_w: 250 })],
  rounds: [{ n: 1, reps_prescribed: 2, reps_completed: 2, avg_w: 279.2, avg_hr: 150, reps_in_band: 1, fade_within_pct: 3.1 }],
};

const EXECUTION = {
  kind: 'workout', score: 87.4, reason: null,
  components: [
    { name: 'intensity', score: 50, weight: 0.5, detail: '50% of reps in band' },
    { name: 'completion', score: 100, weight: 0.3, detail: '2/2 reps' },
    { name: 'consistency', score: null, weight: 0, detail: 'too few reps' },
  ],
};

describe('scoreView', () => {
  it('shows headline and per-component score, effective weight and detail', () => {
    const v = scoreView(EXECUTION, 'Execution score');
    expect(v.headline).toBe('87 / 100');
    expect(v.components[0]).toEqual({ name: 'intensity', score: '50', weight: '50%', detail: '50% of reps in band' });
    expect(v.components[2].score).toBe('—');
    expect(v.components[2].weight).toBe('—');
    expect(v.reason).toBeNull();
  });

  it('says why an unscored workout has no score', () => {
    const v = scoreView({ kind: 'workout', score: null, reason: 'not scored: no match', components: [] }, 'Execution score');
    expect(v.headline).toBe('Not scored');
    expect(v.reason).toBe('not scored: no match');
    expect(scoreView(null, 't')).toBeNull();
  });

  it('prettifies underscore component names', () => {
    const v = scoreView({ kind: 'race', score: 90, components: [{ name: 'pacing_evenness', score: 90, weight: 1, detail: 'd' }] }, 'Race');
    expect(v.components[0].name).toBe('pacing evenness');
  });
});

describe('buildRawAnalysis', () => {
  const workout = { analytics: { intervals: INTERVALS }, quality: { execution: EXECUTION } };

  it('returns null when the workout has no analyzer output at all', () => {
    expect(buildRawAnalysis({ analytics: null }, undefined)).toBeNull();
    expect(buildRawAnalysis({ analytics: { intervals: null } }, undefined)).toBeNull();
    expect(buildRawAnalysis(null, undefined)).toBeNull();
  });

  it('lays out the summary like the baseline doc', () => {
    const m = buildRawAnalysis(workout, undefined);
    const rows = Object.fromEntries(m.summary);
    expect(rows['Matched to prescription']).toBe('yes');
    expect(rows['Target band']).toBe('289.8-331.2 W');
    expect(rows['Reps in band']).toBe('100%');
    expect(rows['Fade across reps']).toBe('+0.4%');
    expect(rows['Decoupling (working time)']).toBe('+20.8%');
    expect(rows['Baseline altitude']).toBeUndefined();
    expect(rows['Home altitude (baseline)']).toBe('823 m (home elevation)');
    expect(rows['Altitude']).toBeUndefined();
    expect(m.score.headline).toBe('87 / 100');
  });

  it('shows the ride-level altitude note, keeping the baseline labeled as home', () => {
    const note = 'Rode at ~1650 m (~5,410 ft), ~827 m above home (823 m): expect ~5% less sustainable power. Targets not adjusted (adjusts at +1000 m).';
    const w = { analytics: { intervals: { ...INTERVALS, ride_altitude_m: 1650, ride_altitude_gain_m: 827, ride_altitude_note: note } } };
    const rows = Object.fromEntries(buildRawAnalysis(w, undefined).summary);
    expect(rows['Altitude']).toBe(note);
    expect(rows['Home altitude (baseline)']).toBe('823 m (home elevation)');
  });

  it('falls back to the altitude vs home when there is no note', () => {
    const w = { analytics: { intervals: { ...INTERVALS, ride_altitude_m: 1100, ride_altitude_gain_m: 277, ride_altitude_note: null } } };
    const rows = Object.fromEntries(buildRawAnalysis(w, undefined).summary);
    expect(rows['Altitude']).toBe('~1100 m (+277 m vs home 823 m)');
  });

  it('builds one row per effort with target band, verdict, fade and drift', () => {
    const m = buildRawAnalysis(workout, undefined);
    expect(m.efforts.columns).toEqual(EFFORT_COLUMNS);
    expect(m.efforts.rows).toHaveLength(2);
    const [r1, r2] = m.efforts.rows;
    expect(r1.length).toBe(EFFORT_COLUMNS.length);
    expect(r1.slice(0, 8)).toEqual(['1', '1.1', '15:00', '0:40', '308 W', '290-331 W', 'yes', '150']);
    expect(r1[8]).toBe('+2.2 bpm');
    expect(r1[9]).toBe('+1.2%');
    expect(r1[10]).toBe('in band');
    expect(r2[6]).toBe('no');
    expect(m.rounds.rows[0]).toEqual(['1', '2/2', '1/2', '279 W', '150', '+3.1%']);
  });

  it('handles free-detected efforts (no round, no band)', () => {
    const iv = {
      efforts_detected: 1, detection_basis: 'power', matched_to_prescription: false,
      efforts: [{ n: 1, start_s: 901, duration_s: 338, avg_w: 258.9, avg_hr: 156, target_w: null, time_in_band_pct: null, verdict: '~259W (no target supplied)' }],
    };
    const m = buildRawAnalysis({ analytics: { intervals: iv } }, undefined);
    expect(m.efforts.rows[0].slice(1, 8)).toEqual(['—', '15:01', '5:38', '259 W', '—', '—', '156']);
    expect(m.rounds).toBeNull();
    expect(m.score).toBeNull();
  });

  it('adds race analysis only once pacing has loaded, and reports loading/error states', () => {
    const pacing = {
      status: 'ready', error: null,
      data: {
        race_execution: { kind: 'race', score: 72.5, components: [{ name: 'late_fade', score: 60, weight: 1, detail: 'd' }] },
        race_phases: { phases: [
          { name: 'start', start_s: 0, end_s: 90, normalized_power_w: 400, avg_speed_mps: 5, vs_phase_1_pct: null },
          { name: 'phase_2', start_s: 700, end_s: 1300, normalized_power_w: 230, avg_speed_mps: 6, vs_phase_1_pct: -8.1, vs_phase_1_significant: true },
        ] },
        gps_laps: { laps: [], note: 'No laps detected' },
      },
    };
    const m = buildRawAnalysis(workout, pacing);
    expect(m.race.score.headline).toBe('73 / 100');
    expect(m.race.phases[1]).toEqual(['phase_2', '11:40–21:40', '230 W', '21.6 km/h', '-8.1% (real)']);
    expect(m.race.lapsNote).toBe('No laps detected');
    expect(buildRawAnalysis(workout, { status: 'loading' }).racePending).toBe(true);
    expect(buildRawAnalysis(workout, { status: 'error', error: 'no series' }).raceError).toBe('no series');
  });
});
