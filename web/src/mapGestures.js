// Pointer-event glue for the course map: two-finger pinch zooms about the pinch midpoint, one-finger
// drag pans only while zoomed (at 1x a finger scrolls the page: touch-action is pan-y), mouse wheel
// zooms, double-tap resets. All maths lives in mapView.js; this file only reads pointers and writes
// the SVG's viewBox, so a gesture never re-renders the page. The final view is handed to `commit`.

import {
  clampView, clientToMap, isZoomed, panBy, pixelsPerUnit, viewBoxAttr, zoomAbout,
} from './mapView.js';

const TAP_MOVE_PX = 6;
const DOUBLE_TAP_MS = 300;
const WHEEL_STEP = 0.002;

const fullOf = (svg) => ({ x: 0, y: 0, w: Number(svg.dataset.w), h: Number(svg.dataset.h) });

function viewOf(svg) {
  const [x, y, w, h] = svg.getAttribute('viewBox').split(' ').map(Number);
  return { x, y, w, h };
}

function paint(svg, view) {
  const full = fullOf(svg);
  const zoomed = isZoomed(view, full);
  svg.setAttribute('viewBox', viewBoxAttr(view));
  svg.style.setProperty('--cs-k', String(Number((view.w / full.w).toFixed(4))));
  svg.style.touchAction = zoomed ? 'none' : 'pan-y';
  const reset = svg.closest('.cs-map-wrap')?.querySelector('.cs-reset');
  if (reset) reset.hidden = !zoomed;
}

const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y);

/** `root` is the delegated container (#app); `commit(view|null)` stores the gesture's final view;
 * `reset()` clears zoom and selection. */
export function attachMapGestures(root, { commit, reset }) {
  const pointers = new Map(); // pointerId -> {x, y}
  let svg = null;
  let pinchDist = null;
  let travelled = 0;
  let moved = false;
  let suppressClick = false;
  let lastTap = 0;

  const finish = () => {
    if (!svg) return;
    const full = fullOf(svg);
    const view = viewOf(svg);
    commit(isZoomed(view, full) ? view : null);
  };

  root.addEventListener('pointerdown', (e) => {
    const target = e.target.closest?.('svg.cs-map');
    if (!target) return;
    if (pointers.size === 0) {
      svg = target;
      travelled = 0;
      moved = false;
    }
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      pinchDist = dist(a, b);
    }
  });

  root.addEventListener('pointermove', (e) => {
    const prev = pointers.get(e.pointerId);
    if (!prev || !svg) return;
    const cur = { x: e.clientX, y: e.clientY };
    pointers.set(e.pointerId, cur);
    const full = fullOf(svg);
    const view = viewOf(svg);
    const rect = svg.getBoundingClientRect();
    if (pointers.size === 2 && pinchDist) {
      const [a, b] = [...pointers.values()];
      const d = dist(a, b);
      const mid = clientToMap(view, rect, (a.x + b.x) / 2, (a.y + b.y) / 2);
      moved = true;
      paint(svg, zoomAbout(view, full, d / pinchDist, mid.x, mid.y));
      pinchDist = d;
      return;
    }
    if (pointers.size !== 1 || !isZoomed(view, full)) return;
    travelled += Math.hypot(cur.x - prev.x, cur.y - prev.y);
    if (travelled < TAP_MOVE_PX) return;
    if (!moved) svg.setPointerCapture?.(e.pointerId); // only a real drag captures, so taps still reach their sector
    moved = true;
    const k = pixelsPerUnit(view, rect);
    paint(svg, panBy(view, full, -(cur.x - prev.x) / k, -(cur.y - prev.y) / k));
  });

  const release = (e) => {
    if (!pointers.delete(e.pointerId)) return;
    pinchDist = null;
    if (pointers.size > 0) return;
    if (moved) {
      suppressClick = true;
      setTimeout(() => { suppressClick = false; }, 60);
      finish();
    } else if (e.type === 'pointerup') {
      const now = Date.now();
      if (now - lastTap < DOUBLE_TAP_MS) {
        lastTap = 0;
        suppressClick = true;
        setTimeout(() => { suppressClick = false; }, 60);
        reset();
      } else {
        lastTap = now;
      }
    }
    svg = null;
  };
  root.addEventListener('pointerup', release);
  root.addEventListener('pointercancel', release);

  root.addEventListener('click', (e) => {
    if (!suppressClick) return;
    suppressClick = false;
    e.stopImmediatePropagation();
    e.preventDefault();
  }, true);

  root.addEventListener('wheel', (e) => {
    const target = e.target.closest?.('svg.cs-map');
    if (!target) return;
    const full = fullOf(target);
    const view = viewOf(target);
    if (!(e.ctrlKey || e.metaKey || isZoomed(view, full))) return; // plain scrolling still scrolls the page
    e.preventDefault();
    const at = clientToMap(view, target.getBoundingClientRect(), e.clientX, e.clientY);
    const next = zoomAbout(view, full, Math.exp(-e.deltaY * WHEEL_STEP), at.x, at.y);
    paint(target, clampView(next, full));
    svg = target;
    finish();
    svg = null;
  }, { passive: false });
}
