import { describe, it, expect } from 'vitest';
import { shouldRefreshOnResume, RESUME_REFRESH_MIN_GAP_MS } from '../../src/resumeRefresh.js';

const base = { visible: true, online: true, configured: true, lastCheckedAt: 0, now: RESUME_REFRESH_MIN_GAP_MS + 1 };

describe('shouldRefreshOnResume', () => {
  it('checks for changes when the app comes back after the debounce window', () => {
    expect(shouldRefreshOnResume(base)).toBe(true);
  });

  it('debounces focus + visibilitychange pairs and rapid window flipping', () => {
    expect(shouldRefreshOnResume({ ...base, now: RESUME_REFRESH_MIN_GAP_MS - 1 })).toBe(false);
  });

  it('keeps the debounce short now that a check is a cheap conditional request', () => {
    expect(RESUME_REFRESH_MIN_GAP_MS).toBeLessThanOrEqual(30 * 1000);
  });

  it('checks when nothing has been checked yet', () => {
    expect(shouldRefreshOnResume({ ...base, lastCheckedAt: null, now: 5 })).toBe(true);
  });

  it('never checks while hidden, offline or unconfigured', () => {
    expect(shouldRefreshOnResume({ ...base, visible: false })).toBe(false);
    expect(shouldRefreshOnResume({ ...base, online: false })).toBe(false);
    expect(shouldRefreshOnResume({ ...base, configured: false })).toBe(false);
  });
});
