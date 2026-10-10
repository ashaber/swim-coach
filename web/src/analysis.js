// Pure model for the "Raw analysis" panel on the workout detail view: the full
// deterministic analyzer output, laid out like docs/analyzer-baseline-*.md
// (a summary, the efforts/reps table with its target band, the round table,
// the execution-score breakdown, and race pacing for a ride that has it).
//
// Read-only and derived entirely from the cached workout (plus the lazily
// fetched pacing result when it has arrived), so it renders offline. DOM-free:
// views.js turns the returned rows into markup.

import { formatClock } from './workouts.js';

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

/** Everything the panel shows, or null when there is nothing analyzer-made to
 * show (no interval analysis and no pacing). `pacing` is
 * `state.pacingByWorkoutId[id]` (`{status, data, error}`) or undefined. */
export function buildRawAnalysis(workout, pacing) {
  const iv = workout?.analytics?.intervals || null;
  const execution = workout?.quality?.execution || null;
  const race = raceView(pacing);
  if (!iv && !race && !execution) return null;
  return {
    summary: iv ? summaryRows(iv) : [],
    score: scoreView(execution, 'Execution score'),
    efforts: iv ? { columns: EFFORT_COLUMNS, rows: effortRows(iv) } : null,
    rounds: iv && (iv.rounds || []).length ? { columns: ROUND_COLUMNS, rows: roundRows(iv) } : null,
    race,
    racePending: pacing?.status === 'loading',
    raceError: pacing?.status === 'error' ? (pacing.error || 'Race analysis is not available.') : null,
  };
}
