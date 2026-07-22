// HTML-string view templates. Pure functions of data in, markup out --
// no DOM access here (that's main.js's job).

import {
  formatShortDate, formatLongDate, formatDuration, formatDistance, formatPace,
  parseIsoDate, sessionsByDay, classifySession, sessionDisplay, sessionDotColorVar,
  pickCurrentAndNextWeek, daysUntil, priorityEvent, currentBlockIndex, longSwimLadder,
} from './plan.js';
import { TOOL_LABELS } from './chat.js';
import {
  sportLabel, sourceBadge, formatWorkoutDistance, formatAnalyticsLine,
  formatDrift, formatSplit, formatPauses, formatSwolf, formatMovingVsElapsed,
  formatOffset, formatClock, formatLengthsSummary, formatSyncResult,
  formatWorkoutChatLabel,
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

function renderMasthead(athlete, events) {
  const event = priorityEvent(events);
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
    <div class="sess${classification.highlight ? ' big' : ''}">
      <span class="dot" style="background:var(${dotVar})"></span>
      <div class="body">
        <div class="title">${esc(title)}${classification.tag ? `<span class="tag">${esc(classification.tag)}</span>` : ''}</div>
        <div class="meta mono">${metaParts.join(' · ')}</div>
        ${detail ? `<div class="desc">${esc(detail)}</div>` : ''}
      </div>
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
      <div class="days">${dayRows}</div>
    </div>`;
}

function renderWeeksSection(weeks) {
  const { current, next } = pickCurrentAndNextWeek(weeks);
  if (!current) {
    return `
    <section>
      <div class="s-head"><h2>The plan, day by day</h2></div>
      <p class="sub">No weeks planned yet.</p>
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
    </section>`;
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

export function renderApp(data) {
  const { athlete, events, macro, weeks } = data;
  const event = priorityEvent(events);

  return `
    <div class="wrap">
      ${renderMasthead(athlete, events)}
      ${renderWeeksSection(weeks)}
      ${renderMacroSection(macro, event, weeks)}
      <div class="foot">
        ${renderLegendPanel()}
        ${renderZonesPanel(athlete)}
      </div>
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
// 6 tabs now that the write endpoints (IDEA 003's Log/Checkin, and this
// build's Feedback log) have a backend; Library/Athlete still don't. Adding
// one later is just another entry in TABS plus a case in main.js's
// tab-content switch -- nothing here needs to change.
const TABS = [
  { id: 'plan', label: 'Plan', icon: '📋' },
  { id: 'log', label: 'Log', icon: '📝' },
  { id: 'checkin', label: 'Check-in', icon: '🌙' },
  { id: 'coach', label: 'Coach', icon: '💬' },
  { id: 'feedback', label: 'Feedback', icon: '💡' },
  { id: 'settings', label: 'Settings', icon: '⚙️' },
];

export function renderTabBar(activeTab) {
  return `
    <nav class="tabbar" aria-label="Main">
      ${TABS.map((tab) => `
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

export function renderLogTab({
  form, submit, ingest, backendConfigured, online, history, detailId, sync, manualOpen, workoutChat,
}) {
  return `
    <div class="wrap settings-wrap">
      <header class="mast" style="border-bottom:none;padding-bottom:0;">
        <div>
          <span class="mark">swim-coach · log</span>
          <h1>Log a swim</h1>
          <p class="sub">Record a completed session so your coach sees it.</p>
        </div>
      </header>
      ${!online ? '<div class="chat-banner">Offline -- logging needs a connection.</div>' : ''}
      ${!backendConfigured ? renderBackendNeededNotice('Logging a swim needs you to sign in and set a backend URL and token first.') : `
      ${renderSyncSection(sync, online)}
      ${renderManualLogSection({
        form, submit, ingest, online, open: !!manualOpen,
      })}
      ${renderHistorySection({ ...history, online, detailId, workoutChat })}`}
    </div>`;
}

// --- Workout history (Log tab section) ----------------------------------
// Renders whatever's already been logged/imported -- manual entries plus
// .fit/.tcx/.csv/coach-text imports, which previously had no UI at all (see
// api.js's listWorkouts, which existed but nothing called). Kept as its own
// section/render function (rather than folded into renderLogTab's markup
// inline) so it's cheaply unit-testable on its own -- see
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

function renderHistoryList(workouts) {
  return `<div class="hist-list">${workouts.map(renderWorkoutRow).join('')}</div>`;
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

/** `history` is `{ status, data, error }` (see main.js's state.workoutHistory)
 * plus `online` and `detailId` folded in -- status is one of
 * idle/loading/ready/error, same convention as plan/profile/feedback in
 * main.js. `detailId` (main.js's state.workoutDetailId) is null for the
 * list view, or a workout id to show that workout's detail view instead --
 * checked ahead of every status branch (using whatever `data` is already in
 * state, stale-during-a-refresh included) so the detail view survives a
 * background render() exactly like every other state-driven view here.
 * `workoutChat` (main.js's state.workoutChat -- {workoutId, messages} or
 * null) feeds the detail view's embedded scoped chat section. */
export function renderHistorySection({
  status, data, error, online, detailId, workoutChat,
}) {
  const hasData = data && data.length > 0;

  if (hasData && detailId) {
    const workout = data.find((w) => w.id === detailId);
    if (workout) {
      return `
        <section class="hist-section">
          <div class="s-head"><button type="button" class="btn-ghost" data-a="history:back">&larr; Back to history</button></div>
          ${renderWorkoutDetail(workout, { chat: workoutChat, online })}
        </section>`;
    }
  }

  if (status === 'error') {
    return `
      <section class="hist-section">
        <div class="s-head"><h2>Recent workouts</h2></div>
        ${hasData ? renderHistoryList(data) : ''}
        <div class="hist-error">Couldn't load your workout history: ${esc(error)}</div>
        <div class="settings-actions"><button type="button" class="btn-ghost" data-a="history:retry">Retry</button></div>
      </section>`;
  }

  if (status === 'loading' && !hasData) {
    return `
      <section class="hist-section">
        <div class="s-head"><h2>Recent workouts</h2></div>
        <p class="sub">Loading history…</p>
      </section>`;
  }

  if (!hasData) {
    const notice = !online
      ? '<p class="sub">History needs a connection -- reconnect to load it.</p>'
      : '<p class="sub">No workouts logged yet.</p>';
    return `
      <section class="hist-section">
        <div class="s-head"><h2>Recent workouts</h2></div>
        ${notice}
      </section>`;
  }

  return `
    <section class="hist-section">
      <div class="s-head"><h2>Recent workouts</h2></div>
      ${renderHistoryList(data)}
    </section>`;
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

// --- Settings tab ------------------------------------------------------------

export function renderSettingsTab({
  identity, identityError, backendConfigured, profileForm, profileLoad, profileSubmit,
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
