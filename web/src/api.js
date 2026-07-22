// Network layer for the Phase-2 backend: coach chat plus the write/list
// endpoints for workouts and wellness check-ins. `streamChat` does real
// streaming I/O so it isn't unit-tested directly -- e2e tests mock `fetch`
// at the browser level instead; the one piece of its real logic (parsing
// the `text/event-stream` body) is factored out to sse.js's
// `feedSSEBuffer`, which *is* unit-tested. The non-streaming
// `apiRequest`-based functions below (`postWorkout`/`listWorkouts`/
// `postWellness`/`listWellness`) are simple enough (one fetch, one JSON
// body) to unit-test directly against a mocked `global.fetch` -- see
// tests/unit/api.test.js.
//
// Deliberately uses fetch + a streaming body reader for chat, not
// EventSource -- EventSource can't send a POST body or an Authorization
// header, and the chat endpoint needs both.

import log from './log.js';
import { feedSSEBuffer } from './sse.js';

/**
 * Streams one /api/chat turn. Calls `onEvent(event)` for every parsed SSE
 * event in arrival order (see backend app/claude.py for the event union:
 * text / tool_use / done / refusal / error). Network failures and non-2xx
 * responses (auth failure, rate limit, 500s -- these come back as a plain
 * JSON `{error}` body, never as SSE, since the stream never starts) are
 * normalized into a single synthetic `{type:'error', error}` event so
 * callers only ever need one error-handling path.
 *
 * `workoutId`, when given (the workout detail view's embedded scoped chat),
 * rides along as `workout_id` -- the backend injects that workout's full
 * detail into the per-request context (see backend/app/routes/chat.py).
 * Omitted entirely for the ordinary Coach tab so its request body is
 * byte-identical to before this feature existed.
 */
export async function streamChat({
  baseUrl, token, athlete, message, history, expertMode, workoutId, onEvent, signal,
}) {
  let response;
  try {
    response = await fetch(`${baseUrl}/api/chat`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        message, history, athlete, expert_mode: !!expertMode,
        ...(workoutId ? { workout_id: workoutId } : {}),
      }),
      signal,
    });
  } catch (err) {
    log.error('chat.request_failed', { error: err.message });
    onEvent({ type: 'error', error: 'Could not reach the coach backend. Check your connection and Settings.' });
    return;
  }

  if (!response.ok) {
    const message2 = await safeErrorMessage(response);
    log.error('chat.response_not_ok', { status: response.status, error: message2 });
    // `status` rides along so main.js can tell a 401 (session token no
    // longer valid -- there's no refresh endpoint, see identity.js) apart
    // from every other failure and route back to the sign-in gate instead
    // of just showing an in-chat error bubble.
    onEvent({ type: 'error', error: message2, status: response.status });
    return;
  }

  if (!response.body) {
    // Environments without a streaming body reader (rare) -- fall back to
    // treating the whole response as unusable rather than hanging forever.
    onEvent({ type: 'error', error: 'Streaming is not supported in this browser.' });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      const chunk = decoder.decode(value, { stream: true });
      const fed = feedSSEBuffer(buffer, chunk);
      buffer = fed.remainder;
      for (const event of fed.events) onEvent(event);
    }
  } catch (err) {
    if (err.name === 'AbortError') return;
    log.error('chat.stream_read_failed', { error: err.message });
    onEvent({ type: 'error', error: 'Lost connection mid-reply.' });
  }
}

async function safeErrorMessage(response) {
  try {
    const body = await response.json();
    if (typeof body?.error === 'string') return body.error;
  } catch {
    // non-JSON error body -- fall through to the generic status-based message
  }
  if (response.status === 401) return 'Backend rejected the token -- check Settings.';
  if (response.status === 429) return 'Too many messages -- wait a moment and try again.';
  return `Backend error (${response.status}).`;
}

/**
 * Shared plumbing for the (non-streaming) write/list endpoints below.
 * Normalizes every failure mode (network failure, non-2xx, unparsable body)
 * into `{ ok: false, error }` so callers only ever need one branch. Success
 * returns `{ ok: true, data }`.
 */
async function apiRequest({ baseUrl, token, path, method = 'GET', body }) {
  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { 'Content-Type': 'application/json' } : {}),
      },
      ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
  } catch (err) {
    log.error('api.request_failed', { path, error: err.message });
    return { ok: false, error: 'Could not reach the coach backend. Check your connection and Settings.' };
  }

  if (!response.ok) {
    const message = await safeErrorMessage(response);
    log.error('api.response_not_ok', { path, status: response.status, error: message });
    // `status` rides along so main.js can single out a 401 (session token
    // no longer valid) and treat it as "session expired" -- see
    // handleUnauthorized in main.js.
    return { ok: false, error: message, status: response.status };
  }

  try {
    const data = await response.json();
    return { ok: true, data };
  } catch (err) {
    log.error('api.parse_failed', { path, error: err.message });
    return { ok: false, error: 'Unexpected response from backend.', status: response.status };
  }
}

/**
 * POST {baseUrl}/api/workouts/ingest?athlete=<slug> -- multipart upload of a
 * .fit/.tcx/.csv watch export. The backend parses it *in memory* and
 * returns the resulting WorkoutDraft (including `warnings`); it never saves
 * anything (see forms.js's `logFormFromDraft` and main.js's
 * `handleSubmitLog` for the separate confirm step that actually persists it
 * via `postWorkout`, with `source` carried through from the draft).
 *
 * Deliberately not built on the shared `apiRequest` helper above: that
 * helper always sends a JSON body with an explicit `Content-Type:
 * application/json` header, but a multipart upload needs the browser to set
 * `Content-Type: multipart/form-data; boundary=...` itself from the
 * FormData body -- setting it manually breaks the boundary. Error handling
 * (network failure / non-2xx / unparsable body) mirrors `apiRequest`'s same
 * three-branch normalization so callers get the same `{ok, error}` /
 * `{ok, data}` shape either way.
 */
export async function uploadWorkoutFile({ baseUrl, token, athlete = 'renee', file }) {
  const path = `/api/workouts/ingest?athlete=${encodeURIComponent(athlete)}`;
  const formData = new FormData();
  formData.append('file', file);

  let response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: formData,
    });
  } catch (err) {
    log.error('api.upload_failed', { path, error: err.message });
    return { ok: false, error: 'Could not reach the coach backend. Check your connection and Settings.' };
  }

  if (!response.ok) {
    const message = await safeErrorMessage(response);
    log.error('api.response_not_ok', { path, status: response.status, error: message });
    return { ok: false, error: message, status: response.status };
  }

  try {
    const data = await response.json();
    return { ok: true, data };
  } catch (err) {
    log.error('api.parse_failed', { path, error: err.message });
    return { ok: false, error: 'Unexpected response from backend.', status: response.status };
  }
}

/** POST {baseUrl}/api/workouts?athlete=<slug> -- logs a completed workout. */
export async function postWorkout({ baseUrl, token, athlete = 'renee', payload }) {
  return apiRequest({
    baseUrl, token, path: `/api/workouts?athlete=${encodeURIComponent(athlete)}`, method: 'POST', body: payload,
  });
}

/** GET {baseUrl}/api/workouts?athlete=<slug> -- lists logged workouts. */
export async function listWorkouts({ baseUrl, token, athlete = 'renee' }) {
  return apiRequest({ baseUrl, token, path: `/api/workouts?athlete=${encodeURIComponent(athlete)}` });
}

/** POST {baseUrl}/api/workouts/sync?athlete=<slug> -- the Log tab's primary
 * "Sync from watch" button. Runs an on-demand intervals.icu sync for the
 * athlete and returns `{ listed, new, saved, failed }` on success. If sync
 * isn't set up for this athlete, the backend returns 409 with a
 * `{error}` body -- surfaced through the same `{ ok: false, error }` shape
 * apiRequest already normalizes every other failure into, so main.js only
 * needs one branch. */
export async function syncWorkouts({ baseUrl, token, athlete = 'renee' }) {
  return apiRequest({
    baseUrl, token, path: `/api/workouts/sync?athlete=${encodeURIComponent(athlete)}`, method: 'POST',
  });
}

/** POST {baseUrl}/api/wellness?athlete=<slug> -- logs a daily check-in. */
export async function postWellness({ baseUrl, token, athlete = 'renee', payload }) {
  return apiRequest({
    baseUrl, token, path: `/api/wellness?athlete=${encodeURIComponent(athlete)}`, method: 'POST', body: payload,
  });
}

/** GET {baseUrl}/api/wellness?athlete=<slug> -- lists logged check-ins. */
export async function listWellness({ baseUrl, token, athlete = 'renee' }) {
  return apiRequest({ baseUrl, token, path: `/api/wellness?athlete=${encodeURIComponent(athlete)}` });
}

/** POST {baseUrl}/api/feedback?athlete=<slug> -- submits a feature request,
 * comment, or bug report (the coach's own research-gap questions are
 * logged separately, server-side, via the chat tool loop -- see
 * backend/app/tools.py's log_open_question). */
export async function postFeedback({ baseUrl, token, athlete = 'renee', payload }) {
  return apiRequest({
    baseUrl, token, path: `/api/feedback?athlete=${encodeURIComponent(athlete)}`, method: 'POST', body: payload,
  });
}

/** GET {baseUrl}/api/feedback?athlete=<slug> -- lists the durable feedback
 * log (most recent first), including the coach's auto-logged research
 * questions. */
export async function listFeedback({ baseUrl, token, athlete = 'renee' }) {
  return apiRequest({ baseUrl, token, path: `/api/feedback?athlete=${encodeURIComponent(athlete)}` });
}

/** GET {baseUrl}/api/plan?athlete=<slug> -- the live per-athlete plan. Used
 * by the Plan tab instead of the static baked data/<slug>.json now that the
 * athlete comes from the signed-in identity (src/identity.js) rather than a
 * build-time default -- see main.js's loadPlan(). */
export async function fetchPlan({ baseUrl, token, athlete }) {
  return apiRequest({ baseUrl, token, path: `/api/plan?athlete=${encodeURIComponent(athlete)}` });
}

/** GET {baseUrl}/api/athlete?athlete=<slug> -- fetches the athlete's own
 * profile, to prefill the Settings tab's profile-edit form. */
export async function getAthlete({ baseUrl, token, athlete }) {
  return apiRequest({ baseUrl, token, path: `/api/athlete?athlete=${encodeURIComponent(athlete)}` });
}

/** PATCH {baseUrl}/api/athlete?athlete=<slug> -- saves edited profile fields
 * (see forms.js's serializeProfileForm for the payload shape). */
export async function patchAthlete({ baseUrl, token, athlete, payload }) {
  return apiRequest({
    baseUrl, token, path: `/api/athlete?athlete=${encodeURIComponent(athlete)}`, method: 'PATCH', body: payload,
  });
}

// --- Google sign-in session exchange -----------------------------------------
// Unlike every function above, `exchangeGoogleToken` throws instead of
// returning `{ok, ...}` -- identity.js's GSI callback awaits it directly in
// a try/catch (see there), and a distinguishable error type is more useful
// than a status code at that call site: "this email isn't allowlisted yet"
// needs different UI copy than "the backend is unreachable," and `instanceof
// RequestAccessError` is a cleaner check than comparing strings.

/** Thrown by `exchangeGoogleToken` when the backend returns 403 -- the
 * signed-in Google account authenticated fine but isn't in the
 * `allowed_emails` allowlist yet (see backend/app/routes/auth.py). Callers
 * (identity.js) use `instanceof RequestAccessError` to show "request
 * access" copy instead of a generic failure message. */
export class RequestAccessError extends Error {}

/**
 * POST {baseUrl}/api/auth/google with the raw Google ID token from GSI's
 * credential callback. The backend verifies the token's signature/audience/
 * issuer/expiry server-side (see backend/app/google_auth.py) -- this is the
 * fix for identity.js's old "IDENTITY FOR UX, NOT A SECURITY BOUNDARY"
 * caveat: the token itself is never decoded client-side anymore, just
 * handed to the backend as-is.
 *
 * Resolves with the raw `{token, athlete, name, role, expires_at}` JSON on
 * success (the minted per-user session token plus the identity the backend
 * resolved it to). Throws `RequestAccessError` on a 403 (email not
 * allowlisted) and a plain `Error` for every other failure (bad/expired
 * token -> 401, network failure, unparsable response).
 */
export async function exchangeGoogleToken({ baseUrl, idToken }) {
  let response;
  try {
    response = await fetch(`${baseUrl}/api/auth/google`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id_token: idToken }),
    });
  } catch (err) {
    log.error('auth.exchange_request_failed', { error: err.message });
    throw new Error('Could not reach the coach backend. Check your connection and Settings.');
  }

  if (response.status === 403) {
    log.warn('auth.exchange_forbidden', {});
    throw new RequestAccessError('This Google account is not authorized yet -- request access from your coach.');
  }

  if (!response.ok) {
    const message = await safeErrorMessage(response);
    log.error('auth.exchange_rejected', { status: response.status, error: message });
    throw new Error(message);
  }

  try {
    return await response.json();
  } catch (err) {
    log.error('auth.exchange_parse_failed', { error: err.message });
    throw new Error('Unexpected response from backend.');
  }
}

// --- Self-service onboarding (Slice 3) --------------------------------------
// POST /api/onboard -- backend/app/routes/onboard.py. Only an ONBOARDING-
// scoped session (minted by exchangeGoogleToken's `{onboarding: true}`
// branch, see identity.js) can call this; it turns the onboarding form's
// hard-data payload into a brand-new athlete and, on success, upgrades the
// caller to an ordinary athlete-bound session token in one round trip.
//
// Throws instead of returning `{ok, ...}` -- same rationale as
// exchangeGoogleToken above: main.js's handleOnboardSubmit wants
// distinguishable failure modes (`instanceof OnboardForbiddenError` for a
// dead/invalid onboarding session, `instanceof OnboardConflictError` for a
// name/slug that's already taken) rather than just a status code to switch
// on. Every thrown error also carries a `.status` (mirroring apiRequest's
// `result.status`) so main.js can single out a 401 (session expired) the
// same way handleUnauthorized does for every other endpoint, without a
// fourth error subclass just for that one case.

/** Thrown by `onboard` on a 403 -- the bearer token isn't (or is no longer)
 * a live onboarding session: the invite backing it was revoked, or this
 * route was called with an already-athlete-bound token (see onboard.py's
 * two distinct 403 branches; both collapse to this one error class since
 * the frontend's response is the same either way -- the form can't proceed
 * with this session). */
export class OnboardForbiddenError extends Error {}

/** Thrown by `onboard` on a 409 -- either this invite already completed
 * onboarding (e.g. a second tab), or the chosen/derived athlete slug
 * collides with an existing athlete. The message (from the backend body)
 * tells them which. */
export class OnboardConflictError extends Error {}

/**
 * POST {baseUrl}/api/onboard with the onboarding form's payload (see
 * src/onboarding.js's `onboardPayloadFromForm`, which mirrors
 * backend/app/routes/onboard.py's `OnboardRequest` field-for-field).
 * Resolves with the raw `{token, athlete, name, role, expires_at}` JSON on
 * success -- the same athlete-bound session shape `exchangeGoogleToken`'s
 * ordinary branch returns, so main.js swaps tokens/identity the same way
 * either path produces one.
 */
export async function onboard({ baseUrl, token, payload }) {
  let response;
  try {
    response = await fetch(`${baseUrl}/api/onboard`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(payload),
    });
  } catch (err) {
    log.error('onboard.request_failed', { error: err.message });
    throw new Error('Could not reach the coach backend. Check your connection and try again.');
  }

  if (response.status === 403) {
    const message = await safeErrorMessage(response);
    log.error('onboard.forbidden', { error: message });
    const err = new OnboardForbiddenError(message || 'This session can no longer complete onboarding.');
    err.status = 403;
    throw err;
  }

  if (response.status === 409) {
    const message = await safeErrorMessage(response);
    log.warn('onboard.conflict', { error: message });
    const err = new OnboardConflictError(message || 'That invite or athlete name is already in use.');
    err.status = 409;
    throw err;
  }

  if (!response.ok) {
    const message = await safeErrorMessage(response);
    log.error('onboard.rejected', { status: response.status, error: message });
    const err = new Error(message);
    err.status = response.status;
    throw err;
  }

  try {
    return await response.json();
  } catch (err) {
    log.error('onboard.parse_failed', { error: err.message });
    throw new Error('Unexpected response from backend.');
  }
}

/**
 * POST {baseUrl}/api/auth/logout -- revokes the session token so it 401s on
 * every subsequent request (see backend/app/routes/auth.py's logout route).
 * Deliberately best-effort and never throws: sign-out is a local action
 * (clear identity + token, per identity.js) that must complete regardless of
 * whether the revoke call itself succeeds -- there is no refresh endpoint,
 * so a failed revoke just leaves a stale session that will 401 on its own
 * once it expires, not a security hole worth blocking the UI over.
 */
export async function logout({ baseUrl, token }) {
  try {
    const response = await fetch(`${baseUrl}/api/auth/logout`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!response.ok) {
      log.warn('auth.logout_failed', { status: response.status });
    }
  } catch (err) {
    log.error('auth.logout_request_failed', { error: err.message });
  }
}
