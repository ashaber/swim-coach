// The one source of truth for per-sport display/behavior facts -- pure
// data, no DOM (same convention plan.js/workouts.js already follow: see
// workouts.js's own header comment).
//
// Before this module existed, sport-conditional logic was scattered as
// ad-hoc string-literal checks and three separate small maps across
// views.js/plan.js/workouts.js -- and it had already drifted: plan.js's
// dot-color map was never updated when "bike" was added (engine/cycling-
// coach), so every bike session's plan-tab dot silently fell through to
// the generic unknown-sport gray, indistinguishable from truly bad data.
// Andrew's own framing (2026-09-12): before adding run/ruck later, put
// every sport's display facts in one place a new entry can't be partially
// forgotten from.
//
// Keyed by the backend's actual `Sport` literal (engine/swim_coach/
// models.py) -- this describes what the backend already defines, it isn't
// a place to invent new sports client-side. Run/ruck have no backend
// `Sport` value yet (IDEA 008) -- deliberately NOT stubbed here; adding a
// real entry once they exist is a ~6-line addition, not a design change.
export const SPORTS = {
  swim_pool: {
    label: 'Pool swim',
    category: 'swim',
    // A planned pool/OW session's distance_m is a real athlete-facing
    // target (the whole point of the session) -- distinct from a LOGGED
    // workout's distance_m, which is real measured telemetry for ANY
    // sport with GPS and is never gated by this flag (see
    // workouts.js's formatWorkoutDistance, a deliberately separate case).
    hasPlannedDistance: true,
    hasSportDetail: false,
    colorVar: '--c-pool',
    // Mirrors backend/app/routes/garmin.py's _SESSION_SPORT_TO_GARMIN_SPORT
    // -- which sports a planned Session can push to a Garmin device today.
    // APS: turned to false as the data corrupts for swim
    canPushToGarmin: false,
  },
  swim_ow: {
    label: 'Open water swim',
    category: 'swim',
    hasPlannedDistance: true,
    hasSportDetail: false,
    colorVar: '--c-ow',
    canPushToGarmin: true,
  },
  bike: {
    label: 'Bike',
    category: 'bike',
    // A planned bike session's distance_m is a nominal/synthetic figure
    // the engine sets for schema completeness only (e.g. plan.py's
    // _skills_sessions) -- duration is the real target. See defect-round
    // (2026-09-12): "In UI, distance in meters should be duration, km or
    // miles."
    hasPlannedDistance: false,
    // Real cycling FIT activities carry a sub_sport (road/mountain/
    // gravel/cyclocross) worth showing as a suffix -- same convention
    // cross_train's own sport_detail already used before the
    // engine/cycling-coach reclassification split cycling out of it.
    hasSportDetail: true,
    colorVar: '--c-bike',
    canPushToGarmin: true,
  },
  strength: {
    label: 'Strength',
    category: 'strength',
    hasPlannedDistance: false,
    hasSportDetail: false,
    colorVar: '--c-strength',
    // APS - turned to false as strength workouts corrupt going to Garmin
    canPushToGarmin: false,
  },
  recovery: {
    label: 'Recovery',
    category: 'recovery',
    hasPlannedDistance: false,
    hasSportDetail: false,
    colorVar: '--c-recovery',
    // No recovery-specific Garmin structured-workout export exists.
    canPushToGarmin: false,
  },
  cross_train: {
    label: 'Cross-train',
    category: 'cross_train',
    hasPlannedDistance: false,
    hasSportDetail: true,
    colorVar: '--c-cross-train',
    // cross_train is a synced-FROM-Garmin catch-all bucket, never
    // planned/authored content -- there's nothing to push.
    canPushToGarmin: false,
  },
};

/** This sport's full registry entry, or `null` for anything not in
 * `SPORTS` (an unrecognized/legacy value -- every accessor below degrades
 * gracefully off this same `null`, never throws). */
export function sportInfo(sport) {
  return SPORTS[sport] || null;
}

export function sportColorVar(sport) {
  return SPORTS[sport]?.colorVar ?? null;
}

export function sportHasPlannedDistance(sport) {
  return SPORTS[sport]?.hasPlannedDistance ?? false;
}

export function sportHasDetail(sport) {
  return SPORTS[sport]?.hasSportDetail ?? false;
}

export function sportCanPushToGarmin(sport) {
  return SPORTS[sport]?.canPushToGarmin ?? false;
}
