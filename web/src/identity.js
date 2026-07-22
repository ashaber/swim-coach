// Google sign-in identity for the swim-coach PWA.
//
// Identity is now resolved SERVER-SIDE: the raw Google ID token GSI hands
// back is sent to POST /api/auth/google (see api.js's exchangeGoogleToken),
// which verifies its signature/audience/issuer/expiry and looks the email up
// in the backend's own allowlist -- this module never decodes or trusts the
// token itself. The backend's response (`{token, athlete, name, role,
// expires_at}`) is the sole source of truth for {athlete, name, role}; the
// minted session `token` is persisted into settings.js's storage (by
// main.js), not here.
//
// Offline caveat: the *first* sign-in needs network (to load Google's GSI
// script and exchange the ID token for a session). The resolved identity is
// then persisted to localStorage so subsequent app loads restore it (via
// `currentIdentity`) without a network round trip -- the offline-first app
// keeps working after that first sign-in, until the session expires (there
// is no refresh endpoint by design -- an expired session just prompts a
// fresh Google sign-in, see main.js's handling of a 401 from any API call).

import log from './log.js';
import { exchangeGoogleToken, RequestAccessError } from './api.js';

const STORAGE_KEY = 'swimcoach_identity';
const GSI_SCRIPT_SRC = 'https://accounts.google.com/gsi/client';

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

/** Restores a previously-resolved identity from localStorage, or null if
 * none is stored / the stored value is corrupt or missing required fields.
 * `athlete` is the only field required to trust the stored value -- `name`
 * defaults to '' and `role` to 'athlete' if either is missing, the same
 * defensive posture as before. */
export function loadIdentity(storage = localStorage) {
  try {
    const raw = storage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed.athlete !== 'string') return null;
    return {
      name: typeof parsed.name === 'string' ? parsed.name : '',
      athlete: parsed.athlete,
      role: parsed.role ?? 'athlete',
    };
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
// possible: load the script once, initialize with GOOGLE_CLIENT_ID, exchange
// the credential it hands back for a backend session (api.js's
// exchangeGoogleToken), persist the resolved identity on success, and call
// the caller's `onIdentity` either way so the UI can react.

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
 * credential response with one of:
 *   - `{ ok: true, identity: {name, athlete, role}, token }` -- the identity
 *     has already been persisted via saveIdentity by then; `token` is the
 *     minted session token, for the caller (main.js) to persist into
 *     settings.js's storage.
 *   - `{ ok: true, onboarding: true, token }` -- the Google account is
 *     allowlisted but has no athlete yet (self-service onboarding, see
 *     backend/app/routes/auth.py's `allowed.athlete_slug is None` branch).
 *     Deliberately NOT treated as a finished sign-in: nothing is saved via
 *     saveIdentity (there's no {name, athlete, role} to save -- athlete is
 *     null), so isConfigured(settings, identity) stays false and the app
 *     can't mistake this for an ordinary signed-in session. `token` is the
 *     onboarding-scoped session token; the caller (main.js) persists it and
 *     switches into onboarding mode so the app shows the onboarding form
 *     (src/onboarding.js / views.js's renderOnboardingForm) instead of the
 *     gated tabs.
 *   - `{ ok: false, requestAccess: true, message }` -- the Google account
 *     authenticated fine but isn't allowlisted on the backend yet.
 *   - `{ ok: false, requestAccess: false, message }` -- any other failure
 *     (backend unreachable, bad/expired Google token, etc).
 *
 * `onIdentity` is deliberately NOT called if the GSI script itself never
 * loads (offline / blocked) -- that's not a user decision, so callers
 * calling signIn() again on every re-render (e.g. main.js's Settings tab,
 * signed out) must never turn a script-load failure into a repeating
 * onIdentity(...) -> render() -> signIn() -> onIdentity(...) loop. A failed
 * load is logged and just leaves the sign-in button inert; a real exchange
 * outcome is only ever reported from an actual credential response below,
 * which only happens once per real sign-in attempt.
 */
export async function signIn({ buttonEl, baseUrl, onIdentity } = {}) {
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
    callback: async (response) => {
      try {
        const session = await exchangeGoogleToken({ baseUrl, idToken: response.credential });
        if (session.onboarding) {
          // Allowlisted, no athlete yet -- see this function's doc comment's
          // second onIdentity outcome. Never saveIdentity here: there's no
          // real {name, athlete, role} to persist, and doing so would make
          // isConfigured() falsely report this onboarding-only session as a
          // fully signed-in athlete.
          log.info('identity.onboarding_session', {});
          onIdentity?.({ ok: true, onboarding: true, token: session.token });
          return;
        }
        const identity = { name: session.name, athlete: session.athlete, role: session.role };
        saveIdentity(identity);
        log.info('identity.sign_in_success', { athlete: identity.athlete, role: identity.role });
        onIdentity?.({ ok: true, identity, token: session.token });
      } catch (err) {
        const requestAccess = err instanceof RequestAccessError;
        log.warn('identity.sign_in_failed', { request_access: requestAccess, error: err.message });
        onIdentity?.({ ok: false, requestAccess, message: err.message });
      }
    },
  });
  if (buttonEl) {
    google.accounts.id.renderButton(buttonEl, { theme: 'outline', size: 'large', width: 280 });
  } else {
    google.accounts.id.prompt();
  }
}

/** Clears the persisted identity and best-effort tells GIS to stop
 * auto-selecting the previous account on the next sign-in attempt. Does NOT
 * revoke the backend session itself -- see api.js's `logout`, which main.js
 * calls separately (it needs the session token, which lives in settings.js's
 * storage, not here). */
export function signOut(storage = localStorage) {
  clearIdentity(storage);
  try {
    window.google?.accounts?.id?.disableAutoSelect();
  } catch {
    // ignore -- best-effort, GIS may not be loaded yet
  }
  log.info('identity.sign_out', {});
}
