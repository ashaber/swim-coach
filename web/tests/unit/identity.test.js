import { describe, it, expect, beforeEach } from 'vitest';
import {
  decodeJwtPayload, resolveIdentity, loadIdentity, saveIdentity, clearIdentity, currentIdentity,
} from '../../src/identity.js';

function makeFakeStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  };
}

function base64url(obj) {
  const json = JSON.stringify(obj);
  return Buffer.from(json, 'utf-8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function fakeIdToken(payload) {
  const header = base64url({ alg: 'RS256', typ: 'JWT' });
  const body = base64url(payload);
  // Signature is never checked by decodeJwtPayload -- any string will do.
  return `${header}.${body}.not-a-real-signature`;
}

describe('decodeJwtPayload', () => {
  it('decodes the payload segment of a sample unsigned token string', () => {
    const token = fakeIdToken({ email: 'andrewshaber@gmail.com', name: 'Andrew', sub: '12345' });
    expect(decodeJwtPayload(token)).toEqual({ email: 'andrewshaber@gmail.com', name: 'Andrew', sub: '12345' });
  });

  it('decodes non-ASCII characters correctly', () => {
    const token = fakeIdToken({ email: 'x@example.com', name: 'Renée' });
    expect(decodeJwtPayload(token)).toEqual({ email: 'x@example.com', name: 'Renée' });
  });

  it('returns null for a non-string input', () => {
    expect(decodeJwtPayload(undefined)).toBeNull();
    expect(decodeJwtPayload(null)).toBeNull();
    expect(decodeJwtPayload(42)).toBeNull();
  });

  it('returns null for a token that does not have 3 segments', () => {
    expect(decodeJwtPayload('not-a-jwt')).toBeNull();
    expect(decodeJwtPayload('only.two')).toBeNull();
  });

  it('returns null for a token whose payload segment is not valid base64/JSON', () => {
    expect(decodeJwtPayload('header.!!!not-base64!!!.sig')).toBeNull();
  });
});

describe('resolveIdentity', () => {
  it('resolves a known email to its mapped athlete + role', () => {
    expect(resolveIdentity('andrewshaber@gmail.com')).toEqual({
      email: 'andrewshaber@gmail.com', athlete: 'andrew', role: 'athlete',
    });
  });

  it('resolves tim (sandbox evaluator) to his own athlete slug', () => {
    expect(resolveIdentity('curry.mtb@gmail.com')).toEqual({
      email: 'curry.mtb@gmail.com', athlete: 'tim', role: 'athlete',
    });
  });

  it('is case-insensitive', () => {
    expect(resolveIdentity('AndrewShaber@Gmail.com')).toEqual({
      email: 'andrewshaber@gmail.com', athlete: 'andrew', role: 'athlete',
    });
  });

  it('trims surrounding whitespace', () => {
    expect(resolveIdentity('  andrewshaber@gmail.com  ')).toEqual({
      email: 'andrewshaber@gmail.com', athlete: 'andrew', role: 'athlete',
    });
  });

  it('returns null for an email not in the map ("not an authorized user")', () => {
    expect(resolveIdentity('someone-else@gmail.com')).toBeNull();
  });

  it('returns null for empty/missing input', () => {
    expect(resolveIdentity('')).toBeNull();
    expect(resolveIdentity(undefined)).toBeNull();
    expect(resolveIdentity(null)).toBeNull();
  });
});

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
    const identity = { email: 'andrewshaber@gmail.com', athlete: 'andrew', role: 'coach' };
    saveIdentity(identity, storage);
    expect(loadIdentity(storage)).toEqual(identity);
    expect(currentIdentity(storage)).toEqual(identity);
  });

  it('clears a saved identity', () => {
    saveIdentity({ email: 'andrewshaber@gmail.com', athlete: 'andrew', role: 'coach' }, storage);
    clearIdentity(storage);
    expect(loadIdentity(storage)).toBeNull();
  });

  it('recovers from corrupt stored JSON', () => {
    storage.setItem('swimcoach_identity', '{{{not json');
    expect(loadIdentity(storage)).toBeNull();
  });

  it('recovers from a stored value missing required fields', () => {
    storage.setItem('swimcoach_identity', JSON.stringify({ athlete: 'andrew' }));
    expect(loadIdentity(storage)).toBeNull();
  });
});
