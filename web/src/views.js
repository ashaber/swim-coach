// HTML-string view templates. Pure functions of data in, markup out --
// no DOM access here (that's main.js's job).

import {
  formatShortDate, formatLongDate, formatDuration, formatDistance, formatPace,
  parseIsoDate, sessionsByDay, classifySession, sessionDisplay, sessionDotColorVar,
  pickCurrentAndNextWeek, daysUntil, priorityEvent, currentBlockIndex, longSwimLadder,
} from './plan.js';

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
