import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import {
  availableMetrics, buildDrill, buildFadeCard, buildFinishSprint, buildFreeSpeed, buildLapsCard, buildRaceSummary, buildRaceView,
  buildSectionAnalysis, buildSplitControls, buildStartCard, clockTenths, hasRaceView, nextSplits, probeIndex, probeLeftPct,
  probeReadout, sectionFrame,
} from '../../src/raceView.js';
import { bucketOf, NEUTRAL, TIER_COLOURS } from '../../src/raceHeat.js';
import { renderWorkoutDetail } from '../../src/views.js';

const FIXTURE = JSON.parse(readFileSync(new URL('../fixtures/race_view_sunday.json', import.meta.url), 'utf8'));
const W = FIXTURE.workout;
const SECTIONS = FIXTURE.sections;
const clone = (o) => JSON.parse(JSON.stringify(o));
const detail = (w, extra = {}) => renderWorkoutDetail(w, { online: true, chat: null, ...extra });

describe('gate', () => {
  it('shows the race view only for a race with sections', () => {
    expect(hasRaceView(W)).toBe(true);
    expect(hasRaceView({ ...W, kind: 'workout' })).toBe(false);
    expect(hasRaceView({ ...W, analytics: { ...W.analytics, course_sectors: undefined } })).toBe(false);
  });
  it('leaves a non-race ride on the ordinary detail view', () => {
    const html = detail({ ...W, kind: 'workout' });
    expect(html).not.toContain('rv-card');
  });
});

describe('summary card', () => {
  it('reads the overview and flags max power', () => {
    const s = buildRaceSummary(W);
    expect(s.headline.map((h) => h.value)).toEqual(['43:28', '232', '933', '166']);
    expect(s.headline[2].emphasis).toBe(true);
    expect(s.more.map((m) => m.label)).toEqual(expect.arrayContaining(['max HR', 'work', 'start + laps', 'total grit']));
    expect(s.more.find((m) => m.label === 'start + laps').value).toBe('1 + 7');
  });
  it('falls back to the existing fields without race_overview', () => {
    const w = clone(W);
    delete w.analytics.race_overview;
    const s = buildRaceSummary(w);
    expect(s.headline[1].value).toBe('232');
    expect(s.headline[2].value).toBe('933'); // 1 s power-curve point
    expect(s.more.some((m) => m.label === 'work')).toBe(false);
  });
  it('toggles the extra numbers with aria-expanded', () => {
    expect(detail(W)).toContain('aria-expanded="false"');
    const open = detail(W, { raceUi: { moreOpen: true } });
    expect(open).toContain('aria-expanded="true"');
    expect(open).toContain('rv-more');
  });
});

describe('start card', () => {
  const start = buildStartCard(W);
  it('has the three tiles with the previous race alongside', () => {
    expect(start.tiles.map((t) => t.value)).toEqual(['933', '588', '37']);
    expect(start.tiles[1].label).toContain('Sat 743');
    expect(start.tiles[2].label).toContain('Sat 40');
    expect(start.subtitle).toContain('vs Saturday');
  });
  it('draws a ghost line and circles the dip', () => {
    expect(start.ghost).toBeTruthy();
    expect(start.dip).toMatchObject({ x: expect.any(Number), y: expect.any(Number) });
    expect(start.callout.strong).toBe('242 W at 7 s');
  });
  it('omits the ghost without a previous race and the circle without a dip', () => {
    const w = clone(W);
    w.analytics.race_start.previous = null;
    w.analytics.race_start.dip = null;
    const s = buildStartCard(w);
    expect(s.ghost).toBeNull();
    expect(s.dip).toBeNull();
    expect(s.callout).toBeNull();
  });
  it('is absent without data', () => {
    const w = clone(W);
    delete w.analytics.race_start;
    expect(buildStartCard(w)).toBeNull();
    expect(detail(w)).not.toContain('aria-label="Start"');
  });
});

describe('probe', () => {
  const rect = { left: 100, width: 320 };
  it('maps a pointer to a sample and clamps', () => {
    expect(probeIndex(100, rect, 40)).toBe(0);
    expect(probeIndex(10000, rect, 40)).toBe(39);
    expect(probeIndex(260, rect, 41)).toBe(20);
  });
  it('places the marker as a percentage', () => {
    expect(probeLeftPct(0, 40)).toBeCloseTo(3.13, 1);
  });
  it('reads seconds, watts, km/h and the previous race', () => {
    const s = buildStartCard(W).series;
    expect(probeReadout(s, 1)).toBe('1 s · Sun 933 W, 24 km/h · Sat 711 W');
  });
  it('counts seconds to the line for the sprint', () => {
    expect(probeReadout({ kind: 'finish', w: [0, 500, 800], v: [10, 20, 30] }, 0)).toBe('2 s to the line · 0 W, 10 km/h');
  });
  it('marks charts as vertical-scroll friendly', () => {
    const html = detail(W);
    expect(html).toContain('class="rv-probe"');
    expect(html).toContain('id="rv-start-read"');
  });
});

describe('finish sprint', () => {
  it('is hidden when null and shown with data', () => {
    expect(buildFinishSprint(W)).toBeNull();
    expect(detail(W)).not.toContain('Finish sprint');
    const w = clone(W);
    w.analytics.finish_sprint = { duration_s: 8, avg_w: 801, peak_w: 932, entry_speed_kmh: 10, exit_speed_kmh: 34, power_w: [0, 400, 800, 932, 700, 0], speed_kmh: [10, 12, 20, 28, 34, 30] };
    const html = detail(w);
    expect(html).toContain('Finish sprint');
    expect(buildFinishSprint(w).tiles.map((t) => t.value)).toEqual(['801', '932', '10→34']);
  });
});

describe('section analysis', () => {
  it('computes the ideal-lap line with the noise-adjusted gap', () => {
    const a = buildSectionAnalysis(W, 'loss');
    expect(a.ideal.ideal).toBe('5:42.8');
    expect(a.ideal.bestLap).toBe('5:49');
    expect(a.ideal.onTable).toBe('6.2 s');
    expect(a.ideal.beyondNoise).toContain('1.2 s');
  });
  it('says laps were within noise when the beyond-noise gap is about zero', () => {
    const w = clone(W);
    w.analytics.course_sectors.ideal_gap_beyond_noise_s = 0.1;
    expect(buildSectionAnalysis(w, 'loss').ideal.beyondNoise).toBe('Laps were within timing noise of each other.');
  });
  it('colours only significant sections on time lost and mutes the rest', () => {
    const rows = buildSectionAnalysis(W, 'loss').rows;
    const c5 = rows.find((r) => r.label === 'C5');
    const c1 = rows.find((r) => r.label === 'C1');
    expect(c5.noise).toBe(false);
    expect(TIER_COLOURS).toContain(c5.colour);
    expect(c1.noise).toBe(true);
    expect(c1.colour).toBe(NEUTRAL);
    expect(c1.text).toBe('within noise');
  });
  it('treats everything as significant when the flags are absent', () => {
    const w = clone(W);
    w.analytics.course_sectors.sectors.forEach((s) => { delete s.loss_significant; });
    expect(buildSectionAnalysis(w, 'loss').rows.every((r) => !r.noise)).toBe(true);
  });
  it('lists only significant biggest losses, or explains there are none', () => {
    const a = buildSectionAnalysis(W, 'loss');
    const bySector = new Map(W.analytics.course_sectors.sectors.map((s) => [s.label, s]));
    expect(a.losses.every((l) => bySector.get(l.label).loss_significant)).toBe(true);
    expect(a.losses.length).toBeGreaterThan(0);
    const w = clone(W);
    w.analytics.course_sectors.top_loss_sectors = [];
    const none = buildSectionAnalysis(w, 'loss');
    expect(none.losses).toEqual([]);
    expect(none.noNotable).toBe('No section stands out beyond timing noise (±0.3 s).');
    expect(detail(w)).toContain('No section stands out beyond timing noise');
  });
  it('greys power sections on efficiency and offers the toggle only with data', () => {
    expect(availableMetrics(W.analytics.course_sectors)).toEqual(['loss', 'spread', 'eff']);
    const rows = buildSectionAnalysis(W, 'eff').rows;
    expect(rows.find((r) => r.label === 'S1')).toMatchObject({ colour: NEUTRAL, text: 'power' });
    expect(rows.find((r) => r.label === 'C4').text).toBe('+30 W');
    const w = clone(W);
    w.analytics.course_sectors.sectors.forEach((s) => { delete s.mean_extra_w; });
    expect(availableMetrics(w.analytics.course_sectors)).toEqual(['loss', 'spread']);
  });
  it('buckets by the tier cuts', () => {
    expect(bucketOf(0.44, [0.45, 0.7, 1])).toBe(0);
    expect(bucketOf(0.7, [0.45, 0.7, 1])).toBe(2);
    expect(bucketOf(3, [0.45, 0.7, 1])).toBe(3);
  });
  it('draws a section on the map as a tappable target', () => {
    const html = detail(W);
    expect(html).toContain('data-a="race:section-open" data-label="C5"');
    expect(html).toContain('within timing noise');
  });
});

describe('free speed, laps and fade', () => {
  it('lists free speed rows and hides an empty list', () => {
    const rows = buildFreeSpeed(W);
    expect(rows[0]).toMatchObject({ label: 'C4', value: '−49 W' });
    expect(rows[0].title).toBe('Lap 5: faster for fewer watts');
    const w = clone(W);
    w.analytics.course_sectors.free_speed = [];
    expect(buildFreeSpeed(w)).toBeNull();
    expect(detail(w)).not.toContain('Free speed');
  });
  it('builds one lap table from canonical laps and never compares the start lap', () => {
    const laps = buildLapsCard(W);
    expect(laps.rows.map((r) => r.n)).toEqual([2, 3, 4, 5, 6, 7, 8]);
    expect(laps.rows.some((r) => r.best)).toBe(true);
    expect(laps.rows[0].np).toBe('239');
    expect(laps.startNote).toContain('Start lap: 2:33 at 284 W NP');
  });
  it('pills the verdict and charts HR against NP', () => {
    const fade = buildFadeCard(W);
    expect(fade.pill).toBe('Gradual drift');
    expect(fade.drifted).toBe(true);
    expect(fade.chart.hrLegend).toMatch(/^HR \d+ → \d+$/);
    expect(fade.chart.firstLabel).toBe('L2');
  });
});

describe('all sections and splits', () => {
  it('offers a split for a section of 400 m or more', () => {
    const controls = buildSplitControls(W);
    expect(controls.map((c) => c.label)).toEqual(['C3']);
    expect(controls[0].button).toBe('Split C3 in 3');
  });
  it('shows split sections and offers to undo', () => {
    const w = clone(W);
    const cs = w.analytics.course_sectors;
    const c3 = cs.sectors.find((s) => s.label === 'C3');
    const parts = ['C3a', 'C3b', 'C3c'].map((label) => ({ ...c3, label, length_m: 225, split_of: 'C3' }));
    cs.sectors.splice(cs.sectors.indexOf(c3), 1, ...parts);
    cs.splits = { C3: 3 };
    const controls = buildSplitControls(w);
    expect(controls).toEqual([expect.objectContaining({ label: 'C3', split: true, button: 'Unsplit C3' })]);
    expect(buildSectionAnalysis(w, 'loss').rows.map((r) => r.label)).toEqual(expect.arrayContaining(['C3a', 'C3b', 'C3c']));
  });
  it('sends the full desired splits map', () => {
    expect(nextSplits({}, 'C3', false)).toEqual({ C3: 3 });
    expect(nextSplits({ C3: 3, S4: 3 }, 'C3', true)).toEqual({ S4: 3 });
    expect(nextSplits(undefined, 'C3', true)).toEqual({});
  });
});

describe('whole view', () => {
  it('orders the cards as designed', () => {
    const html = detail(W, { rawAnalysisOpen: false });
    const order = ['Race summary', 'aria-label="Start"', 'Section analysis', 'Free speed', 'aria-label="Laps"', 'Did I fade?', 'All sections', 'Power curve', 'Raw analysis'];
    const at = order.map((k) => html.indexOf(k));
    expect(at.every((i) => i >= 0)).toBe(true);
    expect([...at].sort((a, b) => a - b)).toEqual(at);
  });
  it('builds nothing for a non-race', () => {
    expect(buildRaceView({ ...W, kind: 'workout' })).toBeNull();
  });
});

describe('drill-down', () => {
  const ready = { status: 'ready', data: SECTIONS, error: null };
  it('defaults to the section fastest lap and the time-lost mode', () => {
    const d = buildDrill(W, { label: 'C4', fetched: ready });
    expect(d.status).toBe('ready');
    expect(d.mode).toBe('loss');
    expect(d.lap).toBe(5);
    expect(d.lapChips.find((c) => c.best).lap).toBe(5);
  });
  it('colours pieces and keeps within-noise pieces neutral', () => {
    const d = buildDrill(W, { label: 'C4', fetched: ready });
    expect(d.map.paths[5]).toBeTruthy(); // noise bucket
    expect(d.legend.map((l) => l.label)).toContain('grey = within timing noise');
    const eff = buildDrill(W, { label: 'C4', fetched: ready, mode: 'eff' });
    expect(eff.legend).toHaveLength(5);
  });
  it('colours power and flow per second by bucket', () => {
    const p = buildDrill(W, { label: 'C4', fetched: ready, mode: 'power' });
    expect(p.map.paths.filter(Boolean).length).toBeGreaterThan(1);
    expect(p.legend[0].label).toBe('< 100 W');
    expect(buildDrill(W, { label: 'C4', fetched: ready, mode: 'flow' }).legend[4].label).toBe('10+ (tight turn)');
  });
  it('fits the section into the frame with north up', () => {
    const f = sectionFrame([0, 0, 100, 50]);
    expect(f.y(50)).toBeLessThan(f.y(0));
    expect(f.x(0)).toBeLessThan(f.x(100));
  });
  it('lists laps with the smoothest flow highlighted and shows speeds', () => {
    const d = buildDrill(W, { label: 'C5', fetched: ready });
    expect(d.rows).toHaveLength(7);
    expect(d.rows.filter((r) => r.smoothest)).toHaveLength(1);
    expect(d.speeds).toBeTruthy();
  });
  it('falls back to the course map while loading, offline or on error', () => {
    expect(buildDrill(W, { label: 'C4', fetched: undefined, online: false }).status).toBe('offline');
    expect(buildDrill(W, { label: 'C4', fetched: { status: 'loading' } }).status).toBe('loading');
    const err = buildDrill(W, { label: 'C4', fetched: { status: 'error', error: 'boom' } });
    expect(err.status).toBe('error');
    expect(err.courseMap.sectors.filter((s) => !s.dim)).toHaveLength(1);
  });
  it('renders the overlay with the note input and a pinch-zoomable map', async () => {
    const { renderRaceDrill } = await import('../../src/views.js');
    const html = renderRaceDrill(W, { drill: { label: 'C4', mode: 'loss', lap: null }, fetched: ready, online: true, mapView: null, note: {} });
    expect(html).toContain('id="race-section-note"');
    expect(html).toContain('class="cs-map rv-drillmap"');
    expect(html).toContain('data-a="race:note-save" data-label="C4"');
    expect(html).toContain('data-a="race:drill-mode" data-mode="power"');
  });
  it('shows the offline note', async () => {
    const { renderRaceDrill } = await import('../../src/views.js');
    const html = renderRaceDrill(W, { drill: { label: 'C4', mode: 'loss', lap: null }, fetched: undefined, online: false, mapView: null, note: {} });
    expect(html).toContain('needs a connection');
  });
  it('formats ideal-lap clock tenths', () => {
    expect(clockTenths(342.8)).toBe('5:42.8');
    expect(clockTenths(60)).toBe('1:00.0');
  });
});
