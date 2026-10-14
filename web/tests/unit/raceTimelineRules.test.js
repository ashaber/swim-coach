import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  timelineClock, editTimelineEntry, removeTimelineEntry, addTimelineEntry, mergeOp, loadQueue, enqueue,
} from '../../src/raceDay.js';
import { renderRaceDayOverlay } from '../../src/views.js';

// Shared with tests/unit/test_race_timeline_rules.py -- the engine and the PWA must agree.
const VECTORS = JSON.parse(readFileSync(new URL('../../../tests/fixtures/race_timeline_vectors.json', import.meta.url), 'utf8'));

describe('shared timeline vectors', () => {
  VECTORS.cases.forEach((c) => {
    it(c.name, () => {
      const clock = timelineClock({ start_time: c.start_time, timeline: c.timeline || VECTORS.timeline });
      const byId = Object.fromEntries(clock.map((e) => [e.id, e.time]));
      Object.entries(c.expect).forEach(([id, time]) => expect(byId[id], id).toBe(time));
      c.absent.forEach((id) => expect(Object.keys(byId)).not.toContain(id));
      const timed = clock.map((e) => e.abs_min).filter((m) => m !== null);
      expect(timed).toEqual([...timed].sort((a, b) => a - b));
    });
  });
});

describe('timeline editing helpers', () => {
  const tl = [
    { id: 'wake', label: 'Wake', day: 'race', offset_min: -300, not_later_than: '07:00', is_start: false },
    { id: 'start', label: 'Start', day: 'race', offset_min: 0, is_start: true },
  ];
  it('edits label, offset and rules; empty rule clears it', () => {
    let next = editTimelineEntry(tl, 'wake', 'label', ' Get up ');
    next = editTimelineEntry(next, 'wake', 'offset_min', '-240');
    next = editTimelineEntry(next, 'wake', 'not_later_than', '');
    next = editTimelineEntry(next, 'wake', 'only_if_start_after', '12:00');
    expect(next[0]).toMatchObject({ label: 'Get up', offset_min: -240, not_later_than: null, only_if_start_after: '12:00' });
    expect(editTimelineEntry(tl, 'wake', 'offset_min', '')[0].offset_min).toBe(-300);
    expect(tl[0].label).toBe('Wake'); // input untouched
  });
  it('never removes the start entry; adds with fresh ids', () => {
    expect(removeTimelineEntry(tl, 'start')).toHaveLength(2);
    expect(removeTimelineEntry(tl, 'wake').map((e) => e.id)).toEqual(['start']);
    const added = addTimelineEntry(addTimelineEntry(tl), 'eve');
    expect(added.slice(2).map((e) => [e.id, e.day])).toEqual([['custom-1', 'race'], ['custom-2', 'eve']]);
  });
  it('removing an anchor re-anchors followers; after_min is editable', () => {
    const chain = [
      { id: 'a', label: 'A', day: 'race', offset_min: -60 },
      { id: 'b', label: 'B', day: 'race', after: 'a', after_min: 10 },
      { id: 'start', label: 'Start', day: 'race', offset_min: 0, is_start: true },
    ];
    expect(removeTimelineEntry(chain, 'a')[0]).toMatchObject({ id: 'b', after: null, offset_min: -50 });
    expect(editTimelineEntry(chain, 'b', 'after_min', '20')[1].after_min).toBe(20);
  });
  it('a timeline op replaces rather than merges field-wise', () => {
    const base = { athlete: 'a', planId: 'p', kind: 'timeline' };
    const q = mergeOp(mergeOp([], { ...base, payload: { timeline: [1] } }), { ...base, payload: { reset: true } });
    expect(q).toHaveLength(1);
    expect(q[0].payload).toEqual({ reset: true });
  });
});

describe('timeline edit queue', () => {
  beforeEach(() => {
    const mem = new Map();
    vi.stubGlobal('localStorage', {
      getItem: (k) => (mem.has(k) ? mem.get(k) : null),
      setItem: (k, v) => { mem.set(k, String(v)); },
      removeItem: (k) => { mem.delete(k); },
    });
  });
  it('keeps only the newest timeline edit per plan', () => {
    enqueue({ athlete: 'a', planId: 'p', kind: 'timeline', payload: { timeline: [{ id: 'x' }] } });
    enqueue({ athlete: 'a', planId: 'p', kind: 'timeline', payload: { timeline: [{ id: 'y' }] } });
    expect(loadQueue()).toHaveLength(1);
    expect(loadQueue()[0].payload.timeline[0].id).toBe('y');
  });
});

describe('overlay edit mode', () => {
  const plan = {
    id: 'p', date: '2026-10-17', name: 'Day 1', start_time: '15:15', active_tags: [], checked: [], sections: [],
    timeline_edited: true,
    timeline: VECTORS.timeline,
  };
  const rd = (extra = {}) => ({ open: true, status: 'ready', plan, tab: 'timeline', date: plan.date, name: 'Day 1', pending: 0, ...extra });
  it('shows lunch for a 15:15 start and read-only rows by default', () => {
    const html = renderRaceDayOverlay(rd());
    expect(html).toContain('Lunch');
    expect(html).toContain('12:15 PM');
    expect(html).toContain('data-a="raceday:tl-edit"');
    expect(html).not.toContain('data-form="raceday-tl"');
  });
  it('edit mode renders inputs, add, and reset when edited', () => {
    const html = renderRaceDayOverlay(rd({ editTimeline: true }));
    expect(html).toContain('data-form="raceday-tl"');
    expect(html).toContain('data-field="not_later_than"');
    expect(html).toContain('data-a="raceday:tl-add"');
    expect(html).toContain('data-a="raceday:tl-reset"');
    expect(renderRaceDayOverlay(rd({ editTimeline: true, plan: { ...plan, timeline_edited: false } }))).not.toContain('raceday:tl-reset');
  });
});
