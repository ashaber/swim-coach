import { describe, it, expect } from 'vitest';
import {
  isoWeekMonday, formatDuration, formatDistance, formatPace, splitPurpose,
  classifySession, sessionDisplay, pickCurrentAndNextWeek, daysUntil,
  priorityEvent, currentBlockIndex, longSwimLadder, sessionsByDay,
} from '../../src/plan.js';

describe('isoWeekMonday', () => {
  it('matches the known real data: 2026-W28 starts Monday Jul 6 2026', () => {
    const monday = isoWeekMonday('2026-W28');
    expect(monday.getFullYear()).toBe(2026);
    expect(monday.getMonth()).toBe(6); // 0-indexed: July
    expect(monday.getDate()).toBe(6);
    expect(monday.getDay()).toBe(1); // Monday
  });

  it('2026-W29 starts the following Monday, Jul 13', () => {
    const monday = isoWeekMonday('2026-W29');
    expect(monday.getDate()).toBe(13);
  });
});

describe('formatDuration', () => {
  it('formats sub-hour minutes plainly', () => {
    expect(formatDuration(40)).toBe('40 min');
  });
  it('formats whole hours', () => {
    expect(formatDuration(300)).toBe('5 h');
  });
  it('formats hours with remainder minutes', () => {
    expect(formatDuration(125)).toBe('2 h 5 min');
  });
});

describe('formatDistance', () => {
  it('adds thousands separators and a unit', () => {
    expect(formatDistance(15000)).toBe('15,000 m');
  });
  it('returns null for null input (no distance field)', () => {
    expect(formatDistance(null)).toBeNull();
  });
});

describe('formatPace', () => {
  it('formats seconds as m:ss', () => {
    expect(formatPace(90)).toBe('1:30');
    expect(formatPace(88)).toBe('1:28');
  });
  it('returns null for missing pace', () => {
    expect(formatPace(null)).toBeNull();
  });
});

describe('splitPurpose', () => {
  it('splits on the em dash convention', () => {
    const { title, detail } = splitPurpose('dryland shoulder strength — moderate (2 days before)');
    expect(title).toBe('dryland shoulder strength');
    expect(detail).toBe('moderate (2 days before)');
  });
  it('falls back to the whole string when there is no dash', () => {
    const { title, detail } = splitPurpose('full rest or gentle mobility');
    expect(title).toBe('full rest or gentle mobility');
    expect(detail).toBeNull();
  });
});

describe('classifySession', () => {
  it('flags an explicit (B race) marker', () => {
    const session = { purpose: 'Bear Lake Monster 10K (B race) — dress rehearsal', sport: 'swim_ow', duration_min: 180 };
    expect(classifySession(session)).toEqual({ highlight: true, tag: 'B Race' });
  });
  it('flags a long open-water swim as a milestone even without a race tag', () => {
    const session = { purpose: 'Lucky Peak 5-HOUR swim — fueling rehearsal', sport: 'swim_ow', duration_min: 300 };
    expect(classifySession(session)).toEqual({ highlight: true, tag: 'Milestone' });
  });
  it('does not flag an ordinary pool session', () => {
    const session = { purpose: 'coached USMS pool — content assigned by coach', sport: 'swim_pool', duration_min: 90 };
    expect(classifySession(session)).toEqual({ highlight: false, tag: null });
  });
});

describe('sessionDisplay', () => {
  it('strips the race-tag parenthetical out of the title', () => {
    const session = { purpose: 'Bear Lake Monster 10K (B race) — dress rehearsal, negative-split', structure: null };
    const { title, detail } = sessionDisplay(session);
    expect(title).toBe('Bear Lake Monster 10K');
    expect(detail).toBe('dress rehearsal, negative-split');
  });
  it('prefers structure over the post-dash detail when both exist', () => {
    const session = { purpose: 'Lucky Peak 5-HOUR swim — fueling rehearsal', structure: 'Feed every 20-30 min.' };
    const { detail } = sessionDisplay(session);
    expect(detail).toBe('fueling rehearsal');
  });
});

describe('pickCurrentAndNextWeek', () => {
  const weeks = [
    { iso_week: '2026-W28', sessions: [] },
    { iso_week: '2026-W29', sessions: [] },
  ];

  it('picks W28 as current when now is mid-week-27 (before W28 starts)', () => {
    const { current, next } = pickCurrentAndNextWeek(weeks, new Date(2026, 6, 5));
    expect(current.iso_week).toBe('2026-W28');
    expect(next.iso_week).toBe('2026-W29');
  });

  it('picks W29 as current once W28 has fully elapsed', () => {
    const { current, next } = pickCurrentAndNextWeek(weeks, new Date(2026, 6, 15));
    expect(current.iso_week).toBe('2026-W29');
    expect(next).toBeNull();
  });

  it('returns nulls for an empty week list', () => {
    expect(pickCurrentAndNextWeek([])).toEqual({ current: null, next: null });
  });
});

describe('daysUntil', () => {
  it('counts whole days to a future date', () => {
    const now = new Date(2026, 6, 5);
    const event = new Date(2026, 6, 15);
    expect(daysUntil(event, now)).toBe(10);
  });
  it('floors at 0 for a past date', () => {
    const now = new Date(2026, 6, 15);
    const event = new Date(2026, 6, 5);
    expect(daysUntil(event, now)).toBe(0);
  });
});

describe('priorityEvent', () => {
  it('prefers the A-priority event over others', () => {
    const events = [
      { name: 'B race', event_date: '2026-07-18', priority: 'B' },
      { name: 'A race', event_date: '2026-09-18', priority: 'A' },
    ];
    expect(priorityEvent(events).name).toBe('A race');
  });
  it('falls back to the earliest event when none is A', () => {
    const events = [
      { name: 'Later', event_date: '2026-09-18', priority: 'C' },
      { name: 'Earlier', event_date: '2026-07-18', priority: 'C' },
    ];
    expect(priorityEvent(events).name).toBe('Earlier');
  });
  it('returns null for no events', () => {
    expect(priorityEvent([])).toBeNull();
  });
});

describe('currentBlockIndex', () => {
  const blocks = [
    { name: 'base', start_date: '2026-07-06', end_date: '2026-08-02' },
    { name: 'build', start_date: '2026-08-03', end_date: '2026-08-16' },
  ];
  it('finds the block containing now', () => {
    expect(currentBlockIndex(blocks, new Date(2026, 6, 10))).toBe(0);
    expect(currentBlockIndex(blocks, new Date(2026, 7, 10))).toBe(1);
  });
  it('falls back to the first block when now is before the plan', () => {
    expect(currentBlockIndex(blocks, new Date(2026, 5, 1))).toBe(0);
  });
  it('falls back to the last block when now is after the plan', () => {
    expect(currentBlockIndex(blocks, new Date(2026, 11, 1))).toBe(1);
  });
});

describe('sessionsByDay', () => {
  it('buckets sessions into the correct weekday', () => {
    const week = {
      iso_week: '2026-W28',
      sessions: [
        { date: '2026-07-06', sport: 'swim_pool' },
        { date: '2026-07-09', sport: 'swim_ow' },
      ],
    };
    const days = sessionsByDay(week);
    expect(days).toHaveLength(7);
    expect(days[0].dow).toBe('Mon');
    expect(days[0].sessions).toHaveLength(1);
    expect(days[3].dow).toBe('Thu');
    expect(days[3].sessions).toHaveLength(1);
    expect(days[1].sessions).toHaveLength(0);
  });
});

describe('longSwimLadder', () => {
  it('derives the biggest swim, a peak estimate, and the event from real-shaped data', () => {
    const weeks = [
      {
        sessions: [
          { sport: 'swim_ow', distance_m: 15000, duration_min: 300, date: '2026-07-09' },
          { sport: 'swim_ow', distance_m: 1500, duration_min: 30, date: '2026-07-16' },
        ],
      },
    ];
    const macro = {
      blocks: [
        { name: 'base', start_date: '2026-07-06', end_date: '2026-08-02' },
        { name: 'build', start_date: '2026-08-03', end_date: '2026-08-16' },
        { name: 'peak', start_date: '2026-08-17', end_date: '2026-08-30' },
        { name: 'taper', start_date: '2026-08-31', end_date: '2026-09-13' },
      ],
    };
    const event = { name: 'UltraSwim 33.3 Greece', distance_m: 33300, event_date: '2026-09-18' };

    const rungs = longSwimLadder(weeks, macro, event);
    expect(rungs[0].km).toBe('15');
    expect(rungs.some((r) => r.connective === 'build-ups')).toBe(true);
    expect(rungs.at(-1).final).toBe(true);
    expect(rungs.at(-1).km).toBe('33.3');
  });

  it('returns an empty ladder with no swims, macro, or event', () => {
    expect(longSwimLadder([], null, null)).toEqual([]);
  });
});
