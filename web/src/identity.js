// Lightweight, CLIENT-SIDE-ONLY identity for the swim-coach PWA.
//
// This is IDENTITY FOR UX, NOT A SECURITY BOUNDARY. The backend still
// accepts any `?athlete=<slug>` (and `athlete` in the chat body) behind the
// single shared bearer token -- see web/src/api.js and CLAUDE.md/ROADMAP.md.
// The Google ID token's *signature* is never verified here (no server round
// trip, no crypto) -- we only base64url-decode its payload to read `email`
// client-side. Real per-user enforcement (RLS, server-side token
// verification) is deferred; do not treat this module as authorization.
//
// Offline caveat: the *first* sign-in needs network (to load Google's GSI
// script and obtain an ID token). The resolved identity is then persisted to
// localStorage so subsequent app loads restore it (via `currentIdentity`)
// without a network round trip -- the offline-first app keeps working after
// that first sign-in.

import log from './log.js';

const STORAGE_KEY = 'swimcoach_identity';
const GSI_SCRIPT_SRC = 'https://accounts.google.com/gsi/client';

/** email (lowercase) -> {athlete, role}. Looked up by `resolveIdentity`
 * after lowercase-normalizing whatever email the ID token contains.
 *
 * Both users are role 'athlete' for now: Andrew wants to experience the
 * system as an athlete in his own sandbox ('andrew'), separate from Renee's
 * data. A 'coach' role -- with cross-athlete access -- is a deliberate later
 * addition (the expert-mode toggle already keys off role === 'coach'). */
const EMAIL_IDENTITY_MAP = {
  'andrewshaber@gmail.com': { athlete: 'andrew', role: 'athlete' },
  'kline.renee@gmail.com': { athlete: 'renee', role: 'athlete' },
  'curry.mtb@gmail.com': { athlete: 'tim', role: 'athlete' },
};

/**
 * Build-time public OAuth client ID for Google Identity Services. Client IDs
 * are not secret (they're embedded in front-end code by design), so this is
 * safe to bake into the static build. Falls back to a clearly-labeled
 * placeholder so `npm run build` succeeds before Andrew registers a real one
 * at https://console.cloud.google.com/apis/credentials -- set
 * VITE_GOOGLE_CLIENT_ID in the build environment (e.g. the GitHub Pages
 * deploy workflow's env / repo secrets) to the real value.
 */
export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID
  || 'REPLACE_WITH_GOOGLE_OAUTH_CLIENT_ID.apps.googleusercontent.com';

/**
 * Decodes (does NOT verify) the payload segment of a JWT / Google ID token.
 * There is no signature check here -- see the module-level warning above.
 * Returns null for anything that isn't a well-formed 3-segment token or that
 * doesn't decode to JSON (malformed tokens must never throw into caller code).
 */
export function decodeJwtPayload(token) {
  if (typeof token !== 'string') return null;
  const parts = token.split('.');
  if (parts.length !== 3 || !parts[1]) return null;
  try {
    const base64 = parts[1].replace(/-/g, '+').replace(/_/g, '/');
    const padded = base64.padEnd(base64.length + ((4 - (base64.length % 4)) % 4), '=');
    const binary = atob(padded);
    const percentEncoded = binary
      .split('')
      .map((c) => `%${c.charCodeAt(0).toString(16).padStart(2, '0')}`)
      .join('');
    return JSON.parse(decodeURIComponent(percentEncoded));
  } catch (err) {
    log.error('identity.jwt_decode_failed', { error: err.message });
    return null;
  }
}

/**
 * Maps a (lowercase-normalized) email to {email, athlete, role}, or null if
 * the email isn't in EMAIL_IDENTITY_MAP -- an unrecognized email is treated
 * as "not an authorized user", not as a fallback athlete.
 */
export function resolveIdentity(email) {
  if (typeof email !== 'string' || !email.trim()) return null;
  const normalized = email.trim().toLowerCase();
  const entry = EMAIL_IDENTITY_MAP[normalized];
  if (!entry) return null;
  return { email: normalized, athlete: entry.athlete, role: entry.role };
}

/** Restores a previously-resolved identity from localStorage, or null if
 * none is stored / the stored value is corrupt or missing required fields. */
export function loadIdentity(storage = localStorage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.athlete !== 'string' || typeof parsed.email !== 'string') return null;
    return { email: parsed.email, athlete: parsed.athlete, role: parsed.role ?? 'athlete' };
  } catch {
    return null;
  }
}

export function saveIdentity(identity, storage = localStorage) {
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(identity));
  } catch {
    // localStorage unavailable (private mode quota, etc.) -- identity just
    // won't persist across reloads; the in-memory session still works.
  }
  return identity;
}

export function clearIdentity(storage = localStorage) {
  try {
    storage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

/** Restore-on-load entry point: the identity to use right now, without any
 * network round trip. main.js calls this at startup the same way it calls
 * loadSettings()/loadChatSession(). */
export function currentIdentity(storage = localStorage) {
  return loadIdentity(storage);
}

// --- Thin GIS/DOM glue -------------------------------------------------------
// Everything above is pure and unit-tested directly (tests/unit/identity.test.js).
// Below is glue around Google Identity Services' script + button -- not
// practical to unit test without a full GIS mock, so it's kept as small as
// possible: load the script once, initialize with GOOGLE_CLIENT_ID, decode +
// resolve the credential it hands back, persist on success, and call the
// caller's `onIdentity` either way so the UI can react (including the
// "not an authorized user" case, where `onIdentity(null)` fires).

let scriptLoadPromise = null;

function loadGsiScript() {
  if (scriptLoadPromise) return scriptLoadPromise;
  scriptLoadPromise = new Promise((resolve, reject) => {
    if (window.google?.accounts?.id) {
      resolve();
      return;
    }
    const script = document.createElement('script');
    script.src = GSI_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('failed to load Google Identity Services script'));
    document.head.appendChild(script);
  });
  return scriptLoadPromise;
}

/**
 * Loads the GSI script, initializes it with GOOGLE_CLIENT_ID, and renders
 * the Sign-In button into `buttonEl` (if given). `onIdentity` fires once per
 * credential response with either the resolved {email, athlete, role} (and
 * the identity has already been persisted via saveIdentity by then) or null
 * when the signed-in Google account's email isn't in EMAIL_IDENTITY_MAP.
 *
 * `onIdentity` is deliberately NOT called if the GSI script itself never
 * loads (offline / blocked) -- that's not a user decision, so callers
 * calling signIn() again on every re-render (e.g. main.js's Settings tab,
 * signed out) must never turn a script-load failure into a repeating
 * onIdentity(null) -> render() -> signIn() -> onIdentity(null) loop. A
 * failed load is logged and just leaves the sign-in button inert; a real
 * "not an authorized user" is only ever reported from an actual credential
 * response below, which only happens once per real sign-in attempt.
 */
export async function signIn({ buttonEl, onIdentity } = {}) {
  try {
    await loadGsiScript();
  } catch (err) {
    log.error('identity.gsi_script_load_failed', { error: err.message });
    return;
  }
  const { google } = window;
  if (!google?.accounts?.id) {
    log.error('identity.gsi_unavailable', {});
    return;
  }
  google.accounts.id.initialize({
    client_id: GOOGLE_CLIENT_ID,
    callback: (response) => {
      const payload = decodeJwtPayload(response.credential);
      const identity = payload ? resolveIdentity(payload.email) : null;
      if (identity) {
        saveIdentity(identity);
        log.info('identity.sign_in_success', { athlete: identity.athlete, role: identity.role });
      } else {
        log.warn('identity.sign_in_unauthorized', {});
      }
      onIdentity?.(identity);
    },
  });
  if (buttonEl) {
    google.accounts.id.renderButton(buttonEl, { theme: 'outline', size: 'large', width: 280 });
  } else {
    google.accounts.id.prompt();
  }
}

/** Clears the persisted identity and best-effort tells GIS to stop
 * auto-selecting the previous account on the next sign-in attempt. */
export function signOut(storage = localStorage) {
  clearIdentity(storage);
  try {
    window.google?.accounts?.id?.disableAutoSelect();
  } catch {
    // ignore -- best-effort, GIS may not be loaded yet
  }
  log.info('identity.sign_out', {});
}
