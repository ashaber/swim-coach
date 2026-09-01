// HTML-string view templates. Pure functions of data in, markup out --
// no DOM access here (that's main.js's job).

import {
  formatShortDate, formatLongDate, formatDuration, formatDistance, formatPace,
  parseIsoDate, sessionsByDay, classifySession, sessionDisplay, sessionDotColorVar,
  pickCurrentAndNextWeek, sortedByIsoWeek, daysUntil, macroTargetEvent, currentBlockIndex,
  longSwimLadder,
  findSessionById, parseStructureBlocks, parseMainSetIntervals, renderStructuredWorkout,
  splitStructuredRationale, sessionZoneDistribution, formatZoneDistributionSummary,
  ZONE_GLOSSARY, TERM_GLOSSARY, ctlAtlTsbChartGeometry, raceWeekCategoryLabel,
  describeWellnessBaselineDeviation, describeCtlAtlTsbTrend, RACE_DAY_TSB_BAND,
  PRODUCTIVE_TRAINING_TSB_BAND, LOAD_CHART_WINDOW_DAYS, LOAD_CHART_WINDOW_OPTIONS,
  CTL_ATL_TREND_WINDOW_DAYS, formatMonthLabel,
} from './plan.js';
import { TOOL_LABELS } from './chat.js';
import { buildHistoryFeed } from './history.js';
import {
  sportLabel, sourceBadge, formatWorkoutDistance, formatAnalyticsLine,
  formatDrift, formatSplit, formatPauses, formatSwolf, formatMovingVsElapsed,
  formatOffset, formatClock, formatLengthsSummary, formatSyncResult,
  formatWorkoutChatLabel, HISTORY_DISPLAY_CAP,
} from './workouts.js';

function esc(value) {
  if (value === null || value === undefined) return '';
  return String(value).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

// D2: which of `session_load`'s four fidelity tiers produced a logged
// workout's `load_au` (see `engine/swim_coach/load.py`'s `SessionLoad.tier`
// docstring for what each tier means) -- one shared map instead of
// duplicating it at each of the three UI call sites (renderDetailStats,
// renderWorkoutRow, renderCoachWorkoutRow). `null` for an unrecognized/
// absent tier -- callers render nothing rather than a blank/broken chip.
const LOAD_TIER_LABELS = {
  srpe: 'from RPE',
  hr_trimp: 'from HR',
  pace_if: 'from pace',
  duration: 'estimated',
};

export function loadTierLabel(tier) {
  return LOAD_TIER_LABELS[tier] || null;
}

const SESSION_LEGEND = [
  { colorVar: '--c-pool', label: 'Coached pool (fixed)' },
  { colorVar: '--c-ow', label: 'Open water (AI-set)' },
  { colorVar: '--c-strength', label: 'Strength' },
  { colorVar: '--c-recovery', label: 'Recovery' },
  { colorVar: '--c-signal', label: 'Milestone / race' },
];

function renderMasthead(athlete, event) {
  const days = event ? daysUntil(parseIsoDate(event.event_date)) : null;

  return `
    <header class="mast">
      <div>
        <span class="mark">swim-coach · training plan</span>
        <h1>${esc(athlete.name)}'s plan</h1>
        <p class="sub">${
          event
            ? `Ultra-distance build toward <b>${esc(event.name)}</b>.`
            : 'No events scheduled yet.'
        }</p>
      </div>
      ${event ? `
      <div class="count">
        <div class="n mono">${days}</div>
        <div class="l">days to ${esc(event.name.split(/[—(]/)[0].trim())}</div>
        <div class="d mono">${esc(formatLongDate(parseIsoDate(event.event_date)))}</div>
      </div>` : ''}
    </header>`;
}

function renderSession(session) {
  const classification = classifySession(session);
  const { title, detail } = sessionDisplay(session);
  const dotVar = sessionDotColorVar(session, classification);

  const metaParts = [formatDuration(session.duration_min)];
  const distance = formatDistance(session.distance_m);
  if (distance) metaParts.push(`~${distance}`);
  if (session.intensity?.zone) metaParts.push(`<span class="pill">${esc(session.intensity.zone)}</span>`);
  if (session.source === 'pool_coach') metaParts.push('<span class="pill">coach-set</span>');

  return `
    <div class="sess${classification.highlight ? ' big' : ''}" data-a="session:open" data-id="${esc(session.id)}">
      <span class="dot" style="background:var(${dotVar})"></span>
      <div class="body">
        <div class="title">${esc(title)}${classification.tag ? `<span class="tag">${esc(classification.tag)}</span>` : ''}</div>
        <div class="meta mono">${metaParts.join(' · ')}</div>
        ${detail ? `<div class="desc">${esc(detail)}</div>` : ''}
      </div>
    </div>`;
}

// --- Ask-the-coach Q&A (shared component, coach-mode Q&A build) ------------
// Renders the durable, `Feedback`-backed Q&A thread for ONE specific planned
// session or completed workout -- the real component the workout-detail
// view's old `renderCoachConversationPlaceholder` stub ("coach conversation
// -- coming soon") was gesturing at, plus a brand-new call site on the Plan
// tab's session detail (which had no chat/placeholder at all before this).
// One shared function, three call sites:
//   - `renderPlanSessionDetail` (athlete's own Plan tab): `form` set, wired
//     to `askAboutSession` via a real submit action.
//   - `renderWorkoutDetail` (athlete's own Dashboard tab): `form` set, wired
//     to `askAboutWorkout`.
//   - Both of the above's coach-roster read-only mirrors (a coach viewing a
//     coached athlete's session/workout): `form: null` -- no input box, no
//     submit action. Coach replies stay centralized in the roster's own
//     Feedback section reply UI (renderCoachFeedbackEntry above/below),
//     never duplicated here.
// `questions` is the CALLER's job to have already filtered down to the one
// workout/session this section is scoped to (client-side, against the
// already-fetched GET /api/feedback / GET /api/coach/athletes/<slug>/feedback
// list -- see main.js's renderTabContent/renderRosterTab wiring) -- this
// function itself doesn't know about workout_id/session_date/session_sport
// at all, just renders whatever list it's handed.

/** Shared by `renderAskCoachEntry` below and the athlete's own Feedback tab
 * (`renderFeedbackEntry`) -- EXACTLY one of three answer states (per the
 * branch brief): an AI provisional answer, a human coach reply (which always
 * wins visually over the AI answer if both are present -- a human reply is
 * the more authoritative, final word), or -- when neither exists yet and the
 * question was flagged for human review -- an honest "waiting on your coach"
 * notice. A question that's neither answered nor flagged (freshly asked, AI
 * still running -- can't actually happen given `ask_question` answers
 * synchronously before saving, but defensive nonetheless) renders with no
 * answer section at all rather than a misleading state. */
function renderFeedbackAnswerBlock(entry) {
  if (entry.coach_reply) {
    return `
      <div class="detail-section">
        <h4>Your coach replied</h4>
        <p class="detail-notes">${esc(entry.coach_reply)}</p>
      </div>`;
  }
  if (entry.ai_provisional_answer) {
    return `
      <div class="detail-section">
        <h4>AI provisional answer</h4>
        <p class="detail-notes">${esc(entry.ai_provisional_answer)}</p>
      </div>`;
  }
  if (entry.needs_human_review) {
    return '<p class="sub">Waiting on your coach to reply.</p>';
  }
  return '';
}

/** One past question in the thread: the question body, then its answer
 * state (see `renderFeedbackAnswerBlock`). */
function renderAskCoachEntry(entry) {
  return `
    <div class="panel feedback-entry">
      <p class="feedback-entry-body">${esc(entry.body)}</p>
      ${renderFeedbackAnswerBlock(entry)}
    </div>`;
}

/** Filters a raw `Feedback` list (GET /api/feedback's response shape) down
 * to just the entries linked to one completed Workout, by `workout_id` --
 * see `renderWorkoutDetail`'s call site. */
function feedbackForWorkout(feedback, workoutId) {
  return (feedback || []).filter((entry) => entry.workout_id === workoutId);
}

/** Same idea as `feedbackForWorkout`, for a planned Session instead --
 * linked by `(session_date, session_sport)`, NOT a raw session id (see
 * `Feedback.session_date`'s own doc comment in engine/swim_coach/models.py
 * for why: `Session.id` doesn't survive `replace_week_plan`'s full
 * regenerate, so a raw-id link would silently orphan). */
function feedbackForSession(feedback, date, sport) {
  return (feedback || []).filter((entry) => entry.session_date === date && entry.session_sport === sport);
}

/** `questions`: the (already-filtered) list of past Q&A for this one
 * workout/session, most-recent-first (same order GET /api/feedback already
 * returns). `form`: `{ body }` (the in-progress draft) when this caller
 * wants a real input box, or `null`/`undefined` for a read-only render (the
 * coach's own view of a coached athlete's session/workout). `submit`:
 * `{ status, error }`, same async-state shape as every other form in this
 * app -- ignored when `form` is falsy. */
export function renderAskCoachSection({ questions, form, submit } = {}) {
  const list = (questions && questions.length > 0)
    ? questions.map(renderAskCoachEntry).join('')
    : '<p class="sub">Nothing asked yet.</p>';

  return `
    <section class="detail-section" id="ask-coach">
      <h4>Ask your coach</h4>
      ${list}
      ${form ? `
      <label class="field">
        <span>Ask a question about this</span>
        <textarea rows="3" data-form="askCoach" data-field="body" placeholder="What do you want to know?">${esc(form.body)}</textarea>
      </label>
      <div class="settings-actions">
        <button type="button" class="btn" data-a="ask-coach:submit" ${submit?.status === 'submitting' ? 'disabled' : ''}>${submit?.status === 'submitting' ? 'Asking…' : 'Ask'}</button>
      </div>
      ${submit?.status === 'error' ? `<div class="conn-result fail">${esc(submit.error)}</div>` : ''}` : ''}
    </section>`;
}

// --- Plan session detail view (tapping a session row) ---------------------
// Mirrors the workout-detail pattern (renderWorkoutDetail below) exactly:
// a full in-tab view swap driven by main.js's state.planSessionDetailId,
// rather than a modal/overlay (there's no such component anywhere in this
// app -- see renderWeeksSection's wiring, which swaps to this the same way
// renderTrainingDashboardBody swaps to renderWorkoutDetail).

function renderPlanSessionDetailStats(session) {
  const stats = [
    renderDetailStat('Duration', formatDuration(session.duration_min)),
    renderDetailStat('Distance', formatDistance(session.distance_m)),
    renderDetailStat('Zone', session.intensity?.zone || null),
    renderDetailStat('Source', session.source === 'pool_coach' ? 'Coach-set' : null),
    // D1: pure display of `session_target_load_au`, computed server-side
    // and attached on-the-fly to every exported session (see
    // scripts/export_plan_json.py's export_athlete) -- no client
    // computation, no persisted field to be stale against.
    renderDetailStat('Target load (AU)', session.target_load_au),
  ].join('');
  return `<div class="detail-stats">${stats}</div>`;
}

/** "Where did the work actually go" -- plan.js's `sessionZoneDistribution`
 * pure aggregation, rendered as one compact line. Only meaningful for a
 * session carrying `structured` (a legacy prose-only session has no
 * per-step target data to bucket) -- callers gate on that the same way they
 * gate the Garmin export buttons. Renders nothing when the computed summary
 * has no entries (e.g. an all-reps/open-duration structure, or the
 * structured tree is empty). */
function renderZoneDistributionSummary(structured) {
  const entries = sessionZoneDistribution(structured);
  if (entries.length === 0) return '';
  return `
    <section class="detail-section">
      <h4>Zone breakdown</h4>
      <p class="detail-notes mono">${esc(formatZoneDistributionSummary(entries))}</p>
    </section>`;
}

/** Renders one `parseStructureBlocks` block as its own titled
 * `.detail-section` (same style as the workout-detail view's sections, see
 * renderWorkoutDetail, for visual consistency). The `Why:` block gets a
 * distinct heading ("Training rationale") -- visually separate from the
 * Warm-up/Main-set/Cool-down instruction blocks, since it's rationale/
 * citation text, not an instruction. The `Main set` block additionally
 * sub-parses its content into distinct numbered interval items via
 * parseMainSetIntervals (today's real engine output only ever produces one,
 * but this renders 2+ just as well the moment a future engine change emits
 * them -- see that function's own doc comment). A block with no recognized
 * label at all (parseStructureBlocks' graceful-degradation case) falls back
 * to the original flat "Structure" heading. */
function renderStructureBlock(block) {
  if (block.label === null) {
    return `
    <section class="detail-section">
      <h4>Structure</h4>
      <p class="detail-notes">${esc(block.content)}</p>
    </section>`;
  }
  if (block.label === 'Why') {
    return `
    <section class="detail-section">
      <h4>Training rationale</h4>
      <p class="detail-notes">${esc(block.content)}</p>
    </section>`;
  }
  if (block.label === 'Main set') {
    const items = parseMainSetIntervals(block.content).map((interval, i) => `
      <div class="detail-interval">
        <div class="detail-interval-label">Interval ${i + 1}</div>
        <p class="detail-notes">${esc(interval)}</p>
      </div>`).join('');
    return `
    <section class="detail-section">
      <h4>Main set</h4>
      ${items}
    </section>`;
  }
  return `
    <section class="detail-section">
      <h4>${esc(block.label)}</h4>
      <p class="detail-notes">${esc(block.content)}</p>
    </section>`;
}

/** A URL safe to put in an `href`, or null if it isn't one.
 *
 * `esc()` is NOT sufficient on its own here. Escaping defuses quote/angle-
 * bracket injection *into the attribute*, but `href="javascript:alert(1)"`
 * needs no escaping to be dangerous -- the browser executes it on tap
 * regardless. `WorkoutStep.reference_url` is a plain `str` with no
 * validation (models.py keeps optional fields loose on purpose) and is
 * reachable from a coach-authored `session_overrides.structured` payload,
 * so the scheme has to be rejected outright rather than merely escaped.
 *
 * Allow-list, not deny-list: only `http:`/`https:` pass. Parsed with `URL`
 * rather than a string prefix check, so casing, leading/trailing
 * whitespace, and percent-encoding tricks all normalize before the
 * comparison instead of slipping past a naive `startsWith`. A rejected or
 * unparseable URL returns null and the caller falls back to plain text --
 * the athlete still sees the exercise, just without a link. */
function safeHref(url) {
  if (!url) return null;
  try {
    const parsed = new URL(String(url).trim());
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : null;
  } catch {
    return null; // relative or malformed -- nothing safe to link to
  }
}

/** One `renderStructuredWorkout` line as its own indented div -- a repeat's
 * header (e.g. "3 x:", "EMOM x10 (every 60s):") or a step's label, each with
 * an optional secondary `.struct-detail` badge (duration/target/load) laid
 * out as its own small span rather than string-concatenated into `text`, so
 * CSS can style the two differently (see index.html's `.struct-*` rules).
 * Indentation is `line.depth` steps of 18px, inline (no new CSS class per
 * depth needed for what's expected to stay a small handful of levels).
 *
 * When `line.referenceUrl` is present (plan.js's `renderStructuredStep`
 * threading `WorkoutStep.reference_url` through -- a coach- or engine-set
 * technique/demo link), the step text renders as a real `<a>` instead of a
 * plain `<span>`, opening in a new tab (`target="_blank"`, with
 * `rel="noopener noreferrer"` since it's an external URL). Same
 * `.struct-text` class either way, so layout is unchanged. A URL that isn't
 * a safe http(s) link renders as the plain span instead -- see `safeHref`.
 *
 * When `line.cue` is present (plan.js's `stepCoachingCue` -- a real,
 * specific technique/coaching cue for this step's drill/set type, only set
 * when the vocabulary actually has one), the whole line becomes a native
 * `<details>`/`<summary>` -- collapsed by default (just the label/detail,
 * identical markup to the plain-line case), the cue text revealed on tap.
 * Native `<details>`, not a click handler, matching this app's only other
 * expand/collapse affordance (`renderAllWeeksAccordion`'s `.all-weeks`) --
 * works with no JS wiring, keyboard-accessible for free, and survives
 * offline. A line with no cue renders exactly as before (a plain `<div>`,
 * not wrapped in `<details>`) -- most lines (anything not matching the real
 * drill/set-type vocabulary) have nothing to expand into. */
function renderStructuredLine(line) {
  const cls = line.kind === 'repeat' ? 'struct-line struct-line-repeat' : 'struct-line struct-line-step';
  const detail = line.detail ? `<span class="struct-detail mono">${esc(line.detail)}</span>` : '';
  const href = safeHref(line.referenceUrl);
  const text = href
    ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer" class="struct-text">${esc(line.text)}</a>`
    : `<span class="struct-text">${esc(line.text)}</span>`;
  if (line.cue) {
    return `
      <details class="${cls} struct-step-toggle" style="padding-left:${line.depth * 18}px">
        <summary class="struct-summary">${text}${detail}</summary>
        <p class="struct-cue">${esc(line.cue)}</p>
      </details>`;
  }
  return `
      <div class="${cls}" style="padding-left:${line.depth * 18}px">
        ${text}${detail}
      </div>`;
}

/** Phase A's structured-IR rendering: a simple, generic tree-walk over
 * `session.structured` (see plan.js's `renderStructuredWorkout` for the
 * actual tree-walking logic -- this just lays its flat `{ depth, kind,
 * text, detail }` lines out as HTML). Deliberately NOT the polished
 * per-block Warm-up/Main-set/Cool-down design `renderStructureBlock` above
 * produces from prose -- that's Phase B's job, a separate follow-up pass.
 * Returns '' for an empty tree (defensive; `renderPlanSessionDetail` only
 * calls this once it's already confirmed `structured.items` is non-empty). */
function renderStructuredWorkoutSection(structured) {
  const lines = renderStructuredWorkout(structured);
  if (lines.length === 0) return '';
  return `
    <section class="detail-section">
      <h4>Workout</h4>
      <div class="struct-tree">${lines.map(renderStructuredLine).join('')}</div>
    </section>`;
}

/** Renders `structure`/`detail` as their own labeled sections. Two rendering
 * paths for the workout-content section, in priority order:
 *  - `session.structured` present (PR #91's `WorkoutStructure` IR, with at
 *    least one item): rendered via `renderStructuredWorkoutSection`'s
 *    generic tree-walk -- Phase A of the migration off prose-regex-parsing
 *    (see plan.js's tree-walk section doc comment for the phased rationale)
 *    -- MINUS its trailing "Why: ..." step, if it has one (split out by
 *    plan.js's `splitStructuredRationale`), which instead renders as its own
 *    "Training rationale" section via `renderStructureBlock({ label: 'Why',
 *    ... })` -- the exact same heading/markup the legacy prose path's own
 *    `Why:` block gets below, so the athlete sees consistent "Training
 *    rationale" treatment regardless of which representation a session
 *    uses (previously: only the legacy prose path got this heading at all).
 *  - Otherwise (legacy session predating `structured`, or a real `None`):
 *    falls back to today's `parseStructureBlocks`/`renderStructureBlock`
 *    prose rendering, unchanged.
 * `structure` (the prose string) is still used for the title/purpose logic
 * below regardless of which path renders the body -- the engine populates
 * both `structure=` and `structured=` at the same call site, so `structure`
 * keeps being a reliable signal for deriveSessionTitle/purpose-vs-detail
 * even on a session that also has `structured`. At least one of
 * `structure`/`detail` is present for every real session shape today, but a
 * pool-coach placeholder with neither still has a real, non-blank title in
 * the header above (deriveSessionTitle's fallback), so there is always
 * something sensible to show even when this whole block is empty.
 *
 * `showGarminActions` (default `true`, preserving the athlete's own Plan tab
 * behaviour unchanged) gates the two Garmin action sections below. The coach
 * roster's Training Plan sub-tab (`renderRosterTrainingPlanBody`) passes
 * `false`: both actions ultimately call backend routes
 * (`backend/app/routes/garmin.py`) gated via `resolve_athlete` (self-only --
 * no `resolve_coach_athlete` support), and the frontend calls
 * (`handleDownloadGarminFit`/`handlePushSessionToGarmin`) resolve the target
 * athlete via `athleteSlug()`, which is always the SIGNED-IN principal's own
 * slug -- for a coach that's the coach's own athlete record, never the
 * coached athlete's. Suppressing just these two sections (not the rest of
 * the detail) is what makes "same view as the athlete sees" honest here:
 * everything else below -- structure, targets, zone breakdown, training
 * rationale, purpose -- renders identically either way.
 *
 * `askCoach` (coach-mode Q&A build): `{ feedback, form, submit }` --
 * `feedback` is the raw, already-fetched Feedback list (filtered here, via
 * `feedbackForSession`, down to just this session's own questions);
 * `form`/`submit` thread straight through to `renderAskCoachSection` (see
 * its own doc comment -- `form: null`/absent renders read-only, the coach
 * roster's call site). `null`/absent entirely renders the section with an
 * empty question list and no input box, so a stale/legacy call site never
 * crashes on a missing prop. */
function renderPlanSessionDetail(session, sessionPush, showGarminActions = true, askCoach = null) {
  const classification = classifySession(session);
  const { title, detail, structure } = sessionDisplay(session);
  const dateLabel = formatLongDate(parseIsoDate(session.date));
  const hasStructured = Boolean(session.structured?.items?.length);
  // Pull the trailing "Why: ..." step (plan.py's real shape, see
  // splitStructuredRationale's own doc comment) out of the generic
  // Workout tree-walk so it can get the exact same "Training rationale"
  // heading the legacy prose path's own `Why:` block gets below, instead of
  // rendering as just another undifferentiated line in the struct-tree.
  const { items: workoutItems, rationale } = hasStructured
    ? splitStructuredRationale(session.structured)
    : { items: [], rationale: null };

  // Whether to show the full, un-split `purpose` or just the post-em-dash
  // `detail` fragment here depends on where the header title (above) came
  // from -- deriveSessionTitle prefers a title derived from `structure`
  // (the "Main set:" line or first line), and only falls back to the
  // pre-em-dash half of `purpose` when `structure` is absent.
  //   - When `structure` is present, the header title never overlapped with
  //     `purpose` at all, so neither half of `purpose` has been shown yet.
  //     Newer purpose strings (engine's `_no_coach_pool_purpose`, the
  //     strength session's purpose=, e.g. "Continuous aerobic volume —
  //     base-block emphasis") are a SINGLE complete statement that merely
  //     contains an em-dash as internal punctuation; splitting those left
  //     only the post-dash half ("base-block emphasis"), a meaningless
  //     fragment. Show the whole sentence instead.
  //   - When `structure` is absent (e.g. the pool-coach placeholder, the
  //     long open-water swim, multi-day stage sessions), the header title
  //     IS the pre-dash half of `purpose` (deriveSessionTitle's
  //     purposeTitle() fallback) -- showing the full purpose here would
  //     literally repeat that title text as a prefix (e.g. title "Long
  //     open-water swim" followed by Purpose "long open-water swim --
  //     endurance and fueling-practice anchor of the week"). Keep the
  //     original post-dash `detail` fragment in that case, exactly as
  //     before this fix.
  // (renderSession's compact-row subtitle intentionally keeps using
  // `detail` unconditionally -- that terse one-line spot is correct for the
  // race-tagged shape and out of scope here.)
  const purpose = structure ? session.purpose : detail;

  return `
    <div class="detail-header">
      <h3>${esc(title)}${classification.tag ? `<span class="tag">${esc(classification.tag)}</span>` : ''}</h3>
      <div class="hist-meta mono">${esc(sportLabel(session.sport))} · ${esc(dateLabel)}</div>
    </div>
    ${renderPlanSessionDetailStats(session)}
    ${hasStructured ? renderZoneDistributionSummary(session.structured) : ''}
    ${hasStructured
      ? renderStructuredWorkoutSection({ items: workoutItems })
        + (rationale ? renderStructureBlock({ label: 'Why', content: rationale }) : '')
      : (structure ? parseStructureBlocks(structure).map(renderStructureBlock).join('') : '')}
    ${session.structured
      ? (showGarminActions
        ? renderGarminDownload(session) + renderGarminPush(session, sessionPush)
        : renderGarminUnavailableNote())
      : ''}
    ${purpose ? `
    <section class="detail-section">
      <h4>Purpose</h4>
      <p class="detail-notes">${esc(purpose)}</p>
    </section>` : ''}
    ${renderAskCoachSection({
      questions: feedbackForSession(askCoach?.feedback, session.date, session.sport),
      form: askCoach?.form ?? null,
      submit: askCoach?.submit,
    })}`;
}

/** Stands in for the two Garmin action sections when `renderPlanSessionDetail`
 * is called with `showGarminActions: false` (the coach roster's Training
 * Plan sub-tab). Same restrained, honest "not available in this context"
 * tone as `renderCoachConversationPlaceholder`'s stripped-chat treatment on
 * the workout-detail view -- a small, real explanation rather than silently
 * omitting the buttons with no comment at all. */
function renderGarminUnavailableNote() {
  return `
    <section class="detail-section">
      <p class="sub">Garmin download/push is only available from the athlete's own device.</p>
    </section>`;
}

/** A plain download button for any session with `structured` populated --
 * triggers `main.js`'s `handleDownloadGarminFit` (via the same `data-a`
 * click-delegation convention every other action in this app uses), which
 * fetches `GET /api/sessions/{id}/garmin.fit` (backend/app/routes/garmin.py)
 * and saves the real Garmin workout-type `.FIT` file it returns. Deliberately
 * plain/undesigned -- see the plan this implements: "reachable from the app"
 * just means the athlete can get the file during/around a coaching
 * conversation, not a polished affordance. Absent entirely when
 * `structured` is `None` (a legacy, un-regenerated session -- there's
 * nothing to export yet). */
function renderGarminDownload(session) {
  return `
    <section class="detail-section">
      <button type="button" class="btn-garmin-download" data-a="session:garmin-download" data-id="${esc(session.id)}">
        Download for Garmin (.fit)
      </button>
    </section>`;
}

/** The wireless counterpart to `renderGarminDownload` above, and the thing
 * the athlete actually asked for: rather than saving a `.fit` to copy over
 * USB, this POSTs to `/api/sessions/{id}/push-intervals`
 * (backend/app/routes/garmin.py), which writes the workout to her
 * intervals.icu calendar for intervals.icu's own Garmin Connect integration
 * to forward to the watch.
 *
 * Gated on `structured` by the caller for the same reason the download
 * button is -- a prose-only session has no real workout to push, and
 * offering it would send garbage to a watch.
 *
 * `sessionPush` is main.js's `state.sessionPush` -- a SINGLE
 * `{ id, status, message }` rather than a per-session map, because only one
 * session detail is open at a time and a push is a short-lived foreground
 * action (same shape and reasoning as `state.logSync`). The `id` check
 * matters: without it, opening a different session right after a push would
 * show the previous session's result under the new one's button. */
function renderGarminPush(session, sessionPush) {
  const push = sessionPush && sessionPush.id === session.id ? sessionPush : null;
  const pushing = push?.status === 'pushing';
  const resultClass = push?.status === 'error' ? 'fail' : 'ok';

  return `
    <section class="detail-section">
      <button type="button" class="btn-garmin-push" data-a="session:push-intervals" data-id="${esc(session.id)}"${pushing ? ' disabled' : ''}>
        ${pushing ? 'Pushing to Garmin…' : 'Push to Garmin'}
      </button>
      ${push && push.message ? `<div class="conn-result ${resultClass}">${esc(push.message)}</div>` : ''}
    </section>`;
}

/** `week.race_week_checklist` (engine/swim_coach/models.py's
 * RaceWeekChecklistItem list) -- only ever non-empty for the final taper
 * week immediately preceding the athlete's active, priority-"A" event (see
 * plan.py's generate_week/_race_week_checklist and library/16-race-week.md).
 * Sorted by date since carb-load/bodywork/logistics items can legitimately
 * carry dates outside this WeekPlan's own 7-day span (a race that doesn't
 * fall on a Monday pushes the carb-load date into the following, not-yet-
 * generated event week) -- date order, not category order, is what makes
 * that visible rather than confusing. Renders nothing when the list is
 * empty (an ordinary taper week, or any non-final-taper week). */
function renderRaceWeekChecklist(checklist) {
  if (!checklist || checklist.length === 0) return '';
  const rows = [...checklist]
    .sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0))
    .map((item) => `
      <div class="race-week-item race-week-item-${esc(item.category)}">
        <span class="race-week-date mono">${esc(formatShortDate(parseIsoDate(item.date)))}</span>
        <span class="race-week-cat">${esc(raceWeekCategoryLabel(item.category))}</span>
        <span class="race-week-label">${esc(item.label)}</span>
      </div>`)
    .join('');
  return `
    <div class="race-week-checklist" data-a="week:race-week-checklist">
      <h4>Race week checklist</h4>
      ${rows}
    </div>`;
}

function renderWeekCard(week, label) {
  const days = sessionsByDay(week);
  const hasHighlight = (daySessions) => daySessions.some((s) => classifySession(s).highlight);

  const dayRows = days.map((day) => `
    <div class="day-row${hasHighlight(day.sessions) ? ' hi' : ''}">
      <div class="dlabel"><div class="dow">${day.dow}</div><div class="date mono">${esc(formatShortDate(day.date))}</div></div>
      <div>${
        day.sessions.length > 0
          ? day.sessions.map(renderSession).join('')
          : '<div class="sess"><div class="body"><div class="meta">—</div></div></div>'
      }</div>
    </div>`).join('');

  return `
    <div class="week">
      <div class="week-head">
        <h3>${esc(label)}</h3>
        <span class="focus">${esc(week.focus)}</span>
        <span class="vol mono">total <b>${week.target_volume_m.toLocaleString('en-US')} m</b></span>
      </div>
      ${week.adaptation_rationale ? `<div class="rationale"><b>Why this shape:</b> ${esc(week.adaptation_rationale)}</div>` : ''}
      ${renderRaceWeekChecklist(week.race_week_checklist)}
      <div class="days">${dayRows}</div>
    </div>`;
}

/** `detailId` is main.js's state.planSessionDetailId (athlete's own Plan tab)
 * or state.roster.sessionDetailId (coach's Training Plan sub-tab) -- null
 * shows the ordinary "This week"/"Next week" cards, a session id swaps the
 * whole section to a back button + renderPlanSessionDetail(...) instead,
 * same convention as renderTrainingDashboardBody's `detailId` handling for
 * workouts. `showGarminActions` (default `true`) just threads through to
 * renderPlanSessionDetail -- see that function's doc comment; the coach's
 * call site (renderRosterTrainingPlanBody) passes `false`. */
function renderWeeksSection(weeks, detailId, sessionPush, allWeeksOpen, showGarminActions = true, askCoach = null) {
  if (detailId) {
    const session = findSessionById(weeks, detailId);
    if (session) {
      return `
    <section>
      <div class="s-head"><button type="button" class="btn-ghost" data-a="session:back">&larr; Back to plan</button></div>
      ${renderPlanSessionDetail(session, sessionPush, showGarminActions, askCoach)}
    </section>`;
    }
  }

  const { current, next, stale } = pickCurrentAndNextWeek(weeks);
  const allWeeks = renderAllWeeksAccordion(weeks, allWeeksOpen);

  // Two genuinely different empty states, and neither one may resurrect a
  // past week as "This week" (the 2026-08-18 defect -- see plan.js's
  // pickCurrentAndNextWeek doc comment). `stale` means weeks exist but the
  // newest one already ended: the plan ran out and needs regenerating, so
  // say so and still let the athlete page back through what was planned.
  if (!current) {
    const message = stale
      ? 'No plan generated for this week yet — ask the coach to plan it.'
      : 'No weeks planned yet.';
    return `
    <section>
      <div class="s-head"><h2>The plan, day by day</h2></div>
      <p class="sub">${message}</p>
      ${allWeeks}
    </section>`;
  }

  const cards = [renderWeekCard(current, `This week · ${weekRangeLabel(current)}`)];
  if (next) cards.push(renderWeekCard(next, `Next week · ${weekRangeLabel(next)}`));

  return `
    <section>
      <div class="s-head">
        <h2>The plan, day by day</h2>
        <span class="note">built around real fixed events</span>
      </div>
      ${cards.join('')}
      ${allWeeks}
    </section>`;
}

/** Every week on file, past and future, in a collapsed `<details>` -- the
 * current/next cards above are the day-to-day view, this is the "show me
 * the whole plan" affordance that previously didn't exist at all (only two
 * cards were ever reachable). Native `<details>` rather than a JS toggle:
 * it works with no click handler, keyboard-accessible for free, and stays
 * usable if the accordion ever renders while offline. `data-a` is present
 * for e2e/unit selection and for main.js's logging convention; the open/
 * close behaviour itself is the browser's. Renders nothing when there are
 * no weeks at all. */
function renderAllWeeksAccordion(weeks, allWeeksOpen) {
  const sorted = sortedByIsoWeek(weeks);
  if (sorted.length === 0) return '';
  const cards = sorted
    .map((week) => renderWeekCard(week, `${week.iso_week} · ${weekRangeLabel(week)}`))
    .join('');
  return `
      <details class="all-weeks"${allWeeksOpen ? ' open' : ''}>
        <summary data-a="weeks:toggle-all">All planned weeks (${sorted.length})</summary>
        ${cards}
      </details>`;
}

function weekRangeLabel(week) {
  const days = sessionsByDay(week);
  const first = days[0].date;
  const last = days[6].date;
  return `${formatShortDate(first)}–${formatShortDate(last)}`;
}

function renderMacroSection(macro, event, weeks) {
  if (!macro || !macro.blocks || macro.blocks.length === 0) {
    return `
    <section>
      <div class="s-head"><h2>The macro plan</h2></div>
      <p class="sub">No macro plan scaffolded yet.</p>
    </section>`;
  }

  const nowIdx = currentBlockIndex(macro.blocks);
  const maxVolume = Math.max(...macro.blocks.map((b) => b.weekly_volume_target_m), 1);
  // Inclusive day-span (end - start + 1) BEFORE dividing by 7, not after --
  // the previous formula divided the exclusive day-diff by 7 and THEN added
  // 1, double-counting the "+1 for inclusive dates" adjustment and
  // overcounting every block by exactly one week (a real production taper
  // block, start_date=2026-10-12/end_date=2026-10-25 -- an exact 14-day/
  // 2-week span -- was mislabeled "3 wk", a 50% overcount; see
  // coach-load-visibility-and-narrative-polish PR for the full hand-check
  // against four real macro blocks).
  const totalWeeks = macro.blocks.reduce(
    (sum, b) => sum + Math.max(1, Math.round(((parseIsoDate(b.end_date) - parseIsoDate(b.start_date)) / 86400000 + 1) / 7)),
    0,
  );

  const blockEls = macro.blocks.map((block, i) => {
    // Math.max(1, ...) guard -- same as totalWeeks above and the race-marker
    // block below -- a block spanning 3 calendar days or fewer would
    // otherwise round DOWN to 0 weeks (Math.round(4/86400000... /7) can
    // land below 0.5), producing a nonsensical `flex:0` (a zero/degenerate-
    // width block) and a literal "0 wk" label. Every real block in this
    // athlete's own macro plan is at least a week long, but a future
    // shorter block (or a bad/edge-case date pair) must never render as
    // "0 wk" -- 1 week is the floor, not zero.
    const weeksInBlock = Math.max(1, Math.round(((parseIsoDate(block.end_date) - parseIsoDate(block.start_date)) / 86400000 + 1) / 7));
    const heightPct = Math.round((block.weekly_volume_target_m / maxVolume) * 100);
    return `
      <div class="block${i === nowIdx ? ' is-now' : ''}" style="flex:${weeksInBlock}">
        <div class="cap">
          <div class="ph">${esc(block.name)}</div>
          <div class="vol mono">${block.weekly_volume_target_m.toLocaleString('en-US')} m/wk</div>
          <div class="wk">${esc(formatShortDate(parseIsoDate(block.start_date)))} – ${esc(formatShortDate(parseIsoDate(block.end_date)))} · ${weeksInBlock} wk</div>
          ${i === nowIdx ? '<span class="nowtag">Now</span>' : ''}
        </div>
        <div class="fill" style="height:${heightPct}%"></div>
      </div>`;
  });

  if (event) {
    blockEls.push(`
      <div class="block race" style="flex:${Math.max(1, Math.round(totalWeeks * 0.14))}">
        <div class="rr"><span class="em">🏝️</span><span class="t">${esc(event.name.split(/[—(]/)[0].trim())}<br>${esc(formatShortDate(parseIsoDate(event.event_date)))}</span></div>
      </div>`);
  }

  const ladder = longSwimLadder(weeks, macro, event);
  const ladderHtml = ladder.length > 0 ? `
      <div class="ladder">
        <span>Long-swim ladder:</span>
        ${ladder.map((rung, i) => `${i > 0 ? '<span class="arrow">→</span>' : ''}${
          rung.connective
            ? `<span class="rung">${esc(rung.connective)}</span>`
            : `<span class="rung"><span class="k">${esc(rung.km)} k</span> · ${esc(rung.label)}</span>`
        }`).join('')}
      </div>` : '';

  return `
    <section>
      <div class="s-head">
        <h2>The macro plan</h2>
        <span class="note">bar height = weekly swim volume</span>
      </div>
      <div class="macro">
        <div class="macro-scroll"><div class="blocks">${blockEls.join('')}</div></div>
        <p class="macro-note">Weekly volume is periodized base → build → peak → taper toward the event. For a single-day continuous swim, the real work isn't weekly volume — it's the <b>long-swim ladder</b>: escalating continuous swims toward a peak a few weeks out.</p>
        ${ladderHtml}
      </div>
    </section>`;
}

// --- CTL/ATL/TSB training-load chart (Dashboard tab + coach roster) --------
// Shared, verbatim render function for both surfaces (see plan.js's
// ctlAtlTsbChartGeometry module comment for the geometry math this
// consumes) -- renderTrainingDashboardBody (both the athlete's own Dashboard
// tab and the coach roster's acting-as-athlete view, since Build 1 moved
// this chart off the Plan tab and into the merged Log+History Dashboard)
// calls this same function with different `load` state; only the data
// source differs (main.js's loadPlanLoad vs. loadCoachLoad).

const LOAD_CHART_LINE_COLOR_VAR = { ctl: '--accent', atl: '--c-strength', tsb: '--c-form' };

function loadChartPointsAttr(points) {
  return points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
}

const WELLNESS_STAT_STATUS_TEXT = {
  'no-data': 'Not enough data yet',
  good: 'Within normal range',
  concerning: 'worth a look',
};

/** Renders one compact stat callout (resting HR or HRV) from a
 * `describeWellnessBaselineDeviation` field (`{value, status}`). `label` is
 * the stat's name; `concerningWord` supplies the field-specific reason a
 * `concerning` status is bad (opposite for the two fields -- "Elevated" for
 * resting HR, "Suppressed" for HRV -- see plan.js's
 * `describeWellnessBaselineDeviation` module comment on why the sign
 * conventions are never unified). A `null` value (no `resting_hr`/`hrv`
 * logged recently, or not enough history) renders an honest "not enough
 * data yet" state -- never a hidden element, never a bare 0.0%. */
function renderWellnessDeviationStat(label, { value, status }, concerningWord) {
  const displayValue = value === null ? '—' : `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
  const statusText = status === 'concerning'
    ? `${concerningWord} — ${WELLNESS_STAT_STATUS_TEXT.concerning}`
    : WELLNESS_STAT_STATUS_TEXT[status];
  return `
      <div class="wellness-stat wellness-stat--${status}">
        <span class="wellness-stat-label">${esc(label)}</span>
        <span class="wellness-stat-value mono">${esc(displayValue)}</span>
        <span class="wellness-stat-status">${esc(statusText)}</span>
      </div>`;
}

/** The resting-HR/HRV baseline-deviation cross-check -- deliberately its
 * own visually distinct block (own heading, own callout styling, a dashed
 * divider above it) rather than a fourth line blended into the CTL/ATL/TSB
 * chart above, per this project's "multiple independent signals, not one
 * master number" convention: it's a physiologically-measured corroboration
 * of the sRPE-derived trend, not a component of it. Renders unconditionally
 * whenever `renderLoadChart` has `load.data` at all (even when the
 * CTL/ATL/TSB series itself is empty) -- wellness history and workout
 * history are independent logs, so one being empty says nothing about the
 * other. `deviation` may be `undefined` (older/partial payload) as well as
 * individually-`null` fields; `describeWellnessBaselineDeviation` treats
 * both the same honest way. */
function renderWellnessBaselineDeviation(deviation) {
  const described = describeWellnessBaselineDeviation(deviation);
  return `
    <div class="wellness-baseline-deviation">
      <h4>Resting HR / HRV cross-check</h4>
      <div class="wellness-stats">
        ${renderWellnessDeviationStat('Resting HR vs. 28-day baseline', described.restingHr, 'Elevated')}
        ${renderWellnessDeviationStat('HRV vs. 28-day baseline', described.hrv, 'Suppressed')}
      </div>
      <p class="load-chart-note">Resting heart rate and HRV are physiologically measured, not self-reported like the RPE behind the CTL/ATL/TSB chart above -- an independent cross-check, not a replacement for it. Treat a mismatch between the two as a reason to look closer, not as a verdict on which one is "right".</p>
    </div>`;
}

/** One shaded reference-band `<rect>`, shared by both the race-ready and
 * productive-training bands in `renderLoadChartSvg` below -- same geometry
 * shape (full plot width, `band.top`..`band.bottom` in the TSB panel's own
 * pixel space), differing only in which band and CSS class they use.
 * `isActive` (the athlete's LATEST TSB actually falls in this band) adds
 * `load-chart-band-active`, bumping the CSS opacity from .22 to .34 --
 * see plan.js's `PRODUCTIVE_TRAINING_TSB_BAND`/`RACE_DAY_TSB_BAND` doc
 * comments and index.html's matching rule. */
function renderLoadChartBandRect(geo, band, className, isActive) {
  const cls = `load-chart-band ${className}${isActive ? ' load-chart-band-active' : ''}`;
  return `<rect class="${cls}" x="${geo.plotLeft}" y="${band.top.toFixed(1)}" width="${(geo.plotRight - geo.plotLeft).toFixed(1)}" height="${Math.max(0, band.bottom - band.top).toFixed(1)}" />`;
}

/** A band's name, set into the band's own left edge, vertically centered --
 * "productive"/"race-ready" per the design spec, so the band reads as
 * self-labeled rather than requiring a separate legend entry to identify
 * which shaded region is which. */
function renderLoadChartBandLabel(geo, band, text) {
  const y = (band.top + band.bottom) / 2;
  return `<text x="${(geo.plotLeft + 8).toFixed(1)}" y="${y.toFixed(1)}" class="load-chart-band-label" dominant-baseline="middle">${esc(text)}</text>`;
}

/** The two UNNAMED zones above/below the two shaded bands -- "transitional"
 * (fresher than race-day useful) above the race-ready band, "high risk"
 * (fatigue outrunning the productive-training convention) below the
 * productive band -- labeled as small edge text per the design spec, with
 * no shaded rect of their own. The grey zone between the two named bands is
 * deliberately left unlabeled (per spec: it reads as itself). */
function renderLoadChartEdgeLabels(geo) {
  const transitionalY = (geo.tsbPlot.top + geo.raceBand.top) / 2;
  const highRiskY = (geo.productiveBand.bottom + geo.tsbPlot.bottom) / 2;
  return `
      <text x="${(geo.plotLeft + 8).toFixed(1)}" y="${transitionalY.toFixed(1)}" class="load-chart-edge-label" dominant-baseline="middle">transitional</text>
      <text x="${(geo.plotLeft + 8).toFixed(1)}" y="${highRiskY.toFixed(1)}" class="load-chart-edge-label" dominant-baseline="middle">high risk</text>`;
}

/** Shared caret-triangle points for one clamped TSB point, pointing further
 * up/down (off the plot) depending on which edge it landed on -- factored
 * out so both the generic clamp-caret pass below AND
 * `renderLoadChartLatestTsbLabel` (when the LATEST point is itself the one
 * that's clamped) draw the identical shape rather than two near-duplicate
 * inline calculations drifting apart over time. */
function caretPolygonPoints(x, y, geo, size) {
  const clampedHigh = Math.abs(y - geo.tsbPlot.top) < Math.abs(y - geo.tsbPlot.bottom);
  return clampedHigh
    ? `${(x - size).toFixed(1)},${(y + size).toFixed(1)} ${(x + size).toFixed(1)},${(y + size).toFixed(1)} ${x.toFixed(1)},${(y - size).toFixed(1)}`
    : `${(x - size).toFixed(1)},${(y - size).toFixed(1)} ${(x + size).toFixed(1)},${(y - size).toFixed(1)} ${x.toFixed(1)},${(y + size).toFixed(1)}`;
}

/** A small caret at the TSB panel's top/bottom edge for every index
 * `ctlAtlTsbChartGeometry` had to clamp into `TSB_AXIS_DOMAIN` (plan.js's
 * `tsbClamped`) -- flags an out-of-range point as an alarm worth a second
 * look, rather than silently drawing it as if it were merely at the edge of
 * "normal". The LATEST point is excluded here even when clamped -- it gets
 * its own combined caret+value marker from `renderLoadChartLatestTsbLabel`
 * instead (drawing both would either duplicate the shape or have the
 * latest-point circle painted on top of it, hiding the very alarm it's
 * meant to show). */
function renderLoadChartClampCarets(geo) {
  const lastIndex = geo.tsbPoints.length - 1;
  return geo.tsbClamped.filter((i) => i !== lastIndex).map((i) => {
    const p = geo.tsbPoints[i];
    return `<polygon class="load-chart-clamp-caret" points="${caretPolygonPoints(p.x, p.y, geo, 4)}" />`;
  }).join('');
}

/** Minimum vertical gap (px) between the CTL/ATL inline end-labels' text
 * baselines before they're pushed further apart -- `TSB = CTL - ATL`, so a
 * TSB reading near 0 means CTL and ATL are numerically close, which means
 * their pixel y-positions on the shared 0-anchored load axis land close
 * together too. Both labels using the same small fixed above-the-point
 * offset would then overlap right when the two lines are hardest to tell
 * apart on the chart itself -- exactly the wrong moment to lose the
 * legend. 14px is comfortably more than one line of this chart's small
 * inline-label text. */
const LOAD_CHART_END_LABEL_MIN_GAP = 14;

/** CTL/ATL's inline end-of-line name labels (the "legend moves inline"
 * change, replacing the old separate `.load-chart-legend` row for these two
 * lines) -- small colored text just to the left of each line's own
 * right-hand (most recent) point, colored to match the line itself. TSB's
 * own end-of-line identity is carried by `renderLoadChartLatestTsbLabel`
 * below instead (it needs a value, not just a name, right at that same
 * point, so the two are combined there rather than duplicated here).
 *
 * When the two points land close together vertically (see
 * `LOAD_CHART_END_LABEL_MIN_GAP`), whichever line is higher on screen (a
 * smaller SVG y) gets pushed further up and whichever is lower gets pushed
 * further down, instead of both using the same small offset -- separating
 * them regardless of which line happens to currently sit on top. */
function renderLoadChartLineEndLabels(geo) {
  const ctlEnd = geo.ctlPoints.at(-1);
  const atlEnd = geo.atlPoints.at(-1);
  const closeTogether = Math.abs(ctlEnd.y - atlEnd.y) < LOAD_CHART_END_LABEL_MIN_GAP;
  const ctlHigher = ctlEnd.y <= atlEnd.y;
  const ctlOffset = closeTogether ? (ctlHigher ? -9 : 9) : -5;
  const atlOffset = closeTogether ? (ctlHigher ? 9 : -9) : -5;
  return `
      <text x="${(ctlEnd.x - 6).toFixed(1)}" y="${(ctlEnd.y + ctlOffset).toFixed(1)}" text-anchor="end" class="load-chart-inline-label" style="fill:var(${LOAD_CHART_LINE_COLOR_VAR.ctl})">CTL</text>
      <text x="${(atlEnd.x - 6).toFixed(1)}" y="${(atlEnd.y + atlOffset).toFixed(1)}" text-anchor="end" class="load-chart-inline-label" style="fill:var(${LOAD_CHART_LINE_COLOR_VAR.atl})">ATL</text>`;
}

/** The TSB panel's last point: a filled dot plus a combined "TSB {value}"
 * label (name and number together, since this one point has to carry both
 * jobs -- the inline legend entry AND the "what is it right now" reading) --
 * per the design spec, "the answer to 'which band am I in' should be
 * visible without reading an axis." Anchored to the LEFT of the dot
 * (`text-anchor="end"`) because the last point always sits at the plot's
 * right edge (`plotRight`) -- anchoring right would push the label outside
 * the viewBox.
 *
 * When the latest point is ITSELF one `ctlAtlTsbChartGeometry` had to clamp
 * (`geo.tsbClamped`), the plain filled circle is replaced by the same
 * caret shape `renderLoadChartClampCarets` draws for every other clamped
 * point (see that function's own doc comment for why it excludes this
 * index) -- a circle drawn on top of a caret at the identical coordinates
 * would hide most of it, silently dropping the one alarm this marker most
 * needs to show. */
function renderLoadChartLatestTsbLabel(geo) {
  const { x, y, value } = geo.latestTsb;
  const valueText = `${value >= 0 ? '+' : ''}${value.toFixed(1)}`;
  const lastIndex = geo.tsbPoints.length - 1;
  const isClamped = geo.tsbClamped.includes(lastIndex);
  const marker = isClamped
    ? `<polygon class="load-chart-clamp-caret load-chart-clamp-caret-latest" points="${caretPolygonPoints(x, y, geo, 5)}" style="fill:var(${LOAD_CHART_LINE_COLOR_VAR.tsb})" />`
    : `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3.5" style="fill:var(${LOAD_CHART_LINE_COLOR_VAR.tsb})" />`;
  return `
      ${marker}
      <text x="${(x - 8).toFixed(1)}" y="${(y - 8).toFixed(1)}" text-anchor="end" class="load-chart-inline-label" style="fill:var(${LOAD_CHART_LINE_COLOR_VAR.tsb})">${esc(`TSB ${valueText}`)}</text>`;
}

/** Two stacked panels (top: CTL/ATL "fitness & fatigue" on one shared,
 * 0-anchored axis; bottom: TSB "form" on its own fixed-domain axis),
 * sharing one x-axis rendered once at the very bottom -- see plan.js's
 * `ctlAtlTsbChartGeometry` module comment for why this replaced an earlier
 * single-axis, then dual-y-axis, design. */
function renderLoadChartSvg(geo) {
  const loadGridlines = geo.yTicks.map((t) => `
      <line x1="${geo.plotLeft}" y1="${t.y.toFixed(1)}" x2="${geo.plotRight}" y2="${t.y.toFixed(1)}" class="load-chart-gridline" />
      <text x="${(geo.plotLeft - 6).toFixed(1)}" y="${t.y.toFixed(1)}" class="load-chart-axis-label" text-anchor="end" dominant-baseline="middle">${esc(t.value)}</text>`).join('');

  // Shared x-axis: rendered once, below the TSB (bottom) panel -- there is
  // only ever one row of date/month labels for the whole chart, not one per
  // panel. `xTickMode` ('date' vs 'month', see plan.js) picks the label
  // format; 'month' is used only for the full-history "Season" window,
  // where a date per tick would be unreadably dense.
  const xTickLabels = geo.xTicks.map((t) => {
    const label = geo.xTickMode === 'month'
      ? formatMonthLabel(parseIsoDate(t.label))
      : formatShortDate(parseIsoDate(t.label));
    return `<text x="${t.x.toFixed(1)}" y="${(geo.tsbPlot.bottom + 18).toFixed(1)}" class="load-chart-axis-label" text-anchor="middle">${esc(label)}</text>`;
  }).join('');

  const productiveActive = geo.latestTsb.band === 'productive';
  const raceActive = geo.latestTsb.band === 'race-ready';

  return `
    <svg class="load-chart-svg" viewBox="0 0 ${geo.width} ${geo.height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Training load chart: fitness (CTL) and fatigue (ATL) on a shared axis in the top panel, form (TSB) on its own fixed-scale panel below with productive-training and race-day reference bands">
      ${renderLoadChartBandRect(geo, geo.productiveBand, 'load-chart-band-productive', productiveActive)}
      ${renderLoadChartBandRect(geo, geo.raceBand, 'load-chart-band-race', raceActive)}
      ${loadGridlines}
      <line x1="${geo.plotLeft}" y1="${geo.tsbZeroY.toFixed(1)}" x2="${geo.plotRight}" y2="${geo.tsbZeroY.toFixed(1)}" class="load-chart-zero-line" />
      ${renderLoadChartBandLabel(geo, geo.productiveBand, 'productive')}
      ${renderLoadChartBandLabel(geo, geo.raceBand, 'race-ready')}
      ${renderLoadChartEdgeLabels(geo)}
      ${xTickLabels}
      <polyline class="load-chart-line load-chart-line-ctl" points="${loadChartPointsAttr(geo.ctlPoints)}" style="stroke:var(${LOAD_CHART_LINE_COLOR_VAR.ctl})" />
      <polyline class="load-chart-line load-chart-line-atl" points="${loadChartPointsAttr(geo.atlPoints)}" style="stroke:var(${LOAD_CHART_LINE_COLOR_VAR.atl})" />
      <polyline class="load-chart-line load-chart-line-tsb" points="${loadChartPointsAttr(geo.tsbPoints)}" style="stroke:var(${LOAD_CHART_LINE_COLOR_VAR.tsb})" />
      ${renderLoadChartClampCarets(geo)}
      ${renderLoadChartLineEndLabels(geo)}
      ${renderLoadChartLatestTsbLabel(geo)}
    </svg>`;
}

/** The window-selector pills above the chart (6 weeks / 12 weeks / Season --
 * `plan.js`'s `LOAD_CHART_WINDOW_OPTIONS`), reusing the roster sub-tab bar's
 * own `.subtab-bar`/`.subtab-btn` look verbatim -- same "pill row selects
 * one of a few named views" pattern, just above a chart instead of above a
 * tab body. `windowDays` is the currently-selected option's `days` (a
 * number, or `null` for "Season") -- `main.js`'s persisted
 * `state.loadWindowDays`. Each pill's `data-a` encodes its own `days` value
 * (`'season'` standing in for `null`, since `data-` attributes are always
 * strings) for `main.js`'s click handler to parse back out. */
function renderLoadChartWindowControls(windowDays) {
  return `
    <nav class="subtab-bar load-chart-window-controls" aria-label="Chart time window">
      ${LOAD_CHART_WINDOW_OPTIONS.map((opt) => {
        const key = opt.days === null ? 'season' : String(opt.days);
        const active = opt.days === windowDays;
        return `<button type="button" class="subtab-btn${active ? ' active' : ''}" data-a="load-chart:window:${key}" aria-current="${active ? 'page' : 'false'}">${esc(opt.label)}</button>`;
      }).join('')}
    </nav>`;
}

/** Athlete-facing wording for each of `classifyTsbBand`'s five band names,
 * for the one-line verdict below -- must follow the constants' own doc
 * comments (plan.js's `PRODUCTIVE_TRAINING_TSB_BAND`/`RACE_DAY_TSB_BAND`):
 * "productive" mid-build is expected and good, never phrased as a warning. */
const TSB_VERDICT_BAND_LABEL = {
  'high-risk': 'high-risk band',
  productive: 'productive band',
  'grey-zone': 'grey zone',
  'race-ready': 'race-ready band',
  transition: 'transitional band',
};

/** The single most useful line on the panel (design spec 3.6): a one-line,
 * plain-text verdict directly under the chart -- "can I see at a glance
 * whether my TSB is in the productive band, over-trained, or tapering
 * toward race-ready?", answered in one sentence, before the athlete has to
 * read the narrative below or the chart's own axes. Derived from the same
 * `describeCtlAtlTsbTrend` structure the narrative already uses (never a
 * second, independently-computed source of truth for the same numbers).
 * Returns `''` when there's no TSB reading at all (`!trend.hasData`) --
 * same empty-series case the chart/narrative already handle their own way. */
function renderLoadChartVerdict(trend) {
  if (!trend.hasData || !trend.tsb) return '';
  const bandLabel = TSB_VERDICT_BAND_LABEL[trend.tsb.band];
  let fitnessPhrase = '';
  if (trend.ctlTrend && trend.ctlTrend.status !== 'insufficient-window') {
    const { status, fromValue, toValue } = trend.ctlTrend;
    const verb = { rising: 'Fitness rising', falling: 'Fitness falling', flat: 'Fitness holding flat' }[status];
    fitnessPhrase = ` ${verb}, ${formatTrendValue(fromValue)} → ${formatTrendValue(toValue)} over ${CTL_ATL_TREND_WINDOW_DAYS} days.`;
  }
  return `<p class="load-chart-verdict">${esc(`Form ${formatTrendValue(trend.tsb.value)} · ${bandLabel}.${fitnessPhrase}`)}</p>`;
}

/** Formats a raw CTL/ATL/TSB number to one decimal for narrative prose --
 * these values arrive already 1-decimal rounded from `summarize_rollup`
 * (see `ctlAtlTsbChartGeometry`'s `roundToTenth` comment), so this only
 * ever normalizes trailing zeros/sign, never adds precision that isn't
 * really there. */
function formatTrendValue(value) {
  return value.toFixed(1);
}

function formatTrendDate(iso) {
  return formatShortDate(parseIsoDate(iso));
}

/** Short, actionable clause appended to each `classifyTsbBand` band's
 * SHORT narrative line (see `renderCtlAtlTsbNarrative`) -- a real
 * recommendation grounded only in the current TSB reading itself, never a
 * claim about specific planned future sessions (this function has no
 * access to future plan/session data, and shouldn't reach for it here).
 * `productive`'s wording matches the athlete's own example verbatim in
 * spirit ("TSB is in the productive range, keep an eye on this to keep it
 * here"); the other four follow the same level of concreteness. */
const TSB_BAND_ACTIONABLE_CLAUSE = {
  productive: 'keep an eye on this to keep it here',
  'high-risk': 'worth easing off over the next few sessions to let fatigue clear',
  'grey-zone': 'not currently in either reference band -- worth watching which way this moves',
  'race-ready': 'in range for race-day freshness',
  transition: "fresher than useful for training -- likely time to pick load back up if there's no race imminent",
};

/** Fuller explanatory clause for each band -- the pre-existing, more
 * detailed text (unchanged from before this reorder), now shown only in
 * the narrative's LONG/expanded form rather than by default. */
const TSB_BAND_LONG_CLAUSE = {
  'productive': `inside the ${PRODUCTIVE_TRAINING_TSB_BAND.low} to ${PRODUCTIVE_TRAINING_TSB_BAND.high} productive-training band -- expected and good while building, not a warning sign. Reaching the +${RACE_DAY_TSB_BAND.low} to +${RACE_DAY_TSB_BAND.high} race-ready band from here is the taper's job, not something that should already be true mid-block`,
  'high-risk': `below the ${PRODUCTIVE_TRAINING_TSB_BAND.low} to ${PRODUCTIVE_TRAINING_TSB_BAND.high} productive-training band -- fatigue is accumulating faster than that convention recommends; worth a closer look at recent load and wellness together, not just this number alone`,
  'grey-zone': `between the productive-training and race-ready bands -- neither deep in a training block nor freshening for a race`,
  'race-ready': `inside the +${RACE_DAY_TSB_BAND.low} to +${RACE_DAY_TSB_BAND.high} race-day reference band`,
  'transition': `above the +${RACE_DAY_TSB_BAND.low} to +${RACE_DAY_TSB_BAND.high} race-day reference band -- fresher than race day calls for, likely losing fitness if held here long`,
};

/** Renders `describeCtlAtlTsbTrend`'s structured summary as the athlete-
 * facing "what the numbers say" prose -- the "useful coach guidance below
 * the load graph" this whole feature is for (an athlete's spouse's own
 * description of a hand-written narrative interpretation of this same
 * chart, judged more useful day-to-day than the generic methodology
 * caption that used to sit directly under it -- see `renderLoadChart`'s
 * own comment for where that caption moved).
 *
 * **Ordering (actionable-first, caveats-last)**: this used to lead with the
 * warmup/cold-start caveat, then CTL, then ATL, then TSB last -- and only
 * ever showed the FIRST of those by default, which meant the caveat (not
 * the actual guidance) was usually the only thing an athlete saw without
 * tapping "more". Direct athlete feedback: "the part shown 'this series
 * has 66 days blah blah blah' belongs at the bottom. Put the two or three
 * actionable sentences at top." This reorders to TSB (with a short
 * actionable clause) -> CTL trend -> ATL spike (when present/non-flat) ->
 * warmup caveat, and shows every one of those EXCEPT the caveat by
 * default -- the caveat is always last and always hidden behind "more",
 * regardless of how many other lines there are, since it's a
 * data-maturity disclaimer, not something to act on today.
 *
 * **Two-level short/long structure**: each fact is a `{ short, long }`
 * pair rather than one flat string. The TSB line specifically needs a
 * distinct short form (band + one actionable clause, e.g. "in the
 * productive band -- keep an eye on this to keep it here") versus its
 * long form (the fuller "expected and good while building..." explanation
 * that used to be the whole line) -- see `TSB_BAND_ACTIONABLE_CLAUSE`/
 * `TSB_BAND_LONG_CLAUSE`. CTL-trend and ATL-spike currently reuse the same
 * text for both short and long (already concise, factual sentences); the
 * warmup caveat only ever has a long form, since it never appears short.
 * Default (non-expanded) view renders every default-visible line's
 * `.short`; expanded view renders every line's `.long`, with the caveat
 * appended at the very end. The ATL-spike sentence keeps stating the real,
 * already-computed `atlSpike.fromDate`/`toDate`/values plainly (never a
 * vague "big training day" guess) -- per the athlete's explicit "not a
 * guess - must have been big training day, read the data" instruction.
 *
 * Returns `''` when `!trend.hasData` -- same empty-series case
 * `ctlAtlTsbChartGeometry` already renders its own "not enough data yet"
 * message for, so this narrative doesn't duplicate that.
 *
 * "More" toggle: same one-way, state-tracked "Show more" convention
 * `main.js`'s `state.dashboardFeedExpanded`/`state.roster.feedExpanded`
 * already use for the Training Dashboard feed (see
 * `handleShowMoreDashboardFeed`'s doc comment there), reused here via
 * `expanded` rather than inventing a second truncation mechanism.
 *
 * Takes the already-computed `trend` (`describeCtlAtlTsbTrend`'s result),
 * not the raw `series` -- `renderLoadChart` computes it once and passes it
 * to both this function and `renderLoadChartVerdict`, rather than each
 * independently re-deriving the identical structure from the same series
 * on every render. */
function renderCtlAtlTsbNarrative(trend, { expanded = false } = {}) {
  if (!trend.hasData) return '';

  // Default-visible facts, in actionable-first priority order: TSB (with
  // its short actionable clause) -> CTL trend -> ATL spike (when present
  // and non-flat). Each is a { short, long } pair.
  const lines = [];

  if (trend.tsb) {
    const { value, band, date } = trend.tsb;
    const bandLabel = TSB_VERDICT_BAND_LABEL[band];
    lines.push({
      short: `TSB (form) is ${formatTrendValue(value)}, in the ${bandLabel} -- ${TSB_BAND_ACTIONABLE_CLAUSE[band]}.`,
      long: `TSB (form) is currently ${formatTrendValue(value)} as of ${formatTrendDate(date)} -- ${TSB_BAND_LONG_CLAUSE[band]}.`,
    });
  }

  if (trend.ctlTrend) {
    let text;
    if (trend.ctlTrend.status === 'insufficient-window') {
      text = `Not enough history yet (${trend.ctlTrend.historyDays} day${trend.ctlTrend.historyDays === 1 ? '' : 's'}) to compare CTL over a ${trend.ctlTrend.requiredWindowDays}-day window.`;
    } else {
      const { status, fromDate, toDate, fromValue, toValue } = trend.ctlTrend;
      const verb = { rising: 'climbed', falling: 'dropped', flat: 'held roughly flat' }[status];
      text = `CTL (fitness) has ${verb}${status === 'flat' ? '' : ' steadily'} from ${formatTrendDate(fromDate)} to ${formatTrendDate(toDate)}: ${formatTrendValue(fromValue)} → ${formatTrendValue(toValue)}.`;
    }
    lines.push({ short: text, long: text });
  }

  if (trend.atlSpike && trend.atlSpike.direction !== 'flat') {
    const { fromDate, toDate, fromValue, toValue, direction } = trend.atlSpike;
    const verb = direction === 'up' ? 'jumped' : 'dropped';
    const dateRange = `${formatTrendDate(fromDate)}–${formatTrendDate(toDate)}`;
    lines.push({
      short: `ATL (fatigue) ${verb} from ${formatTrendValue(fromValue)} to ${formatTrendValue(toValue)} across ${dateRange} -- most likely a big training day; a few shorter days will shed the fatigue.`,
      long: `ATL (fatigue) ${verb} from ${formatTrendValue(fromValue)} to ${formatTrendValue(toValue)} across ${dateRange} -- the biggest recent swing, most likely tracking a big training day or block.`,
    });
  }

  // Warmup/cold-start caveat: ALWAYS last, and only ever rendered in the
  // expanded/"more" view, regardless of how many other lines exist above --
  // it's a data-maturity disclaimer, not something actionable today (the
  // athlete's own "put longer explanation and filling the pipeline in the
  // more^ section" instruction).
  let warmupLong = null;
  if (trend.warmup === 'cold-start') {
    warmupLong = `Only ${trend.historyDays} day${trend.historyDays === 1 ? '' : 's'} of logged history so far -- CTL and ATL are still climbing up from zero and don't yet reflect real fitness/fatigue levels. Read everything above as provisional until more history accumulates.`;
  } else if (trend.warmup === 'warming-up') {
    warmupLong = `This series has ${trend.historyDays} days of history -- past the point where CTL/ATL are pure zero-artifacts, but not yet "fully warmed up" by this model's own standard. Read the trend above as directionally useful, not yet a fully mature fitness estimate.`;
  }

  if (lines.length === 0 && !warmupLong) return '';

  const visibleLines = expanded
    ? [...lines.map((l) => l.long), ...(warmupLong ? [warmupLong] : [])]
    : lines.map((l) => l.short);
  // "More" is offered whenever there's more to show than the default view
  // already shows -- which is always true when reached: `trend.tsb` (and
  // therefore a TSB line whose `long` always differs from its `short`) is
  // guaranteed present here, since `describeCtlAtlTsbTrend` only ever
  // returns a null `tsb` alongside `!hasData`, which already returned early
  // above. So this reduces to simply "not already expanded" -- not, e.g.,
  // "only if the warmup caveat exists," which would wrongly suggest a case
  // (no lines differ AND no warmup caveat) that can't actually occur.
  const hasMore = !expanded;

  return `
    <div class="load-chart-narrative">
      <h4>What the numbers say</h4>
      ${visibleLines.map((line) => `<p>${esc(line)}</p>`).join('')}
      ${hasMore ? '<button type="button" class="btn-ghost load-chart-narrative-more" data-a="load-chart:narrative-more">more</button>' : ''}
    </div>`;
}

/**
 * Renders the CTL ("fitness") / ATL ("fatigue") / TSB ("form") training-load
 * chart -- shared verbatim by `renderTrainingDashboardBody` on both the
 * athlete's own Dashboard tab and the coach roster's acting-as-athlete
 * view; only the `load` state (and a couple of per-surface options, below)
 * differs between the two call sites.
 *
 * `load` follows this app's usual async-state shape (`{status, data, error}`
 * -- same convention as `state.plan`/`state.roster.workouts`), where
 * `data.ctl_atl_tsb` is the `[dateIso, ctl, atl, tsb]` series from
 * `GET /api/plan/load` / `GET /api/coach/athletes/{slug}/load`.
 *
 * **Two-panel rebuild (web/two-panel-load-chart):** CTL and ATL now share
 * one 0-anchored axis in a top panel; TSB gets its own fixed-domain panel
 * below, with the productive-training/race-day reference bands finally
 * living somewhere they can't be misread as applying to the CTL line
 * passing through them. See `ctlAtlTsbChartGeometry`'s module comment in
 * plan.js for the full history of why (single-axis, then dual-axis, then
 * this).
 *
 * Panel order, top to bottom (design spec 3.6 -- "chart panel density"):
 * window-selector pills, the two-panel SVG, a one-line plain-text VERDICT
 * (`renderLoadChartVerdict` -- the single most useful line on the panel),
 * the narrative (`renderCtlAtlTsbNarrative`, now truncated to its first
 * line by default), then the collapsed-by-default methodology `<details>`.
 * The old separate three-line legend row is gone -- CTL/ATL/TSB are now
 * named inline at each line's own right-hand end point instead (see
 * `renderLoadChartSvg`), and the two bands are named directly on their own
 * shaded rects.
 *
 * `options`:
 *   - `windowDays` (default `LOAD_CHART_WINDOW_DAYS`): which of
 *     `LOAD_CHART_WINDOW_OPTIONS` is active -- `null` means the full
 *     series ("Season"), rendered with month-labeled x-ticks instead of
 *     dates. Threaded down from `main.js`'s persisted `state.loadWindowDays`
 *     via `renderTrainingDashboardBody`.
 *   - `narrativeExpanded` (default `false`): whether the narrative's "more"
 *     toggle has been opened -- `main.js`'s
 *     `state.loadNarrativeExpanded`/`state.roster.narrativeExpanded`.
 *   - `showWellnessInline` (default `true`): whether the resting-HR/HRV
 *     baseline-deviation cross-check (`renderWellnessBaselineDeviation`)
 *     renders inline here. The coach roster's acting-as-athlete view keeps
 *     it here (its default); the athlete's OWN Dashboard call site passes
 *     `false` and renders it inside the Check-in tab instead (see
 *     `renderCheckinTab`) -- the coach has no Check-in-tab equivalent to
 *     move it to, and losing this signal there was never in scope.
 */
export function renderLoadChart(load, {
  windowDays = LOAD_CHART_WINDOW_DAYS, narrativeExpanded = false, showWellnessInline = true,
} = {}) {
  if (!load || load.status === 'idle') return '';
  if (load.status === 'loading' && !load.data) {
    return '<div class="panel load-chart-panel"><h3>Training load</h3><p class="sub">Loading training load&hellip;</p></div>';
  }
  if (load.status === 'error') {
    return `<div class="panel load-chart-panel"><h3>Training load</h3><div class="hist-error">Couldn't load training load: ${esc(load.error)}</div></div>`;
  }
  if (!load.data) return '';

  const series = load.data.ctl_atl_tsb || [];
  // Chart window: the selected LOAD_CHART_WINDOW_OPTIONS entry, not the
  // athlete's whole history by default -- for mobile readability (see
  // LOAD_CHART_WINDOW_DAYS's own doc comment in plan.js). `windowDays ===
  // null` ("Season") keeps the full series and switches the x-axis to
  // month labels. The narrative/verdict below intentionally keep using the
  // FULL `series`, not this slice, since their warmup/history-length read
  // needs the athlete's real full history, not just what fits on screen.
  const chartSeries = windowDays === null ? series : series.slice(-windowDays);
  const geo = ctlAtlTsbChartGeometry(chartSeries, { xTickMode: windowDays === null ? 'month' : 'date' });

  const trend = describeCtlAtlTsbTrend(series);

  const body = geo.isEmpty
    ? '<p class="sub">Not enough logged training yet to show a fitness/fatigue trend.</p>'
    : renderLoadChartSvg(geo);

  const verdict = geo.isEmpty ? '' : renderLoadChartVerdict(trend);
  const narrative = geo.isEmpty ? '' : renderCtlAtlTsbNarrative(trend, { expanded: narrativeExpanded });

  return `
    <div class="panel load-chart-panel">
      <h3>Training load (CTL / ATL / TSB)</h3>
      ${renderLoadChartWindowControls(windowDays)}
      ${body}
      ${verdict}
      ${narrative}
      <details class="load-chart-methodology">
        <summary>How this chart works</summary>
        <p class="load-chart-note">CTL ("fitness") and ATL ("fatigue") are 42-day/7-day exponentially weighted averages of daily training load; TSB ("form") is CTL minus ATL. These time constants are the standard cycling/TrainingPeaks convention, carried over as a starting point -- not yet verified for swimming specifically. The two shaded bands, in the panel below, are the same convention's other commonly-cited zones: the lower one (${PRODUCTIVE_TRAINING_TSB_BAND.low} to ${PRODUCTIVE_TRAINING_TSB_BAND.high} TSB) is where productive training typically happens; the upper one (+${RACE_DAY_TSB_BAND.low} to +${RACE_DAY_TSB_BAND.high} TSB) is a commonly-targeted range in cycling coaching practice on race day. Like the time constants above, this is not a swim-specific or peer-reviewed target for either band -- individual variation is large, so your own best-performance history is a better guide than either generic band. CTL and ATL share one axis in the top panel; TSB has its own fixed-scale panel below, sized to always contain both bands with margin so they sit in the same place every time you open the app.</p>
      </details>
      ${showWellnessInline ? renderWellnessBaselineDeviation(load.data.wellness_baseline_deviation) : ''}
    </div>`;
}

function renderZonesPanel(athlete) {
  const zones = athlete.zones;
  if (!zones) return '<div class="panel"><h3>Pace anchors</h3><p class="sub">No zones set yet.</p></div>';

  const order = ['Z2', 'Z3', 'Z4', 'Z5'].filter((z) => zones[z]);
  const cssLabel = athlete.css_pace_s_per_100m ? formatPace(athlete.css_pace_s_per_100m) : null;

  const rows = order.map((zoneName, i) => {
    const zone = zones[zoneName];
    const lo = formatPace(zone.pace_lo_s);
    const hi = formatPace(zone.pace_hi_s);
    let paceText;
    if (lo && hi) paceText = `${lo}–${hi}`;
    else if (hi) paceText = `≤ ${hi}`;
    else if (lo) paceText = `${lo}+`;
    else paceText = '—';
    // Visual-only ramp (increasing intensity left→right); not derived from
    // the actual pace delta between zones.
    const widthPct = 55 + Math.round((i / Math.max(1, order.length - 1)) * 45);
    return `
      <div class="zrow">
        <span class="z">${esc(zoneName)}</span>
        <span class="zbar-track"><span class="zbar" style="width:${widthPct}%"></span></span>
        <span class="p mono">${esc(paceText)}</span>
      </div>`;
  }).join('');

  return `
    <div class="panel">
      <h3>Pace anchors${cssLabel ? ` · CSS ${esc(cssLabel)} /100m` : ''}</h3>
      <div class="zones">${rows}</div>
      <p style="font-size:12.5px; color:var(--ink-soft); margin-top:12px;">Pool pace is the intensity anchor (no power meter in the water). Open-water targets adjust for chop, sighting and wetsuit.</p>
    </div>`;
}

function renderLegendPanel() {
  const items = SESSION_LEGEND.map((item) => `
    <span class="li"><span class="dot" style="background:var(${item.colorVar})"></span>${esc(item.label)}</span>`).join('');
  return `
    <div class="panel">
      <h3>Session types</h3>
      <div class="legend">${items}</div>
      <p style="font-size:12.5px; color:var(--ink-soft); margin-top:14px;">The AI coach plans <b>around</b> the coach-set pool sessions — it owns the open water, long swims, strength, and recovery.</p>
    </div>`;
}

/** A compact, collapsed-by-default zone/terms reference for the Plan tab --
 * "easy to ignore when not needed, easy to find when it is" (the athlete
 * feedback this whole pass responds to was about workouts not making
 * sense without a coach walking through them, so the terms/zones used
 * throughout this tab need to be reachable, but a wall of definitions
 * bolted permanently onto the page would be exactly the wrong fix).
 * Native `<details>`, matching `renderAllWeeksAccordion`'s own affordance
 * (works with no JS, keyboard-accessible, survives offline) -- deliberately
 * its own `.glossary` class rather than reusing `.all-weeks` so main.js's
 * capture-phase `toggle` listener can track this accordion's open state
 * independently (toggling the glossary must not also mark the unrelated
 * all-weeks accordion open, or vice versa). `ZONE_GLOSSARY`/`TERM_GLOSSARY`
 * (plan.js) are the actual data -- real CSS-relative offsets from
 * engine/swim_coach/zones.py, not invented numbers. */
function renderGlossaryPanel(open) {
  const zoneRows = ZONE_GLOSSARY.map((z) => `
        <div class="glossary-zone-row">
          <span class="z mono">${esc(z.zone)}</span>
          <span class="range mono">${esc(z.range)}</span>
          <span class="character">${esc(z.character)}</span>
        </div>`).join('');
  const termRows = TERM_GLOSSARY.map((t) => `
        <dt>${esc(t.term)}</dt>
        <dd>${esc(t.def)}</dd>`).join('');

  return `
      <details class="glossary"${open ? ' open' : ''}>
        <summary data-a="glossary:toggle">Terms &amp; zones</summary>
        <div class="glossary-content">
          <h4>Zones (CSS-anchored)</h4>
          <div class="glossary-zones">${zoneRows}</div>
          <h4>Terms</h4>
          <dl class="glossary-terms">${termRows}</dl>
        </div>
      </details>`;
}

export function renderApp(data, planSessionDetailId) {
  const { athlete, events, macro, weeks, sessionPush, allWeeksOpen, glossaryOpen, askCoach } = data;
  const event = macroTargetEvent(macro, events);

  return `
    <div class="wrap">
      ${renderMasthead(athlete, event)}
      ${renderWeeksSection(weeks, planSessionDetailId, sessionPush, allWeeksOpen, true, askCoach)}
      ${renderMacroSection(macro, event, weeks)}
      <div class="foot">
        ${renderLegendPanel()}
        ${renderZonesPanel(athlete)}
      </div>
      ${renderGlossaryPanel(glossaryOpen)}
      <p class="disc">Generated from ${esc(athlete.name)}'s live plan data on the swim-coach engine. Distances marked ~ are estimates until each session is logged.</p>
    </div>`;
}

export function renderLoading() {
  return '<div class="wrap"><div class="loading">Loading plan…</div></div>';
}

export function renderError(message) {
  return `<div class="wrap"><div class="load-error">Couldn't load the plan: ${esc(message)}</div></div>`;
}

// --- Tab bar ---------------------------------------------------------------
// Log and History merged into one Dashboard tab (Build 1 of the wellness-
// ingestion + training-dashboard plan) -- they'd grown into near-duplicates
// (Log embedded a capped, completed-only history view; History showed the
// same data unbounded, plus derived skips) and the nav had grown "already
// very busy" across many builds. Adding a tab later is just another entry
// in TABS plus a case in main.js's tab-content switch -- nothing here needs
// to change.
const TABS = [
  { id: 'plan', label: 'Plan', icon: '📋' },
  { id: 'dashboard', label: 'Dashboard', icon: '📊' },
  { id: 'checkin', label: 'Check-in', icon: '🌙' },
  { id: 'coach', label: 'Coach', icon: '💬' },
  { id: 'feedback', label: 'Feedback', icon: '💡' },
  { id: 'roster', label: 'My Athletes', icon: '🧑‍🤝‍🧑' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
];

/** B3 (coach-mode Q&A build): a small plain count chip -- new to this app
 * (no existing dot/count precedent anywhere to extend), kept deliberately
 * minimal to match this app's existing conventions rather than introducing
 * a new design system. Renders nothing for a falsy/zero count, so every
 * call site can pass a count unconditionally. */
function renderUnreadBadge(count) {
  if (!count) return '';
  return `<span class="badge-count">${count}</span>`;
}

/**
 * `activeTab` is unchanged. Second arg is an options bag: `{ hideRoster,
 * feedbackUnread, rosterUnread }`.
 * - `hideRoster`: when true, the 'roster' tab (coach mode Phase 1's "My
 *   Athletes") is left out of the bar entirely, since an identity with no
 *   coach grants has nothing to see there (see main.js's render(), which
 *   passes `hideRoster: !state.coachFor.length`). Chosen over a general
 *   allowlist-of-visible-ids because 'roster' is the only tab that's ever
 *   conditionally hidden today -- a single named flag says exactly that,
 *   rather than every call site having to enumerate all 7 tab ids just to
 *   hide one.
 * - `feedbackUnread`/`rosterUnread` (B3): unread counts (main.js's
 *   src/unread.js) rendered as a small badge (`renderUnreadBadge`) on the
 *   Feedback tab (athlete-facing: new coach replies) and the My Athletes tab
 *   (coach-facing: new athlete questions) respectively. Both default to 0
 *   (no badge) -- every existing call site outside main.js's real render()
 *   (e.g. tests) keeps the old "no badges" behavior unchanged.
 * Omitting the second arg entirely keeps the old "every tab always shows,
 * no badges" behavior.
 */
export function renderTabBar(activeTab, { hideRoster = false, feedbackUnread = 0, rosterUnread = 0 } = {}) {
  const tabs = hideRoster ? TABS.filter((tab) => tab.id !== 'roster') : TABS;
  const unreadByTabId = { feedback: feedbackUnread, roster: rosterUnread };
  return `
    <nav class="tabbar" aria-label="Main">
      ${tabs.map((tab) => `
        <button type="button" class="tab-btn${tab.id === activeTab ? ' active' : ''}" data-a="tab:${tab.id}" aria-current="${tab.id === activeTab ? 'page' : 'false'}">
          <span class="tab-icon" aria-hidden="true">${tab.icon}</span>
          <span class="tab-label">${esc(tab.label)}</span>
          ${renderUnreadBadge(unreadByTabId[tab.id])}
        </button>`).join('')}
    </nav>`;
}

// --- Coach chat tab ----------------------------------------------------------

function renderChatMessage(msg) {
  const roleClass = msg.role === 'user' ? 'me' : 'coach';
  const chips = (msg.toolCalls || [])
    .map((t) => `<span class="chat-chip">${esc(TOOL_LABELS[t.name] || t.name)}</span>`)
    .join('');

  let bubbleHtml;
  if (msg.status === 'error') {
    bubbleHtml = `<div class="chat-bubble is-error">${esc(msg.error || 'Something went wrong.')}</div>`;
  } else if (msg.status === 'refusal') {
    bubbleHtml = `<div class="chat-bubble is-refusal">${esc(msg.content)}</div>`;
  } else {
    const cursor = msg.status === 'streaming' ? '<span class="chat-cursor">▍</span>' : '';
    bubbleHtml = `<div class="chat-bubble">${esc(msg.content)}${cursor}</div>`;
  }

  return `
    <div class="chat-row ${roleClass}">
      ${chips ? `<div class="chat-chips">${chips}</div>` : ''}
      ${bubbleHtml}
    </div>`;
}

function renderChatEmptyState(backendConfigured) {
  if (!backendConfigured) {
    return `
      <div class="chat-empty">
        <p>Coach Chat needs you to sign in and set a backend URL and token before it can talk to the AI coach.</p>
        <button type="button" class="btn" data-a="tab:settings">Go to Settings</button>
      </div>`;
  }
  return `
    <div class="chat-empty">
      <p>Ask anything about training, pacing, fueling, recovery, or how this week is shaped.</p>
    </div>`;
}

export function renderCoachTab({
  messages, expertMode, sending, backendConfigured, online, role,
}) {
  const showComposer = backendConfigured;
  // Expert mode (physiologist/coach-facing detail) is gated to the coach
  // role -- it's not tied to a security boundary (see identity.js), just
  // keeps the athlete-facing UI from surfacing a toggle that isn't for them.
  const showExpertToggle = role === 'coach';
  return `
    <div class="wrap chat-wrap">
      <header class="mast chat-mast">
        <div>
          <span class="mark">swim-coach · coach chat</span>
          <h1>Ask your coach</h1>
          <p class="sub">Grounded in your plan and the research library.</p>
        </div>
        ${showExpertToggle ? `
        <label class="expert-toggle">
          <input type="checkbox" data-a="chat:expert-toggle" ${expertMode ? 'checked' : ''}>
          <span>Expert mode<small>physiologist / coach input</small></span>
        </label>` : ''}
      </header>

      ${!online ? '<div class="chat-banner">Offline -- Coach Chat needs a connection. The Plan tab still works offline.</div>' : ''}

      ${!backendConfigured || messages.length === 0
        ? renderChatEmptyState(backendConfigured)
        : `
        <div class="chat-messages" id="chat-messages">
          ${messages.map(renderChatMessage).join('')}
        </div>`}

      ${showComposer ? `
        <div class="chat-composer">
          <textarea id="chat-input" class="chat-input" placeholder="Ask your coach…" rows="2" ${sending || !online ? 'disabled' : ''}></textarea>
          <div class="chat-composer-row">
            <button type="button" class="btn-ghost" data-a="chat:clear" ${messages.length === 0 ? 'disabled' : ''}>New conversation</button>
            <button type="button" class="btn" data-a="chat:send" ${sending || !online ? 'disabled' : ''}>${sending ? 'Sending…' : 'Send'}</button>
          </div>
        </div>` : ''}
    </div>`;
}

// --- Log tab (workout logging) ------------------------------------------------

const SPORT_OPTIONS = [
  { value: 'swim_pool', label: 'Pool swim' },
  { value: 'swim_ow', label: 'Open water swim' },
  { value: 'strength', label: 'Strength' },
  { value: 'recovery', label: 'Recovery' },
  // Added for Phase 3 file upload: a non-swim FIT session (e.g. a kayak)
  // parses to this sport (see engine/swim_coach/parse_files.py's
  // _fit_sport) -- without this option, the <select> would silently fall
  // back to its first option (swim_pool) the moment a cross_train draft
  // pre-filled the form, corrupting exactly the swim-volume math the
  // two-step review/confirm design exists to protect.
  { value: 'cross_train', label: 'Cross-training' },
];

export function renderBackendNeededNotice(message) {
  return `
    <div class="chat-empty">
      <p>${esc(message)}</p>
      <button type="button" class="btn" data-a="tab:settings">Go to Settings</button>
    </div>`;
}

function renderSubmitResult(submit) {
  return submit.message
    ? `<div class="conn-result ${submit.status === 'success' ? 'ok' : 'fail'}">${esc(submit.message)}</div>`
    : '';
}

const SOURCE_LABELS = { fit: '.fit', tcx: '.tcx', csv: '.csv' };

// Renders the "here's what the file said" review card that appears once a
// file upload has parsed successfully -- see main.js's handleLogFileSelected
// (sets state.logIngest) and forms.js's logFormFromDraft (pre-fills
// state.logForm from the same WorkoutDraft this reads `warnings` off of).
// Warnings are surfaced prominently (not buried) per the Phase 3 design:
// a parsed file can be wrong (a kayak mapped to cross_train; a bad date),
// so the athlete needs to actually see the parser's caveats before saving.
function renderIngestSummary(ingest, form) {
  const warnings = form.warnings || [];
  const sportLabel = SPORT_OPTIONS.find((opt) => opt.value === form.sport)?.label || form.sport;
  return `
    <div class="conn-result ok">
      Parsed <b>${esc(ingest.fileName)}</b> (${esc(SOURCE_LABELS[form.source] || form.source)}) -- ${esc(sportLabel)}, ${esc(form.distance_m)} m, ${esc(form.duration_min)} min. Review the fields below, set your effort (RPE -- files never include it), then save.
    </div>
    ${warnings.length > 0 ? `
    <div class="conn-result fail">
      <b>${warnings.length === 1 ? 'Heads up' : `Heads up (${warnings.length})`}:</b>
      <ul style="margin:6px 0 0;padding-left:18px;">
        ${warnings.map((w) => `<li>${esc(w)}</li>`).join('')}
      </ul>
    </div>` : ''}`;
}

// --- Sync from watch (Phase 3 primary Log-tab action) -----------------------
// Calls POST /api/workouts/sync (main.js's handleSyncWorkouts) -- the same
// on-demand intervals.icu sync the coach chat's sync_workouts tool uses.
// Teal `.btn` primary treatment per the design handoff; manual entry/upload
// below is demoted to a secondary, collapsed-by-default action (see
// renderManualLogSection).
function renderSyncSection(sync, online) {
  const syncing = sync.status === 'syncing';
  return `
    <div class="panel settings-panel">
      <button type="button" class="btn" data-a="sync:start" style="width:100%;" ${syncing || !online ? 'disabled' : ''}>
        ${syncing ? 'Syncing…' : 'Sync from watch'}
      </button>
      ${sync.message ? `<div class="conn-result ${sync.status === 'error' ? 'fail' : 'ok'}">${esc(sync.message)}</div>` : ''}
    </div>`;
}

// --- CR-10 sRPE slider (A6a) -------------------------------------------------
// Shared component for BOTH the manual-log form's RPE field
// (renderManualLogSection below) and the workout-detail RPE editor
// (renderRpeEditSection) -- one slider, one anchor map, two call sites.
// Foster's modified Borg CR-10 scale (0-10, not 1-10) per
// `library/19-srpe-protocol.md` -- 6/8/9 are deliberately left unanchored in
// the original published instrument (not a gap in this table), rendered as
// an em-dash rather than fabricated text.
export const CR10_ANCHORS = {
  0: 'Rest / Nothing at all',
  1: 'Very Easy',
  2: 'Easy',
  3: 'Moderate',
  4: 'Somewhat Hard',
  5: 'Hard',
  7: 'Very Hard',
  10: 'Maximal / Exhausting',
};

/** The verbal anchor for one CR-10 value, or `null` for an unanchored rating
 * (6/8/9) or a missing/invalid value -- callers render `null` as an
 * em-dash. Exported so main.js's onAppInput can update the anchor caption
 * live as the slider is dragged, without a full render() (see that
 * handler's existing data-slider-out convention, which this mirrors via
 * `data-slider-anchor`). */
export function cr10AnchorLabel(value) {
  if (value === '' || value === null || value === undefined) return null;
  return CR10_ANCHORS[Number(value)] ?? null;
}

/** Renders just the `<input type="range">` + its live anchor caption --
 * callers wrap this in their own `<label class="field">`/`<span>` value
 * display (see renderManualLogSection and renderRpeEditSection), since the
 * two call sites format that surrounding markup slightly differently.
 * `value` follows the same "'' /null/undefined means unset" convention as
 * every other form field in this app (see renderManualLogSection's
 * `rpeMissing`) -- when unset, no `value` attribute is written so the
 * range input shows its native default (a mid-scale thumb position) until
 * the athlete actually drags it, exactly like the pre-existing bare
 * 1-10 slider did. */
export function renderCr10SliderField({
  value, formName, field, outId, disabled = false,
}) {
  const missing = value === '' || value === null || value === undefined;
  const anchorId = `${outId}-anchor`;
  const anchorText = cr10AnchorLabel(value);
  return `
    <input type="range" min="0" max="10" step="1" data-form="${esc(formName)}" data-field="${esc(field)}" data-slider-out="${esc(outId)}" data-slider-anchor="${esc(anchorId)}"${missing ? '' : ` value="${esc(value)}"`}${disabled ? ' disabled' : ''}>
    <p class="field-hint mono" id="${esc(anchorId)}">${anchorText ? esc(anchorText) : '&mdash;'}</p>`;
}

// --- Manual entry / file upload (Phase 3 secondary Log-tab action) ----------
// Demoted behind a collapsed-by-default toggle (state.logManualOpen, see
// main.js) -- the form/upload markup itself is unchanged from before this
// restructure once expanded.
function renderManualLogSection({
  form, submit, ingest, online, open,
}) {
  const toggleLabel = open ? 'Hide manual entry' : 'Log manually / upload a file';
  const toggleButton = `
    <div class="panel settings-panel">
      <button type="button" class="btn-ghost" data-a="log:toggle-manual" style="width:100%;" aria-expanded="${open ? 'true' : 'false'}">${toggleLabel}</button>
    </div>`;
  if (!open) return toggleButton;

  const rpeMissing = form.rpe === '' || form.rpe === null || form.rpe === undefined;
  const uploading = ingest.status === 'uploading';
  return `
    ${toggleButton}
    <div class="panel settings-panel">
      <label class="field">
        <span>Import from your watch (.fit, .tcx, .csv)</span>
        <input type="file" accept=".fit,.tcx,.csv" data-a="log:file-select" ${uploading || !online ? 'disabled' : ''}>
      </label>
      ${uploading ? '<p class="sub">Parsing&hellip;</p>' : ''}
      ${ingest.status === 'error' ? `<div class="conn-result fail">${esc(ingest.error)}</div>` : ''}
      ${ingest.status === 'ready' ? renderIngestSummary(ingest, form) : ''}
    </div>
    <div class="panel settings-panel">
      <label class="field">
        <span>Date</span>
        <input type="date" data-form="log" data-field="date" value="${esc(form.date)}">
      </label>
      <label class="field">
        <span>Sport</span>
        <select data-form="log" data-field="sport">
          ${SPORT_OPTIONS.map((opt) => `<option value="${opt.value}"${form.sport === opt.value ? ' selected' : ''}>${esc(opt.label)}</option>`).join('')}
        </select>
      </label>
      <label class="field">
        <span>Distance (m)</span>
        <input type="number" min="0" step="1" inputmode="numeric" data-form="log" data-field="distance_m" value="${esc(form.distance_m)}">
      </label>
      <label class="field">
        <span>Duration (min)</span>
        <input type="number" min="0" step="0.5" inputmode="decimal" data-form="log" data-field="duration_min" value="${esc(form.duration_min)}">
      </label>
      <label class="field">
        <span>RPE (effort) &middot; <output id="log-rpe-out">${rpeMissing ? '&ndash;' : esc(form.rpe)}</output>/10 <b id="log-rpe-required-badge"${rpeMissing ? '' : ' hidden'}>(required)</b></span>
        ${renderCr10SliderField({
          value: form.rpe, formName: 'log', field: 'rpe', outId: 'log-rpe-out',
        })}
      </label>
      <label class="field">
        <span>Notes</span>
        <textarea rows="3" data-form="log" data-field="notes" placeholder="How did it feel?">${esc(form.notes)}</textarea>
      </label>
      <div class="settings-actions">
        <button type="button" class="btn" data-a="log:submit" ${submit.status === 'submitting' || !online || rpeMissing ? 'disabled' : ''}>${submit.status === 'submitting' ? 'Saving…' : (form.source ? 'Confirm & save' : 'Save')}</button>
      </div>
      <p class="field-hint" id="log-rpe-hint"${rpeMissing ? '' : ' hidden'}>Set an effort (RPE) before saving.</p>
      ${renderSubmitResult(submit)}
    </div>`;
}

// --- Workout history (dashboard feed rows) --------------------------------
// Renders whatever's already been logged/imported -- manual entries plus
// .fit/.tcx/.csv/coach-text imports, which previously had no UI at all (see
// api.js's listWorkouts, which existed but nothing called). Kept as its own
// row-render function (rather than folded into renderTrainingDashboardBody's
// markup inline) so it's cheaply unit-testable on its own -- see
// tests/unit/views.test.js.

// Bioluminescent Dusk treatment: pace-ish values read in the teal accent,
// HR/attention values in amber -- see highlightDrift below for the drift
// line's own warning-threshold coloring. Wrapping in a span here only adds
// markup around text that's already rendered as-is (see the module doc
// comment on renderWorkoutRow's metaParts, which were never esc()'d because
// they're system-formatted, not user input) -- it doesn't change what text
// ends up on the page, so it's safe alongside the exact-substring checks in
// tests/unit/views.test.js and tests/e2e/test_workout_history.py.
function highlightDrift(line) {
  if (!line) return esc(line);
  // formatAnalyticsLine always puts formatDrift's output first when present
  // (see workouts.js), so the drift token -- if this line has one -- is
  // always a prefix of the full string.
  const match = /^(drift [+-]\d+\.\d+%( ⚠)?)/.exec(line);
  if (!match) return esc(line);
  const driftText = match[1];
  const rest = line.slice(driftText.length);
  const warn = Boolean(match[2]);
  return `<span class="stat-drift${warn ? ' stat-drift--warn' : ''}">${esc(driftText)}</span>${esc(rest)}`;
}

/** D2: a compact "<value> AU · <tier label>" chip -- shared by
 * renderWorkoutRow and renderCoachWorkoutRow below. Defensive: renders
 * nothing when `load_au` is absent (old cached history data from before
 * this build, or any future code path that hasn't been updated to attach
 * it -- see backend/app/routes/workouts.py's module docstring) rather than
 * showing a broken half-chip; a recognized-but-unlabeled `load_tier`
 * (shouldn't happen, but defensive) still shows the bare number. */
function renderLoadChip(workout) {
  if (workout.load_au === null || workout.load_au === undefined) return '';
  const tierLabel = loadTierLabel(workout.load_tier);
  return `<span class="chat-chip">${esc(workout.load_au)} AU${tierLabel ? ` &middot; ${esc(tierLabel)}` : ''}</span>`;
}

/** RPE chip -- shared by renderWorkoutRow and renderCoachWorkoutRow. A real
 * `rpe` renders the existing "RPE {n}" chip unchanged. A missing `rpe`
 * (null/undefined -- common and expected for e.g. GPS-only swims, not an
 * error) now renders an explicit "No RPE" chip instead of nothing at all:
 * previously a missing RPE was silently omitted, so the athlete/coach
 * couldn't tell "this workout has no RPE" from "the row just hasn't
 * rendered it yet." This matters more now that the load narrative (see
 * renderCtlAtlTsbNarrative) can point at a workout's load number, and
 * whether RPE was present is part of how that number was derived. Reuses
 * the plain `.chat-chip` style (already the quiet/neutral default in this
 * file -- unlike the accent-colored `.chip-cta` or attention-colored
 * `.chip-skipped`) rather than an alarming one, since an absent RPE is
 * informational, not a problem. */
function renderRpeChip(workout) {
  if (workout.rpe !== null && workout.rpe !== undefined) {
    return `<span class="chat-chip">RPE ${esc(workout.rpe)}</span>`;
  }
  return '<span class="chat-chip">No RPE</span>';
}

// A6c: an in-app-only "rate this workout" nudge -- no push notification, no
// new fetch/timer plumbing (explicitly out of scope this build, see the
// plan doc). Evaluated purely from data already in the feed, only at
// render time (i.e. only while the app happens to be open) against an
// injected `now` (mirrors history.js's buildHistoryFeed({ now }) pattern)
// so this stays deterministically testable rather than reading
// `Date.now()` with no override.
const RPE_REMINDER_DELAY_MS = 30 * 60 * 1000; // library/19-srpe-protocol.md's ~30-min post-workout ask-timing convention.

/** Best estimate of when a workout ended -- prefers a real FIT-derived
 * `started_at` + `duration_min` (the true finish time), falls back to
 * `logged_at` (the record-saved/"upload" time), and returns `null` (never
 * a fabricated timestamp) when neither is present. */
function estimateWorkoutFinishMs(workout) {
  if (workout.started_at) {
    const startMs = new Date(workout.started_at).getTime();
    if (!Number.isNaN(startMs)) return startMs + (workout.duration_min || 0) * 60000;
  }
  if (workout.logged_at) {
    const loggedMs = new Date(workout.logged_at).getTime();
    if (!Number.isNaN(loggedMs)) return loggedMs;
  }
  return null;
}

/** Tapping this chip opens the workout detail with the RPE editor already
 * open (`history:open-rate`, handled by main.js's
 * handleOpenHistoryDetailForRating) -- distinct from the plain
 * `history:open` the rest of the row triggers. A `<span>`, not a nested
 * `<button>` (this whole row is already a `<button>`) -- `onAppClick`'s
 * `e.target.closest('[data-a]')` delegation finds this element first when
 * tapped, so only the rate action fires, never both. */
function renderRateChip(workout, now) {
  if (workout.rpe !== null && workout.rpe !== undefined) return '';
  const finishMs = estimateWorkoutFinishMs(workout);
  if (finishMs === null) return '';
  if (now - finishMs < RPE_REMINDER_DELAY_MS) return '';
  return `<span class="chat-chip chip-cta" data-a="history:open-rate" data-id="${esc(workout.id)}">Rate this workout</span>`;
}

export function renderWorkoutRow(workout, now = Date.now()) {
  const metaParts = [formatDuration(workout.duration_min)];
  const distance = formatWorkoutDistance(workout.distance_m);
  if (distance) metaParts.push(distance);
  const pace = formatPace(workout.avg_pace_s_per_100m);
  if (pace) metaParts.push(`<span class="stat-pace">${esc(pace)} /100m</span>`);

  const badge = sourceBadge(workout.source);
  const analyticsLine = formatAnalyticsLine(workout.analytics);

  return `
    <button type="button" class="hist-row" data-a="history:open" data-id="${esc(workout.id)}">
      <div class="hist-date mono">${esc(formatShortDate(parseIsoDate(workout.date.slice(0, 10))))}</div>
      <div class="hist-body">
        <div class="hist-title">
          <span>${esc(sportLabel(workout.sport, workout.sport_detail))}</span>
          ${badge ? `<span class="chat-chip">${esc(badge)}</span>` : ''}
          ${renderRpeChip(workout)}
          ${renderLoadChip(workout)}
          ${renderRateChip(workout, now)}
        </div>
        <div class="hist-meta mono">${metaParts.join(' · ')}</div>
        ${analyticsLine ? `<div class="hist-analytics mono">${highlightDrift(analyticsLine)}</div>` : ''}
      </div>
    </button>`;
}

// --- Training dashboard feed (Log+History merge, Build 1) ------------------
// "History should show workouts completed with actual stats and planned
// workout skipped." One reverse-chronological feed of both, built by
// history.js's buildHistoryFeed (see that module on why "skipped" is
// derived rather than read from Session.status).
//
// Completed rows reuse renderWorkoutRow/renderWorkoutDetail verbatim -- the
// original Log tab's history section already rendered exactly the "actual
// stats" half correctly, and forking it would guarantee drift.

/** A planned-but-never-done session. Deliberately a `<div>`, not the
 * `<button>` a completed row is: there is no detail view to open, because
 * there is no logged data behind it -- everything known about a skipped
 * session is already on this row. Making it look tappable would promise a
 * screen that can't exist. */
function renderSkippedRow(session) {
  const metaParts = [];
  const duration = formatDuration(session.duration_min);
  if (duration) metaParts.push(duration);
  const distance = formatDistance(session.distance_m);
  if (distance) metaParts.push(`planned ~${distance}`);

  return `
    <div class="hist-row hist-row-skipped">
      <div class="hist-date mono">${esc(formatShortDate(parseIsoDate(session.date)))}</div>
      <div class="hist-body">
        <div class="hist-title">
          <span>${esc(sportLabel(session.sport))}</span>
          <span class="chat-chip chip-skipped">Skipped</span>
        </div>
        ${metaParts.length > 0 ? `<div class="hist-meta mono">${metaParts.join(' · ')}</div>` : ''}
        ${session.purpose ? `<div class="hist-analytics">${esc(session.purpose)}</div>` : ''}
      </div>
    </div>`;
}

/** One feed item (either kind) as a row -- `renderCompletedRow` lets each
 * surface plug in its own completed-row treatment (the athlete's own
 * `renderWorkoutRow`, or the coach roster's `renderCoachWorkoutRow` with its
 * planned-vs-actual quality line) while sharing this one mapping. `now`
 * threads through to `renderCompletedRow` for `renderWorkoutRow`'s A6c
 * rate-reminder chip (see that function); `renderCoachWorkoutRow` ignores
 * the extra argument. */
function renderFeedRow(item, renderCompletedRow, now) {
  return item.kind === 'completed' ? renderCompletedRow(item.workout, now) : renderSkippedRow(item.session);
}

/** The shared body of the merged Training Dashboard (Log+History merge,
 * Build 1 of the wellness-ingestion + training-dashboard plan): the
 * CTL/ATL/TSB load chart, then caller-supplied `actions` markup (the
 * athlete's own sync/manual-entry section -- `null` for the coach roster's
 * read-only view of someone else's training), then one paginated,
 * reverse-chronological feed of completed (and, for the athlete's own
 * dashboard, derived-skipped) sessions. Exactly one render function, called
 * from both `renderDashboardTab` (athlete) and `renderRosterTab` (coach) --
 * see each call site for how their `feed`/`actions`/row-rendering differ.
 *
 * Pagination: renders only the most recent `HISTORY_DISPLAY_CAP` feed items
 * by default, with a "Show more" control revealing the rest -- applies to
 * both surfaces since both funnel through this one function. `feedExpanded`
 * is the caller's own bit of state (main.js's `state.dashboardFeedExpanded`
 * / `state.roster.feedExpanded`); this stays a pure render like every other
 * view here.
 *
 * Tapping a completed row opens its detail view (`renderWorkoutDetail`,
 * verbatim) via `detailId` -- when it matches, this returns ONLY a back
 * button plus the detail (no chart, no actions, no feed list), same
 * convention the original History tab used: a focused detail view, not a
 * busier one. `chat: false` (roster) omits the embedded "ask your coach"
 * thread entirely -- that's an athlete-only AI feature, never shown on a
 * coach's read-only view of someone else's workout. */
function renderTrainingDashboardBody({
  load, feed, status, error, online, detailId, workoutChat, actions, feedExpanded,
  renderCompletedRow = renderWorkoutRow,
  backAction = 'history:back',
  chat = true,
  // A6b: only the athlete's own Dashboard tab call site opts into the RPE
  // editor (`editable: true` + a real `rpeEdit` state slice) -- the coach
  // roster's call site leaves both at their defaults, so `renderWorkoutDetail`
  // never renders an Edit affordance there. This isn't just a UI choice:
  // `PATCH /api/workouts/{id}` is self-access only (`resolve_athlete`, not
  // `resolve_coach_athlete` -- see backend/app/auth.py), so a coach session
  // could never actually save an edit there even if the button existed.
  rpeEdit = null,
  editable = false,
  now = Date.now(),
  emptyMessage = 'Nothing logged or missed yet. Once you log a session (or miss a planned one), it shows up here.',
  // Coach-mode Q&A build: threaded straight through to `renderWorkoutDetail`
  // -- see that function's own `askCoach` doc comment. `null` (every
  // pre-existing call site of this function, until each is updated) renders
  // an empty read-only Q&A section rather than crashing.
  askCoach = null,
  // Two-panel load chart (web/two-panel-load-chart): threaded straight
  // through to `renderLoadChart` -- see that function's own doc comment for
  // what each means. `showWellnessInline` defaults `true` (the coach
  // roster's call site leaves it at the default); the athlete's own
  // Dashboard call site (`renderDashboardTab`) passes `false` and renders
  // `renderWellnessBaselineDeviation` inside the Check-in tab instead.
  loadWindowDays,
  loadNarrativeExpanded = false,
  showWellnessInline = true,
}) {
  const items = feed || [];
  const hasData = items.length > 0;

  if (hasData && detailId) {
    const match = items.find((i) => i.kind === 'completed' && i.workout.id === detailId);
    if (match) {
      return `
        <section class="hist-section">
          <div class="s-head"><button type="button" class="btn-ghost" data-a="${backAction}">&larr; Back</button></div>
          ${renderWorkoutDetail(match.workout, {
            chat: chat ? workoutChat : null, online, rpeEdit, editable, askCoach,
          })}
        </section>`;
    }
  }

  const capped = feedExpanded ? items : items.slice(0, HISTORY_DISPLAY_CAP);
  const remaining = items.length - capped.length;

  const feedBody = (() => {
    if (status === 'error') {
      return `
        ${hasData ? `<div class="hist-list">${capped.map((item) => renderFeedRow(item, renderCompletedRow, now)).join('')}</div>` : ''}
        <div class="hist-error">Couldn't load your training history: ${esc(error)}</div>
        <div class="settings-actions"><button type="button" class="btn-ghost" data-a="history:retry">Retry</button></div>`;
    }
    if (status === 'loading' && !hasData) {
      return '<p class="sub">Loading history&hellip;</p>';
    }
    if (!hasData) {
      const notice = !online ? 'This needs a connection -- reconnect to load it.' : emptyMessage;
      return `<p class="sub">${esc(notice)}</p>`;
    }
    return `
      <div class="hist-list">${capped.map((item) => renderFeedRow(item, renderCompletedRow, now)).join('')}</div>
      ${remaining > 0 ? `
      <div class="settings-actions">
        <button type="button" class="btn-ghost" data-a="dashboard:show-more">Show ${remaining} more</button>
      </div>` : ''}`;
  })();

  return `
    ${renderLoadChart(load, { windowDays: loadWindowDays, narrativeExpanded: loadNarrativeExpanded, showWellnessInline })}
    ${actions || ''}
    <section class="hist-section">
      <div class="s-head"><h2>Workouts</h2></div>
      ${feedBody}
    </section>`;
}

function dashboardShell(body) {
  return `
    <div class="wrap settings-wrap">
      <header class="mast" style="border-bottom:none;padding-bottom:0;">
        <div>
          <span class="mark">swim-coach · dashboard</span>
          <h1>Training dashboard</h1>
          <p class="sub">Your fitness/fatigue trend, plus everything completed or missed.</p>
        </div>
      </header>
      ${body}
    </div>`;
}

/** The athlete's own merged Log+History tab (Build 1): sync-from-watch +
 * manual-entry actions (the original Log tab's own markup, unchanged --
 * `renderSyncSection`/`renderManualLogSection` above), stacked on top of
 * `renderTrainingDashboardBody`'s shared chart+feed. The full completed+
 * missed feed (built by main.js via `history.js`'s `buildHistoryFeed`) --
 * unlike the coach roster's completed-only view, see `renderRosterTab`. */
export function renderDashboardTab({
  load, feed, status, error, online, detailId, workoutChat, backendConfigured,
  form, submit, ingest, sync, manualOpen, feedExpanded, rpeEdit, askCoach,
  loadWindowDays, loadNarrativeExpanded,
}) {
  if (!backendConfigured) {
    return dashboardShell(renderBackendNeededNotice(
      'The dashboard needs you to sign in and set a backend URL and token in Settings.',
    ));
  }

  const actions = `
    ${renderSyncSection(sync, online)}
    ${renderManualLogSection({ form, submit, ingest, online, open: !!manualOpen })}`;

  return dashboardShell(`
    ${!online ? '<div class="chat-banner">Offline -- some data may be out of date.</div>' : ''}
    ${renderTrainingDashboardBody({
      load, feed, status, error, online, detailId, workoutChat, actions, feedExpanded, rpeEdit, editable: true, askCoach,
      loadWindowDays, loadNarrativeExpanded,
      // Resolved decision (web/two-panel-load-chart): the athlete's OWN
      // Dashboard tab moves the wellness-deviation block OUT of this chart
      // and into the Check-in tab instead (see renderCheckinTab) -- the
      // coach roster's call site (renderRosterTab) leaves this at its
      // `true` default and keeps it rendering here, since there's no
      // coach-side Check-in-tab equivalent to move it to.
      showWellnessInline: false,
    })}`);
}

// --- Workout detail view (tapping a history row) --------------------------
// Renders from the already-fetched full workout dump in state -- no second
// API call. Every section (summary stats, analytics, laps, pauses, lengths,
// notes) is conditional on its own field(s) being present, so an old
// manual-entry workout (none of laps/pauses/analytics) still renders a
// clean summary-stats-only view instead of a half-empty one.

// `kind` is a purely visual hook (Bioluminescent Dusk: pace-ish values in
// teal, HR/attention values in amber, see index.html's .stat-pace/.stat-hr)
// -- optional and additive, doesn't change the existing markup shape.
function renderDetailStat(label, value, kind) {
  if (value === null || value === undefined || value === '') return '';
  const valueClass = kind ? ` stat-${kind}` : '';
  return `<div class="detail-stat"><div class="l">${esc(label)}</div><div class="v${valueClass}">${esc(value)}</div></div>`;
}

/** D2's "Load (AU)" detail-view tile -- a `.detail-stat` like every other
 * tile `renderDetailStat` produces, but with a small reliability-tier chip
 * embedded in the value (so it needs its own markup rather than
 * `renderDetailStat`'s plain-text-only value). Defensive: renders nothing
 * when `load_au` is absent (old cached data, or a code path that hasn't
 * been updated -- see backend/app/routes/workouts.py) rather than crashing
 * or showing a chip with no number behind it. */
function renderLoadDetailStat(workout) {
  if (workout.load_au === null || workout.load_au === undefined) return '';
  const tierLabel = loadTierLabel(workout.load_tier);
  return `
    <div class="detail-stat">
      <div class="l">Load (AU)</div>
      <div class="v">${esc(workout.load_au)}${tierLabel ? ` <span class="chat-chip">${esc(tierLabel)}</span>` : ''}</div>
    </div>`;
}

function renderDetailStats(workout) {
  const pace = formatPace(workout.avg_pace_s_per_100m);
  const hasRpe = workout.rpe !== null && workout.rpe !== undefined;
  const hasAvgHr = workout.avg_hr !== null && workout.avg_hr !== undefined;
  const hasMaxHr = workout.max_hr !== null && workout.max_hr !== undefined;
  const stats = [
    renderDetailStat('Distance', formatWorkoutDistance(workout.distance_m)),
    renderDetailStat('Duration', formatDuration(workout.duration_min)),
    renderDetailStat('Pace', pace ? `${pace} /100m` : null, 'pace'),
    renderDetailStat('RPE', hasRpe ? `${workout.rpe}/10` : null),
    renderDetailStat('Avg HR', hasAvgHr ? `${workout.avg_hr} bpm` : null, 'hr'),
    renderDetailStat('Max HR', hasMaxHr ? `${workout.max_hr} bpm` : null, 'hr'),
    renderLoadDetailStat(workout),
  ].join('');
  return `<div class="detail-stats">${stats}</div>`;
}

// --- A6b: editable RPE on the workout detail view --------------------------
// Only rendered when the caller opts in via `editable: true` (the athlete's
// own Dashboard tab -- see renderTrainingDashboardBody/renderDashboardTab).
// Mirrors the `state.logManualOpen` disclosure mechanic: a toggle button
// swaps in the CR-10 slider + Save/Cancel, driven entirely by main.js's
// `state.workoutRpeEdit` (null = not editing).

function renderRpeEditSection(workout, rpeEdit) {
  const isEditingThis = !!rpeEdit && rpeEdit.workoutId === workout.id;
  const hasRpe = workout.rpe !== null && workout.rpe !== undefined;

  if (!isEditingThis) {
    return `
      <div class="settings-actions">
        <button type="button" class="btn-ghost" data-a="workout:edit-rpe" data-id="${esc(workout.id)}">${hasRpe ? 'Edit RPE' : 'Rate this workout'}</button>
      </div>`;
  }

  const submitting = rpeEdit.status === 'submitting';
  const missing = rpeEdit.rpe === '' || rpeEdit.rpe === null || rpeEdit.rpe === undefined;
  return `
    <section class="detail-section" id="workout-rpe-edit">
      <h4>Rate this workout</h4>
      <label class="field">
        <span>RPE (effort) &middot; <output id="workout-rpe-edit-out">${missing ? '&ndash;' : esc(rpeEdit.rpe)}</output>/10</span>
        ${renderCr10SliderField({
          value: rpeEdit.rpe, formName: 'workoutRpe', field: 'rpe', outId: 'workout-rpe-edit-out', disabled: submitting,
        })}
      </label>
      ${rpeEdit.status === 'error' ? `<div class="conn-result fail">${esc(rpeEdit.error)}</div>` : ''}
      <div class="settings-actions">
        <button type="button" class="btn" data-a="workout:save-rpe" data-id="${esc(workout.id)}" ${submitting || missing ? 'disabled' : ''}>${submitting ? 'Saving…' : 'Save'}</button>
        <button type="button" class="btn-ghost" data-a="workout:cancel-edit-rpe" ${submitting ? 'disabled' : ''}>Cancel</button>
      </div>
    </section>`;
}

/** The full (not compact-line) analytics block -- each of the same five
 * sub-fields formatAnalyticsLine joins into one hist-row line, rendered
 * here as its own row instead, still each conditional on its own presence
 * (formatDrift/formatSplit/formatPauses/formatSwolf/formatMovingVsElapsed
 * all already return null cleanly when their field is absent). */
function renderDetailAnalytics(analytics) {
  if (!analytics) return '';
  const lines = [
    formatDrift(analytics.cardiac_drift_pct),
    formatSplit(analytics),
    formatMovingVsElapsed(analytics),
    formatPauses(analytics),
    formatSwolf(analytics),
  ].filter(Boolean);
  if (lines.length === 0) return '';
  return `
    <section class="detail-section">
      <h4>Analytics</h4>
      <div class="detail-analytics-list">${lines.map((line) => `<div>${highlightDrift(line)}</div>`).join('')}</div>
    </section>`;
}

function renderLapsTable(laps) {
  if (!laps || laps.length === 0) return '';
  const rows = laps.map((lap) => {
    const distance = formatWorkoutDistance(lap.distance_m);
    const duration = formatClock(lap.duration_s);
    const pace = formatPace(lap.avg_pace_s_per_100m);
    const hasHr = lap.avg_hr !== null && lap.avg_hr !== undefined;
    return `
      <tr>
        <td>${esc(lap.index)}</td>
        <td>${distance ? esc(distance) : '—'}</td>
        <td>${duration ? esc(duration) : '—'}</td>
        <td>${pace ? esc(pace) : '—'}</td>
        <td>${hasHr ? esc(lap.avg_hr) : '—'}</td>
      </tr>`;
  }).join('');
  return `
    <section class="detail-section">
      <h4>Laps (${laps.length})</h4>
      <div class="laps-table-wrap">
        <table class="laps-table">
          <thead><tr><th>#</th><th>Dist</th><th>Time</th><th>Pace</th><th>HR</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </section>`;
}

function renderPausesList(pauses) {
  if (!pauses || pauses.length === 0) return '';
  const rows = pauses.map((pause) => {
    const offset = formatOffset(pause.start_offset_s);
    const duration = formatClock(pause.duration_s);
    return `<div class="pause-row mono">${esc(offset)} · ${esc(duration)} · ${esc(pause.source)}</div>`;
  }).join('');
  return `
    <section class="detail-section">
      <h4>Pauses (${pauses.length})</h4>
      <div class="pauses-list">${rows}</div>
    </section>`;
}

function renderLengthsSummarySection(lengths) {
  const summary = formatLengthsSummary(lengths?.length);
  if (!summary) return '';
  return `
    <section class="detail-section">
      <h4>Lengths</h4>
      <p class="sub">${esc(summary)}</p>
    </section>`;
}

function renderDetailNotes(notes) {
  if (!notes) return '';
  return `
    <section class="detail-section">
      <h4>Notes</h4>
      <p class="detail-notes">${esc(notes)}</p>
    </section>`;
}

// --- Embedded workout chat (Phase C slice 1, per the design handoff's
// "Log tab -> Embedded workout chat") ---------------------------------------
// A scoped chat tied to the ONE workout the detail view shows -- same bubble/
// composer classes as the Coach tab (PR #43's chat treatment), its own
// message thread (main.js's state.workoutChat, EPHEMERAL: in-memory only,
// cleared when the detail closes). `chat` is {workoutId, messages} or null
// (defensive: renders nothing if it doesn't match this workout).

function renderWorkoutChatSection({ workout, chat, online }) {
  if (!chat || chat.workoutId !== workout.id) return '';
  const messages = chat.messages || [];
  const last = messages[messages.length - 1];
  const sending = !!last && last.role === 'assistant' && last.status === 'streaming';
  return `
    <section class="detail-section" id="workout-chat">
      <h4>Ask your coach about this workout</h4>
      <p class="sub">${esc(formatWorkoutChatLabel(workout))} · this thread isn't saved -- it clears when you leave this workout.</p>
      ${!online ? '<div class="chat-banner">Offline -- chatting about this workout needs a connection.</div>' : ''}
      ${messages.length > 0 ? `
      <div class="chat-messages" id="workout-chat-messages">
        ${messages.map(renderChatMessage).join('')}
      </div>` : ''}
      <div class="chat-composer">
        <textarea id="workout-chat-input" class="chat-input" placeholder="Ask about this workout…" rows="2" ${sending || !online ? 'disabled' : ''}></textarea>
        <div class="chat-composer-row">
          <span></span>
          <button type="button" class="btn" data-a="workout-chat:send" ${sending || !online ? 'disabled' : ''}>${sending ? 'Sending…' : 'Send'}</button>
        </div>
      </div>
    </section>`;
}

/** `askCoach` (coach-mode Q&A build): `{ feedback, form, submit }`, same
 * shape `renderPlanSessionDetail` takes -- `feedback` is filtered here (via
 * `feedbackForWorkout`) down to just this workout's own questions. This
 * REPLACES the old `renderCoachConversationPlaceholder` stub ("coach
 * conversation -- coming soon") with the real component that stub was
 * gesturing at -- shown on the workout detail view in BOTH the athlete's
 * own Dashboard tab (`form` set, wired to a real submit action) and the
 * coach's roster view of the same workout (`form: null`/absent, read-only;
 * `chat` stays `null` there too, so `renderWorkoutChatSection` still renders
 * nothing on that surface -- unchanged). */
function renderWorkoutDetail(workout, {
  chat, online, rpeEdit = null, editable = false, askCoach = null,
} = {}) {
  const badge = sourceBadge(workout.source);
  return `
    <div class="detail-header">
      <h3>${esc(sportLabel(workout.sport, workout.sport_detail))}</h3>
      <div class="hist-meta mono">${esc(formatLongDate(parseIsoDate(workout.date.slice(0, 10))))}${badge ? ` <span class="chat-chip">${esc(badge)}</span>` : ''}</div>
    </div>
    ${renderDetailStats(workout)}
    ${editable ? renderRpeEditSection(workout, rpeEdit) : ''}
    ${renderDetailAnalytics(workout.analytics)}
    ${renderLapsTable(workout.laps)}
    ${renderPausesList(workout.pauses)}
    ${renderLengthsSummarySection(workout.lengths)}
    ${renderDetailNotes(workout.notes)}
    ${renderAskCoachSection({
      questions: feedbackForWorkout(askCoach?.feedback, workout.id),
      form: askCoach?.form ?? null,
      submit: askCoach?.submit,
    })}
    ${renderWorkoutChatSection({ workout, chat, online })}`;
}

// --- Check-in tab (daily wellness) ---------------------------------------------

/** Resolved decision (web/two-panel-load-chart): the resting-HR/HRV
 * baseline-deviation cross-check moved OUT of the athlete's own Dashboard
 * chart (`renderLoadChart`'s `showWellnessInline: false` call site) and
 * into the top of this form instead -- directly relevant context for "how
 * are you feeling" (RHR/HRV IS part of that story). Reuses the app's
 * ALREADY-fetched `load` state (`main.js`'s `state.planLoad`, the same data
 * the Dashboard tab's chart already pulls `ctl_atl_tsb` from -- and which
 * `main.js` fetches unconditionally at boot, independent of which tab is
 * active, so this data is normally already in flight or landed by the time
 * Check-in renders, even without a prior Dashboard visit) rather than
 * firing a second `GET /api/plan/load`. Renders nothing (not a loading/
 * error state of its own) until that fetch actually lands -- the form
 * itself is fully usable in the meantime; this tab never blocks on, or
 * duplicates, that request. */
export function renderCheckinTab({
  form, submit, backendConfigured, online, load,
}) {
  return `
    <div class="wrap settings-wrap">
      <header class="mast" style="border-bottom:none;padding-bottom:0;">
        <div>
          <span class="mark">swim-coach · check-in</span>
          <h1>How are you feeling?</h1>
          <p class="sub">A quick daily check-in -- sleep, stress, soreness, motivation.</p>
        </div>
      </header>
      ${!online ? '<div class="chat-banner">Offline -- check-in needs a connection.</div>' : ''}
      ${!backendConfigured ? renderBackendNeededNotice('Checking in needs you to sign in and set a backend URL and token first.') : `
      ${load?.data ? `<div class="panel settings-panel">${renderWellnessBaselineDeviation(load.data.wellness_baseline_deviation)}</div>` : ''}
      <div class="panel settings-panel">
        <label class="field">
          <span>Date</span>
          <input type="date" data-form="checkin" data-field="date" value="${esc(form.date)}">
        </label>
        <label class="field">
          <span>Sleep quality &middot; <output id="checkin-sleep_quality-out">${esc(form.sleep_quality)}</output>/5</span>
          <input type="range" min="1" max="5" step="1" data-form="checkin" data-field="sleep_quality" data-slider-out="checkin-sleep_quality-out" value="${esc(form.sleep_quality)}">
        </label>
        <label class="field">
          <span>Sleep hours</span>
          <input type="number" min="0" step="0.25" inputmode="decimal" data-form="checkin" data-field="sleep_hours" value="${esc(form.sleep_hours)}">
        </label>
        <label class="field">
          <span>Stress &middot; <output id="checkin-stress-out">${esc(form.stress)}</output>/5</span>
          <input type="range" min="1" max="5" step="1" data-form="checkin" data-field="stress" data-slider-out="checkin-stress-out" value="${esc(form.stress)}">
        </label>
        <label class="field">
          <span>Soreness &middot; <output id="checkin-soreness-out">${esc(form.soreness)}</output>/5</span>
          <input type="range" min="1" max="5" step="1" data-form="checkin" data-field="soreness" data-slider-out="checkin-soreness-out" value="${esc(form.soreness)}">
        </label>
        <label class="field">
          <span>Motivation &middot; <output id="checkin-motivation-out">${esc(form.motivation)}</output>/5</span>
          <input type="range" min="1" max="5" step="1" data-form="checkin" data-field="motivation" data-slider-out="checkin-motivation-out" value="${esc(form.motivation)}">
        </label>
        <label class="field">
          <span>Resting HR (optional)</span>
          <input type="number" min="0" step="1" inputmode="numeric" data-form="checkin" data-field="resting_hr" value="${esc(form.resting_hr)}">
        </label>
        <label class="field">
          <span>HRV (optional)</span>
          <input type="number" min="0" step="0.1" inputmode="decimal" data-form="checkin" data-field="hrv" value="${esc(form.hrv)}">
        </label>
        <label class="field">
          <span>Notes</span>
          <textarea rows="3" data-form="checkin" data-field="notes" placeholder="Anything else going on?">${esc(form.notes)}</textarea>
        </label>
        <div class="settings-actions">
          <button type="button" class="btn" data-a="checkin:submit" ${submit.status === 'submitting' || !online ? 'disabled' : ''}>${submit.status === 'submitting' ? 'Saving…' : 'Save'}</button>
        </div>
        ${renderSubmitResult(submit)}
      </div>`}
    </div>`;
}

// --- Profile edit (Settings tab section) --------------------------------------
// Self-service profile editing (Phase 2.5) -- an athlete edits name/dob/sex/
// height/weight/CSS pace/pool days themselves instead of Fable hand-loading
// YAML. Lives as a section within the Settings tab (rather than its own tab)
// to minimize nav churn -- see main.js's loadProfile/handleSubmitProfile and
// forms.js's profileFormFromAthlete/serializeProfileForm for the data side.

const SEX_OPTIONS = [
  { value: '', label: 'Prefer not to say' },
  { value: 'male', label: 'Male' },
  { value: 'female', label: 'Female' },
  { value: 'other', label: 'Other' },
];

const POOL_DAY_LABELS = [
  { value: 'monday', label: 'Mon' },
  { value: 'tuesday', label: 'Tue' },
  { value: 'wednesday', label: 'Wed' },
  { value: 'thursday', label: 'Thu' },
  { value: 'friday', label: 'Fri' },
  { value: 'saturday', label: 'Sat' },
  { value: 'sunday', label: 'Sun' },
];

function renderProfilePanel({ form, load, submit }) {
  if (load.status === 'loading' || load.status === 'idle') {
    return `
      <div class="panel settings-panel">
        <h3 style="margin:0 0 12px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);">Your profile</h3>
        <p class="sub">Loading your profile&hellip;</p>
      </div>`;
  }

  const loadError = load.status === 'error'
    ? `<div class="conn-result fail">Couldn't load your profile: ${esc(load.error)}</div>` : '';

  return `
    <div class="panel settings-panel">
      <h3 style="margin:0 0 12px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);">Your profile</h3>
      ${loadError}
      <label class="field">
        <span>Name</span>
        <input type="text" data-form="profile" data-field="name" value="${esc(form.name)}">
      </label>
      <label class="field">
        <span>Date of birth</span>
        <input type="date" data-form="profile" data-field="dob" value="${esc(form.dob)}">
      </label>
      <label class="field">
        <span>Sex</span>
        <select data-form="profile" data-field="sex">
          ${SEX_OPTIONS.map((opt) => `<option value="${opt.value}"${form.sex === opt.value ? ' selected' : ''}>${esc(opt.label)}</option>`).join('')}
        </select>
      </label>
      <label class="field">
        <span>Height</span>
        <div style="display:flex;gap:8px;">
          <input type="number" min="0" step="1" inputmode="numeric" placeholder="ft" style="width:5em;" data-form="profile" data-field="heightFeet" value="${esc(form.heightFeet)}">
          <input type="number" min="0" max="11" step="1" inputmode="numeric" placeholder="in" style="width:5em;" data-form="profile" data-field="heightInches" value="${esc(form.heightInches)}">
        </div>
      </label>
      <label class="field">
        <span>Weight (lb)</span>
        <input type="number" min="0" step="0.1" inputmode="decimal" data-form="profile" data-field="weightLb" value="${esc(form.weightLb)}">
      </label>
      <label class="field">
        <span>CSS pace (per 100m, mm:ss)</span>
        <input type="text" placeholder="1:40" data-form="profile" data-field="cssPace" value="${esc(form.cssPace)}">
      </label>
      <label class="field">
        <span>Lactate-threshold heart rate (bpm)</span>
        <input type="number" min="0" step="1" inputmode="numeric" placeholder="e.g. 172" data-form="profile" data-field="lthrBpm" value="${esc(form.lthrBpm)}">
      </label>
      <label class="field">
        <span>Pool days</span>
        <div class="pool-days">
          ${POOL_DAY_LABELS.map((day) => `
            <label class="pool-day">
              <input type="checkbox" data-form="profile" data-field="pool_days" data-day="${day.value}" ${form.poolDays?.[day.value] ? 'checked' : ''}>
              <span>${day.label}</span>
            </label>`).join('')}
        </div>
      </label>
      <label class="field pool-day" style="flex-direction:row;align-items:center;gap:8px;">
        <input type="checkbox" data-form="profile" data-field="email_notifications_enabled" ${form.emailNotificationsEnabled ? 'checked' : ''}>
        <span>Email notifications (a coach reply, or your own question reaching your coach)</span>
      </label>
      <div class="settings-actions">
        <button type="button" class="btn" data-a="profile:submit" ${submit.status === 'submitting' ? 'disabled' : ''}>${submit.status === 'submitting' ? 'Saving…' : 'Save'}</button>
      </div>
      ${renderSubmitResult(submit)}
    </div>`;
}

// --- Feedback tab (durable feedback log) ---------------------------------

const FEEDBACK_TYPE_OPTIONS = [
  { value: 'feature_request', label: 'Feature request' },
  { value: 'comment', label: 'Comment' },
  { value: 'bug', label: 'Bug' },
];

const FEEDBACK_TYPE_LABELS = {
  research_question: 'Research question',
  feature_request: 'Feature request',
  comment: 'Comment',
  bug: 'Bug',
};

function formatFeedbackDate(isoString) {
  const d = new Date(isoString);
  return Number.isNaN(d.getTime()) ? isoString : d.toLocaleString();
}

/** B2 (coach-mode Q&A build): previously this rendered only type/status/
 * body/date -- an athlete literally could not see an AI or coach answer to
 * her own question in this tab (the durable list of EVERYTHING, not just
 * workout/session-scoped like B1's renderAskCoachSection). Same three-state
 * answer treatment as `renderAskCoachEntry` (coach reply wins over the AI
 * answer if both exist; a "waiting on your coach" notice when neither exists
 * yet but the question was flagged for human review), plus the context line
 * B1 added to the coach's own roster view (`formatFeedbackContext`), so an
 * athlete can tell which workout/session an old question was about too. */
function renderFeedbackEntry(entry) {
  const context = formatFeedbackContext(entry);
  return `
    <div class="panel feedback-entry">
      <div class="feedback-entry-head">
        <span class="chat-chip">${esc(FEEDBACK_TYPE_LABELS[entry.type] || entry.type)}</span>
        ${entry.source === 'coach' ? '<span class="chat-chip">coach-logged</span>' : ''}
        <span class="feedback-entry-date mono">${esc(formatFeedbackDate(entry.created_at))}</span>
      </div>
      ${context ? `<div class="feedback-entry-context mono">${esc(context)}</div>` : ''}
      <p class="feedback-entry-body">${esc(entry.body)}</p>
      ${renderFeedbackAnswerBlock(entry)}
      <div class="feedback-entry-status mono">${esc(entry.status)}</div>
    </div>`;
}

function renderFeedbackList(entries) {
  if (!entries || entries.length === 0) {
    return '<p class="sub">Nothing logged yet.</p>';
  }
  return entries.map(renderFeedbackEntry).join('');
}

export function renderFeedbackTab({
  form, submit, entries, entriesStatus, backendConfigured, online,
}) {
  return `
    <div class="wrap settings-wrap">
      <header class="mast" style="border-bottom:none;padding-bottom:0;">
        <div>
          <span class="mark">swim-coach · feedback</span>
          <h1>Feedback</h1>
          <p class="sub">Feature requests, comments, bugs -- plus the coach's own logged research gaps.</p>
        </div>
      </header>
      ${!online ? '<div class="chat-banner">Offline -- feedback needs a connection.</div>' : ''}
      ${!backendConfigured ? renderBackendNeededNotice('Feedback needs you to sign in and set a backend URL and token first.') : `
      <div class="panel settings-panel">
        <label class="field">
          <span>Type</span>
          <select data-form="feedback" data-field="type">
            ${FEEDBACK_TYPE_OPTIONS.map((opt) => `<option value="${opt.value}"${form.type === opt.value ? ' selected' : ''}>${esc(opt.label)}</option>`).join('')}
          </select>
        </label>
        <label class="field">
          <span>Details</span>
          <textarea rows="4" data-form="feedback" data-field="body" placeholder="What's on your mind?">${esc(form.body)}</textarea>
        </label>
        <div class="settings-actions">
          <button type="button" class="btn" data-a="feedback:submit" ${submit.status === 'submitting' || !online ? 'disabled' : ''}>${submit.status === 'submitting' ? 'Saving…' : 'Send'}</button>
        </div>
        ${renderSubmitResult(submit)}
      </div>
      <section>
        <div class="s-head"><h2>Logged so far</h2></div>
        ${entriesStatus === 'loading' ? '<p class="sub">Loading…</p>' : renderFeedbackList(entries)}
      </section>`}
    </div>`;
}

// --- Roster tab ("My Athletes" -- coach-mode Phase 1) ----------------------
// Coach-side view: the athletes who've granted this signed-in identity
// coach access (GET /api/coach/athletes), then -- once one is selected --
// that athlete's logged workouts (each with a nested planned-vs-actual
// `quality` object, see engine/swim_coach/quality.py -- named `quality`, not
// `compliance`, so it doesn't collide with the engine's other, authoritative
// weekly-aggregate `compliance` number; see IDEAS.md's resolved IDEA 006)
// and durable feedback log, with a reply box for entries that don't have
// one yet.
// Deliberately scoped to roster + grants only for this chunk -- the
// direct-to-coach chat UI and the workout-comment box are a separate,
// later piece (see the branch brief).

function renderCoachedAthleteRow(athlete) {
  return `
    <button type="button" class="hist-row" data-a="roster:select-athlete" data-slug="${esc(athlete.slug)}">
      <div class="hist-body">
        <div class="hist-title"><span>${esc(athlete.name || athlete.slug)}</span></div>
        <div class="hist-meta mono">${esc(athlete.slug)}</div>
      </div>
    </button>`;
}

function renderCoachedAthletesList(athletes) {
  if (athletes.status === 'loading' && athletes.data.length === 0) {
    return '<p class="sub">Loading your athletes&hellip;</p>';
  }
  if (athletes.status === 'error') {
    return `<div class="hist-error">Couldn't load your athletes: ${esc(athletes.error)}</div>`;
  }
  if (athletes.data.length === 0) {
    return '<p class="sub">No one has granted you coach access yet.</p>';
  }
  return `<div class="hist-list">${athletes.data.map(renderCoachedAthleteRow).join('')}</div>`;
}

/** One `WorkoutQuality` (planned-vs-actual for a single logged workout)
 * rendered as a plain, one-line summary -- `matched: false` (no planned
 * session lines up with this workout at all) short-circuits before the
 * delta/intensity/quality fields are even meaningful. */
function formatQualityLine(quality) {
  if (!quality) return null;
  if (!quality.matched) return 'No matching planned session';
  const parts = [];
  if (quality.distance_delta_pct !== null && quality.distance_delta_pct !== undefined) {
    const sign = quality.distance_delta_pct >= 0 ? '+' : '';
    parts.push(`${sign}${quality.distance_delta_pct.toFixed(1)}% distance`);
  }
  if (quality.duration_delta_pct !== null && quality.duration_delta_pct !== undefined) {
    const sign = quality.duration_delta_pct >= 0 ? '+' : '';
    parts.push(`${sign}${quality.duration_delta_pct.toFixed(1)}% duration`);
  }
  parts.push(`${quality.intensity_match} intensity`);
  return parts.join(', ');
}

// `now` is accepted (unused) so this matches renderCompletedRow's shared
// `(workout, now)` call shape (see renderFeedRow) -- no rate-reminder chip
// here, only D2's load chip: this is the coach's read-only view of someone
// else's training, and the reminder is an athlete-facing nudge to log their
// own effort, not something a coach acts on.
function renderCoachWorkoutRow(workout, now) {
  const metaParts = [formatDuration(workout.duration_min)];
  const distance = formatWorkoutDistance(workout.distance_m);
  if (distance) metaParts.push(distance);
  const qualityLine = formatQualityLine(workout.quality);
  const qualitySummary = workout.quality?.quality_summary;

  return `
    <button type="button" class="hist-row hist-row-skipped" data-a="roster:open-workout" data-id="${esc(workout.id)}">
      <div class="hist-date mono">${esc(formatShortDate(parseIsoDate(workout.date.slice(0, 10))))}</div>
      <div class="hist-body">
        <div class="hist-title">
          <span>${esc(sportLabel(workout.sport, workout.sport_detail))}</span>
          ${renderRpeChip(workout)}
          ${renderLoadChip(workout)}
        </div>
        <div class="hist-meta mono">${metaParts.join(' · ')}</div>
        ${qualityLine ? `<div class="hist-analytics mono">${esc(qualityLine)}</div>` : ''}
        ${qualitySummary ? `<div class="hist-analytics">${esc(qualitySummary)}</div>` : ''}
      </div>
    </button>`;
}

/** Small "about" line describing which workout/session a Feedback entry is
 * linked to (coach-mode Q&A build) -- previously the coach's roster Feedback
 * list showed a bare question with no indication of what it was about.
 * `null` for an unlinked entry (a plain feature_request/comment/bug, or a
 * coach-logged research_question -- neither carries either field). Plain
 * text, unescaped -- callers `esc()` it same as any other interpolated
 * value. */
function formatFeedbackContext(entry) {
  if (entry.workout_id) return 'About a logged workout';
  if (entry.session_date) {
    return `About ${sportLabel(entry.session_sport)} on ${formatShortDate(parseIsoDate(entry.session_date))}`;
  }
  return null;
}

function renderCoachFeedbackEntry(entry, replyDraft, replySubmit) {
  const submitting = replySubmit.status === 'submitting' && replySubmit.feedbackId === entry.id;
  const submitError = replySubmit.status === 'error' && replySubmit.feedbackId === entry.id
    ? `<div class="conn-result fail">${esc(replySubmit.error)}</div>` : '';
  const context = formatFeedbackContext(entry);

  return `
    <div class="panel feedback-entry">
      <div class="feedback-entry-head">
        <span class="chat-chip">${esc(FEEDBACK_TYPE_LABELS[entry.type] || entry.type)}</span>
        ${entry.needs_human_review ? '<span class="chat-chip chip-skipped">Needs review</span>' : ''}
        <span class="feedback-entry-date mono">${esc(formatFeedbackDate(entry.created_at))}</span>
      </div>
      ${context ? `<div class="feedback-entry-context mono">${esc(context)}</div>` : ''}
      <p class="feedback-entry-body">${esc(entry.body)}</p>
      ${entry.ai_provisional_answer ? `
      <div class="detail-section">
        <h4>AI provisional answer</h4>
        <p class="detail-notes">${esc(entry.ai_provisional_answer)}</p>
      </div>` : ''}
      ${entry.coach_reply ? `
      <div class="detail-section">
        <h4>Your reply</h4>
        <p class="detail-notes">${esc(entry.coach_reply)}</p>
      </div>` : `
      <label class="field">
        <span>Reply as coach</span>
        <textarea rows="3" data-form="roster-reply" data-field="body" data-id="${esc(entry.id)}" placeholder="Write a reply&hellip;">${esc(replyDraft || '')}</textarea>
      </label>
      <div class="settings-actions">
        <button type="button" class="btn" data-a="roster:reply-submit" data-id="${esc(entry.id)}" ${submitting ? 'disabled' : ''}>${submitting ? 'Sending…' : 'Send reply'}</button>
      </div>
      ${submitError}`}
    </div>`;
}

function renderCoachFeedbackSection(feedback, replyDrafts, replySubmit) {
  if (feedback.status === 'loading' && feedback.data.length === 0) {
    return '<p class="sub">Loading feedback&hellip;</p>';
  }
  if (feedback.status === 'error') {
    return `<div class="hist-error">Couldn't load feedback: ${esc(feedback.error)}</div>`;
  }
  if (feedback.data.length === 0) {
    return '<p class="sub">Nothing logged yet.</p>';
  }
  return feedback.data.map((entry) => renderCoachFeedbackEntry(entry, replyDrafts[entry.id], replySubmit)).join('');
}

function rosterShell(body) {
  return `
    <div class="wrap settings-wrap">
      <header class="mast" style="border-bottom:none;padding-bottom:0;">
        <div>
          <span class="mark">swim-coach · my athletes</span>
          <h1>My Athletes</h1>
          <p class="sub">Athletes who've granted you coach access.</p>
        </div>
      </header>
      ${body}
    </div>`;
}

// --- Roster sub-tabs (Build 2: Conversations / Workouts + Dashboard /
// Training Plan) ------------------------------------------------------------
// The coach's "acting as athlete" view used to be one flat list (workouts +
// feedback). Build 2 splits it into three sub-tabs, nested inside the
// already-a-tab roster view -- same "which one is active" string-state
// convention the app's own top-level tab bar uses (main.js's state.tab /
// this file's TABS / renderTabBar), just scoped to state.roster.subTab
// instead of state.tab, since no existing multi-SECTION (as opposed to
// multi-tab) convention in this app fits mutually-exclusive navigation (the
// allWeeksOpen/glossaryOpen booleans are independent collapsible <details>,
// not a one-of-three switch).
const ROSTER_SUB_TABS = [
  { id: 'conversations', label: 'Conversations' },
  { id: 'dashboard', label: 'Workouts + Dashboard' },
  { id: 'plan', label: 'Training Plan' },
];

function renderRosterSubTabBar(activeSubTab) {
  return `
    <nav class="subtab-bar" aria-label="Athlete view">
      ${ROSTER_SUB_TABS.map((t) => `
        <button type="button" class="subtab-btn${t.id === activeSubTab ? ' active' : ''}" data-a="roster:subtab:${t.id}" aria-current="${t.id === activeSubTab ? 'page' : 'false'}">${esc(t.label)}</button>`).join('')}
    </nav>`;
}

/** Honest, explicitly non-functional placeholder -- Andrew's own words when
 * asking for this: "save chat as a placeholder, I needed to visualize the
 * UI," not real messaging. No fetch, no state, no send action. */
function renderRosterConversationsPlaceholder() {
  return `
    <section class="hist-section">
      <div class="s-head"><h2>Conversations</h2></div>
      <p class="sub">Coach-athlete conversation -- coming soon.</p>
    </section>`;
}

/** The roster's Training Plan sub-tab: the same weeks/macro rendering logic
 * `renderApp` uses for the athlete's own Plan tab (`renderWeeksSection` +
 * `renderMacroSection`), fed by the new `GET /api/coach/athletes/<slug>/plan`
 * endpoint's data (main.js's `state.roster.plan`) instead. Deliberately NOT
 * the load chart -- that stays in the Workouts + Dashboard sub-tab via
 * `renderTrainingDashboardBody`, same "chart lives with the feed, not the
 * plan" split Build 1 already established for the athlete's own tabs.
 *
 * Session-detail drill-down IS supported (fixing the reported "can't open
 * workouts to see the detail" bug): `detailId` is main.js's
 * `state.roster.sessionDetailId` -- its own slice, separate from the
 * athlete's own `state.planSessionDetailId`/`state.sessionPush`, so a coach
 * can have their own Plan tab's session open at the same time as a coached
 * athlete's. `renderWeeksSection` handles the list<->detail branch exactly
 * as it does for the athlete's own Plan tab; the only difference is the
 * trailing `false` passed for `showGarminActions`. That suppresses just the
 * two Garmin push/download sections of `renderPlanSessionDetail` -- they act
 * on the SIGNED-IN coach's OWN athlete slug (`athleteSlug()`), not the
 * coached athlete's, and `backend/app/routes/garmin.py` has no
 * `resolve_coach_athlete` support at all, so wiring them here would either
 * silently act on the wrong athlete's data or 403/404. Everything else in
 * the detail view -- structure, targets, zone breakdown, training rationale,
 * purpose -- renders identically to what the athlete sees, per `sessionPush`
 * being irrelevant here (always `null`: there is no coach-side push action
 * to have a result). `allWeeksOpen` is deliberately the SAME app-level flag
 * the athlete's own Plan tab uses (not a separate `state.roster.allWeeksOpen`)
 * -- a shared, low-stakes accordion-open cosmetic, same "acceptable
 * tradeoff" precedent `allWeeksOpen`'s own doc comment (main.js) already
 * establishes for page-level `<details>` state.
 *
 * `askCoach` (coach-mode Q&A build): threaded straight through to
 * `renderWeeksSection`/`renderPlanSessionDetail` -- the roster's own call
 * site (`renderRosterTab`) always passes `form: null` (read-only: coach
 * replies stay in the roster's own Feedback section reply UI, not
 * duplicated here). */
function renderRosterTrainingPlanBody({
  plan, online, allWeeksOpen, detailId, askCoach,
}) {
  const status = plan?.status;
  if (status === 'error') {
    return `<div class="hist-error">Couldn't load the training plan: ${esc(plan.error)}</div>`;
  }
  if (status === 'loading' && !plan?.data) {
    return '<p class="sub">Loading plan&hellip;</p>';
  }
  if (!plan?.data) {
    const notice = !online ? 'This needs a connection -- reconnect to load it.' : 'Nothing planned yet.';
    return `<p class="sub">${esc(notice)}</p>`;
  }
  const { events, macro, weeks } = plan.data;
  const event = macroTargetEvent(macro, events);
  return `
    ${renderWeeksSection(weeks, detailId, null, allWeeksOpen, false, askCoach)}
    ${renderMacroSection(macro, event, weeks)}`;
}

export function renderRosterTab({
  athletes, actingAsAthlete, workouts, feedback, replyDrafts, replySubmit, workoutDetailId,
  backendConfigured, online, load, feedExpanded, plan, subTab, allWeeksOpen, sessionDetailId,
  // B3 (coach-mode Q&A build): count of `feedback` entries newer than this
  // device's coach "last seen" timestamp (main.js's src/unread.js) -- 0/
  // absent renders no badge at all (see renderUnreadBadge).
  feedbackUnread = 0,
  // Two-panel load chart (web/two-panel-load-chart): `loadWindowDays` is the
  // SAME app-level `state.loadWindowDays` the athlete's own Dashboard tab
  // uses (not a separate `state.roster.loadWindowDays`) -- a shared,
  // low-stakes chart-window preference, same "acceptable tradeoff"
  // precedent `allWeeksOpen` already establishes for page-level state
  // shared between the athlete's own tabs and this roster view.
  // `loadNarrativeExpanded` is the roster's OWN slice
  // (`state.roster.narrativeExpanded`), matching `feedExpanded` just above
  // it -- the coach roster and the athlete's own dashboard are two
  // independent feeds/narratives, so this one stays per-surface.
  loadWindowDays,
  loadNarrativeExpanded,
}) {
  if (!backendConfigured) {
    return rosterShell(renderBackendNeededNotice(
      'My Athletes needs you to sign in and set a backend URL and token in Settings.',
    ));
  }

  if (actingAsAthlete) {
    const match = (athletes.data || []).find((a) => a.slug === actingAsAthlete);
    const name = match?.name || actingAsAthlete;

    // Full completed+missed parity (Build 2, upgraded from Build 1's
    // deliberately completed-only scope): the new coach-plan endpoint means
    // `plan?.data?.weeks` now exists to derive skips from, same
    // `buildHistoryFeed` the athlete's own dashboard uses (main.js's
    // history.js import) -- before that endpoint existed there was nothing
    // to derive a skip from on the coach side at all. `renderCoachWorkoutRow`
    // (planned-vs-actual quality line, no embedded chat) still stands in for
    // the athlete-side completed-row treatment.
    const feed = buildHistoryFeed({
      weeks: plan?.data?.weeks || [],
      workouts: workouts.data || [],
      now: new Date(),
    });
    // Coach-mode Q&A build: read-only (`form: null`) -- coach replies stay
    // centralized in `renderCoachFeedbackSection`'s own reply UI below, not
    // duplicated inside the shared Ask-the-coach component. Shared verbatim
    // between the workout-detail view (via `renderTrainingDashboardBody`)
    // and the Training Plan sub-tab's session-detail view (via
    // `renderRosterTrainingPlanBody`) below -- both filter this same raw
    // list down to their own one workout/session.
    const askCoach = { feedback: feedback.data, form: null };

    const dashboardBody = renderTrainingDashboardBody({
      load,
      feed,
      status: workouts.status,
      error: workouts.error,
      online,
      detailId: workoutDetailId,
      workoutChat: null,
      actions: null,
      feedExpanded,
      renderCompletedRow: renderCoachWorkoutRow,
      backAction: 'roster:close-workout',
      chat: false,
      emptyMessage: 'Nothing logged or missed yet.',
      askCoach,
      loadWindowDays,
      loadNarrativeExpanded,
      // showWellnessInline left at its `true` default -- see
      // renderTrainingDashboardBody's own doc comment.
    });

    // Read-only workout detail (no embedded chat -- that's an athlete-only
    // AI feature). When workoutDetailId matches a loaded workout,
    // `dashboardBody` above is ALREADY just the back button + detail (see
    // renderTrainingDashboardBody's own detailId branch) -- rendered alone,
    // with none of the "Coaching <name>"/Back-to-My-Athletes/sub-tab bar
    // chrome below, same "focused detail view" convention the original
    // History tab used, regardless of which sub-tab was active when it was
    // opened (a workout row only ever renders from the Workouts + Dashboard
    // sub-tab, so this is unambiguous). Falls through to the normal sub-tab
    // view if the id no longer matches anything already loaded (e.g. a stale
    // id after a refresh), same "just show the list" fallback as before.
    const detailWorkout = workoutDetailId
      ? feed.find((i) => i.kind === 'completed' && i.workout.id === workoutDetailId)
      : null;
    if (detailWorkout) {
      return rosterShell(dashboardBody);
    }

    const activeSubTab = subTab || 'dashboard';
    const subTabBody = (() => {
      if (activeSubTab === 'conversations') return renderRosterConversationsPlaceholder();
      if (activeSubTab === 'plan') return renderRosterTrainingPlanBody({
        plan, online, allWeeksOpen, detailId: sessionDetailId, askCoach,
      });
      return `
        ${!online ? '<div class="chat-banner">Offline -- some data may be out of date.</div>' : ''}
        ${dashboardBody}
        <section class="hist-section">
          <div class="s-head"><h2>Feedback${renderUnreadBadge(feedbackUnread)}</h2></div>
          ${renderCoachFeedbackSection(feedback, replyDrafts, replySubmit)}
        </section>`;
    })();

    return rosterShell(`
      <div class="s-head"><button type="button" class="btn-ghost" data-a="roster:back">&larr; Back to My Athletes</button></div>
      <p class="sub">Coaching <b>${esc(name)}</b> (${esc(actingAsAthlete)}).</p>
      ${renderRosterSubTabBar(activeSubTab)}
      ${subTabBody}`);
  }

  return rosterShell(`
    ${!online ? '<div class="chat-banner">Offline -- your athlete list may be out of date.</div>' : ''}
    <section class="hist-section">
      ${renderCoachedAthletesList(athletes)}
    </section>`);
}

// --- Onboarding form (Slice 3 of self-service in-app onboarding) -----------
// Full-screen, rendered instead of the tab bar + tab content entirely (see
// main.js's render()) while state.onboarding.active is true -- there's
// nothing else useful to navigate to yet (no athlete, no plan, no profile).
// Reuses the exact panel/field/pool-days markup and CSS classes the
// Settings tab's profile-edit form and the Log/Check-in tabs already use, so
// this looks and behaves like the rest of the app rather than a bespoke
// wizard screen. Every field maps 1:1 to backend/app/routes/onboard.py's
// OnboardRequest via src/onboarding.js's onboardPayloadFromForm -- see that
// module's doc comment for the exact mapping and which fields are optional.

const CSS_MODE_OPTIONS = [
  { value: 'pace', label: 'I know my CSS pace' },
  { value: 'test', label: 'Time me (400m + 200m test)' },
];

const EVENT_FORMAT_OPTIONS = [
  { value: 'single_day', label: 'Single day' },
  { value: 'multi_day_stage', label: 'Multi-day / staged' },
];

function panelHeading(text) {
  return `<h3 style="margin:0 0 12px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);">${esc(text)}</h3>`;
}

export function renderOnboardingForm({ form, submitting, error }) {
  const cssModeIsTest = form.cssMode === 'test';

  return `
    <div class="wrap settings-wrap">
      <header class="mast" style="border-bottom:none;padding-bottom:0;">
        <div>
          <span class="mark">swim-coach · welcome</span>
          <h1>Let's set up your plan</h1>
          <p class="sub">A few hard-data questions, then your coach builds your first week.</p>
        </div>
      </header>

      <div class="panel settings-panel">
        ${panelHeading('About you')}
        <label class="field">
          <span>Name</span>
          <input type="text" required data-form="onboard" data-field="name" value="${esc(form.name)}">
        </label>
        <label class="field">
          <span>Date of birth (optional)</span>
          <input type="date" data-form="onboard" data-field="dob" value="${esc(form.dob)}">
        </label>
        <label class="field">
          <span>Sex (optional)</span>
          <select data-form="onboard" data-field="sex">
            ${SEX_OPTIONS.map((opt) => `<option value="${opt.value}"${form.sex === opt.value ? ' selected' : ''}>${esc(opt.label)}</option>`).join('')}
          </select>
        </label>
        <label class="field">
          <span>Height (optional)</span>
          <div style="display:flex;gap:8px;">
            <input type="number" min="0" step="1" inputmode="numeric" placeholder="ft" style="width:5em;" data-form="onboard" data-field="heightFeet" value="${esc(form.heightFeet)}">
            <input type="number" min="0" max="11" step="1" inputmode="numeric" placeholder="in" style="width:5em;" data-form="onboard" data-field="heightInches" value="${esc(form.heightInches)}">
          </div>
        </label>
        <label class="field">
          <span>Weight in lb (optional)</span>
          <input type="number" min="0" step="0.1" inputmode="decimal" data-form="onboard" data-field="weightLb" value="${esc(form.weightLb)}">
        </label>
      </div>

      <div class="panel settings-panel">
        ${panelHeading('Your swim fitness')}
        <label class="field">
          <span>How should we get your CSS pace?</span>
          <select data-form="onboard" data-field="cssMode">
            ${CSS_MODE_OPTIONS.map((opt) => `<option value="${opt.value}"${form.cssMode === opt.value ? ' selected' : ''}>${esc(opt.label)}</option>`).join('')}
          </select>
        </label>
        ${cssModeIsTest ? `
        <label class="field">
          <span>400m time trial (mm:ss)</span>
          <input type="text" placeholder="7:20" required data-form="onboard" data-field="test400" value="${esc(form.test400)}">
        </label>
        <label class="field">
          <span>200m time trial (mm:ss)</span>
          <input type="text" placeholder="3:20" required data-form="onboard" data-field="test200" value="${esc(form.test200)}">
        </label>` : `
        <label class="field">
          <span>CSS pace (per 100m, mm:ss)</span>
          <input type="text" placeholder="1:40" required data-form="onboard" data-field="cssPace" value="${esc(form.cssPace)}">
        </label>`}
      </div>

      <div class="panel settings-panel">
        ${panelHeading('Pool schedule')}
        <label class="field">
          <span>Which days do you swim with your pool coach? (optional)</span>
          <div class="pool-days">
            ${POOL_DAY_LABELS.map((day) => `
              <label class="pool-day">
                <input type="checkbox" data-form="onboard" data-field="pool_days" data-day="${day.value}" ${form.poolDays?.[day.value] ? 'checked' : ''}>
                <span>${day.label}</span>
              </label>`).join('')}
          </div>
        </label>
      </div>

      <div class="panel settings-panel">
        ${panelHeading('Target event')}
        <label class="field">
          <span>Event name</span>
          <input type="text" required data-form="onboard" data-field="eventName" value="${esc(form.eventName)}">
        </label>
        <label class="field">
          <span>Event date</span>
          <input type="date" required data-form="onboard" data-field="eventDate" value="${esc(form.eventDate)}">
        </label>
        <label class="field">
          <span>Distance (m)</span>
          <input type="number" min="1" step="1" inputmode="numeric" required data-form="onboard" data-field="eventDistanceM" value="${esc(form.eventDistanceM)}">
        </label>
        <label class="field">
          <span>Format</span>
          <select data-form="onboard" data-field="eventFormat">
            ${EVENT_FORMAT_OPTIONS.map((opt) => `<option value="${opt.value}"${form.eventFormat === opt.value ? ' selected' : ''}>${esc(opt.label)}</option>`).join('')}
          </select>
        </label>
      </div>

      <div class="panel settings-panel">
        ${panelHeading('Training volume')}
        <label class="field">
          <span>Current weekly volume, meters (optional)</span>
          <input type="number" min="0" step="100" inputmode="numeric" data-form="onboard" data-field="currentVolumeM" value="${esc(form.currentVolumeM)}">
        </label>
        <label class="field">
          <span>Peak weekly volume target, meters (optional)</span>
          <input type="number" min="0" step="100" inputmode="numeric" data-form="onboard" data-field="peakVolumeM" value="${esc(form.peakVolumeM)}">
        </label>
        <label class="field">
          <span>Plan start date (optional)</span>
          <input type="date" data-form="onboard" data-field="macroStart" value="${esc(form.macroStart)}">
        </label>
      </div>

      <div class="panel settings-panel">
        <details>
          <summary style="cursor:pointer;font-size:13px;font-weight:600;">Advanced</summary>
          <label class="field" style="margin-top:12px;">
            <span>Custom URL slug (optional)</span>
            <input type="text" data-form="onboard" data-field="slug" value="${esc(form.slug)}">
          </label>
        </details>
      </div>

      <div class="panel settings-panel">
        ${error ? `<div class="conn-result fail">${esc(error)}</div>` : ''}
        <div class="settings-actions">
          <button type="button" class="btn" data-a="onboard:submit" ${submitting ? 'disabled' : ''}>${submitting ? 'Setting up…' : 'Create my plan'}</button>
        </div>
        <div class="settings-actions" style="margin-top:8px;">
          <button type="button" class="btn-ghost" data-a="identity:signout">Not you? Sign out</button>
        </div>
      </div>
    </div>`;
}

// --- Settings tab ------------------------------------------------------------

// --- Coach access panel (Settings tab: "who can coach me") -----------------
// Athlete-self-access grants (POST/GET/PATCH /api/grants -- see
// backend/app/routes/grants.py), NOT the coach-side roster above.

function formatGrantDate(isoString) {
  if (!isoString) return null;
  const d = new Date(isoString);
  return Number.isNaN(d.getTime()) ? isoString : d.toLocaleDateString();
}

/** The `CoachGrant` response (engine/swim_coach/models.py) carries
 * `coach_athlete_id` -- a UUID foreign key -- not the coach's slug; this
 * route has no slug-resolving join today. Shown as a short id prefix
 * rather than a name until a future backend slice enriches the response --
 * still enough to tell rows apart and to revoke the right one. */
function renderGrantRow(grant) {
  const shortId = String(grant.coach_athlete_id || '').slice(0, 8);
  const granted = formatGrantDate(grant.granted_at);
  const revoked = grant.status === 'revoked';
  return `
    <div class="hist-row hist-row-skipped">
      <div class="hist-body">
        <div class="hist-title">
          <span>Coach ${esc(shortId)}</span>
          <span class="chat-chip${revoked ? ' chip-skipped' : ''}">${esc(grant.status)}</span>
        </div>
        ${granted ? `<div class="hist-meta mono">Granted ${esc(granted)}</div>` : ''}
      </div>
      ${!revoked ? `<button type="button" class="btn-ghost" data-a="grants:revoke" data-id="${esc(grant.id)}">Revoke</button>` : ''}
    </div>`;
}

function renderGrantsList(entries) {
  if (!entries || entries.length === 0) {
    return "<p class=\"sub\">You haven't granted anyone coach access yet.</p>";
  }
  return `<div class="hist-list">${entries.map(renderGrantRow).join('')}</div>`;
}

function renderGrantsPanel({ grants, form, submit }) {
  return `
    <div class="panel settings-panel">
      <h3 style="margin:0 0 12px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);">Coach access</h3>
      ${grants.status === 'loading' && grants.data.length === 0 ? '<p class="sub">Loading&hellip;</p>' : renderGrantsList(grants.data)}
      ${grants.status === 'error' ? `<div class="conn-result fail">Couldn't load your grants: ${esc(grants.error)}</div>` : ''}
      <label class="field" style="margin-top:14px;">
        <span>Grant a coach access (their athlete slug)</span>
        <input type="text" data-form="grants" data-field="coachSlug" placeholder="e.g. tim" value="${esc(form.coachSlug)}">
      </label>
      <div class="settings-actions">
        <button type="button" class="btn" data-a="grants:submit" ${submit.status === 'submitting' ? 'disabled' : ''}>${submit.status === 'submitting' ? 'Granting…' : 'Grant access'}</button>
      </div>
      ${submit.status === 'error' ? `<div class="conn-result fail">${esc(submit.error)}</div>` : ''}
    </div>`;
}

export function renderSettingsTab({
  identity, identityError, backendConfigured, profileForm, profileLoad, profileSubmit,
  grants, grantsForm, grantsSubmit,
}) {
  return `
    <div class="wrap settings-wrap">
      <header class="mast" style="border-bottom:none;padding-bottom:0;">
        <div>
          <span class="mark">swim-coach · settings</span>
          <h1>Settings</h1>
          <p class="sub">Sign in with your Google account to load your plan.</p>
        </div>
      </header>
      <div class="panel settings-panel">
        <h3 style="margin:0 0 12px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);">Sign in</h3>
        ${identity ? `
        <p class="field-hint" style="margin:0 0 14px;">Signed in as <b>${esc(identity.name || identity.athlete)}</b> &rarr; athlete <b>${esc(identity.athlete)}</b> (role <b>${esc(identity.role)}</b>).</p>
        <div class="settings-actions">
          <button type="button" class="btn-ghost" data-a="identity:signout">Sign out</button>
        </div>` : `
        <p class="field-hint" style="margin:0 0 14px;">Sign in with Google to load your own plan. The backend verifies your Google account and mints a session for it -- there's no token to paste.</p>
        <div id="google-signin-btn"></div>
        ${identityError ? `<div class="conn-result fail">${esc(identityError)}</div>` : ''}`}
      </div>
      ${backendConfigured ? renderGrantsPanel({ grants, form: grantsForm, submit: grantsSubmit }) : ''}
      ${backendConfigured ? renderProfilePanel({ form: profileForm, load: profileLoad, submit: profileSubmit }) : ''}
    </div>`;
}

// --- PWA update prompt -------------------------------------------------------
// Renders from state.pwaUpdate (see src/pwaUpdate.js's pure reducers/
// predicates, which main.js's thin `virtual:pwa-register` wiring feeds) --
// prepended to every render() regardless of the active tab, same convention
// as the always-present #offline-banner in index.html, except this one goes
// through the normal state->render pipeline (so it's unit-testable here)
// instead of a static DOM node toggled by class.

export function renderUpdateBanner({ needRefresh, needRefreshDismissed, offlineReady, offlineReadyDismissed } = {}) {
  const showReload = !!needRefresh && !needRefreshDismissed;
  if (showReload) {
    return `
      <div class="update-banner" role="status">
        <span>New version available.</span>
        <div class="update-banner-actions">
          <button type="button" class="btn" data-a="pwa:reload">Reload</button>
          <button type="button" class="update-banner-dismiss" data-a="pwa:dismiss-update" aria-label="Dismiss">&times;</button>
        </div>
      </div>`;
  }
  const showOfflineReady = !!offlineReady && !offlineReadyDismissed;
  if (showOfflineReady) {
    return `
      <div class="update-banner update-banner-subtle" role="status">
        <span>Ready to work offline.</span>
        <button type="button" class="update-banner-dismiss" data-a="pwa:dismiss-offline-ready" aria-label="Dismiss">&times;</button>
      </div>`;
  }
  return '';
}
