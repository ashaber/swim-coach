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

// Athlete-facing labels for WeekPlan.race_week_checklist item categories
// (engine/swim_coach/models.py's RaceWeekChecklistItem.category) -- see
// library/16-race-week.md for why these three are kept visually distinct
// (different evidence basis, different timing windows) rather than folded
// into one generic "race week" blob.
const RACE_WEEK_CATEGORY_LABELS = {
  carb_load: 'Carb-load',
  bodywork: 'Bodywork',
  logistics: 'Logistics',
};

export function raceWeekCategoryLabel(category) {
  return RACE_WEEK_CATEGORY_LABELS[category] || category;
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
 * lacking the number(s) it needs).
 *
 * `basis === 'rpe'` reuses `low`/`high` the same way `percent_css`/
 * `absolute` do (models.py's `WorkoutTarget` never gave RPE its own
 * numeric field -- `low`/`high` are already generic per-basis floats, so
 * an RPE target just puts a 1-10 value there, the same scale
 * `Workout.rpe` already uses athlete-facing elsewhere in this app). Renders
 * "RPE 6" / "RPE 6-7" when a number is present; falls back to the bare
 * "RPE" label (this function's previous, and only, behavior) when it
 * isn't -- still meaningful on its own ("effort-based, athlete's
 * discretion"), so this deliberately does NOT return null in that case. */
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
  if (target.basis === 'rpe') {
    if (target.low === null || target.low === undefined) return 'RPE';
    const high = target.high !== null && target.high !== undefined && target.high !== target.low
      ? `-${target.high}` : '';
    return `RPE ${target.low}${high}`;
  }
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

// --- Per-step coaching cues (expand-on-tap technique content) -------------
// Real, specific technique cues for the drill/set-type vocabulary that
// actually appears in this codebase's engine-generated content -- see
// engine/swim_coach/workout_templates/*.yaml's narrative_template strings
// (broken-distance, descend, pyramid, negative-split, the pull/kick/plain
// ladder variants, fins-assisted, backstroke recovery, breathing-pattern
// constraint, race-pace/sprint effort) and plan.py's STRENGTH_CORE_EXERCISES
// / STRENGTH_FULL_BODY_ADDITION (matched by the step's own `exercise_name`,
// a fixed canonical string, not fuzzy label text). Coach-voice, 1-3
// sentences, genuine technique-coaching consensus -- no citation fabricated
// here, matching plan.py's own STRENGTH_EXERCISE_REFERENCE_URLS comment's
// precedent that a technique/form note isn't the kind of claim CLAUDE.md's
// [EVIDENCE]/[ADAPTED] tagging governs (that's for claims driving engine
// constants/prescriptions, not "here's how to execute this move").
//
// Deliberately NOT exhaustive and NOT a generic per-role fallback (e.g. no
// blanket "ease into it" cue for every untagged warmup/cooldown step) -- an
// unmatched step just has no cue and stays a plain, non-expandable line
// (see `renderStructuredStep` below and views.js's `renderStructuredLine`).
// A made-up generic cue would be exactly the "generic placeholder" this
// feature was asked to avoid.

/** Exact-match cues keyed by `WorkoutStep.exercise_name` -- the canonical
 * strings plan.py's `STRENGTH_CORE_EXERCISES`/`STRENGTH_FULL_BODY_ADDITION`
 * actually emit (kept byte-identical to those tuples, including the
 * degree sign and curly-quoted "Ts"/"Ys" labels, so a real generated step
 * always matches). */
const STRENGTH_EXERCISE_CUES = {
  'Internal rotation at 90° abduction':
    'Elbow pinned at your side, forearm out at 90° -- rotate it in toward your stomach and back out, slow and controlled. This is a small, precise motion, not a big swing.',
  'External rotation at 90° abduction':
    'Elbow pinned at your side, forearm out at 90° -- rotate it away from your stomach against light resistance, then control the return just as carefully as the pull.',
  'Scapular punches':
    'Lying on your back, punch straight up toward the ceiling, letting your shoulder blade round forward at the top -- think "push the floor away," then control the return.',
  'Scapular retraction ("Ts")':
    'Face down, raise the arms straight out to the sides to form a T, squeezing the shoulder blades together at the top -- pause briefly before lowering, no momentum.',
  'Retraction with upward rotation ("Ys")':
    'Face down, raise the arms overhead in a Y shape with thumbs up, squeezing the lower traps -- slow and controlled, not a swing up and drop down.',
  '3 x 10 goblet squat or bodyweight squat':
    'Hold the weight at chest height (or hands together if bodyweight), sit the hips back and down, chest tall, knees tracking over the toes rather than caving in.',
  '3 x 10 per side single-leg Romanian deadlift (or bodyweight equivalent)':
    'Hinge at the hip on one leg with a soft bend in the standing knee, back flat, letting the free leg extend behind you for balance -- it\'s a hip hinge, not a balance trick.',
  '3 x 10 plank or dead-bug core hold (30-45s each side)':
    'Keep the low back pressed flat and the hips level throughout -- planking, don\'t let the hips sag; dead-bugging, move the opposite arm and leg slowly without the low back arching off the floor.',
};

/** Ordered, first-match-wins keyword cues for the real main-set format
 * vocabulary (see engine/swim_coach/workout_templates/*.yaml's
 * `narrative_template` strings). More specific multi-word patterns are
 * checked before the generic single-word ones they'd otherwise be masked
 * by (e.g. "descending-distance pull ladder" would also match a bare
 * `/ladder/` or `/pull/` test, so the pull-ladder-specific cue is checked
 * first) -- one real, accurate cue per line, not an attempt to cue every
 * technique element a compound label happens to mention.
 *
 * `broken-distance` is checked only AFTER pyramid/negative-split/descend/
 * ladder, not before them -- every real build/peak/taper template's
 * narrative describes itself as "broken-distance" as a base characteristic
 * (see e.g. build-0-descend's/build-3-negative-split's own narrative_
 * template strings), so checking it first would mask the template's actual
 * distinguishing shape on nearly every build-block label. It still fires on
 * its own for base-1-broken-distance-lite, the one real template where
 * broken-distance genuinely IS the whole story (no descend/pyramid/ladder/
 * negative-split on top of it).
 *
 * `negative-split` is checked before the generic `descend` -- important,
 * not just tie-breaking: build-3-negative-split's real narrative literally
 * contains the substring "descend" (in "...no descend-across-reps
 * progression, distinct from build-0-descend"), which would otherwise
 * false-positive-match the plain descend rule and cue the athlete with the
 * exact behavior that template's own docstring says it deliberately is
 * NOT. */
const SWIM_SET_TYPE_CUES = [
  {
    test: /pull ladder/i,
    cue: 'Pull ladder -- pull buoy in, legs quiet, all the effort into catch and pull-through as the distance shrinks. A shorter rung is not license to kick to compensate.',
  },
  {
    test: /kick ladder/i,
    cue: 'Kick ladder -- hold the same sprint-character kick effort on every rung regardless of distance. Drive from the hips, keep ankles loose and pointed rather than flexed.',
  },
  {
    test: /ladder|climbing pairs/i,
    cue: 'Ladder set -- the distance changes rep to rep, but your pace target per 100m holds steady throughout. A shorter rep is not an invitation to sprint it.',
  },
  {
    test: /pyramid/i,
    cue: 'Pyramid -- effort ramps up toward the middle of the set and eases back down. Go out conservatively; the point is having something left to peak with on the middle reps.',
  },
  {
    test: /negative-split/i,
    cue: 'Negative-split -- swim the second half of each rep faster than the first half. Resist going out hard; the whole point is finishing stronger than you started.',
  },
  {
    test: /descend/i,
    cue: 'Descend -- each rep (or block of reps) gets a little faster than the last while effort feels the same. Start controlled so there\'s real room left to descend by the final rep.',
  },
  {
    test: /broken-distance/i,
    cue: 'Broken-distance -- a few seconds\' rest mid-rep, but hold the exact same pace across the break as if it were continuous. The rest is there for pace consistency, not recovery.',
  },
  {
    test: /fins-assisted|fins-on/i,
    cue: 'Fins-assisted -- the extra propulsion and ankle range of motion is there to reinforce a strong, steady kick rhythm, not just to make you swim faster.',
  },
  {
    test: /backstroke recovery|recovery-paced backstroke|easy backstroke/i,
    cue: 'Easy backstroke -- this is active recovery between hard efforts, not a second work interval. Keep it loose and relaxed, well off race pace.',
  },
  {
    test: /breathing-pattern|breathing constraint/i,
    cue: 'Breathing-pattern constraint -- hold the prescribed stroke count between breaths. If your form starts to break down, breathe more often rather than muscling through it.',
  },
  {
    test: /race-pace effort|sprint effort/i,
    cue: 'Race/sprint-pace effort -- swim the pace you\'d actually target on the day, not an all-out max. The generous rest between reps is there so quality holds rep to rep.',
  },
  {
    test: /\bkick\b/i,
    cue: 'Kick set -- drive from the hips, not just the knees. Keep ankles relaxed and pointed rather than flexed.',
  },
  {
    test: /\bpull\b/i,
    cue: 'Pull set -- pull buoy between the thighs, legs quiet. Put the effort into catch and pull-through, not compensating with a kick.',
  },
];

/** A step's real, specific coaching cue, or `null` when nothing in the
 * vocabulary above matches -- see this section's module comment for why an
 * unmatched step gets no cue rather than a fabricated generic one.
 * Strength steps are matched ONLY by exact `exercise_name` (never by label
 * keyword-matching against the swim vocabulary above, which would produce
 * nonsense like matching "Band pull-apart" against the swim pull-set cue). */
export function stepCoachingCue(step) {
  if (!step) return null;
  if (step.modality === 'strength') {
    return (step.exercise_name && STRENGTH_EXERCISE_CUES[step.exercise_name]) || null;
  }
  const label = step.label || '';
  for (const { test, cue } of SWIM_SET_TYPE_CUES) {
    if (test.test(label)) return cue;
  }
  return null;
}

/** One line for a `WorkoutStep` node: `{ depth, kind: 'step', text, detail }`,
 * plus `referenceUrl` when the step carries one and `cue` when
 * `stepCoachingCue` finds real technique content for it. `text` is the
 * step's label, prefixed for a top-level warmup/interval/cooldown step (see
 * `STRUCTURED_ROLE_PREFIX`); `detail` is the secondary duration/target/load
 * annotation from `structuredStepDetail`, or null. `referenceUrl` mirrors
 * `step.reference_url` (models.py's `WorkoutStep.reference_url` -- a coach-
 * or engine-set technique/demo link, e.g. plan.py's
 * `STRENGTH_EXERCISE_REFERENCE_URLS`) verbatim onto the line when present;
 * left unset (not `null`) when the step has none, so existing line-shape
 * assertions elsewhere that don't mention it keep passing. Same convention
 * for `cue`. views.js's `renderStructuredLine` renders `referenceUrl` as
 * the step's clickable link, and renders a line carrying `cue` as an
 * expandable `<details>` (collapsed line by default, cue text on tap). */
function renderStructuredStep(step, depth) {
  const prefix = depth === 0 ? (STRUCTURED_ROLE_PREFIX[step.role] || '') : '';
  const line = { depth, kind: 'step', text: `${prefix}${step.label}`, detail: structuredStepDetail(step, depth) };
  if (step.reference_url) line.referenceUrl = step.reference_url;
  const cue = stepCoachingCue(step);
  if (cue) line.cue = cue;
  return line;
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

/** Splits a `WorkoutStructure`'s top-level `items` into `{ items, rationale }`
 * -- `rationale` is the trailing top-level `role: "open"` step's label with
 * its leading "Why:" stripped, or `null` when no such step is present (a
 * structured session authored without one, e.g. a coach-authored ad hoc
 * `session_overrides.structured` payload). `items` is the same list with
 * that one step removed.
 *
 * plan.py's `_additional_swim_structure_template` and
 * `_strength_session_structure_template` both append exactly this shape --
 * a final `WorkoutStep(label="Why: ...", role="open", duration_kind="open")`
 * -- as their structured content's last top-level item (see those
 * functions' own docstrings for the citations/rationale text itself). Left
 * where it is, that step renders as just another undifferentiated line
 * inside the generic Workout tree-walk; splitting it out is what lets a
 * structured-IR session get the exact same "Training rationale" heading
 * legacy prose's `Why:` block gets (views.js's `renderStructureBlock`),
 * instead of the rationale being indistinguishable from a real step.
 *
 * Only ever strips a TOP-LEVEL (not nested-under-a-repeat) step -- a
 * "Why:"-labelled step nested inside a `WorkoutRepeat` would be a real (if
 * oddly authored) per-rep instruction, not session-level rationale, so it's
 * left in place. Scans from the end and stops at the first match (today's
 * real content has at most one); a second one -- not producible by any real
 * generator today, but not forbidden by the model either -- would stay in
 * the workout list rather than being silently dropped. */
export function splitStructuredRationale(structured) {
  if (!structured || !structured.items) return { items: [], rationale: null };
  const items = structured.items;
  for (let i = items.length - 1; i >= 0; i--) {
    const item = items[i];
    if (item.kind === 'step' && item.role === 'open' && typeof item.label === 'string' && item.label.startsWith('Why:')) {
      return {
        items: [...items.slice(0, i), ...items.slice(i + 1)],
        rationale: item.label.slice('Why:'.length).trim(),
      };
    }
  }
  return { items, rationale: null };
}

// --- Per-session zone-distribution summary ---------------------------------
// Given a session's WorkoutStructure, how much time/distance was spent at
// each intensity -- a pure aggregation over existing WorkoutStep/
// WorkoutRepeat fields (no new model fields needed). Answers "where did the
// work actually go" at a glance, distinct from renderStructuredWorkout's
// step-by-step instructions above.

/** The bucket a step's target sorts into: its Z-zone when tagged (a
 * `basis="zone"` step's `zone` field, OR a `basis="absolute"` step's `zone`
 * field -- `workout_templates.resolve_template`'s `model_copy(update=...)`
 * only overwrites `basis`/`low`/`high` when resolving a zone target, so the
 * original `zone` tag survives resolution untouched; this is what lets a
 * RESOLVED, athlete-facing workout's steps still bucket by zone correctly,
 * not just an unresolved template's), else `"RPE"`/`"% CSS"` for those
 * relative bases untagged with a zone, else `"Open"` for anything else
 * (no target at all, or `basis === "open"`). Strength `load`-based dosing
 * isn't a zone concept -- callers exclude `modality === "strength"` steps
 * before reaching here (see `sessionZoneDistribution`). */
function zoneDistributionBucketFor(target) {
  if (target && target.zone) return target.zone;
  if (target && target.basis === 'rpe') return 'RPE';
  if (target && target.basis === 'percent_css') return '% CSS';
  return 'Open';
}

const ZONE_DISTRIBUTION_BUCKET_ORDER = ['Z1', 'Z2', 'Z3', 'Z4', 'Z5', '% CSS', 'RPE', 'Open'];

/** Adds one step's duration into `buckets` (a `Map<bucket, { distance_m,
 * duration_s }>`), scaled by `multiplier` (the number of times this step
 * actually repeats -- see `walkForZoneDistribution`'s handling of a
 * `WorkoutRepeat(repeat_mode="count")`). Only `distance_m`/`time_s`
 * duration_kinds contribute -- `reps`/`open` have nothing to sum in either
 * unit, and every real strength step uses one of those two, so excluding
 * `modality === "strength"` up front isn't strictly required for real
 * content today, but is kept explicit (reps-based dosing genuinely isn't a
 * "zone" concept) rather than relying on that coincidence. */
function addStepToZoneDistribution(step, multiplier, buckets) {
  if (step.modality === 'strength') return;
  if (step.duration_value === null || step.duration_value === undefined) return;
  if (step.duration_kind !== 'distance_m' && step.duration_kind !== 'time_s') return;
  const bucket = zoneDistributionBucketFor(step.target);
  const entry = buckets.get(bucket) || { distance_m: 0, duration_s: 0 };
  if (step.duration_kind === 'distance_m') entry.distance_m += step.duration_value * multiplier;
  else entry.duration_s += step.duration_value * multiplier;
  buckets.set(bucket, entry);
}

/** Walks `items` accumulating into `buckets`. A `WorkoutRepeat` multiplies
 * its children's contribution by `count` for `repeat_mode === "count"` (the
 * common "4 x 100m" shape -- each child step's `duration_value` is ONE
 * repetition's worth, e.g. plan.py's engine-authored strength template, or
 * a coach-authored `session_overrides.structured` swim repeat). "for_
 * duration"/"amrap" repeats have no well-defined per-child repetition
 * count (an EMOM's round count isn't "how many times does this step run",
 * and an AMRAP's is genuinely unknown ahead of time), so their children are
 * counted once each -- an intentional undercount for those rarer loop
 * shapes, not a bug. */
function walkForZoneDistribution(items, multiplier, buckets) {
  for (const item of items) {
    if (item.kind === 'repeat') {
      const childMultiplier = item.repeat_mode === 'count' && item.count
        ? multiplier * item.count
        : multiplier;
      walkForZoneDistribution(item.steps, childMultiplier, buckets);
    } else {
      addStepToZoneDistribution(item, multiplier, buckets);
    }
  }
}

/** Entry point: total distance/time spent in each intensity bucket across a
 * session's `WorkoutStructure`, as an ordered array of `{ bucket,
 * distance_m, duration_s }` (Z1..Z5, then "% CSS", "RPE", "Open" --
 * `ZONE_DISTRIBUTION_BUCKET_ORDER` -- omitting any bucket nothing landed
 * in). `distance_m`/`duration_s` are `null`, not `0`, when that unit has no
 * contribution in a bucket, matching this file's usual "null means nothing
 * to show" convention (see `formatDistance`) rather than callers having to
 * treat a real `0` and "not applicable" as the same thing. Returns `[]` for
 * a missing/empty structure, same defensive contract as
 * `renderStructuredWorkout`. */
export function sessionZoneDistribution(structured) {
  if (!structured || !structured.items) return [];
  const buckets = new Map();
  walkForZoneDistribution(structured.items, 1, buckets);
  return ZONE_DISTRIBUTION_BUCKET_ORDER
    .filter((bucket) => buckets.has(bucket))
    .map((bucket) => {
      const { distance_m, duration_s } = buckets.get(bucket);
      return { bucket, distance_m: distance_m || null, duration_s: duration_s || null };
    });
}

/** One zone-distribution entry as compact text, e.g. "1,600 m" or "25 min"
 * -- both joined with " + " on the rare bucket carrying both units (a
 * session mixing a distance-based and a time-based step in the same
 * bucket). */
function formatZoneDistributionEntry(entry) {
  const parts = [];
  if (entry.distance_m) parts.push(formatDistance(entry.distance_m));
  if (entry.duration_s) parts.push(formatDuration(entry.duration_s / 60));
  return parts.join(' + ');
}

/** `sessionZoneDistribution`'s entries as one compact summary line, e.g.
 * "Z1: 10 min, Z2: 25 min, Z4: 8 min" -- the plan brief's own illustrative
 * shape. Returns `''` for no entries so callers can render nothing without
 * a length check of their own. */
export function formatZoneDistributionSummary(entries) {
  return entries.map((e) => `${e.bucket}: ${formatZoneDistributionEntry(e)}`).join(', ');
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

/** Weeks ordered chronologically. `iso_week` strings are zero-padded
 * (`2026-W02`), so a plain lexicographic sort is already chronological.
 * Copies rather than sorting in place -- callers pass the shared plan data. */
export function sortedByIsoWeek(weeks) {
  if (!weeks) return [];
  return [...weeks].sort((a, b) => a.iso_week.localeCompare(b.iso_week));
}

/** Pick the "current" and "next" week from a list, sorted by iso_week, by
 * comparing each week's Monday against `now`. "Current" is the earliest
 * week whose Sunday hasn't passed yet.
 *
 * When EVERY week on file has already elapsed, this returns
 * `{ current: null, next: null, stale: true }` -- deliberately nothing to
 * render as "this week". It used to fall back to the last two weeks
 * instead, which produced the 2026-08-18 defect: the athlete's plan data
 * stopped at 2026-W29 while the wall clock was in W34, and the Plan tab
 * showed the five-week-old W29 under a "This week" heading. A stale
 * prescription presented as the current one is worse than an empty state --
 * it hides the fact that no plan was ever generated. `stale` lets the
 * caller tell "your plan has run out" apart from "you have no plan at all"
 * (empty list -> `stale: false`) and word the empty state honestly. */
export function pickCurrentAndNextWeek(weeks, now = new Date()) {
  const sorted = sortedByIsoWeek(weeks);
  if (sorted.length === 0) return { current: null, next: null, stale: false };

  const currentIndex = sorted.findIndex((week) => {
    const sunday = addDays(isoWeekMonday(week.iso_week), 6);
    return daysBetween(now, sunday) >= 0;
  });
  if (currentIndex === -1) return { current: null, next: null, stale: true };

  return {
    current: sorted[currentIndex] || null,
    next: sorted[currentIndex + 1] || null,
    stale: false,
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

// --- Glossary (Plan tab's collapsed "Terms & zones" reference) -------------
// Real values pulled from engine/swim_coach/zones.py's Z1-Z5 offset table
// and library/04-css-intensity-anchors.md's "character" column for each
// zone (the CSS-anchored offsets themselves are cited engine constants
// already -- this is just their athlete-facing gloss, not a new claim), plus
// the abbreviations/terms that actually show up elsewhere in this file's
// own rendering (RPE, % CSS, EMOM/AMRAP -- see renderStructuredRepeatHeader
// above -- and the main-set format vocabulary SWIM_SET_TYPE_CUES already
// covers). Kept as plain data here (plan.js, not views.js) matching this
// file's existing split between data/formatting and markup.

export const ZONE_GLOSSARY = [
  { zone: 'Z1', range: 'CSS +10s/100m and slower', character: 'Easy / recovery' },
  { zone: 'Z2', range: 'CSS +5s to +9s/100m', character: 'Aerobic endurance' },
  { zone: 'Z3', range: 'CSS +2s to +4s/100m', character: 'Tempo / threshold-adjacent' },
  { zone: 'Z4', range: 'CSS -1s to +1s/100m', character: 'At/near CSS (critical velocity)' },
  { zone: 'Z5', range: 'CSS -2s/100m and faster', character: 'Above critical velocity, anaerobic' },
];

export const TERM_GLOSSARY = [
  { term: 'CSS', def: 'Critical Swim Speed -- the pace anchor every zone is offset from, computed from a timed 400m/200m trial (CSS = (t400 - t200) / 2).' },
  { term: '% CSS', def: 'A pace target expressed as a percentage of CSS pace, e.g. 135% CSS, instead of a fixed Z1-Z5 zone.' },
  { term: 'RPE', def: 'Rate of Perceived Exertion, 1-10 -- an effort-based target used when a specific pace target isn\'t the right anchor for the day (e.g. easy/recovery, or pool-coach-assigned content whose actual pace is unknown until delivered).' },
  { term: 'Main set', def: 'The primary training-stimulus portion of a swim session, between the warm-up and cool-down.' },
  { term: 'Broken-distance', def: 'A set split into shorter segments with brief rest between them, to hold the same pace longer than one continuous effort would allow.' },
  { term: 'Descend', def: 'Each rep (or block of reps) in a set gets a little faster than the last while effort feels the same.' },
  { term: 'Negative-split', def: 'Swimming the second half of a rep or set faster than the first half.' },
  { term: 'Pyramid', def: 'Effort ramps up toward the middle of a set, then eases back down.' },
  { term: 'Ladder', def: 'Rep distance changes (climbing or descending) across a set while the pace target holds steady.' },
  { term: 'EMOM', def: '"Every Minute On the Minute" -- a new round starts on a fixed time interval regardless of how long the previous round took.' },
  { term: 'AMRAP', def: '"As Many Rounds/Reps As Possible" within a fixed time window.' },
];

// --- CTL/ATL/TSB training-load chart (Plan tab + coach roster) -------------
// Pure geometry computation for a hand-rolled inline SVG line chart -- no
// charting library (this project's stated minimal-dependency convention;
// web/package.json carries exactly two font packages and nothing
// chart-related). Consumes the `ctl_atl_tsb` series
// `backend/app/context.py`'s `summarize_rollup` returns (surfaced directly
// via the `GET /api/plan/load` / `GET /api/coach/athletes/{slug}/load`
// endpoints) -- `[[dateIso, ctl, atl, tsb], ...]`, ascending by date.
// `views.js`'s `renderLoadChart` turns this geometry into markup; kept
// separate here so the math is unit-testable without a DOM, matching this
// file's existing split from `renderStructuredWorkout` etc.
//
// CTL ("fitness") and ATL ("fatigue") are exponentially-weighted moving
// averages of daily training load (`engine/swim_coach/load.py`'s
// `ctl_atl_tsb_series`); TSB ("form") = CTL - ATL. All three share ONE
// y-axis (same units -- TSB is literally the other two's difference) --
// the standard cycling-coaching "Performance Management Chart" layout.
// Plotting TSB alone would lose exactly the signal that matters: whether a
// rising TSB reflects a real taper (ATL falling while CTL holds) or a
// stale plan (both eroding together).

/** TrainingPeaks/Joe Friel's commonly-cited cycling-coaching "race-day TSB"
 * reference range -- roughly +5 to +25 -- with that same convention's own
 * explicit caveat that individual variation is large (as much as ~15
 * points between athletes) and masters athletes tend toward the higher
 * end. This is a CYCLING-coaching convention: never verified for swimming,
 * never peer-reviewed, and not itself an [EVIDENCE]/[ADAPTED] engine
 * constant (nothing here feeds plan.py's math) -- rendered as a loose
 * reference band, not a target, and `views.js`'s `renderLoadChart` says so
 * in plain language next to it. Same underlying honesty standard as
 * `engine/swim_coach/load.py`'s `CTL_TIME_CONSTANT_DAYS`/
 * `ATL_TIME_CONSTANT_DAYS` module comment (also cycling-borrowed, also
 * unverified for swimming) -- that caveat is repeated in the chart's own
 * caption rather than papered over here. */
export const RACE_DAY_TSB_BAND = { low: 5, high: 25 };

const LOAD_CHART_WIDTH = 640;
const LOAD_CHART_HEIGHT = 260;
// `right` padding matches `left` (rather than the old, tighter 12px) --
// dual-axis rendering (see `ctlAtlTsbChartGeometry` below) needs room for a
// second set of axis-label text on the right edge, same as the left.
const LOAD_CHART_PADDING = { top: 16, right: 34, bottom: 28, left: 34 };
const LOAD_CHART_MAX_X_TICKS = 5;
const LOAD_CHART_Y_TICK_COUNT = 4;

/** Rounds to one decimal -- CTL/ATL/TSB values arrive already 1-decimal
 * rounded from `summarize_rollup`, so axis labels derived from the data's
 * own min/max stay at the same precision rather than growing spurious
 * extra digits from the padding/tick math below. */
function roundToTenth(value) {
  return Math.round(value * 10) / 10;
}

/** At most `maxCount` evenly spaced indices into an `n`-length array,
 * always including index 0 and `n - 1` (so an axis always anchors on the
 * series' real first/last date) -- used for the x-axis date ticks. Falls
 * back to every index when `n <= maxCount`, since there's nothing to
 * thin out. */
function evenIndices(n, maxCount) {
  if (n <= 0) return [];
  if (n <= maxCount) return Array.from({ length: n }, (_, i) => i);
  const picks = [];
  for (let i = 0; i < maxCount; i++) {
    picks.push(Math.round((i / (maxCount - 1)) * (n - 1)));
  }
  return [...new Set(picks)];
}

/** Pure geometry for the CTL/ATL/TSB chart: given `series` (the
 * `ctl_atl_tsb` list from `GET /api/plan/load` /
 * `GET /api/coach/athletes/{slug}/load`), returns everything
 * `views.js`'s `renderLoadChart` needs to draw the SVG -- pixel-space
 * point coordinates for each of the three lines, the race-day reference
 * band's pixel span, and tick marks for both axes -- with no
 * DOM/rendering logic of its own.
 *
 * Returns `{ isEmpty: true, width, height }` for a missing/empty series
 * (no workouts logged yet, or every logged workout falls outside the
 * requested window) rather than erroring or dividing by zero on an empty
 * domain -- callers render an honest "not enough data yet" message
 * instead of a blank or broken chart.
 *
 * **Dual y-axis (readability fix, Build 1 of the wellness-ingestion +
 * training-dashboard plan):** CTL/TSB plot against one ("primary", left)
 * y-axis, ATL against its own independent ("secondary", right) y-axis.
 * This chart's code was independently re-verified end-to-end and had no
 * bug -- the "CTL looks like -ATL" impression athletes reported is a real,
 * expected property of CTL being a 42-day EWMA (inherently small natural
 * range) sharing one axis with ATL, a 7-day EWMA (inherently large natural
 * range), on any real athlete's data. Giving ATL its own scale fixes the
 * readability problem without touching the underlying math: `ctlPoints`/
 * `tsbPoints`/`bandTop`/`bandBottom`/`yTicks` are all in primary-axis pixel
 * space; `atlPoints`/`yTicksSecondary` are in secondary-axis pixel space.
 * The race-day TSB reference band stays on the primary axis (it describes
 * TSB, not ATL) and, per the existing convention, always keeps 0 and the
 * band itself inside the primary domain regardless of the real CTL/TSB
 * data range. */
export function ctlAtlTsbChartGeometry(series, {
  width = LOAD_CHART_WIDTH, height = LOAD_CHART_HEIGHT, padding = LOAD_CHART_PADDING,
} = {}) {
  if (!series || series.length === 0) {
    return { isEmpty: true, width, height };
  }

  const plotW = width - padding.left - padding.right;
  const plotH = height - padding.top - padding.bottom;
  const n = series.length;

  const ctlValues = series.map((p) => p[1]);
  const atlValues = series.map((p) => p[2]);
  const tsbValues = series.map((p) => p[3]);

  // Primary (left) axis domain: CTL + TSB + the race-day band + 0 -- NEVER
  // ATL (see the dual-axis doc comment above). Always includes the band
  // (and 0) so both are visible even for an athlete whose real TSB never
  // gets near them (e.g. deep in a build block) -- context, not just
  // "whatever fits today's data".
  const primaryValues = [
    ...ctlValues, ...tsbValues, RACE_DAY_TSB_BAND.low, RACE_DAY_TSB_BAND.high, 0,
  ];
  const primaryRawMin = Math.min(...primaryValues);
  const primaryRawMax = Math.max(...primaryValues);
  const primarySpan = primaryRawMax - primaryRawMin || 1;
  const yMin = primaryRawMin - primarySpan * 0.08;
  const yMax = primaryRawMax + primarySpan * 0.08;

  // Secondary (right) axis domain: ATL's own min/max only -- deliberately
  // NOT anchored at 0 the way the primary axis is. Forcing a 0 anchor here
  // would recreate exactly the readability problem this dual-axis change
  // exists to fix: a real ATL trace that hovers in a narrow band (e.g.
  // 35-45) would still look flat, dominated by the distance down to 0,
  // same as it looked flat sharing CTL's axis. Scaled completely
  // independently of the primary axis -- a tiny real ATL range gets the
  // full plot height to show its own shape, instead of being flattened by
  // whatever range CTL/TSB happen to span (or by an arbitrary 0 anchor).
  const secondaryValues = [...atlValues];
  const secondaryRawMin = Math.min(...secondaryValues);
  const secondaryRawMax = Math.max(...secondaryValues);
  const secondarySpan = secondaryRawMax - secondaryRawMin || 1;
  const yMinAtl = secondaryRawMin - secondarySpan * 0.08;
  const yMaxAtl = secondaryRawMax + secondarySpan * 0.08;

  const xFor = (i) => (n === 1 ? padding.left + plotW / 2 : padding.left + (i / (n - 1)) * plotW);
  const yFor = (v) => padding.top + (1 - (v - yMin) / (yMax - yMin)) * plotH;
  const yForAtl = (v) => padding.top + (1 - (v - yMinAtl) / (yMaxAtl - yMinAtl)) * plotH;

  const toPoints = (values, yFn) => series.map((_, i) => ({ x: xFor(i), y: yFn(values[i]) }));

  const xTicks = evenIndices(n, LOAD_CHART_MAX_X_TICKS).map((i) => ({ x: xFor(i), label: series[i][0] }));
  const yTicks = Array.from({ length: LOAD_CHART_Y_TICK_COUNT + 1 }, (_, i) => {
    const value = roundToTenth(yMin + (i / LOAD_CHART_Y_TICK_COUNT) * (yMax - yMin));
    return { y: yFor(value), value };
  });
  const yTicksSecondary = Array.from({ length: LOAD_CHART_Y_TICK_COUNT + 1 }, (_, i) => {
    const value = roundToTenth(yMinAtl + (i / LOAD_CHART_Y_TICK_COUNT) * (yMaxAtl - yMinAtl));
    return { y: yForAtl(value), value };
  });

  return {
    isEmpty: false,
    width,
    height,
    plotLeft: padding.left,
    plotRight: width - padding.right,
    plotTop: padding.top,
    plotBottom: height - padding.bottom,
    ctlPoints: toPoints(ctlValues, yFor),
    atlPoints: toPoints(atlValues, yForAtl),
    tsbPoints: toPoints(tsbValues, yFor),
    bandTop: yFor(RACE_DAY_TSB_BAND.high),
    bandBottom: yFor(RACE_DAY_TSB_BAND.low),
    xTicks,
    yTicks,
    yTicksSecondary,
    firstDate: series[0][0],
    lastDate: series[n - 1][0],
  };
}

// --- CTL/ATL/TSB trend narrative ---------------------------------------------
// Pure "what actually happened in this athlete's numbers" summary, computed
// from the same raw `ctl_atl_tsb` series `ctlAtlTsbChartGeometry` above
// turns into chart geometry -- kept here, not in `views.js`, for the same
// DOM-free-unit-testability split this file already uses (see
// `describeWellnessBaselineDeviation` below).
//
// This exists because a hand-written narrative interpretation of this
// chart -- something like "CTL has climbed steadily and consistently...
// ATL is spiky around big training days... TSB has been deeply negative
// most of the block" -- was, in the athlete's own words, "the useful coach
// guidance below the load graph," genuinely more useful day-to-day than
// the generic methodology caption that used to sit directly under the
// chart. `views.js`'s `renderLoadChart` renders this prominently and moves
// that generic caption behind a collapsed disclosure instead.
//
// Returns a small structured description, NOT rendered markup -- `views.js`
// turns each field into copy, matching how it already turns this file's
// `ctlAtlTsbChartGeometry` output into an SVG.

/** `engine/swim_coach/load.py`'s `CTL_TIME_CONSTANT_DAYS` (42) mirrored
 * here for narrative thresholds below -- duplicated, not imported, since
 * this is a JS module and that's Python; keep the two in sync if the
 * engine constant ever changes. HARD RULE, not a judgment call:
 * `ctl_atl_tsb_series`'s own docstring says CTL/ATL "aren't meaningful"
 * before roughly this many days have accumulated -- both series are
 * seeded at 0 and are still climbing from it, not reflecting genuine
 * fitness/fatigue, before this point. */
export const CTL_COLD_START_DAYS = 42;

/** STYLISTIC, not a hard rule: the same docstring says CTL isn't fully
 * "warmed up" until "roughly a few multiples" of `CTL_COLD_START_DAYS`
 * have accumulated, without pinning an exact number. This reads "a few" as
 * 3x -- Coach judgment, chosen so a real ~60-day athlete history (the
 * documented motivating case for this caveat) lands in the middle
 * "warming-up" bucket below, rather than being read with either full
 * confidence or none. */
export const CTL_WARMED_UP_DAYS = CTL_COLD_START_DAYS * 3;

/** Recent-window length (days) used for BOTH the CTL trend comparison and
 * the ATL-spike search below -- Coach judgment, not a sourced constant.
 * The two pieces of narrative are meant to describe the same recent slice
 * of the block, not two arbitrarily different lookbacks; 14 days reads as
 * "long enough to see a real direction, short enough to still be recent."
 * No library citation -- chosen for narrative coherence only. */
export const CTL_ATL_TREND_WINDOW_DAYS = 14;

/** CTL delta (in CTL points) below which the trend reads as "flat" rather
 * than rising/falling -- Coach judgment. CTL is a slow 42-day EWMA, so even
 * a genuinely flat multi-week stretch can drift by a point or two; 3 was
 * chosen as comfortably above that noise floor without requiring a
 * dramatic swing to call a real direction. */
export const CTL_TREND_FLAT_THRESHOLD = 3;

/** `historyDays` -> `'cold-start' | 'warming-up' | 'warmed-up'`, per
 * `CTL_COLD_START_DAYS`/`CTL_WARMED_UP_DAYS` above. */
function classifyCtlWarmup(historyDays) {
  if (historyDays < CTL_COLD_START_DAYS) return 'cold-start';
  if (historyDays < CTL_WARMED_UP_DAYS) return 'warming-up';
  return 'warmed-up';
}

/** Pure trend summary of the raw `ctl_atl_tsb` series -- see module comment
 * above for what this is for. Deliberately date-based throughout (never
 * assumes a fixed day-to-day index spacing) -- `ctl_atl_tsb_series` always
 * walks every calendar day in the real backend, but callers (including
 * this file's own tests) shouldn't have to rely on that to get an honest
 * answer out of a sparser series.
 *
 * Returns:
 *   - `hasData`: `false` for a missing/empty series -- nothing else below
 *     is meaningful then.
 *   - `historyDays`: inclusive calendar-day span from the series' first to
 *     last date (`null` when `!hasData`).
 *   - `warmup`: `'cold-start' | 'warming-up' | 'warmed-up'` (`null` when
 *     `!hasData`) -- see `classifyCtlWarmup`.
 *   - `ctlTrend`: `null` when fewer than 2 points. Otherwise either
 *     `{ status: 'insufficient-window', historyDays, requiredWindowDays }`
 *     when the series doesn't yet span `CTL_ATL_TREND_WINDOW_DAYS` (an
 *     honest "can't do this comparison yet," rather than silently
 *     comparing over a shorter, unstated window), or
 *     `{ status: 'rising' | 'falling' | 'flat', fromDate, toDate,
 *     fromValue, toValue }` with the real before/after numbers so the
 *     magnitude is visible, not just the word.
 *   - `atlSpike`: `null` when fewer than 2 points. Otherwise the single
 *     largest-magnitude day-to-day ATL change within the last
 *     `CTL_ATL_TREND_WINDOW_DAYS` days (falling back to the two most
 *     recent points if the window doesn't contain at least two):
 *     `{ fromDate, toDate, fromValue, toValue, direction: 'up' | 'down' | 'flat' }`.
 *   - `tsb`: `null` only when `!hasData`. Otherwise
 *     `{ date, value, band: 'below' | 'within' | 'above' }` classifying
 *     the latest TSB against `RACE_DAY_TSB_BAND` -- purely descriptive,
 *     NOT a verdict on whether the athlete "should" currently be in that
 *     band (see `RACE_DAY_TSB_BAND`'s own doc comment: it's a race-day
 *     reference, not a general target). Callers must frame a `'below'`
 *     mid-build reading as expected, not as a warning.
 */
export function describeCtlAtlTsbTrend(series) {
  if (!series || series.length === 0) {
    return {
      hasData: false, historyDays: null, warmup: null, ctlTrend: null, atlSpike: null, tsb: null,
    };
  }

  const n = series.length;
  const firstDateObj = parseIsoDate(series[0][0]);
  const lastDateObj = parseIsoDate(series[n - 1][0]);
  const historyDays = daysBetween(firstDateObj, lastDateObj) + 1;
  const warmup = classifyCtlWarmup(historyDays);

  const lastPoint = series[n - 1];
  const lastTsb = lastPoint[3];
  const tsb = {
    date: lastPoint[0],
    value: lastTsb,
    band: lastTsb < RACE_DAY_TSB_BAND.low
      ? 'below'
      : (lastTsb > RACE_DAY_TSB_BAND.high ? 'above' : 'within'),
  };

  if (n < 2) {
    return {
      hasData: true, historyDays, warmup, ctlTrend: null, atlSpike: null, tsb,
    };
  }

  // Target date for both the CTL-trend comparison and the ATL-spike
  // window: `CTL_ATL_TREND_WINDOW_DAYS` before the series' last date.
  const windowStartTarget = addDays(lastDateObj, -CTL_ATL_TREND_WINDOW_DAYS);

  // --- CTL trend: compare the last point to the latest point at/before
  // the window's start. `fromIndex` stays -1 (series ascending by date, so
  // once one date exceeds the target every later one does too) when even
  // the series' first date is after the target -- not enough history yet.
  let fromIndex = -1;
  for (let i = 0; i < n; i++) {
    if (parseIsoDate(series[i][0]) <= windowStartTarget) fromIndex = i;
    else break;
  }

  const ctlTrend = fromIndex === -1
    ? { status: 'insufficient-window', historyDays, requiredWindowDays: CTL_ATL_TREND_WINDOW_DAYS }
    : (() => {
      const fromValue = series[fromIndex][1];
      const toValue = series[n - 1][1];
      const delta = toValue - fromValue;
      const status = Math.abs(delta) < CTL_TREND_FLAT_THRESHOLD
        ? 'flat'
        : (delta > 0 ? 'rising' : 'falling');
      return {
        status, fromDate: series[fromIndex][0], toDate: series[n - 1][0], fromValue, toValue,
      };
    })();

  // --- Biggest ATL swing within the recent window (or the last two
  // points, if the window doesn't contain at least that many).
  let recentStart = 0;
  while (recentStart < n && parseIsoDate(series[recentStart][0]) < windowStartTarget) recentStart++;
  const spikeStart = Math.min(recentStart, n - 2);
  let biggest = { delta: series[spikeStart + 1][2] - series[spikeStart][2], fromIndex: spikeStart, toIndex: spikeStart + 1 };
  for (let i = spikeStart + 1; i < n - 1; i++) {
    const delta = series[i + 1][2] - series[i][2];
    if (Math.abs(delta) > Math.abs(biggest.delta)) biggest = { delta, fromIndex: i, toIndex: i + 1 };
  }
  const atlSpike = {
    fromDate: series[biggest.fromIndex][0],
    toDate: series[biggest.toIndex][0],
    fromValue: series[biggest.fromIndex][2],
    toValue: series[biggest.toIndex][2],
    direction: biggest.delta > 0 ? 'up' : (biggest.delta < 0 ? 'down' : 'flat'),
  };

  return {
    hasData: true, historyDays, warmup, ctlTrend, atlSpike, tsb,
  };
}

// --- Wellness baseline deviation (RHR/HRV cross-check) ----------------------
// Pure classification of `wellness_baseline_deviation`
// (`engine/swim_coach/load.py`'s `wellness_baseline_deviation`, surfaced
// via the same `GET /api/plan/load` / `GET /api/coach/athletes/{slug}/load`
// endpoints as `ctl_atl_tsb` above) into a good/concerning/no-data status
// per field. `views.js`'s `renderLoadChart` turns this into markup, right
// alongside (never blended into) the CTL/ATL/TSB chart above -- kept here,
// not there, for the same DOM-free-unit-testability split
// `ctlAtlTsbChartGeometry` already uses.
//
// Sign conventions are OPPOSITE for the two fields (see
// `wellness_baseline_deviation`'s own docstring for the full citation
// trail): a positive `resting_hr_pct_deviation` is bad (elevated RHR is a
// fatigue signal); a negative `hrv_pct_deviation` is bad (suppressed HRV is
// a fatigue signal). Neither field is flipped/rescaled to force
// "higher = worse" onto both -- each is classified against its own sign.

/** +-5% threshold for flagging a deviation as "concerning" rather than
 * "within normal range" -- Coach judgment, not sourced from a specific
 * library citation, chosen to match this app's existing `formatDrift`
 * (`workouts.js`) 5% cardiac-decoupling threshold for numeric consistency
 * across the app's various "flag past this magnitude" judgment calls. */
export const WELLNESS_DEVIATION_CONCERNING_PCT = 5;

function classifyDeviation(value, isBad) {
  if (value === null || value === undefined) return { value: null, status: 'no-data' };
  return { value, status: isBad(value) ? 'concerning' : 'good' };
}

/** Classifies `wellness_baseline_deviation` (`{resting_hr_pct_deviation,
 * hrv_pct_deviation}`, either field -- or the whole dict -- possibly
 * `null`/absent, e.g. no `resting_hr`/`hrv` logged recently) into
 * `{restingHr, hrv}`, each `{value, status}` where `status` is
 * `'good' | 'concerning' | 'no-data'`. */
export function describeWellnessBaselineDeviation(deviation) {
  const d = deviation || {};
  return {
    restingHr: classifyDeviation(
      d.resting_hr_pct_deviation, (v) => v >= WELLNESS_DEVIATION_CONCERNING_PCT,
    ),
    hrv: classifyDeviation(
      d.hrv_pct_deviation, (v) => v <= -WELLNESS_DEVIATION_CONCERNING_PCT,
    ),
  };
}
