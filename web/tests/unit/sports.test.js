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
//
// Two different KINDS of test below, deliberately not mixed in one
// describe block (Andrew, 2026-09-12, on why canPushToGarmin's exact-value
// test felt brittle after he changed it and CI still failed): a swim_ow
// registry-value edit was missed even though the corresponding test line
// WAS updated correctly -- two files disagreeing, and nothing in either
// file said why the values should be what they are.
//
// "structural invariants" -- properties that must hold no matter what the
// actual per-sport VALUES are (every sport present, every color distinct,
// unknown-sport safety). These should almost never need touching -- if one
// does, something is probably actually broken, not just a fact changing.
//
// "pinned facts" -- specific values tied to a real, external, CITED reason
// (a known bug, a backend mapping) that genuinely can and does change
// over time. These SHOULD be hardcoded (that's the whole point -- the test
// exists to catch an accidental value change), but the reason belongs in
// exactly ONE place -- sports.js's own comment on the field, not repeated
// here -- so updating a fact means reading one explanation, then updating
// two files in lockstep, not reverse-engineering "why was this true"
// separately in each one.
describe('SPORTS registry -- structural invariants (should rarely change)', () => {
  it('covers every backend Sport literal (engine/swim_coach/models.py)', () => {
    for (const sport of ['swim_pool', 'swim_ow', 'strength', 'recovery', 'cross_train', 'bike']) {
      expect(SPORTS[sport]).toBeTruthy();
    }
  });

  it('gives every real sport a distinct color var -- no silent fallthrough to the unknown-sport color', () => {
    const vars = Object.keys(SPORTS).map((s) => sportColorVar(s));
    expect(vars.every(Boolean)).toBe(true);
    expect(new Set(vars).size).toBe(vars.length);
  });

  it('an unknown sport degrades gracefully everywhere rather than throwing', () => {
    expect(sportInfo('kayak')).toBe(null);
    expect(sportColorVar('kayak')).toBe(null);
    expect(sportHasPlannedDistance('kayak')).toBe(false);
    expect(sportCanPushToGarmin('kayak')).toBe(false);
  });
});

describe('SPORTS registry -- pinned facts (expected to change; see sports.js for why)', () => {
  it('only swim sports carry a real planned-session distance target', () => {
    expect(sportHasPlannedDistance('swim_pool')).toBe(true);
    expect(sportHasPlannedDistance('swim_ow')).toBe(true);
    for (const sport of ['bike', 'strength', 'recovery', 'cross_train']) {
      expect(sportHasPlannedDistance(sport)).toBe(false);
    }
  });

  // NOT "matches the backend mapping" (it deliberately doesn't --
  // backend/app/routes/garmin.py's _SESSION_SPORT_TO_GARMIN_SPORT still
  // technically allows swim/strength; this registry says "don't offer it"
  // ahead of that real, still-open FIT-export corruption bug being fixed
  // -- see sports.js's own header comment for the citation). When that
  // bug is actually fixed and re-verified for a sport, flip BOTH this
  // assertion AND the matching value in sports.js in the same change --
  // that's the fix for the friction that motivated this restructuring,
  // not "stop pinning exact values" (that would just remove the regression
  // guard entirely).
  it('Garmin push is disabled for the sports with a known, still-open FIT-export corruption bug', () => {
    expect(sportCanPushToGarmin('swim_pool')).toBe(false);
    expect(sportCanPushToGarmin('swim_ow')).toBe(false);
    expect(sportCanPushToGarmin('strength')).toBe(false);
    expect(sportCanPushToGarmin('bike')).toBe(true);
    expect(sportCanPushToGarmin('recovery')).toBe(false);
    expect(sportCanPushToGarmin('cross_train')).toBe(false);
  });
});
