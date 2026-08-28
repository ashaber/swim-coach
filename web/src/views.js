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
} from './plan.js';
import { TOOL_LABELS } from './chat.js';
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
 * something sensible to show even when this whole block is empty. */
function renderPlanSessionDetail(session, sessionPush) {
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
    ${session.structured ? renderGarminDownload(session) : ''}
    ${session.structured ? renderGarminPush(session, sessionPush) : ''}
    ${purpose ? `
    <section class="detail-section">
      <h4>Purpose</h4>
      <p class="detail-notes">${esc(purpose)}</p>
    </section>` : ''}`;
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

/** `detailId` is main.js's state.planSessionDetailId -- null shows the
 * ordinary "This week"/"Next week" cards, a session id swaps the whole
 * section to a back button + renderPlanSessionDetail(...) instead, same
 * convention as renderTrainingDashboardBody's `detailId` handling for
 * workouts. */
function renderWeeksSection(weeks, detailId, sessionPush, allWeeksOpen) {
  if (detailId) {
    const session = findSessionById(weeks, detailId);
    if (session) {
      return `
    <section>
      <div class="s-head"><button type="button" class="btn-ghost" data-a="session:back">&larr; Back to plan</button></div>
      ${renderPlanSessionDetail(session, sessionPush)}
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
  const totalWeeks = macro.blocks.reduce(
    (sum, b) => sum + Math.max(1, Math.round((parseIsoDate(b.end_date) - parseIsoDate(b.start_date)) / 86400000 / 7) + 1),
    0,
  );

  const blockEls = macro.blocks.map((block, i) => {
    const weeksInBlock = Math.round((parseIsoDate(block.end_date) - parseIsoDate(block.start_date)) / 86400000 / 7) + 1;
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

const LOAD_CHART_LINE_COLOR_VAR = { ctl: '--accent', atl: '--c-strength', tsb: '--c-ow' };

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

/** Dual y-axis rendering (readability fix -- see `ctlAtlTsbChartGeometry`'s
 * doc comment in plan.js for why): the left axis (grey, gridlined) is
 * CTL/TSB's shared "primary" scale; the right axis (no gridlines of its
 * own -- a second full gridline grid would clutter the plot for one line)
 * is ATL's independent "secondary" scale, its tick labels colored to match
 * ATL's own line color so the two axes read as visually paired with the
 * line each belongs to, exactly like the legend below the chart already
 * pairs a color with a name. */
function renderLoadChartSvg(geo) {
  const yTickLines = geo.yTicks.map((t) => `
      <line x1="${geo.plotLeft}" y1="${t.y.toFixed(1)}" x2="${geo.plotRight}" y2="${t.y.toFixed(1)}" class="load-chart-gridline" />
      <text x="${geo.plotLeft - 6}" y="${t.y.toFixed(1)}" class="load-chart-axis-label" text-anchor="end" dominant-baseline="middle">${esc(t.value)}</text>`).join('');

  const yTickLabelsSecondary = geo.yTicksSecondary.map((t) => `
      <text x="${geo.plotRight + 6}" y="${t.y.toFixed(1)}" class="load-chart-axis-label load-chart-axis-label-secondary" text-anchor="start" dominant-baseline="middle" style="fill:var(${LOAD_CHART_LINE_COLOR_VAR.atl})">${esc(t.value)}</text>`).join('');

  const xTickLabels = geo.xTicks.map((t) => `
      <text x="${t.x.toFixed(1)}" y="${geo.plotBottom + 18}" class="load-chart-axis-label" text-anchor="middle">${esc(formatShortDate(parseIsoDate(t.label)))}</text>`).join('');

  return `
    <svg class="load-chart-svg" viewBox="0 0 ${geo.width} ${geo.height}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Training load chart: CTL and TSB on the left axis, ATL on its own independent right axis">
      <rect class="load-chart-band" x="${geo.plotLeft}" y="${geo.bandTop.toFixed(1)}" width="${geo.plotRight - geo.plotLeft}" height="${Math.max(0, geo.bandBottom - geo.bandTop).toFixed(1)}" />
      ${yTickLines}
      ${yTickLabelsSecondary}
      ${xTickLabels}
      <polyline class="load-chart-line load-chart-line-ctl" points="${loadChartPointsAttr(geo.ctlPoints)}" style="stroke:var(${LOAD_CHART_LINE_COLOR_VAR.ctl})" />
      <polyline class="load-chart-line load-chart-line-atl" points="${loadChartPointsAttr(geo.atlPoints)}" style="stroke:var(${LOAD_CHART_LINE_COLOR_VAR.atl})" />
      <polyline class="load-chart-line load-chart-line-tsb" points="${loadChartPointsAttr(geo.tsbPoints)}" style="stroke:var(${LOAD_CHART_LINE_COLOR_VAR.tsb})" />
    </svg>`;
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

/** Renders `describeCtlAtlTsbTrend`'s structured summary as the athlete-
 * facing "what the numbers say" prose -- the "useful coach guidance below
 * the load graph" this whole feature is for (an athlete's spouse's own
 * description of a hand-written narrative interpretation of this same
 * chart, judged more useful day-to-day than the generic methodology
 * caption that used to sit directly under it -- see `renderLoadChart`'s
 * own comment for where that caption moved). Ordered warmup caveat first
 * (an honest heads-up belongs before the numbers it qualifies, not buried
 * after them), then CTL direction, then the biggest ATL swing, then
 * current TSB. Returns `''` when `!trend.hasData` -- same empty-series
 * case `ctlAtlTsbChartGeometry` already renders its own "not enough data
 * yet" message for, so this narrative doesn't duplicate that. */
function renderCtlAtlTsbNarrative(series) {
  const trend = describeCtlAtlTsbTrend(series);
  if (!trend.hasData) return '';

  const lines = [];

  if (trend.warmup === 'cold-start') {
    lines.push(`Only ${trend.historyDays} day${trend.historyDays === 1 ? '' : 's'} of logged history so far -- CTL and ATL are still climbing up from zero and don't yet reflect real fitness/fatigue levels. Read everything below as provisional until more history accumulates.`);
  } else if (trend.warmup === 'warming-up') {
    lines.push(`This series has ${trend.historyDays} days of history -- past the point where CTL/ATL are pure zero-artifacts, but not yet "fully warmed up" by this model's own standard. Read the trend below as directionally useful, not yet a fully mature fitness estimate.`);
  }

  if (trend.ctlTrend) {
    if (trend.ctlTrend.status === 'insufficient-window') {
      lines.push(`Not enough history yet (${trend.ctlTrend.historyDays} day${trend.ctlTrend.historyDays === 1 ? '' : 's'}) to compare CTL over a ${trend.ctlTrend.requiredWindowDays}-day window.`);
    } else {
      const { status, fromDate, toDate, fromValue, toValue } = trend.ctlTrend;
      const verb = { rising: 'climbed', falling: 'dropped', flat: 'held roughly flat' }[status];
      lines.push(`CTL (fitness) has ${verb}${status === 'flat' ? '' : ' steadily'} from ${formatTrendDate(fromDate)} to ${formatTrendDate(toDate)}: ${formatTrendValue(fromValue)} → ${formatTrendValue(toValue)}.`);
    }
  }

  if (trend.atlSpike && trend.atlSpike.direction !== 'flat') {
    const { fromDate, toDate, fromValue, toValue, direction } = trend.atlSpike;
    const verb = direction === 'up' ? 'jumped' : 'dropped';
    lines.push(`ATL (fatigue) ${verb} from ${formatTrendValue(fromValue)} to ${formatTrendValue(toValue)} across ${formatTrendDate(fromDate)}–${formatTrendDate(toDate)} -- the biggest recent swing, most likely tracking a big training day or block.`);
  }

  if (trend.tsb) {
    const { value, band, date } = trend.tsb;
    const bandPhrase = band === 'within'
      ? `inside the +${RACE_DAY_TSB_BAND.low} to +${RACE_DAY_TSB_BAND.high} race-day reference band`
      : band === 'below'
        ? `below the +${RACE_DAY_TSB_BAND.low} to +${RACE_DAY_TSB_BAND.high} race-day reference band -- expected and fine while deep in training, not a warning sign; that band only means something close to race day`
        : `above the +${RACE_DAY_TSB_BAND.low} to +${RACE_DAY_TSB_BAND.high} race-day reference band`;
    lines.push(`TSB (form) is currently ${formatTrendValue(value)} as of ${formatTrendDate(date)} -- ${bandPhrase}.`);
  }

  if (lines.length === 0) return '';
  return `
    <div class="load-chart-narrative">
      <h4>What the numbers say</h4>
      ${lines.map((line) => `<p>${esc(line)}</p>`).join('')}
    </div>`;
}

/**
 * Renders the CTL ("fitness") / ATL ("fatigue") / TSB ("form") Banister
 * training-load chart -- shared verbatim by `renderTrainingDashboardBody`
 * on both the athlete's own Dashboard tab and the coach roster's
 * acting-as-athlete view; only the `load` state differs between the two
 * call sites.
 *
 * `load` follows this app's usual async-state shape (`{status, data, error}`
 * -- same convention as `state.plan`/`state.roster.workouts`), where
 * `data.ctl_atl_tsb` is the `[dateIso, ctl, atl, tsb]` series from
 * `GET /api/plan/load` / `GET /api/coach/athletes/{slug}/load`.
 *
 * CTL/TSB share one (left) y-axis -- the standard cycling-coaching
 * "Performance Management Chart" layout (see plan.js's module comment for
 * why TSB is never shown alone) -- plus a shaded reference band for the
 * commonly-cited cycling-coaching "race-day TSB" range. ATL plots against
 * its OWN independent (right) y-axis -- a dual-axis readability fix (Build
 * 1): a 42-day EWMA (CTL) has an inherently much smaller natural range than
 * a 7-day EWMA (ATL) on any real athlete's data, so sharing one axis made
 * CTL look flat/negligible next to ATL's swings, even though nothing about
 * the underlying numbers was wrong (verified -- see
 * `ctlAtlTsbChartGeometry`'s own doc comment in plan.js).
 *
 * Directly below the chart sits `renderCtlAtlTsbNarrative`'s athlete-
 * specific "what the numbers say" prose (plan.js's `describeCtlAtlTsbTrend`)
 * -- the computed, day-to-day-useful trend interpretation this whole
 * feature is for. The generic methodology paragraph that used to sit here
 * unconditionally -- explaining the race-day band AND the underlying
 * CTL/ATL time constants are cycling-derived and not yet swim-specific or
 * peer-reviewed (see `engine/swim_coach/load.py`'s
 * `CTL_TIME_CONSTANT_DAYS`/`ATL_TIME_CONSTANT_DAYS` module comment for the
 * same caveat at its source) -- now lives inside a collapsed-by-default
 * `<details>` ("How this chart works"): still one click away, per this
 * project's evidence-discipline convention that these caveats are
 * load-bearing honesty and must stay reachable, just no longer competing
 * for attention with the athlete-specific insight that actually matters
 * day to day. This chart must never read as more authoritative than that
 * series actually is, on either side of the toggle.
 */
export function renderLoadChart(load) {
  if (!load || load.status === 'idle') return '';
  if (load.status === 'loading' && !load.data) {
    return '<div class="panel load-chart-panel"><h3>Training load</h3><p class="sub">Loading training load&hellip;</p></div>';
  }
  if (load.status === 'error') {
    return `<div class="panel load-chart-panel"><h3>Training load</h3><div class="hist-error">Couldn't load training load: ${esc(load.error)}</div></div>`;
  }
  if (!load.data) return '';

  const series = load.data.ctl_atl_tsb || [];
  const geo = ctlAtlTsbChartGeometry(series);

  const body = geo.isEmpty
    ? '<p class="sub">Not enough logged training yet to show a fitness/fatigue trend.</p>'
    : `
      ${renderLoadChartSvg(geo)}
      <div class="legend load-chart-legend">
        <span class="li"><span class="dot" style="background:var(${LOAD_CHART_LINE_COLOR_VAR.ctl})"></span>CTL (fitness) · left axis</span>
        <span class="li"><span class="dot" style="background:var(${LOAD_CHART_LINE_COLOR_VAR.atl})"></span>ATL (fatigue) · right axis</span>
        <span class="li"><span class="dot" style="background:var(${LOAD_CHART_LINE_COLOR_VAR.tsb})"></span>TSB (form) · left axis</span>
        <span class="li"><span class="dot load-chart-band-dot"></span>Race-day TSB reference band</span>
      </div>`;

  const narrative = geo.isEmpty ? '' : renderCtlAtlTsbNarrative(series);

  return `
    <div class="panel load-chart-panel">
      <h3>Training load (CTL / ATL / TSB)</h3>
      ${body}
      ${narrative}
      <details class="load-chart-methodology">
        <summary>How this chart works</summary>
        <p class="load-chart-note">CTL ("fitness") and ATL ("fatigue") are 42-day/7-day exponentially weighted averages of daily training load; TSB ("form") is CTL minus ATL. These time constants are the standard cycling/TrainingPeaks convention, carried over as a starting point -- not yet verified for swimming specifically. The shaded band (+5 to +25 TSB) is a commonly-targeted range in cycling coaching practice on race day, not a swim-specific or peer-reviewed target -- individual variation is large, so your own best-performance history is a better guide than this generic band. CTL and TSB share the left axis; ATL plots against its own right axis -- a 42-day average has an inherently much smaller natural range than a 7-day one, so sharing one scale made CTL look flat next to ATL's swings even though nothing about the underlying numbers was wrong.</p>
      </details>
      ${renderWellnessBaselineDeviation(load.data.wellness_baseline_deviation)}
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
  const { athlete, events, macro, weeks, sessionPush, allWeeksOpen, glossaryOpen } = data;
  const event = macroTargetEvent(macro, events);

  return `
    <div class="wrap">
      ${renderMasthead(athlete, event)}
      ${renderWeeksSection(weeks, planSessionDetailId, sessionPush, allWeeksOpen)}
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

/**
 * `activeTab` is unchanged. Second arg is an options bag: `{ hideRoster }`
 * -- when true, the 'roster' tab (coach mode Phase 1's "My Athletes") is
 * left out of the bar entirely, since an identity with no coach grants has
 * nothing to see there (see main.js's render(), which passes `hideRoster:
 * !state.coachFor.length`). Chosen over a general allowlist-of-visible-ids
 * because 'roster' is the only tab that's ever conditionally hidden today --
 * a single named flag says exactly that, rather than every call site having
 * to enumerate all 8 tab ids just to hide one. Omitting the second arg
 * entirely (every existing call site outside main.js's real render(), e.g.
 * tests) keeps the old "every tab always shows" behavior, `hideRoster`
 * defaulting to falsy.
 */
export function renderTabBar(activeTab, { hideRoster = false } = {}) {
  const tabs = hideRoster ? TABS.filter((tab) => tab.id !== 'roster') : TABS;
  return `
    <nav class="tabbar" aria-label="Main">
      ${tabs.map((tab) => `
        <button type="button" class="tab-btn${tab.id === activeTab ? ' active' : ''}" data-a="tab:${tab.id}" aria-current="${tab.id === activeTab ? 'page' : 'false'}">
          <span class="tab-icon" aria-hidden="true">${tab.icon}</span>
          <span class="tab-label">${esc(tab.label)}</span>
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
        <input type="range" min="1" max="10" step="1" data-form="log" data-field="rpe" data-slider-out="log-rpe-out"${rpeMissing ? '' : ` value="${esc(form.rpe)}"`}>
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

function renderWorkoutRow(workout) {
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
          ${workout.rpe !== null && workout.rpe !== undefined ? `<span class="chat-chip">RPE ${esc(workout.rpe)}</span>` : ''}
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
 * planned-vs-actual quality line) while sharing this one mapping. */
function renderFeedRow(item, renderCompletedRow) {
  return item.kind === 'completed' ? renderCompletedRow(item.workout) : renderSkippedRow(item.session);
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
  emptyMessage = 'Nothing logged or missed yet. Once you log a session (or miss a planned one), it shows up here.',
}) {
  const items = feed || [];
  const hasData = items.length > 0;

  if (hasData && detailId) {
    const match = items.find((i) => i.kind === 'completed' && i.workout.id === detailId);
    if (match) {
      return `
        <section class="hist-section">
          <div class="s-head"><button type="button" class="btn-ghost" data-a="${backAction}">&larr; Back</button></div>
          ${renderWorkoutDetail(match.workout, { chat: chat ? workoutChat : null, online })}
        </section>`;
    }
  }

  const capped = feedExpanded ? items : items.slice(0, HISTORY_DISPLAY_CAP);
  const remaining = items.length - capped.length;

  const feedBody = (() => {
    if (status === 'error') {
      return `
        ${hasData ? `<div class="hist-list">${capped.map((item) => renderFeedRow(item, renderCompletedRow)).join('')}</div>` : ''}
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
      <div class="hist-list">${capped.map((item) => renderFeedRow(item, renderCompletedRow)).join('')}</div>
      ${remaining > 0 ? `
      <div class="settings-actions">
        <button type="button" class="btn-ghost" data-a="dashboard:show-more">Show ${remaining} more</button>
      </div>` : ''}`;
  })();

  return `
    ${renderLoadChart(load)}
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
  form, submit, ingest, sync, manualOpen, feedExpanded,
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
      load, feed, status, error, online, detailId, workoutChat, actions, feedExpanded,
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
  ].join('');
  return `<div class="detail-stats">${stats}</div>`;
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

function renderWorkoutDetail(workout, { chat, online } = {}) {
  const badge = sourceBadge(workout.source);
  return `
    <div class="detail-header">
      <h3>${esc(sportLabel(workout.sport, workout.sport_detail))}</h3>
      <div class="hist-meta mono">${esc(formatLongDate(parseIsoDate(workout.date.slice(0, 10))))}${badge ? ` <span class="chat-chip">${esc(badge)}</span>` : ''}</div>
    </div>
    ${renderDetailStats(workout)}
    ${renderDetailAnalytics(workout.analytics)}
    ${renderLapsTable(workout.laps)}
    ${renderPausesList(workout.pauses)}
    ${renderLengthsSummarySection(workout.lengths)}
    ${renderDetailNotes(workout.notes)}
    ${renderWorkoutChatSection({ workout, chat, online })}`;
}

// --- Check-in tab (daily wellness) ---------------------------------------------

export function renderCheckinTab({ form, submit, backendConfigured, online }) {
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
        <span>Pool days</span>
        <div class="pool-days">
          ${POOL_DAY_LABELS.map((day) => `
            <label class="pool-day">
              <input type="checkbox" data-form="profile" data-field="pool_days" data-day="${day.value}" ${form.poolDays?.[day.value] ? 'checked' : ''}>
              <span>${day.label}</span>
            </label>`).join('')}
        </div>
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

function renderFeedbackEntry(entry) {
  return `
    <div class="panel feedback-entry">
      <div class="feedback-entry-head">
        <span class="chat-chip">${esc(FEEDBACK_TYPE_LABELS[entry.type] || entry.type)}</span>
        ${entry.source === 'coach' ? '<span class="chat-chip">coach-logged</span>' : ''}
        <span class="feedback-entry-date mono">${esc(formatFeedbackDate(entry.created_at))}</span>
      </div>
      <p class="feedback-entry-body">${esc(entry.body)}</p>
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

function renderCoachWorkoutRow(workout) {
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
          ${workout.rpe !== null && workout.rpe !== undefined ? `<span class="chat-chip">RPE ${esc(workout.rpe)}</span>` : ''}
        </div>
        <div class="hist-meta mono">${metaParts.join(' · ')}</div>
        ${qualityLine ? `<div class="hist-analytics mono">${esc(qualityLine)}</div>` : ''}
        ${qualitySummary ? `<div class="hist-analytics">${esc(qualitySummary)}</div>` : ''}
      </div>
    </button>`;
}

function renderCoachFeedbackEntry(entry, replyDraft, replySubmit) {
  const submitting = replySubmit.status === 'submitting' && replySubmit.feedbackId === entry.id;
  const submitError = replySubmit.status === 'error' && replySubmit.feedbackId === entry.id
    ? `<div class="conn-result fail">${esc(replySubmit.error)}</div>` : '';

  return `
    <div class="panel feedback-entry">
      <div class="feedback-entry-head">
        <span class="chat-chip">${esc(FEEDBACK_TYPE_LABELS[entry.type] || entry.type)}</span>
        ${entry.needs_human_review ? '<span class="chat-chip chip-skipped">Needs review</span>' : ''}
        <span class="feedback-entry-date mono">${esc(formatFeedbackDate(entry.created_at))}</span>
      </div>
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

export function renderRosterTab({
  athletes, actingAsAthlete, workouts, feedback, replyDrafts, replySubmit, workoutDetailId,
  backendConfigured, online, load, feedExpanded,
}) {
  if (!backendConfigured) {
    return rosterShell(renderBackendNeededNotice(
      'My Athletes needs you to sign in and set a backend URL and token in Settings.',
    ));
  }

  if (actingAsAthlete) {
    const match = (athletes.data || []).find((a) => a.slug === actingAsAthlete);
    const name = match?.name || actingAsAthlete;

    // Completed-only feed -- no plan-fetch endpoint exists yet on the coach
    // side to derive skips from (Build 2's job, not this one's -- see the
    // Build 1 plan's explicit scope decision). Same
    // `renderTrainingDashboardBody` shared component as the athlete's own
    // dashboard either way (chart -> actions (null, read-only here) ->
    // paginated feed); `renderCoachWorkoutRow` (planned-vs-actual quality
    // line, no embedded chat) stands in for the athlete-side row/detail
    // treatment.
    const feed = (workouts.data || []).map((w) => ({
      kind: 'completed', date: (w.date || '').slice(0, 10), key: `w:${w.id}`, workout: w,
    }));
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
      emptyMessage: 'Nothing logged yet.',
    });

    // Read-only workout detail (no embedded chat -- that's an athlete-only
    // AI feature). When workoutDetailId matches a loaded workout,
    // `dashboardBody` above is ALREADY just the back button + detail (see
    // renderTrainingDashboardBody's own detailId branch) -- rendered alone,
    // with none of the "Coaching <name>"/Back-to-My-Athletes/Feedback
    // chrome below, same "focused detail view" convention the original
    // History tab used. Falls through to the normal workouts/feedback view
    // if the id no longer matches anything already loaded (e.g. a stale id
    // after a refresh), same "just show the list" fallback as before.
    const detailWorkout = workoutDetailId ? feed.find((i) => i.workout.id === workoutDetailId) : null;
    if (detailWorkout) {
      return rosterShell(dashboardBody);
    }

    return rosterShell(`
      <div class="s-head"><button type="button" class="btn-ghost" data-a="roster:back">&larr; Back to My Athletes</button></div>
      <p class="sub">Coaching <b>${esc(name)}</b> (${esc(actingAsAthlete)}).</p>
      ${!online ? '<div class="chat-banner">Offline -- some data may be out of date.</div>' : ''}
      ${dashboardBody}
      <section class="hist-section">
        <div class="s-head"><h2>Feedback</h2></div>
        ${renderCoachFeedbackSection(feedback, replyDrafts, replySubmit)}
      </section>`);
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
