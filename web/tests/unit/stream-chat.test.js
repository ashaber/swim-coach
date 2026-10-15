import { describe, it, expect, vi } from 'vitest';
import { streamChat } from '../../src/api.js';

function sseFetch(frames) {
  const enc = new TextEncoder();
  let i = 0;
  const reader = {
    read: async () => (i < frames.length ? { done: false, value: enc.encode(frames[i++]) } : { done: true }),
  };
  return vi.fn().mockResolvedValue({ ok: true, status: 200, body: { getReader: () => reader } });
}

const frame = (e) => `data: ${JSON.stringify(e)}\n\n`;
const args = { baseUrl: 'https://api.example.com', token: 't', athlete: 'a', message: 'hi', history: [] };

describe('streamChat terminal-event guard', () => {
  it('emits a synthetic error when the stream ends without a terminal event', async () => {
    globalThis.fetch = sseFetch([frame({ type: 'text', text: 'partial' })]);
    const events = [];
    await streamChat({ ...args, onEvent: (e) => events.push(e) });
    expect(events.at(-1)).toEqual({ type: 'error', error: 'Connection closed before the reply finished.' });
  });

  it.each(['done', 'refusal', 'error'])('adds nothing extra after a %s event', async (type) => {
    globalThis.fetch = sseFetch([frame({ type: 'text', text: 'x' }), frame({ type, error: 'e' })]);
    const events = [];
    await streamChat({ ...args, onEvent: (e) => events.push(e) });
    expect(events.map((e) => e.type)).toEqual(['text', type]);
  });
});
