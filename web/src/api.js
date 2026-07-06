// Network layer for the Phase-2 chat backend. Everything here does real
// I/O (fetch) so it isn't unit-tested directly -- e2e tests mock `fetch`
// at the browser level instead. The one piece of real logic (parsing the
// `text/event-stream` body) is factored out to sse.js's `feedSSEBuffer`,
// which *is* unit-tested.
//
// Deliberately uses fetch + a streaming body reader, not EventSource --
// EventSource can't send a POST body or an Authorization header, and the
// chat endpoint needs both.

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
