// Pure form-serialization helpers: turn the raw string values a `<form>`
// collects (via `main.js`'s `data-form`/`data-field` state) into the JSON
// shapes `POST /api/workouts` / `POST /api/wellness` expect (see
// engine/swim_coach/models.py's Workout/Wellness). Kept pure and DOM-free so
// they're cheaply unit-testable without a jsdom environment.

function toNumberOrZero(value) {
  const n = Number(value);
  return Number.isFinite(n) && value !== '' && value !== null && value !== undefined ? n : 0;
}

function toNullableNumber(value) {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function toNullableText(value) {
  const trimmed = (value ?? '').trim();
  return trimmed ? trimmed : null;
}

/** Serializes the Log tab's form state into a `POST /api/workouts` body. */
export function serializeWorkoutForm(form) {
  return {
    date: form.date,
    sport: form.sport,
    distance_m: toNumberOrZero(form.distance_m),
    duration_min: toNumberOrZero(form.duration_min),
    rpe: toNullableNumber(form.rpe),
    notes: toNullableText(form.notes),
  };
}

/** Serializes the Check-in tab's form state into a `POST /api/wellness` body. */
export function serializeWellnessForm(form) {
  return {
    date: form.date,
    sleep_quality: toNumberOrZero(form.sleep_quality),
    sleep_hours: toNumberOrZero(form.sleep_hours),
    stress: toNumberOrZero(form.stress),
    soreness: toNumberOrZero(form.soreness),
    motivation: toNumberOrZero(form.motivation),
    resting_hr: toNullableNumber(form.resting_hr),
    hrv: toNullableNumber(form.hrv),
    notes: toNullableText(form.notes),
  };
}
