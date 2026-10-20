// View models for the race view (the redesigned race detail) and its section drill-down. DOM-free:
// raceViewRender.js turns the models into markup. Every block is built only from data that is
// present, so a race analysed before a field existed simply shows fewer cards. Numbers come from the
// analytics (the engine owns them); this file only selects, orders, formats and buckets them.

import { formatClock, formatWorkoutDistance } from './workouts.js';
import { viewBoxAttr } from './mapView.js';
import { buildCourseMap, canonicalLapLabel, effectiveKind } from './analysis.js';
import {
  EFF_CLASSES, EFF_COLOURS, FLOW_CUTS, HEAT, MAP_METRICS, NEUTRAL, POWER_CUTS, SPLIT_MIN_M, SPLIT_PARTS,
  TIME_LOST_CUTS, TIER_COLOURS, bucketOf,
} from './raceHeat.js';

const num = (v) => v !== null && v !== undefined && Number.isFinite(v);
const dash = '—';
const MINUS = '−';
const round = (v) => Math.round(v);

/** m:ss.t, for ideal-lap style times. */
export function clockTenths(seconds) {
  if (!num(seconds)) return dash;
  const tenths = Math.round(seconds * 10);
  const m = Math.floor(tenths / 600);
  const s = (tenths % 600) / 10;
  return `${m}:${s.toFixed(1).padStart(4, '0')}`;
}

/** "Sat" / "Saturday" for an ISO date; empty when it does not parse. */
export function weekdayName(date, long = false) {
  const d = new Date(`${String(date || '').slice(0, 10)}T12:00:00`);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString('en-US', { weekday: long ? 'long' : 'short' });
}

const signedFixed = (v, digits, unit) => `${v < 0 ? MINUS : '+'}${Math.abs(v).toFixed(digits)}${unit}`;

// --- Gate ---------------------------------------------------------------------

/** The sectioned course data of a race, or null when this ride gets the ordinary detail view. */
export function raceCourse(workout) {
  if (effectiveKind(workout) !== 'race') return null;
  const cs = workout?.analytics?.course_sectors;
  return Array.isArray(cs?.sectors) && cs.sectors.length > 0 ? cs : null;
}

export const hasRaceView = (workout) => raceCourse(workout) !== null;

// --- Summary card -----------------------------------------------------------------

const pick = (...values) => values.find(num) ?? null;
const unitValue = (v, unit, digits = 0) => (num(v) ? { value: v.toFixed(digits), unit } : null);

export function buildRaceSummary(workout) {
  const an = workout.analytics || {};
  const ov = an.race_overview || {};
  const oneSecond = (an.power_curve || []).find((p) => p.duration_s === 1);
  const duration = pick(ov.duration_s, num(workout.duration_min) ? workout.duration_min * 60 : null);
  const laps = an.laps || [];
  const fullLaps = laps.filter((l) => !l.start_lap).length;
  const startLaps = laps.filter((l) => l.start_lap).length;
  const cell = (label, v, extra = {}) => ({ label, value: v ? v.value : dash, unit: v ? v.unit : '', ...extra });
  const headline = [
    cell('race time', num(duration) ? { value: formatClock(duration), unit: '' } : null),
    cell('NP', unitValue(pick(ov.np_w, an.normalized_power_w), 'W')),
    cell('max power', unitValue(pick(ov.max_power_w, oneSecond?.watts), 'W'), { emphasis: true }),
    cell('avg HR', unitValue(pick(ov.avg_hr, workout.avg_hr), '')),
  ];
  const dist = pick(ov.distance_m, workout.distance_m);
  const more = [
    ['max HR', unitValue(pick(ov.max_hr, workout.max_hr), '')],
    ['avg power', unitValue(pick(ov.avg_power_w, an.avg_power_w), 'W')],
    ['work', unitValue(ov.work_kj, 'kJ')],
    ['avg km/h', unitValue(ov.avg_speed_kmh, '', 1)],
    ['max km/h', unitValue(ov.max_speed_kmh, '', 1)],
    ['distance', num(dist) ? { value: formatWorkoutDistance(dist), unit: '' } : null],
    ['start + laps', laps.length ? { value: `${startLaps} + ${fullLaps}`, unit: '' } : null],
    ['avg cadence', unitValue(ov.avg_cadence_rpm, 'rpm')],
    ['total grit', unitValue(pick(ov.total_grit, an.mtb_dynamics?.total_grit), '', 1)],
  ].filter(([, v]) => v).map(([label, v]) => ({ label, value: v.value, unit: v.unit }));
  return { headline, more };
}

// --- Power charts (start, finish sprint) ---------------------------------------------

/** Chart frame shared by the start and finish charts (SVG user units). */
export const CHART = { w: 320, h: 100, left: 10, right: 310, base: 90, span: 75 };

const chartX = (i, n) => CHART.left + (i * (CHART.right - CHART.left)) / Math.max(n - 1, 1);
const chartY = (v, ymax) => CHART.base - (Math.max(v, 0) / ymax) * CHART.span;
const chartPoints = (values, ymax) => values
  .map((v, i) => `${chartX(i, values.length).toFixed(1)},${chartY(v, ymax).toFixed(1)}`).join(' ');

/** Which sample the pointer is over, 0..n-1. `rect` is the chart wrapper's client rect. */
export function probeIndex(clientX, rect, n) {
  if (n < 2 || !rect.width) return 0;
  const x = ((clientX - rect.left) / rect.width) * CHART.w;
  const i = Math.round(((x - CHART.left) / (CHART.right - CHART.left)) * (n - 1));
  return Math.max(0, Math.min(n - 1, i));
}

/** Left offset of the probe marker, as a percentage of the chart width. */
export const probeLeftPct = (i, n) => Number(((chartX(i, n) / CHART.w) * 100).toFixed(2));

const finite = (arr) => (Array.isArray(arr) ? arr.filter(num) : []);

/** The readout under a probed chart. `series.kind` picks the layout. */
export function probeReadout(series, i) {
  const w = series.w?.[i];
  const v = series.v?.[i];
  const speed = num(v) ? `, ${round(v)} km/h` : '';
  if (series.kind === 'finish') {
    return `${series.w.length - 1 - i} s to the line · ${num(w) ? round(w) : dash} W${speed}`;
  }
  const prev = num(series.p?.[i]) ? ` · ${series.prev} ${round(series.p[i])} W` : '';
  return `${i} s · ${series.cur} ${num(w) ? round(w) : dash} W${speed}${prev}`;
}

function prevRace(previous) {
  if (!previous) return null;
  return { name: weekdayName(previous.date, true), short: weekdayName(previous.date, false) };
}

export function buildStartCard(workout) {
  const st = workout?.analytics?.race_start;
  const power = Array.isArray(st?.power_w) ? st.power_w : [];
  if (power.length < 2) return null;
  const prev = st.previous && finite(st.previous.power_w).length >= 2 ? st.previous : null;
  const prevName = prev ? prevRace(prev) : null;
  const ymax = Math.max(1, ...finite(power), ...finite(prev?.power_w));
  const vs = (v, unit) => (prev && num(v) ? ` (${prevName.short || 'prev'} ${round(v)}${unit})` : '');
  const tiles = [
    num(st.peak_w) && { value: String(round(st.peak_w)), unit: 'W', label: `peak${num(st.peak_at_s) ? `, ${round(st.peak_at_s)} s in` : ''}` },
    num(st.mean_15s_w) && { value: String(round(st.mean_15s_w)), unit: 'W', label: `first 15 s${vs(prev?.mean_15s_w, '')}` },
    num(st.top_speed_kmh) && {
      value: String(round(st.top_speed_kmh)), unit: 'km/h',
      label: `top${num(st.top_speed_at_s) ? `, at ${round(st.top_speed_at_s)} s` : ''}${vs(prev?.top_speed_kmh, '')}`,
    },
  ].filter(Boolean);
  const dip = st.dip && num(st.dip.at_s) && num(st.dip.power_w) ? st.dip : null;
  const half = Math.max(50, Math.round(ymax / 2 / 50) * 50);
  let callout = null;
  if (dip) {
    callout = { strong: `${round(dip.power_w)} W at ${round(dip.at_s)} s`, tail: '' };
    if (prev && num(prev.mean_15s_w)) callout.tail = ` ${prevName.name || 'The previous race'} held about ${round(prev.mean_15s_w)} W through 15 s.`;
  }
  const cur = weekdayName(workout.date, false) || 'This race';
  return {
    subtitle: `first ${power.length} s${prev ? ` · vs ${prevName.name || 'previous race'}` : ''}`,
    tiles,
    points: chartPoints(power, ymax),
    ghost: prev ? chartPoints(prev.power_w, ymax) : null,
    dip: dip ? { x: Number(chartX(round(dip.at_s), power.length).toFixed(1)), y: Number(chartY(dip.power_w, ymax).toFixed(1)) } : null,
    grid: { y: Number(chartY(half, ymax).toFixed(1)), label: `${half} W` },
    endLabel: `${power.length} s`,
    callout,
    cur,
    prev: prev ? (prevName.short || 'Prev') : null,
    aria: `Power over the first ${power.length} seconds${dip ? `, dipping to ${round(dip.power_w)} watts at ${round(dip.at_s)} seconds` : ''}`,
    series: { kind: 'start', w: power, v: st.speed_kmh || [], p: prev ? prev.power_w : [], cur, prev: prev ? (prevName.short || 'Prev') : '' },
  };
}

export function buildFinishSprint(workout) {
  const fs = workout?.analytics?.finish_sprint;
  const power = Array.isArray(fs?.power_w) ? fs.power_w : [];
  if (!fs || power.length < 2) return null;
  const ymax = Math.max(1, ...finite(power));
  const tiles = [
    num(fs.avg_w) && { value: String(round(fs.avg_w)), unit: 'W', label: num(fs.duration_s) ? `${round(fs.duration_s)} s average` : 'average' },
    num(fs.peak_w) && { value: String(round(fs.peak_w)), unit: 'W', label: 'peak' },
    num(fs.entry_speed_kmh) && num(fs.exit_speed_kmh) && { value: `${round(fs.entry_speed_kmh)}→${round(fs.exit_speed_kmh)}`, unit: '', label: 'km/h to the line' },
  ].filter(Boolean);
  const half = Math.max(50, Math.round(ymax / 2 / 50) * 50);
  return {
    tiles,
    points: chartPoints(power, ymax),
    grid: { y: Number(chartY(half, ymax).toFixed(1)), label: `${half} W` },
    aria: `Sprint power: peaking at ${num(fs.peak_w) ? round(fs.peak_w) : round(ymax)} watts`,
    series: { kind: 'finish', w: power, v: fs.speed_kmh || [] },
  };
}

// --- Section analysis ---------------------------------------------------------------

const cap = (text) => (text ? text[0].toUpperCase() + text.slice(1) : '');

/** "Corners · 307 m", with the terrain when it is not flat. */
export function sectionMeta(s) {
  const kind = cap(s.kind || 'section');
  const terrain = s.terrain && s.terrain !== 'flat' ? ` · ${s.terrain}` : '';
  return `${kind} · ${num(s.length_m) ? round(s.length_m) : dash} m${terrain}`;
}

/** The map metrics this race can show: efficiency only when some section has an extra-watts figure. */
export function availableMetrics(cs) {
  const metrics = ['loss', 'spread'];
  if ((cs.sectors || []).some((s) => s.efficiency_applies !== false && num(s.mean_extra_w))) metrics.push('eff');
  return metrics;
}

const METRIC_LABELS = { loss: 'Time lost / lap', spread: 'Consistency', eff: 'Efficiency' };
const METRIC_NAMES = { loss: 'time lost per lap', spread: 'lap-to-lap spread', eff: 'extra watts for the same speed' };
const METRIC_FORMAT = {
  loss: (v) => `+${v.toFixed(2)} s`,
  spread: (v) => `${v.toFixed(1)} s`,
  eff: (v) => `+${round(v)} W`,
};

/** The metric's value for one section; null when it does not apply (a power section for efficiency). */
export function metricValue(s, metric) {
  if (metric === 'loss') return num(s.mean_loss_s) ? s.mean_loss_s : null;
  if (metric === 'spread') return num(s.spread_s) ? s.spread_s : null;
  if (s.efficiency_applies === false) return null;
  return num(s.mean_extra_w) ? s.mean_extra_w : null;
}

const tierColour = (value, metric) => (value === null ? NEUTRAL : TIER_COLOURS[bucketOf(value, MAP_METRICS[metric].cuts)]);

function legendFor(metric, hasNoiseFlags = false) {
  const [a, b, c] = MAP_METRICS[metric].cuts;
  const labels = {
    loss: [`< ${a} s`, `${a}–${b} s`, `${b}–${c} s`, `> ${c} s lost / lap`],
    spread: [`< ${a} s`, `${a}–${b} s`, `${b}–${c} s`, `> ${c} s spread`],
    eff: [`< ${a} W extra`, `${a}–${b} W`, `${b}–${c} W`, `${c} W+`],
  }[metric];
  const items = labels.map((label, i) => ({ label, colour: TIER_COLOURS[i] }));
  if (metric === 'eff') items.push({ label: 'power section', colour: NEUTRAL });
  if (metric === 'loss' && hasNoiseFlags) items.push({ label: 'within timing noise', colour: NEUTRAL });
  return items;
}

/** Per-section rows (course order) for the chosen metric: the list and the map share them. */
export function buildSectionRows(cs, metric) {
  const values = cs.sectors.map((s) => metricValue(s, metric));
  const max = Math.max(...values.filter(num), 0) || 1;
  return cs.sectors.map((s, k) => {
    const v = values[k];
    const noise = metric === 'loss' && isWithinNoise(s);
    let text = v === null ? (metric === 'eff' ? 'power' : dash) : METRIC_FORMAT[metric](v);
    if (noise) text = 'within noise';
    return {
      sector: s.sector,
      label: s.label,
      meta: sectionMeta(s),
      noise,
      colour: noise ? NEUTRAL : tierColour(v, metric),
      text,
      widthPct: v === null ? 4 : Math.max(4, round((v / max) * 100)),
    };
  });
}

/** A section whose time loss the engine could not separate from timing noise. Absent flag = significant. */
const isWithinNoise = (s) => s.loss_significant === false;

const lapOrder = (a, b) => a - b;

function slowestLaps(passes) {
  const list = (passes || []).filter((p) => num(p.time_s) && num(p.lap));
  if (list.length < 4) return null;
  return list.slice().sort((a, b) => b.time_s - a.time_s).slice(0, 2).map((p) => p.lap).sort(lapOrder);
}

const lapLength = (cs) => cs.sectors.reduce((sum, s) => sum + (num(s.length_m) ? s.length_m : 0), 0);
const isLong = (s) => num(s.length_m) && s.length_m >= SPLIT_MIN_M && !s.split_of;

/** The ideal-lap gap that survives the timing-noise floor, as a sentence; null when the engine did not say. */
function idealBeyondNoise(cs) {
  const beyond = cs.ideal_gap_beyond_noise_s;
  if (!num(beyond)) return null;
  if (beyond < 0.5) return 'Laps were within timing noise of each other.';
  return `About ${beyond.toFixed(beyond < 10 ? 1 : 0)} s of that is beyond timing noise.`;
}

function noiseNote(cs) {
  const edge = num(cs.edge_noise_s) ? ` (±${cs.edge_noise_s.toFixed(1)} s)` : '';
  return `No section stands out beyond timing noise${edge}.`;
}

export function buildSectionAnalysis(workout, metric) {
  const cs = raceCourse(workout);
  if (!cs) return null;
  const metrics = availableMetrics(cs);
  const active = metrics.includes(metric) ? metric : 'loss';
  const rows = buildSectionRows(cs, active);
  const byLabel = new Map(rows.map((r) => [r.label, r]));
  const total = lapLength(cs);
  const laps = (workout.analytics.laps || []).filter((l) => l.comparable && num(l.duration_s));
  const bestReal = laps.length ? Math.min(...laps.map((l) => l.duration_s)) : null;
  const ideal = num(cs.ideal_lap_s) ? cs.ideal_lap_s : null;
  const bySector = new Map(cs.sectors.map((s) => [s.sector, s]));
  const losses = (cs.top_loss_sectors || []).map((n) => bySector.get(n)).filter((s) => s && !isWithinNoise(s)).slice(0, 3).map((s) => {
    const worst = slowestLaps(s.passes);
    const parts = [];
    if (num(s.spread_s)) parts.push(`${s.spread_s.toFixed(1)} s spread lap to lap`);
    if (worst) parts.push(`laps ${worst.join(' & ')} slowest`);
    if (isLong(s) && total > 0) parts.push(`${round((s.length_m / total) * 100)}% of the lap in one section`);
    return {
      label: s.label,
      title: `${sectionMeta(s)}${isLong(s) ? ' (long, could split)' : ''}`,
      sub: parts.join('. '),
      value: num(s.mean_loss_s) ? `+${s.mean_loss_s.toFixed(1)} s/lap` : dash,
      colour: tierColour(num(s.mean_loss_s) ? s.mean_loss_s : null, 'loss'),
    };
  });
  return {
    metrics: metrics.map((key) => ({ key, label: METRIC_LABELS[key], on: key === active })),
    metric: active,
    metricName: METRIC_NAMES[active],
    effNote: active === 'eff' ? 'Watts spent beyond your cheapest pass that was at least as fast. Grey = power sections, where watts buy speed.' : null,
    ideal: ideal === null ? null : {
      beyondNoise: idealBeyondNoise(cs),
      ideal: clockTenths(ideal),
      bestLap: bestReal === null ? null : formatClock(bestReal),
      onTable: bestReal === null ? null : `${Math.max(bestReal - ideal, 0).toFixed(1)} s`,
    },
    legend: legendFor(active, cs.sectors.some((s) => s.loss_significant === false)),
    map: buildRaceMap(cs, byLabel),
    losses,
    noNotable: losses.length === 0 ? noiseNote(cs) : null,
    rows,
  };
}

/** The coloured course map: geometry from the existing sector map, colours from `rowsByLabel`.
 * `highlight` (a section label) dims every other section. */
export function buildRaceMap(cs, rowsByLabel, highlight = null, highlightColour = HEAT[3]) {
  const base = buildCourseMap(cs);
  if (!base) return null;
  return {
    width: base.width,
    height: base.height,
    viewBox: `0 0 ${base.width} ${base.height}`,
    start: base.start,
    sectors: base.sectors.map((s) => {
      const row = rowsByLabel.get(s.name);
      const picked = highlight === s.name;
      return {
        label: s.name,
        points: s.points,
        at: s.label,
        colour: highlight ? (picked ? highlightColour : NEUTRAL) : (row ? row.colour : NEUTRAL),
        dim: Boolean(highlight) && !picked,
        aria: `Section ${s.name}${row ? `, ${row.text}` : ''}`,
      };
    }),
  };
}

// --- Free speed ----------------------------------------------------------------------

const SAME_TIME_S = 0.05;

export function buildFreeSpeed(workout) {
  const list = workout?.analytics?.course_sectors?.free_speed;
  if (!Array.isArray(list) || !list.length) return null;
  return list.map((f) => {
    const gain = num(f.vs_time_s) && num(f.time_s) ? f.vs_time_s - f.time_s : null;
    let what = 'fewer watts';
    if (gain !== null) what = gain >= SAME_TIME_S ? 'faster for fewer watts' : gain > -SAME_TIME_S ? 'same time, far less power' : 'near-best time, less power';
    const vs = num(f.vs_lap) ? `. Lap ${f.vs_lap}: ${num(f.vs_time_s) ? `${f.vs_time_s.toFixed(1)} s` : dash} at ${num(f.vs_power_w) ? round(f.vs_power_w) : dash} W` : '';
    return {
      label: f.label,
      title: `Lap ${f.lap}: ${what}`,
      sub: `${num(f.time_s) ? f.time_s.toFixed(1) : dash} s at ${num(f.power_w) ? round(f.power_w) : dash} W${vs}`,
      value: num(f.watts_saved) ? `${MINUS}${round(f.watts_saved)} W` : dash,
    };
  });
}

// --- Laps and fade ---------------------------------------------------------------------

function lapList(workout) {
  const an = workout.analytics || {};
  const eff = new Map((an.race_efficiency?.laps || []).map((l) => [l.lap, l]));
  const source = (an.laps || []).length
    ? an.laps.map((l) => ({ n: l.n, start: Boolean(l.start_lap), comparable: Boolean(l.comparable), time: l.duration_s, hr: l.avg_hr, label: canonicalLapLabel(l) }))
    : (an.race_efficiency?.laps || []).map((l) => ({ n: l.lap, start: Boolean(l.start_lap), comparable: !l.start_lap, time: l.time_s, hr: l.avg_hr, label: String(l.lap) }));
  return source.map((l) => {
    const e = eff.get(l.n) || {};
    return { ...l, np: e.np_w, ef: e.ef, hr: pick(e.avg_hr, l.hr) };
  });
}

export function buildLapsCard(workout) {
  const laps = lapList(workout);
  if (!laps.length) return null;
  const comparable = laps.filter((l) => l.comparable && num(l.time));
  const best = comparable.length ? Math.min(...comparable.map((l) => l.time)) : null;
  const maxDelta = comparable.length ? Math.max(...comparable.map((l) => l.time - best)) : 0;
  const rows = laps.filter((l) => !l.start).map((l) => {
    const delta = l.comparable && best !== null && num(l.time) ? l.time - best : null;
    return {
      n: l.n,
      label: l.label,
      time: formatClock(l.time) || dash,
      best: delta !== null && delta < 0.5,
      delta: delta === null ? dash : delta < 0.5 ? 'best' : `+${round(delta)} s`,
      barPct: delta === null ? 0 : delta < 0.5 || maxDelta <= 0 ? 4 : Math.max(8, round((delta / maxDelta) * 100)),
      np: num(l.np) ? String(round(l.np)) : dash,
      hr: num(l.hr) ? String(round(l.hr)) : dash,
      ef: num(l.ef) ? l.ef.toFixed(2) : dash,
    };
  });
  const start = laps.find((l) => l.start);
  return {
    rows,
    startNote: start
      ? `Start lap: ${formatClock(start.time) || dash}${num(start.np) ? ` at ${round(start.np)} W NP` : ''}. Shown, but never compared with the full laps.`
      : null,
  };
}

export function buildFadeCard(workout) {
  const re = workout?.analytics?.race_efficiency;
  if (!re || !re.verdict) return null;
  const t = re.trend || {};
  const verdict = String(re.verdict);
  const cut = verdict.indexOf(':');
  const pill = cut > 0 ? verdict.slice(0, cut) : verdict;
  const detail = cut > 0 ? verdict.slice(cut + 1).trim() : '';
  const facts = [];
  if (num(t.time_change_pct)) facts.push(`lap times ${signedFixed(t.time_change_pct, 1, '%')}`);
  if (num(t.hr_change_bpm)) facts.push(`HR ${signedFixed(t.hr_change_bpm, 0, ' bpm')}`);
  if (num(t.power_change_pct)) facts.push(`power ${signedFixed(t.power_change_pct, 0, '%')}`);
  if (num(t.ef_change_pct)) facts.push(`efficiency ${signedFixed(t.ef_change_pct, 0, '%')}`);
  const laps = (re.laps || []).filter((l) => !l.start_lap && num(l.np_w) && num(l.avg_hr));
  const chart = laps.length >= 2 ? fadeChart(laps) : null;
  return {
    pill,
    drifted: (num(t.ef_change_pct) && t.ef_change_pct <= -5) || (num(t.decoupling_pct) && t.decoupling_pct <= -5),
    text: facts.length ? `First to last lap: ${facts.join(', ')}.` : detail,
    chart,
  };
}

function fadeChart(laps) {
  const w = 320;
  const scale = (values, lo, hi) => values.map((v, i) => {
    const x = 10 + (i * 300) / (values.length - 1);
    const y = hi === lo ? 40 : 66 - ((v - lo) / (hi - lo)) * 54;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const np = laps.map((l) => l.np_w);
  const hr = laps.map((l) => l.avg_hr);
  const first = laps[0];
  const last = laps[laps.length - 1];
  return {
    width: w,
    np: scale(np, Math.min(...np), Math.max(...np)),
    hr: scale(hr, Math.min(...hr), Math.max(...hr)),
    firstLabel: `L${first.lap}`,
    lastLabel: `L${last.lap}`,
    hrLegend: `HR ${round(first.avg_hr)} → ${round(last.avg_hr)}`,
    npLegend: `NP ${round(first.np_w)} → ${round(last.np_w)} W`,
    aria: `Heart rate ${round(first.avg_hr)} to ${round(last.avg_hr)} beats per minute and normalized power ${round(first.np_w)} to ${round(last.np_w)} watts across laps ${first.lap} to ${last.lap}`,
  };
}

// --- Split controls ------------------------------------------------------------------

/** One control per long section (offer a split) and per split section (offer to undo). */
export function buildSplitControls(workout) {
  const cs = raceCourse(workout);
  if (!cs) return [];
  const total = lapLength(cs);
  const controls = [];
  const seen = new Set();
  cs.sectors.forEach((s) => {
    if (s.split_of) {
      if (seen.has(s.split_of)) return;
      seen.add(s.split_of);
      const parts = num(cs.splits?.[s.split_of]) ? cs.splits[s.split_of] : cs.sectors.filter((x) => x.split_of === s.split_of).length;
      controls.push({ label: s.split_of, split: true, hint: `${s.split_of} is split into ${parts} parts.`, button: `Unsplit ${s.split_of}` });
    } else if (isLong(s)) {
      const share = total > 0 ? ` (${round((s.length_m / total) * 100)}% of the lap)` : '';
      controls.push({
        label: s.label,
        split: false,
        hint: `${s.label} is ${round(s.length_m)} m${share}. Split it to see which part costs time.`,
        button: `Split ${s.label} in ${SPLIT_PARTS}`,
      });
    }
  });
  return controls;
}

/** The splits map to send after toggling `label`: the current splits with it added or removed. */
export function nextSplits(current, label, split) {
  const next = { ...(current || {}) };
  if (split) delete next[label];
  else next[label] = SPLIT_PARTS;
  return next;
}

// --- Whole race view --------------------------------------------------------------------

export function buildRaceView(workout, { metric = 'loss' } = {}) {
  if (!hasRaceView(workout)) return null;
  return {
    summary: buildRaceSummary(workout),
    start: buildStartCard(workout),
    analysis: buildSectionAnalysis(workout, metric),
    freeSpeed: buildFreeSpeed(workout),
    laps: buildLapsCard(workout),
    fade: buildFadeCard(workout),
    sprint: buildFinishSprint(workout),
    splits: buildSplitControls(workout),
  };
}

// --- Section drill-down ---------------------------------------------------------------------

export const DRILL_MODES = [
  { key: 'loss', label: 'Time lost' },
  { key: 'eff', label: 'Efficiency' },
  { key: 'power', label: 'Power' },
  { key: 'flow', label: 'Flow' },
];

const DRILL_LEGENDS = {
  loss: ['best (< 0.1 s)', '0.1–0.25 s', '0.25–0.5 s', '0.5–1 s', '> 1 s lost'],
  power: ['< 100 W', '100–200', '200–300', '300–450', '450 W+'],
  flow: ['straight (0)', '< 3', '3–6', '6–10', '10+ (tight turn)'],
  eff: ['faster, fewer W', 'faster, more W', 'par', 'slower, fewer W', 'slower, more W'],
};
const DRILL_COLOURS = {
  loss: [...HEAT, NEUTRAL], power: HEAT, flow: HEAT, eff: EFF_CLASSES.map((c) => EFF_COLOURS[c]),
};

const NOISE_BUCKET = 5;
const MIN_SPAN_M = 30;
const FRAME = { w: 360, h: 310, pad: 20 };

/** Section frame: relative metres to SVG user units, fitted to the section's bbox, north up. */
export function sectionFrame(bbox) {
  const [x0, y0, x1, y1] = bbox;
  const bw = Math.max(x1 - x0, MIN_SPAN_M);
  const bh = Math.max(y1 - y0, MIN_SPAN_M);
  const s = Math.min((FRAME.w - 2 * FRAME.pad) / bw, (FRAME.h - 2 * FRAME.pad) / bh);
  const ox = (FRAME.w - (x1 - x0) * s) / 2;
  const oy = (FRAME.h - (y1 - y0) * s) / 2;
  const f = (n) => Number(n.toFixed(1));
  return {
    width: FRAME.w,
    height: FRAME.h,
    x: (x) => f(ox + (x - x0) * s),
    y: (y) => f(oy + (y1 - y) * s),
  };
}

const pathOf = (pts) => pts.map((p, i) => `${i ? 'L' : 'M'}${p[0]} ${p[1]}`).join(' ');

/** Five path strings (one per bucket) for the chosen mode of one pass. */
function bucketPaths(mode, lap, frame) {
  const pts = (lap?.points || []).map((p) => ({ x: frame.x(p[0]), y: frame.y(p[1]), power: p[2], flow: p[3] }));
  const paths = ['', '', '', '', '', ''];
  const seg = (a, b, k) => { paths[k] += `M${a.x} ${a.y} L${b.x} ${b.y} `; };
  if (mode === 'loss' || mode === 'eff') {
    (lap?.pieces || []).forEach((piece) => {
      let k;
      if (mode === 'loss') k = piece.within_noise ? NOISE_BUCKET : bucketOf(piece.loss_s ?? 0, TIME_LOST_CUTS);
      else k = piece.within_noise ? EFF_CLASSES.indexOf('par') : Math.max(EFF_CLASSES.indexOf(piece.eff), 0);
      for (let i = piece.from_i; i < piece.to_i && i + 1 < pts.length; i += 1) seg(pts[i], pts[i + 1], k);
    });
  } else {
    const cuts = mode === 'power' ? POWER_CUTS : FLOW_CUTS;
    for (let i = 0; i + 1 < pts.length; i += 1) {
      const v = mode === 'power' ? pts[i].power : pts[i].flow;
      seg(pts[i], pts[i + 1], bucketOf(num(v) ? v : 0, cuts));
    }
  }
  return { paths: paths.map((d) => d.trim()), entry: pts.length ? { x: pts[0].x, y: pts[0].y } : null };
}

const DRILL_NOTES = {
  loss: (lap) => `Lap ${lap}: time lost in each piece of the section against your fastest lap through that piece. Start here, then switch to Efficiency, Power or Flow for the why.`,
  eff: (lap) => `Lap ${lap} against your other laps, piece by piece: faster or slower, with more or fewer watts. Par = within about 0.15 s and 15 W. The dark dot is the section entry.`,
  power: () => 'Power each second. The dark dot is the section entry; the grey line is the rest of the course.',
  flow: () => 'Garmin flow each second (0 = straight, higher = tighter turn). The dark dot is the section entry; the grey line is the rest of the course.',
};

const kmh = (mps) => (num(mps) ? (mps * 3.6).toFixed(1) : null);

function passRows(passes) {
  const list = (passes || []).filter((p) => num(p.lap) && num(p.time_s)).slice().sort((a, b) => a.lap - b.lap);
  if (!list.length) return [];
  const best = Math.min(...list.map((p) => p.time_s));
  const worst = Math.max(...list.map((p) => p.time_s));
  const span = worst - best || 1;
  const flows = list.map((p) => p.avg_flow).filter(num);
  const smoothest = flows.length ? Math.min(...flows) : null;
  return list.map((p) => {
    const d = p.time_s - best;
    return {
      lap: p.lap,
      time: `${p.time_s.toFixed(1)} s`,
      best: d < 0.05,
      delta: d < 0.05 ? 'best' : `+${d.toFixed(1)} s`,
      barPct: d < 0.05 ? 4 : Math.max(8, round((d / span) * 100)),
      power: num(p.avg_power_w) ? `${round(p.avg_power_w)} W` : dash,
      flow: num(p.avg_flow) ? p.avg_flow.toFixed(1) : dash,
      smoothest: num(p.avg_flow) && p.avg_flow === smoothest,
    };
  });
}

export const fastestLap = (passes) => {
  const list = (passes || []).filter((p) => num(p.lap) && num(p.time_s));
  return list.length ? list.reduce((a, b) => (b.time_s < a.time_s ? b : a)).lap : null;
};

/** Everything the drill-down overlay draws. `fetched` is `{status, data, error}` of the sections
 * endpoint (or undefined before the first request); `online` decides offline vs. error wording. */
export function buildDrill(workout, {
  label, mode = 'loss', lap = null, fetched = undefined, online = true, mapView = null,
}) {
  const cs = raceCourse(workout);
  const section = cs?.sectors.find((s) => s.label === label);
  if (!section) return null;
  const secData = fetched?.status === 'ready' ? fetched.data?.sections?.[label] : null;
  const lapKeys = secData ? Object.keys(secData.laps || {}).map(Number).sort(lapOrder) : [];
  const fastest = fastestLap(section.passes);
  const chosen = lapKeys.includes(Number(lap)) ? Number(lap) : (lapKeys.includes(fastest) ? fastest : lapKeys[0] ?? null);
  const rows = buildSectionRows(cs, 'loss');
  const byLabel = new Map(rows.map((r) => [r.label, r]));
  const lossColour = byLabel.get(label)?.colour || NEUTRAL;
  const entry = kmh(section.entry_speed_mps);
  const slowest = kmh(section.min_speed_mps);
  const exit = kmh(section.exit_speed_mps);

  const base = {
    label,
    meta: sectionMeta(section),
    colour: lossColour,
    tabs: cs.sectors.map((s) => ({ label: s.label, on: s.label === label })),
    modes: DRILL_MODES.map((m) => ({ ...m, on: m.key === mode })),
    mode,
    speeds: entry && exit ? { entry, slowest, exit } : null,
    rows: passRows(section.passes),
    note: workout.section_notes?.[label] ?? '',
  };

  if (!secData || chosen === null) {
    const status = fetched?.status === 'loading' ? 'loading' : (!online ? 'offline' : (fetched?.status === 'error' ? 'error' : 'loading'));
    return {
      ...base,
      status,
      error: fetched?.error || null,
      courseMap: buildRaceMap(cs, byLabel, label, lossColour),
    };
  }

  const frame = sectionFrame(secData.bbox);
  const { paths, entry: dot } = bucketPaths(mode, secData.laps[String(chosen)], frame);
  return {
    ...base,
    status: 'ready',
    lap: chosen,
    lapChips: lapKeys.map((k) => ({ lap: k, on: k === chosen, best: k === fastest })),
    map: {
      width: frame.width,
      height: frame.height,
      viewBox: mapView ? viewBoxAttr(mapView) : `0 0 ${frame.width} ${frame.height}`,
      outline: pathOf((fetched.data.outline || []).map((p) => [frame.x(p[0]), frame.y(p[1])])),
      paths,
      colours: DRILL_COLOURS[mode],
      dot,
      aria: `Zoomed map of ${label}, lap ${chosen}, coloured by ${DRILL_MODES.find((m) => m.key === mode).label.toLowerCase()}`,
    },
    legend: [...DRILL_LEGENDS[mode], ...(mode === 'loss' ? ['grey = within timing noise'] : [])].map((text, i) => ({ label: text, colour: DRILL_COLOURS[mode][i] })),
    explain: DRILL_NOTES[mode](chosen),
  };
}
