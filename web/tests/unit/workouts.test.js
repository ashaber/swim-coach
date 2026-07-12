import { describe, it, expect } from 'vitest';
import {
  sportLabel, sourceBadge, formatWorkoutDistance, sortWorkoutsNewestFirst,
  formatDrift, formatSplit, formatPauses, formatSwolf, formatMovingVsElapsed,
  formatAnalyticsLine, HISTORY_DISPLAY_CAP,
  formatOffset, formatClock, formatLengthsSummary,
} from '../../src/workouts.js';

describe('sportLabel', () => {
  it('labels every known sport including cross_train', () => {
    expect(sportLabel('swim_pool')).toBe('Pool swim');
    expect(sportLabel('swim_ow')).toBe('Open water swim');
    expect(sportLabel('strength')).toBe('Strength');
    expect(sportLabel('recovery')).toBe('Recovery');
    expect(sportLabel('cross_train')).toBe('Cross-train');
  });
  it('falls back to the raw value for an unknown sport', () => {
    expect(sportLabel('kayak')).toBe('kayak');
  });
  it('renders exactly as before for a cross_train workout with no sport_detail', () => {
    // Back-compat: every workout logged before this feature has
    // sport_detail undefined/null -- must not grow a suffix.
    expect(sportLabel('cross_train', undefined)).toBe('Cross-train');
    expect(sportLabel('cross_train', null)).toBe('Cross-train');
  });
  it('appends a pretty sport_detail suffix for cross_train', () => {
    expect(sportLabel('cross_train', 'cycling/mountain')).toBe('Cross-train · MTB');
    expect(sportLabel('cross_train', 'cycling/road')).toBe('Cross-train · Road ride');
    expect(sportLabel('cross_train', 'kayaking')).toBe('Cross-train · Kayak');
    expect(sportLabel('cross_train', 'walking')).toBe('Cross-train · Walk');
    expect(sportLabel('cross_train', 'cycling')).toBe('Cross-train · Bike');
  });
  it('falls back to a title-cased, underscore-stripped detail when unmapped', () => {
    expect(sportLabel('cross_train', 'training/strength_training')).toBe('Cross-train · Strength Training');
  });
  it('ignores sport_detail for non-cross_train sports', () => {
    expect(sportLabel('swim_pool', 'cycling/mountain')).toBe('Pool swim');
  });
});

describe('sourceBadge', () => {
  it('returns null for manual entries', () => {
    expect(sourceBadge('manual')).toBeNull();
  });
  it('badges fit/tcx/csv/coach_text sources', () => {
    expect(sourceBadge('fit')).toBe('fit');
    expect(sourceBadge('tcx')).toBe('tcx');
    expect(sourceBadge('csv')).toBe('csv');
    expect(sourceBadge('coach_text')).toBe('coach');
  });
});

describe('formatWorkoutDistance', () => {
  it('renders sub-1000m distances in meters', () => {
    expect(formatWorkoutDistance(800)).toBe('800 m');
  });
  it('renders >=1000m distances in km with one decimal', () => {
    expect(formatWorkoutDistance(3000)).toBe('3 km');
    expect(formatWorkoutDistance(3250)).toBe('3.3 km');
  });
  it('returns null for a null/undefined distance', () => {
    expect(formatWorkoutDistance(null)).toBeNull();
    expect(formatWorkoutDistance(undefined)).toBeNull();
  });
});

describe('sortWorkoutsNewestFirst', () => {
  it('sorts by date descending without mutating the input', () => {
    const input = [{ date: '2026-03-14' }, { date: '2026-07-09' }, { date: '2026-01-01' }];
    const sorted = sortWorkoutsNewestFirst(input);
    expect(sorted.map((w) => w.date)).toEqual(['2026-07-09', '2026-03-14', '2026-01-01']);
    expect(input.map((w) => w.date)).toEqual(['2026-03-14', '2026-07-09', '2026-01-01']);
  });
});

describe('HISTORY_DISPLAY_CAP', () => {
  it('caps display at 20', () => {
    expect(HISTORY_DISPLAY_CAP).toBe(20);
  });
});

describe('formatDrift', () => {
  it('formats a negative drift with a minus sign and no warning', () => {
    expect(formatDrift(-13.77)).toBe('drift -13.8%');
  });
  it('formats a positive drift under the warning threshold with a plus sign', () => {
    expect(formatDrift(2.3)).toBe('drift +2.3%');
  });
  it('adds a warning marker at or above +5%', () => {
    expect(formatDrift(5.0)).toBe('drift +5.0% ⚠');
    expect(formatDrift(8.4)).toBe('drift +8.4% ⚠');
  });
  it('returns null when drift is null', () => {
    expect(formatDrift(null)).toBeNull();
  });
});

describe('formatSplit', () => {
  it('combines the split label with both half-paces', () => {
    const analytics = { split_label: 'negative', first_half_pace_s_per_100m: 92, second_half_pace_s_per_100m: 88 };
    expect(formatSplit(analytics)).toBe('negative split (1:32 → 1:28)');
  });
  it('falls back to the bare label when half-paces are missing', () => {
    expect(formatSplit({ split_label: 'even' })).toBe('even split');
  });
  it('returns null when there is no split label', () => {
    expect(formatSplit({})).toBeNull();
    expect(formatSplit(null)).toBeNull();
  });
});

describe('formatPauses', () => {
  it('returns null when there were no pauses', () => {
    expect(formatPauses({ pause_count: 0, pause_total_min: 0 })).toBeNull();
    expect(formatPauses({})).toBeNull();
  });
  it('formats pause count and stopped time', () => {
    expect(formatPauses({ pause_count: 3, pause_total_min: 12 })).toBe('3 pauses · 12 min stopped');
  });
  it('uses singular "pause" for a count of 1', () => {
    expect(formatPauses({ pause_count: 1, pause_total_min: 4 })).toBe('1 pause · 4 min stopped');
  });
  it('omits stopped time when pause_total_min is missing', () => {
    expect(formatPauses({ pause_count: 2, pause_total_min: null })).toBe('2 pauses');
  });
});

describe('formatSwolf', () => {
  it('matches the real andrew 2026-03-14 pool swim example', () => {
    const analytics = { swolf_first_quarter: 40.96, swolf_last_quarter: 43.41, swolf_degradation_pct: 6.0 };
    expect(formatSwolf(analytics)).toBe('SWOLF 41.0→43.4 (+6.0%)');
  });
  it('omits the percentage when degradation is not present', () => {
    expect(formatSwolf({ swolf_first_quarter: 40, swolf_last_quarter: 41 })).toBe('SWOLF 40.0→41.0');
  });
  it('returns null when either quarter is missing', () => {
    expect(formatSwolf({ swolf_first_quarter: 40 })).toBeNull();
    expect(formatSwolf({})).toBeNull();
  });
});

describe('formatMovingVsElapsed', () => {
  it('returns null when moving and elapsed are within a minute of each other', () => {
    expect(formatMovingVsElapsed({ moving_min: 60, elapsed_min: 60.4 })).toBeNull();
  });
  it('renders both durations when they meaningfully diverge', () => {
    expect(formatMovingVsElapsed({ moving_min: 60, elapsed_min: 75 })).toBe('1 h moving of 1 h 15 min');
  });
  it('returns null when either field is missing', () => {
    expect(formatMovingVsElapsed({ moving_min: 60 })).toBeNull();
  });
});

describe('formatAnalyticsLine', () => {
  it('returns null when analytics is absent (older manual workouts)', () => {
    expect(formatAnalyticsLine(null)).toBeNull();
    expect(formatAnalyticsLine(undefined)).toBeNull();
  });
  it('returns null when analytics is present but every field is null', () => {
    const allNull = {
      cardiac_drift_pct: null, split_label: null, first_half_pace_s_per_100m: null,
      second_half_pace_s_per_100m: null, pause_count: null, pause_total_min: null,
      swolf_first_quarter: null, swolf_last_quarter: null, swolf_degradation_pct: null,
      moving_min: null, elapsed_min: null,
    };
    expect(formatAnalyticsLine(allNull)).toBeNull();
  });
  it('joins the real andrew 2026-07-09 cross_train example fields', () => {
    const analytics = { cardiac_drift_pct: -13.77, pause_count: 0, moving_min: 303.3, elapsed_min: 303.3 };
    expect(formatAnalyticsLine(analytics)).toBe('drift -13.8%');
  });
  it('joins multiple present fields with a middle dot', () => {
    const analytics = {
      cardiac_drift_pct: 6.1,
      split_label: 'positive',
      first_half_pace_s_per_100m: 90,
      second_half_pace_s_per_100m: 96,
      pause_count: 2,
      pause_total_min: 5,
    };
    expect(formatAnalyticsLine(analytics)).toBe(
      'drift +6.1% ⚠ · positive split (1:30 → 1:36) · 2 pauses · 5 min stopped',
    );
  });
});

describe('formatOffset', () => {
  it('always includes the hours component, even at zero', () => {
    expect(formatOffset(754)).toBe('0:12:34');
  });
  it('formats offsets past an hour', () => {
    expect(formatOffset(4520)).toBe('1:15:20');
  });
  it('returns null for a null/undefined offset', () => {
    expect(formatOffset(null)).toBeNull();
    expect(formatOffset(undefined)).toBeNull();
  });
});

describe('formatClock', () => {
  it('formats sub-hour durations as m:ss with no hours component', () => {
    expect(formatClock(90)).toBe('1:30');
    expect(formatClock(65)).toBe('1:05');
  });
  it('formats durations at/past an hour as h:mm:ss', () => {
    expect(formatClock(3665)).toBe('1:01:05');
  });
  it('returns null for a null/undefined duration', () => {
    expect(formatClock(null)).toBeNull();
    expect(formatClock(undefined)).toBeNull();
  });
});

describe('formatLengthsSummary', () => {
  it('returns null for zero/null/undefined length counts', () => {
    expect(formatLengthsSummary(0)).toBeNull();
    expect(formatLengthsSummary(null)).toBeNull();
    expect(formatLengthsSummary(undefined)).toBeNull();
  });
  it('uses singular "length" for a count of 1', () => {
    expect(formatLengthsSummary(1)).toBe('1 length logged');
  });
  it('pluralizes for counts other than 1', () => {
    expect(formatLengthsSummary(71)).toBe('71 lengths logged');
  });
});
