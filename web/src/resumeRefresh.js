// Refresh-on-resume gate. A desktop PWA can sit open for hours: the workout list, plan and load
// were only fetched at boot (or when empty), so newly synced rides and coach plan changes never
// appeared until the app was restarted (reported 2026-10-18). On returning to the app we now run a
// cheap conditional check (If-None-Match -> 304, see api.js), so the gate is only a short debounce
// that keeps the focus + visibilitychange pair (and rapid window flipping) from double-firing.
export const RESUME_REFRESH_MIN_GAP_MS = 15 * 1000;

/** True when the app has just become visible and enough time passed since the last check. */
export function shouldRefreshOnResume({ visible, online, configured, lastCheckedAt, now, minGapMs = RESUME_REFRESH_MIN_GAP_MS }) {
  if (!visible || !online || !configured) return false;
  if (lastCheckedAt === null || lastCheckedAt === undefined) return true;
  return now - lastCheckedAt >= minGapMs;
}
