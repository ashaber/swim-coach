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

/** Derive a display title/detail for a session from its purpose, with any
 * race-tag parenthetical stripped out of the title (it's shown as a badge
 * instead). */
export function sessionDisplay(session) {
  const { title, detail } = splitPurpose(session.purpose);
  const cleanTitle = capitalize(title.replace(RACE_TAG_RE, '').replace(/\s{2,}/g, ' ').trim());
  return { title: cleanTitle, detail: detail || session.structure || null };
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
