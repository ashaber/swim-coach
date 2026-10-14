// Pure helpers + localStorage persistence for the race-week item strips and the race-day
// checklist overlay. Mirrors engine/swim_coach/race_day.py (timeline_clock, tag filtering) --
// keep the two in step. No DOM access; every storage touch is try/catch (private mode etc.).

import log from './log.js';

const OPEN_KEY = 'swimcoach_raceday_open';
const QUEUE_KEY = 'swimcoach_raceday_queue';
const PLAN_CACHE_PREFIX = 'swimcoach_raceday_plan:';
const MS_PER_DAY = 86400000;

const RACE_WEEK_ICONS = {
  carb_load: '🍝',
  bodywork: '💆',
  logistics: '🧳',
  bike: '🚲',
  gear: '🎒',
  weather: '🌦️',
  nutrition: '🥣',
  sleep: '😴',
  recovery: '🧘',
};

export function raceWeekCategoryIcon(category) {
  return RACE_WEEK_ICONS[category] || '•';
}

/** Splits a week's race_week_checklist into per-day lists (for the 7 `dayKeys` of the week) and
 * `outside` (dated outside the week), each in date order. */
export function groupRaceWeekItems(checklist, dayKeys) {
  const items = [...(checklist || [])].sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
  const byDay = {};
  const outside = [];
  dayKeys.forEach((k) => { byDay[k] = []; });
  items.forEach((item) => {
    if (byDay[item.date]) byDay[item.date].push(item);
    else outside.push(item);
  });
  return { byDay, outside };
}

export function raceWeekSummary(checklist) {
  const list = checklist || [];
  return { total: list.length, done: list.filter((i) => i.done).length };
}

// --- race-day plan -----------------------------------------------------------------------

export function itemVisible(item, activeTags) {
  return !item.tags || item.tags.length === 0 || item.tags.some((t) => activeTags.includes(t));
}

/** Sections reduced to their visible items (weather-tag filter), each with progress counts. */
export function visibleSections(plan) {
  const checked = new Set(plan.checked || []);
  return (plan.sections || [])
    .map((s) => {
      const items = s.items.filter((i) => itemVisible(i, plan.active_tags || []))
        .map((i) => ({ ...i, checked: checked.has(i.id) }));
      return { id: s.id, title: s.title, items, done: items.filter((i) => i.checked).length, total: items.length };
    })
    .filter((s) => s.total > 0);
}

export function planProgress(plan) {
  const sections = visibleSections(plan);
  return {
    done: sections.reduce((n, s) => n + s.done, 0),
    total: sections.reduce((n, s) => n + s.total, 0),
  };
}

/** Every tag used by an item or already active, sorted -- the weather chips. */
export function allTags(plan) {
  const tags = new Set(plan.active_tags || []);
  (plan.sections || []).forEach((s) => s.items.forEach((i) => (i.tags || []).forEach((t) => tags.add(t))));
  return [...tags].sort();
}

export function applyChecked(plan, itemId, on) {
  const checked = (plan.checked || []).filter((c) => c !== itemId);
  if (on) checked.push(itemId);
  return { ...plan, checked };
}

export function toggleTag(plan, tag) {
  const active = plan.active_tags || [];
  return { ...plan, active_tags: active.includes(tag) ? active.filter((t) => t !== tag) : [...active, tag] };
}

// --- timeline ----------------------------------------------------------------------------

function hhmmToMin(hhmm) {
  const [h, m] = hhmm.split(':').map(Number);
  return h * 60 + m;
}

function minToHhmm(total) {
  const m = ((total % 1440) + 1440) % 1440;
  return `${String(Math.floor(m / 60)).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;
}

/** Timeline entries with `time` ("HH:MM", null until a start time is set) and `abs_min`
 * (minutes relative to race-day midnight; eve entries sit at -1440 + clock). Rules mirror
 * race_day.timeline_clock: offset from start, then not_later_than / not_earlier_than clamp,
 * and only_if_start_after / only_if_start_before (strict) hide an entry -- conditional entries
 * are hidden with no start time. Sorted by clock (eve first); untimed race entries by offset. */
export function timelineClock(plan) {
  const start = plan.start_time ? hhmmToMin(plan.start_time) : null;
  const out = [];
  (plan.timeline || []).forEach((e) => {
    if (e.day === 'eve') {
      out.push({ ...e, time: e.at, abs_min: -1440 + hhmmToMin(e.at) });
      return;
    }
    if (start === null) {
      if (!e.only_if_start_after && !e.only_if_start_before) out.push({ ...e, time: null, abs_min: null });
      return;
    }
    if (e.only_if_start_after && !(start > hhmmToMin(e.only_if_start_after))) return;
    if (e.only_if_start_before && !(start < hhmmToMin(e.only_if_start_before))) return;
    let abs = start + e.offset_min;
    if (e.not_later_than) abs = Math.min(abs, hhmmToMin(e.not_later_than));
    if (e.not_earlier_than) abs = Math.max(abs, hhmmToMin(e.not_earlier_than));
    out.push({ ...e, time: minToHhmm(abs), abs_min: abs });
  });
  const timed = out.filter((e) => e.abs_min !== null).sort((a, b) => a.abs_min - b.abs_min);
  const untimed = out.filter((e) => e.abs_min === null).sort((a, b) => a.offset_min - b.offset_min);
  return [...timed, ...untimed];
}

const RULE_FIELDS = ['not_later_than', 'not_earlier_than', 'only_if_start_after', 'only_if_start_before'];

/** Returns the timeline with entry `id` changed. `field` is label | offset_min | at or one of the
 * rule fields; an empty value clears a rule (label/offset/at ignore empties). */
export function editTimelineEntry(timeline, id, field, value) {
  return (timeline || []).map((e) => {
    if (e.id !== id) return e;
    if (field === 'label') return value.trim() ? { ...e, label: value.trim() } : e;
    if (field === 'offset_min') {
      const n = Math.round(Number(value));
      return value !== '' && Number.isFinite(n) ? { ...e, offset_min: n } : e;
    }
    if (field === 'at') return value ? { ...e, at: value } : e;
    if (RULE_FIELDS.includes(field)) return { ...e, [field]: value || null };
    return e;
  });
}

export function removeTimelineEntry(timeline, id) {
  return (timeline || []).filter((e) => e.id !== id || e.is_start);
}

/** Appends a new entry (race-day by default, 30 min before the start; eve at 19:00). */
export function addTimelineEntry(timeline, day = 'race') {
  const taken = new Set((timeline || []).map((e) => e.id));
  let n = 1;
  while (taken.has(`custom-${n}`)) n += 1;
  const entry = day === 'eve'
    ? { id: `custom-${n}`, label: 'New item', day: 'eve', at: '19:00', is_start: false }
    : { id: `custom-${n}`, label: 'New item', day: 'race', offset_min: -30, is_start: false };
  return [...(timeline || []), entry];
}

/** "6:15 AM" from "06:15". */
export function formatClockTime(hhmm) {
  if (!hhmm) return '';
  const [h, m] = hhmm.split(':').map(Number);
  const suffix = h >= 12 ? 'PM' : 'AM';
  return `${((h + 11) % 12) + 1}:${String(m).padStart(2, '0')} ${suffix}`;
}

/** Which timeline entry is current/next right now. Only meaningful from the evening before
 * through race day; otherwise `{ currentId: null, nextId: null }`. */
export function timelinePosition(clock, raceDateIso, now = new Date()) {
  const [y, mo, d] = raceDateIso.split('-').map(Number);
  const raceMidnight = new Date(y, mo - 1, d).getTime();
  const nowMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const dayDiff = Math.round((nowMidnight - raceMidnight) / MS_PER_DAY);
  const nowAbs = dayDiff * 1440 + now.getHours() * 60 + now.getMinutes();
  if (nowAbs < -1440 || nowAbs >= 1440) return { currentId: null, nextId: null };
  const timed = clock.filter((e) => e.abs_min !== null);
  let current = null;
  let next = null;
  timed.forEach((e) => {
    if (e.abs_min <= nowAbs) current = e;
    else if (!next) next = e;
  });
  return { currentId: current?.id ?? null, nextId: next?.id ?? null };
}

// --- persistence ---------------------------------------------------------------------------

function readJson(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch (err) {
    log.warn('raceday.storage_read_failed', { key, error: err.message });
    return fallback;
  }
}

function writeJson(key, value) {
  try {
    if (value === null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch (err) {
    log.warn('raceday.storage_write_failed', { key, error: err.message });
  }
}

/** The overlay that was open when the app last rendered: `{athlete, date, sessionId, name, tab}`. */
export function loadOpenOverlay(athlete) {
  const saved = readJson(OPEN_KEY, null);
  return saved && saved.athlete === athlete && saved.date ? saved : null;
}

export function saveOpenOverlay(value) {
  writeJson(OPEN_KEY, value);
}

export function loadCachedPlan(athlete, date) {
  return readJson(`${PLAN_CACHE_PREFIX}${athlete}:${date}`, null);
}

export function saveCachedPlan(athlete, plan) {
  writeJson(`${PLAN_CACHE_PREFIX}${athlete}:${plan.date}`, plan);
}

// --- offline queue ---------------------------------------------------------------------------
// Ops are absolute state (never toggles), so replay is idempotent. Later ops for the same plan
// merge into earlier ones: `items` ops merge their {itemId: bool} maps, `meta` ops merge fields.

export function mergeOp(queue, op) {
  const next = queue.map((q) => ({ ...q, payload: { ...q.payload } }));
  const existing = next.find((q) => q.athlete === op.athlete && q.planId === op.planId && q.kind === op.kind);
  // a `timeline` op carries the whole list: the newest replaces, it never merges field-wise
  if (existing) existing.payload = op.kind === 'timeline' ? { ...op.payload } : { ...existing.payload, ...op.payload };
  else next.push({ ...op, payload: { ...op.payload } });
  return next;
}

export function loadQueue() {
  const q = readJson(QUEUE_KEY, []);
  return Array.isArray(q) ? q : [];
}

export function saveQueue(queue) {
  writeJson(QUEUE_KEY, queue.length ? queue : null);
}

export function enqueue(op) {
  const queue = mergeOp(loadQueue(), op);
  saveQueue(queue);
  return queue;
}
