import { describe, it, expect, beforeEach } from 'vitest';
import { loadSettings, saveSettings, isConfigured } from '../../src/settings.js';

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

  it('defaults to empty strings when nothing is stored', () => {
    expect(loadSettings(storage)).toEqual({ baseUrl: '', token: '' });
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
    expect(loadSettings(storage)).toEqual({ baseUrl: '', token: '' });
  });
});

describe('isConfigured', () => {
  it('is false when either field is missing', () => {
    expect(isConfigured({ baseUrl: '', token: '' })).toBe(false);
    expect(isConfigured({ baseUrl: 'http://x', token: '' })).toBe(false);
    expect(isConfigured({ baseUrl: '', token: 't' })).toBe(false);
  });

  it('is true once both are set', () => {
    expect(isConfigured({ baseUrl: 'http://x', token: 't' })).toBe(true);
  });
});
