// Pure logic for the race-day overlay's navigation: which timeline row to lock at the top of the
// scroller, and how a horizontal touch gesture maps onto the Checklist / Timeline tabs.

export const SWIPE_MIN_DX = 60;
export const SWIPE_AXIS_RATIO = 1.5;
export const SWIPE_EDGE_PX = 20;

/** Id of the row to pin at the top: the event BEFORE the current one, or the current one itself
 * when it is first. Null when there is no current event (position not meaningful) or the current
 * id is not in the clock. */
export function timelineAnchorId(clock, currentId) {
  if (!currentId) return null;
  const idx = clock.findIndex((e) => e.id === currentId);
  if (idx < 0) return null;
  return clock[Math.max(0, idx - 1)].id;
}

/** 'left' | 'right' | null for a one-finger touch from (startX, startY) to (endX, endY) on a screen
 * `width` px wide. Starts inside the iOS edge-back zone never count; so do small or mostly
 * vertical movements (a tap, or a scroll). */
export function classifySwipe({ startX, startY, endX, endY, width }) {
  if (startX < SWIPE_EDGE_PX || startX > width - SWIPE_EDGE_PX) return null;
  const dx = endX - startX;
  const dy = endY - startY;
  if (Math.abs(dx) <= SWIPE_MIN_DX || Math.abs(dx) <= SWIPE_AXIS_RATIO * Math.abs(dy)) return null;
  return dx < 0 ? 'left' : 'right';
}

/** The tab a swipe leads to, or null. Left: Checklist -> Timeline; right: Timeline -> Checklist. */
export function swipeTargetTab(tab, direction) {
  if (direction === 'left' && tab === 'list') return 'timeline';
  if (direction === 'right' && tab === 'timeline') return 'list';
  return null;
}
