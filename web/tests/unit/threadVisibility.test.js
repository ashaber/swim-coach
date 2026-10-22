import { describe, it, expect } from 'vitest';
import { visibleThreadMessages } from '../../src/threadVisibility.js';

const thread = [
  { id: '1', sender_role: 'athlete', body: 'hi' },
  { id: '2', sender_role: 'coach', body: 'public', visibility: 'all' },
  { id: '3', sender_role: 'coach', body: 'reanalyze', visibility: 'coach_only' },
  { id: '4', sender_role: 'ai_coach', body: 'done', visibility: 'coach_only' },
];

describe('visibleThreadMessages', () => {
  it('hides coach-only messages from the athlete', () => {
    expect(visibleThreadMessages(thread, 'athlete').map((m) => m.id)).toEqual(['1', '2']);
  });
  it('shows everything the server sent to the coach', () => {
    expect(visibleThreadMessages(thread, 'coach')).toHaveLength(4);
  });
  it('tolerates a missing list', () => {
    expect(visibleThreadMessages(undefined, 'athlete')).toEqual([]);
  });
});
