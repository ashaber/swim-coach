// Athlete<->coach conversation thread state (IDEA 016 Part 2) -- pure logic, unit-tested
// directly, same "small dedicated module" convention as unread.js/session.js. main.js wires it
// to fetch/render; views.js renders it. The thread is three-party (athlete, AI coach, human
// coach) and shared by two surfaces with the same shape: the athlete's "My coach" pane inside
// the Coach tab (`state.myCoach`) and the roster's Conversations sub-tab
// (`state.roster.conversation`).

/** How often a visible, online thread re-fetches. Modest on purpose: one small GET per tick. */
export const CONVERSATION_POLL_INTERVAL_MS = 20000;

const CACHE_KEY_PREFIX = 'swimcoach_thread_cache_';
const CACHE_MAX_MESSAGES = 100;

/** A fresh thread slice. `status`: 'idle' (nothing fetched) | 'loading' | 'ready' | 'error'. */
export function createThreadState() {
  return {
    status: 'idle',
    coachId: null, // athlete side only: which coach's thread (the roster derives it server-side)
    muted: false,
    messages: [],
    draft: '', // the unsent composer text -- kept in state so a poll re-render never wipes it
    sending: false,
    pending: null, // athlete side: the just-sent message awaiting its persisted copy
    stream: null, // athlete side: the AI reply streaming in ({text}) before it is persisted
    error: null,
  };
}

/** Thread order: oldest first, ties broken by id (the backend's own order). */
export function sortThread(messages) {
  return [...messages].sort((a, b) => {
    if (a.created_at !== b.created_at) return a.created_at < b.created_at ? -1 : 1;
    return a.id < b.id ? -1 : a.id > b.id ? 1 : 0;
  });
}

/** Folds `incoming` into `existing`, de-duplicating by id (the poll cursor is inclusive, so the
 * newest known message comes back every time) and keeping thread order. Returns `existing`
 * itself (same reference) when nothing new arrived, so callers can skip a re-render. */
export function mergeThreadMessages(existing, incoming) {
  const known = new Set(existing.map((m) => m.id));
  const fresh = (incoming || []).filter((m) => !known.has(m.id));
  if (fresh.length === 0) return existing;
  return sortThread([...existing, ...fresh]);
}

/** The newest `created_at` held -- the `since` cursor for the next poll -- or null. */
export function threadCursor(messages) {
  return messages.length === 0 ? null : messages[messages.length - 1].created_at;
}

/** Whether a poll should fire right now: only while the page is visible and online, and only
 * when a thread is actually in use (signed in, configured, and a thread to read). */
export function shouldPoll({ visible, online, configured, hasThread, busy = false }) {
  return !!(visible && online && configured && hasThread && !busy);
}

/** localStorage key for one thread's cached messages (`kind:id`, e.g. `athlete:<coachId>`). */
export function threadCacheKey(threadKey) {
  return `${CACHE_KEY_PREFIX}${threadKey}`;
}

/** Cached messages for offline read-only display; [] on a miss or any storage failure. */
export function loadCachedThread(threadKey, storage = localStorage) {
  try {
    const parsed = JSON.parse(storage.getItem(threadCacheKey(threadKey)) || '[]');
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

/** Best-effort write of the newest messages (a failed write just means no offline copy). */
export function saveCachedThread(threadKey, messages, storage = localStorage) {
  try {
    storage.setItem(threadCacheKey(threadKey), JSON.stringify(messages.slice(-CACHE_MAX_MESSAGES)));
  } catch {
    // ignore -- private mode / quota; the thread simply isn't available offline
  }
}

/** Applies one GET response (`{messages, ai_muted, coach_athlete_id?}`) to a thread slice.
 * `status` becomes 'ready'; `changed` says whether the visible content moved (new messages or a
 * flipped mute), so a poll that found nothing can skip render(). */
export function applyThreadPayload(thread, payload) {
  const messages = mergeThreadMessages(thread.messages, payload.messages);
  const muted = !!payload.ai_muted;
  const changed = messages !== thread.messages || muted !== thread.muted || thread.status !== 'ready';
  return { thread: { ...thread, status: 'ready', error: null, messages, muted }, changed };
}
