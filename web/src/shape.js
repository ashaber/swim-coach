// Pure geometry for the workout SHAPE chart: time on x, watts on y. The planned
// side expands a session's `structured` tree (nested repeats and all) into
// timed segments, resolves each zone target to watts from the athlete's FTP,
// and the completed side overlays the ride's actual power (or its laps).
//
// DOM-free, like plan.js's chart geometry: views.js only turns the returned
// numbers into SVG.
//
// Why JS and not an API field: the session tree is already on the client
// (plan JSON is cached for offline use), the walk is ~40 lines, and doing it
// here keeps the planned chart working offline with no extra round trip. The
// zone bounds below are a copy of engine/swim_coach/zones.py's bike table;
// tests/unit/test_shape_zone_table_matches_engine.py fails if they drift.
//
// The chart itself is a Coach-judgment presentation choice; it computes no
// physiology beyond the engine's own %FTP zone table.

import { findWorkoutForSession } from './history.js';

/** Coggan/Allen bike power zones as % of FTP (engine zones.py _BIKE_ZONE_BOUNDS). */
export const BIKE_ZONES = [
  { zone: 'Z1', loPct: 0, hiPct: 55 },
  { zone: 'Z2', loPct: 55, hiPct: 75 },
  { zone: 'Z3', loPct: 75, hiPct: 90 },
  { zone: 'Z4', loPct: 90, hiPct: 105 },
  { zone: 'Z5', loPct: 105, hiPct: 120 },
  { zone: 'Z6', loPct: 120, hiPct: 150 },
  { zone: 'Z7', loPct: 150, hiPct: null },
];

/** Z7 has no upper bound; drawn (and banded) up to this % of FTP. */
export const Z7_DISPLAY_HI_PCT = 200;

/** Cool -> hot, one hue per zone; shared by the planned bars and the actual line. */
export const ZONE_COLORS = {
  Z1: '#4f9fd9',
  Z2: '#35b7a6',
  Z3: '#a3cf4f',
  Z4: '#f2c94c',
  Z5: '#f49342',
  Z6: '#e5534b',
  Z7: '#d6407f',
};

export const ZONE_LABELS = {
  Z1: 'Recovery', Z2: 'Endurance', Z3: 'Tempo', Z4: 'Threshold', Z5: 'VO2max', Z6: 'Anaerobic', Z7: 'Neuromuscular',
};

/** A power_w target with only one bound gets +/-5% (engine prescription.py SINGLE_TARGET_BAND_FRAC). */
const SINGLE_TARGET_BAND_FRAC = 0.05;

/** Safety cap on expanded segments (a long EMOM or a 500-rep set). */
const MAX_SEGMENTS = 1500;

export function zoneForPctFtp(pct) {
  for (const z of BIKE_ZONES) {
    if (z.hiPct === null || pct <= z.hiPct) return z.zone;
  }
  return 'Z7';
}

export function zoneForWatts(watts, ftp) {
  if (!ftp || !Number.isFinite(watts)) return null;
  return zoneForPctFtp((watts / ftp) * 100);
}

/** Watts band of a zone for `ftp`. */
export function zoneBandWatts(zone, ftp) {
  const z = BIKE_ZONES.find((b) => b.zone === zone);
  if (!z || !ftp) return null;
  return { lo: (ftp * z.loPct) / 100, hi: (ftp * (z.hiPct ?? Z7_DISPLAY_HI_PCT)) / 100 };
}

/** A step target -> `{ lo, hi, zone }` in watts, or null when it has no power
 * meaning (RPE, CSS, open, or a zone with no FTP to resolve it). */
export function resolveTargetWatts(target, ftp) {
  if (!target) return null;
  if (target.basis === 'power_w') {
    let { low, high } = target;
    if (low == null && high == null) return null;
    if (low != null && high == null) { high = low * (1 + SINGLE_TARGET_BAND_FRAC); low *= (1 - SINGLE_TARGET_BAND_FRAC); }
    else if (high != null && low == null) { low = high * (1 - SINGLE_TARGET_BAND_FRAC); high *= (1 + SINGLE_TARGET_BAND_FRAC); }
    return { lo: low, hi: high, zone: target.zone || zoneForWatts((low + high) / 2, ftp) };
  }
  if (target.basis === 'zone' && target.zone) {
    const band = zoneBandWatts(target.zone, ftp);
    return band ? { ...band, zone: target.zone } : null;
  }
  return null;
}

/** Expands a `WorkoutStructure` into ordered, timed segments:
 * `{ start_s, dur_s, role, label, zone, lo, hi, startW, endW }`.
 * `startW`/`endW` are the drawn power at the segment's edges (equal for a
 * steady step, low->high for a ramp). Only time-based bike steps that resolve
 * to watts are returned -- distance/reps/open steps have no place on a time
 * axis, and are skipped without shifting the steps around them. */
export function expandStructure(structured, ftp) {
  const segments = [];
  const state = { t: 0 };

  function emitStep(step) {
    if (step.modality && step.modality !== 'bike') return;
    if (step.duration_kind !== 'time_s' || !step.duration_value) return;
    const dur = Number(step.duration_value);
    const band = resolveTargetWatts(step.target, ftp);
    if (band && segments.length < MAX_SEGMENTS) {
      const mid = (band.lo + band.hi) / 2;
      const ramp = step.role === 'ramp' && step.target.low != null && step.target.high != null;
      segments.push({
        start_s: state.t,
        dur_s: dur,
        role: step.role,
        label: step.label || '',
        zone: band.zone,
        lo: band.lo,
        hi: band.hi,
        startW: ramp ? step.target.low : mid,
        endW: ramp ? step.target.high : mid,
      });
    }
    state.t += dur;
  }

  function walk(items) {
    for (const item of items || []) {
      if (item.kind === 'repeat') walkRepeat(item);
      else emitStep(item);
    }
  }

  function walkRepeat(rep) {
    if (rep.repeat_mode === 'for_duration' && rep.duration_s && rep.interval_s) {
      const n = Math.floor(rep.duration_s / rep.interval_s);
      for (let i = 0; i < n && segments.length < MAX_SEGMENTS; i += 1) {
        const before = state.t;
        walk(rep.steps);
        state.t = before + rep.interval_s;
      }
      return;
    }
    if (rep.repeat_mode === 'amrap' && rep.duration_s) {
      const end = state.t + rep.duration_s;
      let guard = 0;
      while (state.t < end && guard < 200 && segments.length < MAX_SEGMENTS) {
        const before = state.t;
        walk(rep.steps);
        if (state.t === before) break;
        guard += 1;
      }
      return;
    }
    const count = rep.count || 1;
    for (let i = 0; i < count && segments.length < MAX_SEGMENTS; i += 1) walk(rep.steps);
  }

  walk(structured?.items);
  return { segments, total_s: state.t };
}

/** Completed-side series -> `[[t_s, watts]]`. Prefers the fetched power
 * profile; falls back to the workout's laps (one flat step per lap that has
 * average power). Returns [] when neither exists. */
export function actualPoints(powerProfile, laps) {
  if (Array.isArray(powerProfile) && powerProfile.length > 1) {
    return powerProfile.filter((p) => p && Number.isFinite(p[0]) && Number.isFinite(p[1]));
  }
  const pts = [];
  let cursor = 0;
  for (const lap of laps || []) {
    if (!Number.isFinite(lap.avg_power_w) || !Number.isFinite(lap.duration_s)) continue;
    const start = Number.isFinite(lap.start_offset_s) ? lap.start_offset_s : cursor;
    pts.push([start, lap.avg_power_w], [start + lap.duration_s, lap.avg_power_w]);
    cursor = start + lap.duration_s;
  }
  return pts;
}

/** The planned session a completed workout was matched to (the inverse of
 * history.js's findWorkoutForSession), or null. */
export function sessionForWorkout(workout, weeks) {
  if (!workout) return null;
  for (const week of weeks || []) {
    for (const session of week.sessions || []) {
      if (findWorkoutForSession(session, [workout]) === workout) return session;
    }
  }
  return null;
}

function niceCeil(v, step = 50) {
  return Math.max(step, Math.ceil(v / step) * step);
}

function niceTimeStep(totalS) {
  const steps = [60, 120, 300, 600, 900, 1200, 1800, 3600];
  return steps.find((s) => totalS / s <= 6) || 3600;
}

export const SHAPE_WIDTH = 360;
export const SHAPE_HEIGHT = 220;
export const SHAPE_PADDING = { top: 10, right: 10, bottom: 26, left: 38 };

/** Everything the SVG needs: planned bars/bands, actual runs, ticks, legend.
 * Returns `{ isEmpty: true, reason }` when there is nothing plottable. */
export function shapeChartGeometry({ segments = [], total_s: plannedTotal = 0, actual = [], ftp,
  width = SHAPE_WIDTH, height = SHAPE_HEIGHT, padding = SHAPE_PADDING } = {}) {
  if (!ftp) return { isEmpty: true, reason: 'ftp' };
  if (segments.length === 0 && actual.length === 0) return { isEmpty: true, reason: 'nothing' };

  const actualEnd = actual.length ? actual[actual.length - 1][0] : 0;
  const totalS = Math.max(plannedTotal, actualEnd, 1);
  const plannedMax = segments.reduce((m, s) => Math.max(m, s.hi, s.startW, s.endW), 0);
  const actualMax = actual.reduce((m, p) => Math.max(m, p[1]), 0);
  const yMax = niceCeil(Math.max(plannedMax, actualMax, ftp) * 1.05);

  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;
  const xFor = (t) => padding.left + (t / totalS) * plotW;
  const yFor = (w) => padding.top + (1 - Math.min(w, yMax) / yMax) * plotH;
  const baseline = yFor(0);

  const zonesUsed = new Set();
  const bars = segments.map((s) => {
    zonesUsed.add(s.zone);
    const x0 = xFor(s.start_s);
    const x1 = xFor(s.start_s + s.dur_s);
    return {
      x: x0,
      w: Math.max(x1 - x0, 0.5),
      zone: s.zone,
      color: ZONE_COLORS[s.zone],
      role: s.role,
      label: s.label,
      // Filled body: trapezoid to the drawn level(s); a steady step is a rectangle.
      points: `${x0},${baseline} ${x0},${yFor(s.startW)} ${x1},${yFor(s.endW)} ${x1},${baseline}`,
      bandTop: yFor(s.hi),
      bandBottom: yFor(s.lo),
      lo: Math.round(s.lo),
      hi: Math.round(s.hi),
    };
  });

  // Actual power as runs of consecutive same-zone points, each run sharing its
  // first point with the previous run's last so the line has no gaps.
  const runs = [];
  let prev = null;
  for (const [t, w] of actual) {
    const zone = zoneForWatts(w, ftp);
    zonesUsed.add(zone);
    const pt = { x: xFor(t), y: yFor(w) };
    if (!runs.length || runs[runs.length - 1].zone !== zone) {
      runs.push({ zone, color: ZONE_COLORS[zone], pts: prev ? [prev, pt] : [pt] });
    } else {
      runs[runs.length - 1].pts.push(pt);
    }
    prev = pt;
  }
  const actualRuns = runs.map((r) => ({
    zone: r.zone,
    color: r.color,
    points: r.pts.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' '),
  }));

  const tStep = niceTimeStep(totalS);
  const xTicks = [];
  for (let t = 0; t <= totalS; t += tStep) xTicks.push({ x: xFor(t), label: `${Math.round(t / 60)}m` });

  const yStep = yMax > 400 ? 100 : 50;
  const yTicks = [];
  for (let w = 0; w <= yMax; w += yStep) yTicks.push({ y: yFor(w), label: `${w}` });

  const legend = BIKE_ZONES.map((z) => z.zone)
    .filter((z) => zonesUsed.has(z))
    .map((z) => ({
      zone: z,
      color: ZONE_COLORS[z],
      name: ZONE_LABELS[z],
      range: zoneRangeLabel(z, ftp),
    }));

  return {
    isEmpty: false,
    width,
    height,
    plotLeft: padding.left,
    plotRight: width - padding.right,
    baseline,
    ftpY: yFor(ftp),
    bars,
    actualRuns,
    hasActual: actual.length > 0,
    hasPlan: segments.length > 0,
    xTicks,
    yTicks,
    legend,
    totalS,
  };
}

function zoneRangeLabel(zone, ftp) {
  const z = BIKE_ZONES.find((b) => b.zone === zone);
  const lo = Math.round((ftp * z.loPct) / 100);
  if (z.hiPct === null) return `${lo}+ W`;
  return `${lo}-${Math.round((ftp * z.hiPct) / 100)} W`;
}
