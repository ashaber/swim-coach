import { describe, it, expect } from 'vitest';
import { feedSSEBuffer } from '../../src/sse.js';

describe('feedSSEBuffer', () => {
  it('parses a single complete frame', () => {
    const { events, remainder } = feedSSEBuffer('', 'data: {"type":"text","text":"hi"}\n\n');
    expect(events).toEqual([{ type: 'text', text: 'hi' }]);
    expect(remainder).toBe('');
  });

  it('parses multiple frames delivered in one chunk', () => {
    const chunk = 'data: {"type":"text","text":"a"}\n\ndata: {"type":"text","text":"b"}\n\n';
    const { events, remainder } = feedSSEBuffer('', chunk);
    expect(events).toEqual([
      { type: 'text', text: 'a' },
      { type: 'text', text: 'b' },
    ]);
    expect(remainder).toBe('');
  });

  it('carries over an incomplete trailing frame as remainder', () => {
    const { events, remainder } = feedSSEBuffer('', 'data: {"type":"text","text":"a"}\n\ndata: {"type":"text"');
    expect(events).toEqual([{ type: 'text', text: 'a' }]);
    expect(remainder).toBe('data: {"type":"text"');
  });

  it('reassembles a frame split across chunks at an arbitrary byte offset', () => {
    // Split mid-JSON, mid-"data: " prefix even -- simulates a real fetch
    // chunk boundary landing anywhere.
    const chunk1 = 'data: {"type":"tex';
    const chunk2 = 't","text":"hello"}\n\n';
    const first = feedSSEBuffer('', chunk1);
    expect(first.events).toEqual([]);
    expect(first.remainder).toBe(chunk1);

    const second = feedSSEBuffer(first.remainder, chunk2);
    expect(second.events).toEqual([{ type: 'text', text: 'hello' }]);
    expect(second.remainder).toBe('');
  });

  it('handles a frame split right at the \\n\\n boundary', () => {
    const first = feedSSEBuffer('', 'data: {"type":"done","stop_reason":"end_turn"}\n');
    expect(first.events).toEqual([]);
    expect(first.remainder).toBe('data: {"type":"done","stop_reason":"end_turn"}\n');

    const second = feedSSEBuffer(first.remainder, '\ndata: {"type":"text","text":"next"}\n\n');
    expect(second.events).toEqual([
      { type: 'done', stop_reason: 'end_turn' },
      { type: 'text', text: 'next' },
    ]);
  });

  it('parses tool_use, refusal, and error event shapes', () => {
    const chunk = [
      'data: {"type":"tool_use","name":"get_plan_summary","input":{}}\n\n',
      'data: {"type":"refusal"}\n\n',
      'data: {"type":"error","error":"boom"}\n\n',
    ].join('');
    const { events } = feedSSEBuffer('', chunk);
    expect(events).toEqual([
      { type: 'tool_use', name: 'get_plan_summary', input: {} },
      { type: 'refusal' },
      { type: 'error', error: 'boom' },
    ]);
  });

  it('drops a malformed JSON frame rather than throwing', () => {
    const chunk = 'data: {not json}\n\ndata: {"type":"text","text":"ok"}\n\n';
    const { events } = feedSSEBuffer('', chunk);
    expect(events).toEqual([{ type: 'text', text: 'ok' }]);
  });

  it('ignores a segment with no data: line', () => {
    const { events, remainder } = feedSSEBuffer('', ': heartbeat comment\n\ndata: {"type":"text","text":"x"}\n\n');
    expect(events).toEqual([{ type: 'text', text: 'x' }]);
    expect(remainder).toBe('');
  });
});
