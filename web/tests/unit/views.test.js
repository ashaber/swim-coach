import { describe, it, expect } from 'vitest';
import {
  renderDashboardTab, renderSettingsTab, renderUpdateBanner, renderApp,
  renderTabBar, renderRosterTab, renderLoadChart,
  renderCr10SliderField, cr10AnchorLabel, loadTierLabel, renderWorkoutRow,
  renderAskCoachSection, renderFeedbackTab,
} from '../../src/views.js';
import { isoWeekMonday, addDays, dateKey, formatShortDate } from '../../src/plan.js';
import { HISTORY_DISPLAY_CAP } from '../../src/workouts.js';

// Real fixture workouts from the task brief -- andrew's 2026-07-09
// cross_train (analytics-rich, no distance/pace since it's not a swim) and
// his 2026-03-14 swim_pool (SWOLF example), plus an older manual entry with
// analytics: null to prove the section renders fine without it.
const CROSS_TRAIN_WORKOUT = {
  id: 'w-cross', date: '2026-07-09', sport: 'cross_train', source: 'fit',
  distance_m: null, duration_min: 303.3, avg_pace_s_per_100m: null, rpe: 6, notes: null,
  analytics: { cardiac_drift_pct: -13.77, pause_count: 0, moving_min: 303.3, elapsed_min: 303.3 },
};

const POOL_SWIM_WORKOUT = {
  id: 'w-pool', date: '2026-03-14', sport: 'swim_pool', source: 'fit',
  distance_m: 3200, duration_min: 65, avg_pace_s_per_100m: 95, rpe: 5, notes: null,
  analytics: {
    swolf_first_quarter: 40.96, swolf_last_quarter: 43.41, swolf_degradation_pct: 6.0,
  },
};

const OLD_MANUAL_WORKOUT = {
  id: 'w-old', date: '2025-11-02', sport: 'swim_pool', source: 'manual',
  distance_m: 2000, duration_min: 40, avg_pace_s_per_100m: null, rpe: null, notes: 'easy recovery',
  analytics: null,
};

// A rich .fit workout with laps + pauses + full analytics, for detail-view
// tests -- distinct from CROSS_TRAIN_WORKOUT/POOL_SWIM_WORKOUT above (those
// only carry `analytics`, no laps/pauses/lengths/avg_hr/max_hr).
const RICH_FIT_WORKOUT = {
  id: 'w-rich', date: '2026-06-01', sport: 'swim_ow', source: 'fit',
  distance_m: 5000, duration_min: 95, avg_pace_s_per_100m: 114, rpe: 7,
  notes: 'Choppy back half, felt strong.',
  avg_hr: 132, max_hr: 158,
  analytics: {
    cardiac_drift_pct: 6.4, split_label: 'positive',
    first_half_pace_s_per_100m: 108, second_half_pace_s_per_100m: 120,
    elapsed_min: 98, moving_min: 95, pause_total_min: 3, pause_count: 2,
    swolf_first_quarter: 38.2, swolf_last_quarter: 44.9, swolf_degradation_pct: 17.5,
  },
  laps: [
    {
      index: 0, start_offset_s: 0, duration_s: 1830, distance_m: 2500,
      avg_hr: 128, max_hr: 145, avg_pace_s_per_100m: 108, stroke: 'freestyle', num_lengths: null,
    },
    {
      index: 1, start_offset_s: 1830, duration_s: 1980, distance_m: 2500,
      avg_hr: 136, max_hr: 158, avg_pace_s_per_100m: 120, stroke: 'freestyle', num_lengths: null,
    },
  ],
  lengths: [],
  pauses: [
    { start_offset_s: 754, duration_s: 45, source: 'gap' },
    { start_offset_s: 2600, duration_s: 90, source: 'timer' },
  ],
};

// Build 1 (Log+History merge, wellness-ingestion + training-dashboard plan):
// renderLogTab, renderHistoryTab, and renderHistorySection are retired in
// favor of one shared renderDashboardTab (athlete-facing wrapper) +
// renderTrainingDashboardBody (shared with renderRosterTab, see that
// describe block below). Every behavioral assertion those three used to
// carry is preserved here, just re-pointed at the merged component.
function feedOf(workouts) {
  return workouts.map((w) => ({ kind: 'completed', date: w.date, key: `w:${w.id}`, workout: w }));
}

const DASHBOARD_BASE_ARGS = {
  load: { status: 'idle', data: null, error: null },
  status: 'ready',
  error: null,
  online: true,
  detailId: null,
  workoutChat: null,
  backendConfigured: true,
  form: {
    date: '2026-07-11', sport: 'swim_pool', distance_m: '', duration_min: '', rpe: 5, notes: '',
  },
  submit: { status: 'idle', message: null },
  ingest: { status: 'idle', fileName: null, error: null },
  sync: { status: 'idle', message: null },
  manualOpen: false,
  feedExpanded: false,
};

describe('renderDashboardTab', () => {
  describe('feed rendering (completed workouts)', () => {
    it('renders a workout row with a compact analytics line when analytics has content', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: feedOf([CROSS_TRAIN_WORKOUT]) });
      expect(html).toContain('Cross-train');
      expect(html).toContain('hist-analytics');
      expect(html).toContain('drift -13.8%');
      expect(html).toContain('fit'); // source badge
      expect(html).toContain('RPE 6');
    });

    it('renders the real swolf example fields', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: feedOf([POOL_SWIM_WORKOUT]) });
      expect(html).toContain('SWOLF 41.0→43.4 (+6.0%)');
      expect(html).toContain('3.2 km');
      expect(html).toContain('1:35 /100m');
    });

    it('renders a workout row with no analytics line when analytics is null', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: feedOf([OLD_MANUAL_WORKOUT]) });
      expect(html).not.toContain('hist-analytics');
      // Manual source gets no source badge chip -- but OLD_MANUAL_WORKOUT's
      // rpe: null still renders the explicit "No RPE" chip (see the "no RPE
      // indicator" describe block below), so a chat-chip IS present here.
      expect(html).toContain('No RPE');
    });

    it('renders multiple rows in the order the feed gives them (does not re-sort)', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([CROSS_TRAIN_WORKOUT, POOL_SWIM_WORKOUT]),
      });
      const crossIdx = html.indexOf('Cross-train');
      const poolIdx = html.indexOf('Pool swim');
      expect(crossIdx).toBeGreaterThan(-1);
      expect(poolIdx).toBeGreaterThan(crossIdx);
    });

    it('shows an empty-state message when nothing has happened yet', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: [] });
      expect(html).toContain('Nothing logged or missed yet');
    });

    it('shows a loading message while loading with nothing cached yet', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: [], status: 'loading' });
      expect(html).toContain('Loading history');
    });

    it('shows the error message and a retry action on fetch failure', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: [], status: 'error', error: 'Backend error (500).',
      });
      expect(html).toContain("Couldn't load your training history");
      expect(html).toContain('Backend error (500).');
      expect(html).toContain('data-a="history:retry"');
    });

    it('still shows stale cached data alongside an error banner on a failed refresh', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: feedOf([OLD_MANUAL_WORKOUT]),
        status: 'error',
        error: 'offline',
        online: false,
      });
      expect(html).toContain('Pool swim');
      expect(html).toContain("Couldn't load your training history");
    });

    it('shows a quiet offline notice (not the empty-feed message) when there is no data and offline', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: [], online: false });
      expect(html).toContain('reconnect');
      expect(html).not.toContain('Nothing logged or missed yet');
    });

    it('escapes workout notes/text content (no raw HTML injection)', () => {
      const malicious = { ...OLD_MANUAL_WORKOUT, sport: '<img src=x onerror=alert(1)>' };
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: feedOf([malicious]) });
      expect(html).not.toContain('<img src=x');
      expect(html).toContain('&lt;img');
    });
  });

  describe('skipped sessions (History-tab half of the merge)', () => {
    const SKIPPED_SESSION = {
      id: 's-missed', date: '2026-08-18', sport: 'strength', source: 'ai_coach',
      duration_min: 45, distance_m: null, intensity: {},
      purpose: 'Dryland shoulder strength — rotator-cuff work',
      structure: null, structured: null, status: 'planned',
    };
    const COMPLETED = {
      id: 'w-done', date: '2026-08-17', sport: 'swim_pool', source: 'fit',
      distance_m: 2050, duration_min: 61, rpe: 6, avg_pace_s_per_100m: 95,
      planned_session_id: null, analytics: null, laps: [], pauses: [],
    };
    const FEED = [
      { kind: 'skipped', date: '2026-08-18', key: 's:s-missed', session: SKIPPED_SESSION },
      { kind: 'completed', date: '2026-08-17', key: 'w:w-done', workout: COMPLETED },
    ];

    it('renders a skipped planned session with what was planned', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: FEED });
      expect(html).toContain('Strength');
      expect(html).toContain('Dryland shoulder strength');
      expect(html).toContain('45 min'); // the planned duration
    });

    it('clearly distinguishes a skipped item from a completed one', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: FEED });
      expect(html).toContain('hist-row-skipped');
      expect(html).toContain('Skipped');
    });

    it('keeps the feed order given -- newest first, no re-sorting', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: FEED });
      expect(html.indexOf('Dryland shoulder strength')).toBeLessThan(html.indexOf('Pool swim'));
    });

    it('makes completed rows tappable for detail but skipped rows not', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: FEED });
      expect(html).toContain('data-a="history:open" data-id="w-done"');
      expect(html).not.toContain('data-id="s-missed"');
    });

    it('escapes hostile content in a skipped session purpose', () => {
      const nasty = { ...SKIPPED_SESSION, id: 's-nasty', purpose: '<img src=x onerror=alert(1)>' };
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: [{ kind: 'skipped', date: '2026-08-18', key: 's:s-nasty', session: nasty }],
      });
      expect(html).not.toContain('<img src=x');
      expect(html).toContain('&lt;img');
    });
  });

  describe('pagination ("Show more", Build 1)', () => {
    const manyWorkouts = Array.from({ length: HISTORY_DISPLAY_CAP + 5 }, (_, i) => ({
      id: `w-${i}`, date: `2026-01-${String(i + 1).padStart(2, '0')}`, sport: 'swim_pool', source: 'manual',
      distance_m: 1000, duration_min: 20, rpe: 5, notes: null, analytics: null,
    }));

    it('shows only the most recent HISTORY_DISPLAY_CAP items by default, with a Show more control', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: feedOf(manyWorkouts) });
      expect(html.match(/data-a="history:open"/g).length).toBe(HISTORY_DISPLAY_CAP);
      expect(html).toContain('data-a="dashboard:show-more"');
    });

    it('shows the full feed and no Show more control once feedExpanded is true', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf(manyWorkouts), feedExpanded: true,
      });
      expect(html).not.toContain('data-a="dashboard:show-more"');
      expect(html.match(/data-a="history:open"/g).length).toBe(manyWorkouts.length);
    });

    it('omits the Show more control when the feed already fits within the cap', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: feedOf([OLD_MANUAL_WORKOUT]) });
      expect(html).not.toContain('data-a="dashboard:show-more"');
    });
  });

  describe('workout detail view (tap a row to open detail)', () => {
    it('renders the detail view instead of the feed when detailId matches a workout', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([RICH_FIT_WORKOUT, OLD_MANUAL_WORKOUT]), detailId: 'w-rich',
      });
      expect(html).toContain('data-a="history:back"');
      expect(html).not.toContain('data-a="history:open"');
      // Header: sport, date, source badge.
      expect(html).toContain('Open water swim');
      expect(html).toContain('fit');
    });

    it('renders summary stats: distance, duration, pace, RPE, avg/max HR', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([RICH_FIT_WORKOUT]), detailId: 'w-rich',
      });
      expect(html).toContain('5 km');
      expect(html).toContain('1 h 35 min');
      expect(html).toContain('1:54 /100m');
      expect(html).toContain('7/10');
      expect(html).toContain('132 bpm');
      expect(html).toContain('158 bpm');
    });

    it('renders the full analytics block with drift warning, split, moving-vs-elapsed, pauses, and swolf', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([RICH_FIT_WORKOUT]), detailId: 'w-rich',
      });
      expect(html).toContain('drift +6.4% ⚠');
      expect(html).toContain('positive split (1:48 → 2:00)');
      expect(html).toContain('1 h 35 min moving of 1 h 38 min');
      expect(html).toContain('2 pauses · 3 min stopped');
      expect(html).toContain('SWOLF 38.2→44.9 (+17.5%)');
    });

    it('renders a laps table with index, distance, duration, pace, and HR', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([RICH_FIT_WORKOUT]), detailId: 'w-rich',
      });
      expect(html).toContain('laps-table');
      expect(html).toContain('2.5 km');
      expect(html).toContain('30:30'); // 1830s
      expect(html).toContain('1:48'); // 108s/100m pace
      expect(html).toContain('128'); // lap avg HR
    });

    it('renders a pauses list with offset (h:mm:ss), duration, and source', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([RICH_FIT_WORKOUT]), detailId: 'w-rich',
      });
      expect(html).toContain('0:12:34'); // 754s offset
      expect(html).toContain('gap');
      expect(html).toContain('timer');
    });

    it('renders notes verbatim (escaped)', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([RICH_FIT_WORKOUT]), detailId: 'w-rich',
      });
      expect(html).toContain('Choppy back half, felt strong.');
    });

    it('escapes malicious notes content in the detail view', () => {
      const malicious = { ...RICH_FIT_WORKOUT, notes: '<img src=x onerror=alert(1)>' };
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([malicious]), detailId: 'w-rich',
      });
      expect(html).not.toContain('<img src=x');
      expect(html).toContain('&lt;img');
    });

    it('renders a bare manual workout (no laps/pauses/analytics) with clean summary stats only', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([OLD_MANUAL_WORKOUT]), detailId: 'w-old',
      });
      expect(html).toContain('data-a="history:back"');
      expect(html).toContain('Pool swim');
      expect(html).toContain('2 km');
      expect(html).toContain('40 min');
      expect(html).toContain('easy recovery');
      // No analytics/laps/pauses sections for a workout with none of those fields.
      expect(html).not.toContain('laps-table');
      expect(html).not.toContain('pauses-list');
      expect(html).not.toContain('detail-analytics-list');
    });

    it('falls back to the feed when detailId does not match any loaded workout', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([OLD_MANUAL_WORKOUT]), detailId: 'no-such-id',
      });
      expect(html).not.toContain('data-a="history:back"');
      expect(html).toContain('data-a="history:open"');
    });

    it('renders the feed (not detail) when detailId is null', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: feedOf([OLD_MANUAL_WORKOUT]), detailId: null,
      });
      expect(html).not.toContain('data-a="history:back"');
      expect(html).toContain('data-a="history:open"');
    });

    it('hides the load chart and sync/manual-entry actions while a detail is open', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: feedOf([RICH_FIT_WORKOUT]),
        detailId: 'w-rich',
        load: {
          status: 'ready',
          data: { ctl_atl_tsb: [['2026-08-01', 10, 5, 5], ['2026-08-02', 11, 6, 5]] },
          error: null,
        },
      });
      expect(html).not.toContain('<svg');
      expect(html).not.toContain('data-a="sync:start"');
    });
  });

  describe('embedded workout chat (Phase C slice 1)', () => {
    const openDetailArgs = {
      ...DASHBOARD_BASE_ARGS, feed: feedOf([RICH_FIT_WORKOUT]), detailId: 'w-rich',
    };

    it('renders the scoped chat section with the "About:" label when workoutChat matches the open detail', () => {
      const html = renderDashboardTab({
        ...openDetailArgs, workoutChat: { workoutId: 'w-rich', messages: [] },
      });
      expect(html).toContain('Ask your coach about this workout');
      expect(html).toContain('About: Jun 1 Open water swim');
      expect(html).toContain('id="workout-chat-input"');
      expect(html).toContain('data-a="workout-chat:send"');
    });

    it('omits the chat section entirely when workoutChat is null', () => {
      const html = renderDashboardTab({ ...openDetailArgs, workoutChat: null });
      expect(html).not.toContain('Ask your coach about this workout');
      expect(html).not.toContain('workout-chat-input');
    });

    it('omits the chat section when workoutChat belongs to a different workout', () => {
      const html = renderDashboardTab({
        ...openDetailArgs, workoutChat: { workoutId: 'w-other', messages: [] },
      });
      expect(html).not.toContain('Ask your coach about this workout');
    });

    it('renders thread messages with the coach-tab bubble classes', () => {
      const html = renderDashboardTab({
        ...openDetailArgs,
        workoutChat: {
          workoutId: 'w-rich',
          messages: [
            { role: 'user', content: 'how did this swim go?', status: 'done' },
            { role: 'assistant', content: 'A strong effort with a positive split.', status: 'done' },
          ],
        },
      });
      expect(html).toContain('chat-row me');
      expect(html).toContain('chat-row coach');
      expect(html).toContain('how did this swim go?');
      expect(html).toContain('A strong effort with a positive split.');
    });

    it('shows the streaming cursor and disables input/send while a reply streams', () => {
      const html = renderDashboardTab({
        ...openDetailArgs,
        workoutChat: {
          workoutId: 'w-rich',
          messages: [
            { role: 'user', content: 'thoughts?', status: 'done' },
            { role: 'assistant', content: 'Looking at it', status: 'streaming', toolCalls: [] },
          ],
        },
      });
      expect(html).toContain('chat-cursor');
      expect(html).toContain('Sending…');
      const inputMatch = /<textarea[^>]*id="workout-chat-input"[^>]*>/.exec(html);
      expect(inputMatch[0]).toContain('disabled');
    });

    it('disables the chat input with an offline notice when offline', () => {
      const html = renderDashboardTab({
        ...openDetailArgs, online: false, workoutChat: { workoutId: 'w-rich', messages: [] },
      });
      expect(html).toContain('chat-banner');
      expect(html.toLowerCase()).toContain('offline');
      const inputMatch = /<textarea[^>]*id="workout-chat-input"[^>]*>/.exec(html);
      expect(inputMatch[0]).toContain('disabled');
      const btnMatch = /<button[^>]*data-a="workout-chat:send"[^>]*>/.exec(html);
      expect(btnMatch[0]).toContain('disabled');
    });

    it('escapes malicious chat message content', () => {
      const html = renderDashboardTab({
        ...openDetailArgs,
        workoutChat: {
          workoutId: 'w-rich',
          messages: [{ role: 'user', content: '<img src=x onerror=alert(1)>', status: 'done' }],
        },
      });
      expect(html).not.toContain('<img src=x');
      expect(html).toContain('&lt;img');
    });
  });

  describe('Ask-the-coach Q&A section (replaces the old coach-conversation placeholder)', () => {
    it('renders the real Q&A section alongside the real AI chat, distinct from it', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: feedOf([RICH_FIT_WORKOUT]),
        detailId: 'w-rich',
        workoutChat: { workoutId: 'w-rich', messages: [] },
        askCoach: { feedback: [], form: { body: '' }, submit: { status: 'idle', error: null } },
      });
      expect(html).toContain('id="ask-coach"');
      expect(html).toContain('Ask your coach');
      // The honest "coming soon" placeholder is gone -- replaced, not additive.
      expect(html).not.toContain('id="coach-conversation"');
      expect(html).not.toContain('coming soon');
      // Still has the real, working AI chat -- unrelated, unaffected.
      expect(html).toContain('Ask your coach about this workout');
      expect(html).toContain('id="workout-chat-input"');
    });

    it('still renders even when the real AI chat is absent (workoutChat null)', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: feedOf([RICH_FIT_WORKOUT]),
        detailId: 'w-rich',
        workoutChat: null,
        askCoach: { feedback: [], form: { body: '' }, submit: { status: 'idle', error: null } },
      });
      expect(html).toContain('id="ask-coach"');
      expect(html).not.toContain('Ask your coach about this workout');
    });

    it('filters the raw feedback list down to just this workout, by workout_id', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: feedOf([RICH_FIT_WORKOUT]),
        detailId: 'w-rich',
        workoutChat: null,
        askCoach: {
          feedback: [
            { id: 'f1', body: 'about this workout', workout_id: 'w-rich' },
            { id: 'f2', body: 'about a different workout', workout_id: 'w-other' },
            { id: 'f3', body: 'a planned-session question', session_date: '2026-06-01', session_sport: 'swim_ow' },
          ],
          form: { body: '' },
          submit: { status: 'idle', error: null },
        },
      });
      expect(html).toContain('about this workout');
      expect(html).not.toContain('about a different workout');
      expect(html).not.toContain('a planned-session question');
    });

    it('renders no input box in read-only mode (form: null -- the coach roster call site)', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: feedOf([RICH_FIT_WORKOUT]),
        detailId: 'w-rich',
        workoutChat: null,
        askCoach: { feedback: [], form: null },
      });
      expect(html).toContain('id="ask-coach"');
      expect(html).not.toContain('data-form="askCoach"');
      expect(html).not.toContain('data-a="ask-coach:submit"');
    });
  });

  describe('sync + manual-entry actions (original Log tab markup, unchanged)', () => {
    it('shows a backend-needed notice, omitting the feed and actions, when backend is not configured', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, backendConfigured: false, feed: [] });
      expect(html).toContain('sign in');
      expect(html).not.toContain('data-a="sync:start"');
      expect(html).not.toContain('<svg');
    });

    it('always shows the primary sync button ahead of the (collapsed) manual section and the feed', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: feedOf([CROSS_TRAIN_WORKOUT]) });
      const syncIdx = html.indexOf('data-a="sync:start"');
      const toggleIdx = html.indexOf('data-a="log:toggle-manual"');
      const feedIdx = html.indexOf('Cross-train');
      expect(syncIdx).toBeGreaterThan(-1);
      expect(toggleIdx).toBeGreaterThan(syncIdx);
      expect(feedIdx).toBeGreaterThan(toggleIdx);
    });

    it('shows "Sync from watch" idle label, enabled, when online and idle', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: [] });
      expect(html).toContain('Sync from watch');
      const btnMatch = /<button[^>]*data-a="sync:start"[^>]*>/.exec(html);
      expect(btnMatch[0]).not.toContain('disabled');
    });

    it('shows a busy "Syncing…" label and disables the button while syncing', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: [], sync: { status: 'syncing', message: null },
      });
      expect(html).toContain('Syncing');
      const btnMatch = /<button[^>]*data-a="sync:start"[^>]*>/.exec(html);
      expect(btnMatch[0]).toContain('disabled');
    });

    it('disables the sync button while offline', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: [], online: false });
      const btnMatch = /<button[^>]*data-a="sync:start"[^>]*>/.exec(html);
      expect(btnMatch[0]).toContain('disabled');
    });

    it('shows a success result line with the ok treatment', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS, feed: [], sync: { status: 'success', message: '2 new workouts synced' },
      });
      expect(html).toContain('conn-result ok');
      expect(html).toContain('2 new workouts synced');
    });

    it('shows an error result line verbatim with the fail treatment', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: [],
        sync: { status: 'error', message: 'sync not configured for this athlete' },
      });
      expect(html).toContain('conn-result fail');
      expect(html).toContain('sync not configured for this athlete');
    });

    it('collapses the manual entry/upload section by default, showing only the toggle', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: [] });
      expect(html).toContain('Log manually / upload a file');
      expect(html).not.toContain('data-a="log:file-select"');
      expect(html).not.toContain('data-form="log" data-field="date"');
    });

    it('expands the manual form and upload input when manualOpen is true', () => {
      const html = renderDashboardTab({ ...DASHBOARD_BASE_ARGS, feed: [], manualOpen: true });
      expect(html).toContain('data-a="log:file-select"');
      expect(html).toContain('data-form="log" data-field="date"');
      expect(html).toContain('Hide manual entry');
    });
  });

  describe('the CTL/ATL/TSB load chart, relocated here from the Plan tab', () => {
    it('renders the chart above the actions and the feed when data is present', () => {
      const html = renderDashboardTab({
        ...DASHBOARD_BASE_ARGS,
        feed: feedOf([CROSS_TRAIN_WORKOUT]),
        load: {
          status: 'ready',
          data: { ctl_atl_tsb: [['2026-08-01', 10, 5, 5], ['2026-08-02', 11, 6, 5]] },
          error: null,
        },
      });
      const chartIdx = html.indexOf('<svg');
      const syncIdx = html.indexOf('data-a="sync:start"');
      const feedIdx = html.indexOf('Cross-train');
      expect(chartIdx).toBeGreaterThan(-1);
      expect(chartIdx).toBeLessThan(syncIdx);
      expect(syncIdx).toBeLessThan(feedIdx);
    });
  });
});

describe('renderApp plan session detail view (click-to-detail)', () => {
  // A far-future week so pickCurrentAndNextWeek always treats it as "This
  // week", regardless of the real wall clock the test suite runs under.
  const FAR_FUTURE_WEEK = '2099-W01';
  const weekMonday = isoWeekMonday(FAR_FUTURE_WEEK);

  // Real generated-text shapes from the task brief -- the swim main-set
  // format and the strength bullet format.
  const MAIN_SET_SESSION = {
    id: 's-main-set',
    date: dateKey(weekMonday),
    sport: 'swim_pool',
    source: 'ai_coach',
    duration_min: 65,
    distance_m: 2400,
    intensity: { zone: 'Z2' },
    purpose: 'pool practice — no pool coach on hand, structure authored below',
    structure: 'Warm-up: 600m easy, building to Z2 pace (1:35-1:39/100m) by the end.\n'
      + 'Main set: 8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume for the week.\n'
      + 'Cool-down: 200m easy choice of stroke.',
  };

  const STRENGTH_SESSION = {
    id: 's-strength',
    date: dateKey(addDays(weekMonday, 1)),
    sport: 'strength',
    source: 'ai_coach',
    duration_min: 30,
    distance_m: null,
    intensity: {},
    purpose: 'dryland shoulder strength — moderate (2 days before the 5-hour swim)',
    structure: 'Rotator-cuff / scapular-stability core (2 sets x 10 reps each):\n'
      + '  - Band external rotation\n'
      + '  - Prone Y-raise',
  };

  const NO_STRUCTURE_SESSION = {
    id: 's-coach-pool',
    date: dateKey(addDays(weekMonday, 2)),
    sport: 'swim_pool',
    source: 'pool_coach',
    duration_min: 90,
    distance_m: null,
    intensity: {},
    purpose: 'coached USMS pool — content assigned by coach',
    structure: null,
  };

  const WEEK = {
    iso_week: FAR_FUTURE_WEEK,
    meso_block: 'base',
    focus: 'aerobic base',
    target_volume_m: 12000,
    sessions: [MAIN_SET_SESSION, STRENGTH_SESSION, NO_STRUCTURE_SESSION],
    adaptation_rationale: null,
  };

  const PLAN_DATA = {
    athlete: { name: 'Renee' }, events: [], macro: { blocks: [] }, weeks: [WEEK],
  };

  // Build 1 (Log+History merge): the CTL/ATL/TSB load chart moved off the
  // Plan tab entirely, into the merged Dashboard tab -- renderApp must never
  // render it, even when a `load` field is (incorrectly) still passed in.
  it('never renders the training-load chart -- it moved to the Dashboard tab (Build 1)', () => {
    const html = renderApp({ ...PLAN_DATA, load: { status: 'ready', data: { ctl_atl_tsb: [['2026-08-01', 10, 5, 5]] } } }, null);
    expect(html).not.toContain('load-chart-svg');
    expect(html).not.toContain('<svg');
  });

  it('renderSession emits a clickable data-a/data-id for each session row', () => {
    const html = renderApp(PLAN_DATA, null);
    expect(html).toContain(`data-a="session:open" data-id="${MAIN_SET_SESSION.id}"`);
    expect(html).toContain(`data-a="session:open" data-id="${STRENGTH_SESSION.id}"`);
  });

  it('derives a specific title from the Main set line instead of the generic purpose-derived label', () => {
    const html = renderApp(PLAN_DATA, null);
    expect(html).toContain('8 x 300m @ Z2 (1:35-1:39/100m)');
    expect(html).not.toContain('>Pool practice<');
  });

  it('regression: renderSession compact-row subtitle for a race-tagged session is unchanged -- still just the post-dash fragment, not the full purpose', () => {
    // "race name — descriptive fragment" is the shape splitPurpose/detail
    // was designed for; the compact week-view row has no room for a full
    // sentence, so it must keep showing only the terse post-dash fragment
    // here. This must NOT regress when renderPlanSessionDetail's Purpose
    // section switches to the full, un-split purpose text.
    const RACE_SESSION = {
      id: 's-race',
      date: dateKey(addDays(weekMonday, 4)),
      sport: 'swim_ow',
      source: 'ai_coach',
      duration_min: 240,
      distance_m: 10000,
      intensity: { zone: 'Z2' },
      purpose: 'Bear Lake Monster 10K (A race) — dress rehearsal, negative-split',
      structure: null,
    };
    const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [RACE_SESSION] }] };
    const html = renderApp(data, null); // week view (compact rows), not detail view
    expect(html).toContain('dress rehearsal, negative-split');
    expect(html).not.toContain('Bear Lake Monster 10K (A race) — dress rehearsal');
  });

  it('opens the full session detail (block-parsed structure + back button) when detailId matches', () => {
    const html = renderApp(PLAN_DATA, MAIN_SET_SESSION.id);
    expect(html).toContain('data-a="session:back"');
    expect(html).not.toContain('data-a="session:open"');
    // Warm-up/Main set/Cool-down are now their own titled sections (block-
    // parsed via plan.js's parseStructureBlocks), not one flat pre-wrap blob
    // with the raw "Label:" prefix still in the text.
    expect(html).toContain('<h4>Warm-up</h4>');
    expect(html).toContain('600m easy, building to Z2 pace');
    expect(html).toContain('<h4>Main set</h4>');
    // The Main-set block's one interval renders as a distinct numbered item.
    expect(html).toContain('Interval 1');
    expect(html).toContain('8 x 300m @ Z2 (1:35-1:39/100m), 15s rest');
    expect(html).toContain('<h4>Cool-down</h4>');
    expect(html).toContain('200m easy choice of stroke.');
  });

  it('renders the strength session detail with indentation-preserving bullets intact, as its own titled block', () => {
    const html = renderApp(PLAN_DATA, STRENGTH_SESSION.id);
    expect(html).toContain('<h4>Rotator-cuff / scapular-stability core (2 sets x 10 reps each)</h4>');
    expect(html).toContain('  - Band external rotation');
    expect(html).toContain('  - Prone Y-raise');
  });

  it('does not render a Garmin download button when structured is absent', () => {
    const html = renderApp(PLAN_DATA, MAIN_SET_SESSION.id);
    expect(html).not.toContain('session:garmin-download');
  });

  it('renders a Garmin download button for a session with structured populated', () => {
    const STRUCTURED_SESSION = {
      id: 's-structured',
      date: dateKey(addDays(weekMonday, 5)),
      sport: 'swim_pool',
      source: 'ai_coach',
      duration_min: 45,
      distance_m: 1600,
      intensity: { zone: 'Z3' },
      purpose: 'garmin-exportable session',
      structure: 'Main set: 4x200 @ Z3',
      structured: {
        schema_version: 1,
        items: [
          {
            schema_version: 1,
            kind: 'step',
            label: '4x200 @ Z3',
            role: 'interval',
            duration_kind: 'distance_m',
            duration_value: 800,
            modality: 'swim',
            equipment: [],
          },
        ],
      },
    };
    const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [...WEEK.sessions, STRUCTURED_SESSION] }] };
    const html = renderApp(data, STRUCTURED_SESSION.id);
    expect(html).toContain(`data-a="session:garmin-download" data-id="${STRUCTURED_SESSION.id}"`);
    expect(html).toContain('Download for Garmin');
  });

  // The wireless counterpart to the download button above -- the athlete
  // asked for a per-session push, not just a chat tool. Same
  // structured-only gating: a prose-only session has nothing real to push.
  describe('push to Garmin button', () => {
    const PUSHABLE = {
      id: 's-pushable',
      date: dateKey(weekMonday),
      sport: 'swim_pool',
      source: 'ai_coach',
      duration_min: 40,
      distance_m: 1600,
      intensity: { zone: 'Z3' },
      purpose: 'Threshold set',
      structure: 'Main set: 4x200 @ Z3',
      structured: {
        items: [{
          kind: 'step', label: '4x200 @ Z3', role: 'interval', duration_kind: 'distance_m',
          duration_value: 800, modality: 'swim', equipment: [],
        }],
      },
    };
    const withPushable = (push) => ({
      ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [PUSHABLE] }], sessionPush: push,
    });

    it('renders a push button for a session with structured data', () => {
      const html = renderApp(withPushable(null), PUSHABLE.id);
      expect(html).toContain(`data-a="session:push-intervals" data-id="${PUSHABLE.id}"`);
      expect(html).toContain('Push to Garmin');
    });

    it('renders NO push button for a prose-only session -- nothing real to push', () => {
      const html = renderApp(PLAN_DATA, NO_STRUCTURE_SESSION.id);
      expect(html).not.toContain('session:push-intervals');
    });

    it('shows a pushing state while in flight', () => {
      const html = renderApp(withPushable({ id: PUSHABLE.id, status: 'pushing', message: null }), PUSHABLE.id);
      expect(html).toContain('Pushing');
    });

    it('shows a success message after a push', () => {
      const push = { id: PUSHABLE.id, status: 'success', message: 'Sent to Garmin via Intervals.icu.' };
      const html = renderApp(withPushable(push), PUSHABLE.id);
      expect(html).toContain('Sent to Garmin via Intervals.icu.');
    });

    it('shows an escaped error message when the push fails', () => {
      const push = { id: PUSHABLE.id, status: 'error', message: '<img src=x onerror=alert(1)>' };
      const html = renderApp(withPushable(push), PUSHABLE.id);
      expect(html).not.toContain('<img src=x');
      expect(html).toContain('&lt;img');
    });

    it('ignores a push state belonging to a different session', () => {
      const push = { id: 'some-other-session', status: 'success', message: 'Sent to Garmin via Intervals.icu.' };
      const html = renderApp(withPushable(push), PUSHABLE.id);
      expect(html).not.toContain('Sent to Garmin via Intervals.icu.');
    });
  });

  it('renders a sensible, non-blank detail view for a session with no structure at all', () => {
    const html = renderApp(PLAN_DATA, NO_STRUCTURE_SESSION.id);
    expect(html).toContain('data-a="session:back"');
    expect(html).toContain('Coached USMS pool'); // falls back to the purpose-derived title
    expect(html).toContain('content assigned by coach'); // the post-dash purpose detail
  });

  it('regression: detail view Purpose section for a structure-less session shows ONLY the post-dash detail fragment, never the full purpose -- avoids duplicating the purpose-derived header title', () => {
    // When `structure` is absent, deriveSessionTitle's purposeTitle()
    // fallback makes the header title the PRE-dash half of `purpose`
    // itself (e.g. "Coached USMS pool"). If the Purpose section below were
    // to show the full, un-split purpose ("coached USMS pool -- content
    // assigned by coach"), it would literally repeat the header title as a
    // prefix. This must stay split to the post-dash fragment only, exactly
    // as it behaved before the full-purpose fix landed for structure-
    // bearing sessions.
    const html = renderApp(PLAN_DATA, NO_STRUCTURE_SESSION.id);
    const purposeMatch = html.match(/<h4>Purpose<\/h4>\s*<p class="detail-notes">(.*?)<\/p>/s);
    expect(purposeMatch).not.toBeNull();
    expect(purposeMatch[1]).toBe('content assigned by coach');
    expect(purposeMatch[1]).not.toContain('Coached USMS pool');
    expect(purposeMatch[1]).not.toContain('coached USMS pool');
  });

  it('detail view Purpose section shows the full, un-split purpose text for a single-statement purpose that contains an internal em-dash (not just the post-dash fragment)', () => {
    // Real shape introduced by PR #83's _no_coach_pool_purpose(): one
    // complete purpose statement that happens to use an em-dash as internal
    // punctuation, not a "race name — descriptive fragment" pair. Splitting
    // this on the dash (as sessionDisplay().detail does) leaves a meaningless
    // fragment ("base-block emphasis") -- the detail view must show the
    // whole sentence instead.
    const NO_COACH_POOL_SESSION = {
      id: 's-no-coach-pool',
      date: dateKey(addDays(weekMonday, 3)),
      sport: 'swim_pool',
      source: 'ai_coach',
      duration_min: 60,
      distance_m: 2200,
      intensity: { zone: 'Z2' },
      purpose: 'Continuous aerobic volume — base-block emphasis',
      structure: 'Warm-up: 400m easy.\n'
        + 'Main set: 6 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume for the week.\n'
        + 'Cool-down: 200m easy.',
    };
    const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [NO_COACH_POOL_SESSION] }] };
    const html = renderApp(data, NO_COACH_POOL_SESSION.id);
    expect(html).toContain('<h4>Purpose</h4>');
    expect(html).toContain('Continuous aerobic volume — base-block emphasis');
  });

  it('falls back to the ordinary week cards when detailId does not match any session', () => {
    const html = renderApp(PLAN_DATA, 'no-such-id');
    expect(html).toContain('data-a="session:open"');
    expect(html).not.toContain('data-a="session:back"');
  });

  it('renders the ordinary week cards when detailId is null/undefined', () => {
    const html = renderApp(PLAN_DATA);
    expect(html).toContain('data-a="session:open"');
    expect(html).not.toContain('data-a="session:back"');
  });

  it('escapes malicious structure content (no raw HTML injection)', () => {
    const malicious = { ...MAIN_SET_SESSION, id: 's-malicious', structure: '<img src=x onerror=alert(1)>' };
    const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [malicious] }] };
    const html = renderApp(data, 's-malicious');
    expect(html).not.toContain('<img src=x');
    expect(html).toContain('&lt;img');
  });

  describe('session.structured (PR #91 WorkoutStructure) tree-walk rendering, Phase A', () => {
    // A synthetic WorkoutStructure matching PR #91's real model shape --
    // one narrated top-level warmup step and a count-based repeat of
    // strength-shaped steps, enough to exercise both branches of the walk.
    const STRUCTURED_SESSION = {
      ...MAIN_SET_SESSION,
      id: 's-structured',
      date: dateKey(addDays(weekMonday, 5)),
      structured: {
        items: [
          {
            kind: 'step', label: 'Easy swim', role: 'warmup', duration_kind: 'distance_m',
            duration_value: 400, target: { basis: 'zone', zone: 'Z2' }, load: null,
            modality: 'swim', stroke: null, equipment: [], exercise_name: null,
          },
          {
            kind: 'repeat', repeat_mode: 'count', count: 3, duration_s: null, interval_s: null,
            steps: [
              {
                kind: 'step', label: '100 build', role: 'interval', duration_kind: 'distance_m',
                duration_value: 100, target: { basis: 'zone', zone: 'Z3' }, load: null,
                modality: 'swim', stroke: null, equipment: [], exercise_name: null,
              },
            ],
          },
        ],
      },
    };

    it('renders session.structured via the generic tree-walk, not the polished per-block prose parser', () => {
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [STRUCTURED_SESSION] }] };
      const html = renderApp(data, STRUCTURED_SESSION.id);
      expect(html).toContain('<h4>Workout</h4>');
      expect(html).toContain('struct-tree');
      expect(html).toContain('Warm-up: Easy swim');
      expect(html).toContain('3 x:');
      expect(html).toContain('100 build');
      // NOT the polished per-block prose headings (Phase B, not this pass) --
      // proves the structured branch actually took priority over
      // parseStructureBlocks/renderStructureBlock for this session.
      expect(html).not.toContain('<h4>Main set</h4>');
      expect(html).not.toContain('Interval 1');
    });

    it('regression: a session with structured absent/null still falls back to the prose block parser unchanged', () => {
      // MAIN_SET_SESSION itself carries no `structured` key at all (real
      // shape for a legacy, un-regenerated session) -- this is the same
      // fixture the earlier "block-parsed structure" test above already
      // exercises; asserted again here, explicitly, as the fallback half of
      // this Phase A feature's regression coverage.
      const html = renderApp(PLAN_DATA, MAIN_SET_SESSION.id);
      expect(html).not.toContain('<h4>Workout</h4>');
      expect(html).not.toContain('struct-tree');
      expect(html).toContain('<h4>Main set</h4>');
      expect(html).toContain('Interval 1');
    });

    it('regression: a session with structured explicitly null (real PR #91 shape for a legacy DB row) also falls back to prose', () => {
      const explicitNull = { ...MAIN_SET_SESSION, id: 's-explicit-null', structured: null };
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [explicitNull] }] };
      const html = renderApp(data, 's-explicit-null');
      expect(html).not.toContain('<h4>Workout</h4>');
      expect(html).toContain('<h4>Main set</h4>');
    });

    it('escapes malicious structured step text (no raw HTML injection)', () => {
      const malicious = {
        ...STRUCTURED_SESSION,
        id: 's-structured-malicious',
        structured: {
          items: [{
            kind: 'step', label: '<img src=x onerror=alert(1)>', role: 'warmup', duration_kind: 'open',
            duration_value: null, target: null, load: null, modality: 'swim', stroke: null,
            equipment: [], exercise_name: null,
          }],
        },
      };
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [malicious] }] };
      const html = renderApp(data, 's-structured-malicious');
      expect(html).not.toContain('<img src=x');
      expect(html).toContain('&lt;img');
    });

    it('renders a step with a referenceUrl as a clickable link, target=_blank, opening in a new tab safely', () => {
      const withLink = {
        ...STRUCTURED_SESSION,
        id: 's-structured-link',
        structured: {
          items: [
            {
              kind: 'step', label: 'Goblet squat', role: 'steady', duration_kind: 'reps',
              duration_value: 10, target: null, load: { basis: 'bodyweight', value: null },
              modality: 'strength', stroke: null, equipment: [], exercise_name: 'Goblet squat',
              reference_url: 'https://www.rehabhero.ca/exercise/goblet-squat',
            },
          ],
        },
      };
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [withLink] }] };
      const html = renderApp(data, 's-structured-link');
      expect(html).toContain(
        '<a href="https://www.rehabhero.ca/exercise/goblet-squat" target="_blank" rel="noopener noreferrer" class="struct-text">Goblet squat</a>',
      );
    });

    it('renders a step without a referenceUrl as a plain span, not a link', () => {
      // STRUCTURED_SESSION's own steps carry no reference_url.
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [STRUCTURED_SESSION] }] };
      const html = renderApp(data, STRUCTURED_SESSION.id);
      expect(html).toContain('<span class="struct-text">Warm-up: Easy swim</span>');
      expect(html).not.toContain('<a href="https://www.rehabhero.ca');
    });

    it('escapes a malicious javascript: reference_url and quote-injecting content (no raw HTML injection)', () => {
      const malicious = {
        ...STRUCTURED_SESSION,
        id: 's-structured-malicious-url',
        structured: {
          items: [{
            kind: 'step', label: 'Goblet squat', role: 'steady', duration_kind: 'reps',
            duration_value: 10, target: null, load: null, modality: 'strength', stroke: null,
            equipment: [], exercise_name: 'Goblet squat',
            reference_url: 'javascript:alert(1)"><img src=x onerror=alert(1)>',
          }],
        },
      };
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [malicious] }] };
      const html = renderApp(data, 's-structured-malicious-url');
      expect(html).not.toContain('<img src=x');
      expect(html).not.toContain('"><img');
      // The URL is rejected outright by safeHref (not an http(s) scheme), so
      // it never reaches the markup at all -- strictly safer than emitting it
      // escaped into an href, which is what this test originally asserted.
      expect(html).not.toContain('javascript:');
      expect(html).not.toContain('&quot;&gt;&lt;img');
      expect(html).toContain('<span class="struct-text">Goblet squat</span>');
    });

    // Escaping alone does NOT defuse a `javascript:` URL -- esc() only
    // neutralizes the quote/angle-bracket injection above; the browser will
    // still happily execute `href="javascript:alert(1)"` on tap, because
    // nothing about that string needs escaping to be dangerous. The scheme
    // itself has to be rejected. `reference_url` is a plain `str` on
    // WorkoutStep with no validation, reachable from a coach-authored
    // `session_overrides.structured` payload, so this is a real path.
    it('does not emit a javascript: href at all -- the scheme is rejected, not merely escaped', () => {
      const malicious = {
        ...STRUCTURED_SESSION,
        id: 's-structured-js-scheme',
        structured: {
          items: [{
            kind: 'step', label: 'Goblet squat', role: 'steady', duration_kind: 'reps',
            duration_value: 10, target: null, load: null, modality: 'strength', stroke: null,
            equipment: [], exercise_name: 'Goblet squat',
            reference_url: 'javascript:alert(1)',
          }],
        },
      };
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [malicious] }] };
      const html = renderApp(data, 's-structured-js-scheme');
      expect(html).not.toContain('javascript:');
      // Falls back to the plain, un-linked rendering rather than dropping
      // the step -- the athlete still sees the exercise.
      expect(html).toContain('<span class="struct-text">Goblet squat</span>');
    });

    it('rejects other non-http(s) schemes too, and is not fooled by case or leading whitespace', () => {
      const cases = [
        'JaVaScRiPt:alert(1)',
        '  javascript:alert(1)',
        'data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
        'vbscript:msgbox(1)',
      ];
      for (const url of cases) {
        const session = {
          ...STRUCTURED_SESSION,
          id: 's-scheme-probe',
          structured: {
            items: [{
              kind: 'step', label: 'Goblet squat', role: 'steady', duration_kind: 'reps',
              duration_value: 10, target: null, load: null, modality: 'strength', stroke: null,
              equipment: [], exercise_name: 'Goblet squat', reference_url: url,
            }],
          },
        };
        const html = renderApp({ ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [session] }] }, 's-scheme-probe');
        expect(html, `scheme should be rejected: ${url}`).not.toContain('<a href=');
      }
    });

    it('still links a plain http(s) URL', () => {
      const session = {
        ...STRUCTURED_SESSION,
        id: 's-scheme-ok',
        structured: {
          items: [{
            kind: 'step', label: 'Goblet squat', role: 'steady', duration_kind: 'reps',
            duration_value: 10, target: null, load: null, modality: 'strength', stroke: null,
            equipment: [], exercise_name: 'Goblet squat',
            reference_url: 'http://example.org/goblet',
          }],
        },
      };
      const html = renderApp({ ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [session] }] }, 's-scheme-ok');
      expect(html).toContain('<a href="http://example.org/goblet"');
    });

    it('a step whose label matches the real technique-cue vocabulary renders as an expandable <details> with the cue text, collapsed by default', () => {
      const session = {
        ...STRUCTURED_SESSION,
        id: 's-with-cue',
        structured: {
          items: [{
            kind: 'step', role: 'interval', duration_kind: 'distance_m', duration_value: 800,
            label: '4 x 200m broken-distance, descend 1-4 from Z3 toward Z4 -- race-pace-adjacent emphasis.',
            target: { basis: 'zone', zone: 'Z3' }, load: null, modality: 'swim', stroke: null, equipment: [],
          }],
        },
      };
      const html = renderApp({ ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [session] }] }, 's-with-cue');
      expect(html).toContain('<details class="struct-line struct-line-step struct-step-toggle"');
      expect(html).toContain('<summary class="struct-summary">');
      // The step's own label/detail markup is unchanged inside the summary
      // (role="interval" is a top-level narrated role, so it keeps its
      // "Main set: " prefix exactly as renderStructuredStep already adds).
      expect(html).toContain('<span class="struct-text">Main set: 4 x 200m broken-distance');
      expect(html).toContain('class="struct-cue"');
      expect(html).toMatch(/negative-split|descend/i);
      // Not present as raw <details open> -- collapsed by default is the
      // native <details> default (no `open` attribute emitted).
      expect(html).not.toContain('<details class="struct-line struct-line-step struct-step-toggle" open');
    });

    it('a step whose label matches no cue vocabulary stays a plain (non-expandable) line -- regression, no generic placeholder cue', () => {
      const html = renderApp(
        { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [STRUCTURED_SESSION] }] },
        STRUCTURED_SESSION.id,
      );
      expect(html).not.toContain('struct-step-toggle');
      expect(html).not.toContain('struct-cue');
    });

    it('escapes a malicious cue string (defensive -- today\'s cue vocabulary is all static, hand-authored text, but esc() is still applied)', () => {
      // stepCoachingCue only ever returns a hand-authored string from the
      // static vocabulary today, so this can't happen via a real session --
      // this proves the renderer itself doesn't special-case cue text as
      // trusted HTML, same defense-in-depth already applied to every other
      // field on this line.
      const session = {
        ...STRUCTURED_SESSION,
        id: 's-cue-escape-probe',
        structured: {
          items: [{
            kind: 'step', role: 'interval', duration_kind: 'distance_m', duration_value: 100,
            label: '2 x 100m broken-distance', target: { basis: 'zone', zone: 'Z3' }, load: null,
            modality: 'swim', stroke: null, equipment: [],
          }],
        },
      };
      const html = renderApp({ ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [session] }] }, 's-cue-escape-probe');
      // The real broken-distance cue text renders escaped/plain, no raw tags.
      expect(html).not.toMatch(/<p class="struct-cue">[^<]*<(?!\/p)/);
    });
  });

  describe('per-session zone-distribution summary', () => {
    const SESSION_WITH_ZONES = {
      ...MAIN_SET_SESSION,
      id: 's-zone-dist',
      structured: {
        items: [
          {
            kind: 'step', label: 'Easy swim', role: 'warmup', duration_kind: 'distance_m',
            duration_value: 400, target: { basis: 'zone', zone: 'Z2' }, load: null,
            modality: 'swim', stroke: null, equipment: [], exercise_name: null,
          },
          {
            kind: 'step', label: '8 x 300m', role: 'interval', duration_kind: 'distance_m',
            duration_value: 2400, target: { basis: 'zone', zone: 'Z3' }, load: null,
            modality: 'swim', stroke: null, equipment: [], exercise_name: null,
          },
        ],
      },
    };

    it('renders a "Zone breakdown" section with the computed per-zone summary', () => {
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [SESSION_WITH_ZONES] }] };
      const html = renderApp(data, SESSION_WITH_ZONES.id);
      expect(html).toContain('<h4>Zone breakdown</h4>');
      expect(html).toContain('Z2: 400 m');
      expect(html).toContain('Z3: 2,400 m');
    });

    it('renders no Zone breakdown section for a legacy prose-only session (no structured step data to bucket)', () => {
      const html = renderApp(PLAN_DATA, MAIN_SET_SESSION.id);
      expect(html).not.toContain('Zone breakdown');
    });
  });

  describe('"Training rationale" for structured-IR sessions (parity with the legacy prose Why: block)', () => {
    const SESSION_WITH_RATIONALE = {
      ...MAIN_SET_SESSION,
      id: 's-structured-rationale',
      structured: {
        items: [
          {
            kind: 'step', label: '8 x 300m @ Z2', role: 'interval', duration_kind: 'distance_m',
            duration_value: 2400, target: { basis: 'zone', zone: 'Z2' }, load: null,
            modality: 'swim', stroke: null, equipment: [], exercise_name: null,
          },
          {
            kind: 'step', role: 'open', duration_kind: 'open', duration_value: null,
            label: 'Why: continuous aerobic-volume emphasis (base-block phase).',
            target: null, load: null, modality: 'swim', stroke: null, equipment: [], exercise_name: null,
          },
        ],
      },
    };

    it('renders a "Training rationale" section for a structured session carrying a trailing Why step', () => {
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [SESSION_WITH_RATIONALE] }] };
      const html = renderApp(data, SESSION_WITH_RATIONALE.id);
      const headings = html.match(/<h4>[^<]*<\/h4>/g) || [];
      expect(headings.some((h) => h.toLowerCase() === '<h4>training rationale</h4>')).toBe(true);
      expect(html).toContain('continuous aerobic-volume emphasis (base-block phase).');
    });

    it('the Why step does not also appear as an undifferentiated line inside the Workout struct-tree', () => {
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [SESSION_WITH_RATIONALE] }] };
      const html = renderApp(data, SESSION_WITH_RATIONALE.id);
      // The rationale text appears exactly once (inside Training rationale),
      // not a second time inside the struct-tree's plain line rendering.
      const occurrences = html.split('continuous aerobic-volume emphasis (base-block phase).').length - 1;
      expect(occurrences).toBe(1);
    });

    it('a structured session with no Why step gets no Training rationale section (parity: same as legacy prose with no Why: block)', () => {
      const noRationaleSession = {
        ...MAIN_SET_SESSION,
        id: 's-structured-no-rationale',
        structured: {
          items: [
            {
              kind: 'step', label: '8 x 300m @ Z2', role: 'interval', duration_kind: 'distance_m',
              duration_value: 2400, target: { basis: 'zone', zone: 'Z2' }, load: null,
              modality: 'swim', stroke: null, equipment: [], exercise_name: null,
            },
          ],
        },
      };
      const data = { ...PLAN_DATA, weeks: [{ ...WEEK, sessions: [noRationaleSession] }] };
      const html = renderApp(data, noRationaleSession.id);
      const headings = (html.match(/<h4>[^<]*<\/h4>/g) || []).map((h) => h.toLowerCase());
      expect(headings).not.toContain('<h4>training rationale</h4>');
    });
  });
});

describe('renderWeekCard race-week checklist (engine/swim_coach/models.py RaceWeekChecklistItem)', () => {
  const RACE_WEEK = '2099-W02';
  const raceWeekMonday = isoWeekMonday(RACE_WEEK);

  const BASE_WEEK = {
    iso_week: RACE_WEEK,
    meso_block: 'taper',
    focus: 'taper',
    target_volume_m: 6000,
    sessions: [],
    adaptation_rationale: null,
  };

  const CHECKLIST = [
    {
      date: dateKey(addDays(raceWeekMonday, 8)), // deliberately past this week's own Sunday --
      category: 'carb_load', // mirrors a race that doesn't fall on a Monday (see library/16-race-week.md)
      label: 'Begin carbohydrate loading: 10-12 g/kg body weight/day.',
    },
    {
      date: dateKey(addDays(raceWeekMonday, 6)),
      category: 'bodywork',
      label: 'Light activation/relaxation bodywork or massage session if available.',
    },
    {
      date: dateKey(raceWeekMonday),
      category: 'logistics',
      label: 'Confirm on-water support (kayak/boat escort) with race organizers.',
    },
  ];

  function planData(weeks) {
    return { athlete: { name: 'Renee' }, events: [], macro: { blocks: [] }, weeks };
  }

  it('renders nothing when race_week_checklist is empty (an ordinary taper week)', () => {
    const html = renderApp(planData([{ ...BASE_WEEK, race_week_checklist: [] }]), null);
    expect(html).not.toContain('race-week-checklist');
  });

  it('renders nothing when race_week_checklist is missing entirely (older persisted weeks)', () => {
    const html = renderApp(planData([BASE_WEEK]), null);
    expect(html).not.toContain('race-week-checklist');
  });

  it('renders every item, its category label, and its date when populated', () => {
    const html = renderApp(planData([{ ...BASE_WEEK, race_week_checklist: CHECKLIST }]), null);
    expect(html).toContain('race-week-checklist');
    expect(html).toContain('Carb-load');
    expect(html).toContain('Bodywork');
    expect(html).toContain('Logistics');
    expect(html).toContain('Begin carbohydrate loading');
    expect(html).toContain('kayak/boat escort');
  });

  it('shows a checklist date that falls outside this WeekPlan\'s own 7 days without crashing', () => {
    // The carb-load item above is dated 8 days after raceWeekMonday -- past
    // this week's own Sunday -- exactly the "race isn't on a Monday" case
    // library/16-race-week.md documents. Rendering must not silently drop
    // or crash on it.
    const html = renderApp(planData([{ ...BASE_WEEK, race_week_checklist: CHECKLIST }]), null);
    const expectedDate = formatShortDate(addDays(raceWeekMonday, 8));
    expect(html).toContain(expectedDate);
  });

  it('escapes malicious content in a checklist item label', () => {
    const malicious = [
      { date: dateKey(raceWeekMonday), category: 'logistics', label: '<img src=x onerror=alert(1)>' },
    ];
    const html = renderApp(planData([{ ...BASE_WEEK, race_week_checklist: malicious }]), null);
    expect(html).not.toContain('<img src=x onerror=alert(1)>');
    expect(html).toContain('&lt;img');
  });
});

describe('renderSettingsTab', () => {
  const baseArgs = {
    identity: null,
    identityError: null,
    backendConfigured: false,
    profileForm: {},
    profileLoad: { status: 'idle', error: null },
    profileSubmit: { status: 'idle', message: null },
  };

  it('shows the Google sign-in button when signed out, with no backend-URL panel', () => {
    const html = renderSettingsTab(baseArgs);
    expect(html).toContain('google-signin-btn');
    // The paste-token-era backend-URL + Test-connection panel is gone --
    // this is the leftover this build removes (see CLAUDE.md's DOD).
    expect(html).not.toContain('settings-base-url');
    expect(html).not.toContain('data-a="settings:save"');
    expect(html).not.toContain('data-a="settings:test"');
    expect(html).not.toContain('Backend URL');
  });

  it('shows the signed-in identity and a Sign out button once signed in', () => {
    const html = renderSettingsTab({
      ...baseArgs,
      identity: { name: 'Renee', athlete: 'renee', role: 'athlete' },
    });
    expect(html).toContain('Signed in as');
    expect(html).toContain('data-a="identity:signout"');
    expect(html).not.toContain('settings-base-url');
  });

  it('shows the identity error message when sign-in was rejected', () => {
    const html = renderSettingsTab({ ...baseArgs, identityError: 'not authorized yet' });
    expect(html).toContain('not authorized yet');
  });

  // --- Coach access (grants) section, coach-mode Phase 1 ---

  const grantsBaseArgs = {
    ...baseArgs,
    backendConfigured: true,
    identity: { name: 'Renee', athlete: 'renee', role: 'athlete' },
    grants: { status: 'idle', data: [], error: null },
    grantsForm: { coachSlug: '' },
    grantsSubmit: { status: 'idle', error: null },
  };

  it('omits the Coach access panel entirely when backend is not configured', () => {
    const html = renderSettingsTab({ ...baseArgs, backendConfigured: false });
    expect(html).not.toContain('Coach access');
    expect(html).not.toContain('data-a="grants:submit"');
  });

  it('shows the grant form and an empty-state message when there are no grants', () => {
    const html = renderSettingsTab(grantsBaseArgs);
    expect(html).toContain('Coach access');
    expect(html).toContain('data-form="grants"');
    expect(html).toContain('data-field="coachSlug"');
    expect(html).toContain('data-a="grants:submit"');
    expect(html).toContain("haven't granted anyone coach access yet");
  });

  it('lists an active grant with a Revoke button', () => {
    const html = renderSettingsTab({
      ...grantsBaseArgs,
      grants: {
        status: 'ready',
        data: [{
          id: 'g1', coach_athlete_id: 'abcdef12-3456-7890-abcd-ef1234567890', status: 'active', granted_at: '2026-07-01T00:00:00Z',
        }],
        error: null,
      },
    });
    expect(html).toContain('active');
    expect(html).toContain('data-a="grants:revoke"');
    expect(html).toContain('data-id="g1"');
  });

  it('lists a revoked grant without a Revoke button', () => {
    const html = renderSettingsTab({
      ...grantsBaseArgs,
      grants: {
        status: 'ready',
        data: [{
          id: 'g1', coach_athlete_id: 'abcdef12-3456-7890-abcd-ef1234567890', status: 'revoked', granted_at: '2026-07-01T00:00:00Z',
        }],
        error: null,
      },
    });
    expect(html).toContain('revoked');
    expect(html).not.toContain('data-a="grants:revoke"');
  });

  it('shows the grant-form error message on a failed submit', () => {
    const html = renderSettingsTab({
      ...grantsBaseArgs,
      grantsSubmit: { status: 'error', error: 'no such coach: nobody' },
    });
    expect(html).toContain('no such coach: nobody');
  });

  // --- B4 (coach-mode Q&A build): "Email notifications" toggle ---

  const profilePanelArgs = {
    ...grantsBaseArgs,
    profileLoad: { status: 'ready', error: null },
    profileForm: {
      name: 'Renee', dob: '', sex: '', heightFeet: '', heightInches: '', weightLb: '', cssPace: '',
      poolDays: {}, emailNotificationsEnabled: true,
    },
  };

  it('renders the email-notifications checkbox, checked when enabled', () => {
    const html = renderSettingsTab(profilePanelArgs);
    expect(html).toContain('data-form="profile"');
    const match = /<input type="checkbox" data-form="profile" data-field="email_notifications_enabled"[^>]*>/.exec(html);
    expect(match).not.toBeNull();
    expect(match[0]).toContain('checked');
  });

  it('renders the email-notifications checkbox unchecked when disabled', () => {
    const html = renderSettingsTab({
      ...profilePanelArgs,
      profileForm: { ...profilePanelArgs.profileForm, emailNotificationsEnabled: false },
    });
    const match = /<input type="checkbox" data-form="profile" data-field="email_notifications_enabled"[^>]*>/.exec(html);
    expect(match[0]).not.toContain('checked');
  });
});

describe('renderAskCoachSection', () => {
  it('shows an empty-state message when there are no past questions', () => {
    const html = renderAskCoachSection({ questions: [], form: { body: '' }, submit: { status: 'idle', error: null } });
    expect(html).toContain('Nothing asked yet.');
  });

  it('renders the AI-provisional-answer state', () => {
    const html = renderAskCoachSection({
      questions: [{ id: 'f1', body: 'how hard should this be?', ai_provisional_answer: 'Zone 2, easy.', coach_reply: null, needs_human_review: false }],
      form: { body: '' },
      submit: { status: 'idle', error: null },
    });
    expect(html).toContain('how hard should this be?');
    expect(html).toContain('AI provisional answer');
    expect(html).toContain('Zone 2, easy.');
    expect(html).not.toContain('Waiting on your coach');
  });

  it('renders the coach-reply state, preferring it over an AI answer when both are present', () => {
    const html = renderAskCoachSection({
      questions: [{
        id: 'f1', body: 'how hard should this be?', ai_provisional_answer: 'Zone 2, easy.',
        coach_reply: 'Push it a bit today.', needs_human_review: false,
      }],
      form: { body: '' },
      submit: { status: 'idle', error: null },
    });
    expect(html).toContain('Your coach replied');
    expect(html).toContain('Push it a bit today.');
    expect(html).not.toContain('AI provisional answer');
  });

  it('renders the waiting-on-coach state when flagged for human review with no answer yet', () => {
    const html = renderAskCoachSection({
      questions: [{
        id: 'f1', body: 'is this safe with my shoulder?', ai_provisional_answer: null,
        coach_reply: null, needs_human_review: true,
      }],
      form: { body: '' },
      submit: { status: 'idle', error: null },
    });
    expect(html).toContain('Waiting on your coach to reply.');
    expect(html).not.toContain('AI provisional answer');
    expect(html).not.toContain('Your coach replied');
  });

  it('renders a real input box and submit button when form is given', () => {
    const html = renderAskCoachSection({ questions: [], form: { body: 'draft text' }, submit: { status: 'idle', error: null } });
    expect(html).toContain('data-form="askCoach"');
    expect(html).toContain('data-a="ask-coach:submit"');
    expect(html).toContain('draft text');
  });

  it('omits the input box entirely when form is null (read-only)', () => {
    const html = renderAskCoachSection({ questions: [], form: null });
    expect(html).not.toContain('data-form="askCoach"');
    expect(html).not.toContain('data-a="ask-coach:submit"');
  });

  it('disables the submit button and shows "Asking…" while submitting', () => {
    const html = renderAskCoachSection({ questions: [], form: { body: 'x' }, submit: { status: 'submitting', error: null } });
    const match = /<button[^>]*data-a="ask-coach:submit"[^>]*>([^<]*)<\/button>/.exec(html);
    expect(match[0]).toContain('disabled');
    expect(match[1]).toContain('Asking');
  });

  it('shows the submit error message when submit failed', () => {
    const html = renderAskCoachSection({ questions: [], form: { body: 'x' }, submit: { status: 'error', error: 'the coach could not answer that just now' } });
    expect(html).toContain('conn-result fail');
    expect(html).toContain('the coach could not answer that just now');
  });

  it('escapes malicious question/answer content', () => {
    const html = renderAskCoachSection({
      questions: [{ id: 'f1', body: '<img src=x onerror=alert(1)>', ai_provisional_answer: '<script>bad</script>' }],
      form: { body: '' },
      submit: { status: 'idle', error: null },
    });
    expect(html).not.toContain('<img src=x');
    expect(html).not.toContain('<script>bad');
  });
});

describe('renderFeedbackTab (B2: answer visibility on the athlete\'s own Feedback tab)', () => {
  const baseArgs = {
    form: { type: 'feature_request', body: '' },
    submit: { status: 'idle', message: null },
    entriesStatus: 'ready',
    backendConfigured: true,
    online: true,
  };

  it('renders the AI-provisional-answer, coach-reply, and waiting-on-coach states', () => {
    const html = renderFeedbackTab({
      ...baseArgs,
      entries: [
        { id: 'f1', type: 'question', source: 'athlete', body: 'q1', status: 'open', created_at: '2026-08-20T00:00:00Z', ai_provisional_answer: 'AI says zone 2.', coach_reply: null, needs_human_review: false },
        { id: 'f2', type: 'question', source: 'athlete', body: 'q2', status: 'answered', created_at: '2026-08-20T00:00:00Z', ai_provisional_answer: 'AI says push it.', coach_reply: 'Coach says ease off.', needs_human_review: false },
        { id: 'f3', type: 'question', source: 'athlete', body: 'q3', status: 'open', created_at: '2026-08-20T00:00:00Z', ai_provisional_answer: null, coach_reply: null, needs_human_review: true },
      ],
    });
    expect(html).toContain('AI says zone 2.');
    expect(html).toContain('Coach says ease off.');
    // The coach reply wins over the AI answer when both exist on one entry.
    expect(html).not.toContain('AI says push it.');
    expect(html).toContain('Waiting on your coach to reply.');
  });

  it('shows the linked session/workout context on a scoped question', () => {
    const html = renderFeedbackTab({
      ...baseArgs,
      entries: [
        { id: 'f1', type: 'question', source: 'athlete', body: 'about a session', status: 'open', created_at: '2026-08-20T00:00:00Z', session_date: '2026-08-10', session_sport: 'swim_pool' },
        { id: 'f2', type: 'question', source: 'athlete', body: 'about a workout', status: 'open', created_at: '2026-08-20T00:00:00Z', workout_id: 'w-1' },
        { id: 'f3', type: 'feature_request', source: 'athlete', body: 'unlinked', status: 'open', created_at: '2026-08-20T00:00:00Z' },
      ],
    });
    expect(html).toContain('About a logged workout');
    expect(html).toMatch(/About Pool swim on/);
  });
});

describe('renderTabBar', () => {
  it('shows every tab, including My Athletes, by default (no second arg)', () => {
    const html = renderTabBar('plan');
    expect(html).toContain('data-a="tab:roster"');
    expect(html).toContain('My Athletes');
  });

  it('hides the roster tab when hideRoster is true', () => {
    const html = renderTabBar('plan', { hideRoster: true });
    expect(html).not.toContain('data-a="tab:roster"');
  });

  it('shows the roster tab when hideRoster is false', () => {
    const html = renderTabBar('plan', { hideRoster: false });
    expect(html).toContain('data-a="tab:roster"');
  });

  it('marks the active tab', () => {
    const html = renderTabBar('roster');
    const match = /<button[^>]*data-a="tab:roster"[^>]*>/.exec(html);
    expect(match[0]).toContain('active');
  });

  // B3 (coach-mode Q&A build): unread count badges.
  it('renders no badge on either tab when both unread counts are 0/omitted', () => {
    const html = renderTabBar('plan');
    expect(html).not.toContain('badge-count');
  });

  it('renders a badge on the Feedback tab when feedbackUnread is positive', () => {
    const html = renderTabBar('plan', { feedbackUnread: 3 });
    const match = /<button[^>]*data-a="tab:feedback"[^>]*>[\s\S]*?<\/button>/.exec(html);
    expect(match[0]).toContain('<span class="badge-count">3</span>');
    // Not leaked onto an unrelated tab.
    const rosterMatch = /<button[^>]*data-a="tab:roster"[^>]*>[\s\S]*?<\/button>/.exec(html);
    expect(rosterMatch[0]).not.toContain('badge-count');
  });

  it('renders a badge on the My Athletes (roster) tab when rosterUnread is positive', () => {
    const html = renderTabBar('plan', { rosterUnread: 2 });
    const match = /<button[^>]*data-a="tab:roster"[^>]*>[\s\S]*?<\/button>/.exec(html);
    expect(match[0]).toContain('<span class="badge-count">2</span>');
  });
});

describe('renderRosterTab', () => {
  const baseArgs = {
    athletes: { status: 'idle', data: [], error: null },
    actingAsAthlete: null,
    workouts: { status: 'idle', data: [], error: null },
    feedback: { status: 'idle', data: [], error: null },
    replyDrafts: {},
    replySubmit: { status: 'idle', error: null, feedbackId: null },
    workoutDetailId: null,
    backendConfigured: true,
    online: true,
  };

  const workout = {
    id: 'w1',
    date: '2026-08-24',
    sport: 'swim_pool',
    source: 'fit',
    rpe: 6,
    duration_min: 45,
    distance_m: 2000,
    avg_pace_s_per_100m: 95,
    avg_hr: 142,
    max_hr: 165,
    notes: null,
    laps: [],
    lengths: [],
    pauses: [],
    analytics: null,
    quality: {
      matched: true, distance_delta_pct: 5.2, duration_delta_pct: null, intensity_match: 'unknown', quality_summary: 'No notable quality flags.',
    },
  };

  it('shows a backend-needed notice when not configured', () => {
    const html = renderRosterTab({ ...baseArgs, backendConfigured: false });
    expect(html).toContain('sign in');
    expect(html).not.toContain('data-a="roster:select-athlete"');
  });

  it('shows an empty state when there are no coached athletes', () => {
    const html = renderRosterTab(baseArgs);
    expect(html).toContain('coach access');
  });

  it('lists coached athletes as clickable rows in the list view', () => {
    const html = renderRosterTab({
      ...baseArgs,
      athletes: { status: 'ready', data: [{ slug: 'renee', name: 'Renee' }], error: null },
    });
    expect(html).toContain('data-a="roster:select-athlete"');
    expect(html).toContain('data-slug="renee"');
    expect(html).toContain('Renee');
    // No detail-view content while no athlete is selected.
    expect(html).not.toContain('data-a="roster:back"');
  });

  it('switches to the detail view (workouts + feedback) once an athlete is selected', () => {
    const html = renderRosterTab({
      ...baseArgs,
      athletes: { status: 'ready', data: [{ slug: 'renee', name: 'Renee' }], error: null },
      actingAsAthlete: 'renee',
      workouts: {
        status: 'ready',
        data: [{
          id: 'w1',
          date: '2026-08-24',
          sport: 'swim_pool',
          rpe: 6,
          duration_min: 45,
          distance_m: 2000,
          quality: {
            matched: true, distance_delta_pct: 5.2, duration_delta_pct: null, intensity_match: 'unknown', quality_summary: 'No notable quality flags.',
          },
        }],
        error: null,
      },
      feedback: {
        status: 'ready',
        data: [{
          id: 'f1', type: 'question', source: 'athlete', body: 'How much fueling for a 4hr swim?', status: 'open', created_at: '2026-08-20T00:00:00Z', needs_human_review: false, ai_provisional_answer: 'Aim for 60-90g carbs/hr.',
        }],
        error: null,
      },
    });
    expect(html).toContain('data-a="roster:back"');
    expect(html).toContain('Renee');
    // Workout row with quality rendered plainly.
    expect(html).toContain('+5.2% distance');
    expect(html).toContain('unknown intensity');
    expect(html).toContain('No notable quality flags.');
    // Feedback entry, its AI provisional answer, and an open reply box
    // (no coach_reply yet).
    expect(html).toContain('How much fueling for a 4hr swim?');
    expect(html).toContain('Aim for 60-90g carbs/hr.');
    expect(html).toContain('data-form="roster-reply"');
    expect(html).toContain('data-id="f1"');
    expect(html).toContain('data-a="roster:reply-submit"');
  });

  it('shows an existing coach_reply instead of the reply box', () => {
    const html = renderRosterTab({
      ...baseArgs,
      actingAsAthlete: 'renee',
      feedback: {
        status: 'ready',
        data: [{
          id: 'f1', type: 'question', source: 'athlete', body: 'Q', status: 'answered', created_at: '2026-08-20T00:00:00Z', needs_human_review: false, coach_reply: 'Already answered this.',
        }],
        error: null,
      },
    });
    expect(html).toContain('Already answered this.');
    expect(html).not.toContain('data-form="roster-reply"');
  });

  it('flags needs_human_review entries visually', () => {
    const html = renderRosterTab({
      ...baseArgs,
      actingAsAthlete: 'renee',
      feedback: {
        status: 'ready',
        data: [{
          id: 'f1', type: 'coach_review', source: 'athlete', body: 'My shoulder hurts', status: 'open', created_at: '2026-08-20T00:00:00Z', needs_human_review: true,
        }],
        error: null,
      },
    });
    expect(html).toContain('Needs review');
  });

  it('renders each workout row as a clickable button opening its detail view', () => {
    const html = renderRosterTab({
      ...baseArgs,
      actingAsAthlete: 'renee',
      workouts: { status: 'ready', data: [workout], error: null },
    });
    expect(html).toContain('data-a="roster:open-workout"');
    expect(html).toContain('data-id="w1"');
  });

  it('shows the read-only workout detail view (no embedded chat) when workoutDetailId matches a loaded workout', () => {
    const html = renderRosterTab({
      ...baseArgs,
      athletes: { status: 'ready', data: [{ slug: 'renee', name: 'Renee' }], error: null },
      actingAsAthlete: 'renee',
      workouts: { status: 'ready', data: [workout], error: null },
      workoutDetailId: 'w1',
    });
    expect(html).toContain('data-a="roster:close-workout"');
    // The detail view itself (renderWorkoutDetail's stats section), not
    // the workouts/feedback list sections.
    expect(html).toContain('2 km');
    expect(html).toContain('Pool swim');
    expect(html).not.toContain('data-a="roster:open-workout"');
    expect(html).not.toContain('data-a="roster:back"');
    // No embedded "ask your coach" chat -- that's an athlete-only feature.
    expect(html).not.toContain('Ask your coach about this workout');
    // The real, read-only Ask-the-coach Q&A section IS shown here too
    // (coach-mode Q&A build) -- distinct from the athlete-only AI chat just
    // excluded above, and with no input box (coach replies stay in the
    // roster's own Feedback section reply UI).
    expect(html).toContain('id="ask-coach"');
    expect(html).not.toContain('data-form="askCoach"');
    expect(html).not.toContain('data-a="ask-coach:submit"');
  });

  describe('sub-tabs (Build 2: Conversations / Workouts + Dashboard / Training Plan)', () => {
    const actingArgs = {
      ...baseArgs,
      athletes: { status: 'ready', data: [{ slug: 'renee', name: 'Renee' }], error: null },
      actingAsAthlete: 'renee',
      plan: { status: 'idle', data: null, error: null },
    };

    it('shows the sub-tab bar with all three options once an athlete is selected', () => {
      const html = renderRosterTab(actingArgs);
      expect(html).toContain('data-a="roster:subtab:conversations"');
      expect(html).toContain('data-a="roster:subtab:dashboard"');
      expect(html).toContain('data-a="roster:subtab:plan"');
    });

    it('defaults to the Workouts + Dashboard sub-tab when subTab is not given', () => {
      const html = renderRosterTab({
        ...actingArgs, workouts: { status: 'ready', data: [workout], error: null },
      });
      expect(html).toContain('data-a="roster:open-workout"');
      expect(html).toContain('class="subtab-btn active"');
    });

    it('shows the honest non-functional Conversations placeholder, not wired to anything', () => {
      const html = renderRosterTab({ ...actingArgs, subTab: 'conversations' });
      expect(html).toContain('coming soon');
      expect(html).not.toContain('data-a="roster:open-workout"');
      expect(html).not.toContain('data-a="roster:reply-submit"');
    });

    it('shows the Training Plan sub-tab\'s weeks/macro sections from the coach-plan endpoint data, without the load chart', () => {
      const html = renderRosterTab({
        ...actingArgs,
        subTab: 'plan',
        plan: {
          status: 'ready',
          data: {
            slug: 'renee',
            name: 'Renee',
            athlete: { name: 'Renee' },
            events: [],
            macro: { blocks: [] },
            weeks: [],
          },
          error: null,
        },
      });
      expect(html).toContain('No weeks planned yet.');
      expect(html).toContain('No macro plan scaffolded yet.');
      expect(html).not.toContain('<svg'); // no load chart in this sub-tab
    });

    it('shows a loading state for the Training Plan sub-tab while the plan fetch is in flight', () => {
      const html = renderRosterTab({
        ...actingArgs, subTab: 'plan', plan: { status: 'loading', data: null, error: null },
      });
      expect(html.toLowerCase()).toContain('loading');
    });

    it('shows an error state for the Training Plan sub-tab on a failed fetch', () => {
      const html = renderRosterTab({
        ...actingArgs, subTab: 'plan', plan: { status: 'error', data: null, error: 'boom' },
      });
      expect(html).toContain('boom');
    });

    it('derives missed (skipped) sessions in the Workouts + Dashboard feed once plan weeks are available', () => {
      const html = renderRosterTab({
        ...actingArgs,
        subTab: 'dashboard',
        workouts: { status: 'ready', data: [], error: null },
        plan: {
          status: 'ready',
          data: {
            weeks: [{
              iso_week: '2020-W01',
              sessions: [{
                id: 'sess-1', date: '2020-01-01', sport: 'swim_pool', duration_min: 45, status: 'planned',
              }],
            }],
          },
          error: null,
        },
      });
      expect(html).toContain('Skipped');
    });

    // Coach session-detail drill-down (the reported bug fix): the coach can
    // now open a session from the Training Plan sub-tab and see the same
    // real content the athlete sees (structure/targets/zone breakdown/
    // rationale/purpose), but with the two Garmin actions suppressed --
    // those act on the SIGNED-IN coach's OWN athlete slug (main.js's
    // athleteSlug()), never the coached athlete's, and the backend has no
    // resolve_coach_athlete support on those routes at all.
    describe('session detail drill-down', () => {
      const structuredSession = {
        id: 'sess-structured',
        date: '2020-01-01',
        sport: 'swim_pool',
        duration_min: 45,
        distance_m: 1600,
        intensity: { zone: 'Z3' },
        purpose: 'garmin-exportable session',
        structure: 'Main set: 4x200 @ Z3',
        structured: {
          items: [{
            kind: 'step', label: '4x200 @ Z3', role: 'interval', duration_kind: 'distance_m',
            duration_value: 800, modality: 'swim', equipment: [],
          }],
        },
      };
      const planWithStructuredSession = {
        status: 'ready',
        data: {
          slug: 'renee',
          name: 'Renee',
          athlete: { name: 'Renee' },
          events: [],
          macro: { blocks: [] },
          weeks: [{
            iso_week: '2020-W01', focus: 'base', target_volume_m: 2000, sessions: [structuredSession],
          }],
        },
        error: null,
      };

      it('opens the real session detail (same structured content the athlete sees) with no Garmin buttons, plus an honest note', () => {
        const html = renderRosterTab({
          ...actingArgs,
          subTab: 'plan',
          sessionDetailId: 'sess-structured',
          plan: planWithStructuredSession,
        });
        expect(html).toContain('data-a="session:back"');
        // Real structured content, same as the athlete's own view.
        expect(html).toContain('4x200 @ Z3');
        // Neither Garmin action -- unsupported for a coach acting on another
        // athlete's session (see the doc comment above).
        expect(html).not.toContain('data-a="session:garmin-download"');
        expect(html).not.toContain('data-a="session:push-intervals"');
        expect(html).not.toContain('Download for Garmin');
        expect(html).not.toContain('Push to Garmin');
        // An honest, small note stands in for them, rather than silently
        // omitting the actions with no explanation.
        expect(html).toContain("only available from the athlete's own device");
      });

      it('falls back to the weeks/macro list when sessionDetailId does not match any loaded session', () => {
        const html = renderRosterTab({
          ...actingArgs,
          subTab: 'plan',
          sessionDetailId: 'no-such-id',
          plan: planWithStructuredSession,
        });
        expect(html).not.toContain('data-a="session:back"');
        expect(html).toContain('data-a="session:open"');
      });
    });
  });

  it('falls back to the workouts/feedback list when workoutDetailId no longer matches any loaded workout', () => {
    const html = renderRosterTab({
      ...baseArgs,
      actingAsAthlete: 'renee',
      workouts: { status: 'ready', data: [workout], error: null },
      workoutDetailId: 'stale-id',
    });
    expect(html).toContain('data-a="roster:back"');
    expect(html).toContain('data-a="roster:open-workout"');
  });
});

describe('renderUpdateBanner', () => {
  it('renders nothing when there is no update and offline-readiness has not fired', () => {
    expect(renderUpdateBanner({
      needRefresh: false, needRefreshDismissed: false, offlineReady: false, offlineReadyDismissed: false,
    })).toBe('');
    expect(renderUpdateBanner()).toBe('');
  });

  it('renders the reload banner when needRefresh is set', () => {
    const html = renderUpdateBanner({
      needRefresh: true, needRefreshDismissed: false, offlineReady: false, offlineReadyDismissed: false,
    });
    expect(html).toContain('New version available');
    expect(html).toContain('data-a="pwa:reload"');
    expect(html).toContain('data-a="pwa:dismiss-update"');
  });

  it('renders nothing once the reload banner is dismissed', () => {
    const html = renderUpdateBanner({
      needRefresh: true, needRefreshDismissed: true, offlineReady: false, offlineReadyDismissed: false,
    });
    expect(html).toBe('');
  });

  it('renders the offline-ready note when offlineReady is set and needRefresh is not', () => {
    const html = renderUpdateBanner({
      needRefresh: false, needRefreshDismissed: false, offlineReady: true, offlineReadyDismissed: false,
    });
    expect(html).toContain('Ready to work offline');
    expect(html).toContain('data-a="pwa:dismiss-offline-ready"');
  });

  it('renders nothing once the offline-ready note is dismissed', () => {
    const html = renderUpdateBanner({
      needRefresh: false, needRefreshDismissed: false, offlineReady: true, offlineReadyDismissed: true,
    });
    expect(html).toBe('');
  });

  it('prefers the reload banner over the offline-ready note when both are set', () => {
    const html = renderUpdateBanner({
      needRefresh: true, needRefreshDismissed: false, offlineReady: true, offlineReadyDismissed: false,
    });
    expect(html).toContain('New version available');
    expect(html).not.toContain('Ready to work offline');
  });
});

// --- Stale/empty plan state + the browsable all-weeks accordion ----------
// The 2026-08-18 defect: the athlete's plan data stopped at 2026-W29 while
// the wall clock had moved on to W34, and the Plan tab rendered W29 under a
// "This week" heading. Two fixes are covered here: an honest empty state
// when every planned week has elapsed (distinct from "nothing planned at
// all"), and a collapsed accordion so the whole plan -- past weeks included
// -- is browsable instead of only current+next.

describe('renderApp weeks section: stale / empty states', () => {
  const PAST_WEEKS = [
    {
      iso_week: '2020-W01', meso_block: 'base', focus: 'aerobic base',
      target_volume_m: 12000, sessions: [], adaptation_rationale: null,
    },
    {
      iso_week: '2020-W02', meso_block: 'base', focus: 'aerobic base',
      target_volume_m: 13000, sessions: [], adaptation_rationale: null,
    },
  ];
  const BASE = { athlete: { name: 'Renee' }, events: [], macro: { blocks: [] } };

  it('says no plan exists for this week -- and does NOT label a past week "This week"', () => {
    const html = renderApp({ ...BASE, weeks: PAST_WEEKS }, null);
    expect(html).toContain('No plan generated for this week yet');
    expect(html).not.toContain('This week ·');
    expect(html).not.toContain('Next week ·');
  });

  it('distinguishes "nothing planned at all" from "this week is missing"', () => {
    const html = renderApp({ ...BASE, weeks: [] }, null);
    expect(html).toContain('No weeks planned yet');
    expect(html).not.toContain('No plan generated for this week yet');
  });

  it('still offers the all-weeks accordion when the plan is stale, so past weeks stay readable', () => {
    const html = renderApp({ ...BASE, weeks: PAST_WEEKS }, null);
    expect(html).toContain('data-a="weeks:toggle-all"');
    expect(html).toContain('2020-W01');
    expect(html).toContain('2020-W02');
  });

  it('renders no accordion at all when there are no weeks', () => {
    const html = renderApp({ ...BASE, weeks: [] }, null);
    expect(html).not.toContain('data-a="weeks:toggle-all"');
  });
});

describe('renderApp weeks section: all-weeks accordion', () => {
  const FUTURE = '2099-W01';
  const monday = isoWeekMonday(FUTURE);
  const makeWeek = (iso, volume) => ({
    iso_week: iso, meso_block: 'base', focus: 'aerobic base',
    target_volume_m: volume, sessions: [], adaptation_rationale: null,
  });
  const DATA = {
    athlete: { name: 'Renee' }, events: [], macro: { blocks: [] },
    weeks: [makeWeek('2099-W02', 13000), makeWeek(FUTURE, 12000), makeWeek('2019-W40', 9000)],
  };

  it('renders current + next cards as before', () => {
    const html = renderApp(DATA, null);
    expect(html).toContain('This week ·');
    expect(html).toContain('Next week ·');
    expect(dateKey(addDays(monday, 0))).toBeTruthy(); // sanity: fixture week resolves
  });

  it('lists every week, past ones included, inside a collapsed <details> accordion', () => {
    const html = renderApp(DATA, null);
    expect(html).toContain('<details');
    expect(html).toContain('data-a="weeks:toggle-all"');
    // All three weeks appear in the accordion, chronologically.
    const i2019 = html.indexOf('2019-W40');
    const i2099w1 = html.indexOf('2099-W01', html.indexOf('data-a="weeks:toggle-all"'));
    const i2099w2 = html.indexOf('2099-W02', html.indexOf('data-a="weeks:toggle-all"'));
    expect(i2019).toBeGreaterThan(-1);
    expect(i2019).toBeLessThan(i2099w1);
    expect(i2099w1).toBeLessThan(i2099w2);
  });

  it('does not open the accordion by default (no `open` attribute)', () => {
    const html = renderApp(DATA, null);
    expect(html).not.toMatch(/<details[^>]*\sopen/);
  });

  // The accordion is native <details>, so its open/closed state lives in the
  // DOM -- and every render() rebuilds that DOM from scratch. Without the
  // state being re-emitted as an `open` attribute, any unrelated re-render
  // (a plan refresh, an online/offline flip, a background load landing)
  // silently snapped it shut mid-read. Caught as a flaky e2e failure.
  it('re-emits the open attribute when the accordion is open, so a re-render keeps it open', () => {
    const html = renderApp({ ...DATA, allWeeksOpen: true }, null);
    expect(html).toMatch(/<details[^>]*\sopen/);
  });

  it('stays closed when the flag is false', () => {
    const html = renderApp({ ...DATA, allWeeksOpen: false }, null);
    expect(html).not.toMatch(/<details[^>]*\sopen/);
  });
});

// --- History tab ----------------------------------------------------------
// Andrew's ask: "history - should show workouts completed with actual stats
// and planned workout skipped." One reverse-chron feed of both.

describe('renderLoadChart', () => {
  const readySeries = [
    ['2026-07-01', 10.0, 5.0, 5.0],
    ['2026-07-02', 10.5, 6.0, 4.5],
    ['2026-07-03', 11.0, 4.0, 7.0],
  ];

  it('renders nothing for idle or missing load state', () => {
    expect(renderLoadChart({ status: 'idle', data: null, error: null })).toBe('');
    expect(renderLoadChart(undefined)).toBe('');
    expect(renderLoadChart(null)).toBe('');
  });

  it('shows a loading message while loading with no data yet', () => {
    const html = renderLoadChart({ status: 'loading', data: null, error: null });
    expect(html).toContain('Loading training load');
  });

  it('surfaces an error message', () => {
    const html = renderLoadChart({ status: 'error', data: null, error: 'network down' });
    expect(html).toContain('network down');
  });

  it('shows an honest empty-data message rather than a broken chart for an empty series', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: [] }, error: null });
    expect(html).toContain('Not enough logged training');
    expect(html).not.toContain('<svg');
  });

  it('renders the two-panel chart, its three lines, and clear inline labels for a real series', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toContain('<svg');
    expect(html).toContain('load-chart-line-ctl');
    expect(html).toContain('load-chart-line-atl');
    expect(html).toContain('load-chart-line-tsb');
    // Legend moved inline (design spec 3.6) -- CTL/ATL/TSB are named at
    // each line's own end point now, not in a separate legend row.
    expect(html).toContain('>CTL<');
    expect(html).toContain('>ATL<');
    expect(html).toMatch(/>TSB [+-]?\d/);
    // x-axis date labels are present in some human-readable form.
    expect(html).toMatch(/Jul \d/);
  });

  it('defaults the chart window to LOAD_CHART_WINDOW_DAYS (6 weeks), for mobile readability', () => {
    // 60 daily points, well past the 42-day default window. The chart's
    // x-axis must not reach back to the series' real first date.
    const longSeries = Array.from({ length: 60 }, (_, i) => {
      const d = new Date(Date.UTC(2026, 5, 1));
      d.setUTCDate(d.getUTCDate() + i);
      const iso = d.toISOString().slice(0, 10);
      return [iso, 10 + i, 5 + i * 0.1, 5];
    });
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: longSeries }, error: null });
    // The series' real first date (Jun 1) falls outside the default 42-day
    // window and must not appear as an x-axis tick label.
    expect(html).not.toMatch(/Jun 1\b/);
    // The series' real last date is always in-window.
    expect(html).toMatch(/Jul 30\b/);
  });

  it('respects an explicit windowDays option, including null ("Season" -- the full series)', () => {
    const longSeries = Array.from({ length: 60 }, (_, i) => {
      const d = new Date(Date.UTC(2026, 5, 1));
      d.setUTCDate(d.getUTCDate() + i);
      return [d.toISOString().slice(0, 10), 10 + i, 5, 5];
    });
    const windowed = renderLoadChart(
      { status: 'ready', data: { ctl_atl_tsb: longSeries }, error: null }, { windowDays: 84 },
    );
    // 60 days fits entirely inside an 84-day window -- the real first date
    // shows up.
    expect(windowed).toMatch(/Jun 1\b/);

    const season = renderLoadChart(
      { status: 'ready', data: { ctl_atl_tsb: longSeries }, error: null }, { windowDays: null },
    );
    // "Season" formats x-ticks as month names, not day-level dates.
    expect(season).toMatch(/>Jun</);
    expect(season).not.toMatch(/Jun \d/);
  });

  it('marks the currently-selected window pill active', () => {
    const html = renderLoadChart(
      { status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null }, { windowDays: 84 },
    );
    expect(html).toContain('data-a="load-chart:window:84"');
    // The active pill's own button tag carries the active class + aria-current.
    const activeButton = html.match(/<button[^>]*data-a="load-chart:window:84"[^>]*>/)[0];
    expect(activeButton).toContain('active');
    expect(activeButton).toContain('aria-current="page"');
    const inactiveButton = html.match(/<button[^>]*data-a="load-chart:window:42"[^>]*>/)[0];
    expect(inactiveButton).not.toContain('active');
  });

  it('renders the race-day reference band, self-labeled, with an honest, non-authoritative caption', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toContain('load-chart-band-race');
    // The band names itself now (design spec 3.2), not a separate legend
    // line.
    expect(html).toContain('>race-ready<');
    // Must frame the band as a cycling-coaching convention, not a
    // swim-specific or peer-reviewed target -- the honesty requirement
    // from CLAUDE.md's evidence-discipline standard, applied to UI copy.
    expect(html.toLowerCase()).toContain('cycling');
    expect(html.toLowerCase()).toContain('not a swim-specific or peer-reviewed target');
  });

  it('also renders the productive-training reference band, self-labeled and distinct from the race-day one', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toContain('load-chart-band-productive');
    expect(html).toContain('load-chart-band-race');
    expect(html).toContain('>productive<');
  });

  it('bumps the currently-occupied band to load-chart-band-active, and only that one', () => {
    // readySeries' last point has TSB=7.0 -- inside the race-ready band
    // (+5..+25), not the productive band.
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toMatch(/load-chart-band-race load-chart-band-active|load-chart-band load-chart-band-race load-chart-band-active/);
    expect(html).not.toMatch(/load-chart-band-productive load-chart-band-active/);
  });

  it('renders a zero line and the two unnamed-zone edge labels', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toContain('load-chart-zero-line');
    expect(html).toContain('transitional');
    expect(html).toContain('high risk');
    // The grey zone between the two named bands is deliberately unlabeled.
    expect(html.toLowerCase()).not.toContain('grey zone');
  });

  it('flags an out-of-range TSB point with a clamp caret rather than silently drawing it at the edge', () => {
    const extremeSeries = [
      ['2026-07-01', 30, 30, -60], // below TSB_AXIS_DOMAIN.min
      ['2026-07-02', 30, 30, 0],
    ];
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: extremeSeries }, error: null });
    expect(html).toContain('load-chart-clamp-caret');
  });

  it('draws a caret (not a circle) for the latest point when it is itself clamped', () => {
    // Regression: the latest-point marker used to always draw a plain
    // filled circle, painted on top of (and mostly hiding) the identical
    // clamp caret drawn underneath it whenever the MOST RECENT point was
    // itself out of TSB_AXIS_DOMAIN's range -- exactly the one point where
    // an athlete most needs to see the "off the plot" flag.
    const extremeSeries = [
      ['2026-07-01', 30, 30, 0],
      ['2026-07-02', 30, 30, -60], // below TSB_AXIS_DOMAIN.min, and the LAST point
    ];
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: extremeSeries }, error: null });
    expect(html).toContain('load-chart-clamp-caret-latest');
    // Exactly one caret polygon total (the latest point's own combined
    // marker) -- no separate plain circle marker duplicating/hiding it.
    expect((html.match(/<polygon class="load-chart-clamp-caret/g) || []).length).toBe(1);
    expect(html).not.toMatch(/<circle[^>]*r="3\.5"/);
  });

  it('still draws the plain circle marker when the latest point is NOT clamped', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toMatch(/<circle[^>]*r="3\.5"/);
    expect(html).not.toContain('load-chart-clamp-caret-latest');
  });

  it('separates the CTL/ATL inline end-labels vertically when the two lines are numerically close (TSB near 0)', () => {
    // CTL and ATL both ~30 on the last day (TSB ~0) -- their pixel
    // y-positions on the shared 0-anchored axis land close together, so
    // the two end-labels must not use the same small fixed offset (they'd
    // overlap right when the lines themselves are hardest to tell apart).
    const closeSeries = [
      ['2026-07-01', 25, 20, 5],
      ['2026-07-02', 30, 30, 0],
    ];
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: closeSeries }, error: null });
    const ctlY = Number(html.match(/y="(-?[\d.]+)"[^>]*fill:var\(--accent\)">CTL</)?.[1]);
    const atlY = Number(html.match(/y="(-?[\d.]+)"[^>]*fill:var\(--c-strength\)">ATL</)?.[1]);
    expect(Number.isFinite(ctlY)).toBe(true);
    expect(Number.isFinite(atlY)).toBe(true);
    expect(Math.abs(ctlY - atlY)).toBeGreaterThanOrEqual(14);
  });

  it('renders a one-line plain-text verdict below the chart, before the narrative', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toContain('load-chart-verdict');
    // readySeries' last point: TSB 7.0, inside the race-ready band.
    expect(html).toMatch(/Form 7\.0.*race-ready band/);
    const verdictIndex = html.indexOf('load-chart-verdict');
    const narrativeIndex = html.indexOf('load-chart-narrative');
    expect(verdictIndex).toBeLessThan(narrativeIndex);
  });

  // readySeries is a 3-day series (2026-07-01..07-03) -- cold-start warmup
  // (< CTL_COLD_START_DAYS=42), CTL trend is 'insufficient-window' (only
  // 3 days of history vs. the 14-day comparison window), ATL drops
  // 6.0->4.0 (non-flat, so it renders), and TSB=7.0 lands in the
  // race-ready band.
  it('shows TSB/CTL/ATL lines (actionable-first) by default, hiding the cold-start caveat behind "more"', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toContain('load-chart-narrative-more');
    // TSB's SHORT actionable line leads (race-ready band's actionable clause).
    expect(html).toContain('in range for race-day freshness');
    // CTL trend's insufficient-window line is present too.
    expect(html).toContain('Not enough history yet');
    // ATL's spike line (real dates/values, non-flat) is present.
    expect(html).toContain('ATL (fatigue) dropped from 6.0 to 4.0');
    // The cold-start caveat and TSB's fuller long-form explanation are
    // both hidden by default -- caveats-last, actionable-first.
    expect(html).not.toContain('still climbing up from zero');
    expect(html).not.toContain('TSB (form) is currently');
    // TSB's short line renders first (actionable-first ordering).
    expect(html.indexOf('in range for race-day freshness')).toBeLessThan(html.indexOf('Not enough history yet'));
  });

  it('expanded view shows the cold-start caveat (last) and TSB\'s fuller explanation, with no "more" toggle', () => {
    const html = renderLoadChart(
      { status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null }, { narrativeExpanded: true },
    );
    expect(html).not.toContain('load-chart-narrative-more');
    expect(html).toContain('TSB (form) is currently');
    expect(html).toContain('still climbing up from zero');
    // The caveat is the LAST line, after TSB/CTL/ATL's long forms.
    expect(html.indexOf('TSB (form) is currently')).toBeLessThan(html.indexOf('still climbing up from zero'));
  });

  describe('TSB band actionable clause (short) vs. fuller explanation (long)', () => {
    it('productive band: short view shows the actionable clause, not the fuller explanation', () => {
      const series = [['2026-08-01', 10, 5, -5], ['2026-08-02', 10, 5, -20]]; // tsb=-20, productive
      const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: series }, error: null });
      expect(html).toContain('keep an eye on this to keep it here');
      expect(html).not.toContain('expected and good while building');
    });

    it('productive band: expanded view shows the fuller explanation', () => {
      const series = [['2026-08-01', 10, 5, -5], ['2026-08-02', 10, 5, -20]];
      const html = renderLoadChart(
        { status: 'ready', data: { ctl_atl_tsb: series }, error: null }, { narrativeExpanded: true },
      );
      expect(html).toContain('expected and good while building');
    });

    it('high-risk band: short view shows the actionable clause, not the fuller explanation', () => {
      const series = [['2026-08-01', 10, 5, -20], ['2026-08-02', 10, 5, -40]]; // tsb=-40, high-risk
      const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: series }, error: null });
      expect(html).toContain('worth easing off over the next few sessions to let fatigue clear');
      expect(html).not.toContain('fatigue is accumulating faster');
    });

    it('high-risk band: expanded view shows the fuller explanation', () => {
      const series = [['2026-08-01', 10, 5, -20], ['2026-08-02', 10, 5, -40]];
      const html = renderLoadChart(
        { status: 'ready', data: { ctl_atl_tsb: series }, error: null }, { narrativeExpanded: true },
      );
      expect(html).toContain('fatigue is accumulating faster');
    });
  });

  it('renders the wellness cross-check inline by default (showWellnessInline defaults true)', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html).toContain('wellness-baseline-deviation');
  });

  it('omits the wellness cross-check entirely when showWellnessInline is false', () => {
    const html = renderLoadChart(
      { status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null }, { showWellnessInline: false },
    );
    expect(html).not.toContain('wellness-baseline-deviation');
  });

  it('acknowledges the CTL/ATL time constants are provisional cycling-borrowed values', () => {
    const html = renderLoadChart({ status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null });
    expect(html.toLowerCase()).toContain('not yet verified for swimming');
  });

  it('escapes hostile content in the error message', () => {
    const html = renderLoadChart({ status: 'error', data: null, error: '<img src=x onerror=alert(1)>' });
    expect(html).not.toContain('<img src=x');
    expect(html).toContain('&lt;img');
  });

  describe('wellness baseline deviation (RHR/HRV cross-check)', () => {
    const readyWithDeviation = (wellness_baseline_deviation) => ({
      status: 'ready',
      data: { ctl_atl_tsb: readySeries, wellness_baseline_deviation },
      error: null,
    });

    it('shows both deviations with correct, independent good/concerning framing', () => {
      // Elevated RHR (bad) and suppressed HRV (bad) at the same time --
      // opposite raw signs, both flagged.
      const html = renderLoadChart(readyWithDeviation({
        resting_hr_pct_deviation: 9.0, hrv_pct_deviation: -12.0,
      }));
      expect(html).toContain('+9.0%');
      expect(html).toContain('-12.0%');
      expect(html).toContain('wellness-stat--concerning');
      // Both stats are concerning here -- exactly two concerning callouts.
      expect(html.match(/wellness-stat--concerning/g).length).toBe(2);
      expect(html).not.toContain('wellness-stat--good');
    });

    it('shows a good status for a mild positive RHR deviation and a mild negative HRV deviation', () => {
      const html = renderLoadChart(readyWithDeviation({
        resting_hr_pct_deviation: 1.0, hrv_pct_deviation: -1.0,
      }));
      expect(html).toContain('wellness-stat--good');
      expect(html).not.toContain('wellness-stat--concerning');
    });

    it('does NOT flag a positive HRV deviation as concerning (sign conventions are opposite for the two fields)', () => {
      const html = renderLoadChart(readyWithDeviation({
        resting_hr_pct_deviation: null, hrv_pct_deviation: 15.0,
      }));
      // A rising HRV is good, not bad -- must not be colored the same
      // direction as a rising (bad) RHR.
      expect(html).toContain('wellness-stat--good');
      expect(html).not.toContain('wellness-stat--concerning');
    });

    it('shows an honest "not enough data" state per-field when both are null, not zero and not hidden', () => {
      const html = renderLoadChart(readyWithDeviation({
        resting_hr_pct_deviation: null, hrv_pct_deviation: null,
      }));
      expect(html.toLowerCase()).toMatch(/not enough data/);
      expect(html).not.toContain('0.0%');
      expect(html.match(/wellness-stat--no-data/g).length).toBe(2);
    });

    it('shows an honest "not enough data" state for just one field when only one is null', () => {
      const html = renderLoadChart(readyWithDeviation({
        resting_hr_pct_deviation: 3.0, hrv_pct_deviation: null,
      }));
      expect(html).toContain('wellness-stat--good');
      expect(html).toContain('wellness-stat--no-data');
      expect(html.match(/wellness-stat--no-data/g).length).toBe(1);
    });

    it('still renders the wellness section (as all no-data) when the field is entirely absent from the payload', () => {
      const html = renderLoadChart({
        status: 'ready', data: { ctl_atl_tsb: readySeries }, error: null,
      });
      expect(html.match(/wellness-stat--no-data/g).length).toBe(2);
    });

    it('frames the cross-check as independent of, not a replacement for, the sRPE-derived chart above', () => {
      const html = renderLoadChart(readyWithDeviation({
        resting_hr_pct_deviation: null, hrv_pct_deviation: null,
      }));
      expect(html.toLowerCase()).toContain('independent');
      expect(html.toLowerCase()).toMatch(/not (a )?replace/);
    });

    it('keeps the deviation display visually distinct from the CTL/ATL/TSB line markup', () => {
      const html = renderLoadChart(readyWithDeviation({
        resting_hr_pct_deviation: 2.0, hrv_pct_deviation: -2.0,
      }));
      expect(html).toContain('wellness-baseline-deviation');
      expect(html).not.toMatch(/load-chart-line-(ctl|atl|tsb)"[^>]*wellness/);
    });
  });
});

// --- A6a: shared CR-10 sRPE slider ------------------------------------------

describe('CR-10 sRPE slider (A6a)', () => {
  it('uses the 0-10 CR-10 range, not the old bare 1-10 scale', () => {
    const html = renderCr10SliderField({
      value: 5, formName: 'log', field: 'rpe', outId: 'log-rpe-out',
    });
    expect(html).toContain('min="0"');
    expect(html).toContain('max="10"');
  });

  it('carries the data-form/data-field/data-slider-out attributes callers rely on', () => {
    const html = renderCr10SliderField({
      value: 5, formName: 'log', field: 'rpe', outId: 'log-rpe-out',
    });
    expect(html).toContain('data-form="log"');
    expect(html).toContain('data-field="rpe"');
    expect(html).toContain('data-slider-out="log-rpe-out"');
  });

  it.each([
    [0, 'Rest / Nothing at all'],
    [1, 'Very Easy'],
    [2, 'Easy'],
    [3, 'Moderate'],
    [4, 'Somewhat Hard'],
    [5, 'Hard'],
    [7, 'Very Hard'],
    [10, 'Maximal / Exhausting'],
  ])('shows the Foster CR-10 anchor for value %i', (value, anchor) => {
    expect(cr10AnchorLabel(value)).toBe(anchor);
    const html = renderCr10SliderField({
      value, formName: 'log', field: 'rpe', outId: 'log-rpe-out',
    });
    expect(html).toContain(anchor);
  });

  it.each([6, 8, 9])('renders an em-dash, never fabricated text, for the unanchored value %i', (value) => {
    expect(cr10AnchorLabel(value)).toBeNull();
    const html = renderCr10SliderField({
      value, formName: 'log', field: 'rpe', outId: 'log-rpe-out',
    });
    expect(html).toContain('&mdash;');
  });

  it('renders an em-dash and no `value` attribute when unset', () => {
    expect(cr10AnchorLabel('')).toBeNull();
    expect(cr10AnchorLabel(null)).toBeNull();
    expect(cr10AnchorLabel(undefined)).toBeNull();
    const html = renderCr10SliderField({
      value: '', formName: 'log', field: 'rpe', outId: 'log-rpe-out',
    });
    expect(html).toContain('&mdash;');
    expect(html).not.toMatch(/value="\d"/);
  });
});

// --- A6c: in-app "rate this workout" reminder chip --------------------------

describe('renderWorkoutRow rate-reminder chip (A6c)', () => {
  const NOW = new Date(2026, 7, 20, 12, 0, 0).getTime(); // 2026-08-20 noon, local

  function unratedWorkout(overrides = {}) {
    return {
      id: 'w-1', date: '2026-08-20', sport: 'swim_pool', source: 'fit',
      distance_m: 2000, duration_min: 30, rpe: null, ...overrides,
    };
  }

  it('shows the chip once >=30 min past the started_at+duration finish estimate', () => {
    const startedAt = new Date(NOW - 70 * 60000).toISOString(); // finishes 40 min ago (30 min duration)
    const html = renderWorkoutRow(unratedWorkout({ started_at: startedAt, duration_min: 30 }), NOW);
    expect(html).toContain('Rate this workout');
    expect(html).toContain('data-a="history:open-rate"');
  });

  it('does not show the chip before the 30-minute window has elapsed', () => {
    const startedAt = new Date(NOW - 40 * 60000).toISOString(); // finishes 10 min ago (30 min duration)
    const html = renderWorkoutRow(unratedWorkout({ started_at: startedAt, duration_min: 30 }), NOW);
    expect(html).not.toContain('Rate this workout');
  });

  it('falls back to logged_at when started_at is absent', () => {
    const loggedAt = new Date(NOW - 31 * 60000).toISOString();
    const html = renderWorkoutRow(unratedWorkout({ logged_at: loggedAt }), NOW);
    expect(html).toContain('Rate this workout');
  });

  it('never fabricates a timestamp -- no chip when both started_at and logged_at are absent', () => {
    const html = renderWorkoutRow(unratedWorkout(), NOW);
    expect(html).not.toContain('Rate this workout');
  });

  it('never shows the chip once the workout already has an rpe', () => {
    const startedAt = new Date(NOW - 120 * 60000).toISOString();
    const html = renderWorkoutRow(unratedWorkout({ started_at: startedAt, duration_min: 30, rpe: 6 }), NOW);
    expect(html).not.toContain('Rate this workout');
  });

  it('accepts an injected `now` rather than reading Date.now() unconditionally, and still works with none given', () => {
    // Mirrors history.test.js's buildHistoryFeed({ now: NOW }) injection
    // convention -- deterministic when `now` is passed, and still callable
    // (defaults to Date.now()) when it isn't.
    expect(() => renderWorkoutRow(unratedWorkout())).not.toThrow();
  });
});

// --- D2: load_au/load_tier reliability chip ---------------------------------

describe('loadTierLabel / load chips (D2)', () => {
  it.each([
    ['srpe', 'from RPE'],
    ['hr_trimp', 'from HR'],
    ['pace_if', 'from pace'],
    ['duration', 'estimated'],
  ])('labels the %s tier as "%s"', (tier, label) => {
    expect(loadTierLabel(tier)).toBe(label);
  });

  it('returns null (not a fabricated label) for an unrecognized or absent tier', () => {
    expect(loadTierLabel('bogus')).toBeNull();
    expect(loadTierLabel(undefined)).toBeNull();
    expect(loadTierLabel(null)).toBeNull();
  });

  it.each([
    ['srpe', 'from RPE'],
    ['hr_trimp', 'from HR'],
    ['pace_if', 'from pace'],
    ['duration', 'estimated'],
  ])('renders the %s tier\'s chip on a workout row', (tier, label) => {
    const html = renderWorkoutRow({
      id: 'w-1', date: '2026-08-20', sport: 'swim_pool', source: 'fit',
      distance_m: 2000, duration_min: 60, rpe: 6, load_au: 360, load_tier: tier,
    }, Date.now());
    expect(html).toContain('360');
    expect(html).toContain('AU');
    expect(html).toContain(label);
  });

  it('renders nothing extra when load_au/load_tier are absent -- defensive for old cached data', () => {
    const html = renderWorkoutRow({
      id: 'w-1', date: '2026-08-20', sport: 'swim_pool', source: 'fit',
      distance_m: 2000, duration_min: 60, rpe: 6,
    }, Date.now());
    expect(html).not.toContain('AU');
  });
});

// --- Explicit "no RPE" indicator (coach-load-visibility-and-narrative-polish) ----
// Previously a missing rpe rendered nothing at all -- the athlete/coach
// couldn't tell "no RPE was recorded" from "the row hasn't rendered yet."
// Both renderWorkoutRow (the athlete's own history row) and
// renderCoachWorkoutRow (the coach's per-athlete row, exercised here via
// renderRosterTab) must show the same explicit indicator, and a real rpe
// must still render the existing "RPE {n}" chip unchanged in both.

describe('explicit "No RPE" indicator', () => {
  it('renderWorkoutRow shows a "No RPE" chip when rpe is null', () => {
    const html = renderWorkoutRow({
      id: 'w-1', date: '2026-08-20', sport: 'swim_pool', source: 'fit',
      distance_m: 2000, duration_min: 60, rpe: null,
    }, Date.now());
    expect(html).toContain('No RPE');
    expect(html).not.toContain('RPE null');
  });

  it('renderWorkoutRow shows a "No RPE" chip when rpe is undefined', () => {
    const html = renderWorkoutRow({
      id: 'w-1', date: '2026-08-20', sport: 'swim_pool', source: 'fit',
      distance_m: 2000, duration_min: 60,
    }, Date.now());
    expect(html).toContain('No RPE');
  });

  it('renderWorkoutRow still shows "RPE {n}" and no "No RPE" chip when rpe is a real number', () => {
    const html = renderWorkoutRow({
      id: 'w-1', date: '2026-08-20', sport: 'swim_pool', source: 'fit',
      distance_m: 2000, duration_min: 60, rpe: 6,
    }, Date.now());
    expect(html).toContain('RPE 6');
    expect(html).not.toContain('No RPE');
  });

  it("renderCoachWorkoutRow (coach roster) shows a \"No RPE\" chip when rpe is null", () => {
    const html = renderRosterTab({
      athletes: { status: 'ready', data: [{ slug: 'renee', name: 'Renee' }], error: null },
      actingAsAthlete: 'renee',
      workouts: {
        status: 'ready',
        data: [{
          id: 'w1', date: '2026-08-24', sport: 'swim_pool', source: 'fit',
          rpe: null, duration_min: 45, distance_m: 2000,
          quality: { matched: true, distance_delta_pct: null, duration_delta_pct: null, intensity_match: 'unknown', quality_summary: null },
        }],
        error: null,
      },
      feedback: { status: 'idle', data: [], error: null },
      replyDrafts: {},
      replySubmit: { status: 'idle', error: null, feedbackId: null },
      workoutDetailId: null,
      backendConfigured: true,
      online: true,
    });
    expect(html).toContain('No RPE');
  });

  it('renderCoachWorkoutRow (coach roster) still shows "RPE {n}" and no "No RPE" chip when rpe is a real number', () => {
    const html = renderRosterTab({
      athletes: { status: 'ready', data: [{ slug: 'renee', name: 'Renee' }], error: null },
      actingAsAthlete: 'renee',
      workouts: {
        status: 'ready',
        data: [{
          id: 'w1', date: '2026-08-24', sport: 'swim_pool', source: 'fit',
          rpe: 6, duration_min: 45, distance_m: 2000,
          quality: { matched: true, distance_delta_pct: null, duration_delta_pct: null, intensity_match: 'unknown', quality_summary: null },
        }],
        error: null,
      },
      feedback: { status: 'idle', data: [], error: null },
      replyDrafts: {},
      replySubmit: { status: 'idle', error: null, feedbackId: null },
      workoutDetailId: null,
      backendConfigured: true,
      online: true,
    });
    expect(html).toContain('RPE 6');
    expect(html).not.toContain('No RPE');
  });
});

// --- D1: planned/target load tile on the Plan tab's session detail ---------

describe('renderPlanSessionDetailStats target load (D1)', () => {
  function planWithSession(session) {
    return {
      athlete: { name: 'Renee' },
      events: [],
      macro: { blocks: [] },
      weeks: [{
        iso_week: '2099-W01', meso_block: 'base', focus: 'aerobic base',
        target_volume_m: 10000, sessions: [session], adaptation_rationale: null,
      }],
    };
  }

  it('renders session.target_load_au as a "Target load (AU)" tile', () => {
    const session = {
      id: 's-1', date: '2099-01-05', sport: 'swim_pool', source: 'ai_coach',
      duration_min: 60, distance_m: 2000, intensity: { zone: 'Z2' },
      purpose: 'aerobic set', structure: null, structured: null, status: 'planned',
      target_load_au: 260,
    };
    const html = renderApp(planWithSession(session), 's-1');
    expect(html).toContain('Target load (AU)');
    expect(html).toContain('260');
  });

  it('renders nothing extra when target_load_au is absent', () => {
    const session = {
      id: 's-2', date: '2099-01-05', sport: 'swim_pool', source: 'ai_coach',
      duration_min: 60, distance_m: 2000, intensity: { zone: 'Z2' },
      purpose: 'aerobic set', structure: null, structured: null, status: 'planned',
    };
    const html = renderApp(planWithSession(session), 's-2');
    expect(html).not.toContain('Target load (AU)');
  });
});

// --- A6b: editable RPE on the workout detail view ---------------------------

describe('RPE editor affordance on the workout detail view (A6b)', () => {
  const UNRATED = {
    id: 'w-unrated', date: '2026-08-20', sport: 'swim_pool', source: 'fit',
    distance_m: 2000, duration_min: 40, rpe: null, notes: null,
    avg_hr: null, max_hr: null, analytics: null, laps: [], lengths: [], pauses: [],
  };

  it('shows a "Rate this workout" toggle on the athlete\'s own Dashboard tab when unrated', () => {
    const html = renderDashboardTab({
      ...DASHBOARD_BASE_ARGS, feed: feedOf([UNRATED]), detailId: 'w-unrated',
    });
    expect(html).toContain('data-a="workout:edit-rpe"');
    expect(html).toContain('Rate this workout');
  });

  it('swaps in the CR-10 slider + Save/Cancel once rpeEdit targets this workout', () => {
    const html = renderDashboardTab({
      ...DASHBOARD_BASE_ARGS,
      feed: feedOf([UNRATED]),
      detailId: 'w-unrated',
      rpeEdit: {
        workoutId: 'w-unrated', rpe: 6, status: 'idle', error: null,
      },
    });
    expect(html).toContain('data-a="workout:save-rpe"');
    expect(html).toContain('data-a="workout:cancel-edit-rpe"');
    expect(html).toContain('data-form="workoutRpe"');
  });

  it('surfaces a save error message', () => {
    const html = renderDashboardTab({
      ...DASHBOARD_BASE_ARGS,
      feed: feedOf([UNRATED]),
      detailId: 'w-unrated',
      rpeEdit: {
        workoutId: 'w-unrated', rpe: 6, status: 'error', error: 'invalid rpe',
      },
    });
    expect(html).toContain('invalid rpe');
  });

  it("never shows the RPE editor on the coach roster's read-only view of the same workout", () => {
    const html = renderRosterTab({
      athletes: { status: 'ready', data: [{ slug: 'renee', name: 'Renee' }], error: null },
      actingAsAthlete: 'renee',
      workouts: { status: 'ready', data: [UNRATED], error: null },
      feedback: { status: 'idle', data: [], error: null },
      replyDrafts: {},
      replySubmit: { status: 'idle', error: null, feedbackId: null },
      workoutDetailId: 'w-unrated',
      backendConfigured: true,
      online: true,
    });
    expect(html).not.toContain('data-a="workout:edit-rpe"');
  });
});

// --- Macro-block week-count off-by-one (coach-load-visibility-and-narrative-polish) ----
// Previous formula: round(dayDiff / 7) + 1 -- takes the raw EXCLUSIVE
// day-difference, divides by 7, THEN adds 1, double-counting the
// "+1 for inclusive dates" adjustment and overcounting every block by
// exactly one week. Fixed: round((dayDiff + 1) / 7) -- make the span
// inclusive-of-both-endpoints BEFORE dividing by 7. These are the real
// four blocks from this athlete's real production macro plan (see the PR
// description's hand-computation) -- base/build/peak/taper should now
// read 3/1/2/2 real calendar weeks, not the old (wrong) 4/2/3/3.

describe('renderMacroSection week-count (macro-block off-by-one fix)', () => {
  const REAL_MACRO_BLOCKS = [
    { name: 'Base', start_date: '2026-08-31', end_date: '2026-09-20', weekly_volume_target_m: 20000 },
    { name: 'Build', start_date: '2026-09-21', end_date: '2026-09-27', weekly_volume_target_m: 24000 },
    { name: 'Peak', start_date: '2026-09-28', end_date: '2026-10-11', weekly_volume_target_m: 28000 },
    { name: 'Taper', start_date: '2026-10-12', end_date: '2026-10-25', weekly_volume_target_m: 14000 },
  ];

  const MACRO_PLAN_DATA = {
    athlete: { name: 'Renee' }, events: [], macro: { blocks: REAL_MACRO_BLOCKS }, weeks: [],
  };

  it('labels each real block with the correct inclusive calendar-week count, not overcounted by one', () => {
    const html = renderApp(MACRO_PLAN_DATA, null);
    expect(html).toContain('3 wk'); // Base: 2026-08-31..2026-09-20, 21 days = 3 weeks
    expect(html).toContain('1 wk'); // Build: 2026-09-21..2026-09-27, 7 days = 1 week
    // Peak and Taper are both 2 wk (14 days each) -- assert the count of "2 wk"
    // occurrences rather than presence alone, since two distinct blocks share it.
    const twoWkMatches = html.match(/2 wk/g) || [];
    expect(twoWkMatches.length).toBe(2);
    // Old (wrong) formula's overcount for Base ("4 wk") must not appear.
    expect(html).not.toContain('4 wk');
  });

  it('does not render the old off-by-one overcounts for any of the four real blocks', () => {
    const html = renderApp(MACRO_PLAN_DATA, null);
    // Old formula gave Base "4 wk", Build "2 wk", Peak "3 wk", Taper "3 wk".
    // Build's old wrong value ("2 wk") coincides with Peak/Taper's correct
    // value, so it can't be asserted absent globally -- but Base's "4 wk"
    // and the "3 wk" that used to apply to Peak/Taper can be checked
    // precisely: with the fix, exactly one block ("Base") should read "3 wk",
    // not two or more.
    const threeWkMatches = html.match(/3 wk/g) || [];
    expect(threeWkMatches.length).toBe(1);
    expect(html).not.toContain('4 wk');
  });

  it('floors a same-day (degenerate) block at 1 week, never 0', () => {
    // Regression: the corrected inclusive-day-span formula
    // (Math.round(((end-start)/86400000+1)/7)) rounds DOWN to 0 for any
    // block spanning ~3 calendar days or fewer (e.g. a same-day
    // start_date===end_date block: (0+1)/7 = 0.14, rounds to 0) -- unlike
    // the old formula, which could never go below 1 since its own "+1" was
    // added AFTER rounding. A `flex:0` block collapses to zero/degenerate
    // width and a literal "0 wk" label would render -- both nonsensical
    // for a block that, however short, still spans at least one real day.
    // totalWeeks and the race-marker block a few lines below already guard
    // the same expression with `Math.max(1, ...)`; weeksInBlock must too.
    const degenerateBlocks = [
      { name: 'Base', start_date: '2026-08-31', end_date: '2026-08-31', weekly_volume_target_m: 20000 },
    ];
    const html = renderApp(
      { athlete: { name: 'Renee' }, events: [], macro: { blocks: degenerateBlocks }, weeks: [] },
      null,
    );
    expect(html).toContain('1 wk');
    expect(html).not.toContain('0 wk');
    expect(html).not.toMatch(/flex:0[^.\d]/);
  });
});
