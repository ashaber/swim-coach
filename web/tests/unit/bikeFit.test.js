import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import {
  createBikeFitForm, setBikeType, setField, serializeBikeFit, saveDraft, loadDraft, clearDraft,
  draftKey, focusInfo, signedAngle,
} from '../../src/bikeFit.js';
import { POINT_DEFINITIONS, TAPE_FIELDS, WIDTH_DEFAULTS_MM, H_STEPS } from '../../src/bikeFitSpec.js';

const memoryStorage = () => {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, String(v)), removeItem: (k) => m.delete(k) };
};
const throwingStorage = () => ({
  getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); }, removeItem() { throw new Error('blocked'); },
});

function filled(type = 'drop_bar') {
  let f = createBikeFitForm({ bikeType: type, today: '2026-11-02' });
  f = setField(f, 'name', 'CX');
  TAPE_FIELDS.forEach((t, i) => { f = setField(f, t.key, String(500 + i * 10)); });
  f = setField(f, 'tiltMag', '0');
  f = setField(f, 'saddleLength', '270');
  f = setField(f, 'crankLength', '172.5');
  f = setField(f, 'stringLength', '420');
  return f;
}

describe('form defaults', () => {
  it('starts as a drop-bar bike dated today with blank widths (fallbacks are not prefilled)', () => {
    const f = createBikeFitForm({ today: '2026-11-02' });
    expect(f.bikeType).toBe('drop_bar');
    expect(f.date).toBe('2026-11-02');
    expect([f.crankWidth, f.frontAxleWidth, f.rearAxleWidth]).toEqual(['', '', '']);
  });

  it('switching bike type keeps what was typed', () => {
    let f = setField(createBikeFitForm({ today: '2026-11-02' }), 'frontAxleWidth', '101');
    f = setBikeType(f, 'mtb');
    expect(f.bikeType).toBe('mtb');
    expect(f.frontAxleWidth).toBe('101');
  });
});

describe('serializeBikeFit', () => {
  it('builds the API payload with numbers, not strings', () => {
    const r = serializeBikeFit(filled());
    expect(r.ok).toBe(true);
    expect(r.payload.bike_name).toBe('CX');
    expect(r.payload.bike_type).toBe('drop_bar');
    expect(r.payload.inputs.tape.bb_fa).toBe(500);
    expect(r.payload.inputs.crank_length_mm).toBe(172.5);
    expect(r.payload.inputs.string_length_mm).toBe(420);
    expect(r.payload.inputs.crank_bolt_width_mm).toBeUndefined();
    expect(r.payload.inputs.bar_model).toBeUndefined();
    expect(r.payload.inputs.tape.fa_h).toBeGreaterThan(0);
    expect(r.payload.inputs.sag_front_pct).toBeUndefined();
    expect(r.payload.inputs.seated_floor_bb_mm).toBeUndefined();
  });

  it('sends measured widths and the recorded bar text, and rejects a silly width', () => {
    let f = setField(setField(setField(filled(), 'crankWidth', '121'), 'frontAxleWidth', '100'), 'barModel', 'Zipp SL-70');
    const r = serializeBikeFit(f);
    expect(r.payload.inputs.crank_bolt_width_mm).toBe(121);
    expect(r.payload.inputs.front_axle_width_mm).toBe(100);
    expect(r.payload.inputs.bar_model).toBe('Zipp SL-70');
    f = setField(filled(), 'rearAxleWidth', '5');
    expect(serializeBikeFit(f).ok).toBe(false);
  });

  it('requires crank length and string length', () => {
    const r = serializeBikeFit(setField(setField(filled(), 'crankLength', ''), 'stringLength', ''));
    expect(r.errors.join(' ')).toMatch(/Crank length/);
    expect(r.errors.join(' ')).toMatch(/String length/);
  });

  it('lists every missing required field in one pass', () => {
    const r = serializeBikeFit(createBikeFitForm({ today: '2026-11-02' }));
    expect(r.ok).toBe(false);
    expect(r.errors.length).toBeGreaterThanOrEqual(TAPE_FIELDS.length + 1);
    expect(r.errors.join(' ')).toMatch(/BB to FA/);
  });

  it('rejects non-numeric and non-positive tape values', () => {
    const r = serializeBikeFit(setField(setField(filled(), 'bb_fa', 'abc'), 'bb_bc', '0'));
    expect(r.ok).toBe(false);
    expect(r.errors.join(' ')).toMatch(/BB to FA/);
    expect(r.errors.join(' ')).toMatch(/BB to BC/);
  });

  it('signs the saddle tilt and subtracts nothing client-side (the engine does)', () => {
    let f = setField(setField(filled(), 'tiltDir', 'down'), 'tiltMag', '2.5');
    expect(serializeBikeFit(f).payload.inputs.saddle_tilt_deg).toBe(-2.5);
    f = setField(setField(f, 'tiltDir', 'up'), 'tiltMag', '1');
    f = setField(setField(f, 'floorDir', 'down'), 'floorMag', '0.4');
    const p = serializeBikeFit(f).payload.inputs;
    expect(p.saddle_tilt_deg).toBe(1);
    expect(p.floor_tilt_deg).toBe(-0.4);
  });

  it('requires both seated readings or neither', () => {
    const r = serializeBikeFit(setField(filled('mtb'), 'seatBb', '330'));
    expect(r.ok).toBe(false);
    expect(r.errors.join(' ')).toMatch(/seated/i);
    const both = serializeBikeFit(setField(setField(filled('mtb'), 'seatBb', '330'), 'seatBc', '980'));
    expect(both.payload.inputs.seated_floor_bb_mm).toBe(330);
  });

  it('includes sag and tire pressures when given', () => {
    const f = setField(setField(setField(filled('mtb'), 'sagFront', '20'), 'sagRear', '30'), 'tireFront', '22');
    const r = serializeBikeFit(f);
    expect(r.payload.inputs.sag_front_pct).toBe(20);
    expect(r.payload.tire_front_psi).toBe(22);
    expect(r.payload.tire_rear_psi).toBeUndefined();
  });

  it('signedAngle: blank is null, level is zero', () => {
    expect(signedAngle('up', '')).toBeNull();
    expect(signedAngle('down', '0')).toBe(0);
  });
});

describe('draft persistence', () => {
  it('round-trips through storage per athlete', () => {
    const s = memoryStorage();
    saveDraft('renee', filled(), s);
    expect(loadDraft('renee', s).name).toBe('CX');
    expect(loadDraft('someone-else', s)).toBeNull();
    clearDraft('renee', s);
    expect(loadDraft('renee', s)).toBeNull();
  });

  it('survives blocked storage without throwing', () => {
    const s = throwingStorage();
    expect(() => saveDraft('renee', filled(), s)).not.toThrow();
    expect(loadDraft('renee', s)).toBeNull();
    expect(() => clearDraft('renee', s)).not.toThrow();
  });

  it('ignores a corrupt or wrong-version draft', () => {
    const s = memoryStorage();
    s.setItem(draftKey('renee'), '{not json');
    expect(loadDraft('renee', s)).toBeNull();
    s.setItem(draftKey('renee'), JSON.stringify({ version: 99, form: { name: 'x' } }));
    expect(loadDraft('renee', s)).toBeNull();
  });

  it('merges a draft over fresh defaults so new fields still exist', () => {
    const s = memoryStorage();
    s.setItem(draftKey('renee'), JSON.stringify({ version: 1, form: { name: 'Old' } }));
    const d = loadDraft('renee', s);
    expect(d.name).toBe('Old');
    expect(d.crankWidth).toBeDefined();
  });
});

describe('focusInfo (diagram highlight)', () => {
  it('a tape field highlights its two points, the tape line, and each exact definition', () => {
    const info = focusInfo('bb_bc', 'drop_bar');
    expect(info.points).toEqual(['BB', 'BC']);
    expect(info.tape).toEqual({ from: 'BB', to: 'BC' });
    expect(info.definitions.map((d) => d.text)).toEqual([POINT_DEFINITIONS.BB, POINT_DEFINITIONS.BC]);
    expect(POINT_DEFINITIONS.BB).toContain('center of the left crank bolt');
  });

  it('H takes the bike-type definition', () => {
    expect(focusInfo('bb_h', 'drop_bar').definitions[1].text).toContain('top centers of the left and right hoods');
    expect(focusInfo('bb_h', 'mtb').definitions[1].text).toContain('centers of the left and right grips');
    expect(focusInfo('bc_h', 'mtb').points).toEqual(['BC', 'H']);
    expect(focusInfo('stringLength', 'mtb').points).toEqual(['H']);
  });

  it('floor-height fields highlight the axle and a vertical floor line', () => {
    const info = focusInfo('floor_fa', 'mtb');
    expect(info.points).toEqual(['FA']);
    expect(info.floor).toBe('FA');
    expect(info.tape).toBeNull();
  });

  it('seated heights highlight BB and BC with floor lines', () => {
    expect(focusInfo('seatBb', 'mtb').floor).toBe('BB');
    expect(focusInfo('seatBc', 'mtb').floor).toBe('BC');
  });

  it('unknown fields highlight nothing', () => {
    expect(focusInfo('name', 'mtb').points).toEqual([]);
  });
});

describe('point definitions are verbatim', () => {
  it('match the brief and appear in the spec module source', () => {
    const src = readFileSync(fileURLToPath(new URL('../../src/bikeFitSpec.js', import.meta.url)), 'utf8');
    for (const text of [
      'center of the left crank bolt', 'center of the left front axle end', 'center of the left rear axle end',
      "bar clamp, center of where the stem clamps the bar, on the bike's centerline",
      'saddle tip, on the centerline',
      'midpoint of a string stretched between the top centers of the left and right hoods, where the palms sit',
      'midpoint of a string stretched between the centers of the left and right grips, where the palms sit',
    ]) {
      expect(src).toContain(text);
    }
  });

  it('width fallbacks mirror the engine constants', () => {
    const py = readFileSync(fileURLToPath(new URL('../../../engine/swim_coach/bike_fit.py', import.meta.url)), 'utf8');
    for (const [type, d] of Object.entries(WIDTH_DEFAULTS_MM)) {
      expect(py).toContain(`"${type}": {"crank": ${d.crank}.0, "fa": ${d.fa}.0, "ra": ${d.ra}.0}`);
    }
  });

  it('the string method has step-by-step wording for both bikes', () => {
    expect(H_STEPS.drop_bar).toHaveLength(3);
    expect(H_STEPS.mtb[0]).toContain('grips');
  });
});
