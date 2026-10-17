// Pure model for the "Raw analysis" panel on the workout detail view: the full
// deterministic analyzer output, laid out like docs/analyzer-baseline-*.md
// (a summary, the efforts/reps table with its target band, the round table,
// the execution-score breakdown, and race pacing for a ride that has it).
//
// Read-only and derived entirely from the cached workout (plus the lazily
// fetched pacing result when it has arrived), so it renders offline. DOM-free:
// views.js turns the returned rows into markup.

import { formatClock } from './workouts.js';
import { sessionForWorkout, ZONE_COLORS, ZONE_LABELS } from './shape.js';

const num = (v) => v !== null && v !== undefined && Number.isFinite(v);
const dash = '—';

function watts(v) {
  return num(v) ? `${Math.round(v)} W` : dash;
}

function signed(v, digits = 1, unit = '%') {
  if (!num(v)) return dash;
  const r = Number(v.toFixed(digits));
  return `${r > 0 ? '+' : ''}${r}${unit}`;
}

/** Score breakdown -> `{ kind, title, headline, reason, components }`, or null when absent. */
export function scoreView(execution, title) {
  if (!execution) return null;
  const scored = num(execution.score);
  return {
    kind: execution.kind,
    title,
    headline: scored ? `${Math.round(execution.score)} / 100` : 'Not scored',
    reason: scored ? null : (execution.reason || 'Not enough data to score.'),
    components: (execution.components || []).map((c) => ({
      name: c.name.replace(/_/g, ' '),
      score: num(c.score) ? String(Math.round(c.score)) : dash,
      weight: num(c.score) ? `${Math.round(c.weight * 100)}%` : dash,
      detail: c.detail,
    })),
  };
}

function altitudeVsBaseline(iv) {
  const here = `~${Math.round(iv.ride_altitude_m)} m`;
  if (!num(iv.ride_altitude_gain_m) || !num(iv.baseline_altitude_m)) return here;
  const g = Math.round(iv.ride_altitude_gain_m);
  return `${here} (${g >= 0 ? '+' : ''}${g} m vs home ${Math.round(iv.baseline_altitude_m)} m)`;
}

function summaryRows(iv) {
  const rows = [];
  rows.push(['Matched to prescription', iv.matched_to_prescription ? 'yes' : 'no']);
  if (num(iv.prescribed_count)) rows.push(['Prescribed reps', String(iv.prescribed_count)]);
  rows.push(['Efforts detected', String(iv.efforts_detected)]);
  if (iv.detection_source) rows.push(['Located from', iv.detection_source]);
  if (iv.detection_basis) rows.push(['Detection basis', iv.detection_basis]);
  if (num(iv.reps_completed)) rows.push(['Reps completed', String(iv.reps_completed)]);
  if (iv.target_zone) rows.push(['Target zone', iv.target_zone]);
  if (Array.isArray(iv.target_band_w)) rows.push(['Target band', `${iv.target_band_w[0]}-${iv.target_band_w[1]} W`]);
  if (num(iv.reps_in_band_pct)) rows.push(['Reps in band', `${iv.reps_in_band_pct}%`]);
  if (num(iv.fade_across_reps_pct)) rows.push(['Fade across reps', signed(iv.fade_across_reps_pct)]);
  if (num(iv.fade_across_rounds_pct)) rows.push(['Fade across rounds', signed(iv.fade_across_rounds_pct)]);
  if (num(iv.decoupling_tightened_pct)) rows.push(['Decoupling (working time)', signed(iv.decoupling_tightened_pct)]);
  if (iv.decoupling_note) rows.push(['Decoupling note', iv.decoupling_note]);
  if (iv.ride_altitude_note) rows.push(['Altitude', iv.ride_altitude_note]);
  else if (num(iv.ride_altitude_m)) rows.push(['Altitude', altitudeVsBaseline(iv)]);
  if (num(iv.baseline_altitude_m)) rows.push(['Home altitude (baseline)', `${Math.round(iv.baseline_altitude_m)} m (${(iv.baseline_altitude_source || '').replace('_', ' ')})`]);
  return rows;
}

export const EFFORT_COLUMNS = ['#', 'Round', 'Start', 'Dur', 'Avg W', 'Target', 'In band', 'HR', 'Drift', 'Fade (+ = faded)', 'Verdict'];

function effortRows(iv) {
  const band = Array.isArray(iv.target_band_w) ? `${Math.round(iv.target_band_w[0])}-${Math.round(iv.target_band_w[1])} W` : null;
  return (iv.efforts || []).map((e) => {
    let target = dash;
    if (band && e.in_target_band !== null && e.in_target_band !== undefined) target = band;
    else if (num(e.target_w)) target = watts(e.target_w);
    let inBand = dash;
    if (e.in_target_band === true) inBand = 'yes';
    else if (e.in_target_band === false) inBand = 'no';
    else if (num(e.time_in_band_pct)) inBand = `${Math.round(e.time_in_band_pct)}%`;
    const round = num(e.round_n) ? `${e.round_n}.${e.rep_in_round ?? ''}` : dash;
    return [
      String(e.n),
      round,
      formatClock(e.start_s) || dash,
      formatClock(e.duration_s) || dash,
      watts(e.avg_w),
      target,
      inBand,
      num(e.avg_hr) ? String(e.avg_hr) : dash,
      num(e.hr_drift_bpm) ? signed(e.hr_drift_bpm, 1, ' bpm') : dash,
      num(e.fade_pct) ? signed(e.fade_pct) : dash,
      e.verdict || dash,
    ];
  });
}

export const ROUND_COLUMNS = ['Round', 'Reps', 'In band', 'Avg W', 'Avg HR', 'Fade within (+ = faded)'];

function roundRows(iv) {
  return (iv.rounds || []).map((r) => [
    String(r.n),
    `${r.reps_completed}/${r.reps_prescribed}`,
    num(r.reps_in_band) ? `${r.reps_in_band}/${r.reps_completed}` : dash,
    watts(r.avg_w),
    num(r.avg_hr) ? String(r.avg_hr) : dash,
    num(r.fade_within_pct) ? signed(r.fade_within_pct) : dash,
  ]);
}

export const PHASE_COLUMNS = ['Phase', 'Span', 'NP', 'Speed', 'vs phase 1'];
export const LAP_COLUMNS = ['Lap', 'Time', 'NP', 'Speed', 'Work', 'VI', 'Coasting'];

function raceView(pacing) {
  if (!pacing || pacing.status !== 'ready' || !pacing.data) return null;
  const d = pacing.data;
  const speed = (v) => (num(v) ? `${(v * 3.6).toFixed(1)} km/h` : dash);
  return {
    score: scoreView(d.race_execution, 'Race execution score'),
    phases: (d.race_phases?.phases || []).map((p) => [
      p.name,
      `${formatClock(p.start_s)}–${formatClock(p.end_s)}`,
      watts(p.normalized_power_w),
      speed(p.avg_speed_mps),
      num(p.vs_phase_1_pct) ? `${signed(p.vs_phase_1_pct)}${p.vs_phase_1_significant ? ' (real)' : ''}` : dash,
    ]),
    laps: (d.gps_laps?.laps || []).map((l) => [
      String(l.lap_n),
      formatClock(l.duration_s) || dash,
      watts(l.normalized_power_w),
      speed(l.avg_speed_mps),
      num(l.total_work_kj) ? `${l.total_work_kj} kJ` : dash,
      num(l.variability_index) ? String(l.variability_index) : dash,
      num(l.coasting_s) ? formatClock(l.coasting_s) : dash,
    ]),
    lapsNote: d.gps_laps?.note || null,
  };
}


// --- Workout kind ---------------------------------------------------------------

export const KIND_OPTIONS = [
  ['workout', 'Workout'], ['race', 'Race'], ['free_ride', 'Free ride'], ['opener', 'Opener'], ['warmup', 'Warm-up'],
];

/** The kind the analyzer uses: the athlete's retag wins over the derived kind; null on rows
 * stored before kinds existed. */
export function effectiveKind(workout) {
  return workout?.kind_override || workout?.kind || null;
}

export function kindLabel(kind) {
  const hit = KIND_OPTIONS.find(([k]) => k === kind);
  return hit ? hit[1] : null;
}

/** Whether the detail view needs `GET /api/workouts/{id}/pacing`: only a bike ride, and then
 * only for a race (the race pacing panel) or a ride matched to a planned session (its
 * plan-vs-ridden overlay is drawn from the pacing response's power profile). */
export function shouldLoadPacing(workout, weeks) {
  if (!workout || workout.sport !== 'bike') return false;
  if (effectiveKind(workout) === 'race') return true;
  return sessionForWorkout(workout, weeks) !== null;
}

// --- Power curve + race starts --------------------------------------------------

// Durations shown in the table (the chart plots every stored point).
const CURVE_TABLE_S = [1, 5, 15, 30, 60, 300, 600, 1200, 3600];

function durationLabel(d) {
  return d < 60 ? `${d}s` : `${Math.round(d / 60)}min`;
}

export const POWER_CURVE_COLUMNS = ['Duration', 'This ride', '42-day best', '90-day best', ''];

function curveFlag(p) {
  if (p.is_best_90d === true) return 'new 90-day best';
  if (p.is_best_42d === true) return 'new 42-day best';
  return '';
}

/** SVG-ready geometry for the mean-max curve: log10(duration) on x, watts on y.
 * Two lines: this ride and the prior 90-day best (only where one exists). */
export function powerCurveGeometry(curve, { width = 320, height = 170 } = {}) {
  const pts = (curve || []).filter((p) => num(p.duration_s) && num(p.watts) && p.duration_s > 0);
  if (pts.length < 2) return null;
  const left = 38;
  const right = width - 8;
  const top = 8;
  const bottom = height - 24;
  const xs = pts.map((p) => Math.log10(p.duration_s));
  const x0 = xs[0];
  const x1 = xs[xs.length - 1];
  const maxW = Math.max(...pts.map((p) => Math.max(p.watts, p.best_90d_w || 0)));
  const yMax = Math.ceil(maxW / 100) * 100 || 100;
  const X = (d) => left + ((Math.log10(d) - x0) / (x1 - x0 || 1)) * (right - left);
  const Y = (w) => bottom - (w / yMax) * (bottom - top);
  const line = (rows, key) => rows.filter((p) => num(p[key])).map((p) => `${X(p.duration_s).toFixed(1)},${Y(p[key]).toFixed(1)}`).join(' ');
  const yTicks = [0, 0.5, 1].map((f) => ({ y: Y(yMax * f), label: `${Math.round(yMax * f)}` }));
  const xTicks = pts.filter((p) => CURVE_TABLE_S.includes(p.duration_s)).map((p) => ({ x: X(p.duration_s), label: durationLabel(p.duration_s) }));
  return {
    width, height, plotLeft: left, plotRight: right, yTicks, xTicks,
    ride: line(pts, 'watts'),
    best90: line(pts, 'best_90d_w'),
    hasBest90: pts.some((p) => num(p.best_90d_w)),
  };
}

function powerCurveView(curve) {
  if (!Array.isArray(curve) || curve.length === 0) return null;
  const byDur = new Map(curve.map((p) => [p.duration_s, p]));
  const rows = CURVE_TABLE_S.filter((d) => byDur.has(d)).map((d) => {
    const p = byDur.get(d);
    return [durationLabel(d), watts(p.watts), watts(p.best_42d_w), watts(p.best_90d_w), curveFlag(p)];
  });
  const anyCompared = curve.some((p) => p.is_best_42d !== null && p.is_best_42d !== undefined);
  return {
    columns: POWER_CURVE_COLUMNS,
    rows,
    geometry: powerCurveGeometry(curve),
    note: anyCompared ? null : 'No earlier rides have a stored curve yet, so no best is flagged.',
  };
}

/** SVG-ready geometry for one start's 1 Hz power trace (`trace_w`): a polyline plus x positions
 * for the launch, the point it stopped, and the intended end (each only when inside the trace). */
export function startTraceGeometry(start, { width = 160, height = 40 } = {}) {
  const w = start?.trace_w;
  if (!Array.isArray(w) || w.length < 2) return null;
  const pad = 2;
  const yMax = Math.max(...w, 1);
  const X = (i) => pad + (i / (w.length - 1)) * (width - 2 * pad);
  const Y = (v) => height - pad - (v / yMax) * (height - 2 * pad);
  const t0 = num(start.trace_t0) ? start.trace_t0 : 0;
  const mark = (sec) => (num(sec) && t0 + sec >= 0 && t0 + sec <= w.length - 1 ? Number(X(t0 + sec).toFixed(1)) : null);
  return {
    width, height,
    points: w.map((v, i) => `${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' '),
    launchX: mark(0),
    stopX: mark(start.stopped_at_s),
    plannedEndX: mark(start.intended_s),
    peakW: Math.max(...w),
  };
}

export const STARTS_COLUMNS = ['Start', 'At', 'Held', 'Peak', 'To peak', 'Best 5 s', 'Avg', 'vs best', 'Verdict'];

function startsView(iv) {
  const starts = iv?.starts || [];
  if (starts.length === 0) return null;
  return {
    columns: STARTS_COLUMNS,
    rows: starts.map((s) => [
      String(s.n),
      num(s.burst_start_s) ? formatClock(s.burst_start_s) : dash,
      num(s.held_s)
        ? `${Math.round(s.held_s)} of ${Math.round(s.intended_s ?? s.prescribed_s)} s`
        : num(s.burst_s) ? `${Math.round(s.burst_s)} s (of ${Math.round(s.prescribed_s)})` : dash,
      watts(s.peak_w),
      num(s.s_to_peak) ? `${Math.round(s.s_to_peak)} s` : dash,
      watts(s.best_5s_w),
      watts(s.avg_w),
      num(s.drop_vs_best_pct) ? signed(-s.drop_vs_best_pct, 0) : dash,
      s.verdict || dash,
    ]),
    flag: iv.starts_flag || null,
    traces: starts
      .map((s) => ({ n: s.n, geometry: startTraceGeometry(s), verdict: s.verdict || '' }))
      .filter((t) => t.geometry),
  };
}

/** Everything the panel shows, or null when there is nothing analyzer-made to
 * show (no interval analysis and no pacing). `pacing` is
 * `state.pacingByWorkoutId[id]` (`{status, data, error}`) or undefined. */
export function buildRawAnalysis(workout, pacing) {
  const iv = workout?.analytics?.intervals || null;
  const execution = workout?.quality?.execution || null;
  const isRace = effectiveKind(workout) === 'race';
  const race = isRace ? raceView(pacing) : null;
  const powerCurve = powerCurveView(workout?.analytics?.power_curve);
  if (!iv && !race && !execution && !powerCurve) return null;
  return {
    summary: iv ? summaryRows(iv) : [],
    score: scoreView(execution, 'Execution score'),
    efforts: iv ? { columns: EFFORT_COLUMNS, rows: effortRows(iv) } : null,
    rounds: iv && (iv.rounds || []).length ? { columns: ROUND_COLUMNS, rows: roundRows(iv) } : null,
    starts: startsView(iv),
    powerCurve,
    race,
    racePending: isRace && pacing?.status === 'loading',
    raceError: isRace && pacing?.status === 'error' ? (pacing.error || 'Race analysis is not available.') : null,
  };
}

// --- Free ride -------------------------------------------------------------------

export const FREE_RIDE_EFFORT_COLUMNS = ['Window', 'At', 'Avg', '% FTP', 'HR', 'Climb', ''];
export const FREE_RIDE_MATCH_COLUMNS = ['At', 'Dur', 'Avg', 'Peak', 'kJ over FTP'];
const FREE_RIDE_TOP = 3;
const MIN_ZONE_SEGMENT_PCT = 0.5; // thinner slivers are not drawn (they stay in the legend)

function effortRow(e) {
  const climb = num(e.altitude_gain_m)
    ? `${signed(e.altitude_gain_m, 0, ' m')}${num(e.avg_grade_pct) ? ` at ${e.avg_grade_pct}%` : ''}`
    : dash;
  const best = e.new_best_90d ? ' (new 90-day best)' : e.new_best_42d ? ' (new 42-day best)' : '';
  return [
    `${Math.round(e.duration_s / 60)} min`,
    formatClock(e.start_offset_s),
    watts(e.avg_w),
    num(e.pct_ftp) ? `${Math.round(e.pct_ftp)}%` : dash,
    num(e.avg_hr) ? `${e.avg_hr}` : dash,
    climb,
    `${e.label || ''}${best}`.trim(),
  ];
}

function matchRow(m) {
  return [formatClock(m.start_offset_s), `${m.duration_s} s`, watts(m.avg_w), watts(m.peak_w), `${m.kj_above_ftp}`];
}

/** The "Free ride" section model (`analytics.free_ride`), or null when the ride has none.
 * `zoneBar` is the pedalling-time split (width % per zone, drawn as stacked CSS segments);
 * everything else is plain rows/strings for views.js. */
export function buildFreeRide(workout) {
  const fr = workout?.analytics?.free_ride;
  if (!fr) return null;
  const m = fr.matches;
  return {
    zoneBar: (fr.power_zones || []).filter((z) => z.seconds > 0).map((z) => ({
      zone: z.zone,
      pct: z.pct,
      color: ZONE_COLORS[z.zone],
      label: `${z.zone} ${ZONE_LABELS[z.zone]} ${Math.round(z.seconds / 60)} min (${Math.round(z.pct)}%)`,
      drawn: z.pct >= MIN_ZONE_SEGMENT_PCT,
    })),
    coasting: `Coasting ${Math.round(fr.coasting_pct)}% of moving time (not in the bar).`,
    creep: fr.tempo_creep_note || null,
    efforts: fr.notable_efforts?.length
      ? { columns: FREE_RIDE_EFFORT_COLUMNS, rows: fr.notable_efforts.map(effortRow) }
      : null,
    matches: m && m.count
      ? {
        summary: `${m.count} match${m.count === 1 ? '' : 'es'} burned: ${formatClock(m.time_above_ftp_s)} above FTP, ${m.kj_above_ftp} kJ over FTP.`,
        columns: FREE_RIDE_MATCH_COLUMNS,
        rows: m.efforts.slice(0, FREE_RIDE_TOP).map(matchRow),
      }
      : null,
    cost: fr.cost?.note || null,
    drift: (fr.steady_drift || []).map(
      (d) => `Steady ${Math.round(d.duration_min)} min from ${formatClock(d.start_offset_s)}: ${watts(d.avg_w)}, drift ${signed(d.drift_pct, 1)}.`,
    ),
    driftNote: fr.steady_drift?.length ? null : fr.steady_note || null,
    quality: fr.data_quality_notes || [],
  };
}

// --- MTB dynamics (Garmin Grit / Flow / jumps) and course sectors ------------------------------
// Device metrics: shown as recorded, no thresholds. Grit is course difficulty (compare laps on the
// same course); lower Flow is smoother.

export const MTB_LAP_COLUMNS = ['Lap', 'Time', 'Power', 'Grit', 'Flow', 'Jumps'];
export const SECTOR_LAP_COLUMNS = ['Lap', 'Time', 'vs best', 'Power', 'Flow'];
export const SECTOR_LOSS_COLUMNS = ['Sector', 'Best', 'Lost (total)', 'Lost / lap', 'Flow vs best', 'Grit'];

function jumpsLine(j) {
  if (!j) return null;
  const parts = [`${j.count} jump${j.count === 1 ? '' : 's'}`];
  if (num(j.max_height_m)) parts.push(`max height ${j.max_height_m} m`);
  if (num(j.max_hang_time_s)) parts.push(`max hang time ${j.max_hang_time_s} s`);
  if (num(j.best_score)) parts.push(`best score ${j.best_score}`);
  return parts.join(', ');
}

/** The "Mountain bike dynamics" section model (`analytics.mtb_dynamics`), or null when absent. */
export function buildMtbDynamics(workout) {
  const m = workout?.analytics?.mtb_dynamics;
  if (!m) return null;
  const summary = [];
  if (num(m.total_grit)) summary.push(`Total grit ${m.total_grit}`);
  if (num(m.avg_flow)) summary.push(`Avg flow ${m.avg_flow}`);
  const jumps = jumpsLine(m.jumps) || (num(m.jump_count) ? `${m.jump_count} jumps` : null);
  if (jumps) summary.push(jumps);
  const laps = m.laps || [];
  return {
    summary,
    note: 'Garmin device metrics: Grit is course difficulty (compare laps on the same course); lower Flow is smoother.',
    laps: laps.length
      ? {
        columns: MTB_LAP_COLUMNS,
        rows: laps.map((l) => [
          String(l.lap),
          formatClock(l.duration_s),
          watts(l.avg_power_w),
          num(l.grit) ? String(l.grit) : dash,
          num(l.avg_flow) ? String(l.avg_flow) : dash,
          num(l.jumps) ? String(l.jumps) : dash,
        ]),
      }
      : null,
  };
}

const MAP_WIDTH = 320;
const MAP_MAX_HEIGHT = 340;
const MAP_PAD = 18;

/** Tapping the selected sector again clears the highlight. */
export function nextSector(current, tapped) {
  return current === tapped ? null : tapped;
}

/** Loss tone per sector: the worst top-loss sector is `hot`, the other top-loss sectors `warm`,
 * everything else `neutral` (CSS maps the tones to colour tokens). */
function sectorTones(cs) {
  const tones = new Map();
  const bySector = new Map((cs.sectors || []).map((s) => [s.sector, s]));
  const ranked = (cs.top_loss_sectors || []).map((n) => bySector.get(n)).filter(Boolean)
    .sort((a, b) => b.total_loss_s - a.total_loss_s);
  ranked.forEach((s, i) => tones.set(s.sector, i === 0 ? 'hot' : 'warm'));
  return tones;
}

/** SVG-ready model of the best lap's outline (`course_sectors.track`: local metres, x east / y north):
 * north up, uniform scale, per-sector polyline + number label, start/finish marker, loss tone and
 * the highlight state. Null when the ride has no track. */
export function buildCourseMap(cs, selected = null) {
  const track = cs?.track?.sectors;
  if (!Array.isArray(track) || track.length === 0) return null;
  const pts = track.flatMap((t) => t.points);
  if (pts.length < 2) return null;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const minX = Math.min(...xs);
  const maxY = Math.max(...ys);
  const spanX = Math.max(Math.max(...xs) - minX, 1);
  const spanY = Math.max(maxY - Math.min(...ys), 1);
  const scale = Math.min((MAP_WIDTH - 2 * MAP_PAD) / spanX, (MAP_MAX_HEIGHT - 2 * MAP_PAD) / spanY);
  const X = (x) => Number((MAP_PAD + (x - minX) * scale).toFixed(1));
  const Y = (y) => Number((MAP_PAD + (maxY - y) * scale).toFixed(1)); // SVG y runs down; north is up
  const tones = sectorTones(cs);
  const bySector = new Map((cs.sectors || []).map((s) => [s.sector, s]));
  const hasSelection = selected !== null && selected !== undefined;
  return {
    width: MAP_WIDTH,
    height: Math.round(spanY * scale + 2 * MAP_PAD),
    start: { x: X(track[0].points[0][0]), y: Y(track[0].points[0][1]) },
    sectors: track.map((t) => {
      const loss = bySector.get(t.sector);
      return {
        sector: t.sector,
        points: t.points.map((p) => `${X(p[0])},${Y(p[1])}`).join(' '),
        label: { x: X(t.label[0]), y: Y(t.label[1]) },
        tone: tones.get(t.sector) || 'neutral',
        selected: hasSelection && t.sector === selected,
        dim: hasSelection && t.sector !== selected,
        aria: `Sector ${t.sector}${loss ? `, loses ${loss.total_loss_s.toFixed(1)} s in total` : ''}`,
      };
    }),
  };
}

/** The "Course sectors" section model (`analytics.course_sectors`), or null when absent.
 * `selected` is the highlighted sector number (map and table share it). */
export function buildCourseSectors(workout, selected = null) {
  const cs = workout?.analytics?.course_sectors;
  if (!cs) return null;
  const f = cs.fade || {};
  const trend = [`Time ${signed(f.time_change_pct)} first to last lap`];
  if (num(f.power_change_pct)) trend.push(`power ${signed(f.power_change_pct)}`);
  if (num(f.flow_change)) trend.push(`flow ${signed(f.flow_change, 2, '')}`);
  const bySector = new Map((cs.sectors || []).map((s) => [s.sector, s]));
  const top = (cs.top_loss_sectors || []).map((n) => bySector.get(n)).filter(Boolean);
  const picked = bySector.get(selected);
  return {
    trend: trend.join(', '),
    note: `Each lap is cut into ${cs.sector_count} equal-distance sectors; sector numbers line up across laps. Ask which course feature each sector is.`,
    map: buildCourseMap(cs, selected),
    selected: picked
      ? `Sector ${picked.sector}: best lap ${picked.best_time_s.toFixed(1)} s, loses ${picked.total_loss_s.toFixed(1)} s in total (${picked.mean_loss_s.toFixed(1)} s per lap).`
      : null,
    laps: {
      columns: SECTOR_LAP_COLUMNS,
      rows: (cs.laps || []).map((l) => [
        `${l.lap}${l.lap === cs.best_lap ? ' (best)' : ''}`,
        formatClock(l.time_s),
        l.time_vs_best_s ? signed(l.time_vs_best_s, 1, ' s') : dash,
        watts(l.avg_power_w),
        num(l.avg_flow) ? String(l.avg_flow) : dash,
      ]),
    },
    losses: top.length
      ? {
        columns: SECTOR_LOSS_COLUMNS,
        sectors: top.map((s) => s.sector),
        rows: top.map((s) => [
          String(s.sector),
          `${s.best_time_s.toFixed(1)} s`,
          `${s.total_loss_s.toFixed(1)} s`,
          `${s.mean_loss_s.toFixed(1)} s`,
          num(s.flow_vs_best) ? signed(s.flow_vs_best, 2, '') : dash,
          num(s.avg_grit) ? String(s.avg_grit) : dash,
        ]),
      }
      : null,
  };
}
