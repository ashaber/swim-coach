import { describe, it, expect } from 'vitest';
import {
  workoutDateKey, findWorkoutForSession, isSessionSkipped, buildHistoryFeed,
  SKIP_EXEMPT_SPORTS,
} from '../../src/history.js';

const NOW = new Date(2026, 7, 20); // Thu 2026-08-20, local time

function session(overrides = {}) {
  return {
    id: 's-1', date: '2026-08-18', sport: 'swim_pool', source: 'ai_coach',
    duration_min: 60, distance_m: 2000, intensity: {}, purpose: 'Threshold set',
    structure: null, structured: null, status: 'planned', ...overrides,
  };
}

function workout(overrides = {}) {
  return {
    id: 'w-1', date: '2026-08-18', sport: 'swim_pool', source: 'fit',
    distance_m: 2050, duration_min: 61, rpe: 6, planned_session_id: null, ...overrides,
  };
}

describe('workoutDateKey', () => {
  it('takes the date half of a full ISO timestamp', () => {
    expect(workoutDateKey({ date: '2026-08-18T06:30:00' })).toBe('2026-08-18');
  });
  it('passes a plain date through unchanged', () => {
    expect(workoutDateKey({ date: '2026-08-18' })).toBe('2026-08-18');
  });
  it('returns null for a missing date rather than throwing', () => {
    expect(workoutDateKey({})).toBeNull();
    expect(workoutDateKey(null)).toBeNull();
  });
});

describe('findWorkoutForSession', () => {
  it('matches on planned_session_id first -- the explicit link', () => {
    const linked = workout({ id: 'w-linked', date: '2026-08-19', sport: 'swim_ow', planned_session_id: 's-1' });
    // Deliberately a different date AND sport: the explicit link wins over
    // any heuristic, because the athlete (or the coach) said so.
    expect(findWorkoutForSession(session(), [linked])).toBe(linked);
  });

  it('falls back to same date + sport when no link is populated', () => {
    // The .fit auto-sync path threads planned_session_id through from the
    // parse draft but never computes the match, so it is generally null --
    // without this fallback every synced workout would look like a skip.
    const w = workout();
    expect(findWorkoutForSession(session(), [w])).toBe(w);
  });

  it('does not match a different sport on the same date', () => {
    const w = workout({ sport: 'strength' });
    expect(findWorkoutForSession(session(), [w])).toBeNull();
  });

  it('does not match the same sport on a different date', () => {
    const w = workout({ date: '2026-08-17' });
    expect(findWorkoutForSession(session(), [w])).toBeNull();
  });

  it('will not reuse a workout already explicitly claimed by another session', () => {
    // Same date+sport, but this workout is explicitly linked elsewhere.
    // Counting it here would let one workout satisfy two planned sessions
    // and hide a genuine skip.
    const claimed = workout({ planned_session_id: 's-other' });
    expect(findWorkoutForSession(session(), [claimed])).toBeNull();
  });

  it('handles workouts carrying a full ISO timestamp rather than a plain date', () => {
    const w = workout({ date: '2026-08-18T06:30:00' });
    expect(findWorkoutForSession(session(), [w])).toBe(w);
  });

  it('returns null for an empty workout list', () => {
    expect(findWorkoutForSession(session(), [])).toBeNull();
  });
});

describe('isSessionSkipped', () => {
  it('is true for a past session with no matching workout', () => {
    expect(isSessionSkipped(session({ date: '2026-08-18' }), [], NOW)).toBe(true);
  });

  it('is false when a matching workout exists', () => {
    expect(isSessionSkipped(session({ date: '2026-08-18' }), [workout()], NOW)).toBe(false);
  });

  it("is false for today's session -- the day isn't over yet", () => {
    expect(isSessionSkipped(session({ date: '2026-08-20' }), [], NOW)).toBe(false);
  });

  it('is false for a future session', () => {
    expect(isSessionSkipped(session({ date: '2026-08-25' }), [], NOW)).toBe(false);
  });

  it('never marks a recovery/mobility day as skipped', () => {
    // Recovery is modeled as a short mobility session because the Session
    // model can't represent a 0-minute day off (see plan.py's
    // RECOVERY_SESSION_MIN). Nobody logs a rest day, so counting these as
    // skips would bury the real ones in noise.
    expect(SKIP_EXEMPT_SPORTS.has('recovery')).toBe(true);
    expect(isSessionSkipped(session({ date: '2026-08-18', sport: 'recovery' }), [], NOW)).toBe(false);
  });

  it('still flags a missed coached pool session -- those are real sessions', () => {
    const s = session({ date: '2026-08-18', sport: 'swim_pool', source: 'pool_coach' });
    expect(isSessionSkipped(s, [], NOW)).toBe(true);
  });

  it('trusts an explicit completed status even with no workout on file', () => {
    // Session.status is only reliably written by the chat log-workout path,
    // so it is a hint, not the source of truth -- but when it DOES say
    // completed, contradicting it would be wrong.
    const s = session({ date: '2026-08-18', status: 'completed' });
    expect(isSessionSkipped(s, [], NOW)).toBe(false);
  });

  it('does not treat a replaced session as skipped', () => {
    const s = session({ date: '2026-08-18', status: 'replaced' });
    expect(isSessionSkipped(s, [], NOW)).toBe(false);
  });
});

describe('buildHistoryFeed', () => {
  const weeks = [
    {
      iso_week: '2026-W34',
      sessions: [
        session({ id: 's-done', date: '2026-08-17', sport: 'swim_pool' }),
        session({ id: 's-missed', date: '2026-08-18', sport: 'strength', purpose: 'Dryland shoulder strength' }),
        session({ id: 's-today', date: '2026-08-20', sport: 'swim_ow' }),
        session({ id: 's-future', date: '2026-08-22', sport: 'swim_pool' }),
        session({ id: 's-rest', date: '2026-08-19', sport: 'recovery' }),
      ],
    },
  ];
  const workouts = [
    workout({ id: 'w-done', date: '2026-08-17', sport: 'swim_pool' }),
    workout({ id: 'w-unplanned', date: '2026-08-16', sport: 'cross_train' }),
  ];

  it('interleaves completed workouts and skipped sessions, newest first', () => {
    const feed = buildHistoryFeed({ weeks, workouts, now: NOW });
    expect(feed.map((i) => [i.kind, i.date])).toEqual([
      ['skipped', '2026-08-18'],
      ['completed', '2026-08-17'],
      ['completed', '2026-08-16'],
    ]);
  });

  it('includes a completed workout that was never planned', () => {
    const feed = buildHistoryFeed({ weeks, workouts, now: NOW });
    const ids = feed.filter((i) => i.kind === 'completed').map((i) => i.workout.id);
    expect(ids).toContain('w-unplanned');
  });

  it('excludes future and same-day sessions, and rest days', () => {
    const feed = buildHistoryFeed({ weeks, workouts, now: NOW });
    const skippedIds = feed.filter((i) => i.kind === 'skipped').map((i) => i.session.id);
    expect(skippedIds).toEqual(['s-missed']);
  });

  it('carries the planned session through so the UI can show what was missed', () => {
    const feed = buildHistoryFeed({ weeks, workouts, now: NOW });
    const skipped = feed.find((i) => i.kind === 'skipped');
    expect(skipped.session.purpose).toBe('Dryland shoulder strength');
    expect(skipped.session.sport).toBe('strength');
  });

  it('puts the completed item first when both land on the same date', () => {
    const sameDay = [{
      iso_week: '2026-W34',
      sessions: [
        session({ id: 's-a', date: '2026-08-17', sport: 'swim_pool' }),
        session({ id: 's-b', date: '2026-08-17', sport: 'strength' }),
      ],
    }];
    const feed = buildHistoryFeed({ weeks: sameDay, workouts: [workout({ date: '2026-08-17' })], now: NOW });
    expect(feed.map((i) => i.kind)).toEqual(['completed', 'skipped']);
  });

  it('returns an empty feed for no data, without throwing', () => {
    expect(buildHistoryFeed({ weeks: [], workouts: [], now: NOW })).toEqual([]);
    expect(buildHistoryFeed({ weeks: null, workouts: null, now: NOW })).toEqual([]);
  });

  it('works with only workouts and no plan at all', () => {
    const feed = buildHistoryFeed({ weeks: [], workouts, now: NOW });
    expect(feed).toHaveLength(2);
    expect(feed.every((i) => i.kind === 'completed')).toBe(true);
  });

  it('gives every item a stable key so rendering can be keyed on it', () => {
    const feed = buildHistoryFeed({ weeks, workouts, now: NOW });
    const keys = feed.map((i) => i.key);
    expect(new Set(keys).size).toBe(keys.length);
    expect(keys.every((k) => typeof k === 'string' && k.length > 0)).toBe(true);
  });
});
