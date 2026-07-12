import { describe, it, expect } from 'vitest';
import { renderHistorySection, renderLogTab } from '../../src/views.js';

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

describe('renderLogTab', () => {
  const baseArgs = {
    form: { date: '2026-07-11', sport: 'swim_pool', distance_m: '', duration_min: '', rpe: 5, notes: '' },
    submit: { status: 'idle', message: null },
    ingest: { status: 'idle', fileName: null, error: null },
    backendConfigured: true,
    online: true,
    history: { status: 'idle', data: [], error: null },
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
});
