// Pure date/formatting/derivation helpers for rendering the athlete's plan.
// Kept free of DOM access so it's cheaply unit-testable (see tests/unit/plan.test.js).

const DOW_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const MS_PER_DAY = 86400000;

/** Parse a 'YYYY-MM-DD' string as a local-time midnight Date (avoids the
 * UTC-parse day-shift bug of `new Date('YYYY-MM-DD')` in timezones behind UTC). */
export function parseIsoDate(dateStr) {
  const [y, m, d] = dateStr.split('-').map(Number);
  return new Date(y, m - 1, d);
}

/** Monday of a given ISO week string like "2026-W28", as a local Date. */
export function isoWeekMonday(isoWeek) {
  const [yearStr, weekStr] = isoWeek.split('-W');
  const year = Number(yearStr);
  const week = Number(weekStr);
  const jan4 = new Date(year, 0, 4);
  const jan4DowMon0 = (jan4.getDay() + 6) % 7; // 0=Monday .. 6=Sunday
  const week1Monday = new Date(year, 0, 4 - jan4DowMon0);
  return new Date(week1Monday.getFullYear(), week1Monday.getMonth(), week1Monday.getDate() + (week - 1) * 7);
}

export function addDays(date, days) {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate() + days);
}

export function daysBetween(from, to) {
  return Math.round((to.getTime() - from.getTime()) / MS_PER_DAY);
}

export function dateKey(date) {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function formatShortDate(date) {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function formatLongDate(date) {
  return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

export function dowLabel(index) {
  return DOW_LABELS[index];
}

/** "300" -> "5 h", "90" -> "90 min", "125" -> "2 h 5 min". */
export function formatDuration(minutes) {
  const m = Math.round(minutes);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  const rem = m % 60;
  return rem === 0 ? `${h} h` : `${h} h ${rem} min`;
}

export function formatDistance(distanceM) {
  if (distanceM === null || distanceM === undefined) return null;
  return `${distanceM.toLocaleString('en-US')} m`;
}

/** "1:30" for 90 seconds/100m. */
export function formatPace(seconds) {
  if (seconds === null || seconds === undefined) return null;
  const s = Math.round(seconds);
  const min = Math.floor(s / 60);
  const sec = s % 60;
  return `${min}:${String(sec).padStart(2, '0')}`;
}

/** Sessions in this codebase write `purpose` as "title — detail" (an
 * em dash separator) by convention, e.g. "dryland shoulder strength —
 * moderate (2 days before the 5-hour swim)". Not guaranteed -- gracefully
 * degrades to the full text as the title when there's no dash. */
export function splitPurpose(purpose) {
  const dashIdx = purpose.indexOf('—');
  if (dashIdx === -1) return { title: purpose.trim(), detail: null };
  return {
    title: purpose.slice(0, dashIdx).trim(),
    detail: purpose.slice(dashIdx + 1).trim(),
  };
}

function capitalize(text) {
  if (!text) return text;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

const RACE_TAG_RE = /\(([ab])\s*race\)/i;

/** Sessions whose purpose is marked "(A race)"/"(B race)", or long (3h+)
 * open-water swims, are the plan's milestones -- highlight them and give
 * them a badge. This is a heuristic over free-text `purpose`, not a model
 * field, since Session has no explicit milestone flag today. */
export function classifySession(session) {
  const raceMatch = session.purpose.match(RACE_TAG_RE);
  if (raceMatch) {
    return { highlight: true, tag: `${raceMatch[1].toUpperCase()} Race` };
  }
  if (session.sport === 'swim_ow' && session.duration_min >= 180) {
    return { highlight: true, tag: 'Milestone' };
  }
  return { highlight: false, tag: null };
}

const MAIN_SET_RE = /Main set:\s*([^\n]+)/;

/** Cuts `text` at whichever of a comma or " -- " occurs first (mirrors the
 * "Main set:" line's own conventions -- see deriveSessionTitle's doc
 * comment for the real example), or returns it unchanged if neither is
 * present. */
function cutAtFirstBoundary(text) {
  const commaIdx = text.indexOf(',');
  const dashIdx = text.indexOf(' -- ');
  const candidates = [commaIdx, dashIdx].filter((i) => i !== -1);
  if (candidates.length === 0) return text;
  return text.slice(0, Math.min(...candidates));
}

/** Derives a short, actually-descriptive session title from its authored
 * `structure` text (the real warm-up/main-set/cool-down or strength-bullet
 * content) rather than the generic sport label `purpose` alone would give.
 *
 * - Swim-session format (a "Main set:" line present): takes that line's
 *   text up to its first comma or " -- ", whichever comes first. E.g.
 *   "Main set: 8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous
 *   aerobic volume..." -> "8 x 300m @ Z2 (1:35-1:39/100m)".
 * - Strength-session format (no "Main set:" line): takes structure's first
 *   line up to its first "(". E.g. "Rotator-cuff / scapular-stability core
 *   (2 sets x 10 reps each):\n  - ..." -> "Rotator-cuff / scapular-stability
 *   core".
 * - No structure at all (pool-coach placeholders, recovery, the long
 *   open-water swim): falls back to today's existing purpose-derived title,
 *   unchanged.
 * - Defensive edge case: if a structure string is shaped unlike either format
 *   above closely enough that the cut leaves nothing (e.g. a strength-style
 *   first line that starts with "(" itself, cutting to an empty string
 *   before its first paren) -- not producible by either real generator
 *   today, but not guaranteed by the format either -- falls back to the same
 *   purpose-derived title rather than surfacing a blank one. */
export function deriveSessionTitle(session) {
  const purposeTitle = () => {
    const { title } = splitPurpose(session.purpose);
    return capitalize(title.replace(RACE_TAG_RE, '').replace(/\s{2,}/g, ' ').trim());
  };
  const { structure } = session;
  if (structure) {
    const mainSetMatch = structure.match(MAIN_SET_RE);
    if (mainSetMatch) {
      const derived = capitalize(cutAtFirstBoundary(mainSetMatch[1]).trim());
      return derived || purposeTitle();
    }
    const firstLine = structure.split('\n')[0];
    const parenIdx = firstLine.indexOf('(');
    const text = parenIdx !== -1 ? firstLine.slice(0, parenIdx) : firstLine;
    const derived = capitalize(text.trim());
    return derived || purposeTitle();
  }
  return purposeTitle();
}

/** Derive a display title/detail/structure for a session. `structure` (the
 * real authored warm-up/main-set/cool-down or strength content) is surfaced
 * as its own field, never suppressed by `detail` (the post-em-dash text
 * split out of `purpose`) -- both are returned separately so callers (the
 * compact session row AND the click-to-detail view) can each show whatever
 * is appropriate for their own space, instead of one silently winning via
 * `||` collapse. */
export function sessionDisplay(session) {
  const { detail } = splitPurpose(session.purpose);
  return { title: deriveSessionTitle(session), detail, structure: session.structure || null };
}

const SPORT_COLOR_VAR = {
  swim_pool: '--c-pool',
  swim_ow: '--c-ow',
  strength: '--c-strength',
  recovery: '--c-recovery',
};

export function sessionDotColorVar(session, classification) {
  if (classification.highlight) return '--c-signal';
  return SPORT_COLOR_VAR[session.sport] || '--c-ink-faint';
}

/** Finds a session by id across every loaded week's `sessions` (mirrors the
 * simple exact-match lookup renderHistorySection does for workouts -- these
 * are internal ids, not user-typed, so no fuzzy matching is needed). Returns
 * null if no week has a session with that id. */
export function findSessionById(weeks, id) {
  if (!id || !weeks) return null;
  for (const week of weeks) {
    const found = (week.sessions || []).find((s) => s.id === id);
    if (found) return found;
  }
  return null;
}

/** Group a week's sessions by calendar date across the week's Mon..Sun span. */
export function sessionsByDay(week) {
  const monday = isoWeekMonday(week.iso_week);
  const days = [];
  for (let i = 0; i < 7; i++) {
    const date = addDays(monday, i);
    const key = dateKey(date);
    days.push({
      date,
      dow: dowLabel(i),
      sessions: week.sessions.filter((s) => s.date === key),
    });
  }
  return days;
}

/** Pick the "current" and "next" week from a list, sorted by iso_week, by
 * comparing each week's Monday against `now`. "Current" is the earliest
 * week whose Sunday hasn't passed yet; if every week is already past, falls
 * back to the last two so there's still something to show. */
export function pickCurrentAndNextWeek(weeks, now = new Date()) {
  const sorted = [...weeks].sort((a, b) => a.iso_week.localeCompare(b.iso_week));
  if (sorted.length === 0) return { current: null, next: null };

  let currentIndex = sorted.findIndex((week) => {
    const sunday = addDays(isoWeekMonday(week.iso_week), 6);
    return daysBetween(now, sunday) >= 0;
  });
  if (currentIndex === -1) currentIndex = Math.max(0, sorted.length - 2);

  return {
    current: sorted[currentIndex] || null,
    next: sorted[currentIndex + 1] || null,
  };
}

/** Days remaining (>=0) until `eventDate` (a Date), rounded up so "today" and
 * "tomorrow morning" both read as at least 1 day out once the date has passed
 * midnight, and 0 on/after the event date itself. */
export function daysUntil(eventDate, now = new Date()) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.max(0, daysBetween(today, eventDate));
}

/** The athlete's priority-A event, or the earliest event if none is marked A. */
export function priorityEvent(events) {
  if (!events || events.length === 0) return null;
  const aEvents = events.filter((e) => e.priority === 'A');
  const pool = aEvents.length > 0 ? aEvents : events;
  return [...pool].sort((a, b) => a.event_date.localeCompare(b.event_date))[0];
}

/** The event the CURRENT macro plan is actually built toward, if one exists
 * -- looked up by `macro.event_id`, not by priority/date. `priorityEvent`
 * alone can silently diverge from the active macro (e.g. an athlete with
 * several events on file where the soonest-dated one isn't what the macro
 * targets), which showed up as the Plan tab's masthead displaying a
 * completely different race than the one the plan was actually built
 * around. Falls back to `priorityEvent` only when there's no macro at all
 * (or its event_id doesn't resolve to a known event). */
export function macroTargetEvent(macro, events) {
  if (macro && macro.event_id) {
    const matched = (events || []).find((e) => e.id === macro.event_id);
    if (matched) return matched;
  }
  return priorityEvent(events);
}

/** The macro block containing `now`, or the nearest one (first if now is
 * before the whole plan, last if now is after it) -- there's always a
 * "you are here" marker to draw. */
export function currentBlockIndex(blocks, now = new Date()) {
  if (!blocks || blocks.length === 0) return -1;
  const idx = blocks.findIndex((b) => {
    const start = parseIsoDate(b.start_date);
    const end = parseIsoDate(b.end_date);
    return daysBetween(start, now) >= 0 && daysBetween(now, end) >= 0;
  });
  if (idx !== -1) return idx;
  const firstStart = parseIsoDate(blocks[0].start_date);
  if (daysBetween(firstStart, now) < 0) return 0;
  return blocks.length - 1;
}

/** Long-swim ladder rungs: the biggest logged/planned open-water swim found
 * across the supplied weeks (the current milestone), a static "build-ups"
 * connective step, an estimated peak swim derived from the macro's peak
 * block (60-70% of event distance per library/06 guidance -- ROADMAP.md),
 * and the event itself. Returns [] if there's not enough data to derive
 * anything (no swim_ow sessions and no event). */
export function longSwimLadder(weeks, macro, event) {
  const rungs = [];

  let biggest = null;
  for (const week of weeks) {
    for (const session of week.sessions) {
      if (session.sport !== 'swim_ow' || !session.distance_m) continue;
      if (!biggest || session.distance_m > biggest.distance_m) biggest = session;
    }
  }
  if (biggest) {
    rungs.push({
      km: (biggest.distance_m / 1000).toFixed(biggest.distance_m % 1000 === 0 ? 0 : 1),
      label: `${formatDuration(biggest.duration_min)} · ${formatShortDate(parseIsoDate(biggest.date))}`,
    });
  }

  if (macro && macro.blocks && macro.blocks.length > 2) {
    rungs.push({ connective: 'build-ups' });
  }

  const peakBlock = macro?.blocks?.find((b) => b.name === 'peak');
  if (peakBlock && event) {
    const peakDistance = Math.round((event.distance_m * 0.65) / 100) * 100;
    const peakEnd = parseIsoDate(peakBlock.end_date);
    rungs.push({
      km: (peakDistance / 1000).toFixed(peakDistance % 1000 === 0 ? 0 : 1),
      label: `peak swim · ${peakEnd.toLocaleDateString('en-US', { month: 'short' })}`,
    });
  }

  if (event) {
    rungs.push({
      km: (event.distance_m / 1000).toFixed(event.distance_m % 1000 === 0 ? 0 : 1),
      label: event.name.split(/[—(]/)[0].trim(),
      final: true,
    });
  }

  return rungs;
}
