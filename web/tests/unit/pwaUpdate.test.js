import { describe, it, expect, vi } from 'vitest';
import {
  createPwaUpdateState, markNeedRefresh, markOfflineReady,
  dismissNeedRefresh, dismissOfflineReady,
  shouldShowReloadBanner, shouldShowOfflineReadyNote, triggerUpdate,
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
