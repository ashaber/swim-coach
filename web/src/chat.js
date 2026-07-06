// Pure chat-session state: append/stream reducers plus localStorage
// persistence. No fetch/DOM access here (that's api.js / main.js) -- kept
// pure so the reducers and persistence round-trip are cheaply unit-testable.

const STORAGE_PREFIX = 'swimcoach_chat_';

const REFUSAL_TEXT = "I'm not able to answer that one safely on my own -- it sounds like it "
  + "needs a real coach or clinician's judgment. Please check with your coach or a medical "
  + 'professional before continuing.';

export const TOOL_LABELS = {
  propose_adaptation: 'drafting an adaptation…',
  get_plan_summary: 'consulting the plan…',
  log_open_question: 'logging a question for research…',
};

/** A fresh, empty chat session. */
export function createChatSession() {
  return { messages: [], expertMode: false };
}

/** Append the athlete's message plus an empty in-progress assistant
 * placeholder that subsequent `applyStreamEvent` calls fill in. */
export function appendUserMessage(session, text) {
  const messages = [
    ...session.messages,
    { role: 'user', content: text, status: 'done' },
    { role: 'assistant', content: '', status: 'streaming', toolCalls: [] },
  ];
  return { ...session, messages };
}

/** Fold one parsed SSE event (see sse.js) into the session, mutating only
 * the most recent (in-progress) assistant message. Unknown event types
 * and a missing/finalized last message are no-ops -- defensive against a
 * malformed or duplicate event never crashing the chat UI. */
export function applyStreamEvent(session, event) {
  const messages = session.messages.slice();
  const lastIdx = messages.length - 1;
  const last = messages[lastIdx];
  if (!last || last.role !== 'assistant' || last.status !== 'streaming') return session;

  let next = last;
  switch (event?.type) {
    case 'text':
      next = { ...last, content: last.content + (event.text ?? '') };
      break;
    case 'tool_use':
      next = { ...last, toolCalls: [...(last.toolCalls || []), { name: event.name, input: event.input }] };
      break;
    case 'done':
      next = { ...last, status: 'done', stopReason: event.stop_reason };
      break;
    case 'refusal':
      next = { ...last, status: 'refusal', content: last.content || REFUSAL_TEXT };
      break;
    case 'error':
      next = { ...last, status: 'error', error: event.error || 'Something went wrong.' };
      break;
    default:
      return session; // unrecognized event type -- ignore rather than throw
  }
  messages[lastIdx] = next;
  return { ...session, messages };
}

/** True while the last message is an unfinished assistant turn -- drives
 * disabling the composer / showing a "thinking" state. */
export function isStreaming(session) {
  const last = session.messages[session.messages.length - 1];
  return !!last && last.role === 'assistant' && last.status === 'streaming';
}

export function setExpertMode(session, expertMode) {
  return { ...session, expertMode: !!expertMode };
}

/** Clears messages but keeps the expert-mode preference. */
export function clearMessages(session) {
  return { ...session, messages: [] };
}

/** The `history` array to send with the *next* request: every finalized
 * turn (done or refusal) in {role, content} shape, exactly the backend's
 * `HistoryMessage`. Streaming/error turns are excluded -- an error turn
 * has no real assistant content worth replaying back to the model. */
export function toApiHistory(messages) {
  return messages
    .filter((m) => m.status === 'done' || m.status === 'refusal')
    .map((m) => ({ role: m.role, content: m.content }));
}

function storageKey(athleteSlug) {
  return `${STORAGE_PREFIX}${athleteSlug}`;
}

export function loadChatSession(athleteSlug, storage = localStorage) {
  try {
    const raw = storage.getItem(storageKey(athleteSlug));
    if (!raw) return createChatSession();
    const parsed = JSON.parse(raw);
    return {
      messages: Array.isArray(parsed.messages) ? parsed.messages : [],
      expertMode: !!parsed.expertMode,
    };
  } catch {
    return createChatSession();
  }
}

export function saveChatSession(athleteSlug, session, storage = localStorage) {
  try {
    storage.setItem(storageKey(athleteSlug), JSON.stringify({
      messages: session.messages,
      expertMode: session.expertMode,
    }));
  } catch {
    // localStorage unavailable (private mode quota, etc.) -- in-memory state still works
  }
}

export function clearChatStorage(athleteSlug, storage = localStorage) {
  try {
    storage.removeItem(storageKey(athleteSlug));
  } catch {
    // ignore
  }
}
