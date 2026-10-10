import { describe, it, expect } from 'vitest';
import { renderCoachTab, renderWorkoutDetail, renderRosterTrainingPlanBody } from '../../src/views.js';
import { setDraft, getDraft, clearDraft } from '../../src/composerDrafts.js';

const XSS = 'hi <b>"x"</b> & more';
const ESCAPED = 'hi &lt;b&gt;&quot;x&quot;&lt;/b&gt; &amp; more';
const taOf = (html, id) => html.match(new RegExp(`<textarea id="${id}"[^>]*>([^<]*)</textarea>`))?.[1];

describe('composerDrafts store', () => {
  it('stores, returns and clears a draft; empty string deletes', () => {
    setDraft('k', 'abc');
    expect(getDraft('k')).toBe('abc');
    setDraft('k', '');
    expect(getDraft('k')).toBe('');
    setDraft('k', 'x');
    clearDraft('k');
    expect(getDraft('k')).toBe('');
  });
});

describe('chat composer drafts survive a re-render', () => {
  it('AI coach composer re-emits its draft, escaped, and is empty after clearDraft', () => {
    const args = { messages: [], expertMode: false, sending: false, backendConfigured: true, online: true, role: 'athlete' };
    setDraft('chat-input', XSS);
    expect(taOf(renderCoachTab(args), 'chat-input')).toBe(ESCAPED);
    clearDraft('chat-input');
    expect(taOf(renderCoachTab(args), 'chat-input')).toBe('');
  });

  it('workout and roster-workout composers re-emit a draft keyed per workout', () => {
    const workout = { id: 'w1', sport: 'swim_pool', date: '2026-10-01T00:00:00Z', chat_messages: [] };
    setDraft('workout-chat-input:w1', XSS);
    setDraft('roster-workout-chat-input:w1', XSS);
    expect(taOf(renderWorkoutDetail(workout, { online: true, chat: null }), 'workout-chat-input')).toBe(ESCAPED);
    expect(taOf(renderWorkoutDetail(workout, { online: true, viewerRole: 'coach' }), 'roster-workout-chat-input')).toBe(ESCAPED);
    const other = { ...workout, id: 'w2' };
    expect(taOf(renderWorkoutDetail(other, { online: true, chat: null }), 'workout-chat-input')).toBe('');
    clearDraft('workout-chat-input:w1');
    clearDraft('roster-workout-chat-input:w1');
  });

  it('roster AI chat composer drafts are per coached athlete', () => {
    const render = (slug) => renderRosterTrainingPlanBody({
      plan: { status: 'loading' }, online: true, chat: null, chatSending: false, athleteSlug: slug,
    });
    setDraft('roster-chat-input:ann', XSS);
    expect(taOf(render('ann'), 'roster-chat-input')).toBe(ESCAPED);
    expect(taOf(render('bob'), 'roster-chat-input')).toBe('');
    expect(render('bob')).toContain('data-draft-key="roster-chat-input:bob"');
    expect(taOf(render('ann'), 'roster-chat-input')).toBe(ESCAPED);
    clearDraft('roster-chat-input:ann');
  });
});
