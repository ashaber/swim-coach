import { describe, it, expect } from 'vitest';
import {
  renderHistorySection, renderLogTab, renderSettingsTab, renderUpdateBanner, renderApp,
  renderHistoryTab,
} from '../../src/views.js';
import { isoWeekMonday, addDays, dateKey } from '../../src/plan.js';

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

describe('renderHistorySection', () => {
  it('renders a workout row with a compact analytics line when analytics has content', () => {
    const html = renderHistorySection({ status: 'ready', data: [CROSS_TRAIN_WORKOUT], error: null, online: true });
    expect(html).toContain('Cross-train');
    expect(html).toContain('hist-analytics');
    expect(html).toContain('drift -13.8%');
    expect(html).toContain('fit'); // source badge
    expect(html).toContain('RPE 6');
  });

  it('renders the real swolf example fields', () => {
    const html = renderHistorySection({ status: 'ready', data: [POOL_SWIM_WORKOUT], error: null, online: true });
    expect(html).toContain('SWOLF 41.0→43.4 (+6.0%)');
    expect(html).toContain('3.2 km');
    expect(html).toContain('1:35 /100m');
  });

  it('renders a workout row with no analytics line when analytics is null', () => {
    const html = renderHistorySection({ status: 'ready', data: [OLD_MANUAL_WORKOUT], error: null, online: true });
    expect(html).not.toContain('hist-analytics');
    // Manual source gets no source badge chip.
    expect(html).not.toContain('chat-chip');
  });

  it('renders multiple rows newest-first order as given (does not re-sort)', () => {
    const html = renderHistorySection({
      status: 'ready', data: [CROSS_TRAIN_WORKOUT, POOL_SWIM_WORKOUT], error: null, online: true,
    });
    const crossIdx = html.indexOf('Cross-train');
    const poolIdx = html.indexOf('Pool swim');
    expect(crossIdx).toBeGreaterThan(-1);
    expect(poolIdx).toBeGreaterThan(crossIdx);
  });

  it('shows an empty-state message when there are no workouts', () => {
    const html = renderHistorySection({ status: 'ready', data: [], error: null, online: true });
    expect(html).toContain('No workouts logged yet.');
  });

  it('shows a loading message while loading with nothing cached yet', () => {
    const html = renderHistorySection({ status: 'loading', data: [], error: null, online: true });
    expect(html).toContain('Loading history');
  });

  it('shows the error message and a retry action on fetch failure', () => {
    const html = renderHistorySection({
      status: 'error', data: [], error: 'Backend error (500).', online: true,
    });
    expect(html).toContain("Couldn't load your workout history");
    expect(html).toContain('Backend error (500).');
    expect(html).toContain('data-a="history:retry"');
  });

  it('still shows stale cached data alongside an error banner on a failed refresh', () => {
    const html = renderHistorySection({
      status: 'error', data: [OLD_MANUAL_WORKOUT], error: 'offline', online: false,
    });
    expect(html).toContain('Pool swim');
    expect(html).toContain("Couldn't load your workout history");
  });

  it('shows a quiet offline notice (not the empty-log message) when idle and offline', () => {
    const html = renderHistorySection({ status: 'idle', data: [], error: null, online: false });
    expect(html).toContain('reconnect');
    expect(html).not.toContain('No workouts logged yet.');
  });

  it('escapes workout notes/text content (no raw HTML injection)', () => {
    const malicious = { ...OLD_MANUAL_WORKOUT, sport: '<img src=x onerror=alert(1)>' };
    const html = renderHistorySection({ status: 'ready', data: [malicious], error: null, online: true });
    expect(html).not.toContain('<img src=x');
    expect(html).toContain('&lt;img');
  });
});

describe('renderHistorySection detail view (Slice 2: tap a row to open detail)', () => {
  it('renders the detail view instead of the list when detailId matches a workout', () => {
    const html = renderHistorySection({
      status: 'ready', data: [RICH_FIT_WORKOUT, OLD_MANUAL_WORKOUT], error: null, online: true, detailId: 'w-rich',
    });
    expect(html).toContain('data-a="history:back"');
    expect(html).not.toContain('data-a="history:open"');
    // Header: sport, date, source badge.
    expect(html).toContain('Open water swim');
    expect(html).toContain('fit');
  });

  it('renders summary stats: distance, duration, pace, RPE, avg/max HR', () => {
    const html = renderHistorySection({
      status: 'ready', data: [RICH_FIT_WORKOUT], error: null, online: true, detailId: 'w-rich',
    });
    expect(html).toContain('5 km');
    expect(html).toContain('1 h 35 min');
    expect(html).toContain('1:54 /100m');
    expect(html).toContain('7/10');
    expect(html).toContain('132 bpm');
    expect(html).toContain('158 bpm');
  });

  it('renders the full analytics block with drift warning, split, moving-vs-elapsed, pauses, and swolf', () => {
    const html = renderHistorySection({
      status: 'ready', data: [RICH_FIT_WORKOUT], error: null, online: true, detailId: 'w-rich',
    });
    expect(html).toContain('drift +6.4% ⚠');
    expect(html).toContain('positive split (1:48 → 2:00)');
    expect(html).toContain('1 h 35 min moving of 1 h 38 min');
    expect(html).toContain('2 pauses · 3 min stopped');
    expect(html).toContain('SWOLF 38.2→44.9 (+17.5%)');
  });

  it('renders a laps table with index, distance, duration, pace, and HR', () => {
    const html = renderHistorySection({
      status: 'ready', data: [RICH_FIT_WORKOUT], error: null, online: true, detailId: 'w-rich',
    });
    expect(html).toContain('laps-table');
    expect(html).toContain('2.5 km');
    expect(html).toContain('30:30'); // 1830s
    expect(html).toContain('1:48'); // 108s/100m pace
    expect(html).toContain('128'); // lap avg HR
  });

  it('renders a pauses list with offset (h:mm:ss), duration, and source', () => {
    const html = renderHistorySection({
      status: 'ready', data: [RICH_FIT_WORKOUT], error: null, online: true, detailId: 'w-rich',
    });
    expect(html).toContain('0:12:34'); // 754s offset
    expect(html).toContain('gap');
    expect(html).toContain('timer');
  });

  it('renders notes verbatim (escaped)', () => {
    const html = renderHistorySection({
      status: 'ready', data: [RICH_FIT_WORKOUT], error: null, online: true, detailId: 'w-rich',
    });
    expect(html).toContain('Choppy back half, felt strong.');
  });

  it('escapes malicious notes content in the detail view', () => {
    const malicious = { ...RICH_FIT_WORKOUT, notes: '<img src=x onerror=alert(1)>' };
    const html = renderHistorySection({
      status: 'ready', data: [malicious], error: null, online: true, detailId: 'w-rich',
    });
    expect(html).not.toContain('<img src=x');
    expect(html).toContain('&lt;img');
  });

  it('renders a bare manual workout (no laps/pauses/analytics) with clean summary stats only', () => {
    const html = renderHistorySection({
      status: 'ready', data: [OLD_MANUAL_WORKOUT], error: null, online: true, detailId: 'w-old',
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

  it('falls back to the list when detailId does not match any loaded workout', () => {
    const html = renderHistorySection({
      status: 'ready', data: [OLD_MANUAL_WORKOUT], error: null, online: true, detailId: 'no-such-id',
    });
    expect(html).not.toContain('data-a="history:back"');
    expect(html).toContain('data-a="history:open"');
  });

  it('renders the list (not detail) when detailId is null', () => {
    const html = renderHistorySection({
      status: 'ready', data: [OLD_MANUAL_WORKOUT], error: null, online: true, detailId: null,
    });
    expect(html).not.toContain('data-a="history:back"');
    expect(html).toContain('data-a="history:open"');
  });
});

describe('renderHistorySection embedded workout chat (Phase C slice 1)', () => {
  const openDetailArgs = {
    status: 'ready', data: [RICH_FIT_WORKOUT], error: null, online: true, detailId: 'w-rich',
  };

  it('renders the scoped chat section with the "About:" label when workoutChat matches the open detail', () => {
    const html = renderHistorySection({
      ...openDetailArgs, workoutChat: { workoutId: 'w-rich', messages: [] },
    });
    expect(html).toContain('Ask your coach about this workout');
    expect(html).toContain('About: Jun 1 Open water swim');
    expect(html).toContain('id="workout-chat-input"');
    expect(html).toContain('data-a="workout-chat:send"');
  });

  it('omits the chat section entirely when workoutChat is null', () => {
    const html = renderHistorySection({ ...openDetailArgs, workoutChat: null });
    expect(html).not.toContain('Ask your coach about this workout');
    expect(html).not.toContain('workout-chat-input');
  });

  it('omits the chat section when workoutChat belongs to a different workout', () => {
    const html = renderHistorySection({
      ...openDetailArgs, workoutChat: { workoutId: 'w-other', messages: [] },
    });
    expect(html).not.toContain('Ask your coach about this workout');
  });

  it('renders thread messages with the coach-tab bubble classes', () => {
    const html = renderHistorySection({
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
    const html = renderHistorySection({
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
    const html = renderHistorySection({
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
    const html = renderHistorySection({
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
  });
});

describe('renderLogTab', () => {
  const baseArgs = {
    form: { date: '2026-07-11', sport: 'swim_pool', distance_m: '', duration_min: '', rpe: 5, notes: '' },
    submit: { status: 'idle', message: null },
    ingest: { status: 'idle', fileName: null, error: null },
    backendConfigured: true,
    online: true,
    history: { status: 'idle', data: [], error: null },
    sync: { status: 'idle', message: null },
    manualOpen: false,
  };

  it('includes the history section when backend is configured', () => {
    const html = renderLogTab({
      ...baseArgs, history: { status: 'ready', data: [CROSS_TRAIN_WORKOUT], error: null },
    });
    expect(html).toContain('Recent workouts');
    expect(html).toContain('Cross-train');
  });

  it('omits the history section (and the whole form) when backend is not configured', () => {
    const html = renderLogTab({
      ...baseArgs, backendConfigured: false, history: { status: 'idle', data: [], error: null },
    });
    expect(html).not.toContain('Recent workouts');
  });

  it('passes detailId through to the history section, opening the detail view', () => {
    const html = renderLogTab({
      ...baseArgs, history: { status: 'ready', data: [CROSS_TRAIN_WORKOUT], error: null }, detailId: 'w-cross',
    });
    expect(html).toContain('data-a="history:back"');
  });

  // --- Phase 3: "Sync from watch" primary action, manual entry secondary ---

  it('always shows the primary sync button ahead of the (collapsed) manual section', () => {
    const html = renderLogTab(baseArgs);
    const syncIdx = html.indexOf('data-a="sync:start"');
    const toggleIdx = html.indexOf('data-a="log:toggle-manual"');
    const historyIdx = html.indexOf('Recent workouts');
    expect(syncIdx).toBeGreaterThan(-1);
    expect(toggleIdx).toBeGreaterThan(syncIdx);
    expect(historyIdx).toBeGreaterThan(toggleIdx);
  });

  it('shows "Sync from watch" idle label, enabled, when online and idle', () => {
    const html = renderLogTab(baseArgs);
    expect(html).toContain('Sync from watch');
    const btnMatch = /<button[^>]*data-a="sync:start"[^>]*>/.exec(html);
    expect(btnMatch[0]).not.toContain('disabled');
  });

  it('shows a busy "Syncing…" label and disables the button while syncing', () => {
    const html = renderLogTab({ ...baseArgs, sync: { status: 'syncing', message: null } });
    expect(html).toContain('Syncing');
    const btnMatch = /<button[^>]*data-a="sync:start"[^>]*>/.exec(html);
    expect(btnMatch[0]).toContain('disabled');
  });

  it('disables the sync button while offline', () => {
    const html = renderLogTab({ ...baseArgs, online: false });
    const btnMatch = /<button[^>]*data-a="sync:start"[^>]*>/.exec(html);
    expect(btnMatch[0]).toContain('disabled');
  });

  it('shows a success result line with the ok treatment', () => {
    const html = renderLogTab({
      ...baseArgs, sync: { status: 'success', message: '2 new workouts synced' },
    });
    expect(html).toContain('conn-result ok');
    expect(html).toContain('2 new workouts synced');
  });

  it('shows an error result line verbatim with the fail treatment', () => {
    const html = renderLogTab({
      ...baseArgs, sync: { status: 'error', message: 'sync not configured for this athlete' },
    });
    expect(html).toContain('conn-result fail');
    expect(html).toContain('sync not configured for this athlete');
  });

  it('collapses the manual entry/upload section by default, showing only the toggle', () => {
    const html = renderLogTab(baseArgs);
    expect(html).toContain('Log manually / upload a file');
    expect(html).not.toContain('data-a="log:file-select"');
    expect(html).not.toContain('data-form="log" data-field="date"');
  });

  it('expands the manual form and upload input when manualOpen is true', () => {
    const html = renderLogTab({ ...baseArgs, manualOpen: true });
    expect(html).toContain('data-a="log:file-select"');
    expect(html).toContain('data-form="log" data-field="date"');
    expect(html).toContain('Hide manual entry');
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

describe('renderHistoryTab', () => {
  const COMPLETED = {
    id: 'w-done', date: '2026-08-17', sport: 'swim_pool', source: 'fit',
    distance_m: 2050, duration_min: 61, rpe: 6, avg_pace_s_per_100m: 95,
    planned_session_id: null, analytics: null, laps: [], pauses: [],
  };
  const SKIPPED_SESSION = {
    id: 's-missed', date: '2026-08-18', sport: 'strength', source: 'ai_coach',
    duration_min: 45, distance_m: null, intensity: {},
    purpose: 'Dryland shoulder strength — rotator-cuff work',
    structure: null, structured: null, status: 'planned',
  };
  const FEED = [
    { kind: 'skipped', date: '2026-08-18', key: 's:s-missed', session: SKIPPED_SESSION },
    { kind: 'completed', date: '2026-08-17', key: 'w:w-done', workout: COMPLETED },
  ];

  const base = {
    feed: FEED, status: 'ready', error: null, online: true,
    detailId: null, workoutChat: null, backendConfigured: true,
  };

  it('renders completed workouts with their actual logged stats', () => {
    const html = renderHistoryTab(base);
    expect(html).toContain('Pool swim');
    // The ACTUAL logged distance (2050 m -> "2.1 km" per
    // formatWorkoutDistance), not the 2000 m the plan had targeted.
    expect(html).toContain('2.1 km');
    expect(html).toContain('RPE 6');
  });

  it('renders a skipped planned session with what was planned', () => {
    const html = renderHistoryTab(base);
    expect(html).toContain('Strength');
    expect(html).toContain('Dryland shoulder strength');
    expect(html).toContain('45 min'); // the planned duration
  });

  it('clearly distinguishes a skipped item from a completed one', () => {
    const html = renderHistoryTab(base);
    expect(html).toContain('hist-row-skipped');
    expect(html).toContain('Skipped');
  });

  it('keeps the feed order given -- newest first, no re-sorting', () => {
    const html = renderHistoryTab(base);
    expect(html.indexOf('Dryland shoulder strength')).toBeLessThan(html.indexOf('Pool swim'));
  });

  it('makes completed rows tappable for detail but skipped rows not', () => {
    const html = renderHistoryTab(base);
    expect(html).toContain('data-a="history:open" data-id="w-done"');
    expect(html).not.toContain('data-id="s-missed"');
  });

  it('opens the workout detail view when detailId matches a completed item', () => {
    const html = renderHistoryTab({ ...base, detailId: 'w-done' });
    expect(html).toContain('data-a="history:back"');
    expect(html).toContain('Distance');
    expect(html).not.toContain('data-a="history:open"');
  });

  it('shows an empty state when nothing has happened yet', () => {
    const html = renderHistoryTab({ ...base, feed: [] });
    expect(html).toContain('Nothing logged or missed yet');
  });

  it('shows a loading state before the first load lands', () => {
    const html = renderHistoryTab({ ...base, feed: [], status: 'loading' });
    expect(html).toContain('Loading');
  });

  it('surfaces an error with a retry action, keeping any stale feed visible', () => {
    const html = renderHistoryTab({ ...base, status: 'error', error: 'boom' });
    expect(html).toContain('boom');
    expect(html).toContain('data-a="history:retry"');
    expect(html).toContain('Pool swim'); // stale data still shown
  });

  it('tells the athlete when history needs a connection', () => {
    const html = renderHistoryTab({ ...base, feed: [], online: false });
    expect(html).toContain('connection');
  });

  it('prompts for setup when the backend is not configured', () => {
    const html = renderHistoryTab({ ...base, backendConfigured: false });
    expect(html).toContain('Settings');
  });

  it('escapes hostile content in a skipped session purpose', () => {
    const nasty = {
      ...SKIPPED_SESSION, id: 's-nasty', purpose: '<img src=x onerror=alert(1)>',
    };
    const html = renderHistoryTab({
      ...base,
      feed: [{ kind: 'skipped', date: '2026-08-18', key: 's:s-nasty', session: nasty }],
    });
    expect(html).not.toContain('<img src=x');
    expect(html).toContain('&lt;img');
  });
});
