import { describe, it, expect, beforeEach } from 'vitest';
import {
  loadIdentity, saveIdentity, clearIdentity, currentIdentity, mergeMeIntoIdentity,
} from '../../src/identity.js';

// Identity resolution (email -> athlete/role) is no longer client-side --
// the backend's POST /api/auth/google does that now (see
// backend/app/routes/auth.py and api.js's exchangeGoogleToken, tested in
// tests/unit/api.test.js's `exchangeGoogleToken` describe block). This file
// only covers the pure localStorage persistence identity.js still owns:
// restoring a previously-resolved {name, athlete, role} across page loads
// without a network round trip.

function makeFakeStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  };
}

describe('identity persistence', () => {
  let storage;
  beforeEach(() => {
    storage = makeFakeStorage();
  });

  it('returns null when nothing is stored', () => {
    expect(loadIdentity(storage)).toBeNull();
    expect(currentIdentity(storage)).toBeNull();
  });

  it('round-trips a saved identity', () => {
    const identity = {
      name: 'Andrew', athlete: 'andrew', role: 'coach', coachFor: ['renee'], isLibraryAdmin: true,
    };
    saveIdentity(identity, storage);
    expect(loadIdentity(storage)).toEqual(identity);
    expect(currentIdentity(storage)).toEqual(identity);
  });

  it('clears a saved identity', () => {
    saveIdentity({
      name: 'Andrew', athlete: 'andrew', role: 'coach', coachFor: [], isLibraryAdmin: false,
    }, storage);
    clearIdentity(storage);
    expect(loadIdentity(storage)).toBeNull();
  });

  it('recovers from corrupt stored JSON', () => {
    storage.setItem('swimcoach_identity', '{{{not json');
    expect(loadIdentity(storage)).toBeNull();
  });

  it('recovers from a stored value missing the required athlete field', () => {
    storage.setItem('swimcoach_identity', JSON.stringify({ name: 'Andrew', role: 'athlete' }));
    expect(loadIdentity(storage)).toBeNull();
  });

  it('defaults name to empty string, role to athlete, and coachFor to [] when missing', () => {
    storage.setItem('swimcoach_identity', JSON.stringify({ athlete: 'renee' }));
    expect(loadIdentity(storage)).toEqual({
      name: '', athlete: 'renee', role: 'athlete', coachFor: [], isLibraryAdmin: false,
    });
  });

  it('defaults coachFor to [] for an identity persisted before this field existed', () => {
    storage.setItem('swimcoach_identity', JSON.stringify({ name: 'Renee', athlete: 'renee', role: 'athlete' }));
    expect(loadIdentity(storage)).toEqual({
      name: 'Renee', athlete: 'renee', role: 'athlete', coachFor: [], isLibraryAdmin: false,
    });
  });

  it('defaults isLibraryAdmin to false for an identity persisted before this field existed', () => {
    storage.setItem(
      'swimcoach_identity',
      JSON.stringify({ name: 'Renee', athlete: 'renee', role: 'athlete', coachFor: [] }),
    );
    expect(loadIdentity(storage).isLibraryAdmin).toBe(false);
  });

  it('round-trips isLibraryAdmin true', () => {
    storage.setItem(
      'swimcoach_identity',
      JSON.stringify({
        name: 'Andrew', athlete: 'andrew', role: 'athlete', coachFor: [], isLibraryAdmin: true,
      }),
    );
    expect(loadIdentity(storage).isLibraryAdmin).toBe(true);
  });
});

// web/resources-hotfix fix 1: app-start refresh of isLibraryAdmin/coachFor
// from a fresh GET /api/me, for a saved identity from before those fields
// (or their current value) existed/changed server-side.
describe('mergeMeIntoIdentity', () => {
  const identity = {
    name: 'Renee', athlete: 'renee', role: 'athlete', coachFor: [], isLibraryAdmin: false,
  };

  it('promotes isLibraryAdmin and coachFor from a successful /api/me response', () => {
    const meResult = { ok: true, data: { is_library_admin: true, coach_for: ['andrew'] } };
    expect(mergeMeIntoIdentity(identity, meResult)).toEqual({
      ...identity, isLibraryAdmin: true, coachFor: ['andrew'],
    });
  });

  it('demotes isLibraryAdmin when /api/me now reports false', () => {
    const admin = { ...identity, isLibraryAdmin: true };
    const meResult = { ok: true, data: { is_library_admin: false, coach_for: [] } };
    expect(mergeMeIntoIdentity(admin, meResult).isLibraryAdmin).toBe(false);
  });

  it('keeps the saved identity unchanged when the /api/me call failed', () => {
    const meResult = { ok: false, error: 'network error', status: 0 };
    expect(mergeMeIntoIdentity(identity, meResult)).toBe(identity);
  });

  it('keeps the saved identity unchanged when there is no identity to merge into', () => {
    expect(mergeMeIntoIdentity(null, { ok: true, data: { is_library_admin: true } })).toBeNull();
  });

  it('leaves fields as-is when the response omits them', () => {
    const meResult = { ok: true, data: {} };
    expect(mergeMeIntoIdentity(identity, meResult)).toEqual(identity);
  });
});
