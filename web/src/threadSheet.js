// Which scoped-thread sheet (if any) is open. A workout or planned session's chat lives in a
// full-screen bottom sheet (views.js `renderThreadSheetShell`), opened from a button pinned to the
// detail page. One sheet at a time, identified by a key such as `workout:<id>`, `session:<id>`
// or `roster-workout:<id>`; each detail view renders its sheet only when its own key is open, so
// a stale key can never show another record's thread. Kept as a tiny module (not threaded through
// every render signature) so views.js and main.js agree without a long parameter chain.

let openKey = null;

export function getOpenSheetKey() {
  return openKey;
}

export function isSheetOpen(key) {
  return openKey !== null && openKey === key;
}

export function setOpenSheetKey(key) {
  openKey = key || null;
}

export function sheetKeyFor(kind, id) {
  return `${kind}:${id}`;
}
