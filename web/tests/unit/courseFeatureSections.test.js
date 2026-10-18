import { describe, expect, it } from 'vitest';
import { buildCourseMap, buildCourseSectors } from '../../src/analysis.js';

describe('course-feature sections', () => {
  const track = {
    sectors: [
      { sector: 1, kind: 'straight', name: 'S1', points: [[0, 0], [100, 0]], label: [50, 0] },
      { sector: 2, kind: 'corners', name: 'C1', points: [[100, 0], [100, 50]], label: [100, 25] },
      { sector: 3, kind: 'straight', name: 'S2', points: [[100, 50], [0, 50]], label: [50, 50] },
    ],
  };
  const cs = {
    sector_count: 3, best_lap: 1, fade: { time_change_pct: 1 }, track,
    laps: [
      { lap: 1, time_s: 60, time_vs_best_s: 0, sector_times_s: [21, 19, 20] },
      { lap: 2, time_s: 63, time_vs_best_s: 3, sector_times_s: [22, 21, 20] },
    ],
    sectors: [
      { sector: 1, kind: 'straight', label: 'S1', length_m: 100, best_time_s: 21, mean_loss_s: 0.5, total_loss_s: 1, avg_speed_mps: 6.1 },
      { sector: 2, kind: 'corners', label: 'C1', length_m: 50, best_time_s: 19, mean_loss_s: 1, total_loss_s: 2, spread_s: 2,
        entry_speed_mps: 7.5, min_speed_mps: 3.2, exit_speed_mps: 5.1, flow_by_lap: [4, 6] },
      { sector: 3, kind: 'straight', label: 'S2', length_m: 100, best_time_s: 20, mean_loss_s: 0, total_loss_s: 0 },
    ],
    top_loss_sectors: [2, 1],
  };
  const model = (selected = null) => buildCourseSectors({ analytics: { course_sectors: cs } }, selected);

  it('labels the map by section name and kind', () => {
    const m = buildCourseMap(cs);
    expect(m.sectors.map((s) => s.name)).toEqual(['S1', 'C1', 'S2']);
    expect(m.sectors.map((s) => s.kind)).toEqual(['straight', 'corners', 'straight']);
    expect(m.sectors[1].aria).toBe('Section C1 (corner sequence), loses 2.0 s in total');
  });

  it('names the grid columns by section with their kind', () => {
    const grid = model().grid;
    expect(grid.sectors.map((s) => s.label)).toEqual(['S1', 'C1', 'S2']);
    expect(grid.sectors.map((s) => s.kind)).toEqual(['straight', 'corners', 'straight']);
    expect(grid.sectors[1].aria).toBe('Section C1 (corner sequence)');
  });

  it('describes a selected corner sequence with speeds and the flow trend', () => {
    const line = model(2).selected;
    expect(line).toContain('Section C1 (corner sequence): 50 m');
    expect(line).toContain('Speed in 7.5, slowest 3.2, out 5.1 m/s');
    expect(line).toContain('Flow 4.0 to 6.0 across laps');
    expect(model(1).selected).toContain('Average 6.1 m/s');
  });

  it('explains the sections instead of equal-distance sectors', () => {
    expect(model().featured).toBe(true);
    expect(model().note).toContain('straights (S) and corner sequences (C');
  });

  it('keeps the numbered sectors on the equal-distance fallback', () => {
    const plain = {
      ...cs,
      track: { sectors: track.sectors.map(({ kind, name, ...t }) => t) },
      sectors: cs.sectors.map(({ kind, label, ...s }) => s),
    };
    const m = buildCourseSectors({ analytics: { course_sectors: plain } });
    expect(m.featured).toBe(false);
    expect(m.map.sectors.map((s) => s.name)).toEqual(['1', '2', '3']);
    expect(m.grid.sectors.map((s) => s.label)).toEqual(['S1', 'S2', 'S3']);
    expect(m.note).toContain('equal-distance sectors');
  });
});
