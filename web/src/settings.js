// Pure localStorage helpers for the backend URL + bearer token (the
// "paste-token" auth-lite login from ROADMAP.md). Kept separate from
// api.js (which does the actual network calls) so the storage round-trip
// is trivially unit-testable without mocking fetch.

const STORAGE_KEY = 'swimcoach_settings';

// Pre-fills the live Cloud Run backend on first run so the athlete only
// has to paste their bearer token -- still fully editable/clearable in
// Settings, and once anything is explicitly saved (even back to '') that
// choice is respected instead of re-defaulting.
export const DEFAULT_BASE_URL = 'https://swim-coach-api-445273334913.us-central1.run.app';

export function loadSettings(storage = localStorage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return { baseUrl: DEFAULT_BASE_URL, token: '' };
    const parsed = JSON.parse(raw);
    return {
      baseUrl: typeof parsed.baseUrl === 'string' ? parsed.baseUrl : DEFAULT_BASE_URL,
      token: typeof parsed.token === 'string' ? parsed.token : '',
    };
  } catch {
    return { baseUrl: DEFAULT_BASE_URL, token: '' };
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

// Requires a signed-in identity (see src/identity.js) in addition to the
// backend URL + token -- identity isn't a security boundary (the backend
// still only checks the shared bearer token), but the UI shouldn't let
// anyone act as an athlete before Google Sign-In has resolved one.
export function isConfigured(settings, identity) {
  return !!(settings?.baseUrl && settings?.token && identity);
}
