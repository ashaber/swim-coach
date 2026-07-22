// Pure state/reducers for the "new version available -> reload" prompt (see
// vite.config.js's VitePWA `registerType: 'prompt'`, which trades the old
// silent `autoUpdate` for this explicit flow -- an installed PWA that never
// gets tapped to reload could otherwise sit a build behind indefinitely).
//
// Kept separate from main.js so it's unit-testable without importing
// `virtual:pwa-register` -- that's a Vite build-time virtual module (see
// vite-plugin-pwa) that only resolves inside an actual Vite build/dev
// server, never under vitest (see vite.config.js's `test` block). main.js's
// own `registerSW(...)` call stays thin: wire its onNeedRefresh/
// onOfflineReady callbacks to the reducers below, and its returned
// `updateSW` function to `triggerUpdate`.

export function createPwaUpdateState() {
  return {
    needRefresh: false, needRefreshDismissed: false,
    offlineReady: false, offlineReadyDismissed: false,
  };
}

/** registerSW's onNeedRefresh fired: a new service worker is installed and
 * waiting -- show the "New version -- Reload" banner. Un-dismisses it even
 * if a previous one had been dismissed (a fresh update is worth re-surfacing). */
export function markNeedRefresh(state) {
  return { ...state, needRefresh: true, needRefreshDismissed: false };
}

/** registerSW's onOfflineReady fired: the first install finished precaching
 * everything needed to work offline. */
export function markOfflineReady(state) {
  return { ...state, offlineReady: true, offlineReadyDismissed: false };
}

/** Dismisses the reload banner without applying the update -- non-blocking,
 * per CLAUDE.md's PWA UX bar; the athlete can keep using the current build
 * and pick up the new one on a later natural reload. */
export function dismissNeedRefresh(state) {
  return { ...state, needRefreshDismissed: true };
}

/** Dismisses the subtle "ready to work offline" note. */
export function dismissOfflineReady(state) {
  return { ...state, offlineReadyDismissed: true };
}

/** Whether the "New version -- Reload" banner should currently render. */
export function shouldShowReloadBanner(state) {
  return !!state.needRefresh && !state.needRefreshDismissed;
}

/** Whether the subtle "ready to work offline" note should currently render.
 * Deliberately mutually exclusive with the reload banner in practice (a
 * fresh install fires onOfflineReady; a later update fires onNeedRefresh),
 * but both flags are independent here so a render function can't get this
 * wrong by construction. */
export function shouldShowOfflineReadyNote(state) {
  return !!state.offlineReady && !state.offlineReadyDismissed && !shouldShowReloadBanner(state);
}

/** Invokes the `updateSW` callback vite-plugin-pwa's registerSW() returns,
 * telling the waiting service worker to activate (which triggers the page
 * reload) -- factored out so main.js's click handler, and this module's own
 * test, don't need to special-case a missing callback (e.g. registerSW()
 * never having run because `'serviceWorker' in navigator` was false). */
export function triggerUpdate(updateSW) {
  if (typeof updateSW === 'function') updateSW(true);
}
