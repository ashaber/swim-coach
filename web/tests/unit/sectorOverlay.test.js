import { describe, it, expect } from 'vitest';
import { createSectorOverlay, openSectorOverlay, switchOverlaySector, closeSectorOverlay } from '../../src/sectorOverlay.js';
import { renderSectorOverlay, renderWorkoutDetail } from '../../src/views.js';

const cs = {
  sector_count: 2, best_lap: 1,
  fade: { time_change_pct: 1 },
  laps: [{ lap: 1, time_s: 600, time_vs_best_s: 0, sector_times_s: [30, 40] }, { lap: 2, time_s: 610, time_vs_best_s: 10, sector_times_s: [32, 48] }],
  sectors: [
    { sector: 1, best_time_s: 30, total_loss_s: 4, mean_loss_s: 2, spread_s: 3 },
    { sector: 2, best_time_s: 40, total_loss_s: 9, mean_loss_s: 4.5, spread_s: 5 },
  ],
  track: { sectors: [
    { sector: 1, points: [[0, 0], [10, 5]], label: [5, 2] },
    { sector: 2, points: [[10, 5], [20, 0]], label: [15, 2] },
  ] },
};
const workout = { id: 'w1', date: '2026-09-29', sport: 'bike', source: 'fit', distance_m: 1, duration_min: 1, laps: [], analytics: { course_sectors: cs } };

describe('sector overlay state', () => {
  it('opens with a sector and remembers scroll', () => {
    expect(openSectorOverlay(2, 340)).toEqual({ overlay: { open: true, scrollY: 340 }, selectedSector: 2, mapView: null });
  });
  it('opens without a selection from Expand', () => {
    expect(openSectorOverlay(null, 10).selectedSector).toBeNull();
  });
  it('switches sector in place and never toggles off', () => {
    expect(switchOverlaySector(1, '2')).toBe(2);
    expect(switchOverlaySector(2, 2)).toBe(2);
  });
  it('close clears selection and zoom but keeps scroll for restore', () => {
    expect(closeSectorOverlay({ open: true, scrollY: 340 }))
      .toEqual({ overlay: { open: false, scrollY: 340 }, selectedSector: null, mapView: null });
    expect(createSectorOverlay().open).toBe(false);
  });
});

describe('sector overlay view', () => {
  it('renders a labelled dialog with map, grid, summary and nothing else', () => {
    const html = renderSectorOverlay(workout, 2, null);
    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(html).toContain('aria-label="Course sectors"');
    expect(html).toContain('class="cs-map"');
    expect(html).toContain('cs-grid');
    expect(html).toContain('Sector 2: best time 40.0 s');
    expect(html).toContain('data-a="sector-overlay:close"');
    expect(html).not.toContain('detail-section');
  });
  it('renders nothing without course sectors', () => {
    expect(renderSectorOverlay({ ...workout, analytics: {} }, null, null)).toBe('');
  });
  it('shows a tap hint with no selection', () => {
    expect(renderSectorOverlay(workout, null, null)).toContain('Tap a sector');
  });
  it('in-page map has an Expand button, overlay map does not', () => {
    expect(renderWorkoutDetail(workout, {})).toContain('data-a="sector-overlay:open"');
    expect(renderSectorOverlay(workout, null, null)).not.toContain('sector-overlay:open');
  });
});
