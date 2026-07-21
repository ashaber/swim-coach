import { describe, it, expect, beforeEach } from 'vitest';
import {
  loadIdentity, saveIdentity, clearIdentity, currentIdentity,
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
    const identity = { name: 'Andrew', athlete: 'andrew', role: 'coach' };
    saveIdentity(identity, storage);
    expect(loadIdentity(storage)).toEqual(identity);
    expect(currentIdentity(storage)).toEqual(identity);
  });

  it('clears a saved identity', () => {
    saveIdentity({ name: 'Andrew', athlete: 'andrew', role: 'coach' }, storage);
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

  it('defaults name to empty string and role to athlete when either is missing', () => {
    storage.setItem('swimcoach_identity', JSON.stringify({ athlete: 'renee' }));
    expect(loadIdentity(storage)).toEqual({ name: '', athlete: 'renee', role: 'athlete' });
  });
});
