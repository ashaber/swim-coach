import { describe, it, expect, beforeEach } from 'vitest';
import {
  sortLibraryFiles, isNewFile, formatAddedLabel, loadLibrarySort, saveLibrarySort, DEFAULT_LIBRARY_SORT,
} from '../../src/librarySort.js';

const c = (file, added, review_state = 'reviewed') => ({ file, added, review_state });

const CARDS = [
  c('03-a.md', '2026-07-05'),
  c('38-b.md', '2026-10-10', 'unreviewed'),
  c('39-c.md', '2026-10-11', 'unreviewed'),
  c('40-d.md', '2026-10-11', 'unreviewed'),
  c('41-e.md', '2026-10-12', 'unreviewed'),
  c('99-nodate.md', null),
  c('41-e.md', '2026-10-12', 'unreviewed'),
];

describe('sortLibraryFiles', () => {
  it('recent: newest first, ties broken by higher filename, missing dates last', () => {
    expect(sortLibraryFiles(CARDS, 'recent')).toEqual(
      ['41-e.md', '40-d.md', '39-c.md', '38-b.md', '03-a.md', '99-nodate.md'],
    );
  });

  it('library: keeps first-seen (API) order, deduping files', () => {
    expect(sortLibraryFiles(CARDS, 'library')).toEqual(
      ['03-a.md', '38-b.md', '39-c.md', '40-d.md', '41-e.md', '99-nodate.md'],
    );
  });

  it('needs_review: files with unreviewed/flagged cards first, then newest', () => {
    const cards = [
      c('03-a.md', '2026-07-05'),
      c('04-b.md', '2026-08-01', 'unreviewed'),
      c('05-c.md', '2026-09-01', 'accepted'),
      c('06-d.md', '2026-07-20', 'flagged'),
    ];
    expect(sortLibraryFiles(cards, 'needs_review')).toEqual(
      ['04-b.md', '06-d.md', '05-c.md', '03-a.md'],
    );
  });

  it('a file takes its date from any card that has one', () => {
    const cards = [c('01-x.md', null), c('01-x.md', '2026-10-01'), c('02-y.md', '2026-09-01')];
    expect(sortLibraryFiles(cards, 'recent')).toEqual(['01-x.md', '02-y.md']);
  });

  it('unknown mode falls back to recent', () => {
    expect(sortLibraryFiles(CARDS, 'bogus')[0]).toBe('41-e.md');
  });
});

describe('isNewFile', () => {
  const now = new Date('2026-10-13T10:00:00');
  it('true within 14 days, false after, false when missing', () => {
    expect(isNewFile('2026-10-12', now)).toBe(true);
    expect(isNewFile('2026-09-29', now)).toBe(true);
    expect(isNewFile('2026-09-28', now)).toBe(false);
    expect(isNewFile(null, now)).toBe(false);
    expect(isNewFile('garbage', now)).toBe(false);
  });
});

describe('formatAddedLabel', () => {
  it('formats as "added Oct 12" and is empty when missing', () => {
    expect(formatAddedLabel('2026-10-12')).toBe('added Oct 12');
    expect(formatAddedLabel('2026-07-05')).toBe('added Jul 5');
    expect(formatAddedLabel(null)).toBe('');
  });
});

function fakeStorage() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v) };
}

describe('sort persistence', () => {
  let storage;
  beforeEach(() => { storage = fakeStorage(); });
  it('defaults to recent, round-trips, ignores junk', () => {
    expect(loadLibrarySort(storage)).toBe(DEFAULT_LIBRARY_SORT);
    expect(DEFAULT_LIBRARY_SORT).toBe('recent');
    saveLibrarySort('library', storage);
    expect(loadLibrarySort(storage)).toBe('library');
    storage.setItem('swimcoach_library_sort', 'wat');
    expect(loadLibrarySort(storage)).toBe('recent');
  });
  it('never throws when storage is broken', () => {
    const broken = { getItem() { throw new Error('x'); }, setItem() { throw new Error('x'); } };
    expect(loadLibrarySort(broken)).toBe('recent');
    expect(() => saveLibrarySort('library', broken)).not.toThrow();
  });
});
