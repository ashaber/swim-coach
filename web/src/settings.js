// Pure localStorage helpers for the backend URL + session token. Kept
// separate from api.js (which does the actual network calls) so the storage
// round-trip is trivially unit-testable without mocking fetch.
//
// `token` used to be a manually-pasted SHARED bearer token (the "paste-
// token" auth-lite login from ROADMAP.md). It's now a per-user SESSION token
// minted by POST /api/auth/google and machine-set by main.js after a Google
// sign-in (see identity.js's signIn) -- nothing in this module changes to
// support that; every call site already just reads/writes `token`. See
// SETTINGS_SCHEMA_VERSION below for the one thing that *does* need to change
// because of it: dropping any token cached under the old meaning.

const STORAGE_KEY = 'swimcoach_settings';

// Pre-fills the live Cloud Run backend on first run -- still fully
// editable/clearable in Settings, and once anything is explicitly saved
// (even back to '') that choice is respected instead of re-defaulting.
export const DEFAULT_BASE_URL = 'https://swim-coach-api-445273334913.us-central1.run.app';

// Bumped when the *meaning* of a stored field changes such that an old
// cached value would misbehave under new code, not just when a new field is
// added. Bumped here (1 -> 2) because pre-cutover builds stored a manually-
// pasted SHARED bearer token in `token`; after the Google-sign-in cutover,
// `token` means a per-user Google-minted SESSION token instead. The backend
// still accepts that old shared token as a valid (service-level) credential,
// so without this bump it would keep silently authenticating every request
// as that legacy credential forever -- completely bypassing the new Google
// sign-in gate this feature exists to add. On a version mismatch, only
// `token` is dropped (forcing one Google re-sign-in, seamless since every
// current user is already allowlisted) -- `baseUrl` is harmless to keep.
const SETTINGS_SCHEMA_VERSION = 2;

export function loadSettings(storage = localStorage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return { baseUrl: DEFAULT_BASE_URL, token: '' };
    const parsed = JSON.parse(raw);
    const baseUrl = typeof parsed.baseUrl === 'string' ? parsed.baseUrl : DEFAULT_BASE_URL;
    const isCurrentVersion = parsed.version === SETTINGS_SCHEMA_VERSION;
    const token = isCurrentVersion && typeof parsed.token === 'string' ? parsed.token : '';
    return { baseUrl, token };
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
    storage.setItem(STORAGE_KEY, JSON.stringify({ ...clean, version: SETTINGS_SCHEMA_VERSION }));
  } catch {
    // localStorage unavailable -- settings just won't persist across reloads
  }
  return clean;
}

// Requires a signed-in identity (see src/identity.js) in addition to the
// backend URL + session token -- every write/chat/plan feature needs both,
// and the UI shouldn't let anyone act as an athlete before Google Sign-In
// has resolved (and the backend has minted a session for) one.
export function isConfigured(settings, identity) {
  return !!(settings?.baseUrl && settings?.token && identity);
}
