// Pure derivation for the History tab: what the athlete actually did
// (completed workouts) and what she planned but never did (skipped
// sessions), merged into one reverse-chronological feed.
//
// DOM-free and clock-injectable (`now` is always a parameter, never
// `new Date()` inside a rule) so it's cheaply unit-testable -- same
// separation plan.js/workouts.js already follow against views.js.
//
// --- Why "skipped" is DERIVED, not read from Session.status -----------------
// `Session.status` has a "skipped" value in the model, but nothing in the
// codebase ever writes it (verified by grep across engine + backend): a
// missed session stays "planned" forever. Only the chat-driven log-workout
// skill flips a session to "completed"; the `.fit` auto-sync path
// (backend/app/sync.py) threads `planned_session_id` through from the parse
// draft without ever computing the match, so it's generally null for
// anything the athlete synced from her watch rather than described in chat.
//
// So `status` is treated as a HINT that can only ever rescue a session from
// being called skipped (an explicit "completed"/"replaced" is believed),
// never as the thing that marks one. The reliable signal is the absence of a
// matching workout, which is what these rules compute.

/** A workout's calendar date as 'YYYY-MM-DD'. Workouts may carry a full ISO
 * timestamp while plan sessions always carry a plain date, so both sides are
 * normalized to the date half before any comparison. Null (not a throw) for
 * a missing/blank date, so one malformed row can't take down the feed. */
export function workoutDateKey(workout) {
  const raw = workout?.date;
  if (!raw || typeof raw !== 'string') return null;
  return raw.slice(0, 10);
}

/** Sports that can never count as "skipped".
 *
 * Recovery is modeled as a short mobility session only because the Session
 * model requires `duration_min > 0` and so can't represent a plain day off
 * (see plan.py's RECOVERY_SESSION_MIN). Nobody logs a rest day, so every
 * single one would render as a skip and bury the real ones in noise. */
export const SKIP_EXEMPT_SPORTS = new Set(['recovery']);

/** Session statuses that mean "this was dealt with" regardless of whether a
 * workout is on file -- see the module note on why status is a hint. */
const SETTLED_STATUSES = new Set(['completed', 'replaced']);

/** The workout that satisfies `session`, or null.
 *
 * Two rules, in priority order:
 *  1. An explicit `planned_session_id` link -- the athlete or the coach said
 *     so, and it wins even if the date/sport don't line up (a session moved
 *     to another day is still that session).
 *  2. Same date AND same sport. This is what catches everything logged
 *     without the link populated, which is most of it (see the module note).
 *
 * A workout already explicitly linked to a DIFFERENT session is not eligible
 * for rule 2 -- otherwise one workout could satisfy two planned sessions on
 * the same day and silently hide a genuine skip. */
export function findWorkoutForSession(session, workouts) {
  if (!session || !workouts) return null;

  const linked = workouts.find((w) => w.planned_session_id && w.planned_session_id === session.id);
  if (linked) return linked;

  const sessionDate = session.date;
  return workouts.find((w) => (
    !w.planned_session_id
    && w.sport === session.sport
    && workoutDateKey(w) === sessionDate
  )) || null;
}

/** Whether `session` was planned and never done: strictly before today, not
 * a rest day, not already settled by an explicit status, and with no
 * workout that satisfies it. "Strictly before today" matters -- a session
 * planned for this afternoon has not been skipped yet. */
export function isSessionSkipped(session, workouts, now) {
  if (!session || !session.date) return false;
  if (SKIP_EXEMPT_SPORTS.has(session.sport)) return false;
  if (SETTLED_STATUSES.has(session.status)) return false;

  const today = toDateKey(now);
  if (session.date >= today) return false; // zero-padded ISO -> lexicographic works

  return findWorkoutForSession(session, workouts) === null;
}

function toDateKey(now) {
  const d = now instanceof Date ? now : new Date(now);
  const month = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${month}-${day}`;
}

/** The unified History feed: every completed workout plus every derived
 * skipped session, newest first.
 *
 * Items are `{ kind: 'completed'|'skipped', date, key, workout|session }`.
 * `key` is stable and unique per item so rendering can key on it.
 *
 * On a date carrying both, the completed item sorts first -- the thing she
 * actually did leads, the miss follows.
 *
 * NOTE: `workouts` must be the FULL fetched list, not a display-capped
 * slice. Matching a session against a truncated list would report older
 * sessions as skipped purely because their workout fell off the end. */
export function buildHistoryFeed({ weeks, workouts, now }) {
  const allWorkouts = workouts || [];
  const items = allWorkouts
    .filter((w) => workoutDateKey(w) !== null)
    .map((w) => ({ kind: 'completed', date: workoutDateKey(w), key: `w:${w.id}`, workout: w }));

  for (const week of weeks || []) {
    for (const session of week.sessions || []) {
      if (isSessionSkipped(session, allWorkouts, now)) {
        items.push({ kind: 'skipped', date: session.date, key: `s:${session.id}`, session });
      }
    }
  }

  return items.sort((a, b) => {
    if (a.date !== b.date) return a.date < b.date ? 1 : -1; // newest first
    if (a.kind === b.kind) return 0;
    return a.kind === 'completed' ? -1 : 1;
  });
}
