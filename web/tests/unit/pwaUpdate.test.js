import { describe, it, expect, vi } from 'vitest';
import {
  createPwaUpdateState, markNeedRefresh, markOfflineReady,
  dismissNeedRefresh, dismissOfflineReady,
  shouldShowReloadBanner, shouldShowOfflineReadyNote, triggerUpdate,
  startCheck, finishCheck, shouldCheckOnResume, checkForUpdate, UPDATE_CHECK_INTERVAL_MS,
} from '../../src/pwaUpdate.js';

describe('pwaUpdate state', () => {
  it('starts with nothing to show', () => {
    const state = createPwaUpdateState();
    expect(shouldShowReloadBanner(state)).toBe(false);
    expect(shouldShowOfflineReadyNote(state)).toBe(false);
  });

  it('shows the reload banner once onNeedRefresh fires', () => {
    const state = markNeedRefresh(createPwaUpdateState());
    expect(shouldShowReloadBanner(state)).toBe(true);
  });

  it('hides the reload banner once dismissed', () => {
    let state = markNeedRefresh(createPwaUpdateState());
    state = dismissNeedRefresh(state);
    expect(shouldShowReloadBanner(state)).toBe(false);
  });

  it('re-shows the reload banner on a fresh markNeedRefresh even after a prior dismissal', () => {
    let state = markNeedRefresh(createPwaUpdateState());
    state = dismissNeedRefresh(state);
    state = markNeedRefresh(state);
    expect(shouldShowReloadBanner(state)).toBe(true);
  });

  it('shows the offline-ready note once onOfflineReady fires', () => {
    const state = markOfflineReady(createPwaUpdateState());
    expect(shouldShowOfflineReadyNote(state)).toBe(true);
  });

  it('hides the offline-ready note once dismissed', () => {
    let state = markOfflineReady(createPwaUpdateState());
    state = dismissOfflineReady(state);
    expect(shouldShowOfflineReadyNote(state)).toBe(false);
  });

  it('the reload banner takes priority over the offline-ready note if both are somehow set', () => {
    let state = markOfflineReady(createPwaUpdateState());
    state = markNeedRefresh(state);
    expect(shouldShowReloadBanner(state)).toBe(true);
    expect(shouldShowOfflineReadyNote(state)).toBe(false);
  });
});

describe('triggerUpdate', () => {
  it('calls the injected updateSW callback with true (activate + reload)', () => {
    const updateSW = vi.fn();
    triggerUpdate(updateSW);
    expect(updateSW).toHaveBeenCalledWith(true);
  });

  it('is a no-op when no updateSW callback is available (registerSW never ran)', () => {
    expect(() => triggerUpdate(undefined)).not.toThrow();
    expect(() => triggerUpdate(null)).not.toThrow();
  });
});

describe('update check state', () => {
  it('walks idle -> checking -> latest', () => {
    let s = createPwaUpdateState();
    expect(s.check).toBe('idle');
    s = startCheck(s);
    expect(s.check).toBe('checking');
    s = finishCheck(s, 'latest');
    expect(s.check).toBe('latest');
  });

  it('maps outcomes: update -> updating, error -> error', () => {
    expect(finishCheck(startCheck(createPwaUpdateState()), 'update').check).toBe('updating');
    expect(finishCheck(startCheck(createPwaUpdateState()), 'error').check).toBe('error');
  });

  it('a fresh needRefresh clears a stale "latest" result', () => {
    const s = markNeedRefresh(finishCheck(createPwaUpdateState(), 'latest'));
    expect(s.check).toBe('idle');
  });
});

describe('shouldCheckOnResume', () => {
  const base = { now: 1_000_000_000, lastCheckAt: 0, online: true, hasRegistration: true };
  it('checks when never checked', () => {
    expect(shouldCheckOnResume(base)).toBe(true);
  });
  it('throttles within the interval', () => {
    expect(shouldCheckOnResume({ ...base, lastCheckAt: base.now - UPDATE_CHECK_INTERVAL_MS + 1 })).toBe(false);
  });
  it('checks once the interval has elapsed', () => {
    expect(shouldCheckOnResume({ ...base, lastCheckAt: base.now - UPDATE_CHECK_INTERVAL_MS })).toBe(true);
  });
  it('never checks offline or without a registration', () => {
    expect(shouldCheckOnResume({ ...base, online: false })).toBe(false);
    expect(shouldCheckOnResume({ ...base, hasRegistration: false })).toBe(false);
  });
});

describe('checkForUpdate', () => {
  it('returns unsupported without a registration', async () => {
    expect(await checkForUpdate(null)).toBe('unsupported');
  });
  it('returns latest when nothing is waiting or installing', async () => {
    const reg = { update: vi.fn().mockResolvedValue(undefined), waiting: null, installing: null };
    expect(await checkForUpdate(reg)).toBe('latest');
    expect(reg.update).toHaveBeenCalled();
  });
  it('returns update when a worker is waiting', async () => {
    const reg = { update: vi.fn().mockResolvedValue(undefined), waiting: {}, installing: null };
    expect(await checkForUpdate(reg)).toBe('update');
  });
  it('waits for an installing worker to finish installing', async () => {
    const listeners = {};
    const installing = {
      state: 'installing',
      addEventListener: (_t, fn) => { listeners.fn = fn; },
      removeEventListener: () => {},
    };
    const reg = { update: vi.fn().mockResolvedValue(undefined), waiting: null, installing };
    const p = checkForUpdate(reg, { installTimeoutMs: 1000 });
    await Promise.resolve(); await Promise.resolve();
    installing.state = 'installed';
    reg.waiting = installing;
    listeners.fn();
    expect(await p).toBe('update');
  });
  it('returns error when update() rejects', async () => {
    const reg = { update: vi.fn().mockRejectedValue(new Error('net')), waiting: null, installing: null };
    expect(await checkForUpdate(reg)).toBe('error');
  });
});
