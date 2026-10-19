// Refresh-on-resume gate. A desktop PWA can sit open for hours: the workout list, plan and
// load were only fetched at boot (or when empty), so newly synced rides never appeared until
// the app was restarted (reported 2026-10-18). On returning to the app, refetch when the data
// is older than this.
export const RESUME_REFRESH_MAX_AGE_MS = 2 * 60 * 1000;

/** True when the app has just become visible and its data is stale enough to refetch. */
export function shouldRefreshOnResume({ visible, online, configured, lastLoadedAt, now, maxAgeMs = RESUME_REFRESH_MAX_AGE_MS }) {
  if (!visible || !online || !configured) return false;
  if (lastLoadedAt === null || lastLoadedAt === undefined) return true;
  return now - lastLoadedAt >= maxAgeMs;
}
