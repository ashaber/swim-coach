import { describe, it, expect } from 'vitest';
import {
  isoWeekMonday, formatDuration, formatDistance, formatPace, splitPurpose,
  classifySession, sessionDisplay, deriveSessionTitle, findSessionById,
  pickCurrentAndNextWeek, sortedByIsoWeek, daysUntil,
  priorityEvent, macroTargetEvent, currentBlockIndex, longSwimLadder, sessionsByDay,
  parseStructureBlocks, parseMainSetIntervals, renderStructuredWorkout,
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
