import { describe, it, expect, beforeEach } from 'vitest';
import { loadSettings, saveSettings, isConfigured, DEFAULT_BASE_URL } from '../../src/settings.js';

function makeFakeStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  };
}

describe('settings persistence', () => {
  let storage;
  beforeEach(() => {
    storage = makeFakeStorage();
  });

  it('defaults to the live Cloud Run backend URL and an empty token when nothing is stored', () => {
    expect(loadSettings(storage)).toEqual({ baseUrl: DEFAULT_BASE_URL, token: '' });
  });

  it('respects an explicitly saved empty base URL instead of re-defaulting', () => {
    saveSettings({ baseUrl: '', token: 't' }, storage);
    expect(loadSettings(storage)).toEqual({ baseUrl: '', token: 't' });
  });

  it('round-trips a trimmed base URL and token', () => {
    saveSettings({ baseUrl: '  http://localhost:8000/  ', token: '  secret-token  ' }, storage);
    expect(loadSettings(storage)).toEqual({ baseUrl: 'http://localhost:8000', token: 'secret-token' });
  });

  it('strips trailing slashes from the base URL', () => {
    saveSettings({ baseUrl: 'https://api.example.com///', token: 't' }, storage);
    expect(loadSettings(storage).baseUrl).toBe('https://api.example.com');
  });

  it('recovers from corrupt stored JSON', () => {
    storage.setItem('swimcoach_settings', '{{{not json');
    expect(loadSettings(storage)).toEqual({ baseUrl: DEFAULT_BASE_URL, token: '' });
  });

  it('keeps a token saved under the current schema version (round-trip via saveSettings)', () => {
    saveSettings({ baseUrl: 'https://api.example.com', token: 'session-tok' }, storage);
    expect(loadSettings(storage)).toEqual({ baseUrl: 'https://api.example.com', token: 'session-tok' });
  });

  it('drops a stale pre-cutover token (no version field) but keeps the base URL', () => {
    // Simulates a browser that still has the OLD manually-pasted shared
    // bearer token cached from before the Google-sign-in switch -- see
    // settings.js's SETTINGS_SCHEMA_VERSION doc comment for why this must
    // not silently keep authenticating as that legacy credential.
    storage.setItem(
      'swimcoach_settings',
      JSON.stringify({ baseUrl: 'https://old.example.com', token: 'old-shared-token' }),
    );
    expect(loadSettings(storage)).toEqual({ baseUrl: 'https://old.example.com', token: '' });
  });

  it('drops a token saved under an older explicit schema version too', () => {
    storage.setItem(
      'swimcoach_settings',
      JSON.stringify({ baseUrl: 'https://old.example.com', token: 'old-shared-token', version: 1 }),
    );
    expect(loadSettings(storage)).toEqual({ baseUrl: 'https://old.example.com', token: '' });
  });
});

describe('isConfigured', () => {
  const identity = { name: 'Andrew', athlete: 'andrew', role: 'coach' };

  it('is false when either the base URL or token is missing, even with an identity', () => {
    expect(isConfigured({ baseUrl: '', token: '' }, identity)).toBe(false);
    expect(isConfigured({ baseUrl: 'http://x', token: '' }, identity)).toBe(false);
    expect(isConfigured({ baseUrl: '', token: 't' }, identity)).toBe(false);
  });

  it('is false without a signed-in identity, even with a base URL and token', () => {
    expect(isConfigured({ baseUrl: 'http://x', token: 't' }, null)).toBe(false);
    expect(isConfigured({ baseUrl: 'http://x', token: 't' })).toBe(false);
  });

  it('is true once the base URL, token, and a signed-in identity are all set', () => {
    expect(isConfigured({ baseUrl: 'http://x', token: 't' }, identity)).toBe(true);
  });
});
