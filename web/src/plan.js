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

// --- Session.structure block parsing (Plan tab's session detail view) -----
// `structure` is a plain "Label: content"-per-line string (see plan.py's
// _additional_swim_structure/_strength_session_structure), never a
// structured object -- keeping it a string avoids any migration of already-
// persisted plan data. These two helpers split it into visual blocks for
// renderPlanSessionDetail instead of one flat pre-wrap blob.

/** Recognized structure labels, in two shapes:
 *  - "inline": `Label: rest of line` -- the swim format's Warm-up/Main set/
 *    Cool-down lines and both formats' trailing Why: rationale line. Content
 *    starts inline on the same line as the label.
 *  - heading-only (no captured inline content): the strength format's own
 *    two headings, e.g. "Rotator-cuff / scapular-stability core (2 sets x
 *    10 reps each):" -- the whole line (minus its trailing colon) IS the
 *    label; content is only the bullet lines that follow it. */
const STRUCTURE_LABEL_PATTERNS = [
  { re: /^(Warm-up|Main set|Cool-down|Why):\s*(.*)$/ },
  { re: /^(Rotator-cuff \/ scapular-stability core.*?|General full-body.*?):\s*$/ },
];

/** Joins a block's collected lines back into its `content` string, dropping
 * only fully-blank leading/trailing lines -- NOT a blanket `.join('\n').
 * trim()`, which would also eat the first content line's own leading
 * whitespace (the strength format's indented `  - ` bullets rely on that
 * indentation surviving intact). */
function joinBlockLines(lines) {
  let start = 0;
  let end = lines.length;
  while (start < end && lines[start].trim() === '') start++;
  while (end > start && lines[end - 1].trim() === '') end--;
  return lines.slice(start, end).join('\n');
}

/** Splits a `session.structure` string into an ordered list of
 * `{ label, content }` blocks, one per recognized label. Degrades
 * gracefully for any structure shape matching no known label at all:
 * returns a single `{ label: null, content: structure }` block containing
 * the original text verbatim, rather than erroring or dropping content. */
export function parseStructureBlocks(structure) {
  if (!structure) return [];
  const lines = structure.split('\n');
  const blocks = [];
  let current = null;

  for (const line of lines) {
    let label = null;
    let inlineContent = null;
    for (const { re } of STRUCTURE_LABEL_PATTERNS) {
      const m = line.match(re);
      if (m) {
        label = m[1];
        inlineContent = m.length > 2 ? m[2] : null;
        break;
      }
    }
    if (label !== null) {
      if (current) blocks.push(current);
      current = { label, lines: inlineContent ? [inlineContent] : [] };
    } else if (current) {
      current.lines.push(line);
    } else {
      current = { label: null, lines: [line] };
    }
  }
  if (current) blocks.push(current);

  if (blocks.length === 1 && blocks[0].label === null) {
    // Nothing matched any known label -- degrade to one block with the
    // original text untouched.
    return [{ label: null, content: structure }];
  }
  return blocks.map((b) => ({ label: b.label, content: joinBlockLines(b.lines) }));
}

/** Sub-parses a Main-set block's `content` (as returned by
 * parseStructureBlocks) into an ordered list of distinct interval strings,
 * one per non-blank line. Today's real engine output only ever emits ONE
 * line under "Main set:" (so this naturally returns a single-element
 * array) -- but this is forward-compatible with a future engine change
 * emitting 2+ distinct interval lines there, which would split into that
 * many items with zero further parsing/rendering changes needed. */
export function parseMainSetIntervals(mainSetContent) {
  if (!mainSetContent) return [];
  return mainSetContent.split('\n').map((line) => line.trim()).filter(Boolean);
}

// --- Session.structured tree-walk (Plan tab's session detail view, Phase A) -
// `structured` (the new `WorkoutStructure` IR from PR #91, engine/swim_coach/
// models.py) is a real object tree -- `WorkoutStructure.items`, a list of
// `WorkoutStep`/`WorkoutRepeat` nodes (discriminated by `kind`). This walks
// that tree directly (property access on real fields), never regex-parsing a
// prose string the way parseStructureBlocks/parseMainSetIntervals above do.
// This is explicitly NOT the polished per-block Warm-up/Main-set/Cool-down
// design those two helpers feed (that stays as today's fallback, used only
// when `structured` is absent) -- just a simple, generic, readable line-per-
// step/repeat walk. Phase A of a two-phase plan; Phase B (a later pass)
// retires the prose-parsing helpers above entirely.

/** Athlete-facing prefixes for the three "fully narrated" swim-session roles
 * -- mirrors `workout_templates.py`'s own `_ROLE_LINE_PREFIX` map exactly
 * (same voice as the prose fallback), applied only to TOP-LEVEL steps
 * (depth 0): a top-level warmup/interval/cooldown step's `label` is already
 * a complete narrated sentence (baked in at template-build time -- see
 * `render_main_set`), so nested/per-rep children under a `WorkoutRepeat`
 * never get this prefix (there, `label` is a short per-rep name, not a full
 * sentence, and the repeat's own header line already supplies the context.) */
const STRUCTURED_ROLE_PREFIX = { warmup: 'Warm-up: ', interval: 'Main set: ', cooldown: 'Cool-down: ' };

/** "90" -> "1:30", "600" -> "10:00". Always mm:ss (unlike formatDuration,
 * which switches to "h min" -- repeat/step durations here stay short enough
 * that seconds-resolution mm:ss reads better than an hours split). */
function formatSecondsClock(totalSeconds) {
  const total = Math.round(totalSeconds);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** A `WorkoutStep`'s duration as short athlete-facing text, or null for
 * `duration_kind === 'open'` / a missing value. */
function formatStepDuration(durationKind, durationValue) {
  if (durationValue === null || durationValue === undefined) return null;
  if (durationKind === 'distance_m') return `${Math.round(durationValue)}m`;
  if (durationKind === 'time_s') {
    const v = Math.round(durationValue);
    return v < 60 ? `${v}s` : formatSecondsClock(v);
  }
  if (durationKind === 'reps') return `${Math.round(durationValue)} reps`;
  return null;
}

/** A `WorkoutTarget`'s core intensity text (no leading "@"), or null when
 * there's nothing meaningful to show (`basis === 'open'`, or a `basis`
 * lacking the number(s) it needs). */
function formatTargetCore(target) {
  if (!target) return null;
  if (target.basis === 'zone') return target.zone || null;
  if (target.basis === 'percent_css') {
    if (target.low === null || target.low === undefined) return null;
    const high = target.high !== null && target.high !== undefined && target.high !== target.low
      ? `-${target.high}` : '';
    return `${target.low}${high}% CSS`;
  }
  if (target.basis === 'absolute') {
    if (target.low === null || target.low === undefined) return null;
    const high = target.high !== null && target.high !== undefined && target.high !== target.low
      ? `-${formatPace(target.high)}` : '';
    return `${formatPace(target.low)}${high}/100m`;
  }
  if (target.basis === 'rpe') return 'RPE';
  return null; // basis === 'open'
}

/** A `WorkoutLoad`'s core resistance text (no leading "@"), or null.
 * `basis === 'bodyweight'` deliberately renders nothing -- it's this
 * codebase's default/uninteresting case (see `_strength_session_structure_
 * template`'s doc comment: every real strength exercise today is
 * bodyweight/band-based), so surfacing it on every single exercise line
 * would be noise rather than signal; `percent_1rm`/`absolute`/`rpe_only` are
 * all genuinely informative and shown. */
function formatLoadCore(load) {
  if (!load) return null;
  if (load.basis === 'percent_1rm') {
    return load.value !== null && load.value !== undefined ? `${load.value}% 1RM` : null;
  }
  if (load.basis === 'absolute') {
    return load.value !== null && load.value !== undefined ? `${load.value} kg` : null;
  }
  if (load.basis === 'rpe_only') return 'RPE';
  return null; // basis === 'bodyweight'
}

/** One `WorkoutStep`'s secondary annotation line -- duration, then target OR
 * load (a step is swim-shaped or strength-shaped, never carries both
 * meaningfully), then non-default stroke/equipment -- joined with " · ", or
 * null when there's nothing beyond the label worth showing. Kept separate
 * from the step's `text` (its label) so callers (renderStructuredStep below)
 * can lay the two out differently -- e.g. label as the line's main text,
 * detail as a smaller/mono trailing badge -- without string-surgery.
 *
 * Returns null unconditionally for a TOP-LEVEL narrated step (depth 0,
 * role in `STRUCTURED_ROLE_PREFIX`): real generated content (see
 * `render_main_set`) always bakes its full distance AND target/pace into
 * that step's `label` already (e.g. "9 x 300m @ Z2 (1:35-1:39/100m), 15s
 * rest..."), so composing a duration/target annotation from the raw fields
 * here would just repeat what the label already says. Every other step
 * (nested per-rep children under a `WorkoutRepeat`, and non-narrated roles
 * like rest/steady) has a short, non-descriptive `label` and genuinely
 * needs this annotation to be readable -- see e.g. "Rest 15s". */
function structuredStepDetail(step, depth) {
  if (depth === 0 && Object.prototype.hasOwnProperty.call(STRUCTURED_ROLE_PREFIX, step.role)) return null;
  const parts = [];
  const durationText = formatStepDuration(step.duration_kind, step.duration_value);
  if (durationText) parts.push(durationText);
  const targetCore = formatTargetCore(step.target);
  const loadCore = targetCore ? null : formatLoadCore(step.load);
  if (targetCore) parts.push(`@ ${targetCore}`);
  else if (loadCore) parts.push(`@ ${loadCore}`);
  if (step.stroke && step.stroke !== 'free') parts.push(capitalize(step.stroke));
  if (step.equipment && step.equipment.length > 0) parts.push(step.equipment.join(', '));
  return parts.length > 0 ? parts.join(' · ') : null;
}

/** One line for a `WorkoutStep` node: `{ depth, kind: 'step', text, detail }`.
 * `text` is the step's label, prefixed for a top-level warmup/interval/
 * cooldown step (see `STRUCTURED_ROLE_PREFIX`); `detail` is the secondary
 * duration/target/load annotation from `structuredStepDetail`, or null. */
function renderStructuredStep(step, depth) {
  const prefix = depth === 0 ? (STRUCTURED_ROLE_PREFIX[step.role] || '') : '';
  return { depth, kind: 'step', text: `${prefix}${step.label}`, detail: structuredStepDetail(step, depth) };
}

/** One header line for a `WorkoutRepeat` node: `{ depth, kind: 'repeat',
 * text, detail: null }`. `text` always ends in ':' (introducing its indented
 * children, matching this codebase's existing heading convention -- see
 * `_strength_session_structure_template`'s own "...(2 sets x 10 reps each):"
 * label). Framing comes entirely from `repeat_mode`:
 *  - "count": "{count} x:" (falls back to "? x:" if count is somehow null).
 *  - "for_duration": EMOM-style -- "every {interval_s}s" is the defining
 *    trait, so it always shows; the round count is derived (duration_s /
 *    interval_s) when both are known, e.g. "EMOM x10 (every 60s):".
 *  - "amrap": "AMRAP for {mm:ss}:", or bare "AMRAP:" if duration_s is
 *    missing. */
function renderStructuredRepeatHeader(repeat, depth) {
  let text;
  if (repeat.repeat_mode === 'for_duration') {
    const hasInterval = repeat.interval_s !== null && repeat.interval_s !== undefined;
    const rounds = hasInterval && repeat.duration_s !== null && repeat.duration_s !== undefined
      ? Math.round(repeat.duration_s / repeat.interval_s) : null;
    if (hasInterval) {
      text = rounds !== null
        ? `EMOM x${rounds} (every ${Math.round(repeat.interval_s)}s)`
        : `EMOM (every ${Math.round(repeat.interval_s)}s)`;
    } else {
      text = repeat.duration_s !== null && repeat.duration_s !== undefined
        ? `For ${formatSecondsClock(repeat.duration_s)}` : 'For duration';
    }
  } else if (repeat.repeat_mode === 'amrap') {
    text = repeat.duration_s !== null && repeat.duration_s !== undefined
      ? `AMRAP for ${formatSecondsClock(repeat.duration_s)}` : 'AMRAP';
  } else {
    text = `${repeat.count !== null && repeat.count !== undefined ? repeat.count : '?'} x`;
  }
  return { depth, kind: 'repeat', text: `${text}:`, detail: null };
}

/** Recursively walks a `WorkoutRepeat`/`WorkoutStructure`'s ordered `items`
 * (or `steps`) list into a flat array of `{ depth, kind, text, detail }`
 * lines, one per step/repeat node, each carrying its nesting depth so the
 * caller can indent it -- nested `WorkoutRepeat`s (rare in real content
 * today, but real per the model) recurse to depth+1 exactly the same way. */
function walkStructuredItems(items, depth, out) {
  for (const item of items) {
    if (item.kind === 'repeat') {
      out.push(renderStructuredRepeatHeader(item, depth));
      walkStructuredItems(item.steps, depth + 1, out);
    } else {
      out.push(renderStructuredStep(item, depth));
    }
  }
}

/** Entry point: flattens a `WorkoutStructure` (`{ items: [...] }`) into an
 * ordered array of `{ depth, kind, text, detail }` lines for
 * `views.js`'s `renderStructuredWorkoutView` to lay out as indented HTML.
 * Returns `[]` for a missing/empty structure so callers can render nothing
 * without a null check of their own. */
export function renderStructuredWorkout(structured) {
  if (!structured || !structured.items) return [];
  const out = [];
  walkStructuredItems(structured.items, 0, out);
  return out;
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
