// In-progress text of the chat composers that are not conversation.js threads (those keep
// `draft` on their own slice). render() rebuilds the whole DOM, so every composer textarea is
// re-emitted from here; without it each background render (plan/history/conversation loads at
// launch) wiped what the athlete was typing. Keyed by a per-thread key (`data-draft-key`).

const drafts = new Map();

export function getDraft(key) {
  return drafts.get(key) || '';
}

export function setDraft(key, value) {
  if (value) drafts.set(key, value);
  else drafts.delete(key);
}

export function clearDraft(key) {
  drafts.delete(key);
}
