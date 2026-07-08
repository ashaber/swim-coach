import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  postWorkout, listWorkouts, postWellness, listWellness, fetchPlan, getAthlete, patchAthlete,
} from '../../src/api.js';

function fakeFetch(body, { ok = true, status = 200 } = {}) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  });
}

describe('postWorkout', () => {
  beforeEach(() => {
    global.fetch = undefined;
  });

  it('POSTs to /api/workouts with the athlete query param, bearer header, and JSON body', async () => {
    const created = { id: 'w1', date: '2026-07-07', sport: 'swim_pool' };
    global.fetch = fakeFetch(created);
    const payload = { date: '2026-07-07', sport: 'swim_pool', distance_m: 3000, duration_min: 60 };

    const result = await postWorkout({
      baseUrl: 'https://api.example.com', token: 'tok123', athlete: 'renee', payload,
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/workouts?athlete=renee');
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer tok123');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual(payload);
    expect(result).toEqual({ ok: true, data: created });
  });

  it('defaults to athlete=renee when not given', async () => {
    global.fetch = fakeFetch({});
    await postWorkout({ baseUrl: 'https://api.example.com', token: 't', payload: {} });
    const [url] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/workouts?athlete=renee');
  });

  it('returns a normalized error on a non-2xx response', async () => {
    global.fetch = fakeFetch({ error: 'bad sport' }, { ok: false, status: 422 });
    const result = await postWorkout({ baseUrl: 'https://api.example.com', token: 't', payload: {} });
    expect(result).toEqual({ ok: false, error: 'bad sport' });
  });

  it('returns a normalized error on a 401', async () => {
    global.fetch = fakeFetch({}, { ok: false, status: 401 });
    const result = await postWorkout({ baseUrl: 'https://api.example.com', token: 'bad', payload: {} });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/token/i);
  });

  it('returns a normalized error when fetch itself rejects (offline)', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    const result = await postWorkout({ baseUrl: 'https://api.example.com', token: 't', payload: {} });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/connection|reach/i);
  });
});

describe('listWorkouts', () => {
  it('GETs /api/workouts with the athlete query param and bearer header, no body', async () => {
    const items = [{ id: 'w1' }, { id: 'w2' }];
    global.fetch = fakeFetch(items);

    const result = await listWorkouts({ baseUrl: 'https://api.example.com', token: 'tok', athlete: 'renee' });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/workouts?athlete=renee');
    expect(init.method === 'GET' || init.method === undefined).toBe(true);
    expect(init.body).toBeUndefined();
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(result).toEqual({ ok: true, data: items });
  });
});

describe('postWellness', () => {
  it('POSTs to /api/wellness with the athlete query param, bearer header, and JSON body', async () => {
    const created = { id: 'we1', date: '2026-07-07', sleep_quality: 4 };
    global.fetch = fakeFetch(created);
    const payload = { date: '2026-07-07', sleep_quality: 4, sleep_hours: 7.5, stress: 2, soreness: 2, motivation: 4 };

    const result = await postWellness({
      baseUrl: 'https://api.example.com', token: 'tok123', athlete: 'renee', payload,
    });

    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/wellness?athlete=renee');
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual(payload);
    expect(result).toEqual({ ok: true, data: created });
  });
});

describe('listWellness', () => {
  it('GETs /api/wellness with the athlete query param and bearer header', async () => {
    const items = [{ id: 'we1' }];
    global.fetch = fakeFetch(items);

    const result = await listWellness({ baseUrl: 'https://api.example.com', token: 'tok', athlete: 'renee' });

    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/wellness?athlete=renee');
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(result).toEqual({ ok: true, data: items });
  });
});

describe('fetchPlan', () => {
  it('GETs /api/plan with the athlete query param and bearer header, no body', async () => {
    const plan = { slug: 'andrew', athlete: { name: 'Andrew' }, events: [], weeks: [], macro: { blocks: [] } };
    global.fetch = fakeFetch(plan);

    const result = await fetchPlan({ baseUrl: 'https://api.example.com', token: 'tok', athlete: 'andrew' });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/plan?athlete=andrew');
    expect(init.method === 'GET' || init.method === undefined).toBe(true);
    expect(init.body).toBeUndefined();
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(result).toEqual({ ok: true, data: plan });
  });

  it('targets whichever athlete slug it is given, not a hardcoded default', async () => {
    global.fetch = fakeFetch({});
    await fetchPlan({ baseUrl: 'https://api.example.com', token: 'tok', athlete: 'renee' });
    const [url] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/plan?athlete=renee');
  });

  it('returns a normalized error on a non-2xx response', async () => {
    global.fetch = fakeFetch({ error: 'no such athlete' }, { ok: false, status: 404 });
    const result = await fetchPlan({ baseUrl: 'https://api.example.com', token: 'tok', athlete: 'ghost' });
    expect(result).toEqual({ ok: false, error: 'no such athlete' });
  });
});

describe('getAthlete', () => {
  it('GETs /api/athlete with the athlete query param and bearer header, no body', async () => {
    const profile = { slug: 'andrew', name: 'Andrew', css_pace_s_per_100m: 100.0 };
    global.fetch = fakeFetch(profile);

    const result = await getAthlete({ baseUrl: 'https://api.example.com', token: 'tok', athlete: 'andrew' });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/athlete?athlete=andrew');
    expect(init.method === 'GET' || init.method === undefined).toBe(true);
    expect(init.body).toBeUndefined();
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(result).toEqual({ ok: true, data: profile });
  });

  it('returns a normalized error on a non-2xx response', async () => {
    global.fetch = fakeFetch({ error: 'no such athlete' }, { ok: false, status: 404 });
    const result = await getAthlete({ baseUrl: 'https://api.example.com', token: 'tok', athlete: 'ghost' });
    expect(result).toEqual({ ok: false, error: 'no such athlete' });
  });
});

describe('patchAthlete', () => {
  it('PATCHes /api/athlete with the athlete query param, bearer header, and JSON body', async () => {
    const updated = { slug: 'andrew', name: 'Andrew Shaber' };
    global.fetch = fakeFetch(updated);
    const payload = { name: 'Andrew Shaber' };

    const result = await patchAthlete({
      baseUrl: 'https://api.example.com', token: 'tok123', athlete: 'andrew', payload,
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/athlete?athlete=andrew');
    expect(init.method).toBe('PATCH');
    expect(init.headers.Authorization).toBe('Bearer tok123');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual(payload);
    expect(result).toEqual({ ok: true, data: updated });
  });

  it('returns a normalized error on a 422', async () => {
    global.fetch = fakeFetch({ error: 'invalid sex' }, { ok: false, status: 422 });
    const result = await patchAthlete({
      baseUrl: 'https://api.example.com', token: 'tok', athlete: 'andrew', payload: {},
    });
    expect(result).toEqual({ ok: false, error: 'invalid sex' });
  });
});
