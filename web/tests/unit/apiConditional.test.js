import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  listWorkouts, listWellness, fetchPlan, fetchPlanLoad, resetApiCache,
} from '../../src/api.js';

describe('conditional GETs (ETag cache)', () => {
  const args = { baseUrl: 'https://api.example.com', token: 'tok', athlete: 'renee' };

  function etagResponse(body, etag, status = 200) {
    return {
      ok: status === 200,
      status,
      headers: { get: (name) => (name.toLowerCase() === 'etag' ? etag : null) },
      json: async () => body,
    };
  }

  beforeEach(() => {
    resetApiCache();
  });

  it('first request sends no If-None-Match', async () => {
    global.fetch = vi.fn().mockResolvedValue(etagResponse([{ id: 'w1' }], 'W/"a"'));
    await listWorkouts(args);
    expect(global.fetch.mock.calls[0][1].headers['If-None-Match']).toBeUndefined();
  });

  it('replays the remembered ETag and returns the cached data marked notModified on 304', async () => {
    const items = [{ id: 'w1' }];
    global.fetch = vi.fn()
      .mockResolvedValueOnce(etagResponse(items, 'W/"a"'))
      .mockResolvedValueOnce(etagResponse(undefined, 'W/"a"', 304));
    const first = await listWorkouts(args);
    expect(first).toEqual({ ok: true, data: items });
    const second = await listWorkouts(args);
    expect(global.fetch.mock.calls[1][1].headers['If-None-Match']).toBe('W/"a"');
    expect(second).toEqual({ ok: true, data: items, notModified: true });
  });

  it('a changed 200 replaces the cached data and ETag', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce(etagResponse([{ id: 'w1' }], 'W/"a"'))
      .mockResolvedValueOnce(etagResponse([{ id: 'w1' }, { id: 'w2' }], 'W/"b"'))
      .mockResolvedValueOnce(etagResponse(undefined, 'W/"b"', 304));
    await fetchPlan(args);
    const changed = await fetchPlan(args);
    expect(changed.notModified).toBeUndefined();
    expect(changed.data).toHaveLength(2);
    const again = await fetchPlan(args);
    expect(global.fetch.mock.calls[2][1].headers['If-None-Match']).toBe('W/"b"');
    expect(again.data).toHaveLength(2);
  });

  it('keeps ETags separate per endpoint and per athlete', async () => {
    global.fetch = vi.fn().mockResolvedValue(etagResponse({}, 'W/"x"'));
    await fetchPlan(args);
    await fetchPlanLoad(args);
    await fetchPlan({ ...args, athlete: 'tim' });
    for (const call of global.fetch.mock.calls) expect(call[1].headers['If-None-Match']).toBeUndefined();
  });

  it('dedupes identical in-flight requests into one fetch', async () => {
    let release;
    global.fetch = vi.fn().mockReturnValue(new Promise((resolve) => { release = resolve; }));
    const a = listWorkouts(args);
    const b = listWorkouts(args);
    release(etagResponse([{ id: 'w1' }], 'W/"a"'));
    expect(await a).toEqual(await b);
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  it('a failed request is not cached and the next one is unconditional', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: false, status: 500, headers: { get: () => null }, json: async () => ({ error: 'boom' }),
      })
      .mockResolvedValueOnce(etagResponse([], 'W/"a"'));
    expect((await listWorkouts(args)).ok).toBe(false);
    await listWorkouts(args);
    expect(global.fetch.mock.calls[1][1].headers['If-None-Match']).toBeUndefined();
  });

  it('a 304 with nothing cached is retried unconditionally', async () => {
    global.fetch = vi.fn()
      .mockResolvedValueOnce(etagResponse(undefined, 'W/"a"', 304))
      .mockResolvedValueOnce(etagResponse([{ id: 'w1' }], 'W/"a"'));
    const result = await listWorkouts(args);
    expect(result).toEqual({ ok: true, data: [{ id: 'w1' }] });
    expect(global.fetch).toHaveBeenCalledTimes(2);
  });

  it('only the polled reads are conditional', async () => {
    global.fetch = vi.fn().mockResolvedValue(etagResponse([], 'W/"a"'));
    await listWellness(args);
    await listWellness(args);
    expect(global.fetch.mock.calls[1][1].headers['If-None-Match']).toBeUndefined();
  });
});
