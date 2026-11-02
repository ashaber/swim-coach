// Bike-geometry view (Resources > Bike geometry): a mobile-first measurement form with a
// side-view diagram that highlights the focused field's points, saved-snapshot results with +/-,
// a closure check, a two-snapshot comparison and an overlay drawing. String-template renderers
// over state; no DOM access except the exported in-place diagram refresh. Records and compares
// geometry only: nothing here recommends a change.

import { esc } from './html.js';
import { DIAGRAMS } from './bikeFitDiagram.js';
import { focusInfo } from './bikeFit.js';
import {
  TAPE_FIELDS, BIKE_TYPES, LATERAL_NOTE, HOW_TO_MEASURE, HOW_TO_BY_FIELD, STATEMENT,
} from './bikeFitSpec.js';

const SVG_NS = 'http://www.w3.org/2000/svg';

const flip = (v) => Math.round(-v * 10) / 10;

// --- Entry point in Settings ---------------------------------------------------------------

export function renderBikeFitEntryPanel() {
  return `
    <div class="panel settings-panel" id="bikefit-entry">
      <h3 class="bf-kicker">Bike geometry</h3>
      <p class="field-hint" style="margin:0 0 12px;">Measure each bike with a tape, keep dated snapshots, and compare them side by side. ${esc(STATEMENT)}</p>
      <div class="settings-actions">
        <button type="button" class="btn" data-a="bikefit:open">Open bike geometry</button>
      </div>
    </div>`;
}

// --- Diagram -------------------------------------------------------------------------------

function line(a, b, cls) {
  return `<line class="${cls}" x1="${a[0]}" y1="${flip(a[1])}" x2="${b[0]}" y2="${flip(b[1])}" />`;
}

function drawBike(d, focus) {
  const p = d.points;
  const pt = (id) => p[id];
  const parts = [];
  parts.push(`<line class="bf-floor" x1="${d.floor.x0}" y1="${flip(d.floor.y)}" x2="${d.floor.x1}" y2="${flip(d.floor.y)}" />`);
  for (const w of ['RA', 'FA']) {
    parts.push(`<circle class="bf-tire" cx="${p[w][0]}" cy="${flip(p[w][1])}" r="${d.wheelR}" />`);
    parts.push(`<circle class="bf-rim" cx="${p[w][0]}" cy="${flip(p[w][1])}" r="${d.wheelR - 24}" />`);
  }
  for (const [a, b, cls] of d.frame) parts.push(line(a, b, cls || 'bf-frame'));
  for (const path of d.paths) parts.push(`<path class="${path.cls}" d="${path.d}" />`);
  parts.push(`<path class="bf-saddle${focus.extra === 'saddle' ? ' is-active' : ''}" d="${d.saddle}" />`);
  parts.push(line(d.crank[0], d.crank[1], `bf-crank${focus.extra === 'crank' ? ' is-active' : ''}`));
  for (const extra of d.extras || []) parts.push(extra);
  return parts.join('');
}

function drawFocus(d, focus) {
  const parts = [];
  const p = d.points;
  if (focus.tape) {
    parts.push(line(p[focus.tape.from], p[focus.tape.to], 'bf-tape'));
  }
  if (focus.floor) {
    const at = p[focus.floor];
    parts.push(line(at, [at[0], d.floor.y], 'bf-tape'));
  }
  for (const id of Object.keys(p)) {
    const on = focus.points.includes(id);
    const [x, y] = p[id];
    const lab = d.labels[id];
    parts.push(`<g class="bf-pt${on ? ' is-active' : ''}" data-point="${id}">`
      + (on ? `<circle class="bf-halo" cx="${x}" cy="${flip(y)}" r="${d.dot * 3.2}" />` : '')
      + `<circle class="bf-dot" cx="${x}" cy="${flip(y)}" r="${d.dot * (on ? 1.5 : 1)}" />`
      + `<text class="bf-label" x="${x + lab[0]}" y="${flip(y) + lab[1]}" text-anchor="${lab[2]}" font-size="${d.font}">${id}</text>`
      + '</g>');
  }
  return parts.join('');
}

/** The side-view SVG for a bike type, with the focused field's points and tape line highlighted. */
export function renderBikeSvg(bikeType, focus) {
  const d = DIAGRAMS[bikeType] || DIAGRAMS.drop_bar;
  const label = bikeType === 'mtb' ? 'Side view of a full-suspension mountain bike' : 'Side view of a drop-bar bike';
  return `<svg class="bf-svg" xmlns="${SVG_NS}" viewBox="${d.viewBox}" role="img" aria-label="${label}">${drawBike(d, focus)}${drawFocus(d, focus)}</svg>`;
}

function definitionsHtml(info, bikeType) {
  if (!info.points.length) {
    return '<p class="bf-def-empty">Tap a measurement field to see its points on the bike.</p>';
  }
  const items = info.definitions.map((x) => `<li><b>${esc(x.point)}</b> (${esc(x.name)}): ${esc(x.text)}</li>`).join('');
  const how = HOW_TO_BY_FIELD[{ tiltMag: 'saddle_tilt', tiltDir: 'saddle_tilt', floorMag: 'floor_tilt', floorDir: 'floor_tilt',
    saddleLength: 'saddle_length', crankLength: 'crank_length', barWidth: 'bar_width', seatBb: 'seated_bb', seatBc: 'seated_bc' }[info.field]];
  const tape = info.tape
    ? `<p class="bf-def-line">Tape straight from ${esc(info.tape.from)} to ${esc(info.tape.to)}.</p>`
    : info.floor ? `<p class="bf-def-line">Tape straight down from ${esc(info.floor)} to the floor.</p>` : '';
  return `<ul class="bf-def-list">${items}</ul>${tape}${how ? `<p class="bf-def-line">${esc(how)}</p>` : ''}`;
}

/** Diagram plus the one-sentence definition of each highlighted point; re-rendered in place on focus. */
export function renderDiagramPanel(bikeType, focusField) {
  const info = focusInfo(focusField, bikeType);
  return `${renderBikeSvg(bikeType, info)}<div class="bf-defs" aria-live="polite">${definitionsHtml(info, bikeType)}</div>`;
}

/** Swaps the diagram panel's contents without re-rendering the form (keeps the keyboard up). */
export function refreshDiagram(root, bikeType, focusField) {
  const el = root.querySelector('#bf-diagram');
  if (el) el.innerHTML = renderDiagramPanel(bikeType, focusField);
}

// --- Form ----------------------------------------------------------------------------------

function numField({ field, label, value, hint, mode = 'numeric', unit = 'mm', required = false, n = null, extra = '' }) {
  return `
    <label class="field bf-field">
      <span>${n ? `<b class="bf-n">${n}</b> ` : ''}${esc(label)}${required ? '' : ' <i class="bf-opt">optional</i>'}</span>
      <span class="bf-input-row">
        <input type="text" inputmode="${mode}" autocomplete="off" enterkeyhint="next" data-form="bikefit" data-field="${field}"
          aria-label="${esc(label)} in ${esc(unit)}" value="${esc(value)}" ${extra}>
        <span class="bf-unit">${esc(unit)}</span>
      </span>
      ${hint ? `<span class="bf-hint">${esc(hint)}</span>` : ''}
    </label>`;
}

function signedField({ dirField, magField, form, label, hint, required }) {
  return `
    <div class="field bf-field">
      <span>${esc(label)}${required ? '' : ' <i class="bf-opt">optional</i>'}</span>
      <span class="bf-input-row">
        <select data-form="bikefit" data-field="${dirField}" aria-label="${esc(label)} direction">
          <option value="up"${form[dirField] === 'up' ? ' selected' : ''}>Nose up (+)</option>
          <option value="down"${form[dirField] === 'down' ? ' selected' : ''}>Nose down (&minus;)</option>
        </select>
        <input type="text" inputmode="decimal" autocomplete="off" data-form="bikefit" data-field="${magField}"
          aria-label="${esc(label)} in degrees" value="${esc(form[magField])}">
        <span class="bf-unit">deg</span>
      </span>
      ${hint ? `<span class="bf-hint">${esc(hint)}</span>` : ''}
    </div>`;
}

function tapeGroups(form) {
  const groups = [];
  for (const t of TAPE_FIELDS) {
    let g = groups.find((x) => x.name === t.group);
    if (!g) { g = { name: t.group, fields: [] }; groups.push(g); }
    g.fields.push(t);
  }
  return groups.map((g) => `
    <fieldset class="bf-group">
      <legend>${esc(g.name)}</legend>
      ${g.fields.map((t) => numField({
    field: t.key, label: t.label, value: form[t.key], required: true, n: t.n,
  })).join('')}
    </fieldset>`).join('');
}

function renderForm({ form, errors, submit, online }) {
  const mtb = form.bikeType === 'mtb';
  const saving = submit.status === 'submitting';
  return `
    <div class="panel bf-panel">
      <h3 class="bf-kicker">New snapshot</h3>
      <p class="bf-draft">Your entries are saved on this device as you type, so a half-finished session survives a reload or losing signal.</p>
      <label class="field bf-field"><span>Bike name</span>
        <input type="text" autocomplete="off" data-form="bikefit" data-field="name" value="${esc(form.name)}" aria-label="Bike name"></label>
      <label class="field bf-field"><span>Bike type</span>
        <select data-form="bikefit" data-field="bikeType" aria-label="Bike type">
          ${BIKE_TYPES.map((o) => `<option value="${o.value}"${form.bikeType === o.value ? ' selected' : ''}>${esc(o.label)}</option>`).join('')}
        </select></label>
      <label class="field bf-field"><span>Date</span>
        <input type="date" data-form="bikefit" data-field="date" value="${esc(form.date)}" aria-label="Date"></label>
      <details class="bf-howto" open>
        <summary>How to take the measurements</summary>
        <ul>${HOW_TO_MEASURE.map((h) => `<li>${esc(h)}</li>`).join('')}</ul>
      </details>
      <h4 class="bf-sub">Tape measures (mm)</h4>
      ${tapeGroups(form)}
      <h4 class="bf-sub">Saddle, cranks and bars</h4>
      ${signedField({ dirField: 'tiltDir', magField: 'tiltMag', form, label: 'Saddle tilt', required: true, hint: HOW_TO_BY_FIELD.saddle_tilt + ' Enter 0 if level.' })}
      ${signedField({ dirField: 'floorDir', magField: 'floorMag', form, label: 'Floor reading, same device', hint: HOW_TO_BY_FIELD.floor_tilt })}
      ${numField({ field: 'saddleLength', label: 'Saddle length', value: form.saddleLength, required: true, hint: HOW_TO_BY_FIELD.saddle_length })}
      ${numField({ field: 'crankLength', label: 'Crank length', value: form.crankLength, required: true, mode: 'decimal', hint: HOW_TO_BY_FIELD.crank_length })}
      ${numField({ field: 'barWidth', label: 'Bar width', value: form.barWidth, required: true, hint: HOW_TO_BY_FIELD.bar_width })}
      <h4 class="bf-sub">Lateral offsets from the centerline (assumptions)</h4>
      <p class="bf-hint">${esc(LATERAL_NOTE[form.bikeType])} These are assumptions, not measurements: edit them if you know better.</p>
      ${numField({ field: 'latBb', label: 'BB bolt, left of centerline', value: form.latBb, required: true })}
      ${numField({ field: 'latFa', label: 'Front axle end, left of centerline', value: form.latFa, required: true })}
      ${numField({ field: 'latRa', label: 'Rear axle end, left of centerline', value: form.latRa, required: true })}
      ${mtb ? `
      <h4 class="bf-sub">Suspension</h4>
      <p class="bf-hint">Sag is recorded and shown, not used in the geometry.</p>
      ${numField({ field: 'sagFront', label: 'Front sag', value: form.sagFront, unit: '%', mode: 'decimal' })}
      ${numField({ field: 'sagRear', label: 'Rear sag', value: form.sagRear, unit: '%', mode: 'decimal' })}` : ''}
      <h4 class="bf-sub">Seated${mtb ? '' : ' (optional)'}, helper needed</h4>
      <p class="bf-hint">Rider on the bike, a helper reads both heights. Both or neither. Used to estimate the bike&rsquo;s orientation under load.</p>
      ${numField({ field: 'seatBb', label: 'Seated: floor to BB', value: form.seatBb, hint: HOW_TO_BY_FIELD.seated_bb })}
      ${numField({ field: 'seatBc', label: 'Seated: floor to BC', value: form.seatBc, hint: HOW_TO_BY_FIELD.seated_bc })}
      <h4 class="bf-sub">Tires and note</h4>
      ${numField({ field: 'tireFront', label: 'Front tire pressure', value: form.tireFront, unit: 'psi', mode: 'decimal' })}
      ${numField({ field: 'tireRear', label: 'Rear tire pressure', value: form.tireRear, unit: 'psi', mode: 'decimal' })}
      <label class="field bf-field"><span>Note <i class="bf-opt">optional</i></span>
        <textarea rows="2" data-form="bikefit" data-field="note" aria-label="Note">${esc(form.note)}</textarea></label>
      ${errors.length ? `<div class="conn-result fail" role="alert"><ul class="bf-errors">${errors.map((e) => `<li>${esc(e)}</li>`).join('')}</ul></div>` : ''}
      ${submit.status === 'error' ? `<div class="conn-result fail" role="alert">${esc(submit.message)}</div>` : ''}
      ${online ? '' : '<div class="conn-result fail" role="status">You are offline. Your entries are kept on this device; save the snapshot when you are back online.</div>'}
      <div class="settings-actions" style="margin-top:14px;">
        <button type="button" class="btn" data-a="bikefit:save"${saving || !online ? ' disabled' : ''}>${saving ? 'Saving&hellip;' : 'Save snapshot'}</button>
        <button type="button" class="btn-ghost" data-a="bikefit:reset-draft">Clear entries</button>
      </div>
    </div>`;
}

// --- Results -------------------------------------------------------------------------------

export function fmtValue(v, unit) {
  if (v === null || v === undefined || Number.isNaN(v)) return '';
  const rounded = Math.abs(v) < 0.05 ? 0 : v;
  return `${rounded.toFixed(1)}${unit === 'deg' ? '°' : ''}`;
}

function fmtPm(sigma, unit) {
  return `±${sigma.toFixed(1)}${unit === 'deg' ? '°' : ''}`;
}

function valueRows(outputs) {
  return outputs.map((o) => `
    <tr><th scope="row">${esc(o.label)} <span class="bf-u">(${esc(o.unit)})</span></th>
      <td class="mono">${esc(fmtValue(o.value, o.unit))}</td><td class="mono bf-pm">${esc(fmtPm(o.sigma, o.unit))}</td></tr>`).join('');
}

function definitionList(outputs) {
  return `<details class="bf-howto"><summary>What each value means</summary><dl class="bf-dl">${
    outputs.map((o) => `<dt>${esc(o.label)}</dt><dd>${esc(o.definition)}</dd>`).join('')}</dl></details>`;
}

function closureHtml(c) {
  const cls = { ok: 'ok', warn: 'warn', bad: 'bad' }[c.status];
  const word = { ok: 'Closure OK', warn: 'Closure: recheck', bad: 'Closure: likely bad measurement' }[c.status];
  const suspects = c.suspects.length
    ? `<p class="bf-hint">Recheck first: ${esc(c.suspects.map((s) => s.label).join(', '))}.</p>` : '';
  const affected = c.affected_outputs.length
    ? `<p class="bf-hint">Values that depend on the suspect measures: ${esc(c.affected_outputs.join(', '))}.</p>` : '';
  return `
    <div class="bf-closure bf-closure-${cls}" data-closure="${c.status}">
      <b>${word}</b>: solved RA-FA ${c.computed_mm.toFixed(1)} mm, measured ${c.measured_mm.toFixed(1)} mm, difference ${c.residual_mm.toFixed(1)} mm
      (warn from ${c.warn_mm} mm, likely bad beyond ${c.bad_mm} mm).
      <p class="bf-hint">${esc(c.message)}</p>${suspects}${affected}
    </div>`;
}

function assumptionsHtml(a) {
  return `<p class="bf-hint"><b>Assumptions:</b> lateral offsets from the centerline, in mm: BB bolt ${a.bb_mm}, front axle end ${a.fa_mm},
    rear axle end ${a.ra_mm}, hand point ${a.h_mm} (half the bar width)${a.defaulted.length ? `; ${a.defaulted.map((k) => k.toUpperCase()).join(', ')} are bike-type defaults` : ''}.</p>`;
}

export function renderResults(snap) {
  if (snap.error) {
    return `<div class="panel bf-panel"><h3 class="bf-kicker">${esc(snap.bike_name)}</h3><div class="conn-result fail">These measurements no longer solve: ${esc(snap.error)}</div></div>`;
  }
  const d = snap.derived;
  const seated = d.seated;
  const notes = d.notes.map((n) => `<p class="bf-note">${esc(n)}</p>`).join('');
  return `
    <div class="panel bf-panel" data-results="${esc(snap.id)}">
      <h3 class="bf-kicker">${esc(snap.bike_name)} &middot; ${esc(snap.date)}${snap.retired ? ' &middot; retired' : ''}</h3>
      <p class="bf-hint">${esc(snap.bike_type === 'mtb' ? 'Full-suspension MTB' : 'Drop bar')}${snap.tire_front_psi != null ? `; tires ${snap.tire_front_psi} front / ${snap.tire_rear_psi ?? '?'} rear psi` : ''}${snap.inputs.sag_front_pct != null || snap.inputs.sag_rear_pct != null ? `; sag ${snap.inputs.sag_front_pct ?? '?'}% front / ${snap.inputs.sag_rear_pct ?? '?'}% rear (recorded, not used)` : ''}</p>
      ${snap.note ? `<p class="bf-hint">Note: ${esc(snap.note)}</p>` : ''}
      ${closureHtml(d.closure)}
      <h4 class="bf-sub">Unweighted${snap.bike_type === 'mtb' && !seated ? ' (only)' : ''}</h4>
      <p class="bf-hint">Ground direction uses a wheel-radius correction of ${d.radius_difference_mm.toFixed(1)} mm (front minus rear axle height), a ${d.ground_pitch_deg.toFixed(2)}° axle-line tilt.
        Each ± is one standard deviation of tape error (${d.constants.tape_sigma_mm} mm per reading). Comparisons use the sit point (${d.constants.sit_fraction} of the saddle, tip to tail); the tip stays visible.</p>
      <div class="bf-table-wrap"><table class="bf-table"><tbody>${valueRows(d.outputs)}</tbody></table></div>
      ${seated ? `
      <h4 class="bf-sub">Seated, under load</h4>
      <p class="bf-hint">Frame rotated ${fmtValue(seated.rotation_deg, 'deg')} (±${seated.rotation_sigma_deg.toFixed(2)}°) about the BB from the unweighted position (positive is nose up). ${esc(seated.assumption)}</p>
      <div class="bf-table-wrap"><table class="bf-table"><tbody>${valueRows(seated.outputs)}</tbody></table></div>` : ''}
      ${notes}
      ${assumptionsHtml(d.assumptions)}
      ${definitionList(d.outputs)}
    </div>`;
}

// --- Comparison ----------------------------------------------------------------------------

function compareRows(rows) {
  return rows.map((r) => `
    <tr data-key="${esc(r.key)}"><th scope="row">${esc(r.label)} <span class="bf-u">(${esc(r.unit)})</span></th>
      <td class="mono">${esc(fmtValue(r.a, r.unit))}</td><td class="mono">${esc(fmtValue(r.b, r.unit))}</td>
      <td class="mono">${r.diff > 0 ? '+' : ''}${esc(fmtValue(r.diff, r.unit))}</td>
      <td class="mono bf-pm">${esc(fmtPm(r.sigma_diff, r.unit))}</td>
      <td><span class="bf-verdict ${r.exceeds_error ? 'bf-beyond' : 'bf-within'}">${r.exceeds_error ? 'Exceeds error' : 'Within error'}</span></td></tr>`).join('');
}

function compareTable(rows, aName, bName) {
  return `<div class="bf-table-wrap"><table class="bf-table bf-compare">
    <thead><tr><th scope="col">Value</th><th scope="col">${esc(aName)}</th><th scope="col">${esc(bName)}</th><th scope="col">B &minus; A</th><th scope="col">Combined ±</th><th scope="col">Real?</th></tr></thead>
    <tbody>${compareRows(rows)}</tbody></table></div>`;
}

const snapLabel = (s) => `${s.bike_name} · ${s.date}`;

export function renderOverlay(a, b) {
  const pts = [...Object.values(a.derived.points), ...Object.values(b.derived.points)];
  const radii = [...Object.values(a.derived.axle_heights_mm), ...Object.values(b.derived.axle_heights_mm)];
  const maxR = Math.max(...radii);
  const xs = [...pts.map((q) => q[0]), -maxR - 450, maxR + 650];
  const ys = [...pts.map((q) => q[1]), 120];
  const x0 = Math.min(...xs) - 60; const x1 = Math.max(...xs) + 60;
  const top = Math.max(...ys) + 60; const bottom = -(maxR + 60);
  const bike = (snap, cls) => {
    const q = snap.derived.points;
    const wheel = (id, r) => `<circle class="${cls} bf-ov-wheel" cx="${q[id][0].toFixed(1)}" cy="${flip(q[id][1])}" r="${r}" />`;
    const seg = (m, n) => `<line class="${cls}" x1="${q[m][0].toFixed(1)}" y1="${flip(q[m][1])}" x2="${q[n][0].toFixed(1)}" y2="${flip(q[n][1])}" />`;
    const dot = (id) => `<circle class="${cls} bf-ov-dot" cx="${q[id][0].toFixed(1)}" cy="${flip(q[id][1])}" r="14" />`;
    return wheel('RA', snap.derived.axle_heights_mm.rear) + wheel('FA', snap.derived.axle_heights_mm.front)
      + seg('RA', 'BB') + seg('BB', 'FA') + seg('BB', 'ST') + seg('ST', 'SRP') + seg('BB', 'BC') + seg('BC', 'H')
      + dot('BB') + dot('ST') + dot('SRP') + dot('H');
  };
  return `
    <figure class="bf-overlay">
      <svg class="bf-svg" xmlns="${SVG_NS}" viewBox="${x0.toFixed(0)} ${flip(top)} ${(x1 - x0).toFixed(0)} ${(top - bottom).toFixed(0)}" role="img"
        aria-label="Both bikes drawn on top of each other, aligned at the bottom bracket">
        ${bike(a, 'bf-ov-a')}${bike(b, 'bf-ov-b')}
        <circle class="bf-ov-origin" cx="0" cy="0" r="22" />
      </svg>
      <figcaption class="bf-hint">Aligned at the BB (ring), unweighted, with the sit point (SRP) marked. <span class="bf-key bf-key-a"></span> A: ${esc(snapLabel(a))} &nbsp; <span class="bf-key bf-key-b"></span> B: ${esc(snapLabel(b))}. Skeleton lines join measured points only: not frame tubes.</figcaption>
    </figure>`;
}

function renderCompare({ snapshots, compare }) {
  if (snapshots.length < 2) {
    return `<div class="panel bf-panel"><h3 class="bf-kicker">Compare</h3><p class="bf-hint">Save at least two snapshots (two bikes, or before and after) to compare them.</p></div>`;
  }
  const opts = (sel) => snapshots.map((s) => `<option value="${esc(s.id)}"${s.id === sel ? ' selected' : ''}>${esc(snapLabel(s))}</option>`).join('');
  let body = '';
  if (compare.status === 'loading') body = '<p class="bf-hint">Comparing&hellip;</p>';
  else if (compare.status === 'error') body = `<div class="conn-result fail">${esc(compare.error)}</div>`;
  else if (compare.status === 'ready') {
    const c = compare.data;
    body = `
      <p class="bf-hint">Difference is B minus A. &ldquo;Exceeds error&rdquo; means the difference is more than ${c.factor}&times; its combined ±, so smaller gaps should not be read as real.
        Both snapshots use their sit point; saddles differ, so the tip rows are shown too.</p>
      ${c.notes.map((n) => `<p class="bf-note">${esc(n)}</p>`).join('')}
      ${compareTable(c.unweighted, c.a.bike_name, c.b.bike_name)}
      ${c.seated ? `<h4 class="bf-sub">Seated (both snapshots)</h4>${compareTable(c.seated, c.a.bike_name, c.b.bike_name)}` : ''}
      ${renderOverlay(c.a, c.b)}`;
  }
  return `
    <div class="panel bf-panel" id="bf-compare">
      <h3 class="bf-kicker">Compare two snapshots</h3>
      <label class="field bf-field"><span>A</span><select data-form="bikefit-compare" data-field="a" aria-label="Snapshot A">${opts(compare.a)}</select></label>
      <label class="field bf-field"><span>B</span><select data-form="bikefit-compare" data-field="b" aria-label="Snapshot B">${opts(compare.b)}</select></label>
      <div class="settings-actions"><button type="button" class="btn" data-a="bikefit:compare">Compare</button></div>
      ${body}
    </div>`;
}

// --- Snapshot list -------------------------------------------------------------------------

function renderList({ snapshots, selectedId }) {
  if (!snapshots.length) return '';
  return `
    <div class="panel bf-panel">
      <h3 class="bf-kicker">Saved snapshots</h3>
      <ul class="bf-list">${snapshots.slice().reverse().map((s) => `
        <li class="bf-item${s.retired ? ' is-retired' : ''}${s.id === selectedId ? ' is-selected' : ''}" data-snapshot="${esc(s.id)}">
          <span class="bf-item-name"><b>${esc(s.bike_name)}</b> <span class="bf-hint">${esc(s.date)} &middot; ${esc(s.bike_type === 'mtb' ? 'MTB' : 'drop bar')}${s.retired ? ' &middot; retired' : ''}</span></span>
          <span class="bf-item-actions">
            <button type="button" class="btn-ghost" data-a="bikefit:show" data-id="${esc(s.id)}">Results</button>
            <button type="button" class="btn-ghost" data-a="bikefit:retire" data-id="${esc(s.id)}" data-retired="${s.retired ? '1' : '0'}">${s.retired ? 'Restore' : 'Retire'}</button>
          </span>
        </li>`).join('')}</ul>
      <p class="bf-hint">Snapshots are never edited or deleted. Retiring one only marks it superseded.</p>
    </div>`;
}

// --- Whole view ----------------------------------------------------------------------------

export function renderBikeFitView({ bikeFit, online }) {
  const { form, load, snapshots, selectedId, compare, focus, submit, formErrors } = bikeFit;
  const selected = snapshots.find((s) => s.id === selectedId);
  const loadNote = load.status === 'loading' ? '<p class="bf-hint">Loading your saved snapshots&hellip;</p>'
    : load.status === 'error' ? `<div class="conn-result fail">Couldn't load saved snapshots: ${esc(load.error)}</div>` : '';
  return `
    <div class="wrap settings-wrap bf-wrap">
      <header class="mast">
        <div>
          <span class="mark">swim-coach &middot; resources</span>
          <h1>Bike geometry</h1>
          <p class="sub">${esc(STATEMENT)}</p>
        </div>
        <button type="button" class="btn-ghost" data-a="bikefit:close">Back to resources</button>
      </header>
      <div class="panel bf-panel bf-sticky" id="bf-diagram-panel">
        <div id="bf-diagram">${renderDiagramPanel(form.bikeType, focus)}</div>
      </div>
      ${renderForm({ form, errors: formErrors, submit, online })}
      ${loadNote}
      ${selected ? renderResults(selected) : ''}
      ${renderList({ snapshots, selectedId })}
      ${renderCompare({ snapshots, compare })}
      <div class="panel bf-panel"><p class="bf-hint">${esc(bikeFit.limits || STATEMENT)}</p></div>
    </div>`;
}
