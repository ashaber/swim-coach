import { describe, it, expect } from 'vitest';
import { renderDiagramPanel, renderResults, renderOverlay, renderBikeFitView, fmtValue } from '../../src/bikeFitView.js';
import { createBikeFitState, createBikeFitForm } from '../../src/bikeFit.js';

const value = (key, v, sigma) => ({ key, label: `Label ${key}`, unit: key.endsWith('deg') ? 'deg' : 'mm', value: v, sigma, definition: `def ${key}`, depends_on: [] });
const derived = (extra = {}) => ({
  outputs: [value('setback_tip_mm', 5, 1.8), value('effective_seat_angle_deg', 78.8, 0.14)],
  seated: null,
  closure: {
    status: 'warn', message: 'recheck', not_checked: 'The six checks cannot see the floor heights.',
    checks: [
      { key: 'ra_fa', label: 'RA-FA (wheelbase)', computed_mm: 1000, measured_mm: 1004, residual_mm: -4, sigma_mm: 1.7, warn_mm: 4.2, bad_mm: 6.8, status: 'ok' },
      { key: 'fa_h', label: 'FA-H', computed_mm: 900, measured_mm: 905, residual_mm: -5, sigma_mm: 2.5, warn_mm: 6.2, bad_mm: 10, status: 'warn' },
    ],
    suspects: [{ measure: 'bb_fa', label: 'BB-FA', estimated_error_mm: 12, fit: 0.97 }], affected_outputs: ['setback_tip_mm'],
  },
  ground_pitch_deg: 0.3, radius_difference_mm: -8, assumptions: { bb_mm: 60, fa_mm: 50, ra_mm: 71, widths_mm: { crank_bolt: 120, front_axle: 100, rear_axle: 142 }, defaulted: ['crank'] },
  lateral_effect: { width_error_mm: 5, max_output_change_mm: 0.22, per_width_mm: {} },
  constants: { tape_sigma_mm: 1 }, notes: [],
  coordinates: [
    { key: 'st', label: 'Saddle tip (ST)', x: -5, y: 705, sigma_x: 1.1, sigma_y: 1.2 },
    { key: 's', label: 'Sit-bone point (S)', x: -140, y: 703, sigma_x: 2.1, sigma_y: 1 },
    { key: 'bc', label: 'Bar clamp (BC)', x: 480, y: 640, sigma_x: 1, sigma_y: 1 },
    { key: 'h', label: 'Hand point (H)', x: 560, y: 650, sigma_x: 1, sigma_y: 1 },
  ],
  recorded: { saddle_model: 'Test saddle', saddle_rail_note: '2 mm back', saddle_tilt_deg: 1, floor_tilt_deg: null, saddle_length_mm: 270, sit_point_from_tip_mm: 135, frame_stack_mm: null, frame_reach_mm: 390, pedal_stack_mm: 12, pedal_stack_source: 'maker_spec' },
  points: { BB: [0, 0], FA: [600, 70], RA: [-420, 70], BC: [480, 640], ST: [-5, 705], H: [560, 650], S: [-140, 703] },
  axle_heights_mm: { front: 340, rear: 332 },
  ...extra,
});
const snap = (id, name, extra) => ({ id, bike_name: name, bike_type: 'drop_bar', date: '2026-11-02', retired: false, note: '', inputs: { string_length_mm: 420, bar_model: 'Zipp SL-70' }, derived: derived(extra), error: null });

describe('diagram panel', () => {
  it('renders one diagram per bike type, with all seven labelled points', () => {
    for (const type of ['drop_bar', 'mtb']) {
      const html = renderDiagramPanel(type, null);
      for (const p of ['BB', 'FA', 'RA', 'BC', 'ST', 'S', 'H']) expect(html).toContain(`data-point="${p}"`);
      expect(html).not.toContain('is-active');
    }
    expect(renderDiagramPanel('mtb', null)).not.toBe(renderDiagramPanel('drop_bar', null));
  });

  it('focus highlights the two points, the tape line and the exact definitions', () => {
    const html = renderDiagramPanel('drop_bar', 'bb_bc');
    expect(html.match(/class="bf-pt is-active"/g)).toHaveLength(2);
    expect(html).toContain('class="bf-tape"');
    expect(html).toContain('center of the left crank bolt');
    expect(html).toContain('bar clamp, center of where the stem clamps the bar, on the bike&#39;s centerline');
  });

  it('hand point definition follows bike type', () => {
    expect(renderDiagramPanel('drop_bar', 'bb_h')).toContain('top centers of the left and right hoods');
    expect(renderDiagramPanel('mtb', 'bb_h')).toContain('centers of the left and right grips');
    expect(renderDiagramPanel('mtb', 'bb_h')).toContain('bf-string');
  });

  it('floor-height focus draws a line to the floor', () => {
    const html = renderDiagramPanel('mtb', 'floor_fa');
    expect(html.match(/class="bf-pt is-active"/g)).toHaveLength(1);
    expect(html).toContain('class="bf-tape"');
  });
});

describe('results', () => {
  it('shows value, plus-minus, closure status, assumptions and what each value means', () => {
    const html = renderResults(snap('a', 'CX'));
    expect(html).toContain('5.0');
    expect(html).toContain('±1.8');
    expect(html).toContain('data-closure="warn"');
    expect(html.match(/data-check=/g)).toHaveLength(2);
    expect(html).toContain('BB-FA');
    expect(html).toContain('a hint only');
    expect(html).toContain('floor heights');
    expect(html).toContain('(assumed fallback)');
    expect(html).toContain('(measured)');
    expect(html).toContain('0.22 mm');
    expect(html).toContain('Zipp SL-70');
    expect(html).toContain('def setback_tip_mm');
  });

  it('shows BB-origin coordinates, the clamp versus hand wording, and the recorded-only fields', () => {
    const html = renderResults(snap('a', 'CX'));
    expect(html.match(/data-coord=/g)).toHaveLength(4);
    expect(html).toContain('Sit-bone point (S)');
    expect(html).toContain('Bar stack and reach are at the clamp');
    expect(html).toContain('hand reach and drop are at H');
    expect(html).toContain('head tube top');
    expect(html).toContain('sit-bone point S (135 mm from the tip, Test saddle)');
    expect(html).toContain('Saddle rail note: 2 mm back');
    expect(html).toContain('Frame reach: 390 mm');
    expect(html).toContain('Pedal stack: 12 mm (maker spec)');
    expect(html).not.toMatch(/SRP|midpoint of the saddle/);
  });

  it('shows the engine tilt advisory as a neutral note', () => {
    const note = 'Tilt beyond \u00b14\u00b0: check the measurement. Not a target.';
    const html = renderResults(snap('a', 'CX', { notes: [note] }));
    expect(html).toContain('Tilt beyond \u00b14\u00b0: check the measurement');
  });

  it('formats degrees and avoids negative zero', () => {
    expect(fmtValue(78.84, 'deg')).toBe('78.8°');
    expect(fmtValue(-0.01, 'mm')).toBe('0.0');
  });

  it('reports an unsolvable snapshot as an error, not a table', () => {
    const html = renderResults({ ...snap('a', 'CX'), derived: null, error: 'BB-BC cannot form a triangle' });
    expect(html).toContain('no longer solve');
    expect(html).not.toContain('<table');
  });
});

describe('whole view', () => {
  const view = (bikeFit) => renderBikeFitView({ bikeFit, online: true });

  it('states plainly that it records geometry and does not recommend changes', () => {
    const html = view({ ...createBikeFitState(), open: true, form: createBikeFitForm({ today: '2026-11-02' }) });
    expect(html).toContain('doesn&#39;t recommend changes'.replace('&#39;', '’'));
    expect(html).toContain('inputmode="numeric"');
  });

  it('renders the comparison with exceeds-error indicators and an overlay', () => {
    const a = snap('a', 'CX');
    const b = snap('b', 'Trail');
    const rows = [
      { key: 'setback_tip_mm', label: 'Setback', unit: 'mm', a: 5, b: 90, diff: 85, sigma_a: 1.8, sigma_b: 2, sigma_diff: 2.7, exceeds_error: true },
      { key: 'reach_bc_mm', label: 'Reach', unit: 'mm', a: 480, b: 482, diff: 2, sigma_a: 1.7, sigma_b: 1.7, sigma_diff: 2.4, exceeds_error: false },
    ];
    const state = {
      ...createBikeFitState(), open: true, snapshots: [a, b], form: createBikeFitForm({ today: '2026-11-02' }),
      compare: { a: 'a', b: 'b', status: 'ready', error: null, data: { a, b, factor: 2, unweighted: rows, seated: null, notes: [], saddle: { model_a: 'Test saddle', model_b: 'Test saddle', same: true }, crank: { a_mm: 172.5, b_mm: 170, diff_mm: -2.5, pedal_down_effect_mm: -2.5, pedal_up_effect_mm: 2.5 }, pedal_stack: { a_mm: 12, b_mm: 15, diff_mm: 3, adjusted_pedal_down_diff_mm: 0.5, sigma_each_mm: 3, sigma_diff_mm: 4.6, exceeds_error: false, note: 'Pedal stack is hard to measure and its accuracy is limited.' } } },
    };
    const html = view(state);
    expect(html).toContain('bf-beyond');
    expect(html).toContain('bf-within');
    expect(html).toContain('Exceeds error');
    expect(html).toContain('class="bf-overlay"');
    expect(html).toContain('data-saddle-same="1"');
    expect(html).toContain('Crank length: 172.5 mm vs 170 mm, a difference of -2.5 mm');
    expect(html).toContain('-2.5 mm with the crank down and +2.5 mm with the crank up');
    expect(html).toContain('data-pedal-stack="1"');
    expect(html).toContain('stated 3 mm per-snapshot assumption');
    expect(html).not.toMatch(/you should|we recommend/i);
  });

  it('the overlay draws both bikes aligned at the BB', () => {
    const svg = renderOverlay(snap('a', 'CX'), snap('b', 'Trail'));
    expect(svg).toContain('bf-ov-a');
    expect(svg).toContain('bf-ov-b');
    expect(svg).toContain('bf-ov-origin');
  });
});

describe('fitter setup notes block', () => {
  const view = (setupNotes) => renderBikeFitView({ bikeFit: { ...createBikeFitState(), setupNotes }, online: true });
  const note = (extra = {}) => ({ id: 'n1', date: '2025-05-01', text: 'Professional fit.\nSaddle height 75.2 cm', pressure_front_psi: 18, pressure_rear_psi: 19, ...extra });

  it('lists each note above the form with its date, text and tire pressures', () => {
    const html = view([note(), note({ id: 'n2', date: '2026-03-01', text: 'New cleats', pressure_front_psi: null, pressure_rear_psi: null })]);
    expect(html).toContain("Fitter's numbers and setup notes");
    expect(html).toContain('2025-05-01');
    expect(html).toContain('Saddle height 75.2 cm');
    expect(html).toContain('Tires at the time: 18 psi front / 19 psi rear');
    expect(html.match(/Tires at the time/g)).toHaveLength(1);
    expect(html.indexOf("Fitter's numbers")).toBeLessThan(html.indexOf('data-form="bikefit"'));
  });

  it('is absent when there are no notes', () => {
    expect(view([])).not.toContain('Fitter');
    expect(renderBikeFitView({ bikeFit: createBikeFitState(), online: true })).not.toContain('Fitter');
  });

  it('escapes html in note text', () => {
    const html = view([note({ text: 'bars <b>wide</b> & low' })]);
    expect(html).toContain('bars &lt;b&gt;wide&lt;/b&gt; &amp; low');
    expect(html).not.toContain('<b>wide</b>');
  });
});
