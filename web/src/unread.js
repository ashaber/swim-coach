// B3 (coach-mode Q&A build): in-app unread badges for the durable
// `Feedback` log -- client-side only, no new backend state. A "last seen"
// timestamp per ROLE (athlete/coach), NOT per-athlete/per-feedback-item --
// same tradeoff the branch brief accepts for localStorage-only conveniences
// elsewhere in this app (e.g. allWeeksOpen, the active-tab flag): one
// device's view of "have I looked at this recently" is good enough, and it
// resets independently per browser/device, which is fine here.
//
// Deliberately asymmetric per role -- see `countUnread`'s own doc comment:
// a coach cares about newly-ASKED questions, an athlete cares about newly-
// ARRIVED replies to her own questions. Pure logic lives here (unit-tested
// directly, same "small dedicated module" convention as pwaUpdate.js/
// session.js/onboarding.js) -- main.js just wires it to render()/setTab/
// the roster handlers.

const STORAGE_KEY_PREFIX = 'swimcoach_feedback_last_seen_';

/** Reads the last-seen ISO timestamp for `role` ('athlete' | 'coach'), or
 * `null` if this device has never marked that role's feedback as seen
 * (every dated entry counts as unread in that case -- see `countUnread`).
 * `storage` is injectable (defaults to the real `localStorage`) -- same
 * convention as settings.js's loadSettings/chat.js's loadChatSession, so
 * this is unit-testable without a DOM/jsdom environment (this project's
 * vitest config runs in Node -- see vite.config.js). */
export function loadLastSeen(role, storage = localStorage) {
  try {
    return storage.getItem(`${STORAGE_KEY_PREFIX}${role}`);
  } catch {
    return null;
  }
}

/** Marks `role`'s feedback as seen as of `isoNow` (defaults to the real
 * current time) -- called when the relevant section is actually opened/
 * viewed (see main.js's setTab 'feedback' branch and the roster's
 * handleSelectCoachedAthlete/handleSelectRosterSubTab). Best-effort, like
 * every other localStorage write in this app (saveActiveTab, chat.js's
 * saveChatSession): a failed write (private mode, quota) just means the
 * badge won't clear until storage is next reachable, not a crash. Same
 * injectable-`storage` convention as `loadLastSeen` above. */
export function saveLastSeen(role, isoNow = new Date().toISOString(), storage = localStorage) {
  try {
    storage.setItem(`${STORAGE_KEY_PREFIX}${role}`, isoNow);
  } catch {
    // ignore -- see doc comment above
  }
  return isoNow;
}

/** Counts `entries` (a Feedback list, exactly as GET /api/feedback /
 * GET /api/coach/athletes/<slug>/feedback already return it) newer than
 * `lastSeen` (an ISO string, or `null` meaning "never seen anything" -- every
 * dated entry then counts).
 *
 * `role` picks which timestamp field distinguishes "new" for that audience:
 *  - 'coach': `created_at` -- a newly-asked question the coach hasn't looked
 *    at yet.
 *  - 'athlete' (anything else): `coach_reply_at` -- a newly-arrived reply to
 *    one of the athlete's own questions. An entry with no reply yet (or an
 *    old one that predates `lastSeen`) never counts, even if the QUESTION
 *    itself is recent -- an unanswered question isn't something new for the
 *    athlete to read.
 *
 * Malformed/missing timestamps are skipped rather than counted or thrown on
 * -- defensive against a field genuinely absent on old rows (both fields are
 * optional/defaulted on `Feedback`, see engine/swim_coach/models.py). */
export function countUnread(entries, lastSeen, role) {
  const field = role === 'coach' ? 'created_at' : 'coach_reply_at';
  const lastSeenMs = lastSeen ? Date.parse(lastSeen) : 0;
  return (entries || []).reduce((count, entry) => {
    const value = entry?.[field];
    if (!value) return count;
    const ms = Date.parse(value);
    if (Number.isNaN(ms)) return count;
    return ms > lastSeenMs ? count + 1 : count;
  }, 0);
}

// --- Athlete<->coach conversation threads (IDEA 016 Part 2) --------------------------------
// Same "last seen" idea as the feedback badge above, but per THREAD (not per role): the athlete
// has one thread per coach (`athlete:<coachId>`), a coach one per coached athlete
// (`coach:<athleteSlug>`). Client-side only, same accepted tradeoff as above.

const THREAD_STORAGE_KEY_PREFIX = 'swimcoach_thread_last_seen_';

export function loadThreadLastSeen(threadKey, storage = localStorage) {
  try {
    return storage.getItem(`${THREAD_STORAGE_KEY_PREFIX}${threadKey}`);
  } catch {
    return null;
  }
}

/** Marks a thread seen up to `iso` -- callers pass the newest message's own `created_at`
 * (server time), not the device clock, so clock skew can never hide a real unread message. */
export function saveThreadLastSeen(threadKey, iso, storage = localStorage) {
  if (!iso) return;
  try {
    storage.setItem(`${THREAD_STORAGE_KEY_PREFIX}${threadKey}`, iso);
  } catch {
    // ignore -- see saveLastSeen
  }
}

/** Counts messages from the OTHER human party newer than `lastSeen`: for the athlete that is
 * the human coach's comments (`sender_role === 'coach'`), for the coach the athlete's messages
 * (`'athlete'`). The AI's replies never count -- an athlete watches those stream in live, and a
 * coach does not need a badge for the AI talking to the athlete. */
export function countUnreadThread(messages, lastSeen, viewerRole) {
  const wanted = viewerRole === 'coach' ? 'athlete' : 'coach';
  const lastSeenMs = lastSeen ? Date.parse(lastSeen) : 0;
  return (messages || []).reduce((count, m) => {
    if (m?.sender_role !== wanted) return count;
    const ms = Date.parse(m.created_at);
    return !Number.isNaN(ms) && ms > lastSeenMs ? count + 1 : count;
  }, 0);
}
