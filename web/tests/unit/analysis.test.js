import { describe, it, expect } from 'vitest';
import {
  buildCourseSectors, buildRaceEfficiency, buildCourseMap, nextSector, buildMtbDynamics, buildFreeRide, buildRawAnalysis, buildPacingEffort, scoreView, EFFORT_COLUMNS, effectiveKind, kindLabel, shouldLoadPacing, startTraceGeometry,
} from '../../src/analysis.js';

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
    const race = { ...workout, kind: 'race' };
    expect(buildRawAnalysis(workout, pacing).race).toBeNull(); // a workout-kind ride never shows the race panel
    expect(buildRawAnalysis({ ...workout, kind: 'race', kind_override: 'workout' }, pacing).race).toBeNull();
    const m = buildRawAnalysis(race, pacing);
    expect(m.race.score.headline).toBe('73 / 100');
    expect(buildPacingEffort(race, pacing).phases.rows[1]).toEqual(['phase_2', '11:40–21:40', '230 W', '21.6 km/h', '-8.1% (real)']);
    expect(buildPacingEffort(race, pacing).lapsNote).toBe('No laps detected');
    expect(buildRawAnalysis(workout, { status: 'loading' }).racePending).toBe(false);
    expect(buildRawAnalysis(race, { status: 'loading' }).racePending).toBe(true);
    expect(buildRawAnalysis(race, { status: 'error', error: 'no series' }).raceError).toBe('no series');
  });
});

describe('workout kind', () => {
  it('lets the retag win over the derived kind and labels it', () => {
    expect(effectiveKind({ kind: 'workout', kind_override: 'race' })).toBe('race');
    expect(effectiveKind({ kind: 'free_ride' })).toBe('free_ride');
    expect(effectiveKind({})).toBeNull();
    expect(kindLabel('free_ride')).toBe('Free ride');
    expect(kindLabel(null)).toBeNull();
  });

  it('fetches pacing only for a bike race or a ride matched to a planned session', () => {
    const session = { id: 's1', sport: 'bike', date: '2026-09-29', title: 'x' };
    const weeks = [{ sessions: [session] }];
    const ride = { id: 'w', sport: 'bike', date: '2026-09-29', kind: 'workout', planned_session_id: 's1' };
    const loose = { ...ride, planned_session_id: null, date: '2026-09-30' };
    expect(shouldLoadPacing(loose, weeks)).toBe(false);
    expect(shouldLoadPacing({ ...loose, kind_override: 'race' }, weeks)).toBe(true);
    expect(shouldLoadPacing(ride, weeks)).toBe(true);
    expect(shouldLoadPacing({ ...ride, sport: 'swim_pool', kind: 'race' }, weeks)).toBe(false);
    expect(shouldLoadPacing(null, weeks)).toBe(false);
  });
});

describe('start traces', () => {
  const start = {
    n: 4, intended_s: 30, stopped_at_s: 21, trace_t0: 0, verdict: 'launch 0->1100 W in 5 s',
    trace_w: [0, 187, 302, 649, 864, 1100, 721, 843, 925, 883, 857, 830, 765, 668, 639, 711, 704, 707, 694, 655, 603, 5, 22, 365, 445, 547, 543, 498, 67, 2, 2, 2, 5, 1, 0, 0, 0],
  };

  it('builds a polyline with the launch, stop and intended-end marks inside the trace', () => {
    const g = startTraceGeometry(start);
    expect(g.points.split(' ')).toHaveLength(start.trace_w.length);
    expect(g.peakW).toBe(1100);
    expect(g.launchX).toBe(2);
    expect(g.stopX).toBeGreaterThan(g.launchX);
    expect(g.plannedEndX).toBeGreaterThan(g.stopX);
    const ys = g.points.split(' ').map((p) => Number(p.split(',')[1]));
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(0);
    expect(Math.max(...ys)).toBeLessThanOrEqual(g.height);
  });

  it('drops marks outside the trace and returns null without a trace', () => {
    expect(startTraceGeometry({ ...start, intended_s: 90 }).plannedEndX).toBeNull();
    expect(startTraceGeometry({ n: 1 })).toBeNull();
  });

  it('puts a trace on each start in the starts model', () => {
    const m = buildRawAnalysis({ analytics: { intervals: { efforts_detected: 0, starts: [start, { n: 5 }] } } }, undefined);
    expect(m.starts.traces).toHaveLength(1);
    expect(m.starts.traces[0].verdict).toBe('launch 0->1100 W in 5 s');
  });
});

const FREE_RIDE = {
  moving_s: 9513, coasting_s: 3590, coasting_pct: 37.7,
  power_zones: [
    { zone: 'Z1', seconds: 1376, pct: 23.2 }, { zone: 'Z2', seconds: 1310, pct: 22.1 },
    { zone: 'Z3', seconds: 0, pct: 0 }, { zone: 'Z4', seconds: 870, pct: 54.4 }, { zone: 'Z7', seconds: 10, pct: 0.3 },
  ],
  tempo_creep_note: null,
  notable_efforts: [
    { duration_s: 1200, start_offset_s: 1766, avg_w: 236, pct_ftp: 85.5, avg_hr: 156, altitude_gain_m: 185.4, avg_grade_pct: 3.5, label: 'tempo climb', new_best_90d: true },
    { duration_s: 60, start_offset_s: 2616, avg_w: 346, pct_ftp: 125.4, avg_hr: null, altitude_gain_m: null, avg_grade_pct: null, label: null },
  ],
  matches: {
    count: 27, time_above_ftp_s: 723, kj_above_ftp: 45.4,
    efforts: [1, 2, 3, 4].map((i) => ({ start_offset_s: 100 * i, duration_s: 40, avg_w: 370, peak_w: 440, kj_above_ftp: 4.5 })),
  },
  cost: { note: 'TSS 151, IF 0.76' },
  steady_drift: [], steady_note: 'No steady stretch of 20 min or more (power varied or stops); no drift read.',
  data_quality_notes: ['Altitude range is only 14 m.'],
};

describe('buildFreeRide', () => {
  it('is null without a free_ride block', () => {
    expect(buildFreeRide({ analytics: {} })).toBeNull();
    expect(buildFreeRide(null)).toBeNull();
  });

  it('builds the zone bar from non-empty zones and hides slivers from the bar but not the legend', () => {
    const m = buildFreeRide({ analytics: { free_ride: FREE_RIDE } });
    expect(m.zoneBar.map((z) => z.zone)).toEqual(['Z1', 'Z2', 'Z4', 'Z7']);
    expect(m.zoneBar.map((z) => z.drawn)).toEqual([true, true, true, false]);
    expect(m.zoneBar[0].label).toBe('Z1 Recovery 23 min (23%)');
    expect(m.coasting).toBe('Coasting 38% of moving time (not in the bar).');
  });

  it('formats efforts, flags new bests, and keeps only the top three matches', () => {
    const m = buildFreeRide({ analytics: { free_ride: FREE_RIDE } });
    expect(m.efforts.rows[0]).toEqual(['20 min', '29:26', '236 W', '86%', '156', '+185 m at 3.5%', 'tempo climb (new 90-day best)']);
    expect(m.efforts.rows[1].slice(4)).toEqual(['—', '—', '']);
    expect(m.matches.summary).toBe('27 matches burned: 12:03 above FTP, 45.4 kJ over FTP.');
    expect(m.matches.rows).toHaveLength(3);
  });

  it('carries the cost, quality and no-steady-stretch notes', () => {
    const m = buildFreeRide({ analytics: { free_ride: FREE_RIDE } });
    expect(m.cost).toBe('TSS 151, IF 0.76');
    expect(m.quality).toEqual(['Altitude range is only 14 m.']);
    expect(m.drift).toEqual([]);
    expect(m.driftNote).toMatch(/No steady stretch/);
  });

  it('lists steady-stretch drift instead of the note when there is one', () => {
    const fr = { ...FREE_RIDE, steady_drift: [{ start_offset_s: 600, duration_min: 45, avg_w: 200, drift_pct: 5.4 }] };
    const m = buildFreeRide({ analytics: { free_ride: fr } });
    expect(m.drift).toEqual(['Steady 45 min from 10:00: 200 W, drift +5.4%.']);
    expect(m.driftNote).toBeNull();
  });
});

describe('buildMtbDynamics', () => {
  it('is null without the block', () => {
    expect(buildMtbDynamics({ analytics: {} })).toBeNull();
    expect(buildMtbDynamics(null)).toBeNull();
  });

  it('shows totals, jumps and a per-lap table', () => {
    const m = buildMtbDynamics({
      analytics: {
        mtb_dynamics: {
          total_grit: 92.05, avg_flow: 4.4, jump_count: 28,
          jumps: { count: 28, max_height_m: 1.2, max_hang_time_s: 0.8, best_score: 70 },
          laps: [
            { lap: 1, duration_s: 300, avg_power_w: 210, grit: 11.3, avg_flow: 6.1, jumps: 3 },
            { lap: 2, duration_s: 312, avg_power_w: 208, grit: 11.9, avg_flow: null, jumps: null },
          ],
        },
      },
    });
    expect(m.summary).toEqual(['Total grit 92.05', 'Avg flow 4.4', '28 jumps, max height 1.2 m, max hang time 0.8 s, best score 70']);
    expect(m.laps.columns).toEqual(['Lap', 'Flow', 'Grit', 'Jumps']);
    expect(m.laps.rows[0]).toEqual(['1', '6.1', '11.3', '3']);
    expect(m.laps.rows[1]).toEqual(['2', '—', '11.9', '—']);
    expect(m.note).toMatch(/lower Flow is smoother/);
  });
});

describe('buildCourseSectors', () => {
  const cs = {
    sector_count: 8, best_lap: 1,
    fade: { time_change_pct: 12, power_change_pct: -1.5, flow_change: 1.6 },
    laps: [
      { lap: 1, time_s: 300, time_vs_best_s: 0, avg_power_w: 210, avg_flow: 3 },
      { lap: 2, time_s: 336, time_vs_best_s: 36, avg_power_w: 207, avg_flow: 4.6 },
    ],
    sectors: [{ sector: 5, best_time_s: 40, mean_loss_s: 9.2, total_loss_s: 9.2, flow_vs_best: 1.4, avg_grit: 0.3 }],
    top_loss_sectors: [5],
  };

  it('is null without the block', () => {
    expect(buildCourseSectors({ analytics: {} })).toBeNull();
  });

  it('shows the fade, the laps and the top loss sectors', () => {
    const m = buildCourseSectors({ analytics: { course_sectors: cs } });
    expect(m.trend).toBe('Time +12% first to last lap, power -1.5%, flow +1.6');
    expect(m.laps).toBeUndefined(); // the lap table lives in Lap efficiency and the Raw master table
  });

  describe('lap x sector grid', () => {
    // Lap 2 wins sector 1, lap 1 wins sector 2, lap 3 is slowest everywhere.
    const g = {
      sector_count: 3, best_lap: 1, fade: { time_change_pct: 5 }, top_loss_sectors: [2],
      ideal_lap_s: 59, ideal_gap_s: 1,
      laps: [
        { lap: 1, time_s: 60, time_vs_best_s: 0, sector_times_s: [21, 19, 20] },
        { lap: 2, time_s: 61, time_vs_best_s: 1, sector_times_s: [20, 21, 20] },
        { lap: 3, time_s: 66, time_vs_best_s: 6, sector_times_s: [23, 23, 20] },
      ],
      sectors: [],
    };
    const grid = (selected) => buildCourseSectors({ analytics: { course_sectors: g } }, selected).grid;

    it('is null without per-lap sector times', () => {
      const bare = { ...g, laps: g.laps.map(({ sector_times_s: _, ...l }) => l) };
      expect(buildCourseSectors({ analytics: { course_sectors: bare } }).grid).toBeNull();
    });

    it('measures every cell against the best time through that sector, never below zero', () => {
      const m = grid();
      expect(m.sectors.map((s) => s.best)).toEqual(['20.0', '19.0', '20.0']);
      expect(m.rows.map((r) => r.cells.map((c) => c.text))).toEqual([
        ['1.0', '0.0', '0.0'], ['0.0', '2.0', '0.0'], ['3.0', '4.0', '0.0'],
      ]);
      expect(m.rows.flatMap((r) => r.cells).every((c) => c.loss >= 0)).toBe(true);
    });

    it('marks the best cell per sector and heat-tints the rest by loss', () => {
      const m = grid();
      expect(m.rows[0].cells[1].best).toBe(true);
      expect(m.rows[1].cells[0].best).toBe(true);
      expect(m.rows[0].cells[1].heat).toBe(0);
      expect(m.rows[2].cells[1].heat).toBe(4); // the biggest loss in the grid
      expect(m.rows[0].cells[0].heat).toBeGreaterThan(0);
      expect(m.rows[2].cells[0].heat).toBeGreaterThan(m.rows[0].cells[0].heat);
    });

    it('labels each lap with its time and gap to the ideal lap, and sums the footer', () => {
      const m = grid();
      expect(m.rows.map((r) => [r.label, r.time, r.gap])).toEqual([
        ['Lap 1', '1:00', '+1.0 s'], ['Lap 2', '1:01', '+2.0 s'], ['Lap 3', '1:06', '+7.0 s'],
      ]);
      expect(m.sectors.map((s) => s.total)).toEqual(['4.0', '6.0', '0.0']);
      expect(m.sectors.map((s) => s.spread)).toEqual(['3.0', '4.0', '0.0']);
      expect(m.ideal).toBe('Ideal lap 0:59 · best lap is 1.0 s slower');
      expect(m.caption).toBe('Each cell: seconds slower than your best time through that sector. Ideal lap = your best sectors combined.');
    });

    it('flags the selected sector column', () => {
      const m = grid(2);
      expect(m.sectors.map((s) => s.selected)).toEqual([false, true, false]);
      expect(m.rows[0].cells.map((c) => c.selected)).toEqual([false, true, false]);
    });
  });
});

describe('course map', () => {
  // Synthetic loop in local metres: sector 1 runs east along the south edge, sector 2 north, sector 3 west.
  const track = {
    sectors: [
      { sector: 1, points: [[0, 0], [100, 0]], label: [50, 0] },
      { sector: 2, points: [[100, 0], [100, 50]], label: [100, 25] },
      { sector: 3, points: [[100, 50], [0, 50]], label: [50, 50] },
    ],
  };
  const cs = {
    sector_count: 3, best_lap: 1, fade: { time_change_pct: 1 }, laps: [], track,
    sectors: [
      { sector: 1, best_time_s: 20, mean_loss_s: 0, total_loss_s: 0 },
      { sector: 2, best_time_s: 10, mean_loss_s: 3, total_loss_s: 6, spread_s: 4 },
      { sector: 3, best_time_s: 20, mean_loss_s: 1, total_loss_s: 2 },
    ],
    top_loss_sectors: [2, 3],
  };
  const xy = (points) => points.split(' ').map((p) => p.split(',').map(Number));

  it('is null without a track', () => {
    expect(buildCourseMap({ ...cs, track: undefined })).toBeNull();
    expect(buildCourseSectors({ analytics: { course_sectors: { ...cs, track: undefined } } }).map).toBeNull();
  });

  it('projects north-up with one uniform scale that fits the width', () => {
    const m = buildCourseMap(cs);
    expect(m.width).toBe(320);
    const [a, b] = xy(m.sectors[0].points);
    const [, north] = xy(m.sectors[1].points);
    expect(b[0]).toBeGreaterThan(a[0]); // east is right
    expect(b[1]).toBe(a[1]);
    expect(north[1]).toBeLessThan(a[1]); // north is up (smaller SVG y)
    const allX = m.sectors.flatMap((s) => xy(s.points).map((p) => p[0]));
    expect(Math.max(...allX)).toBeLessThanOrEqual(320);
    expect(m.start).toEqual({ x: a[0], y: a[1] });
  });

  it('colours the worst loss hot, the other top-loss sectors warm, the rest neutral', () => {
    expect(buildCourseMap(cs).sectors.map((s) => s.tone)).toEqual(['neutral', 'hot', 'warm']);
  });

  it('highlights the selected sector and dims the rest', () => {
    const m = buildCourseMap(cs, 2);
    expect(m.sectors.map((s) => s.selected)).toEqual([false, true, false]);
    expect(m.sectors.map((s) => s.dim)).toEqual([true, false, true]);
    expect(buildCourseMap(cs).sectors.some((s) => s.dim || s.selected)).toBe(false);
    expect(m.sectors[1].aria).toBe('Sector 2, loses 6.0 s in total');
  });

  it('frames the whole lap, the selected sector, or a gesture view (which wins)', () => {
    const whole = buildCourseMap(cs);
    expect(whole.viewBox).toBe(`0 0 ${whole.width} ${whole.height}`);
    expect(whole.zoomed).toBe(false);
    expect(whole.k).toBe(1);
    const small = { ...cs, track: { sectors: [...track.sectors.slice(0, 2), { sector: 3, points: [[100, 50], [90, 50]], label: [95, 50] }] } };
    const framed = buildCourseMap(small, 3);
    expect(framed.zoomed).toBe(true);
    expect(framed.k).toBeLessThan(1);
    const gesture = { x: 10, y: 10, w: 80, h: 50 };
    const g = buildCourseMap(cs, 2, gesture);
    expect(g.viewBox).toBe('10 10 80 50');
    expect(g.k).toBeCloseTo(80 / whole.width, 3);
  });

  it('shares the selection with the table and toggles it', () => {
    const m = buildCourseSectors({ analytics: { course_sectors: cs } }, 2);
    expect(m.selected).toMatch(/^Sector 2: best time 10.0 s, loses 6.0 s in total/);
    expect(m.selected).toMatch(/spread 4.0 s/);
    expect(nextSector(null, 2)).toBe(2);
    expect(nextSector(2, 2)).toBeNull();
    expect(nextSector(2, 3)).toBe(3);
  });
});

describe('buildRaceEfficiency', () => {
  const re = {
    verdict: 'Decoupled: EF -8%, HR +8 bpm, power -4%, flow rougher',
    laps: [
      { lap: 11, time_s: 342, np_w: 238.3, avg_hr: 169.7, ef: 1.404, avg_flow: 5.95 },
      { lap: 12, time_s: 336, np_w: 236.9, avg_hr: 175.3, ef: 1.352, avg_flow: null },
    ],
    trend: { decoupling_pct: -5.2, ef_slope_per_lap: -0.052, hr_slope_bpm_per_lap: 5.6, power_slope_w_per_lap: -1.4 },
  };

  it('is null without the block or laps', () => {
    expect(buildRaceEfficiency({ analytics: {} })).toBeNull();
    expect(buildRaceEfficiency({ analytics: { race_efficiency: { ...re, laps: [] } } })).toBeNull();
  });

  it('carries the verdict, the per-lap rows and the slopes', () => {
    const m = buildRaceEfficiency({ analytics: { race_efficiency: re } });
    expect(m.verdict).toBe(re.verdict);
    expect(m.decoupled).toBe(true);
    expect(m.laps.columns).toEqual(['Lap', 'Time', '+best', 'NP', 'HR', 'EF']);
    expect(m.laps.rows[0]).toEqual(['11', '5:42', '+6 s', '238 W', '170', '1.40']);
    expect(m.laps.rows[1]).toEqual(['12', '5:36', 'best', '237 W', '175', '1.35']);
    expect(m.slopes).toBe('EF -0.052/lap, HR +5.6 bpm/lap, NP -1.4 W/lap');
  });

  it('is not decoupled when efficiency held', () => {
    const m = buildRaceEfficiency({ analytics: { race_efficiency: { ...re, trend: { decoupling_pct: -1 } } } });
    expect(m.decoupled).toBe(false);
    expect(m.slopes).toBe('');
  });
});
