import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  groupRaceWeekItems, raceWeekSummary, visibleSections, planProgress, allTags, applyChecked, removeItem, addItem, newItemId, checklistView, toggleTag,
  timelineClock, timelinePosition, formatClockTime, mergeOp, loadQueue, enqueue, saveQueue,
  loadOpenOverlay, saveOpenOverlay,
} from '../../src/raceDay.js';
import { renderApp, renderRaceDayOverlay } from '../../src/views.js';

const PLAN = {
  id: 'p1',
  date: '2026-10-17',
  name: 'Day 1',
  start_time: '09:00',
  active_tags: [],
  checked: ['helmet'],
  sections: [
    { id: 'kit', title: 'Kit', items: [
      { id: 'helmet', text: 'Helmet', tags: [], default_checked: false },
      { id: 'covers', text: 'Shoe covers', tags: ['cold', 'wet'], default_checked: false },
    ] },
    { id: 'bike', title: 'Bike prep', items: [
      { id: 'wheels', text: 'Swap wheels', tags: ['mud'], default_checked: false },
    ] },
  ],
  timeline: [
    { id: 'dinner', label: 'Dinner', day: 'eve', at: '19:00', offset_min: null, is_start: false },
    { id: 'wake', label: 'Wake up', day: 'race', at: null, offset_min: -315, is_start: false },
    { id: 'start', label: 'Start', day: 'race', at: null, offset_min: 0, is_start: true },
    { id: 'cool', label: 'Cooldown', day: 'race', at: null, offset_min: 60, is_start: false },
  ],
};

describe('race-week grouping', () => {
  const keys = ['2026-10-12', '2026-10-13', '2026-10-14'];
  const items = [
    { id: 'c', date: '2026-10-20', done: false },
    { id: 'a', date: '2026-10-13', done: true },
    { id: 'b', date: '2026-10-12', done: false },
  ];
  it('groups by day in date order and puts out-of-week items in outside', () => {
    const { byDay, outside } = groupRaceWeekItems(items, keys);
    expect(byDay['2026-10-12'].map((i) => i.id)).toEqual(['b']);
    expect(byDay['2026-10-13'].map((i) => i.id)).toEqual(['a']);
    expect(byDay['2026-10-14']).toEqual([]);
    expect(outside.map((i) => i.id)).toEqual(['c']);
  });
  it('summarises counts and tolerates a missing list', () => {
    expect(raceWeekSummary(items)).toEqual({ total: 3, done: 1 });
    expect(raceWeekSummary(undefined)).toEqual({ total: 0, done: 0 });
  });
});

describe('weather tag filtering and progress', () => {
  it('shows only untagged items until a matching tag is active', () => {
    expect(visibleSections(PLAN).map((s) => s.title)).toEqual(['Kit']);
    const wet = toggleTag(PLAN, 'wet');
    expect(visibleSections(wet)[0].items.map((i) => i.id)).toEqual(['helmet', 'covers']);
    const mud = toggleTag(wet, 'mud');
    expect(visibleSections(mud).map((s) => s.title)).toEqual(['Kit', 'Bike prep']);
    expect(toggleTag(mud, 'mud').active_tags).toEqual(['wet']);
  });
  it('counts progress per section over visible items only', () => {
    const wet = toggleTag(PLAN, 'wet');
    expect(visibleSections(wet)[0]).toMatchObject({ done: 1, total: 2 });
    expect(planProgress(wet)).toEqual({ done: 1, total: 2 });
    expect(planProgress(applyChecked(wet, 'covers', true))).toEqual({ done: 2, total: 2 });
    expect(planProgress(applyChecked(wet, 'helmet', false))).toEqual({ done: 0, total: 2 });
  });
  it('lists every tag, sorted', () => {
    expect(allTags(PLAN)).toEqual(['cold', 'mud', 'wet']);
  });
});

describe('completed partition', () => {
  const wet = toggleTag(PLAN, 'wet');
  it('moves checked items to completed, remembering their section', () => {
    const view = checklistView(wet);
    expect(view.sections.map((s) => [s.title, s.items.map((i) => i.id)])).toEqual([['Kit', ['covers']]]);
    expect(view.sections[0]).toMatchObject({ done: 1, total: 2 }); // header still counts the whole section
    expect(view.completed.map((i) => [i.id, i.sectionTitle])).toEqual([['helmet', 'Kit']]);
  });
  it('unchecking restores the item to its original section, in its original place', () => {
    const view = checklistView(applyChecked(wet, 'helmet', false));
    expect(view.sections[0].items.map((i) => i.id)).toEqual(['helmet', 'covers']);
    expect(view.completed).toEqual([]);
  });
  it('drops a section that has nothing left to do, but keeps its items under completed', () => {
    const view = checklistView(applyChecked(PLAN, 'helmet', true));
    expect(view.sections).toEqual([]);
    expect(view.completed.map((i) => i.id)).toEqual(['helmet']);
  });
  it('renders a Completed section below the open ones with a labelled origin', () => {
    const html = renderRaceDayOverlay({
      open: true, status: 'ready', plan: wet, tab: 'list', date: '2026-10-17', name: 'Day 1', pending: 0,
    });
    expect(html.indexOf('Completed')).toBeGreaterThan(html.indexOf('Shoe covers'));
    expect(html).toContain('class="rd-origin">Kit<');
  });
});

describe('adding an item', () => {
  it('creates a Misc section at the top on first add, then reuses it', () => {
    const one = addItem(PLAN, 'u1', '  Spare tube ');
    expect(one.sections.map((s) => s.title)).toEqual(['Misc', 'Kit', 'Bike prep']);
    expect(one.sections[0].items).toEqual([{ id: 'u1', text: 'Spare tube', tags: [], default_checked: false }]);
    const two = addItem(one, 'u2', 'Gels');
    expect(two.sections.map((s) => s.title)).toEqual(['Misc', 'Kit', 'Bike prep']);
    expect(two.sections[0].items.map((i) => i.id)).toEqual(['u1', 'u2']);
    expect(PLAN.sections).toHaveLength(2); // input not mutated
  });
  it('shows Misc first in the rendered list, and an unchecked Misc item stays out of Completed', () => {
    const view = checklistView(addItem(PLAN, 'u1', 'Gels'));
    expect(view.sections.map((s) => s.title)).toEqual(['Misc']);
    expect(view.completed.map((i) => i.id)).toEqual(['helmet']);
  });
  it('a checked Misc item goes to Completed and returns to Misc when unchecked', () => {
    const checked = applyChecked(addItem(PLAN, 'u1', 'Gels'), 'u1', true);
    expect(checklistView(checked).completed.map((i) => [i.id, i.sectionTitle])).toContainEqual(['u1', 'Misc']);
    expect(checklistView(applyChecked(checked, 'u1', false)).sections[0].items.map((i) => i.id)).toEqual(['u1']);
  });
  it('ignores blank or over-long text and replays of the same id', () => {
    expect(addItem(PLAN, 'u1', '   ')).toBeNull();
    expect(addItem(PLAN, 'u1', 'x'.repeat(201))).toBeNull();
    const once = addItem(PLAN, 'u1', 'Gels');
    expect(addItem(once, 'u1', 'Gels').sections[0].items).toHaveLength(1);
  });
  it('generates distinct ids', () => {
    expect(newItemId()).not.toBe(newItemId());
  });
  it('renders the add entry with the draft text and an Add button', () => {
    const html = renderRaceDayOverlay({
      open: true, status: 'ready', plan: PLAN, tab: 'list', date: '2026-10-17', name: 'Day 1', pending: 0, addDraft: 'Gels "x"',
    });
    expect(html).toContain('id="raceday-add-input"');
    expect(html).toContain('value="Gels &quot;x&quot;"');
    expect(html).toContain('data-a="raceday:add"');
  });
});

describe('removing an item from the plan', () => {
  it('drops it from its section and the checked list without touching other items', () => {
    const next = removeItem(PLAN, 'helmet');
    expect(next.sections[0].items.map((i) => i.id)).toEqual(['covers']);
    expect(next.checked).toEqual([]);
    expect(next.sections[1]).toEqual(PLAN.sections[1]);
    expect(PLAN.sections[0].items).toHaveLength(2); // input not mutated
  });
  it('is a no-op for an unknown id', () => {
    expect(removeItem(PLAN, 'nope').sections[0].items).toHaveLength(2);
  });
});

describe('timeline clock', () => {
  it('computes clock times from the start time, eve entries at their own clock time', () => {
    const clock = timelineClock(PLAN);
    expect(clock.map((e) => [e.id, e.time])).toEqual([
      ['dinner', '19:00'], ['wake', '03:45'], ['start', '09:00'], ['cool', '10:00'],
    ]);
  });
  it('shifts every race entry when the start time changes, and wraps past midnight', () => {
    const shifted = timelineClock({ ...PLAN, start_time: '10:30' });
    expect(shifted.filter((e) => e.day === 'race').map((e) => e.time)).toEqual(['05:15', '10:30', '11:30']);
    expect(shifted[0].time).toBe('19:00');
    expect(timelineClock({ ...PLAN, start_time: '03:00' }).find((e) => e.id === 'wake').time).toBe('21:45');
  });
  it('has no race times without a start time', () => {
    const clock = timelineClock({ ...PLAN, start_time: null });
    expect(clock.find((e) => e.id === 'wake').time).toBeNull();
    expect(clock.find((e) => e.id === 'dinner').time).toBe('19:00');
  });
  it('formats 12-hour', () => {
    expect(formatClockTime('00:05')).toBe('12:05 AM');
    expect(formatClockTime('13:30')).toBe('1:30 PM');
  });
  it('highlights current and next only from the evening before through race day', () => {
    const clock = timelineClock(PLAN);
    const at = (y, m, d, h, min) => new Date(y, m - 1, d, h, min);
    expect(timelinePosition(clock, '2026-10-17', at(2026, 10, 17, 8, 0))).toEqual({ currentId: 'wake', nextId: 'start' });
    expect(timelinePosition(clock, '2026-10-17', at(2026, 10, 16, 19, 30))).toEqual({ currentId: 'dinner', nextId: 'wake' });
    expect(timelinePosition(clock, '2026-10-17', at(2026, 10, 17, 11, 0))).toEqual({ currentId: 'cool', nextId: null });
    expect(timelinePosition(clock, '2026-10-17', at(2026, 10, 14, 12, 0))).toEqual({ currentId: null, nextId: null });
  });
});

describe('offline queue', () => {
  beforeEach(() => {
    const mem = new Map();
    vi.stubGlobal('localStorage', {
      getItem: (k) => (mem.has(k) ? mem.get(k) : null),
      setItem: (k, v) => { mem.set(k, String(v)); },
      removeItem: (k) => { mem.delete(k); },
    });
  });
  it('merges ops for the same plan+kind with later values winning', () => {
    let q = mergeOp([], { athlete: 'a', planId: 'p1', kind: 'items', payload: { x: true, y: true } });
    q = mergeOp(q, { athlete: 'a', planId: 'p1', kind: 'items', payload: { x: false } });
    q = mergeOp(q, { athlete: 'a', planId: 'p1', kind: 'meta', payload: { start_time: '09:00' } });
    q = mergeOp(q, { athlete: 'a', planId: 'p2', kind: 'items', payload: { z: true } });
    expect(q).toHaveLength(3);
    expect(q[0].payload).toEqual({ x: false, y: true });
  });
  it('accumulates checklist edits for a plan instead of overwriting them', () => {
    let q = mergeOp([], { athlete: 'a', planId: 'p1', kind: 'checklist', payload: { remove: ['a'] } });
    q = mergeOp(q, { athlete: 'a', planId: 'p1', kind: 'checklist', payload: { remove: ['b', 'a'] } });
    expect(q).toHaveLength(1);
    expect(q[0].payload).toEqual({ remove: ['a', 'b'] });
    q = mergeOp(q, { athlete: 'a', planId: 'p1', kind: 'checklist', payload: { add: [{ id: 'u1', text: 'Gels' }] } });
    q = mergeOp(q, { athlete: 'a', planId: 'p1', kind: 'checklist', payload: { add: [{ id: 'u1', text: 'Gels' }, { id: 'u2', text: 'Tube' }] } });
    expect(q[0].payload).toEqual({ remove: ['a', 'b'], add: [{ id: 'u1', text: 'Gels' }, { id: 'u2', text: 'Tube' }] });
  });
  it('does not mutate its input', () => {
    const base = [{ athlete: 'a', planId: 'p1', kind: 'items', payload: { x: true } }];
    mergeOp(base, { athlete: 'a', planId: 'p1', kind: 'items', payload: { x: false } });
    expect(base[0].payload).toEqual({ x: true });
  });
  it('persists to localStorage and clears the key when emptied', () => {
    enqueue({ athlete: 'a', planId: 'p1', kind: 'items', payload: { x: true } });
    expect(loadQueue()).toHaveLength(1);
    saveQueue([]);
    expect(loadQueue()).toEqual([]);
    expect(localStorage.getItem('swimcoach_raceday_queue')).toBeNull();
  });
  it('remembers the open overlay per athlete', () => {
    saveOpenOverlay({ athlete: 'a', date: '2026-10-17', sessionId: 's', name: 'Day 1', tab: 'list' });
    expect(loadOpenOverlay('a').date).toBe('2026-10-17');
    expect(loadOpenOverlay('b')).toBeNull();
    saveOpenOverlay(null);
    expect(loadOpenOverlay('a')).toBeNull();
  });
});

describe('renderRaceDayOverlay', () => {
  const rd = (over = {}) => ({
    open: true, status: 'ready', plan: PLAN, tab: 'list', date: '2026-10-17', name: 'Day 1', pending: 0, ...over,
  });
  it('renders nothing when closed', () => {
    expect(renderRaceDayOverlay({ open: false })).toBe('');
  });
  it('shows sections, progress, tag chips, and only untagged items by default', () => {
    const html = renderRaceDayOverlay(rd());
    expect(html).toContain('Kit');
    expect(html).toContain('1/1');
    expect(html).toContain('data-tag="wet"');
    expect(html).not.toContain('Shoe covers');
    expect(renderRaceDayOverlay(rd({ plan: toggleTag(PLAN, 'wet') }))).toContain('Shoe covers');
  });
  it('escapes item text and shows an offline notice plus pending sync', () => {
    const evil = { ...PLAN, sections: [{ id: 's', title: '<b>x</b>', items: [{ id: 'i', text: '<img src=x>', tags: [] }] }] };
    const html = renderRaceDayOverlay(rd({ plan: evil }), false);
    expect(html).not.toContain('<img src=x>');
    expect(html).toContain('Offline');
  });
  it('timeline tab shows clock times, the eve marker, and the start row', () => {
    const html = renderRaceDayOverlay(rd({ tab: 'timeline' }), true, new Date(2026, 9, 17, 8, 0));
    expect(html).toContain('3:45 AM');
    expect(html).toContain('evening before');
    expect(html).toContain('rd-tl-row start');
    expect(html).toContain('rd-tl-row current');
  });
  it('renders a separate, labelled remove button per item', () => {
    const html = renderRaceDayOverlay(rd());
    expect(html).toContain('data-a="raceday:remove" data-id="helmet"');
    expect(html).toContain('aria-label="Remove Helmet"');
  });
  it('shows an error message when the plan failed to load', () => {
    expect(renderRaceDayOverlay({ open: true, status: 'error', error: 'no template yet', date: '2026-10-17' })).toContain('no template yet');
  });
});

describe('week view race-week strips and race tile button', () => {
  const week = {
    iso_week: '2099-W02', meso_block: 'taper', focus: 'race', target_volume_m: 0,
    sessions: [{
      id: 'race1', date: '2099-01-10', sport: 'bike', source: 'ai_coach', duration_min: 45, distance_m: null,
      intensity: {}, purpose: 'Race day 1', kind: 'race', status: 'planned',
    }],
    race_week_checklist: [
      { id: 'i1', date: '2099-01-09', category: 'bike', label: 'Clean bike', done: true },
      { id: 'i2', date: '2099-01-12', category: 'gear', label: 'Pack kit', done: false },
    ],
  };
  const data = { athlete: { name: 'A' }, events: [], macro: { blocks: [] }, weeks: [week] };
  it('renders a per-day strip, a summary, and a toggle action per item', () => {
    const html = renderApp(data, null);
    expect(html).toContain('Race week: 2 items, 1 done');
    expect(html).toContain('class="rw-strip"');
    expect(html).toContain('data-a="raceweek:toggle" data-week="2099-W02" data-id="i1"');
    expect(html).toContain('rw-chip rw-chip-bike done');
  });
  it('gives only race sessions a Checklist button', () => {
    expect(renderApp(data, null)).toContain('data-a="raceday:open" data-id="race1" data-date="2099-01-10"');
    const plain = { ...week, sessions: [{ ...week.sessions[0], kind: 'workout' }] };
    expect(renderApp({ ...data, weeks: [plain] }, null)).not.toContain('raceday:open');
  });
});
