import { describe, it, expect } from 'vitest';
import { renderDiagramPanel, renderResults, renderOverlay, renderBikeFitView, fmtValue } from '../../src/bikeFitView.js';
import { createBikeFitState, createBikeFitForm } from '../../src/bikeFit.js';

const value = (key, v, sigma) => ({ key, label: `Label ${key}`, unit: key.endsWith('deg') ? 'deg' : 'mm', value: v, sigma, definition: `def ${key}`, depends_on: [] });
const derived = (extra = {}) => ({
  outputs: [value('setback_tip_mm', 5, 1.8), value('effective_seat_angle_deg', 78.8, 0.14)],
  seated: null,
  closure: { status: 'warn', computed_mm: 1000, measured_mm: 1004, residual_mm: -4, warn_mm: 3, bad_mm: 6, message: 'recheck', suspects: [{ measure: 'bb_fa', label: 'BB-FA', sensitivity: 1 }], affected_outputs: ['setback_tip_mm'] },
  ground_pitch_deg: 0.3, radius_difference_mm: -8, assumptions: { bb_mm: 60, fa_mm: 50, ra_mm: 71, h_mm: 210, defaulted: ['bb'] },
  constants: { tape_sigma_mm: 1, sit_fraction: 0.5 }, notes: [],
  points: { BB: [0, 0], FA: [600, 70], RA: [-420, 70], BC: [480, 640], ST: [-5, 705], H: [560, 650], SRP: [-140, 705] },
  axle_heights_mm: { front: 340, rear: 332 },
  ...extra,
});
const snap = (id, name, extra) => ({ id, bike_name: name, bike_type: 'drop_bar', date: '2026-11-02', retired: false, note: '', inputs: {}, derived: derived(extra), error: null });

describe('diagram panel', () => {
  it('renders one diagram per bike type, with all six labelled points', () => {
    for (const type of ['drop_bar', 'mtb']) {
      const html = renderDiagramPanel(type, null);
      for (const p of ['BB', 'FA', 'RA', 'BC', 'ST', 'H']) expect(html).toContain(`data-point="${p}"`);
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
    expect(renderDiagramPanel('drop_bar', 'bb_h')).toContain('top center of the left hood');
    expect(renderDiagramPanel('mtb', 'bb_h')).toContain('center of the left grip');
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
    expect(html).toContain('BB-FA');
    expect(html).toContain('Assumptions');
    expect(html).toContain('def setback_tip_mm');
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
      compare: { a: 'a', b: 'b', status: 'ready', error: null, data: { a, b, factor: 2, unweighted: rows, seated: null, notes: [] } },
    };
    const html = view(state);
    expect(html).toContain('bf-beyond');
    expect(html).toContain('bf-within');
    expect(html).toContain('Exceeds error');
    expect(html).toContain('class="bf-overlay"');
  });

  it('the overlay draws both bikes aligned at the BB', () => {
    const svg = renderOverlay(snap('a', 'CX'), snap('b', 'Trail'));
    expect(svg).toContain('bf-ov-a');
    expect(svg).toContain('bf-ov-b');
    expect(svg).toContain('bf-ov-origin');
  });
});
