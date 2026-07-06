// Pure localStorage helpers for the backend URL + bearer token (the
// "paste-token" auth-lite login from ROADMAP.md). Kept separate from
// api.js (which does the actual network calls) so the storage round-trip
// is trivially unit-testable without mocking fetch.

const STORAGE_KEY = 'swimcoach_settings';

export function loadSettings(storage = localStorage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return { baseUrl: '', token: '' };
    const parsed = JSON.parse(raw);
    return {
      baseUrl: typeof parsed.baseUrl === 'string' ? parsed.baseUrl : '',
      token: typeof parsed.token === 'string' ? parsed.token : '',
    };
  } catch {
    return { baseUrl: '', token: '' };
  }
}

export function saveSettings(settings, storage = localStorage) {
  const clean = {
    baseUrl: (settings.baseUrl || '').trim().replace(/\/+$/, ''),
    token: (settings.token || '').trim(),
  };
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(clean));
  } catch {
    // localStorage unavailable -- settings just won't persist across reloads
  }
  return clean;
}

export function isConfigured(settings) {
  return !!(settings?.baseUrl && settings?.token);
}
