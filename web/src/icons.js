// Small, hand-authored single-color line icons for session types -- these
// replace the plain colored `.dot` square that used to be the only visual
// distinction between session types on the Plan tab (Andrew, 2026-09-17:
// "switch from color squares to a graphic ... can be simple, single
// color"). Deliberately simple 24x24 stroke-based glyphs (Feather-icon
// convention: `stroke="currentColor"`, `fill="none"` except where a shape
// reads better filled, e.g. the recovery crescent) -- no illustration, no
// gradients, no external icon library/CDN dependency. The caller sets
// color via the wrapping element's CSS `color`, same pattern the old dot's
// `background:var(--c-x)` used.
//
// Keyed by `plan.js`'s `sessionIconKey` output: the real `Sport` values
// (`src/sports.js`) plus the two heuristic-detected kinds this pass added
// (`nutrition`, `yoga` -- see that module for why those aren't real Sport
// values). A key with no entry here (unrecognized sport, or the registry
// gains a new sport before this file catches up) renders no icon at all --
// `renderSessionIcon` returns null and callers fall back to the original
// plain colored dot, exactly like `sportColorVar`'s own `?? null` graceful
// degradation already works for color.
const ICON_PATHS = {
  swim_pool: '<path d="M2 9.5c1.8-2.2 4-2.2 6 0s4.2 2.2 6 0 4-2.2 6 0" />'
    + '<path d="M2 15c1.8-2.2 4-2.2 6 0s4.2 2.2 6 0 4-2.2 6 0" />',
  swim_ow: '<path d="M2 9.5c1.8-2.2 4-2.2 6 0s4.2 2.2 6 0 4-2.2 6 0" />'
    + '<path d="M2 15c1.8-2.2 4-2.2 6 0s4.2 2.2 6 0 4-2.2 6 0" />',
  bike: '<circle cx="5.5" cy="17.5" r="3.5" />'
    + '<circle cx="18.5" cy="17.5" r="3.5" />'
    + '<path d="M15 6a1 1 0 100-2 1 1 0 000 2zM12 17.5V14l-3-3 4-3 2 3h2" />',
  strength: '<path d="M2 9v6M5 7v10M19 7v10M22 9v6M5 12h14" />',
  recovery: '<path fill="currentColor" stroke="none" '
    + 'd="M21 12.79A9 9 0 1111.21 3a7 7 0 009.79 9.79z" />',
  cross_train: '<path d="M4 8l6 4-6 4M20 8l-6 4 6 4M10 12h4" />',
  // Pre-event fueling-plan session (see plan.js's isFuelingPlanSession) --
  // a simple bottle silhouette.
  nutrition: '<path d="M9 2h6M10 2v3.2c0 .5-.2 1-.6 1.4L8 8c-.6.6-1 1.5-1 2.4V20a2 2 0 002 2h6a2 2 0 002-2v-9.6c0-.9-.4-1.8-1-2.4l-1.4-1.4c-.4-.4-.6-.9-.6-1.4V2" />'
    + '<path d="M7 14h10" />',
  // Free-text-detected yoga/mobility session (see plan.js's
  // isYogaSession) -- a simple seated figure.
  yoga: '<circle cx="12" cy="4" r="2" />'
    + '<path d="M12 6v5M6 21l4-6h4l4 6M6.5 13h11" />',
};

/** The inner `<svg>` markup for `key` (one of `ICON_PATHS`' keys above),
 * or `null` for any key with no icon defined -- callers must fall back to
 * the plain colored dot in that case, never render nothing/broken markup.
 * `className` is applied to the `<svg>` itself so CSS can size/align it
 * without this module needing any DOM/layout knowledge of its own. */
export function renderSessionIcon(key, className = 'session-icon') {
  const paths = ICON_PATHS[key];
  if (!paths) return null;
  return `<svg class="${className}" viewBox="0 0 24 24" width="16" height="16" `
    + 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
    + `stroke-linejoin="round" aria-hidden="true">${paths}</svg>`;
}
