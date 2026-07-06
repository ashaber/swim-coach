import { describe, it, expect, beforeEach } from 'vitest';
import {
  createChatSession, appendUserMessage, applyStreamEvent, isStreaming,
  setExpertMode, clearMessages, toApiHistory,
  loadChatSession, saveChatSession, clearChatStorage,
} from '../../src/chat.js';

// Minimal in-memory localStorage stand-in -- tests pass this explicitly
// rather than touching the real global, so they're isolated and don't
// need jsdom.
function makeFakeStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
    _store: store,
  };
}

describe('appendUserMessage', () => {
  it('appends the user turn plus an empty streaming assistant placeholder', () => {
    const session = appendUserMessage(createChatSession(), 'how should I pace the long swim?');
    expect(session.messages).toEqual([
      { role: 'user', content: 'how should I pace the long swim?', status: 'done' },
      { role: 'assistant', content: '', status: 'streaming', toolCalls: [] },
    ]);
  });
});

describe('applyStreamEvent', () => {
  it('accumulates text deltas onto the in-progress assistant message', () => {
    let session = appendUserMessage(createChatSession(), 'hi');
    session = applyStreamEvent(session, { type: 'text', text: 'Hello ' });
    session = applyStreamEvent(session, { type: 'text', text: 'Renee' });
    expect(session.messages.at(-1)).toEqual({
      role: 'assistant', content: 'Hello Renee', status: 'streaming', toolCalls: [],
    });
  });

  it('records tool_use events without altering content', () => {
    let session = appendUserMessage(createChatSession(), 'what does this week look like?');
    session = applyStreamEvent(session, { type: 'tool_use', name: 'get_plan_summary', input: {} });
    expect(session.messages.at(-1).toolCalls).toEqual([{ name: 'get_plan_summary', input: {} }]);
    expect(session.messages.at(-1).status).toBe('streaming');
  });

  it('finalizes the message on done', () => {
    let session = appendUserMessage(createChatSession(), 'hi');
    session = applyStreamEvent(session, { type: 'text', text: 'sure' });
    session = applyStreamEvent(session, { type: 'done', stop_reason: 'end_turn' });
    expect(session.messages.at(-1)).toEqual({
      role: 'assistant', content: 'sure', status: 'done', toolCalls: [], stopReason: 'end_turn',
    });
    expect(isStreaming(session)).toBe(false);
  });

  it('marks refusal turns and supplies fallback copy when no text preceded it', () => {
    let session = appendUserMessage(createChatSession(), 'is this shoulder pain normal?');
    session = applyStreamEvent(session, { type: 'refusal' });
    const last = session.messages.at(-1);
    expect(last.status).toBe('refusal');
    expect(last.content.length).toBeGreaterThan(0);
    expect(isStreaming(session)).toBe(false);
  });

  it('marks error turns with the error message', () => {
    let session = appendUserMessage(createChatSession(), 'hi');
    session = applyStreamEvent(session, { type: 'error', error: 'backend exploded' });
    expect(session.messages.at(-1)).toMatchObject({ status: 'error', error: 'backend exploded' });
    expect(isStreaming(session)).toBe(false);
  });

  it('is a no-op once the turn is already finalized', () => {
    let session = appendUserMessage(createChatSession(), 'hi');
    session = applyStreamEvent(session, { type: 'done', stop_reason: 'end_turn' });
    const after = applyStreamEvent(session, { type: 'text', text: 'late arrival' });
    expect(after).toBe(session);
  });

  it('ignores unknown event types', () => {
    let session = appendUserMessage(createChatSession(), 'hi');
    const after = applyStreamEvent(session, { type: 'mystery' });
    expect(after).toBe(session);
  });
});

describe('setExpertMode / clearMessages', () => {
  it('toggles expert mode independent of messages', () => {
    const session = setExpertMode(createChatSession(), true);
    expect(session.expertMode).toBe(true);
    expect(session.messages).toEqual([]);
  });

  it('clears messages but keeps expert mode', () => {
    let session = setExpertMode(createChatSession(), true);
    session = appendUserMessage(session, 'hi');
    session = clearMessages(session);
    expect(session.messages).toEqual([]);
    expect(session.expertMode).toBe(true);
  });
});

describe('toApiHistory', () => {
  it('includes done and refusal turns, excludes streaming and error turns', () => {
    let session = appendUserMessage(createChatSession(), 'q1');
    session = applyStreamEvent(session, { type: 'text', text: 'a1' });
    session = applyStreamEvent(session, { type: 'done', stop_reason: 'end_turn' });
    session = appendUserMessage(session, 'q2 -- risky question');
    session = applyStreamEvent(session, { type: 'refusal' });
    session = appendUserMessage(session, 'q3');
    // q3's assistant reply is still streaming -- should not appear in history yet.

    const history = toApiHistory(session.messages);
    expect(history).toEqual([
      { role: 'user', content: 'q1' },
      { role: 'assistant', content: 'a1' },
      { role: 'user', content: 'q2 -- risky question' },
      { role: 'assistant', content: session.messages[3].content },
      { role: 'user', content: 'q3' },
    ]);
  });

  it('excludes an errored assistant turn', () => {
    let session = appendUserMessage(createChatSession(), 'q1');
    session = applyStreamEvent(session, { type: 'error', error: 'boom' });
    const history = toApiHistory(session.messages);
    expect(history).toEqual([{ role: 'user', content: 'q1' }]);
  });
});

describe('localStorage persistence round-trip', () => {
  let storage;
  beforeEach(() => {
    storage = makeFakeStorage();
  });

  it('loadChatSession returns an empty session when nothing is stored', () => {
    expect(loadChatSession('renee', storage)).toEqual({ messages: [], expertMode: false });
  });

  it('round-trips messages and expertMode through save/load', () => {
    let session = setExpertMode(createChatSession(), true);
    session = appendUserMessage(session, 'hi coach');
    session = applyStreamEvent(session, { type: 'text', text: 'hey!' });
    session = applyStreamEvent(session, { type: 'done', stop_reason: 'end_turn' });

    saveChatSession('renee', session, storage);
    const loaded = loadChatSession('renee', storage);
    expect(loaded).toEqual(session);
  });

  it('keys storage per athlete so sessions do not collide', () => {
    saveChatSession('renee', appendUserMessage(createChatSession(), 'renee msg'), storage);
    saveChatSession('andrew', appendUserMessage(createChatSession(), 'andrew msg'), storage);
    expect(loadChatSession('renee', storage).messages[0].content).toBe('renee msg');
    expect(loadChatSession('andrew', storage).messages[0].content).toBe('andrew msg');
  });

  it('clearChatStorage removes only that athlete\'s entry', () => {
    saveChatSession('renee', appendUserMessage(createChatSession(), 'hi'), storage);
    clearChatStorage('renee', storage);
    expect(loadChatSession('renee', storage)).toEqual({ messages: [], expertMode: false });
  });

  it('falls back to an empty session on corrupt stored JSON', () => {
    storage.setItem('swimcoach_chat_renee', 'not json{{{');
    expect(loadChatSession('renee', storage)).toEqual({ messages: [], expertMode: false });
  });
});
