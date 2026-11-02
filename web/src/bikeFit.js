// Bike-geometry form logic: form state, validation into the API payload, the local draft (so a
// half-finished garage session survives a reload or going offline), and which diagram points a
// focused field highlights. Pure functions over plain objects; the DOM lives in bikeFitView.js.
// Measurements only: nothing in here suggests a fit change.

import log from './log.js';
import {
  TAPE_FIELDS, TAPE_KEYS, POINT_NAMES, pointDefinition,
} from './bikeFitSpec.js';

const DRAFT_VERSION = 1;
const DRAFT_PREFIX = 'swimcoach_bikefit_draft_';

export function createBikeFitForm({ bikeType = 'drop_bar', today = '' } = {}) {
  const form = {
    name: '', bikeType, date: today, note: '', tireFront: '', tireRear: '',
    tiltDir: 'up', tiltMag: '', floorDir: 'up', floorMag: '',
    saddleLength: '', crankLength: '', stringLength: '',
    crankWidth: '', frontAxleWidth: '', rearAxleWidth: '',
    barModel: '', stemLength: '', backsweep: '', upsweep: '',
    sagFront: '', sagRear: '', seatBb: '', seatBc: '',
  };
  for (const key of TAPE_KEYS) form[key] = '';
  return form;
}

/** Slice of app state for the bike-geometry view (see main.js's state.bikeFit). */
export function createBikeFitState() {
  return {
    open: false,
    load: { status: 'idle', error: null },
    snapshots: [],
    limits: '',
    form: createBikeFitForm(),
    formErrors: [],
    focus: null,
    submit: { status: 'idle', message: null },
    selectedId: null,
    compare: { a: '', b: '', status: 'idle', data: null, error: null },
  };
}

export function localIsoDate(now = new Date()) {
  const pad = (n) => String(n).padStart(2, '0');
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

export function setField(form, field, value) {
  return { ...form, [field]: value };
}

export function setBikeType(form, bikeType) {
  return { ...form, bikeType };
}

function num(text) {
  const t = String(text ?? '').trim().replace(',', '.');
  if (t === '') return null;
  const n = Number(t);
  return Number.isFinite(n) ? n : NaN;
}

export function signedAngle(dir, mag) {
  const n = num(mag);
  if (n === null || Number.isNaN(n)) return n;
  const size = Math.abs(n);
  return dir === 'down' && size !== 0 ? -size : size;
}

function putOptional(target, key, value) {
  if (value !== null && !Number.isNaN(value)) target[key] = value;
}

/** Validates the form and builds the POST /api/bike-fit payload, or lists every problem. */
export function serializeBikeFit(form) {
  const errors = [];
  const required = (text, label, { min = 0, max = Infinity, exclusiveMin = true } = {}) => {
    const n = num(text);
    if (n === null) { errors.push(`${label} is required`); return null; }
    if (Number.isNaN(n)) { errors.push(`${label} must be a number`); return null; }
    if (exclusiveMin ? n <= min : n < min) { errors.push(`${label} must be greater than ${min}`); return null; }
    if (n > max) { errors.push(`${label} must be at most ${max}`); return null; }
    return n;
  };
  const optional = (text, label, max) => {
    const n = num(text);
    if (n === null) return null;
    if (Number.isNaN(n) || n < 0 || n > max) { errors.push(`${label} must be a number from 0 to ${max}`); return null; }
    return n;
  };

  if (!String(form.name).trim()) errors.push('Bike name is required');
  if (!form.date) errors.push('Date is required');
  const tape = {};
  for (const t of TAPE_FIELDS) {
    tape[t.key] = required(form[t.key], `${t.n}. ${t.label}`, { max: t.floor ? 1500 : 3000 });
  }
  const tilt = signedAngle(form.tiltDir, form.tiltMag);
  if (tilt === null) errors.push('Saddle tilt is required (enter 0 if level)');
  else if (Number.isNaN(tilt) || Math.abs(tilt) > 45) errors.push('Saddle tilt must be a number up to 45 degrees');
  const floorTilt = signedAngle(form.floorDir, form.floorMag);
  if (Number.isNaN(floorTilt) || (floorTilt !== null && Math.abs(floorTilt) > 20)) {
    errors.push('Floor reading must be a number up to 20 degrees');
  }
  const saddleLength = required(form.saddleLength, 'Saddle length', { min: 100, max: 400, exclusiveMin: false });
  const crankLength = required(form.crankLength, 'Crank length', { min: 140, max: 220, exclusiveMin: false });
  const stringLength = required(form.stringLength, 'String length (contact width)', { min: 100, max: 900, exclusiveMin: false });
  const seatBb = optional(form.seatBb, 'Seated floor to BB', 1500);
  const seatBc = optional(form.seatBc, 'Seated floor to BC', 2000);
  if ((seatBb === null) !== (seatBc === null)) errors.push('Give both seated heights (floor to BB and floor to BC) or neither');
  if (errors.length) return { ok: false, errors };

  const inputs = {
    tape,
    saddle_tilt_deg: tilt,
    saddle_length_mm: saddleLength,
    crank_length_mm: crankLength,
    string_length_mm: stringLength,
  };
  putOptional(inputs, 'floor_tilt_deg', floorTilt);
  const width = (text, label) => {
    const n = num(text);
    if (n === null) return null;
    if (Number.isNaN(n) || n < 40 || n > 400) { errors.push(`${label} must be a number from 40 to 400 mm (or blank to use the fallback)`); return null; }
    return n;
  };
  putOptional(inputs, 'crank_bolt_width_mm', width(form.crankWidth, 'Crank bolt width'));
  putOptional(inputs, 'front_axle_width_mm', width(form.frontAxleWidth, 'Front axle width'));
  putOptional(inputs, 'rear_axle_width_mm', width(form.rearAxleWidth, 'Rear axle width'));
  for (const [key, field] of [['bar_model', 'barModel'], ['stem_length', 'stemLength'], ['bar_backsweep', 'backsweep'], ['bar_upsweep', 'upsweep']]) {
    const text = String(form[field] || '').trim();
    if (text) inputs[key] = text;
  }
  putOptional(inputs, 'sag_front_pct', optional(form.sagFront, 'Front sag', 100));
  putOptional(inputs, 'sag_rear_pct', optional(form.sagRear, 'Rear sag', 100));
  putOptional(inputs, 'seated_floor_bb_mm', seatBb);
  putOptional(inputs, 'seated_floor_bc_mm', seatBc);

  const payload = {
    bike_name: String(form.name).trim(), bike_type: form.bikeType, date: form.date,
    note: String(form.note || '').trim(), inputs,
  };
  putOptional(payload, 'tire_front_psi', optional(form.tireFront, 'Front tire pressure', 200));
  putOptional(payload, 'tire_rear_psi', optional(form.tireRear, 'Rear tire pressure', 200));
  if (errors.length) return { ok: false, errors };
  return { ok: true, payload };
}

// --- Local draft ---------------------------------------------------------------------------

export function draftKey(athlete) {
  return `${DRAFT_PREFIX}${athlete || 'unknown'}`;
}

export function saveDraft(athlete, form, storage = localStorage) {
  try {
    storage.setItem(draftKey(athlete), JSON.stringify({ version: DRAFT_VERSION, form }));
  } catch (err) {
    log.warn('bikefit.draft_save_failed', { error: String(err?.message || err) });
  }
}

export function loadDraft(athlete, storage = localStorage) {
  try {
    const raw = storage.getItem(draftKey(athlete));
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.version !== DRAFT_VERSION || typeof parsed.form !== 'object' || parsed.form === null) return null;
    const base = createBikeFitForm({ bikeType: parsed.form.bikeType === 'mtb' ? 'mtb' : 'drop_bar' });
    return { ...base, ...parsed.form };
  } catch (err) {
    log.warn('bikefit.draft_load_failed', { error: String(err?.message || err) });
    return null;
  }
}

export function clearDraft(athlete, storage = localStorage) {
  try {
    storage.removeItem(draftKey(athlete));
  } catch (err) {
    log.warn('bikefit.draft_clear_failed', { error: String(err?.message || err) });
  }
}

// --- Diagram highlight -----------------------------------------------------------------------

// Form fields that point at something on the bike beyond the twelve tape measures.
const OTHER_FOCUS = {
  tiltDir: { points: ['ST'], extra: 'saddle' },
  tiltMag: { points: ['ST'], extra: 'saddle' },
  floorDir: { points: [], extra: null },
  floorMag: { points: [], extra: null },
  saddleLength: { points: ['ST'], extra: 'saddle' },
  crankLength: { points: ['BB'], extra: 'crank' },
  stringLength: { points: ['H'], extra: 'string' },
  crankWidth: { points: ['BB'], extra: null },
  frontAxleWidth: { points: ['FA'], extra: null },
  rearAxleWidth: { points: ['RA'], extra: null },
  seatBb: { points: ['BB'], floor: 'BB' },
  seatBc: { points: ['BC'], floor: 'BC' },
};

/**
 * What the diagram should highlight for a focused form field: the two points, the tape line
 * between them (or a vertical line to the floor), and the exact definition of each point.
 */
export function focusInfo(field, bikeType) {
  const tape = TAPE_FIELDS.find((t) => t.key === field);
  let points = [];
  let tapeLine = null;
  let floor = null;
  let extra = null;
  if (tape) {
    points = tape.floor ? [tape.from] : [tape.from, tape.to];
    tapeLine = tape.floor ? null : { from: tape.from, to: tape.to };
    floor = tape.floor ? tape.from : null;
  } else if (OTHER_FOCUS[field]) {
    ({ points } = OTHER_FOCUS[field]);
    floor = OTHER_FOCUS[field].floor || null;
    extra = OTHER_FOCUS[field].extra || null;
  }
  return {
    field,
    points,
    tape: tapeLine,
    floor,
    extra,
    definitions: points.map((p) => ({ point: p, name: POINT_NAMES[p], text: pointDefinition(p, bikeType) })),
  };
}
