// Markup for the race view cards and the section drill-down overlay (models: raceView.js). Graphics take
// their colours from raceHeat.js through inline styles; everything textual uses the theme tokens.

import { esc } from './html.js';
import { CHART } from './raceView.js';

const bar = (colour, pct) => `<i class="rv-bar" style="background:${colour};width:${pct}%"></i>`;
const swatch = (colour) => `<i class="rv-swatch" style="background:${colour}"></i>`;
const legend = (items) => `<div class="rv-legend" aria-hidden="true">${items.map((i) => `<span>${swatch(i.colour)}${esc(i.label)}</span>`).join('')}</div>`;

function tile(t, cls = '') {
  return `<div class="rv-tile ${cls}"><span class="rv-num${t.emphasis ? ' rv-emph' : ''}">${esc(t.value)}${t.unit ? `<small> ${esc(t.unit)}</small>` : ''}</span><span class="rv-cap">${esc(t.label)}</span></div>`;
}

function renderSummary(summary, ui) {
  const open = Boolean(ui.moreOpen);
  return `
    <section class="rv-card" aria-label="Race summary">
      <div class="rv-tiles rv-tiles-4">${summary.headline.map((t) => tile(t)).join('')}</div>
      ${open && summary.more.length ? `<div class="rv-tiles rv-tiles-3 rv-more">${summary.more.map((t) => tile(t, 'rv-tile-sm')).join('')}</div>` : ''}
      ${summary.more.length ? `<button type="button" class="rv-btn" data-a="race:more-toggle" aria-expanded="${open}">${open ? 'Fewer numbers' : 'More numbers: max HR, speed, work…'}</button>` : ''}
    </section>`;
}

/** A probeable power chart: the wrapper carries the series for chartProbe.js. */
function probeChart(id, aria, inner, series) {
  return `
      <div class="rv-probe" data-probe="${esc(JSON.stringify(series))}" data-probe-read="${id}">
        <svg viewBox="0 0 ${CHART.w} ${CHART.h}" class="rv-chart" role="img" aria-label="${esc(aria)}">
          <line class="rv-axis" x1="${CHART.left}" y1="${CHART.base}" x2="${CHART.right}" y2="${CHART.base}"/>
          ${inner}
        </svg>
        <span class="rv-probe-line" hidden></span>
      </div>
      <div class="rv-readout" id="${id}" aria-live="polite">Touch or hover the graph for values</div>`;
}

function renderStart(start) {
  if (!start) return '';
  const inner = `
          <line class="rv-grid" x1="${CHART.left}" y1="${start.grid.y}" x2="${CHART.right}" y2="${start.grid.y}"/>
          ${start.ghost ? `<polyline class="rv-line rv-ghost" points="${start.ghost}"/>` : ''}
          <polyline class="rv-line rv-now" points="${start.points}"/>
          ${start.dip ? `<circle class="rv-dip" cx="${start.dip.x}" cy="${start.dip.y}" r="5"/>` : ''}
          <text class="rv-tick" x="${CHART.left}" y="99">0 s</text><text class="rv-tick" x="${CHART.right - 20}" y="99">${esc(start.endLabel)}</text>
          <text class="rv-tick" x="${CHART.right - 20}" y="${start.grid.y - 4}">${esc(start.grid.label)}</text>`;
  return `
    <section class="rv-card" aria-label="Start">
      <div class="rv-head"><h4>Start</h4><span class="rv-sub">${esc(start.subtitle)}</span></div>
      <div class="rv-tiles rv-tiles-3">${start.tiles.map((t) => tile(t)).join('')}</div>
      ${probeChart('rv-start-read', start.aria, inner, start.series)}
      <div class="rv-keys"><span>${swatch('var(--accent)')}${esc(start.cur)}</span>${start.prev ? `<span>${swatch('var(--ink-soft)')}${esc(start.prev)}</span>` : ''}</div>
      ${start.callout ? `<p class="rv-text">Power dropped to <b>${esc(start.callout.strong)}</b> before you got back on it.${esc(start.callout.tail)}</p>` : ''}
    </section>`;
}

function renderRaceMap(map) {
  const segs = map.sectors.map((s) => `
        <g class="rv-seg${s.dim ? ' rv-dim' : ''}" data-a="race:section-open" data-label="${esc(s.label)}" role="button" tabindex="0" aria-label="${esc(s.aria)}">
          <polyline class="rv-hit" points="${s.points}" fill="none"/>
          <polyline points="${s.points}" fill="none" stroke="${s.colour}" class="rv-stroke"/>
          <text class="rv-seglabel" x="${s.at.x}" y="${s.at.y}" text-anchor="middle" dominant-baseline="central">${esc(s.label)}</text>
        </g>`).join('');
  return `
      <svg class="rv-map" viewBox="${map.viewBox}" role="group" aria-label="Course map, north up. Tap a section for its detail.">
        ${segs}
        <circle class="rv-start" cx="${map.start.x}" cy="${map.start.y}" r="5"/>
      </svg>`;
}

function idealLine(ideal) {
  if (!ideal) return '';
  const best = ideal.bestLap ? ` Best real lap ${esc(ideal.bestLap)}, so <b>${esc(ideal.onTable)}</b> is on the table.` : '';
  return `<p class="rv-text">Ideal lap <b>${esc(ideal.ideal)}</b> (your best of every section).${best}${ideal.beyondNoise ? ` ${esc(ideal.beyondNoise)}` : ''}</p>`;
}

function lossRow(r) {
  return `
      <button type="button" class="rv-item" data-a="race:section-open" data-label="${esc(r.label)}">
        <span class="rv-item-name">${swatch(r.colour)}${esc(r.label)}</span>
        <span class="rv-item-body"><b>${esc(r.title)}</b><small>${esc(r.sub)}</small></span>
        <span class="rv-item-val">${esc(r.value)} ›</span>
      </button>`;
}

function renderAnalysis(a) {
  if (!a) return '';
  const buttons = a.metrics.map((m) => `<button type="button" class="rv-chip${m.on ? ' on' : ''}" data-a="race:metric" data-metric="${m.key}" aria-pressed="${m.on}">${esc(m.label)}</button>`).join('');
  return `
    <section class="rv-card" aria-label="Section analysis">
      <h4>Section analysis</h4>
      <span class="rv-kicker">Time lost · consistency · efficiency · flow (tap a section)</span>
      ${idealLine(a.ideal)}
      <div class="rv-chips" role="group" aria-label="Map colour">${buttons}</div>
      ${a.effNote ? `<p class="rv-sub">${esc(a.effNote)}</p>` : ''}
      ${a.map ? renderRaceMap(a.map) : ''}
      ${legend(a.legend)}
      <h5 class="rv-h5">Biggest losses</h5>
      ${a.losses.length ? a.losses.map(lossRow).join('') : `<p class="rv-sub">${esc(a.noNotable || 'No section stands out.')}</p>`}
    </section>`;
}

function renderFreeSpeed(list) {
  if (!list) return '';
  return `
    <section class="rv-card" aria-label="Free speed">
      <h4>Free speed</h4>
      <p class="rv-text">Passes where you went as fast or faster for fewer watts. Ride these lines every lap.</p>
      ${list.map((f) => `
      <button type="button" class="rv-item" data-a="race:section-open" data-label="${esc(f.label)}">
        <span class="rv-item-name">${swatch('var(--accent)')}${esc(f.label)}</span>
        <span class="rv-item-body"><b>${esc(f.title)}</b><small>${esc(f.sub)}</small></span>
        <span class="rv-item-val">${esc(f.value)} ›</span>
      </button>`).join('')}
    </section>`;
}

function renderLaps(laps) {
  if (!laps) return '';
  const rows = laps.rows.map((l) => `
      <div class="rv-laprow${l.best ? ' rv-best' : ''}"><span>${esc(l.label)}</span><span>${esc(l.time)}</span><span class="rv-lapbar">${l.barPct ? bar(l.best ? 'var(--accent)' : 'var(--amber)', l.barPct) : ''}<small>${esc(l.delta)}</small></span><span>${esc(l.np)}</span><span>${esc(l.hr)}</span><span>${esc(l.ef)}</span></div>`).join('');
  return `
    <section class="rv-card" aria-label="Laps">
      <div class="rv-head"><h4>Laps</h4><span class="rv-sub">bar = time behind best</span></div>
      <div class="rv-laprow rv-laphead"><span>Lap</span><span>Time</span><span></span><span>NP</span><span>HR</span><span>EF</span></div>
      ${rows}
      ${laps.startNote ? `<p class="rv-sub">${esc(laps.startNote)}</p>` : ''}
    </section>`;
}

function renderFade(fade) {
  if (!fade) return '';
  const c = fade.chart;
  const chart = c ? `
      <svg viewBox="0 0 ${c.width} 84" class="rv-chart" role="img" aria-label="${esc(c.aria)}">
        <line class="rv-axis" x1="10" y1="70" x2="310" y2="70"/>
        <polyline class="rv-line rv-now" points="${c.np}"/>
        <polyline class="rv-line rv-hr" points="${c.hr}"/>
        <text class="rv-tick" x="4" y="82">${esc(c.firstLabel)}</text><text class="rv-tick" x="296" y="82">${esc(c.lastLabel)}</text>
      </svg>
      <div class="rv-keys"><span>${swatch('var(--amber)')}${esc(c.hrLegend)}</span><span>${swatch('var(--accent)')}${esc(c.npLegend)}</span></div>` : '';
  return `
    <section class="rv-card" aria-label="Efficiency">
      <div class="rv-head"><h4>Did I fade?</h4><span class="rv-pill${fade.drifted ? ' rv-pill-warn' : ''}">${esc(fade.pill)}</span></div>
      ${fade.text ? `<p class="rv-text">${esc(fade.text)}</p>` : ''}
      ${chart}
    </section>`;
}

function renderSprint(sprint) {
  if (!sprint) return '';
  const inner = `
          <line class="rv-grid" x1="${CHART.left}" y1="${sprint.grid.y}" x2="${CHART.right}" y2="${sprint.grid.y}"/>
          <polyline class="rv-line rv-now" points="${sprint.points}"/>
          <text class="rv-tick" x="${CHART.right - 20}" y="${sprint.grid.y - 4}">${esc(sprint.grid.label)}</text><text class="rv-tick" x="${CHART.right - 24}" y="99">line</text>`;
  return `
    <section class="rv-card" aria-label="Finish sprint">
      <h4>Finish sprint</h4>
      <div class="rv-tiles rv-tiles-3">${sprint.tiles.map((t) => tile(t)).join('')}</div>
      ${probeChart('rv-finish-read', sprint.aria, inner, sprint.series)}
    </section>`;
}

function renderAllSections(analysis, splits, ui) {
  if (!analysis) return '';
  const busy = ui.splitBusy;
  const controls = splits.map((c) => `
      <div class="rv-splitbar"><span>${esc(c.hint)}</span><button type="button" class="rv-chip" data-a="race:split" data-label="${esc(c.label)}" data-split="${c.split}" ${busy ? 'disabled' : ''}>${esc(c.button)}</button></div>`).join('');
  const rows = analysis.rows.map((r) => `
      <button type="button" class="rv-secrow${r.noise ? ' rv-muted' : ''}" data-a="race:section-open" data-label="${esc(r.label)}">
        <b>${esc(r.label)}</b><small>${esc(r.meta)}</small>${bar(r.colour, r.widthPct)}<span class="rv-mono">${esc(r.text)}</span>
      </button>`).join('');
  return `
    <section class="rv-card" aria-label="All sections">
      <div class="rv-head"><h4>All sections</h4><span class="rv-sub">course order</span></div>
      ${controls}
      ${busy ? '<p class="rv-sub">Re-analysing…</p>' : ''}
      ${ui.splitError ? `<p class="hist-error">${esc(ui.splitError)}</p>` : ''}
      ${rows}
    </section>`;
}

/** Cards 2-9 of the race view. */
export function renderRaceCards(model, ui = {}) {
  return [
    renderSummary(model.summary, ui),
    renderStart(model.start),
    renderAnalysis(model.analysis),
    renderFreeSpeed(model.freeSpeed),
    renderLaps(model.laps),
    renderFade(model.fade),
    renderSprint(model.sprint),
    renderAllSections(model.analysis, model.splits, ui),
  ].join('');
}

// --- Drill-down -------------------------------------------------------------------------------

function drillMap(d) {
  if (d.status === 'ready') {
    const m = d.map;
    const strokes = m.paths.map((p, i) => (p ? `<path d="${p}" stroke="${m.colours[i]}"/>` : '')).join('');
    return `
      <div class="cs-map-wrap">
        <svg class="cs-map rv-drillmap" viewBox="${m.viewBox}" data-w="${m.width}" data-h="${m.height}" style="--cs-k:1" preserveAspectRatio="xMidYMid meet" role="img" aria-label="${esc(m.aria)}">
          <path class="rv-outline" d="${m.outline}" fill="none"/>
          <g class="rv-heat" fill="none">${strokes}</g>
          ${m.dot ? `<circle class="rv-entry" cx="${m.dot.x}" cy="${m.dot.y}" r="5"/>` : ''}
        </svg>
        <button type="button" class="btn-ghost cs-reset" data-a="workout:map-reset" hidden>Reset view</button>
      </div>`;
  }
  const note = {
    loading: 'Loading the section trace…',
    offline: 'The zoomed trace needs a connection. The course map shows where this section is.',
    error: `Couldn't load the section trace${d.error ? `: ${d.error}` : ''}.`,
  }[d.status];
  return `${d.courseMap ? renderRaceMap(d.courseMap) : ''}
      <p class="rv-sub" role="status">${esc(note)}${d.status === 'error' ? ' <button type="button" class="rv-chip" data-a="race:sections-retry">Retry</button>' : ''}</p>`;
}

function drillTable(rows) {
  if (!rows.length) return '';
  return `
    <section class="rv-card" aria-label="Lap by lap">
      <div class="rv-head"><h4>Lap by lap</h4><span class="rv-sub">flow: lower = smoother</span></div>
      <div class="rv-drillrow rv-laphead"><span>Lap</span><span>Time</span><span>behind best</span><span>Power</span><span>Flow</span></div>
      ${rows.map((l) => `
      <div class="rv-drillrow${l.best ? ' rv-best' : ''}"><span>${l.lap}</span><span>${esc(l.time)}</span><span class="rv-lapbar">${bar(l.best ? 'var(--accent)' : 'var(--amber)', l.barPct)}<small>${esc(l.delta)}</small></span><span>${esc(l.power)}</span><span${l.smoothest ? ' class="rv-smooth"' : ''}>${esc(l.flow)}</span></div>`).join('')}
    </section>`;
}

/** The full-screen drill-down for one section. `note` is `{draft, status, error}`. */
export function renderSectionDrill(d, note = {}) {
  if (!d) return '';
  const tabs = d.tabs.map((t) => `<button type="button" class="rv-tab${t.on ? ' on' : ''}" data-a="race:section-tab" data-label="${esc(t.label)}" aria-pressed="${t.on}">${esc(t.label)}</button>`).join('');
  const modes = d.modes.map((m) => `<button type="button" class="rv-chip${m.on ? ' on' : ''}" data-a="race:drill-mode" data-mode="${m.key}" aria-pressed="${m.on}">${esc(m.label)}</button>`).join('');
  const ready = d.status === 'ready';
  const chips = ready ? `<div class="rv-chips" role="group" aria-label="Lap">${d.lapChips.map((c) => `<button type="button" class="rv-chip rv-lapchip${c.on ? ' on' : ''}" data-a="race:drill-lap" data-lap="${c.lap}" aria-pressed="${c.on}">L${c.lap}${c.best ? ' best' : ''}</button>`).join('')}</div>` : '';
  const speeds = d.speeds ? `
    <section class="rv-card rv-tiles rv-tiles-3" aria-label="Speed through the section">
      ${tile({ value: d.speeds.entry, label: 'entry km/h' })}${d.speeds.slowest ? tile({ value: d.speeds.slowest, label: 'slowest km/h' }) : ''}${tile({ value: d.speeds.exit, label: 'exit km/h' })}
    </section>` : '';
  const saving = note.status === 'submitting';
  return `
    <div class="rd-overlay cs-overlay rv-drill" id="section-drill" role="dialog" aria-modal="true" aria-label="Section ${esc(d.label)}">
      <div class="rd-head" id="section-drill-head">
        <button type="button" class="btn-ghost" data-a="race:drill-close">&larr; Race view</button>
        <button type="button" class="btn-ghost rd-x" data-a="race:drill-close" aria-label="Close">✕</button>
      </div>
      <div class="rd-body" id="section-drill-body">
        <div class="rv-tabs" role="group" aria-label="Section">${tabs}</div>
        <div class="rv-drillhead"><h3 style="--rv-c:${d.colour}"><span class="rv-dot" style="background:${d.colour}"></span>${esc(d.label)}</h3><span class="rv-sub">${esc(d.meta)}</span></div>
        ${drillMap(d)}
        <div class="rv-chips" role="group" aria-label="Heat map colour">${modes}</div>
        ${chips}
        ${ready ? `${legend(d.legend)}<p class="rv-sub">${esc(d.explain)}</p>` : ''}
        ${speeds}
        ${drillTable(d.rows)}
        <section class="rv-card" aria-label="What is in this section">
          <label for="race-section-note" class="rv-notelabel">What's in ${esc(d.label)}? The data can't see features.</label>
          <input id="race-section-note" class="rv-input" type="text" data-form="sectionNote" data-field="draft" placeholder="e.g. off-camber after the barriers, passed two riders on lap 3" value="${esc(note.draft ?? d.note)}">
          <button type="button" class="rv-btn" data-a="race:note-save" data-label="${esc(d.label)}" ${saving ? 'disabled' : ''}>${saving ? 'Saving…' : 'Save note for the coach'}</button>
          ${note.error ? `<p class="hist-error">${esc(note.error)}</p>` : ''}
          ${note.status === 'saved' ? '<p class="rv-sub" role="status">Saved.</p>' : ''}
        </section>
      </div>
    </div>`;
}
