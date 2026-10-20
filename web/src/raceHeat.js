// Colour and bucket constants for the race view's graphics (map strokes, bars, swatches). Text never
// uses these: text colours come from the theme tokens. Everything here is Coach judgment (a readable
// cool-to-hot ramp for a phone in daylight), except where a comment says otherwise.

/** Heat ramp, cool to hot. */
export const HEAT = ['#24619A', '#2E93AD', '#B07C0A', '#D45A15', '#C42B25'];
export const NEUTRAL = '#A3B0B5';
export const PAR = '#8E9EA4';

/** Race-view map tiers: blue, amber, orange, red. */
export const TIER_COLOURS = [HEAT[0], HEAT[2], HEAT[3], HEAT[4]];

/** Tier cut points per map metric (three cuts = four tiers). */
export const MAP_METRICS = {
  loss: { cuts: [0.45, 0.7, 1.0] },
  spread: { cuts: [1.0, 1.6, 2.5] },
  eff: { cuts: [10, 20, 30] },
};

/** Drill-down bucket edges: a value at or above an edge moves up a bucket. */
export const TIME_LOST_CUTS = [0.1, 0.25, 0.5, 1];
export const POWER_CUTS = [100, 200, 300, 450];
export const FLOW_CUTS = [0.5, 3, 6, 10];

/** Efficiency classes of one piece of a pass, in legend order. */
export const EFF_CLASSES = ['free', 'bought', 'par', 'saved', 'lost'];
export const EFF_COLOURS = { free: HEAT[0], bought: HEAT[1], par: PAR, saved: HEAT[2], lost: HEAT[4] };

/** A section this long or longer offers a split (a section hiding its loss in one stretch). */
export const SPLIT_MIN_M = 400;
export const SPLIT_PARTS = 3;

/** Index of the bucket `value` falls in: how many cut points it has reached. */
export function bucketOf(value, cuts) {
  let b = 0;
  while (b < cuts.length && value >= cuts[b]) b += 1;
  return b;
}
