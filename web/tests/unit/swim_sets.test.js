import { describe, it, expect } from 'vitest';
import { buildSwimPace, buildSwimSets } from '../../src/analysis.js';

const POOL = {
  pool_unit: 'yd',
  moving_pace_s_per_100_unit: 109.4,
  elapsed_pace_s_per_100_unit: 116.8,
  moving_pace_s_per_100m: 119.6,
  elapsed_pace_s_per_100m: 127.7,
  rest_total_s: 224,
  segmentation_note: 'Only 2 rests were recorded; rest at the wall without pressing lap/rest isn\'t visible.',
  swim_sets: [
    {
      description: '500 free @ 2:15/100',
      reps: [{ distance: 500, stroke: 'free', swim_time_s: 675, pace_s_per_100: 135, rest_after_s: 30 }],
    },
    { description: '10×100 free on 1:45 @ 1:20/100 (rest ~0:25)', reps: [] },
  ],
};

describe('buildSwimPace', () => {
  it('headlines moving pace in the pool unit, elapsed second, rest total', () => {
    expect(buildSwimPace(POOL)).toEqual({ moving: '1:49 /100yd', elapsed: '1:57 /100yd', rest: '3:44' });
  });
  it('uses per-100m when no pool unit (open water)', () => {
    const p = buildSwimPace({ moving_pace_s_per_100m: 119.6, elapsed_pace_s_per_100m: 120, rest_total_s: 0 });
    expect(p).toEqual({ moving: '2:00 /100m', elapsed: '2:00 /100m', rest: null });
  });
  it('returns null for an old row without the new fields', () => {
    expect(buildSwimPace({ moving_min: 50 })).toBeNull();
    expect(buildSwimPace(null)).toBeNull();
  });
});

describe('buildSwimSets', () => {
  it('lists set descriptions with rep lines and the note', () => {
    const v = buildSwimSets(POOL);
    expect(v.unit).toBe('yd');
    expect(v.sets[0].description).toBe('500 free @ 2:15/100');
    expect(v.sets[0].reps).toEqual(['500 free in 11:15 (2:15/100) · rest 0:30']);
    expect(v.note).toContain('Only 2 rests');
  });
  it('returns null without sets', () => {
    expect(buildSwimSets({ swim_sets: [] })).toBeNull();
    expect(buildSwimSets(undefined)).toBeNull();
  });
});

describe('stroke-less reps and detected rest', () => {
  it('omits the stroke word and marks detected rest', () => {
    const v = buildSwimSets({
      pool_unit: 'yd',
      swim_sets: [{
        description: '4×100 on 1:45 @ 1:36/100 (rest ~0:10, detected)',
        reps: [{ distance: 100, stroke: null, swim_time_s: 96, pace_s_per_100: 96, rest_after_s: 9, rest_source: 'detected' }],
      }],
    });
    expect(v.sets[0].reps).toEqual(['100 in 1:36 (1:36/100) · rest 0:09 (detected)']);
  });
});
