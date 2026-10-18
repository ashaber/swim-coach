import { describe, it, expect } from 'vitest';
import { parseRaceStartInput, raceStartInfo } from '../../src/analysis.js';
import { renderWorkoutDetail } from '../../src/views.js';
import { postWorkoutRaceStart } from '../../src/api.js';

describe('parseRaceStartInput', () => {
  it('reads mm:ss, h:mm:ss and plain seconds', () => {
    expect(parseRaceStartInput('47:57')).toBe(2877);
    expect(parseRaceStartInput('1:02:03')).toBe(3723);
    expect(parseRaceStartInput(' 2877 ')).toBe(2877);
  });
  it('refuses anything else', () => {
    for (const bad of ['', 'soon', '12:75', '-5', '1:2:3:4', null, undefined]) {
      expect(parseRaceStartInput(bad)).toBeNull();
    }
  });
});

describe('raceStartInfo', () => {
  it('labels the source from the workout override', () => {
    const pacing = { data: { race_start_s: 2877 } };
    expect(raceStartInfo({ race_start_s: null }, pacing)).toEqual({ seconds: 2877, source: 'detected' });
    expect(raceStartInfo({ race_start_s: 2877 }, pacing)).toEqual({ seconds: 2877, source: 'set' });
    expect(raceStartInfo({}, { data: { race_start_s: null } })).toBeNull();
    expect(raceStartInfo({}, undefined)).toBeNull();
  });
});

const workout = {
  id: 'w1', sport: 'bike', source: 'fit', kind: 'race', date: '2026-10-17', duration_min: 78, race_start_s: null,
};
const pacing = { status: 'ready', error: null, data: { race_start_s: 2877, gps_laps: { laps: [], note: 'none' }, race_phases: { phases: [] } } };

describe('race start control in the race analysis section', () => {
  it('shows the detected start with a Change button for an editable viewer', () => {
    const html = renderWorkoutDetail(workout, { pacing, editable: true });
    expect(html).toContain('Race start: 47:57 (detected)');
    expect(html).toContain('data-a="race-start:edit"');
  });
  it('is read-only for a viewer who cannot edit', () => {
    const html = renderWorkoutDetail(workout, { pacing, editable: false });
    expect(html).toContain('Race start: 47:57');
    expect(html).not.toContain('race-start:edit');
  });
  it('shows an mm:ss input while editing', () => {
    const html = renderWorkoutDetail(workout, { pacing, editable: true, raceStartEdit: { open: true, status: 'idle', error: null } });
    expect(html).toContain('data-a="race-start:input"');
    expect(html).toContain('value="47:57"');
    expect(html).toContain('data-a="race-start:save"');
  });
});

describe('postWorkoutRaceStart', () => {
  it('POSTs race_start to the race-start route', async () => {
    const calls = [];
    globalThis.fetch = async (url, init) => {
      calls.push([url, JSON.parse(init.body)]);
      return new Response(JSON.stringify({ id: 'w1' }), { status: 200, headers: { 'content-type': 'application/json' } });
    };
    const result = await postWorkoutRaceStart({ baseUrl: 'https://api.test', token: 't', athlete: 'andrew', workoutId: 'w1', raceStartS: 2877 });
    expect(result.ok).toBe(true);
    expect(calls[0][0]).toBe('https://api.test/api/workouts/w1/race-start?athlete=andrew');
    expect(calls[0][1]).toEqual({ race_start: 2877 });
  });
});
