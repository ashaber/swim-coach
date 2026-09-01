import { describe, it, expect } from 'vitest';
import {
  isoWeekMonday, formatDuration, formatDistance, formatPace, splitPurpose,
  classifySession, sessionDisplay, deriveSessionTitle, findSessionById,
  pickCurrentAndNextWeek, sortedByIsoWeek, daysUntil,
  priorityEvent, macroTargetEvent, currentBlockIndex, longSwimLadder, sessionsByDay,
  parseStructureBlocks, parseMainSetIntervals, renderStructuredWorkout,
  splitStructuredRationale, sessionZoneDistribution, formatZoneDistributionSummary,
  stepCoachingCue, ZONE_GLOSSARY, TERM_GLOSSARY,
  ctlAtlTsbChartGeometry, RACE_DAY_TSB_BAND, PRODUCTIVE_TRAINING_TSB_BAND, raceWeekCategoryLabel,
  describeWellnessBaselineDeviation, WELLNESS_DEVIATION_CONCERNING_PCT,
  describeCtlAtlTsbTrend, CTL_COLD_START_DAYS, CTL_WARMED_UP_DAYS,
  CTL_ATL_TREND_WINDOW_DAYS, CTL_TREND_FLAT_THRESHOLD, LOAD_CHART_WINDOW_DAYS,
  LOAD_CHART_WINDOW_OPTIONS, TSB_AXIS_DOMAIN, TSB_PANEL_RATIO, classifyTsbBand,
  formatMonthLabel,
} from '../../src/plan.js';

describe('isoWeekMonday', () => {
  it('matches the known real data: 2026-W28 starts Monday Jul 6 2026', () => {
    const monday = isoWeekMonday('2026-W28');
    expect(monday.getFullYear()).toBe(2026);
    expect(monday.getMonth()).toBe(6); // 0-indexed: July
    expect(monday.getDate()).toBe(6);
    expect(monday.getDay()).toBe(1); // Monday
  });

  it('2026-W29 starts the following Monday, Jul 13', () => {
    const monday = isoWeekMonday('2026-W29');
    expect(monday.getDate()).toBe(13);
  });
});

describe('formatDuration', () => {
  it('formats sub-hour minutes plainly', () => {
    expect(formatDuration(40)).toBe('40 min');
  });
  it('formats whole hours', () => {
    expect(formatDuration(300)).toBe('5 h');
  });
  it('formats hours with remainder minutes', () => {
    expect(formatDuration(125)).toBe('2 h 5 min');
  });
});

describe('formatDistance', () => {
  it('adds thousands separators and a unit', () => {
    expect(formatDistance(15000)).toBe('15,000 m');
  });
  it('returns null for null input (no distance field)', () => {
    expect(formatDistance(null)).toBeNull();
  });
});

describe('formatPace', () => {
  it('formats seconds as m:ss', () => {
    expect(formatPace(90)).toBe('1:30');
    expect(formatPace(88)).toBe('1:28');
  });
  it('returns null for missing pace', () => {
    expect(formatPace(null)).toBeNull();
  });
});

describe('splitPurpose', () => {
  it('splits on the em dash convention', () => {
    const { title, detail } = splitPurpose('dryland shoulder strength — moderate (2 days before)');
    expect(title).toBe('dryland shoulder strength');
    expect(detail).toBe('moderate (2 days before)');
  });
  it('falls back to the whole string when there is no dash', () => {
    const { title, detail } = splitPurpose('full rest or gentle mobility');
    expect(title).toBe('full rest or gentle mobility');
    expect(detail).toBeNull();
  });
});

describe('classifySession', () => {
  it('flags an explicit (B race) marker', () => {
    const session = { purpose: 'Bear Lake Monster 10K (B race) — dress rehearsal', sport: 'swim_ow', duration_min: 180 };
    expect(classifySession(session)).toEqual({ highlight: true, tag: 'B Race' });
  });
  it('flags a long open-water swim as a milestone even without a race tag', () => {
    const session = { purpose: 'Lucky Peak 5-HOUR swim — fueling rehearsal', sport: 'swim_ow', duration_min: 300 };
    expect(classifySession(session)).toEqual({ highlight: true, tag: 'Milestone' });
  });
  it('does not flag an ordinary pool session', () => {
    const session = { purpose: 'coached USMS pool — content assigned by coach', sport: 'swim_pool', duration_min: 90 };
    expect(classifySession(session)).toEqual({ highlight: false, tag: null });
  });
});

describe('sessionDisplay', () => {
  it('strips the race-tag parenthetical out of the title', () => {
    const session = { purpose: 'Bear Lake Monster 10K (B race) — dress rehearsal, negative-split', structure: null };
    const { title, detail } = sessionDisplay(session);
    expect(title).toBe('Bear Lake Monster 10K');
    expect(detail).toBe('dress rehearsal, negative-split');
  });
  it('surfaces structure alongside the post-dash detail -- neither suppresses the other', () => {
    // Regression: sessionDisplay used to do `detail: detail || session.structure`,
    // so structure (the real authored warm-up/main-set/cool-down content) was
    // dead code any time purpose had its usual em-dash detail -- which is
    // effectively always. Both must now come back as distinct fields.
    const session = { purpose: 'Lucky Peak 5-HOUR swim — fueling rehearsal', structure: 'Feed every 20-30 min.' };
    const { detail, structure } = sessionDisplay(session);
    expect(detail).toBe('fueling rehearsal');
    expect(structure).toBe('Feed every 20-30 min.');
  });

  it('title falls back to the purpose-derived title when there is no structure', () => {
    const session = { purpose: 'Long open-water swim — build to event pace', structure: null };
    const { title, structure } = sessionDisplay(session);
    expect(title).toBe('Long open-water swim');
    expect(structure).toBeNull();
  });
});

describe('deriveSessionTitle', () => {
  it('derives the title from a swim session\'s "Main set:" line, cut at the first comma', () => {
    const session = {
      purpose: 'pool practice — no pool coach on hand, structure authored below',
      structure: 'Warm-up: 600m easy, building to Z2 pace (1:35-1:39/100m) by the end.\n'
        + 'Main set: 8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume...\n'
        + 'Cool-down: 200m easy choice of stroke.',
    };
    expect(deriveSessionTitle(session)).toBe('8 x 300m @ Z2 (1:35-1:39/100m)');
  });

  it('derives the title from a strength session\'s first line, cut at the first paren', () => {
    const session = {
      purpose: 'dryland shoulder strength — moderate (2 days before the 5-hour swim)',
      structure: 'Rotator-cuff / scapular-stability core (2 sets x 10 reps each):\n'
        + '  - Band external rotation\n'
        + '  - Prone Y-raise',
    };
    expect(deriveSessionTitle(session)).toBe('Rotator-cuff / scapular-stability core');
  });

  it('falls back to the existing splitPurpose-based title when there is no structure', () => {
    const session = { purpose: 'Bear Lake Monster 10K (B race) — dress rehearsal, negative-split', structure: null };
    expect(deriveSessionTitle(session)).toBe('Bear Lake Monster 10K');
  });

  it('does not crash on a "Main set:" line with unusual punctuation (no comma, no " -- ")', () => {
    const session = { purpose: 'pool practice — structure authored below', structure: 'Main set: 6 x 200m descend 1-6\nCool-down: 200m easy.' };
    expect(deriveSessionTitle(session)).toBe('6 x 200m descend 1-6');
  });

  it('does not crash on a bare strength-format first line with no "(" at all', () => {
    const session = { purpose: 'dryland strength — core work', structure: 'Core stability circuit\n  - plank x 3\n  - dead bug x 10' };
    expect(deriveSessionTitle(session)).toBe('Core stability circuit');
  });

  it('falls back to the purpose-derived title rather than a blank one when the structure first line starts with "("', () => {
    // Not producible by either real generator today (see the doc comment
    // above), but the format isn't guaranteed either -- a derived title that
    // slices to empty must never surface as a blank title in the UI.
    const session = { purpose: 'dryland strength — optional mobility flow', structure: '(optional) mobility flow\n  - hip circles' };
    expect(deriveSessionTitle(session)).toBe('Dryland strength');
  });

  it('falls back to the purpose-derived title for freeform prose with neither a "Main set:" line nor a bulleted list (real bug: was surfacing the warm-up line as the title)', () => {
    // A coach-authored `structure` override that doesn't follow the
    // "Main set:"/strength-bullet conventions (e.g. free-text authored
    // directly in a chat session) isn't a strength session -- it must not
    // fall into the strength-format first-line heuristic just because it
    // also has no "Main set:" line.
    const session = {
      purpose: 'open water sighting practice — building comfort spotting buoys in chop',
      structure: '600m easy warm-up, settling into rhythm.\n2400m steady at Z2, sighting every 6 strokes.\n300m easy cool-down.',
    };
    expect(deriveSessionTitle(session)).toBe('Open water sighting practice');
  });
});

describe('parseStructureBlocks', () => {
  it('splits the real swim-session format into Warm-up/Main set/Cool-down/Why blocks, in order', () => {
    const structure = 'Warm-up: 600m easy, building to Z2 pace (1:35-1:39/100m) by the end.\n'
      + 'Main set: 8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume (base-block emphasis).\n'
      + 'Cool-down: 200m easy choice of stroke.\n'
      + 'Why: continuous aerobic-volume emphasis (base-block phase).';
    const blocks = parseStructureBlocks(structure);
    expect(blocks.map((b) => b.label)).toEqual(['Warm-up', 'Main set', 'Cool-down', 'Why']);
    expect(blocks[0].content).toBe('600m easy, building to Z2 pace (1:35-1:39/100m) by the end.');
    expect(blocks[1].content).toBe(
      '8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume (base-block emphasis).'
    );
    expect(blocks[2].content).toBe('200m easy choice of stroke.');
    expect(blocks[3].content).toBe('continuous aerobic-volume emphasis (base-block phase).');
  });

  it('splits the real strength-session format into its two heading blocks + Why, preserving bullet indentation', () => {
    const structure = 'Rotator-cuff / scapular-stability core (2 sets x 10 reps each):\n'
      + '  - Band external rotation\n'
      + '  - Prone Y-raise\n'
      + 'General full-body (layered in as time allows):\n'
      + '  - Goblet squat\n'
      + 'Why: rotator-cuff strength/balance, reduces shoulder-injury risk (Hibberd 2012; Manske 2015; Tavares et al. 2025).';
    const blocks = parseStructureBlocks(structure);
    expect(blocks.map((b) => b.label)).toEqual([
      'Rotator-cuff / scapular-stability core (2 sets x 10 reps each)',
      'General full-body (layered in as time allows)',
      'Why',
    ]);
    expect(blocks[0].content).toBe('  - Band external rotation\n  - Prone Y-raise');
    expect(blocks[1].content).toBe('  - Goblet squat');
    expect(blocks[2].content).toBe(
      'rotator-cuff strength/balance, reduces shoulder-injury risk (Hibberd 2012; Manske 2015; Tavares et al. 2025).'
    );
  });

  it('splits a strength session with only the first (no odd-index full-body) block', () => {
    const structure = 'Rotator-cuff / scapular-stability core (2 sets x 10 reps each):\n'
      + '  - Band external rotation\n'
      + 'Why: rotator-cuff strength/balance, reduces shoulder-injury risk (Hibberd 2012; Manske 2015; Tavares et al. 2025).';
    const blocks = parseStructureBlocks(structure);
    expect(blocks.map((b) => b.label)).toEqual([
      'Rotator-cuff / scapular-stability core (2 sets x 10 reps each)',
      'Why',
    ]);
  });

  it('degrades gracefully to one block containing everything when no known label matches at all', () => {
    const structure = 'Some completely unstructured free text\nwith a second line\nand a third.';
    const blocks = parseStructureBlocks(structure);
    expect(blocks).toEqual([{ label: null, content: structure }]);
  });

  it('returns an empty array for null/empty structure', () => {
    expect(parseStructureBlocks(null)).toEqual([]);
    expect(parseStructureBlocks('')).toEqual([]);
  });
});

describe('parseMainSetIntervals', () => {
  it("today's real single-line Main-set content renders as exactly one interval", () => {
    const content = '8 x 300m @ Z2 (1:35-1:39/100m), 15s rest -- continuous aerobic volume (base-block emphasis).';
    expect(parseMainSetIntervals(content)).toEqual([content]);
  });

  it('a synthetic multi-line Main-set content (simulating a future multi-interval engine output) splits into multiple distinct interval items', () => {
    // Today's engine only ever emits one line here -- this proves the
    // forward-compatibility requirement: the moment a future engine change
    // emits 2+ distinct interval lines, this parsing already handles it.
    const content = '400m @ Z2 (1:35-1:39/100m) build\n'
      + '4 x 100m @ Z3 (1:20-1:24/100m), 20s rest\n'
      + '200m @ Z4 (1:08-1:12/100m) descend';
    expect(parseMainSetIntervals(content)).toEqual([
      '400m @ Z2 (1:35-1:39/100m) build',
      '4 x 100m @ Z3 (1:20-1:24/100m), 20s rest',
      '200m @ Z4 (1:08-1:12/100m) descend',
    ]);
  });

  it('filters out blank lines and trims each interval', () => {
    const content = '  first interval  \n\n  second interval\n';
    expect(parseMainSetIntervals(content)).toEqual(['first interval', 'second interval']);
  });

  it('returns an empty array for null/empty content', () => {
    expect(parseMainSetIntervals(null)).toEqual([]);
    expect(parseMainSetIntervals('')).toEqual([]);
  });
});

describe('renderStructuredWorkout', () => {
  // Synthetic `WorkoutStructure` fixtures matching PR #91's real model
  // shape (engine/swim_coach/models.py's WorkoutStep/WorkoutRepeat: `kind`
  // discriminator, `role`, `duration_kind`/`duration_value`, `target`/
  // `load`, `modality`, `stroke`, `equipment`, `exercise_name` for steps;
  // `repeat_mode`/`count`/`duration_s`/`interval_s`/`steps` for repeats) --
  // not raw JSON dumps of real generated content, since this function must
  // walk the tree generically regardless of which real template produced it.

  it('a plain step list (no repeats): warmup/rest/cooldown, one line each', () => {
    const structured = {
      items: [
        {
          kind: 'step', label: 'Easy swim', role: 'warmup', duration_kind: 'distance_m',
          duration_value: 400, target: { basis: 'zone', zone: 'Z2' }, load: null,
          modality: 'swim', stroke: null, equipment: [], exercise_name: null,
        },
        {
          kind: 'step', label: 'Rest', role: 'rest', duration_kind: 'time_s',
          duration_value: 15, target: null, load: null,
          modality: 'swim', stroke: null, equipment: [], exercise_name: null,
        },
        {
          kind: 'step', label: 'Cool down easy', role: 'cooldown', duration_kind: 'distance_m',
          duration_value: 200, target: null, load: null,
          modality: 'swim', stroke: null, equipment: [], exercise_name: null,
        },
      ],
    };
    expect(renderStructuredWorkout(structured)).toEqual([
      // Top-level warmup/cooldown: label is already the full narrated text
      // (real generated content bakes distance AND target into it -- see
      // structuredStepDetail's doc comment), so detail is suppressed
      // entirely to avoid repeating it.
      { depth: 0, kind: 'step', text: 'Warm-up: Easy swim', detail: null },
      // "Rest 15s" -- exactly the plan's own illustrative example. `rest`
      // isn't a narrated role, so its short label needs this annotation.
      { depth: 0, kind: 'step', text: 'Rest', detail: '15s' },
      { depth: 0, kind: 'step', text: 'Cool-down: Cool down easy', detail: null },
    ]);
  });

  it('a count-based repeat: "2 x:" header, children indented one level with reps shown (bodyweight load suppressed)', () => {
    const structured = {
      items: [
        {
          kind: 'repeat', repeat_mode: 'count', count: 2, duration_s: null, interval_s: null,
          steps: [
            {
              kind: 'step', label: 'Band pull-apart', role: 'steady', duration_kind: 'reps',
              duration_value: 10, target: null, load: { basis: 'bodyweight', value: null },
              modality: 'strength', stroke: null, equipment: [], exercise_name: 'Band pull-apart',
            },
            {
              kind: 'step', label: 'Prone Y-raise', role: 'steady', duration_kind: 'reps',
              duration_value: 10, target: null, load: { basis: 'bodyweight', value: null },
              modality: 'strength', stroke: null, equipment: [], exercise_name: 'Prone Y-raise',
            },
          ],
        },
      ],
    };
    expect(renderStructuredWorkout(structured)).toEqual([
      { depth: 0, kind: 'repeat', text: '2 x:', detail: null },
      { depth: 1, kind: 'step', text: 'Band pull-apart', detail: '10 reps' },
      { depth: 1, kind: 'step', text: 'Prone Y-raise', detail: '10 reps' },
    ]);
  });

  it('a for_duration (EMOM-style) repeat derives its round count from duration_s/interval_s, e.g. "EMOM x10 (every 60s):"', () => {
    const structured = {
      items: [
        {
          kind: 'repeat', repeat_mode: 'for_duration', count: null, duration_s: 600, interval_s: 60,
          steps: [
            {
              kind: 'step', label: 'Kettlebell swing', role: 'steady', duration_kind: 'reps',
              duration_value: 15, target: null, load: { basis: 'percent_1rm', value: 40 },
              modality: 'strength', stroke: null, equipment: [], exercise_name: 'Kettlebell swing',
            },
          ],
        },
      ],
    };
    expect(renderStructuredWorkout(structured)).toEqual([
      { depth: 0, kind: 'repeat', text: 'EMOM x10 (every 60s):', detail: null },
      { depth: 1, kind: 'step', text: 'Kettlebell swing', detail: '15 reps · @ 40% 1RM' },
    ]);
  });

  it('an amrap repeat shows its total window as "AMRAP for {mm:ss}:"', () => {
    const structured = {
      items: [
        {
          kind: 'repeat', repeat_mode: 'amrap', count: null, duration_s: 720, interval_s: null,
          steps: [
            {
              kind: 'step', label: 'Burpee', role: 'steady', duration_kind: 'reps',
              duration_value: 10, target: null, load: { basis: 'bodyweight', value: null },
              modality: 'strength', stroke: null, equipment: [], exercise_name: 'Burpee',
            },
            {
              kind: 'step', label: 'Rest', role: 'rest', duration_kind: 'time_s',
              duration_value: 10, target: null, load: null,
              modality: 'strength', stroke: null, equipment: [], exercise_name: null,
            },
          ],
        },
      ],
    };
    expect(renderStructuredWorkout(structured)).toEqual([
      { depth: 0, kind: 'repeat', text: 'AMRAP for 12:00:', detail: null },
      { depth: 1, kind: 'step', text: 'Burpee', detail: '10 reps' },
      { depth: 1, kind: 'step', text: 'Rest', detail: '10s' },
    ]);
  });

  it('a nested (non-top-level) swim interval shows its own distance/target/stroke/equipment -- only top-level narrated steps suppress duration', () => {
    const structured = {
      items: [
        {
          kind: 'repeat', repeat_mode: 'count', count: 4, duration_s: null, interval_s: null,
          steps: [
            {
              kind: 'step', label: '100 build', role: 'interval', duration_kind: 'distance_m',
              duration_value: 100, target: { basis: 'percent_css', low: 130, high: 140 }, load: null,
              modality: 'swim', stroke: 'fly', equipment: ['paddles'], exercise_name: null,
            },
          ],
        },
      ],
    };
    expect(renderStructuredWorkout(structured)).toEqual([
      { depth: 0, kind: 'repeat', text: '4 x:', detail: null },
      { depth: 1, kind: 'step', text: '100 build', detail: '100m · @ 130-140% CSS · Fly · paddles' },
    ]);
  });

  it('an rpe-basis target with a number renders "RPE {n}", not the bare literal "RPE" (bug fix)', () => {
    const structured = {
      items: [
        {
          kind: 'step', label: 'Easy recovery swim', role: 'steady', duration_kind: 'distance_m',
          duration_value: 1000, target: { basis: 'rpe', low: 3, high: null }, load: null,
          modality: 'swim', stroke: null, equipment: [], exercise_name: null,
        },
      ],
    };
    expect(renderStructuredWorkout(structured)).toEqual([
      { depth: 0, kind: 'step', text: 'Easy recovery swim', detail: '1000m · @ RPE 3' },
    ]);
  });

  it('an rpe-basis target with a low/high range renders "RPE {low}-{high}"', () => {
    const structured = {
      items: [
        {
          kind: 'step', label: 'Steady swim', role: 'steady', duration_kind: 'distance_m',
          duration_value: 1000, target: { basis: 'rpe', low: 4, high: 6 }, load: null,
          modality: 'swim', stroke: null, equipment: [], exercise_name: null,
        },
      ],
    };
    const lines = renderStructuredWorkout(structured);
    expect(lines[0].detail).toBe('1000m · @ RPE 4-6');
  });

  it('an rpe-basis target with no number at all still falls back to the bare "RPE" label (still meaningful on its own)', () => {
    const structured = {
      items: [
        {
          kind: 'step', label: 'Easy recovery swim', role: 'steady', duration_kind: 'distance_m',
          duration_value: 1000, target: { basis: 'rpe', low: null, high: null }, load: null,
          modality: 'swim', stroke: null, equipment: [], exercise_name: null,
        },
      ],
    };
    const lines = renderStructuredWorkout(structured);
    expect(lines[0].detail).toBe('1000m · @ RPE');
  });

  it('returns [] for a missing/empty structured tree (regression: fallback callers must be able to rely on this)', () => {
    expect(renderStructuredWorkout(null)).toEqual([]);
    expect(renderStructuredWorkout(undefined)).toEqual([]);
    expect(renderStructuredWorkout({ items: [] })).toEqual([]);
  });

  it('threads a step\'s reference_url through as referenceUrl on its line, leaving it unset when absent', () => {
    const structured = {
      items: [
        {
          kind: 'step', label: 'Goblet squat', role: 'steady', duration_kind: 'reps',
          duration_value: 10, target: null, load: { basis: 'bodyweight', value: null },
          modality: 'strength', stroke: null, equipment: [], exercise_name: 'Goblet squat',
          reference_url: 'https://www.rehabhero.ca/exercise/goblet-squat',
        },
        {
          kind: 'step', label: 'Kettlebell swing', role: 'steady', duration_kind: 'reps',
          duration_value: 10, target: null, load: { basis: 'bodyweight', value: null },
          modality: 'strength', stroke: null, equipment: [], exercise_name: 'Kettlebell swing',
        },
      ],
    };
    const lines = renderStructuredWorkout(structured);
    expect(lines[0].referenceUrl).toBe('https://www.rehabhero.ca/exercise/goblet-squat');
    expect(lines[1].referenceUrl).toBeUndefined();
  });

  it('a repeat header never carries a referenceUrl, even when its child steps do', () => {
    const structured = {
      items: [
        {
          kind: 'repeat', repeat_mode: 'count', count: 2, duration_s: null, interval_s: null,
          steps: [
            {
              kind: 'step', label: 'Goblet squat', role: 'steady', duration_kind: 'reps',
              duration_value: 10, target: null, load: { basis: 'bodyweight', value: null },
              modality: 'strength', stroke: null, equipment: [], exercise_name: 'Goblet squat',
              reference_url: 'https://www.rehabhero.ca/exercise/goblet-squat',
            },
          ],
        },
      ],
    };
    const lines = renderStructuredWorkout(structured);
    expect(lines[0].kind).toBe('repeat');
    expect(lines[0].referenceUrl).toBeUndefined();
    expect(lines[1].referenceUrl).toBe('https://www.rehabhero.ca/exercise/goblet-squat');
  });
});

describe('stepCoachingCue', () => {
  it('returns null for a swim step whose label matches no known set-type vocabulary', () => {
    expect(stepCoachingCue({
      kind: 'step', label: '100 build', role: 'interval', modality: 'swim',
    })).toBeNull();
  });

  it('matches a real broken-distance main-set label (base-1-broken-distance-lite\'s real narrative)', () => {
    const cue = stepCoachingCue({
      kind: 'step', modality: 'swim',
      label: '6 x (200m + 200m) @ Z2 (1:35-1:39/100m), 10s rest between segments / 15s between reps -- broken-distance-lite aerobic volume, same total distance and pace as straight reps (base-block emphasis).',
    });
    expect(cue).toMatch(/broken-distance/i);
  });

  it('matches a real descend main-set label (build-0-descend\'s real narrative)', () => {
    const cue = stepCoachingCue({
      kind: 'step', modality: 'swim',
      label: '9 x 300m broken-distance, descend 1-9 from Z3 (1:32-1:34/100m) toward Z4 (1:29-1:31/100m) on the last rep, negative-split each repeat -- race-pace-adjacent emphasis (build block).',
    });
    // "descend"/"negative-split"/"broken-distance" are all present -- the
    // more specific "negative-split" pattern is checked before the generic
    // "descend" one, so that's the cue that wins here (first-match-wins).
    expect(cue).toMatch(/negative-split/i);
  });

  it('picks the pull-ladder-specific cue over the generic ladder cue for a real pull-ladder label', () => {
    const cue = stepCoachingCue({
      kind: 'step', modality: 'swim',
      label: 'descending-distance pull ladder -- 400/300/200/100 -- each rung negative-split from Z3 (1:32-1:34/100m) toward Z4 (1:29-1:31/100m) as the distance shrinks, 20s rest between rungs.',
    });
    expect(cue).toMatch(/Pull ladder/);
  });

  it('picks the kick-ladder-specific cue over the generic ladder cue for a real kick-ladder label', () => {
    const cue = stepCoachingCue({
      kind: 'step', modality: 'swim',
      label: 'descending-distance kick ladder -- 200/100/50/25 -- same sprint-character effort held on every rung.',
    });
    expect(cue).toMatch(/Kick ladder/);
  });

  it('matches an exact canonical strength exercise_name (plan.py\'s STRENGTH_CORE_EXERCISES)', () => {
    const cue = stepCoachingCue({
      kind: 'step', modality: 'strength', label: 'Internal rotation at 90° abduction',
      exercise_name: 'Internal rotation at 90° abduction',
    });
    expect(cue).toMatch(/rotate/i);
  });

  it('does NOT keyword-match a strength step\'s label against the swim vocabulary (e.g. "Band pull-apart" must not get the swim pull-set cue)', () => {
    expect(stepCoachingCue({
      kind: 'step', modality: 'strength', label: 'Band pull-apart', exercise_name: 'Band pull-apart',
    })).toBeNull();
  });

  it('returns null for a strength step whose exercise_name is not one of the canonical exercises', () => {
    expect(stepCoachingCue({
      kind: 'step', modality: 'strength', label: 'Kettlebell swing', exercise_name: 'Kettlebell swing',
    })).toBeNull();
  });

  it('returns null for a null/undefined step', () => {
    expect(stepCoachingCue(null)).toBeNull();
    expect(stepCoachingCue(undefined)).toBeNull();
  });
});

describe('renderStructuredWorkout: per-step coaching cue threaded onto matching lines', () => {
  it('attaches cue to a step whose label matches the vocabulary, leaves it unset on one that doesn\'t (regression: existing no-cue line shapes must stay exact)', () => {
    const structured = {
      items: [
        {
          kind: 'step', label: 'Easy swim', role: 'warmup', duration_kind: 'distance_m',
          duration_value: 400, target: { basis: 'zone', zone: 'Z2' }, load: null,
          modality: 'swim', stroke: null, equipment: [], exercise_name: null,
        },
        {
          kind: 'step', modality: 'swim', role: 'interval', duration_kind: 'distance_m', duration_value: 800,
          label: '4 x 200m broken-distance, descend 1-4 from Z3 toward Z4 -- race-pace-adjacent emphasis.',
          target: { basis: 'zone', zone: 'Z3' }, load: null, stroke: null, equipment: [], exercise_name: null,
        },
      ],
    };
    const lines = renderStructuredWorkout(structured);
    expect(lines[0].cue).toBeUndefined(); // "Easy swim" matches no vocabulary
    expect(lines[1].cue).toMatch(/descend/i);
  });

  it('a repeat header never carries a cue, even when its child steps do', () => {
    const structured = {
      items: [
        {
          kind: 'repeat', repeat_mode: 'count', count: 2, duration_s: null, interval_s: null,
          steps: [
            {
              kind: 'step', label: 'Internal rotation at 90° abduction', role: 'steady', duration_kind: 'reps',
              duration_value: 10, target: null, load: { basis: 'bodyweight', value: null },
              modality: 'strength', stroke: null, equipment: [], exercise_name: 'Internal rotation at 90° abduction',
            },
          ],
        },
      ],
    };
    const lines = renderStructuredWorkout(structured);
    expect(lines[0].kind).toBe('repeat');
    expect(lines[0].cue).toBeUndefined();
    expect(lines[1].cue).toMatch(/rotate/i);
  });
});

describe('splitStructuredRationale', () => {
  it('returns items unchanged and rationale null when there is no trailing Why step', () => {
    const structured = { items: [{ kind: 'step', label: 'Easy swim', role: 'warmup' }] };
    expect(splitStructuredRationale(structured)).toEqual({ items: structured.items, rationale: null });
  });

  it('strips a trailing top-level Why step and exposes its text with the "Why:" prefix removed (plan.py\'s real shape)', () => {
    const warmup = { kind: 'step', label: 'Easy swim', role: 'warmup' };
    const mainSet = { kind: 'step', label: '8 x 300m @ Z2', role: 'interval' };
    const why = {
      kind: 'step', role: 'open', duration_kind: 'open',
      label: 'Why: continuous aerobic-volume emphasis (base-block phase).',
    };
    const structured = { items: [warmup, mainSet, why] };
    const result = splitStructuredRationale(structured);
    expect(result.items).toEqual([warmup, mainSet]);
    expect(result.rationale).toBe('continuous aerobic-volume emphasis (base-block phase).');
  });

  it('leaves a "Why:"-labelled step in place when it is nested inside a repeat, not top-level', () => {
    const nestedWhy = { kind: 'step', role: 'open', label: 'Why: nested, not session rationale.' };
    const structured = {
      items: [{ kind: 'repeat', repeat_mode: 'count', count: 2, steps: [nestedWhy] }],
    };
    const result = splitStructuredRationale(structured);
    expect(result.items).toEqual(structured.items);
    expect(result.rationale).toBeNull();
  });

  it('does not match a role="open" step whose label merely contains "Why" without the leading "Why:" prefix', () => {
    const structured = { items: [{ kind: 'step', role: 'open', label: "Here's why this matters." }] };
    expect(splitStructuredRationale(structured)).toEqual({ items: structured.items, rationale: null });
  });

  it('returns { items: [], rationale: null } for a missing/empty structured tree', () => {
    expect(splitStructuredRationale(null)).toEqual({ items: [], rationale: null });
    expect(splitStructuredRationale(undefined)).toEqual({ items: [], rationale: null });
    expect(splitStructuredRationale({ items: [] })).toEqual({ items: [], rationale: null });
  });
});

describe('sessionZoneDistribution', () => {
  it('sums distance per zone across plain top-level steps, ordered Z1..Z5', () => {
    const structured = {
      items: [
        {
          kind: 'step', label: 'Easy swim', role: 'warmup', duration_kind: 'distance_m',
          duration_value: 400, target: { basis: 'zone', zone: 'Z2' }, modality: 'swim',
        },
        {
          kind: 'step', label: 'Main set', role: 'interval', duration_kind: 'distance_m',
          duration_value: 1500, target: { basis: 'zone', zone: 'Z3' }, modality: 'swim',
        },
        {
          kind: 'step', label: 'Cool down', role: 'cooldown', duration_kind: 'distance_m',
          duration_value: 200, target: { basis: 'zone', zone: 'Z2' }, modality: 'swim',
        },
      ],
    };
    expect(sessionZoneDistribution(structured)).toEqual([
      { bucket: 'Z2', distance_m: 600, duration_s: null },
      { bucket: 'Z3', distance_m: 1500, duration_s: null },
    ]);
  });

  it('a resolved (basis="absolute") step still buckets by its surviving zone tag (resolve_template never clears `zone`)', () => {
    const structured = {
      items: [
        {
          kind: 'step', label: 'Main set', role: 'interval', duration_kind: 'distance_m',
          duration_value: 900, target: { basis: 'absolute', zone: 'Z4', low: 89, high: 91 }, modality: 'swim',
        },
      ],
    };
    expect(sessionZoneDistribution(structured)).toEqual([
      { bucket: 'Z4', distance_m: 900, duration_s: null },
    ]);
  });

  it('buckets an untagged percent_css target as "% CSS", an rpe target as "RPE", and a targetless step as "Open"', () => {
    const structured = {
      items: [
        { kind: 'step', label: 'a', duration_kind: 'distance_m', duration_value: 100, target: { basis: 'percent_css', low: 135 }, modality: 'swim' },
        { kind: 'step', label: 'b', duration_kind: 'distance_m', duration_value: 200, target: { basis: 'rpe', low: 3 }, modality: 'swim' },
        { kind: 'step', label: 'c', duration_kind: 'distance_m', duration_value: 300, target: null, modality: 'swim' },
      ],
    };
    expect(sessionZoneDistribution(structured)).toEqual([
      { bucket: '% CSS', distance_m: 100, duration_s: null },
      { bucket: 'RPE', distance_m: 200, duration_s: null },
      { bucket: 'Open', distance_m: 300, duration_s: null },
    ]);
  });

  it('multiplies a count-based repeat\'s children by its count', () => {
    const structured = {
      items: [
        {
          kind: 'repeat', repeat_mode: 'count', count: 4, steps: [
            { kind: 'step', label: '100 build', duration_kind: 'distance_m', duration_value: 100, target: { basis: 'zone', zone: 'Z3' }, modality: 'swim' },
          ],
        },
      ],
    };
    expect(sessionZoneDistribution(structured)).toEqual([
      { bucket: 'Z3', distance_m: 400, duration_s: null },
    ]);
  });

  it('does not multiply a for_duration/amrap repeat\'s children (no well-defined repetition count)', () => {
    const structured = {
      items: [
        {
          kind: 'repeat', repeat_mode: 'amrap', duration_s: 600, steps: [
            { kind: 'step', label: 'Kettlebell swing', duration_kind: 'reps', duration_value: 15, target: null, modality: 'strength' },
          ],
        },
      ],
    };
    expect(sessionZoneDistribution(structured)).toEqual([]);
  });

  it('sums duration_s for time-based steps into minutes-ready seconds totals', () => {
    const structured = {
      items: [
        { kind: 'step', label: 'EMOM work', duration_kind: 'time_s', duration_value: 600, target: { basis: 'zone', zone: 'Z4' }, modality: 'swim' },
      ],
    };
    expect(sessionZoneDistribution(structured)).toEqual([
      { bucket: 'Z4', distance_m: null, duration_s: 600 },
    ]);
  });

  it('excludes strength (reps/load-based) steps entirely -- not a zone concept', () => {
    const structured = {
      items: [
        { kind: 'step', label: 'Goblet squat', duration_kind: 'reps', duration_value: 10, target: null, modality: 'strength' },
      ],
    };
    expect(sessionZoneDistribution(structured)).toEqual([]);
  });

  it('ignores a reps/open duration_kind step even for a swim-modality step (nothing to sum in either unit)', () => {
    const structured = {
      items: [
        { kind: 'step', label: 'Sighting practice', duration_kind: 'open', duration_value: null, target: { basis: 'zone', zone: 'Z2' }, modality: 'swim' },
      ],
    };
    expect(sessionZoneDistribution(structured)).toEqual([]);
  });

  it('returns [] for a missing/empty structured tree', () => {
    expect(sessionZoneDistribution(null)).toEqual([]);
    expect(sessionZoneDistribution(undefined)).toEqual([]);
    expect(sessionZoneDistribution({ items: [] })).toEqual([]);
  });
});

describe('formatZoneDistributionSummary', () => {
  it('formats the plan brief\'s own illustrative shape: "Z1: 10 min, Z2: 25 min, Z4: 8 min"', () => {
    const entries = [
      { bucket: 'Z1', distance_m: null, duration_s: 600 },
      { bucket: 'Z2', distance_m: null, duration_s: 1500 },
      { bucket: 'Z4', distance_m: null, duration_s: 480 },
    ];
    expect(formatZoneDistributionSummary(entries)).toBe('Z1: 10 min, Z2: 25 min, Z4: 8 min');
  });

  it('formats a distance-only entry with formatDistance\'s thousands separator', () => {
    expect(formatZoneDistributionSummary([{ bucket: 'Z2', distance_m: 1600, duration_s: null }]))
      .toBe('Z2: 1,600 m');
  });

  it('joins distance and time with " + " when a single bucket carries both', () => {
    expect(formatZoneDistributionSummary([{ bucket: 'Z3', distance_m: 300, duration_s: 120 }]))
      .toBe('Z3: 300 m + 2 min');
  });

  it('returns "" for no entries', () => {
    expect(formatZoneDistributionSummary([])).toBe('');
  });
});

describe('ZONE_GLOSSARY / TERM_GLOSSARY', () => {
  it('covers all five zones, in order, matching zones.py\'s real CSS-relative offsets', () => {
    expect(ZONE_GLOSSARY.map((z) => z.zone)).toEqual(['Z1', 'Z2', 'Z3', 'Z4', 'Z5']);
    expect(ZONE_GLOSSARY.every((z) => z.range && z.character)).toBe(true);
  });

  it('covers the abbreviations this app actually renders elsewhere (CSS, RPE, EMOM, AMRAP)', () => {
    const terms = TERM_GLOSSARY.map((t) => t.term);
    expect(terms).toEqual(expect.arrayContaining(['CSS', 'RPE', 'EMOM', 'AMRAP']));
  });
});

describe('findSessionById', () => {
  const weeks = [
    { iso_week: '2026-W28', sessions: [{ id: 's-1', purpose: 'a' }, { id: 's-2', purpose: 'b' }] },
    { iso_week: '2026-W29', sessions: [{ id: 's-3', purpose: 'c' }] },
  ];

  it('finds a session by id across every week', () => {
    expect(findSessionById(weeks, 's-3').purpose).toBe('c');
  });

  it('returns null when no session matches', () => {
    expect(findSessionById(weeks, 'nonexistent')).toBeNull();
  });

  it('returns null for a null/empty id', () => {
    expect(findSessionById(weeks, null)).toBeNull();
  });
});

describe('pickCurrentAndNextWeek', () => {
  const weeks = [
    { iso_week: '2026-W28', sessions: [] },
    { iso_week: '2026-W29', sessions: [] },
  ];

  it('picks W28 as current when now is mid-week-27 (before W28 starts)', () => {
    const { current, next, stale } = pickCurrentAndNextWeek(weeks, new Date(2026, 6, 5));
    expect(current.iso_week).toBe('2026-W28');
    expect(next.iso_week).toBe('2026-W29');
    expect(stale).toBe(false);
  });

  it('picks W29 as current once W28 has fully elapsed', () => {
    const { current, next, stale } = pickCurrentAndNextWeek(weeks, new Date(2026, 6, 15));
    expect(current.iso_week).toBe('2026-W29');
    expect(next).toBeNull();
    expect(stale).toBe(false);
  });

  it('returns nulls for an empty week list', () => {
    expect(pickCurrentAndNextWeek([])).toEqual({ current: null, next: null, stale: false });
  });

  // The live defect (2026-08-18): the athlete's plan stopped at 2026-W29
  // while the wall clock was in W34, and the Plan tab happily showed W29 as
  // "This week". A stale week presented as the current one is worse than
  // showing nothing -- it silently hides that no plan exists, so the athlete
  // trains off a five-week-old prescription. Report the gap instead.
  it('reports stale (no current/next) when every week has already elapsed', () => {
    const result = pickCurrentAndNextWeek(weeks, new Date(2026, 7, 18));
    expect(result).toEqual({ current: null, next: null, stale: true });
  });

  it('treats the final week as current right up to its own Sunday, not stale', () => {
    // 2026-W29 runs Mon Jul 13 .. Sun Jul 19; Sunday itself is still "this week".
    const { current, stale } = pickCurrentAndNextWeek(weeks, new Date(2026, 6, 19));
    expect(current.iso_week).toBe('2026-W29');
    expect(stale).toBe(false);
  });
});

describe('sortedByIsoWeek', () => {
  it('orders weeks chronologically without mutating the input', () => {
    const weeks = [{ iso_week: '2026-W29' }, { iso_week: '2026-W02' }, { iso_week: '2025-W51' }];
    const sorted = sortedByIsoWeek(weeks);
    expect(sorted.map((w) => w.iso_week)).toEqual(['2025-W51', '2026-W02', '2026-W29']);
    expect(weeks[0].iso_week).toBe('2026-W29');
  });

  it('returns an empty array for a missing week list', () => {
    expect(sortedByIsoWeek(null)).toEqual([]);
  });
});

describe('daysUntil', () => {
  it('counts whole days to a future date', () => {
    const now = new Date(2026, 6, 5);
    const event = new Date(2026, 6, 15);
    expect(daysUntil(event, now)).toBe(10);
  });
  it('floors at 0 for a past date', () => {
    const now = new Date(2026, 6, 15);
    const event = new Date(2026, 6, 5);
    expect(daysUntil(event, now)).toBe(0);
  });
});

describe('priorityEvent', () => {
  it('prefers the A-priority event over others', () => {
    const events = [
      { name: 'B race', event_date: '2026-07-18', priority: 'B' },
      { name: 'A race', event_date: '2026-09-18', priority: 'A' },
    ];
    expect(priorityEvent(events).name).toBe('A race');
  });
  it('falls back to the earliest event when none is A', () => {
    const events = [
      { name: 'Later', event_date: '2026-09-18', priority: 'C' },
      { name: 'Earlier', event_date: '2026-07-18', priority: 'C' },
    ];
    expect(priorityEvent(events).name).toBe('Earlier');
  });
  it('returns null for no events', () => {
    expect(priorityEvent([])).toBeNull();
  });
});

describe('macroTargetEvent', () => {
  const events = [
    { id: 'warm-lake', name: 'Warm Lake Fall Breeze 3K', event_date: '2026-09-26', priority: 'B' },
    { id: 'ten-k', name: 'Andrew Test Goal 10K', event_date: '2026-10-03', priority: 'B' },
    { id: 'quinns', name: "Quinn's Halloween Spook Swim 4K", event_date: '2026-10-30', priority: 'A' },
  ];

  it('resolves the event the macro actually targets, even when it is not the soonest/priority-A pick', () => {
    // Regression: replace_macro_plan moved the athlete's macro onto Quinn's
    // (Oct 30, priority A), but the Plan tab masthead kept showing Warm Lake
    // (Sep 26) because it derived the displayed event from priorityEvent()
    // alone, ignoring macro.event_id entirely.
    const macro = { event_id: 'quinns', blocks: [] };
    expect(macroTargetEvent(macro, events).name).toBe("Quinn's Halloween Spook Swim 4K");
  });

  it('falls back to priorityEvent when there is no macro', () => {
    expect(macroTargetEvent(null, events).id).toBe('quinns'); // priority A wins
  });

  it('falls back to priorityEvent when the macro event_id does not match any known event', () => {
    const macro = { event_id: 'deleted-event', blocks: [] };
    expect(macroTargetEvent(macro, events).id).toBe('quinns');
  });
});

describe('currentBlockIndex', () => {
  const blocks = [
    { name: 'base', start_date: '2026-07-06', end_date: '2026-08-02' },
    { name: 'build', start_date: '2026-08-03', end_date: '2026-08-16' },
  ];
  it('finds the block containing now', () => {
    expect(currentBlockIndex(blocks, new Date(2026, 6, 10))).toBe(0);
    expect(currentBlockIndex(blocks, new Date(2026, 7, 10))).toBe(1);
  });
  it('falls back to the first block when now is before the plan', () => {
    expect(currentBlockIndex(blocks, new Date(2026, 5, 1))).toBe(0);
  });
  it('falls back to the last block when now is after the plan', () => {
    expect(currentBlockIndex(blocks, new Date(2026, 11, 1))).toBe(1);
  });
});

describe('sessionsByDay', () => {
  it('buckets sessions into the correct weekday', () => {
    const week = {
      iso_week: '2026-W28',
      sessions: [
        { date: '2026-07-06', sport: 'swim_pool' },
        { date: '2026-07-09', sport: 'swim_ow' },
      ],
    };
    const days = sessionsByDay(week);
    expect(days).toHaveLength(7);
    expect(days[0].dow).toBe('Mon');
    expect(days[0].sessions).toHaveLength(1);
    expect(days[3].dow).toBe('Thu');
    expect(days[3].sessions).toHaveLength(1);
    expect(days[1].sessions).toHaveLength(0);
  });
});

describe('longSwimLadder', () => {
  it('derives the biggest swim, a peak estimate, and the event from real-shaped data', () => {
    const weeks = [
      {
        sessions: [
          { sport: 'swim_ow', distance_m: 15000, duration_min: 300, date: '2026-07-09' },
          { sport: 'swim_ow', distance_m: 1500, duration_min: 30, date: '2026-07-16' },
        ],
      },
    ];
    const macro = {
      blocks: [
        { name: 'base', start_date: '2026-07-06', end_date: '2026-08-02' },
        { name: 'build', start_date: '2026-08-03', end_date: '2026-08-16' },
        { name: 'peak', start_date: '2026-08-17', end_date: '2026-08-30' },
        { name: 'taper', start_date: '2026-08-31', end_date: '2026-09-13' },
      ],
    };
    const event = { name: 'UltraSwim 33.3 Greece', distance_m: 33300, event_date: '2026-09-18' };

    const rungs = longSwimLadder(weeks, macro, event);
    expect(rungs[0].km).toBe('15');
    expect(rungs.some((r) => r.connective === 'build-ups')).toBe(true);
    expect(rungs.at(-1).final).toBe(true);
    expect(rungs.at(-1).km).toBe('33.3');
  });

  it('returns an empty ladder with no swims, macro, or event', () => {
    expect(longSwimLadder([], null, null)).toEqual([]);
  });
});

describe('RACE_DAY_TSB_BAND', () => {
  it('is the +5 to +25 TrainingPeaks/Joe Friel cycling-coaching reference range', () => {
    expect(RACE_DAY_TSB_BAND).toEqual({ low: 5, high: 25 });
  });
});

describe('PRODUCTIVE_TRAINING_TSB_BAND', () => {
  it('is the -30 to -10 PMC-convention "productive training"/"optimal" reference range', () => {
    expect(PRODUCTIVE_TRAINING_TSB_BAND).toEqual({ low: -30, high: -10 });
  });

  it('sits entirely below RACE_DAY_TSB_BAND, with no overlap', () => {
    expect(PRODUCTIVE_TRAINING_TSB_BAND.high).toBeLessThan(RACE_DAY_TSB_BAND.low);
  });
});

describe('LOAD_CHART_WINDOW_DAYS', () => {
  it('defaults to 42 days (6 weeks)', () => {
    expect(LOAD_CHART_WINDOW_DAYS).toBe(42);
  });
});

describe('LOAD_CHART_WINDOW_OPTIONS', () => {
  it('offers 6 weeks (42d), 12 weeks (84d), and a full-series Season option', () => {
    expect(LOAD_CHART_WINDOW_OPTIONS).toEqual([
      { days: 42, label: '6 weeks' },
      { days: 84, label: '12 weeks' },
      { days: null, label: 'Season' },
    ]);
  });

  it('the default window is one of the offered options', () => {
    expect(LOAD_CHART_WINDOW_OPTIONS.some((o) => o.days === LOAD_CHART_WINDOW_DAYS)).toBe(true);
  });
});

describe('TSB_AXIS_DOMAIN', () => {
  it('is a fixed range wide enough to hold both named bands with margin', () => {
    expect(TSB_AXIS_DOMAIN.min).toBeLessThan(PRODUCTIVE_TRAINING_TSB_BAND.low);
    expect(TSB_AXIS_DOMAIN.max).toBeGreaterThan(RACE_DAY_TSB_BAND.high);
  });
});

describe('classifyTsbBand', () => {
  it('classifies below the productive band as high-risk', () => {
    expect(classifyTsbBand(PRODUCTIVE_TRAINING_TSB_BAND.low - 1)).toBe('high-risk');
  });

  it('classifies inside the productive band as productive', () => {
    expect(classifyTsbBand(PRODUCTIVE_TRAINING_TSB_BAND.low)).toBe('productive');
    expect(classifyTsbBand(PRODUCTIVE_TRAINING_TSB_BAND.high)).toBe('productive');
  });

  it('classifies between the two named bands as grey-zone', () => {
    expect(classifyTsbBand(PRODUCTIVE_TRAINING_TSB_BAND.high + 1)).toBe('grey-zone');
  });

  it('classifies inside the race-day band as race-ready', () => {
    expect(classifyTsbBand(RACE_DAY_TSB_BAND.low)).toBe('race-ready');
    expect(classifyTsbBand(RACE_DAY_TSB_BAND.high)).toBe('race-ready');
  });

  it('classifies above the race-day band as transition', () => {
    expect(classifyTsbBand(RACE_DAY_TSB_BAND.high + 1)).toBe('transition');
  });
});

describe('formatMonthLabel', () => {
  it('formats a date as a short month name only', () => {
    expect(formatMonthLabel(new Date(2026, 6, 15))).toBe('Jul');
  });
});

describe('ctlAtlTsbChartGeometry', () => {
  it('returns isEmpty for a missing or empty series, without erroring', () => {
    expect(ctlAtlTsbChartGeometry([]).isEmpty).toBe(true);
    expect(ctlAtlTsbChartGeometry(null).isEmpty).toBe(true);
    expect(ctlAtlTsbChartGeometry(undefined).isEmpty).toBe(true);
  });

  it('produces one point per series entry for each of the three lines', () => {
    const series = [
      ['2026-08-01', 10, 5, 5],
      ['2026-08-02', 11, 6, 5],
      ['2026-08-03', 12, 4, 8],
    ];
    const geo = ctlAtlTsbChartGeometry(series);
    expect(geo.isEmpty).toBe(false);
    expect(geo.ctlPoints).toHaveLength(3);
    expect(geo.atlPoints).toHaveLength(3);
    expect(geo.tsbPoints).toHaveLength(3);
    // x strictly increases left to right, matching the series' own
    // ascending-by-date order.
    expect(geo.ctlPoints[0].x).toBeLessThan(geo.ctlPoints[1].x);
    expect(geo.ctlPoints[1].x).toBeLessThan(geo.ctlPoints[2].x);
    // First/last x land exactly on the plot's left/right edges.
    expect(geo.ctlPoints[0].x).toBeCloseTo(geo.plotLeft, 5);
    expect(geo.ctlPoints[2].x).toBeCloseTo(geo.plotRight, 5);
  });

  it('single-point series is centered horizontally and does not divide by zero', () => {
    const geo = ctlAtlTsbChartGeometry([['2026-08-01', 10, 5, 5]]);
    expect(geo.isEmpty).toBe(false);
    expect(Number.isFinite(geo.ctlPoints[0].x)).toBe(true);
    expect(Number.isFinite(geo.ctlPoints[0].y)).toBe(true);
    expect(geo.ctlPoints[0].x).toBeCloseTo((geo.plotLeft + geo.plotRight) / 2, 5);
  });

  it('right padding is small -- no secondary axis lives past plotRight any more', () => {
    // Was 34px (matching the left axis) to make room for the old
    // dual-axis design's secondary tick labels on the right edge; nothing
    // draws past plotRight in the two-panel design, so this should be back
    // down near the pre-dual-axis ~12px, not still budgeting for a second
    // axis that no longer exists.
    const series = [['2026-08-01', 10, 5, 5], ['2026-08-02', 11, 6, 5]];
    const geo = ctlAtlTsbChartGeometry(series);
    expect(geo.width - geo.plotRight).toBeLessThanOrEqual(16);
  });

  it('respects custom width/height/padding options', () => {
    const series = [['2026-08-01', 10, 5, 5], ['2026-08-02', 11, 6, 5]];
    const geo = ctlAtlTsbChartGeometry(series, { width: 300, height: 150 });
    expect(geo.width).toBe(300);
    expect(geo.height).toBe(150);
  });

  it('x ticks always include the first and last date', () => {
    const series = Array.from({ length: 20 }, (_, i) => [`2026-08-${String(i + 1).padStart(2, '0')}`, i, i, 0]);
    const geo = ctlAtlTsbChartGeometry(series);
    const labels = geo.xTicks.map((t) => t.label);
    expect(labels[0]).toBe('2026-08-01');
    expect(labels.at(-1)).toBe('2026-08-20');
    expect(geo.xTicks.length).toBeLessThanOrEqual(5);
  });

  it('defaults to date-mode x ticks, one per calendar-month boundary in month mode', () => {
    const series = [
      ['2026-06-28', 10, 5, 0], ['2026-06-29', 10, 5, 0], ['2026-06-30', 10, 5, 0],
      ['2026-07-01', 10, 5, 0], ['2026-07-15', 10, 5, 0], ['2026-08-01', 10, 5, 0],
    ];
    const dateGeo = ctlAtlTsbChartGeometry(series);
    expect(dateGeo.xTickMode).toBe('date');

    const monthGeo = ctlAtlTsbChartGeometry(series, { xTickMode: 'month' });
    expect(monthGeo.xTickMode).toBe('month');
    // One tick for the series' first index, then one per new month entered:
    // Jun 28 (start), Jul 1 (month change), Aug 1 (month change) => 3 ticks.
    expect(monthGeo.xTicks.map((t) => t.label)).toEqual(['2026-06-28', '2026-07-01', '2026-08-01']);
  });

  it('caps month-mode x ticks at 5 even when the series spans many months', () => {
    // A year-plus of daily entries crossing 14 calendar-month boundaries --
    // unbounded, "Season" mode would crowd 14+ month labels into the same
    // axis width date-mode budgets 5 dates for.
    const series = [];
    let d = new Date('2025-06-01T00:00:00Z');
    const end = new Date('2026-08-01T00:00:00Z');
    while (d < end) {
      series.push([d.toISOString().slice(0, 10), 10, 5, 0]);
      d.setUTCDate(d.getUTCDate() + 1);
    }
    const geo = ctlAtlTsbChartGeometry(series, { xTickMode: 'month' });
    expect(geo.xTicks.length).toBeLessThanOrEqual(5);
    // Still anchors on the series' real first and last month-boundary tick.
    expect(geo.xTicks[0].label).toBe(series[0][0]);
  });

  describe('top panel (CTL/ATL, "fitness & fatigue") -- one shared, 0-anchored axis', () => {
    it('a higher value plots higher on screen (smaller SVG y)', () => {
      const series = [
        ['2026-08-01', 10, 5, 5],
        ['2026-08-02', 20, 5, 15],
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      expect(geo.ctlPoints[1].y).toBeLessThan(geo.ctlPoints[0].y);
    });

    it('a higher ATL value also plots higher on screen, on the SAME axis as CTL', () => {
      const series = [
        ['2026-08-01', 50, 5, 5],
        ['2026-08-02', 50, 15, 5],
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      expect(geo.atlPoints[1].y).toBeLessThan(geo.atlPoints[0].y);
    });

    it('CTL and ATL points fall within the loadPlot pixel span, not the tsbPlot span', () => {
      const series = [
        ['2026-08-01', 10, 40, -20],
        ['2026-08-02', 100, 42, -20],
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      for (const p of [...geo.ctlPoints, ...geo.atlPoints]) {
        expect(p.y).toBeGreaterThanOrEqual(geo.loadPlot.top - 0.01);
        expect(p.y).toBeLessThanOrEqual(geo.loadPlot.bottom + 0.01);
      }
    });

    it('CTL and ATL share the exact same axis (a huge CTL value does not compress ATL toward a flat line)', () => {
      // Before the two-panel split, this same scenario compressed ATL's
      // 40->42 movement to a sliver on a shared-with-CTL axis. Sharing a
      // 0-anchored axis is now the deliberate point (see plan.js's module
      // comment: the CTL/ATL gap IS the fatigue story) -- so this no longer
      // asserts ATL gets independent spread; it asserts CTL and ATL use the
      // literal same linear mapping (same two points at the same raw value
      // land at the same pixel y).
      const series = [
        ['2026-08-01', 10, 10, 0],
        ['2026-08-02', 100, 100, 0],
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      expect(geo.ctlPoints[0].y).toBeCloseTo(geo.atlPoints[0].y, 5);
      expect(geo.ctlPoints[1].y).toBeCloseTo(geo.atlPoints[1].y, 5);
    });

    it('the shared axis is anchored at 0 even when all real CTL/ATL values are well above it', () => {
      const series = [
        ['2026-08-01', 40, 35, 0],
        ['2026-08-02', 42, 33, 0],
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      const values = geo.yTicks.map((t) => t.value);
      expect(Math.min(...values)).toBeLessThanOrEqual(0);
    });

    it('y ticks span from below the data minimum to above the data maximum', () => {
      const series = [
        ['2026-08-01', 10, 5, 5],
        ['2026-08-02', 20, 8, 12],
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      const values = geo.yTicks.map((t) => t.value);
      expect(Math.min(...values)).toBeLessThanOrEqual(0);
      expect(Math.max(...values)).toBeGreaterThan(20);
    });
  });

  describe('bottom panel (TSB, "form") -- fixed TSB_AXIS_DOMAIN, clamped', () => {
    it('the race-day and productive-training bands are always inside the tsbPlot pixel span', () => {
      const series = [
        ['2026-08-01', 30, 30, 0],
        ['2026-08-02', 30, 30, 0],
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      expect(geo.raceBand.top).toBeGreaterThanOrEqual(geo.tsbPlot.top);
      expect(geo.raceBand.bottom).toBeLessThanOrEqual(geo.tsbPlot.bottom);
      expect(geo.raceBand.top).toBeLessThan(geo.raceBand.bottom);
      expect(geo.productiveBand.top).toBeGreaterThanOrEqual(geo.tsbPlot.top);
      expect(geo.productiveBand.bottom).toBeLessThanOrEqual(geo.tsbPlot.bottom);
      expect(geo.productiveBand.top).toBeLessThan(geo.productiveBand.bottom);
      // Productive band (-30..-10) is a lower TSB range than the race-day
      // band (+5..+25), so it must plot BELOW it (larger pixel y).
      expect(geo.productiveBand.top).toBeGreaterThan(geo.raceBand.bottom);
    });

    it('the TSB domain (and therefore the bands) never moves with the data -- same pixel position regardless of series values', () => {
      const flat = ctlAtlTsbChartGeometry([['2026-08-01', 30, 30, 0], ['2026-08-02', 30, 30, 0]]);
      const extreme = ctlAtlTsbChartGeometry([['2026-08-01', 30, 30, -35], ['2026-08-02', 30, 30, 30]]);
      expect(extreme.raceBand).toEqual(flat.raceBand);
      expect(extreme.productiveBand).toEqual(flat.productiveBand);
    });

    it('a TSB value inside the fixed domain plots at its true value, unclamped', () => {
      const series = [['2026-08-01', 40, 40, -10], ['2026-08-02', 40, 40, 10]];
      const geo = ctlAtlTsbChartGeometry(series);
      expect(geo.tsbClamped).toEqual([]);
    });

    it('a TSB value outside the fixed domain is clamped to the nearest edge and flagged in tsbClamped', () => {
      const series = [
        ['2026-08-01', 40, 40, -60], // below TSB_AXIS_DOMAIN.min (-40)
        ['2026-08-02', 40, 40, 0],
        ['2026-08-03', 40, 40, 60], // above TSB_AXIS_DOMAIN.max (35)
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      expect(geo.tsbClamped).toEqual([0, 2]);
      // Clamped points land exactly on the tsbPlot edges.
      expect(geo.tsbPoints[0].y).toBeCloseTo(geo.tsbPlot.bottom, 1);
      expect(geo.tsbPoints[2].y).toBeCloseTo(geo.tsbPlot.top, 1);
    });

    it('a higher TSB value plots higher on screen (smaller SVG y)', () => {
      const series = [['2026-08-01', 30, 30, -10], ['2026-08-02', 30, 30, 10]];
      const geo = ctlAtlTsbChartGeometry(series);
      expect(geo.tsbPoints[1].y).toBeLessThan(geo.tsbPoints[0].y);
    });

    it('exposes a zero line inside the tsbPlot span', () => {
      const geo = ctlAtlTsbChartGeometry([['2026-08-01', 30, 30, 0], ['2026-08-02', 30, 30, 5]]);
      expect(geo.tsbZeroY).toBeGreaterThanOrEqual(geo.tsbPlot.top);
      expect(geo.tsbZeroY).toBeLessThanOrEqual(geo.tsbPlot.bottom);
    });

    it('exposes the latest (last-point) TSB value, pixel position, and band classification', () => {
      const series = [
        ['2026-08-01', 40, 70, -40],
        ['2026-08-02', 42, 59, -17], // inside the productive band
      ];
      const geo = ctlAtlTsbChartGeometry(series);
      expect(geo.latestTsb.value).toBe(-17);
      expect(geo.latestTsb.band).toBe('productive');
      expect(geo.latestTsb.x).toBeCloseTo(geo.plotRight, 5);
      expect(geo.latestTsb.y).toBeGreaterThanOrEqual(geo.tsbPlot.top);
      expect(geo.latestTsb.y).toBeLessThanOrEqual(geo.tsbPlot.bottom);
    });
  });

  describe('two-panel layout', () => {
    it('the load (top) panel sits entirely above the TSB (bottom) panel, with a gap between them', () => {
      const geo = ctlAtlTsbChartGeometry([['2026-08-01', 30, 30, 0], ['2026-08-02', 30, 30, 0]]);
      expect(geo.loadPlot.top).toBeLessThan(geo.loadPlot.bottom);
      expect(geo.tsbPlot.top).toBeLessThan(geo.tsbPlot.bottom);
      expect(geo.loadPlot.bottom).toBeLessThan(geo.tsbPlot.top);
    });

    it('the TSB panel gets roughly TSB_PANEL_RATIO of the combined plot height', () => {
      const geo = ctlAtlTsbChartGeometry([['2026-08-01', 30, 30, 0], ['2026-08-02', 30, 30, 0]]);
      const loadH = geo.loadPlot.bottom - geo.loadPlot.top;
      const tsbH = geo.tsbPlot.bottom - geo.tsbPlot.top;
      const ratio = tsbH / (loadH + tsbH);
      expect(ratio).toBeCloseTo(TSB_PANEL_RATIO, 1);
    });

    it('both panels share the same x extents (plotLeft/plotRight)', () => {
      const geo = ctlAtlTsbChartGeometry([['2026-08-01', 30, 30, 0], ['2026-08-02', 30, 30, 5]]);
      // Every point (whichever panel it's in) uses the same xFor mapping --
      // the first/last point's x always lands on plotLeft/plotRight for
      // every one of the three series.
      expect(geo.ctlPoints[0].x).toBeCloseTo(geo.plotLeft, 5);
      expect(geo.tsbPoints[0].x).toBeCloseTo(geo.plotLeft, 5);
      expect(geo.ctlPoints.at(-1).x).toBeCloseTo(geo.plotRight, 5);
      expect(geo.tsbPoints.at(-1).x).toBeCloseTo(geo.plotRight, 5);
    });
  });
});

describe('describeCtlAtlTsbTrend', () => {
  // Builds a `ctl_atl_tsb`-shaped series of `n` daily points starting at
  // `startIso`, with per-point [ctl, atl, tsb] from `valueFn(i)`. Pure UTC
  // date math (Date.UTC + a fixed 86400000ms step, `toISOString` to read
  // the date back out) so the generated ISO strings never depend on the
  // machine's local timezone, unlike stepping a local `Date` across a
  // month/year boundary would.
  function buildSeries(startIso, n, valueFn) {
    const [y, m, d] = startIso.split('-').map(Number);
    const startMs = Date.UTC(y, m - 1, d);
    return Array.from({ length: n }, (_, i) => {
      const iso = new Date(startMs + i * 86400000).toISOString().slice(0, 10);
      const [ctl, atl, tsb] = valueFn(i);
      return [iso, ctl, atl, tsb];
    });
  }

  it('reports no data for an empty or missing series', () => {
    for (const series of [[], null, undefined]) {
      expect(describeCtlAtlTsbTrend(series)).toEqual({
        hasData: false, historyDays: null, warmup: null, ctlTrend: null, atlSpike: null, tsb: null,
      });
    }
  });

  it('a single-point series has no trend/spike (nothing to compare) but does have a TSB reading', () => {
    const result = describeCtlAtlTsbTrend([['2026-08-01', 10, 5, 3]]);
    expect(result.hasData).toBe(true);
    expect(result.historyDays).toBe(1);
    expect(result.ctlTrend).toBeNull();
    expect(result.atlSpike).toBeNull();
    // TSB=3 sits between the two named bands (productive tops out at -10,
    // race-ready starts at +5) -- genuinely neither, i.e. 'grey-zone'.
    expect(result.tsb).toEqual({ date: '2026-08-01', value: 3, band: 'grey-zone' });
    // 1 day is nowhere near CTL_COLD_START_DAYS -- definitely cold-start.
    expect(result.warmup).toBe('cold-start');
  });

  it('flags a series shorter than the trend window as insufficient, rather than silently comparing over a shorter span', () => {
    // 5 daily points -- well short of CTL_ATL_TREND_WINDOW_DAYS (14).
    const series = buildSeries('2026-08-01', 5, (i) => [10 + i, 5 + i, 5]);
    const result = describeCtlAtlTsbTrend(series);
    expect(result.historyDays).toBe(5);
    expect(result.ctlTrend).toEqual({
      status: 'insufficient-window', historyDays: 5, requiredWindowDays: CTL_ATL_TREND_WINDOW_DAYS,
    });
    // The ATL-spike search doesn't need a full window -- it still reports
    // the biggest available swing from whatever history exists.
    expect(result.atlSpike).not.toBeNull();
  });

  it('detects a rising CTL trend with the real before/after numbers', () => {
    // 20 daily points, CTL climbing by 1/day -- comfortably past both the
    // window (14 days) and the flat threshold (3 points).
    const series = buildSeries('2026-08-01', 20, (i) => [10 + i, 5, 0]);
    const result = describeCtlAtlTsbTrend(series);
    expect(result.ctlTrend.status).toBe('rising');
    expect(result.ctlTrend.toValue).toBe(29); // 10 + 19
    expect(result.ctlTrend.fromValue).toBe(29 - CTL_ATL_TREND_WINDOW_DAYS);
    expect(result.ctlTrend.toDate).toBe(series.at(-1)[0]);
  });

  it('detects a falling CTL trend', () => {
    const series = buildSeries('2026-08-01', 20, (i) => [40 - i, 5, 0]);
    const result = describeCtlAtlTsbTrend(series);
    expect(result.ctlTrend.status).toBe('falling');
    expect(result.ctlTrend.fromValue).toBeGreaterThan(result.ctlTrend.toValue);
  });

  it('classifies a small drift within CTL_TREND_FLAT_THRESHOLD as flat, not a false direction', () => {
    const series = buildSeries('2026-08-01', 20, (i) => [50 + (i % 2), 5, 0]);
    const result = describeCtlAtlTsbTrend(series);
    expect(result.ctlTrend.status).toBe('flat');
  });

  it('treats a delta of exactly CTL_TREND_FLAT_THRESHOLD as a real direction, not flat (boundary is exclusive)', () => {
    const atThreshold = [
      ['2026-08-01', 10, 5, 0],
      ['2026-08-15', 10 + CTL_TREND_FLAT_THRESHOLD, 5, 0], // exactly 14 days apart
    ];
    expect(describeCtlAtlTsbTrend(atThreshold).ctlTrend.status).toBe('rising');
    const justUnder = [
      ['2026-08-01', 10, 5, 0],
      ['2026-08-15', 10 + CTL_TREND_FLAT_THRESHOLD - 0.5, 5, 0],
    ];
    expect(describeCtlAtlTsbTrend(justUnder).ctlTrend.status).toBe('flat');
  });

  it('finds the single largest ATL jump in the recent window, not just the last delta', () => {
    // ATL: mostly small day-to-day moves, with one big jump in the middle
    // of the window -- the "big training day" shape from the real example.
    const atlValues = [40, 39, 39.2, 111.1, 105, 100, 95, 90, 88, 86, 84, 82, 80, 78, 76];
    const series = buildSeries('2026-08-10', atlValues.length, (i) => [50, atlValues[i], 0]);
    const result = describeCtlAtlTsbTrend(series);
    expect(result.atlSpike.direction).toBe('up');
    expect(result.atlSpike.fromValue).toBe(39.2);
    expect(result.atlSpike.toValue).toBe(111.1);
  });

  it('reports a downward ATL swing honestly as "down", not force-fit into "spike"', () => {
    const atlValues = [100, 98, 20, 19, 18];
    const series = buildSeries('2026-08-20', atlValues.length, (i) => [50, atlValues[i], 0]);
    const result = describeCtlAtlTsbTrend(series);
    expect(result.atlSpike.direction).toBe('down');
    expect(result.atlSpike.fromValue).toBe(98);
    expect(result.atlSpike.toValue).toBe(20);
  });

  it('classifies current TSB five-way against both named bands, independent of race proximity', () => {
    // Below the productive-training band entirely -- fatigue outrunning
    // even the "expected while building" convention.
    const highRisk = describeCtlAtlTsbTrend([['2026-08-01', 40, 75, -40]]);
    expect(highRisk.tsb.band).toBe('high-risk');
    // Inside the productive-training band (-30 to -10) -- the real
    // motivating example: Fitness 42 / Fatigue 59 / Form -17.
    const productive = describeCtlAtlTsbTrend([['2026-08-01', 42, 59, -17]]);
    expect(productive.tsb.band).toBe('productive');
    // Between the two named bands -- genuinely neither.
    const greyZone = describeCtlAtlTsbTrend([['2026-08-01', 40, 40, 0]]);
    expect(greyZone.tsb.band).toBe('grey-zone');
    // Inside the race-ready band.
    const raceReady = describeCtlAtlTsbTrend([['2026-08-01', 40, 30, 10]]);
    expect(raceReady.tsb.band).toBe('race-ready');
    // Above the race-ready band -- fresher than useful.
    const transition = describeCtlAtlTsbTrend([['2026-08-01', 60, 20, 40]]);
    expect(transition.tsb.band).toBe('transition');

    // Boundary values are inclusive of whichever named band they touch.
    const atProductiveLow = describeCtlAtlTsbTrend(
      [['2026-08-01', 40, 70, PRODUCTIVE_TRAINING_TSB_BAND.low]]
    );
    expect(atProductiveLow.tsb.band).toBe('productive');
    const atProductiveHigh = describeCtlAtlTsbTrend(
      [['2026-08-01', 40, 50, PRODUCTIVE_TRAINING_TSB_BAND.high]]
    );
    expect(atProductiveHigh.tsb.band).toBe('productive');
    const atRaceLow = describeCtlAtlTsbTrend([['2026-08-01', 40, 35, RACE_DAY_TSB_BAND.low]]);
    expect(atRaceLow.tsb.band).toBe('race-ready');
    const atRaceHigh = describeCtlAtlTsbTrend([['2026-08-01', 40, 15, RACE_DAY_TSB_BAND.high]]);
    expect(atRaceHigh.tsb.band).toBe('race-ready');
  });

  it('classifies warmup status by history length: cold-start below CTL_COLD_START_DAYS, warming-up up to CTL_WARMED_UP_DAYS, warmed-up beyond', () => {
    const cold = buildSeries('2026-01-01', CTL_COLD_START_DAYS - 1, (i) => [i, 5, 0]);
    expect(describeCtlAtlTsbTrend(cold).warmup).toBe('cold-start');

    const justWarming = buildSeries('2026-01-01', CTL_COLD_START_DAYS, (i) => [i, 5, 0]);
    expect(describeCtlAtlTsbTrend(justWarming).warmup).toBe('warming-up');

    // A real ~60-day athlete history (the documented motivating case) --
    // past one time constant but nowhere near "a few multiples" of it.
    const sixtyDays = buildSeries('2026-01-01', 60, (i) => [i, 5, 0]);
    expect(describeCtlAtlTsbTrend(sixtyDays).warmup).toBe('warming-up');

    const stillWarming = buildSeries('2026-01-01', CTL_WARMED_UP_DAYS - 1, (i) => [i, 5, 0]);
    expect(describeCtlAtlTsbTrend(stillWarming).warmup).toBe('warming-up');

    const fullyWarmed = buildSeries('2026-01-01', CTL_WARMED_UP_DAYS, (i) => [i, 5, 0]);
    expect(describeCtlAtlTsbTrend(fullyWarmed).warmup).toBe('warmed-up');
  });

  it('is robust to non-daily (sparse) series -- date math, not index counting', () => {
    // Weekly points, matching the shape used by this feature's own e2e
    // fixture -- must not assume a fixed daily index spacing.
    const series = [
      ['2026-08-01', 40.0, 38.0, 2.0],
      ['2026-08-08', 41.0, 30.0, 11.0],
      ['2026-08-15', 40.5, 20.0, 20.5],
      ['2026-08-22', 40.0, 15.0, 25.0],
    ];
    const result = describeCtlAtlTsbTrend(series);
    expect(result.historyDays).toBe(22);
    // window target = 2026-08-22 minus 14 days = 2026-08-08, which is an
    // exact point in this series.
    expect(result.ctlTrend.fromDate).toBe('2026-08-08');
    expect(result.ctlTrend.toDate).toBe('2026-08-22');
  });
});

describe('raceWeekCategoryLabel', () => {
  it('maps each RaceWeekChecklistItem category to an athlete-facing label', () => {
    expect(raceWeekCategoryLabel('carb_load')).toBe('Carb-load');
    expect(raceWeekCategoryLabel('bodywork')).toBe('Bodywork');
    expect(raceWeekCategoryLabel('logistics')).toBe('Logistics');
  });

  it('falls back to the raw category string for an unknown value', () => {
    expect(raceWeekCategoryLabel('mystery')).toBe('mystery');
  });
});

describe('describeWellnessBaselineDeviation', () => {
  it('reports no-data for null fields', () => {
    const result = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: null, hrv_pct_deviation: null,
    });
    expect(result.restingHr).toEqual({ value: null, status: 'no-data' });
    expect(result.hrv).toEqual({ value: null, status: 'no-data' });
  });

  it('reports no-data when the field is missing or the whole dict is absent', () => {
    expect(describeWellnessBaselineDeviation({}).restingHr.status).toBe('no-data');
    expect(describeWellnessBaselineDeviation(undefined).restingHr.status).toBe('no-data');
    expect(describeWellnessBaselineDeviation(null).hrv.status).toBe('no-data');
  });

  it('flags a positive resting_hr_pct_deviation at/above the threshold as concerning (elevated = bad)', () => {
    const atThreshold = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: WELLNESS_DEVIATION_CONCERNING_PCT, hrv_pct_deviation: null,
    });
    expect(atThreshold.restingHr).toEqual({ value: WELLNESS_DEVIATION_CONCERNING_PCT, status: 'concerning' });

    const wellAbove = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: 12.5, hrv_pct_deviation: null,
    });
    expect(wellAbove.restingHr).toEqual({ value: 12.5, status: 'concerning' });
  });

  it('reports resting_hr_pct_deviation below the threshold (including negative) as good', () => {
    const belowThreshold = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: 2.0, hrv_pct_deviation: null,
    });
    expect(belowThreshold.restingHr).toEqual({ value: 2.0, status: 'good' });

    const negative = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: -8.0, hrv_pct_deviation: null,
    });
    expect(negative.restingHr).toEqual({ value: -8.0, status: 'good' });
  });

  it('flags a negative hrv_pct_deviation at/beyond the threshold as concerning (suppressed = bad)', () => {
    const atThreshold = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: null, hrv_pct_deviation: -WELLNESS_DEVIATION_CONCERNING_PCT,
    });
    expect(atThreshold.hrv).toEqual({ value: -WELLNESS_DEVIATION_CONCERNING_PCT, status: 'concerning' });

    const wellBelow = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: null, hrv_pct_deviation: -20.0,
    });
    expect(wellBelow.hrv).toEqual({ value: -20.0, status: 'concerning' });
  });

  it('reports hrv_pct_deviation above the negative threshold (including positive) as good', () => {
    const mild = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: null, hrv_pct_deviation: -2.0,
    });
    expect(mild.hrv).toEqual({ value: -2.0, status: 'good' });

    const positive = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: null, hrv_pct_deviation: 15.0,
    });
    expect(positive.hrv).toEqual({ value: 15.0, status: 'good' });
  });

  it('classifies resting_hr and hrv independently in the same call (opposite sign conventions)', () => {
    // A simultaneously elevated RHR (bad) and suppressed HRV (bad) --
    // both flagged concerning despite opposite-signed raw values.
    const bothBad = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: 9.0, hrv_pct_deviation: -9.0,
    });
    expect(bothBad.restingHr.status).toBe('concerning');
    expect(bothBad.hrv.status).toBe('concerning');

    // A high positive HRV deviation is NOT concerning (never flip the
    // sign convention to force "big number = bad" onto both fields).
    const hrvUp = describeWellnessBaselineDeviation({
      resting_hr_pct_deviation: null, hrv_pct_deviation: 9.0,
    });
    expect(hrvUp.hrv.status).toBe('good');
  });
});
