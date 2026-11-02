// Static description of the bike-geometry measurement scheme: the point definitions (verbatim),
// the tape measures, and the bike-type defaults. Pure data, no DOM, so the form works
// offline. The numbers in WIDTH_DEFAULTS_MM mirror engine/swim_coach/bike_fit.py (a test checks
// both); they are ASSUMPTIONS, shown and editable. Nothing here is a fit target.

export const POINT_DEFINITIONS = {
  BB: 'center of the left crank bolt, at its outer face',
  FA: 'center of the left front axle end, at its outer face',
  RA: 'center of the left rear axle end, at its outer face',
  BC: "bar clamp, center of where the stem clamps the bar, on the bike's centerline",
  ST: 'saddle tip, on the centerline',
  S: 'sit-bone point: the tape mark on the saddle\u2019s top centerline, at the entered distance from the tip. No standard exists for this location, so use your fitter\u2019s and keep it the same on every bike',
  H_drop_bar: 'midpoint of a string stretched between the top centers of the left and right hoods, where the palms sit',
  H_mtb: 'midpoint of a string stretched between the centers of the left and right grips, where the palms sit',
};

export const POINT_NAMES = {
  BB: 'Bottom bracket',
  FA: 'Front axle',
  RA: 'Rear axle',
  BC: 'Bar clamp',
  ST: 'Saddle tip',
  S: 'Sit-bone point',
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
// only their difference is used, to correct for unequal wheel radius. `check` tapes (BC-H, RA-FA, FA-H,
// RA-BC, RA-S) are compared with the solved geometry, not used to build it. BB-S and BC-S place the
// sit-bone point S on the saddle centerline.
export const TAPE_FIELDS = [
  { key: 'bb_fa', n: 1, label: 'BB to FA', from: 'BB', to: 'FA', group: 'Triangle one' },
  { key: 'bb_bc', n: 2, label: 'BB to BC', from: 'BB', to: 'BC', group: 'Triangle one' },
  { key: 'fa_bc', n: 3, label: 'FA to BC', from: 'FA', to: 'BC', group: 'Triangle one' },
  { key: 'bb_st', n: 4, label: 'BB to ST', from: 'BB', to: 'ST', group: 'Triangle two' },
  { key: 'bc_st', n: 5, label: 'BC to ST', from: 'BC', to: 'ST', group: 'Triangle two' },
  { key: 'bb_s', n: 6, label: 'BB to S (sit-bone mark)', from: 'BB', to: 'S', group: 'Sit-bone point S (saddle centerline)' },
  { key: 'bc_s', n: 7, label: 'BC to S (sit-bone mark)', from: 'BC', to: 'S', group: 'Sit-bone point S (saddle centerline)' },
  { key: 'ra_bb', n: 8, label: 'RA to BB', from: 'RA', to: 'BB', group: 'Triangle three' },
  { key: 'ra_st', n: 9, label: 'RA to ST', from: 'RA', to: 'ST', group: 'Triangle three' },
  { key: 'bb_h', n: 10, label: 'BB to H', from: 'BB', to: 'H', group: 'Hand point (string midpoint)' },
  { key: 'st_h', n: 11, label: 'ST to H', from: 'ST', to: 'H', group: 'Hand point (string midpoint)' },
  { key: 'bc_h', n: 12, label: 'BC to H (bar clamp center to string midpoint)', from: 'BC', to: 'H', check: true, group: 'Hand point (string midpoint)' },
  { key: 'ra_fa', n: 13, label: 'RA to FA (wheelbase)', from: 'RA', to: 'FA', check: true, group: 'Closure checks' },
  { key: 'fa_h', n: 14, label: 'FA to H', from: 'FA', to: 'H', check: true, group: 'Closure checks' },
  { key: 'ra_bc', n: 15, label: 'RA to BC', from: 'RA', to: 'BC', check: true, group: 'Closure checks' },
  { key: 'ra_s', n: 16, label: 'RA to S (sit-bone mark)', from: 'RA', to: 'S', check: true, group: 'Closure checks' },
  { key: 'floor_fa', n: 17, label: 'Floor to FA axle center', from: 'FA', to: null, floor: true, group: 'Wheel radius correction' },
  { key: 'floor_ra', n: 18, label: 'Floor to RA axle center', from: 'RA', to: null, floor: true, group: 'Wheel radius correction' },
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
  saddle_tilt: 'Lay a straightedge along the saddle top from tip to tail and put a digital level on the straightedge. The saddle top is concave, so a level sitting directly on it is unreliable. Positive is nose up.',
  floor_tilt: 'Same device, same orientation, laid on the floor where the bike stands. It is subtracted from the saddle reading.',
  saddle_length: 'Tip to tail along the saddle, in millimetres. Recorded only.',
  sit_point: 'Mark the saddle\u2019s top centerline with a bit of tape at this distance from the tip, along the saddle top. Use the same mark distance on both bikes if they have the same saddle. No standard exists for this location, so use your fitter\u2019s (ask them) or keep it consistent.',
  saddle_model: 'Make and model, as printed on the saddle.',
  saddle_rail: 'Where the rails sit in the clamp, in your own words. Recorded only: sit-point setback, not rail position, is what compares bikes, because seat tube angle differs.',
  frame_stack: 'The maker\u2019s frame stack (head tube top). Recorded only: this tool does not measure it.',
  frame_reach: 'The maker\u2019s frame reach (head tube top). Recorded only: this tool does not measure it.',
  pedal_stack: 'Pedal axle center to the shoe sole with the shoe clipped in. Hard to measure and accuracy is limited. The same shoes on both bikes cancel out, so only the pedal difference matters. Leave blank if unsure.',
  pedal_stack_source: 'Where the pedal stack figure came from.',
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

export const TILT_ADVISORY_DEG = 4;
export const TILT_NOTE = `Tilt beyond \u00b1${TILT_ADVISORY_DEG}\u00b0: check the measurement. Not a target: it does not block saving or change any result.`;

export const SIT_POINT_NOTE = 'No standard exists for the sit-bone location: use your fitter\u2019s, or keep it consistent. The same saddle on both bikes makes the comparison cleaner.';

export const H_NOTE = 'H is the tape mark at the middle of the string, on the bike\u2019s centerline.';

export const STATEMENT = 'This records geometry and doesn’t recommend changes. It gives no target angles and is not medical advice: take changes and any pain to your fitter.';

export const MTB_UNWEIGHTED_NOTE = 'An MTB with only unweighted results: rear sag normally rotates the frame back, so unweighted numbers may understate how upright the bike is actually ridden. Add the seated readings (a helper is needed) to see the bike under load.';
