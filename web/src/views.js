// HTML-string view templates. Pure functions of data in, markup out --
// no DOM access here (that's main.js's job).

import {
  formatShortDate, formatLongDate, formatDuration, formatDistance, formatPace,
  parseIsoDate, sessionsByDay, classifySession, sessionDisplay, sessionDotColorVar,
  pickCurrentAndNextWeek, daysUntil, priorityEvent, currentBlockIndex, longSwimLadder,
} from './plan.js';
import { TOOL_LABELS } from './chat.js';

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
// 5 tabs now that the write endpoints (IDEA 003's Log/Checkin) have a
// backend; Library/Athlete still don't. Adding one later is just another
// entry in TABS plus a case in main.js's tab-content switch -- nothing here
// needs to change.
const TABS = [
  { id: 'plan', label: 'Plan', icon: '📋' },
  { id: 'log', label: 'Log', icon: '📝' },
  { id: 'checkin', label: 'Check-in', icon: '🌙' },
  { id: 'coach', label: 'Coach', icon: '💬' },
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

export function renderLogTab({ form, submit, backendConfigured, online }) {
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
          <span>RPE (effort) &middot; <output id="log-rpe-out">${esc(form.rpe)}</output>/10</span>
          <input type="range" min="1" max="10" step="1" data-form="log" data-field="rpe" data-slider-out="log-rpe-out" value="${esc(form.rpe)}">
        </label>
        <label class="field">
          <span>Notes</span>
          <textarea rows="3" data-form="log" data-field="notes" placeholder="How did it feel?">${esc(form.notes)}</textarea>
        </label>
        <div class="settings-actions">
          <button type="button" class="btn" data-a="log:submit" ${submit.status === 'submitting' || !online ? 'disabled' : ''}>${submit.status === 'submitting' ? 'Saving…' : 'Save'}</button>
        </div>
        ${renderSubmitResult(submit)}
      </div>`}
    </div>`;
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

// --- Settings tab ------------------------------------------------------------

export function renderSettingsTab({
  baseUrl, token, testStatus, identity, identityError, backendConfigured, profileForm, profileLoad, profileSubmit,
}) {
  return `
    <div class="wrap settings-wrap">
      <header class="mast" style="border-bottom:none;padding-bottom:0;">
        <div>
          <span class="mark">swim-coach · settings</span>
          <h1>Backend connection</h1>
          <p class="sub">Point the app at your coach-chat backend.</p>
        </div>
      </header>
      <div class="panel settings-panel">
        <h3 style="margin:0 0 12px;font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--ink-faint);">Sign in</h3>
        ${identity ? `
        <p class="field-hint" style="margin:0 0 14px;">Signed in as <b>${esc(identity.email)}</b> &rarr; athlete <b>${esc(identity.athlete)}</b> (role <b>${esc(identity.role)}</b>).</p>
        <div class="settings-actions">
          <button type="button" class="btn-ghost" data-a="identity:signout">Sign out</button>
        </div>` : `
        <p class="field-hint" style="margin:0 0 14px;">Sign in with Google to load your own plan. This is client-side identity only -- the shared bearer token below still does the real authenticating to the backend.</p>
        <div id="google-signin-btn"></div>
        ${identityError ? `<div class="conn-result fail">${esc(identityError)}</div>` : ''}`}
      </div>
      <div class="panel settings-panel">
        <label class="field">
          <span>Backend URL</span>
          <input type="url" id="settings-base-url" placeholder="https://coach-api.example.com" value="${esc(baseUrl)}" inputmode="url" autocomplete="off" spellcheck="false">
        </label>
        <label class="field">
          <span>Bearer token</span>
          <input type="password" id="settings-token" placeholder="paste your token" value="${esc(token)}" autocomplete="off" spellcheck="false">
        </label>
        <p class="field-hint">Stored only in this browser's local storage -- never sent anywhere except the backend URL above.</p>
        <div class="settings-actions">
          <button type="button" class="btn" data-a="settings:save">Save</button>
          <button type="button" class="btn-ghost" data-a="settings:test">Test connection</button>
        </div>
        ${testStatus ? `<div class="conn-result ${testStatus.ok ? 'ok' : 'fail'}">${esc(testStatus.message)}</div>` : ''}
      </div>
      ${backendConfigured ? renderProfilePanel({ form: profileForm, load: profileLoad, submit: profileSubmit }) : ''}
    </div>`;
}
