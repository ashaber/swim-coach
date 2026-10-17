// Pure viewBox maths for the course map's zoom and pan. DOM-free: mapGestures.js feeds it pointer
// positions, views.js turns the returned viewBox into the SVG attribute.
//
// A view is `{x, y, w, h}` in map units; `full` is the whole-lap view `{x:0, y:0, w, h}`.

export const MIN_ZOOM = 1;
export const MAX_ZOOM = 8;
export const SECTOR_MARGIN = 0.25; // fraction of the sector's longer side kept around it when fitting
const MIN_SECTOR_SPAN = 30; // map units: a very short sector still zooms to a useful window

/** Zoom factor of `view` relative to `full` (1 = whole lap). */
export function zoomLevel(view, full) {
  return full.w / view.w;
}

export function isZoomed(view, full) {
  return !!view && zoomLevel(view, full) > 1.01;
}

/** Keep the view's size within 1x..8x and the lap in bounds. */
export function clampView(view, full) {
  const w = Math.min(full.w, Math.max(full.w / MAX_ZOOM, view.w));
  const h = w * (full.h / full.w);
  const x = Math.min(full.x + full.w - w, Math.max(full.x, view.x));
  const y = Math.min(full.y + full.h - h, Math.max(full.y, view.y));
  return { x, y, w, h };
}

/** Zoom by `factor` (>1 zooms in) keeping the map point (px, py) fixed on screen. */
export function zoomAbout(view, full, factor, px, py) {
  const target = clampView({ ...view, w: view.w / factor, h: view.h / factor }, full);
  const k = target.w / view.w;
  return clampView({ x: px - (px - view.x) * k, y: py - (py - view.y) * k, w: target.w, h: target.h }, full);
}

/** Move the view by (dx, dy) map units, clamped to the lap. */
export function panBy(view, full, dx, dy) {
  return clampView({ ...view, x: view.x + dx, y: view.y + dy }, full);
}

/** Smallest view (at the map's aspect ratio) holding `bounds` plus a margin. */
export function fitBounds(bounds, full, margin = SECTOR_MARGIN) {
  const spanX = Math.max(bounds.maxX - bounds.minX, MIN_SECTOR_SPAN);
  const spanY = Math.max(bounds.maxY - bounds.minY, MIN_SECTOR_SPAN);
  const pad = Math.max(spanX, spanY) * margin;
  const aspect = full.w / full.h;
  const w = Math.max(spanX + 2 * pad, (spanY + 2 * pad) * aspect);
  const cx = (bounds.minX + bounds.maxX) / 2;
  const cy = (bounds.minY + bounds.maxY) / 2;
  const h = w / aspect;
  return clampView({ x: cx - w / 2, y: cy - h / 2, w, h }, full);
}

export function resetView(full) {
  return { ...full };
}

/** Bounds of an SVG `points` string ("x,y x,y ..."). */
export function boundsOfPoints(points) {
  const pts = points.split(' ').map((p) => p.split(',').map(Number));
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) };
}

/** Map point under a client position, honouring `preserveAspectRatio="xMidYMid meet"`.
 * `rect` is the SVG element's client rect. */
export function clientToMap(view, rect, clientX, clientY) {
  const s = Math.min(rect.width / view.w, rect.height / view.h);
  const offX = (rect.width - view.w * s) / 2;
  const offY = (rect.height - view.h * s) / 2;
  return { x: view.x + (clientX - rect.left - offX) / s, y: view.y + (clientY - rect.top - offY) / s };
}

/** Screen pixels per map unit for the current view. */
export function pixelsPerUnit(view, rect) {
  return Math.min(rect.width / view.w, rect.height / view.h);
}

export function viewBoxAttr(view) {
  const r = (v) => Number(v.toFixed(2));
  return `${r(view.x)} ${r(view.y)} ${r(view.w)} ${r(view.h)}`;
}
