import { describe, it, expect } from 'vitest';
import { shouldRefreshOnResume, RESUME_REFRESH_MAX_AGE_MS } from '../../src/resumeRefresh.js';

const base = { visible: true, online: true, configured: true, lastLoadedAt: 0, now: RESUME_REFRESH_MAX_AGE_MS + 1 };

describe('shouldRefreshOnResume', () => {
  it('refreshes when the app comes back after the data went stale', () => {
    expect(shouldRefreshOnResume(base)).toBe(true);
  });

  it('skips a quick tab-away so flipping windows does not refetch every time', () => {
    expect(shouldRefreshOnResume({ ...base, now: RESUME_REFRESH_MAX_AGE_MS - 1 })).toBe(false);
  });

  it('refreshes when nothing has been loaded yet', () => {
    expect(shouldRefreshOnResume({ ...base, lastLoadedAt: null, now: 5 })).toBe(true);
  });

  it('never refreshes while hidden, offline or unconfigured', () => {
    expect(shouldRefreshOnResume({ ...base, visible: false })).toBe(false);
    expect(shouldRefreshOnResume({ ...base, online: false })).toBe(false);
    expect(shouldRefreshOnResume({ ...base, configured: false })).toBe(false);
  });
});
