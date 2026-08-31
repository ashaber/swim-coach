import { describe, it, expect, beforeEach } from 'vitest';
import { loadLastSeen, saveLastSeen, countUnread } from '../../src/unread.js';

// Fixed "now"-ish timestamps, same plain-constant convention as
// history.test.js's own NOW -- countUnread takes `lastSeen` as an explicit
// argument, so no fake-timers/global Date patching is needed here.
const LAST_SEEN = '2026-08-20T12:00:00Z';
const BEFORE_LAST_SEEN = '2026-08-20T09:00:00Z';
const AFTER_LAST_SEEN = '2026-08-20T15:00:00Z';

function entry(overrides = {}) {
  return {
    id: 'f1', type: 'question', source: 'athlete', body: 'question?',
    created_at: BEFORE_LAST_SEEN, coach_reply_at: null, ...overrides,
  };
}

describe('countUnread', () => {
  it('coach role counts entries created after lastSeen', () => {
    const entries = [
      entry({ id: 'f1', created_at: BEFORE_LAST_SEEN }),
      entry({ id: 'f2', created_at: AFTER_LAST_SEEN }),
    ];
    expect(countUnread(entries, LAST_SEEN, 'coach')).toBe(1);
  });

  it('athlete role counts entries whose coach_reply_at is after lastSeen, ignoring created_at', () => {
    const entries = [
      // Asked recently but never answered -- not "new" to the athlete.
      entry({ id: 'f1', created_at: AFTER_LAST_SEEN, coach_reply_at: null }),
      // Asked long ago, replied to just now -- new to the athlete.
      entry({ id: 'f2', created_at: BEFORE_LAST_SEEN, coach_reply_at: AFTER_LAST_SEEN }),
      // Replied to before lastSeen -- already seen.
      entry({ id: 'f3', created_at: BEFORE_LAST_SEEN, coach_reply_at: BEFORE_LAST_SEEN }),
    ];
    expect(countUnread(entries, LAST_SEEN, 'athlete')).toBe(1);
  });

  it('treats a null lastSeen as "never seen anything" -- every dated entry counts', () => {
    const entries = [entry({ id: 'f1', created_at: BEFORE_LAST_SEEN })];
    expect(countUnread(entries, null, 'coach')).toBe(1);
  });

  it('skips entries missing the relevant field rather than counting or throwing', () => {
    const entries = [
      entry({ id: 'f1', coach_reply_at: undefined }),
      entry({ id: 'f2', coach_reply_at: null }),
    ];
    expect(countUnread(entries, LAST_SEEN, 'athlete')).toBe(0);
  });

  it('skips malformed timestamps rather than throwing', () => {
    const entries = [entry({ id: 'f1', created_at: 'not-a-date' })];
    expect(() => countUnread(entries, LAST_SEEN, 'coach')).not.toThrow();
    expect(countUnread(entries, LAST_SEEN, 'coach')).toBe(0);
  });

  it('returns 0 for an empty or missing entries list', () => {
    expect(countUnread([], LAST_SEEN, 'coach')).toBe(0);
    expect(countUnread(undefined, LAST_SEEN, 'coach')).toBe(0);
  });
});

function makeFakeStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  };
}

describe('loadLastSeen / saveLastSeen', () => {
  let storage;
  beforeEach(() => {
    storage = makeFakeStorage();
  });

  it('returns null before anything has ever been saved for a role', () => {
    expect(loadLastSeen('athlete', storage)).toBeNull();
  });

  it('round-trips a saved timestamp through storage, scoped per role', () => {
    saveLastSeen('athlete', '2026-08-20T12:00:00Z', storage);
    saveLastSeen('coach', '2026-08-21T09:00:00Z', storage);
    expect(loadLastSeen('athlete', storage)).toBe('2026-08-20T12:00:00Z');
    expect(loadLastSeen('coach', storage)).toBe('2026-08-21T09:00:00Z');
  });

  it('defaults to the real current time when no timestamp is given', () => {
    const before = Date.now();
    const saved = saveLastSeen('athlete', undefined, storage);
    const after = Date.now();
    const savedMs = Date.parse(saved);
    expect(savedMs).toBeGreaterThanOrEqual(before);
    expect(savedMs).toBeLessThanOrEqual(after);
    expect(loadLastSeen('athlete', storage)).toBe(saved);
  });

  it('recovers to null when storage throws (e.g. private-mode/quota)', () => {
    const throwingStorage = {
      getItem: () => { throw new Error('nope'); },
      setItem: () => { throw new Error('nope'); },
    };
    expect(loadLastSeen('athlete', throwingStorage)).toBeNull();
    expect(() => saveLastSeen('athlete', '2026-08-20T12:00:00Z', throwingStorage)).not.toThrow();
  });
});
