import { describe, it, expect } from 'vitest';
import {
  createThreadState, sortThread, mergeThreadMessages, threadCursor, shouldPoll,
  loadCachedThread, saveCachedThread, applyThreadPayload, CONVERSATION_POLL_INTERVAL_MS,
} from '../../src/conversation.js';
import { countUnreadThread, loadThreadLastSeen, saveThreadLastSeen } from '../../src/unread.js';

const msg = (id, role, at, body = id) => ({ id, sender_role: role, body, created_at: at });
const T = (m) => `2026-09-29T10:${String(m).padStart(2, '0')}:00Z`;

function memoryStorage(initial = {}) {
  const data = { ...initial };
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
  };
}

describe('thread ordering and merging', () => {
  it('sorts oldest first, ties by id, without mutating the input', () => {
    const input = [msg('b', 'coach', T(2)), msg('z', 'athlete', T(1)), msg('a', 'athlete', T(1))];
    expect(sortThread(input).map((m) => m.id)).toEqual(['a', 'z', 'b']);
    expect(input[0].id).toBe('b');
  });

  it('de-duplicates by id (the inclusive poll cursor re-sends the newest message)', () => {
    const existing = [msg('a', 'athlete', T(1)), msg('b', 'coach', T(2))];
    const merged = mergeThreadMessages(existing, [msg('b', 'coach', T(2)), msg('c', 'ai_coach', T(3))]);
    expect(merged.map((m) => m.id)).toEqual(['a', 'b', 'c']);
  });

  it('returns the SAME array when nothing new arrived, so callers can skip a render', () => {
    const existing = [msg('a', 'athlete', T(1))];
    expect(mergeThreadMessages(existing, [msg('a', 'athlete', T(1))])).toBe(existing);
    expect(mergeThreadMessages(existing, [])).toBe(existing);
    expect(mergeThreadMessages(existing, undefined)).toBe(existing);
  });

  it('slots a late-arriving older message into order', () => {
    const merged = mergeThreadMessages([msg('b', 'coach', T(5))], [msg('a', 'athlete', T(1))]);
    expect(merged.map((m) => m.id)).toEqual(['a', 'b']);
  });

  it('cursor is the newest created_at, or null for an empty thread', () => {
    expect(threadCursor([])).toBeNull();
    expect(threadCursor([msg('a', 'athlete', T(1)), msg('b', 'coach', T(7))])).toBe(T(7));
  });
});

describe('applyThreadPayload', () => {
  it('first load: ready, changed, adopts messages and mute state', () => {
    const { thread, changed } = applyThreadPayload(createThreadState(), {
      messages: [msg('a', 'athlete', T(1))], ai_muted: true,
    });
    expect(changed).toBe(true);
    expect(thread.status).toBe('ready');
    expect(thread.muted).toBe(true);
    expect(thread.messages).toHaveLength(1);
  });

  it('a poll that finds nothing new is not a change', () => {
    const first = applyThreadPayload(createThreadState(), { messages: [msg('a', 'athlete', T(1))], ai_muted: false }).thread;
    const { changed } = applyThreadPayload(first, { messages: [msg('a', 'athlete', T(1))], ai_muted: false });
    expect(changed).toBe(false);
  });

  it('a flipped mute alone is a change', () => {
    const first = applyThreadPayload(createThreadState(), { messages: [], ai_muted: false }).thread;
    expect(applyThreadPayload(first, { messages: [], ai_muted: true }).changed).toBe(true);
  });

  it('keeps an unsent draft untouched across a poll', () => {
    const base = { ...createThreadState(), draft: 'half typed' };
    expect(applyThreadPayload(base, { messages: [msg('a', 'coach', T(1))], ai_muted: false }).thread.draft).toBe('half typed');
  });
});

describe('shouldPoll', () => {
  const live = { visible: true, online: true, configured: true, hasThread: true };
  it('polls only when visible, online, configured and a thread is in use', () => {
    expect(shouldPoll(live)).toBe(true);
    expect(shouldPoll({ ...live, visible: false })).toBe(false);
    expect(shouldPoll({ ...live, online: false })).toBe(false);
    expect(shouldPoll({ ...live, configured: false })).toBe(false);
    expect(shouldPoll({ ...live, hasThread: false })).toBe(false);
  });

  it('pauses while a send is in flight', () => {
    expect(shouldPoll({ ...live, busy: true })).toBe(false);
  });

  it('interval stays modest (15-30 s)', () => {
    expect(CONVERSATION_POLL_INTERVAL_MS).toBeGreaterThanOrEqual(15000);
    expect(CONVERSATION_POLL_INTERVAL_MS).toBeLessThanOrEqual(30000);
  });
});

describe('offline cache', () => {
  it('round-trips and caps at the newest 100 messages', () => {
    const storage = memoryStorage();
    const many = Array.from({ length: 130 }, (_, i) => msg(`m${i}`, 'athlete', `2026-09-29T10:00:${String(i % 60).padStart(2, '0')}Z`));
    saveCachedThread('athlete:c1', many, storage);
    const loaded = loadCachedThread('athlete:c1', storage);
    expect(loaded).toHaveLength(100);
    expect(loaded[99].id).toBe('m129');
  });

  it('misses, corrupt JSON and a throwing storage all read as an empty thread', () => {
    expect(loadCachedThread('nope', memoryStorage())).toEqual([]);
    expect(loadCachedThread('k', memoryStorage({ swimcoach_thread_cache_k: '{oops' }))).toEqual([]);
    const throwing = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('blocked'); } };
    expect(loadCachedThread('k', throwing)).toEqual([]);
    expect(() => saveCachedThread('k', [msg('a', 'athlete', T(1))], throwing)).not.toThrow();
  });
});

describe('countUnreadThread / last seen', () => {
  const thread = [
    msg('a', 'athlete', T(1)), msg('b', 'ai_coach', T(2)), msg('c', 'coach', T(3)),
    msg('d', 'athlete', T(4)), msg('e', 'coach', T(5)),
  ];

  it("athlete: counts only the human coach's messages newer than last seen", () => {
    expect(countUnreadThread(thread, null, 'athlete')).toBe(2);
    expect(countUnreadThread(thread, T(3), 'athlete')).toBe(1);
    expect(countUnreadThread(thread, T(5), 'athlete')).toBe(0);
  });

  it("coach: counts only the athlete's messages; the AI's replies never count", () => {
    expect(countUnreadThread(thread, null, 'coach')).toBe(2);
    expect(countUnreadThread(thread, T(1), 'coach')).toBe(1);
  });

  it('is defensive about missing/garbled data', () => {
    expect(countUnreadThread(undefined, null, 'athlete')).toBe(0);
    expect(countUnreadThread([{ sender_role: 'coach', created_at: 'garbage' }, null], null, 'athlete')).toBe(0);
  });

  it('last-seen round-trips per thread key and tolerates a failing storage', () => {
    const storage = memoryStorage();
    expect(loadThreadLastSeen('athlete:c1', storage)).toBeNull();
    saveThreadLastSeen('athlete:c1', T(9), storage);
    expect(loadThreadLastSeen('athlete:c1', storage)).toBe(T(9));
    expect(loadThreadLastSeen('coach:renee', storage)).toBeNull();
    saveThreadLastSeen('athlete:c1', null, storage); // no-op, never clobbers with null
    expect(loadThreadLastSeen('athlete:c1', storage)).toBe(T(9));
    const throwing = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); } };
    expect(loadThreadLastSeen('k', throwing)).toBeNull();
    expect(() => saveThreadLastSeen('k', T(1), throwing)).not.toThrow();
  });
});
