import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  postWorkout, listWorkouts, postWellness, listWellness, fetchPlan, getAthlete, patchAthlete,
  postFeedback, listFeedback, uploadWorkoutFile, exchangeGoogleToken, RequestAccessError, logout,
  onboard, OnboardForbiddenError, OnboardConflictError,
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
    expect(result).toEqual({ ok: false, error: 'bad sport', status: 422 });
  });

  it('returns a normalized error (with status 401) on a 401 -- main.js uses this to treat the session as expired', async () => {
    global.fetch = fakeFetch({}, { ok: false, status: 401 });
    const result = await postWorkout({ baseUrl: 'https://api.example.com', token: 'bad', payload: {} });
    expect(result.ok).toBe(false);
    expect(result.status).toBe(401);
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
    expect(result).toEqual({ ok: false, error: 'no such athlete', status: 404 });
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
    expect(result).toEqual({ ok: false, error: 'no such athlete', status: 404 });
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
    expect(result).toEqual({ ok: false, error: 'invalid sex', status: 422 });
  });
});

describe('postFeedback', () => {
  it('POSTs to /api/feedback with the athlete query param, bearer header, and JSON body', async () => {
    const created = { id: 'f1', type: 'feature_request', body: 'add a pace calculator' };
    global.fetch = fakeFetch(created);
    const payload = { type: 'feature_request', body: 'add a pace calculator' };

    const result = await postFeedback({
      baseUrl: 'https://api.example.com', token: 'tok123', athlete: 'renee', payload,
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/feedback?athlete=renee');
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer tok123');
    expect(JSON.parse(init.body)).toEqual(payload);
    expect(result).toEqual({ ok: true, data: created });
  });

  it('returns a normalized error on a non-2xx response', async () => {
    global.fetch = fakeFetch({ error: 'research_question is coach-only' }, { ok: false, status: 422 });
    const result = await postFeedback({
      baseUrl: 'https://api.example.com', token: 't', athlete: 'renee', payload: {},
    });
    expect(result).toEqual({ ok: false, error: 'research_question is coach-only', status: 422 });
  });
});

describe('uploadWorkoutFile', () => {
  it('POSTs multipart FormData to /api/workouts/ingest with the athlete query param and bearer header, no Content-Type override', async () => {
    const draft = {
      date: '2026-03-14', sport: 'swim_pool', source: 'fit', distance_m: 1623, duration_min: 54, warnings: [],
    };
    global.fetch = fakeFetch(draft);
    const file = new File(['fake fit bytes'], 'workout.fit', { type: 'application/octet-stream' });

    const result = await uploadWorkoutFile({
      baseUrl: 'https://api.example.com', token: 'tok123', athlete: 'renee', file,
    });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/workouts/ingest?athlete=renee');
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer tok123');
    // No explicit Content-Type -- fetch must set the multipart boundary itself.
    expect(init.headers['Content-Type']).toBeUndefined();
    expect(init.body).toBeInstanceOf(FormData);
    expect(init.body.get('file')).toBe(file);
    expect(result).toEqual({ ok: true, data: draft });
  });

  it('defaults to athlete=renee when not given', async () => {
    global.fetch = fakeFetch({});
    const file = new File(['x'], 'a.csv', { type: 'text/csv' });
    await uploadWorkoutFile({ baseUrl: 'https://api.example.com', token: 't', file });
    const [url] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/workouts/ingest?athlete=renee');
  });

  it('returns a normalized error on a 415 unsupported-type response', async () => {
    global.fetch = fakeFetch({ error: "unsupported file extension '.gpx'" }, { ok: false, status: 415 });
    const file = new File(['x'], 'a.gpx', { type: 'application/octet-stream' });
    const result = await uploadWorkoutFile({ baseUrl: 'https://api.example.com', token: 't', file });
    expect(result).toEqual({ ok: false, error: "unsupported file extension '.gpx'", status: 415 });
  });

  it('returns a normalized error on a 413 too-large response', async () => {
    global.fetch = fakeFetch({ error: 'file too large; max 10 MB' }, { ok: false, status: 413 });
    const file = new File(['x'], 'huge.fit', { type: 'application/octet-stream' });
    const result = await uploadWorkoutFile({ baseUrl: 'https://api.example.com', token: 't', file });
    expect(result).toEqual({ ok: false, error: 'file too large; max 10 MB', status: 413 });
  });

  it('returns a normalized error on a 422 parse-failure response', async () => {
    global.fetch = fakeFetch({ error: 'could not parse corrupt.fit: bad header' }, { ok: false, status: 422 });
    const file = new File(['garbage'], 'corrupt.fit', { type: 'application/octet-stream' });
    const result = await uploadWorkoutFile({ baseUrl: 'https://api.example.com', token: 't', file });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/could not parse/);
  });

  it('returns a normalized error when fetch itself rejects (offline)', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    const file = new File(['x'], 'a.fit', { type: 'application/octet-stream' });
    const result = await uploadWorkoutFile({ baseUrl: 'https://api.example.com', token: 't', file });
    expect(result.ok).toBe(false);
    expect(result.error).toMatch(/connection|reach/i);
  });
});

describe('listFeedback', () => {
  it('GETs /api/feedback with the athlete query param and bearer header, no body', async () => {
    const items = [{ id: 'f1' }, { id: 'f2' }];
    global.fetch = fakeFetch(items);

    const result = await listFeedback({ baseUrl: 'https://api.example.com', token: 'tok', athlete: 'renee' });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/feedback?athlete=renee');
    expect(init.method === 'GET' || init.method === undefined).toBe(true);
    expect(init.body).toBeUndefined();
    expect(init.headers.Authorization).toBe('Bearer tok');
    expect(result).toEqual({ ok: true, data: items });
  });
});

describe('exchangeGoogleToken', () => {
  it('POSTs the Google ID token to /api/auth/google and returns the minted session JSON', async () => {
    const session = {
      token: 'session-abc', athlete: 'renee', name: 'Renee', role: 'athlete', expires_at: '2026-08-01T00:00:00Z',
    };
    global.fetch = fakeFetch(session);

    const result = await exchangeGoogleToken({ baseUrl: 'https://api.example.com', idToken: 'google-id-token' });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/auth/google');
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual({ id_token: 'google-id-token' });
    expect(result).toEqual(session);
  });

  it('throws a RequestAccessError on a 403 (email not allowlisted)', async () => {
    global.fetch = fakeFetch({ error: 'request access' }, { ok: false, status: 403 });
    await expect(exchangeGoogleToken({ baseUrl: 'https://api.example.com', idToken: 'x' }))
      .rejects.toBeInstanceOf(RequestAccessError);
  });

  it('throws a generic error on a 401 (bad/expired Google ID token)', async () => {
    global.fetch = fakeFetch({ error: 'invalid Google ID token' }, { ok: false, status: 401 });
    await expect(exchangeGoogleToken({ baseUrl: 'https://api.example.com', idToken: 'x' }))
      .rejects.toThrow(/invalid google id token/i);
  });

  it('throws a generic error when fetch itself rejects (offline)', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(exchangeGoogleToken({ baseUrl: 'https://api.example.com', idToken: 'x' }))
      .rejects.toThrow(/connection|reach/i);
  });
});

describe('onboard', () => {
  it('POSTs the onboarding payload to /api/onboard with the onboarding bearer token, returns the athlete-bound session JSON', async () => {
    const session = {
      token: 'athlete-session-xyz', athlete: 'jamie', name: 'Jamie', role: 'athlete', expires_at: '2026-08-01T00:00:00Z',
    };
    global.fetch = fakeFetch(session);
    const payload = { name: 'Jamie', css_pace_s_per_100m: 95, events: [{ name: 'Big Swim', event_date: '2027-06-01', distance_m: 33300 }] };

    const result = await onboard({ baseUrl: 'https://api.example.com', token: 'onboard-tok', payload });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/onboard');
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer onboard-tok');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual(payload);
    expect(result).toEqual(session);
  });

  it('throws OnboardForbiddenError on a 403 (dead/invalid onboarding session)', async () => {
    global.fetch = fakeFetch({ error: 'invite no longer valid' }, { ok: false, status: 403 });
    await expect(onboard({ baseUrl: 'https://api.example.com', token: 't', payload: {} }))
      .rejects.toBeInstanceOf(OnboardForbiddenError);
  });

  it('throws OnboardConflictError on a 409 (slug/invite already used)', async () => {
    global.fetch = fakeFetch({ error: "athlete slug 'jamie' already exists" }, { ok: false, status: 409 });
    await expect(onboard({ baseUrl: 'https://api.example.com', token: 't', payload: {} }))
      .rejects.toBeInstanceOf(OnboardConflictError);
  });

  it('throws a generic error carrying the backend message on a 422 (bad input)', async () => {
    global.fetch = fakeFetch({ error: 'insufficient runway before the target event' }, { ok: false, status: 422 });
    await expect(onboard({ baseUrl: 'https://api.example.com', token: 't', payload: {} }))
      .rejects.toThrow(/insufficient runway/i);
  });

  it('every thrown error carries the response status for main.js to single out a 401', async () => {
    global.fetch = fakeFetch({ error: 'nope' }, { ok: false, status: 403 });
    try {
      await onboard({ baseUrl: 'https://api.example.com', token: 't', payload: {} });
      throw new Error('expected onboard() to throw');
    } catch (err) {
      expect(err.status).toBe(403);
    }
  });

  it('throws a generic error when fetch itself rejects (offline)', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(onboard({ baseUrl: 'https://api.example.com', token: 't', payload: {} }))
      .rejects.toThrow(/connection|reach/i);
  });
});

describe('logout', () => {
  it('POSTs to /api/auth/logout with the bearer header', async () => {
    global.fetch = fakeFetch({ ok: true });

    await logout({ baseUrl: 'https://api.example.com', token: 'session-abc' });

    expect(global.fetch).toHaveBeenCalledTimes(1);
    const [url, init] = global.fetch.mock.calls[0];
    expect(url).toBe('https://api.example.com/api/auth/logout');
    expect(init.method).toBe('POST');
    expect(init.headers.Authorization).toBe('Bearer session-abc');
  });

  it('never throws, even when the request fails -- sign-out must proceed locally regardless', async () => {
    global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));
    await expect(logout({ baseUrl: 'https://api.example.com', token: 't' })).resolves.toBeUndefined();
  });

  it('never throws on a non-2xx response either', async () => {
    global.fetch = fakeFetch({ error: 'nope' }, { ok: false, status: 500 });
    await expect(logout({ baseUrl: 'https://api.example.com', token: 't' })).resolves.toBeUndefined();
  });
});
