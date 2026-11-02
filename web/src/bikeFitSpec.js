// Static description of the bike-geometry measurement scheme: the point definitions (verbatim),
// the twelve tape measures, and the bike-type defaults. Pure data, no DOM, so the form works
// offline. The numbers in WIDTH_DEFAULTS_MM mirror engine/swim_coach/bike_fit.py (a test checks
// both); they are ASSUMPTIONS, shown and editable. Nothing here is a fit target.

export const POINT_DEFINITIONS = {
  BB: 'center of the left crank bolt, at its outer face',
  FA: 'center of the left front axle end, at its outer face',
  RA: 'center of the left rear axle end, at its outer face',
  BC: "bar clamp, center of where the stem clamps the bar, on the bike's centerline",
  ST: 'saddle tip, on the centerline',
  H_drop_bar: 'midpoint of a string stretched between the top centers of the left and right hoods, where the palms sit',
  H_mtb: 'midpoint of a string stretched between the centers of the left and right grips, where the palms sit',
};

export const POINT_NAMES = {
  BB: 'Bottom bracket',
  FA: 'Front axle',
  RA: 'Rear axle',
  BC: 'Bar clamp',
  ST: 'Saddle tip',
  H: 'Hand point',
};

export function pointDefinition(point, bikeType) {
  if (point === 'H') return bikeType === 'mtb' ? POINT_DEFINITIONS.H_mtb : POINT_DEFINITIONS.H_drop_bar;
  return POINT_DEFINITIONS[point] || '';
}

export const BIKE_TYPES = [
  { value: 'drop_bar', label: 'Drop bar (road, CX, gravel)' },
  { value: 'mtb', label: 'Full-suspension MTB' },
];

// n is the athlete's own numbering of the tape measures. `floor_*` are floor-to-axle heights:
// only their difference is used, to correct for unequal wheel radius. `check` tapes (RA-FA, FA-H,
// RA-BC, BC-H) are compared with the solved geometry, not used to build it.
export const TAPE_FIELDS = [
  { key: 'bb_fa', n: 1, label: 'BB to FA', from: 'BB', to: 'FA', group: 'Triangle one' },
  { key: 'bb_bc', n: 2, label: 'BB to BC', from: 'BB', to: 'BC', group: 'Triangle one' },
  { key: 'fa_bc', n: 3, label: 'FA to BC', from: 'FA', to: 'BC', group: 'Triangle one' },
  { key: 'bb_st', n: 4, label: 'BB to ST', from: 'BB', to: 'ST', group: 'Triangle two' },
  { key: 'bc_st', n: 5, label: 'BC to ST', from: 'BC', to: 'ST', group: 'Triangle two' },
  { key: 'ra_bb', n: 6, label: 'RA to BB', from: 'RA', to: 'BB', group: 'Triangle three' },
  { key: 'ra_st', n: 7, label: 'RA to ST', from: 'RA', to: 'ST', group: 'Triangle three' },
  { key: 'bb_h', n: 8, label: 'BB to H', from: 'BB', to: 'H', group: 'Hand point (string midpoint)' },
  { key: 'st_h', n: 9, label: 'ST to H', from: 'ST', to: 'H', group: 'Hand point (string midpoint)' },
  { key: 'bc_h', n: 13, label: 'BC to H (bar clamp center to string midpoint)', from: 'BC', to: 'H', check: true, group: 'Hand point (string midpoint)' },
  { key: 'ra_fa', n: 10, label: 'RA to FA (wheelbase)', from: 'RA', to: 'FA', check: true, group: 'Closure checks' },
  { key: 'fa_h', n: 14, label: 'FA to H', from: 'FA', to: 'H', check: true, group: 'Closure checks' },
  { key: 'ra_bc', n: 15, label: 'RA to BC', from: 'RA', to: 'BC', check: true, group: 'Closure checks' },
  { key: 'floor_fa', n: 11, label: 'Floor to FA axle center', from: 'FA', to: null, floor: true, group: 'Wheel radius correction' },
  { key: 'floor_ra', n: 12, label: 'Floor to RA axle center', from: 'RA', to: null, floor: true, group: 'Wheel radius correction' },
];

export const TAPE_KEYS = TAPE_FIELDS.map((f) => f.key);

// Widths measured end to end across the bike, mm; each lateral offset from the centerline is half.
// FALLBACK ASSUMPTIONS, used only when a width is left blank (and then flagged in the results).
export const WIDTH_DEFAULTS_MM = {
  drop_bar: { crank: 120, fa: 100, ra: 142 },
  mtb: { crank: 140, fa: 110, ra: 148 },
};

export const HOW_TO_MEASURE = [
  'Wheels pointing straight ahead.',
  'Tires at race pressure.',
  'Bike upright and still (in a stand or held against a wall).',
  'Unweighted (nobody on the bike) unless the field says seated.',
  'Tape straight and taut between the two points; read to the nearest millimetre.',
  'Measure on the bike’s left side wherever a point is off the centerline.',
];

export const HOW_TO_BY_FIELD = {
  saddle_tilt: 'Digital level or phone laid on a straightedge along the saddle top. Positive is nose up.',
  floor_tilt: 'Same device, same orientation, laid on the floor where the bike stands. It is subtracted from the saddle reading.',
  saddle_length: 'Tip to tail along the saddle, in millimetres.',
  crank_length: 'The number stamped on the crank arm.',
  string_length: 'The length of the string between the left and right contact points (hood tops or grip centers), measured straight.',
  crank_width: 'Outer face center of the left crank bolt to outer face center of the right crank bolt, straight across with a tape or caliper. Half of it is the BB bolt\u2019s distance from the centerline.',
  front_axle_width: 'Outer face of the left front axle end to outer face of the right, end to end, tape or caliper. Half of it is the front axle end\u2019s distance from the centerline.',
  rear_axle_width: 'Outer face of the left rear axle end to outer face of the right, end to end, tape or caliper. Half of it is the rear axle end\u2019s distance from the centerline.',
  seated_bb: 'Rider on the bike, helper reads. Floor to the center of the left crank bolt.',
  seated_bc: 'Rider on the bike, helper reads. Floor to the bar clamp center.',
};

export const H_STEPS = {
  drop_bar: [
    'Stretch a string between the top centers of the left and right hoods, where the palms sit.',
    'Pull it taut, then fold it in half to find the middle and stick a piece of tape there: that mark is H.',
    'Measure the string length (the contact width), then tape from each point to the mark: BB, ST, BC, FA.',
  ],
  mtb: [
    'Stretch a string between the centers of the left and right grips, where the palms sit.',
    'Pull it taut, then fold it in half to find the middle and stick a piece of tape there: that mark is H.',
    'Measure the string length (the contact width), then tape from each point to the mark: BB, ST, BC, FA.',
  ],
};

export const H_NOTE = 'H is the tape mark at the middle of the string, on the bike\u2019s centerline.';

export const STATEMENT = 'This records geometry and doesn’t recommend changes. It gives no target angles and is not medical advice: take changes and any pain to your fitter.';

export const MTB_UNWEIGHTED_NOTE = 'An MTB with only unweighted results: rear sag normally rotates the frame back, so unweighted numbers may understate how upright the bike is actually ridden. Add the seated readings (a helper is needed) to see the bike under load.';
