import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  groupRaceWeekItems, raceWeekSummary, visibleSections, planProgress, allTags, applyChecked, toggleTag,
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
