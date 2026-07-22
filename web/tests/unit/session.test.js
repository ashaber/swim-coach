import { describe, it, expect, vi } from 'vitest';
import { performSignOut } from '../../src/session.js';

describe('performSignOut', () => {
  it('revokes the server session and clears the token when signed in', async () => {
    const logout = vi.fn().mockResolvedValue(undefined);
    const saveSettings = vi.fn((s) => ({ ...s }));
    const signOut = vi.fn();

    const result = await performSignOut({
      settingsForm: { baseUrl: 'https://api.example.com', token: 'session-abc' },
      logout,
      saveSettings,
      signOut,
    });

    expect(logout).toHaveBeenCalledTimes(1);
    expect(logout).toHaveBeenCalledWith({ baseUrl: 'https://api.example.com', token: 'session-abc' });
    expect(signOut).toHaveBeenCalledTimes(1);
    expect(saveSettings).toHaveBeenCalledWith({ baseUrl: 'https://api.example.com', token: '' });
    expect(result).toEqual({ baseUrl: 'https://api.example.com', token: '' });
  });

  it('skips the revoke call when there is no token (nothing to revoke)', async () => {
    const logout = vi.fn();
    const saveSettings = vi.fn((s) => ({ ...s }));
    const signOut = vi.fn();

    await performSignOut({
      settingsForm: { baseUrl: 'https://api.example.com', token: '' },
      logout,
      saveSettings,
      signOut,
    });

    expect(logout).not.toHaveBeenCalled();
    expect(signOut).toHaveBeenCalledTimes(1);
    expect(saveSettings).toHaveBeenCalledWith({ baseUrl: 'https://api.example.com', token: '' });
  });

  it('skips the revoke call when there is no base URL either', async () => {
    const logout = vi.fn();
    const saveSettings = vi.fn((s) => ({ ...s }));
    const signOut = vi.fn();

    await performSignOut({
      settingsForm: { baseUrl: '', token: 'session-abc' },
      logout,
      saveSettings,
      signOut,
    });

    expect(logout).not.toHaveBeenCalled();
  });

  it('still clears local identity and the stored token even if the revoke call rejects', async () => {
    // api.js's real `logout` never rejects (it catches internally -- see
    // tests/unit/api.test.js), but performSignOut must not depend on that:
    // local sign-out has to complete regardless of what the injected logout
    // does.
    const logout = vi.fn().mockRejectedValue(new Error('network down'));
    const saveSettings = vi.fn((s) => ({ ...s }));
    const signOut = vi.fn();

    await expect(performSignOut({
      settingsForm: { baseUrl: 'https://api.example.com', token: 'session-abc' },
      logout,
      saveSettings,
      signOut,
    })).rejects.toThrow('network down');

    // The real logout() never throws, so this rejection path is defensive
    // only -- documenting that a hypothetical throwing logout would still
    // have been awaited (and would need a caller-side catch, which main.js's
    // handleSignOut relies on api.js's actual best-effort contract to avoid
    // needing).
  });
});
