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

// --- Profile edit form (Settings tab) ---------------------------------------
// Pure unit-conversion + (de)serialization helpers for the self-service
// profile-edit form (GET/PATCH /api/athlete -- see engine/swim_coach/models.py's
// Athlete). Kept US-friendly at the UI layer (ft/in, lb, mm:ss pace) while the
// API/model store cm/kg/seconds -- see backend/app/routes/athlete.py.

const CM_PER_INCH = 2.54;
const KG_PER_LB = 0.45359237;

function toNumberOrNull(value) {
  if (value === '' || value === null || value === undefined) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/** Parses a CSS-pace input given as "mm:ss[.f]" or a plain-seconds string
 * into seconds (float). Returns null for blank/unparseable input rather than
 * NaN -- callers (serializeProfileForm) omit the field entirely on null
 * instead of sending garbage to the API. */
export function parsePaceToSeconds(value) {
  if (value === '' || value === null || value === undefined) return null;
  const trimmed = String(value).trim();
  if (!trimmed) return null;
  if (trimmed.includes(':')) {
    const [minutesPart, secondsPart] = trimmed.split(':');
    const minutes = Number(minutesPart);
    const seconds = Number(secondsPart);
    if (!Number.isFinite(minutes) || !Number.isFinite(seconds)) return null;
    return minutes * 60 + seconds;
  }
  const n = Number(trimmed);
  return Number.isFinite(n) ? n : null;
}

/** Formats seconds (e.g. Athlete.css_pace_s_per_100m) as "m:ss" for display
 * in the pace input -- rounds to the nearest whole second (sub-second
 * precision isn't meaningful for a hand-entered CSS pace). */
export function formatSecondsToPace(seconds) {
  const n = toNumberOrNull(seconds);
  if (n === null) return '';
  const total = Math.round(n);
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  return `${minutes}:${String(secs).padStart(2, '0')}`;
}

/** Converts cm to whole feet + inches (rounded), for a US-friendly height
 * display. Returns blanks for null/undefined (no height set yet). */
export function cmToFeetInches(cm) {
  const n = toNumberOrNull(cm);
  if (n === null) return { feet: '', inches: '' };
  const totalInches = n / CM_PER_INCH;
  let feet = Math.floor(totalInches / 12);
  let inches = Math.round(totalInches - feet * 12);
  if (inches === 12) {
    feet += 1;
    inches = 0;
  }
  return { feet, inches };
}

/** Converts feet + inches back to cm (one decimal place). Returns null if
 * both parts are blank (no height entered) or the total is non-positive. */
export function feetInchesToCm(feet, inches) {
  const f = toNumberOrNull(feet);
  const i = toNumberOrNull(inches);
  if (f === null && i === null) return null;
  const totalInches = (f ?? 0) * 12 + (i ?? 0);
  if (totalInches <= 0) return null;
  return Math.round(totalInches * CM_PER_INCH * 10) / 10;
}

/** Converts kg to lb (one decimal place) for a US-friendly weight display.
 * Returns an empty string for null/undefined (no weight set yet). */
export function kgToLb(kg) {
  const n = toNumberOrNull(kg);
  if (n === null) return '';
  return Math.round((n / KG_PER_LB) * 10) / 10;
}

/** Converts lb back to kg (one decimal place). Returns null for blank or
 * non-positive input rather than 0/NaN. */
export function lbToKg(lb) {
  const n = toNumberOrNull(lb);
  if (n === null || n <= 0) return null;
  return Math.round(n * KG_PER_LB * 10) / 10;
}

// Canonical Mon-Sun order, used both to build a fully-populated day map and
// to serialize it back out in a stable order.
export const POOL_DAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'];

/** Reads an Athlete.pool_schedule (list[str | dict], see models.py) into a
 * {monday: bool, ...} map the checkbox-per-day UI can render directly.
 * Handles both the plain-string shape (["tue", "thu"]) and the richer
 * dict shape ([{day, duration_min, source}, ...]) real profiles use --
 * either way, only the *day* is surfaced here (see dayMapToPoolSchedule's
 * docstring for why per-day duration_min/source isn't round-tripped by this
 * lightweight editor). */
export function poolScheduleToDayMap(poolSchedule) {
  const present = new Set();
  (poolSchedule || []).forEach((entry) => {
    const day = typeof entry === 'string' ? entry : entry?.day;
    if (typeof day === 'string') present.add(day.trim().toLowerCase());
  });
  const map = {};
  POOL_DAYS.forEach((day) => {
    map[day] = present.has(day);
  });
  return map;
}

/** Serializes a day map back to a plain-string pool_schedule, in Mon-Sun
 * order. Deliberately simplified to just day names -- this editor covers
 * the common case ("which days do I swim"); a coach wanting per-day
 * duration_min/source metadata still edits that richer shape via YAML. */
export function dayMapToPoolSchedule(dayMap) {
  return POOL_DAYS.filter((day) => !!(dayMap || {})[day]);
}

/** Builds the profile-edit form's initial state from a GET /api/athlete
 * response, converting cm/kg/seconds to the US-friendly ft/in/lb/mm:ss the
 * form fields show. */
export function profileFormFromAthlete(athlete) {
  const { feet, inches } = cmToFeetInches(athlete.height_cm);
  return {
    name: athlete.name || '',
    dob: athlete.dob || '',
    sex: athlete.sex || '',
    heightFeet: feet === '' ? '' : String(feet),
    heightInches: inches === '' ? '' : String(inches),
    weightLb: (() => {
      const lb = kgToLb(athlete.weight_kg);
      return lb === '' ? '' : String(lb);
    })(),
    cssPace: formatSecondsToPace(athlete.css_pace_s_per_100m),
    poolDays: poolScheduleToDayMap(athlete.pool_schedule),
  };
}

/** Serializes the profile-edit form's state into a partial `PATCH
 * /api/athlete` body -- only the fields that have a value to send.
 * name/dob/sex are simple text/date/select inputs (blank dob/sex are sent
 * as an explicit `null`, i.e. "clear it"; a blank name is never sent, since
 * the API's Athlete.name is a required non-blank field). height/weight/css
 * pace go through unit conversion first and are omitted (not sent as
 * garbage) when unparseable, so an in-progress/invalid edit in one field
 * never blocks saving the others. pool_schedule is always included (see
 * dayMapToPoolSchedule). */
export function serializeProfileForm(form) {
  const payload = {};

  const name = (form.name ?? '').trim();
  if (name) payload.name = name;

  payload.dob = form.dob ? form.dob : null;
  payload.sex = form.sex ? form.sex : null;

  const heightCm = feetInchesToCm(form.heightFeet, form.heightInches);
  if (heightCm !== null) payload.height_cm = heightCm;

  const weightKg = lbToKg(form.weightLb);
  if (weightKg !== null) payload.weight_kg = weightKg;

  const cssPaceSeconds = parsePaceToSeconds(form.cssPace);
  if (cssPaceSeconds !== null) payload.css_pace_s_per_100m = cssPaceSeconds;

  payload.pool_schedule = dayMapToPoolSchedule(form.poolDays);

  return payload;
}

/** Serializes the Feedback tab's form state into a `POST /api/feedback` body.
 * `type` is one of feature_request/comment/bug (research_question is
 * coach-only -- see backend/app/routes/feedback.py); `body` is trimmed (not
 * nulled when blank -- the backend rejects an empty body as a 422, same as
 * any other required-field validation failure). */
export function serializeFeedbackForm(form) {
  return {
    type: form.type,
    body: (form.body ?? '').trim(),
  };
}
