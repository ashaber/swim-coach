// Static description of the bike-geometry measurement scheme: the point definitions (verbatim),
// the twelve tape measures, and the bike-type defaults. Pure data, no DOM, so the form works
// offline. The numbers in LATERAL_DEFAULTS_MM mirror engine/swim_coach/bike_fit.py (a test checks
// both); they are ASSUMPTIONS, shown and editable. Nothing here is a fit target.

export const POINT_DEFINITIONS = {
  BB: 'center of the left crank bolt',
  FA: 'center of the left front axle end',
  RA: 'center of the left rear axle end',
  BC: "bar clamp, center of where the stem clamps the bar, on the bike's centerline",
  ST: 'saddle tip, on the centerline',
  H_drop_bar: 'top center of the left hood',
  H_mtb: 'center of the left grip',
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
// only their difference is used, to correct for unequal wheel radius.
export const TAPE_FIELDS = [
  { key: 'bb_fa', n: 1, label: 'BB to FA', from: 'BB', to: 'FA', group: 'Triangle one' },
  { key: 'bb_bc', n: 2, label: 'BB to BC', from: 'BB', to: 'BC', group: 'Triangle one' },
  { key: 'fa_bc', n: 3, label: 'FA to BC', from: 'FA', to: 'BC', group: 'Triangle one' },
  { key: 'bb_st', n: 4, label: 'BB to ST', from: 'BB', to: 'ST', group: 'Triangle two' },
  { key: 'bc_st', n: 5, label: 'BC to ST', from: 'BC', to: 'ST', group: 'Triangle two' },
  { key: 'ra_bb', n: 6, label: 'RA to BB', from: 'RA', to: 'BB', group: 'Triangle three' },
  { key: 'ra_st', n: 7, label: 'RA to ST', from: 'RA', to: 'ST', group: 'Triangle three' },
  { key: 'bb_h', n: 8, label: 'BB to H', from: 'BB', to: 'H', group: 'Hand point' },
  { key: 'st_h', n: 9, label: 'ST to H', from: 'ST', to: 'H', group: 'Hand point' },
  { key: 'ra_fa', n: 10, label: 'RA to FA (wheelbase)', from: 'RA', to: 'FA', group: 'Closure check' },
  { key: 'floor_fa', n: 11, label: 'Floor to FA axle center', from: 'FA', to: null, floor: true, group: 'Wheel radius correction' },
  { key: 'floor_ra', n: 12, label: 'Floor to RA axle center', from: 'RA', to: null, floor: true, group: 'Wheel radius correction' },
];

export const TAPE_KEYS = TAPE_FIELDS.map((f) => f.key);

// Lateral offsets from the bike's centerline, mm. ASSUMPTIONS, editable.
export const LATERAL_DEFAULTS_MM = {
  drop_bar: { bb: 60, fa: 50, ra: 71 },
  mtb: { bb: 70, fa: 55, ra: 74 },
};

export const LATERAL_NOTE = {
  drop_bar: 'Axle ends at half the hub width (front 100, rear 142 mm); crank bolt is a labelled default.',
  mtb: 'Axle ends at half the Boost hub width (front 110, rear 148 mm); crank bolt is a labelled default.',
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
  bar_width: 'Grip or hood centre to centre. The hand point sits half this far from the centerline.',
  seated_bb: 'Rider on the bike, helper reads. Floor to the center of the left crank bolt.',
  seated_bc: 'Rider on the bike, helper reads. Floor to the bar clamp center.',
};

export const STATEMENT = 'This records geometry and doesn’t recommend changes. It gives no target angles and is not medical advice: take changes and any pain to your fitter.';

export const MTB_UNWEIGHTED_NOTE = 'An MTB with only unweighted results: rear sag normally rotates the frame back, so unweighted numbers may understate how upright the bike is actually ridden. Add the seated readings (a helper is needed) to see the bike under load.';
