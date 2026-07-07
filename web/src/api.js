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
 */
export async function streamChat({ baseUrl, token, athlete, message, history, expertMode, onEvent, signal }) {
  let response;
  try {
    response = await fetch(`${baseUrl}/api/chat`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ message, history, athlete, expert_mode: !!expertMode }),
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
    onEvent({ type: 'error', error: message2 });
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
 * into `{ ok: false, error }` so callers only ever need one branch -- same
 * convention as `testConnection`. Success returns `{ ok: true, data }`.
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
    return { ok: false, error: message };
  }

  try {
    const data = await response.json();
    return { ok: true, data };
  } catch (err) {
    log.error('api.parse_failed', { path, error: err.message });
    return { ok: false, error: 'Unexpected response from backend.' };
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

/** GET {baseUrl}/health -- used by the Settings tab's "Test connection". */
export async function testConnection({ baseUrl, token }) {
  try {
    const response = await fetch(`${baseUrl}/health`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    if (!response.ok) {
      return { ok: false, message: `Backend responded ${response.status}.` };
    }
    const body = await response.json();
    if (body?.status === 'ok') return { ok: true, message: 'Connected.' };
    return { ok: false, message: 'Unexpected response from backend.' };
  } catch (err) {
    log.error('settings.test_connection_failed', { error: err.message });
    return { ok: false, message: 'Could not reach that URL.' };
  }
}
