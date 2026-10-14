// Resources tab sort for the research library ("Recently added" etc.).
// Pure logic, unit-tested directly; views.js/main.js only wire it up.
// `added` (YYYY-MM-DD) comes from each card file's top-level `added:` key via
// GET /api/library/cards -- see library/review-cards/*.yaml.

export const LIBRARY_SORTS = [
  { id: 'recent', label: 'Recently added' },
  { id: 'library', label: 'Library order' },
  { id: 'needs_review', label: 'Needs review' },
];
export const DEFAULT_LIBRARY_SORT = 'recent';
export const NEW_FILE_DAYS = 14;

const STORAGE_KEY = 'swimcoach_library_sort';
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DATE_RE = /^(\d{4})-(\d{2})-(\d{2})/;

export function loadLibrarySort(storage = localStorage) {
  try {
    const v = storage.getItem(STORAGE_KEY);
    return LIBRARY_SORTS.some((s) => s.id === v) ? v : DEFAULT_LIBRARY_SORT;
  } catch {
    return DEFAULT_LIBRARY_SORT;
  }
}

export function saveLibrarySort(id, storage = localStorage) {
  try {
    storage.setItem(STORAGE_KEY, id);
  } catch {
    // storage unavailable (private window etc.) -- the sort just won't persist
  }
}

function summarizeFiles(cards) {
  const files = new Map();
  (cards || []).forEach((card, index) => {
    let f = files.get(card.file);
    if (!f) {
      f = { file: card.file, index, added: null, needsReview: false };
      files.set(card.file, f);
    }
    if (card.added && (!f.added || card.added > f.added)) f.added = card.added;
    if (card.review_state === 'unreviewed' || card.review_state === 'flagged') f.needsReview = true;
  });
  return [...files.values()];
}

// Newest first; ties -> higher filename (later library numbers are newer);
// a file with no date sorts after every dated one.
function byRecent(a, b) {
  if (a.added !== b.added) {
    if (!a.added) return 1;
    if (!b.added) return -1;
    return a.added < b.added ? 1 : -1;
  }
  if (a.file === b.file) return 0;
  return a.file < b.file ? 1 : -1;
}

/** Distinct file names in display order for `mode`. */
export function sortLibraryFiles(cards, mode) {
  const files = summarizeFiles(cards);
  if (mode === 'library') {
    files.sort((a, b) => a.index - b.index);
  } else if (mode === 'needs_review') {
    files.sort((a, b) => (a.needsReview === b.needsReview ? byRecent(a, b) : (a.needsReview ? -1 : 1)));
  } else {
    files.sort(byRecent);
  }
  return files.map((f) => f.file);
}

/** The newest `added` among one file's cards (or null). */
export function fileAddedDate(cards, file) {
  return summarizeFiles((cards || []).filter((c) => c.file === file))[0]?.added ?? null;
}

export function isNewFile(added, now = new Date()) {
  const m = DATE_RE.exec(added || '');
  if (!m) return false;
  const addedDay = new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]));
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const days = Math.round((today - addedDay) / 86400000);
  return days >= 0 && days <= NEW_FILE_DAYS;
}

export function formatAddedLabel(added) {
  const m = DATE_RE.exec(added || '');
  if (!m) return '';
  return `added ${MONTHS[Number(m[2]) - 1]} ${Number(m[3])}`;
}
