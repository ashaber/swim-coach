// Pure formatting/derivation helpers for rendering workout history (Slice 2:
// the Log tab's history section). Kept DOM-free so it's cheaply
// unit-testable without a jsdom environment -- see tests/unit/workouts.test.js.
// Mirrors plan.js's separation of pure logic from views.js's render functions.

import { formatDuration, formatPace } from './plan.js';

/** How many most-recent workouts the Log tab's history section shows. */
export const HISTORY_DISPLAY_CAP = 20;

const SPORT_LABELS = {
  swim_pool: 'Pool swim',
  swim_ow: 'Open water swim',
  strength: 'Strength',
  recovery: 'Recovery',
  cross_train: 'Cross-train',
};

const SOURCE_BADGES = {
  fit: 'fit',
  tcx: 'tcx',
  csv: 'csv',
  coach_text: 'coach',
};

export function sportLabel(sport) {
  return SPORT_LABELS[sport] || sport;
}

/** null for manual entries (no badge needed) -- a short label for anything
 * imported (.fit/.tcx/.csv or pasted pool-coach text). */
export function sourceBadge(source) {
  if (!source || source === 'manual') return null;
  return SOURCE_BADGES[source] || source;
}

/** "3200" -> "3.2 km" (one decimal place), "800" -> "800 m". Distinct from
 * plan.js's formatDistance (which always renders bare meters -- appropriate
 * for planned-session distances, which stay in the low thousands) since
 * logged history can span a single 400m recovery swim up to an 18km ultra
 * swim, where km reads far better once >= 1000m. */
export function formatWorkoutDistance(distanceM) {
  if (distanceM === null || distanceM === undefined) return null;
  if (distanceM >= 1000) {
    const km = Math.round(distanceM / 100) / 10;
    return `${km.toLocaleString('en-US', { maximumFractionDigits: 1 })} km`;
  }
  return `${Math.round(distanceM).toLocaleString('en-US')} m`;
}

/** Newest-first by ISO date string (works for both bare YYYY-MM-DD and full
 * timestamps, since ISO 8601 sorts lexicographically). Returns a new array. */
export function sortWorkoutsNewestFirst(workouts) {
  return [...workouts].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
}

/** "+6.2% ⚠" / "-13.8%" -- the ⚠ only appears at/above +5% (the threshold
 * where cardiac drift starts to flag aerobic-decoupling concern; Coach
 * judgment, not sourced from a specific library citation). */
export function formatDrift(pct) {
  if (pct === null || pct === undefined) return null;
  const rounded = pct.toFixed(1);
  const signed = pct >= 0 ? `+${rounded}%` : `${rounded}%`;
  return `drift ${signed}${pct >= 5 ? ' ⚠' : ''}`;
}

const SPLIT_LABELS = { negative: 'negative split', even: 'even split', positive: 'positive split' };

/** "negative split (1:32 -> 1:28)" -- falls back to just the label text if
 * the half-paces aren't both present. */
export function formatSplit(analytics) {
  const splitLabel = analytics?.split_label;
  if (!splitLabel) return null;
  const labelText = SPLIT_LABELS[splitLabel] || splitLabel;
  const firstPace = formatPace(analytics.first_half_pace_s_per_100m);
  const secondPace = formatPace(analytics.second_half_pace_s_per_100m);
  if (firstPace && secondPace) return `${labelText} (${firstPace} → ${secondPace})`;
  return labelText;
}

/** "3 pauses · 12 min stopped" -- omitted entirely when there were no pauses. */
export function formatPauses(analytics) {
  const count = analytics?.pause_count;
  if (!count) return null;
  const totalMin = analytics.pause_total_min;
  const stoppedText = totalMin !== null && totalMin !== undefined ? ` · ${formatDuration(totalMin)} stopped` : '';
  return `${count} pause${count === 1 ? '' : 's'}${stoppedText}`;
}

/** "SWOLF 41.0->43.4 (+6.0%)" -- both quarter SWOLF values are required;
 * the degradation percentage is appended only when present. */
export function formatSwolf(analytics) {
  const first = analytics?.swolf_first_quarter;
  const last = analytics?.swolf_last_quarter;
  if (first === null || first === undefined || last === null || last === undefined) return null;
  const pct = analytics.swolf_degradation_pct;
  const pctText = pct !== null && pct !== undefined ? ` (${pct >= 0 ? '+' : ''}${pct.toFixed(1)}%)` : '';
  return `SWOLF ${first.toFixed(1)}→${last.toFixed(1)}${pctText}`;
}

/** "5 h moving of 5 h 20 min" -- only when moving and elapsed time actually
 * diverge by a meaningful margin (>= 1 min; otherwise it's noise, and
 * usually redundant with the pause summary above it anyway). */
export function formatMovingVsElapsed(analytics) {
  const moving = analytics?.moving_min;
  const elapsed = analytics?.elapsed_min;
  if (moving === null || moving === undefined || elapsed === null || elapsed === undefined) return null;
  if (Math.abs(elapsed - moving) < 1) return null;
  return `${formatDuration(moving)} moving of ${formatDuration(elapsed)}`;
}

/** Assembles the full compact analytics line for one workout, skipping any
 * null/absent sub-field cleanly. Returns null both when `analytics` itself
 * is absent and when it's present but every field on it is null (an older
 * manual workout, or a very short one with nothing worth summarizing). */
export function formatAnalyticsLine(analytics) {
  if (!analytics) return null;
  const parts = [
    formatDrift(analytics.cardiac_drift_pct),
    formatSplit(analytics),
    formatPauses(analytics),
    formatSwolf(analytics),
    formatMovingVsElapsed(analytics),
  ].filter(Boolean);
  return parts.length > 0 ? parts.join(' · ') : null;
}
