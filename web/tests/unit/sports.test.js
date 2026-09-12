import { describe, it, expect } from 'vitest';
import {
  SPORTS, sportInfo, sportColorVar, sportHasPlannedDistance, sportCanPushToGarmin,
} from '../../src/sports.js';

// Sept 12 defect-round follow-up: sport-conditional logic (distance
// display, dot color, Garmin-push eligibility, sport_detail suffix) was
// scattered as ad-hoc string-literal checks and three separate small maps
// across views.js/plan.js/workouts.js -- one of them (plan.js's dot-color
// map) had never been updated for "bike" at all, silently falling through
// to the generic unknown-sport color. This module is the single source of
// truth those call sites now read from instead.

describe('SPORTS registry', () => {
  it('covers every backend Sport literal (engine/swim_coach/models.py)', () => {
    for (const sport of ['swim_pool', 'swim_ow', 'strength', 'recovery', 'cross_train', 'bike']) {
      expect(SPORTS[sport]).toBeTruthy();
    }
  });

  it('only swim sports carry a real planned-session distance target', () => {
    expect(sportHasPlannedDistance('swim_pool')).toBe(true);
    expect(sportHasPlannedDistance('swim_ow')).toBe(true);
    for (const sport of ['bike', 'strength', 'recovery', 'cross_train']) {
      expect(sportHasPlannedDistance(sport)).toBe(false);
    }
  });

  it('gives every real sport a distinct color var -- no silent fallthrough to the unknown-sport color', () => {
    const vars = Object.keys(SPORTS).map((s) => sportColorVar(s));
    expect(vars.every(Boolean)).toBe(true);
    expect(new Set(vars).size).toBe(vars.length);
  });

  it('Garmin push matches the real backend mapping (routes/garmin.py _SESSION_SPORT_TO_GARMIN_SPORT)', () => {
    expect(sportCanPushToGarmin('swim_pool')).toBe(true);
    expect(sportCanPushToGarmin('swim_ow')).toBe(true);
    expect(sportCanPushToGarmin('strength')).toBe(true);
    expect(sportCanPushToGarmin('bike')).toBe(true);
    expect(sportCanPushToGarmin('recovery')).toBe(false);
    expect(sportCanPushToGarmin('cross_train')).toBe(false);
  });

  it('an unknown sport degrades gracefully everywhere rather than throwing', () => {
    expect(sportInfo('kayak')).toBe(null);
    expect(sportColorVar('kayak')).toBe(null);
    expect(sportHasPlannedDistance('kayak')).toBe(false);
    expect(sportCanPushToGarmin('kayak')).toBe(false);
  });
});
