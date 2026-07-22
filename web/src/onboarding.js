// Pure logic for the first-login onboarding form (Slice 3 of self-service
// in-app onboarding -- docs/design-self-service-onboarding.md; stacks on
// Slice 1 (#67, onboarding-scoped sessions) and Slice 2 (#68, POST
// /api/onboard, backend/app/routes/onboard.py)). Kept DOM-free, same
// convention as forms.js/session.js, so the form shape, the required-field/
// CSS-or-test validation, and the request->payload mapping are all
// unit-testable without jsdom.
//
// `onboardPayloadFromForm` mirrors backend/app/routes/onboard.py's
// `OnboardRequest` pydantic model field-for-field -- see that file's own
// docstring for the exact shape this must match. Unit + height/weight
// conversion reuses forms.js's existing feetInchesToCm/lbToKg/
// parsePaceToSeconds/dayMapToPoolSchedule helpers (the same ones the
// Settings tab's profile-edit form already uses) rather than re-deriving
// them, so onboarding and profile-edit stay byte-identical on unit handling.

import {
  feetInchesToCm, lbToKg, parsePaceToSeconds, dayMapToPoolSchedule,
} from './forms.js';

export function createOnboardForm() {
  return {
    name: '',
    dob: '',
    sex: '',
    heightFeet: '',
    heightInches: '',
    weightLb: '',
    // 'pace' (a known CSS pace) or 'test' (derive it from a 400m/200m time
    // trial) -- mirrors OnboardRequest's mutually-exclusive
    // css_pace_s_per_100m vs test_400+test_200, see the model_validator in
    // onboard.py.
    cssMode: 'pace',
    cssPace: '', // mm:ss, used when cssMode === 'pace'
    test400: '', // mm:ss, used when cssMode === 'test'
    test200: '', // mm:ss, used when cssMode === 'test'
    poolDays: {
      monday: false,
      tuesday: false,
      wednesday: false,
      thursday: false,
      friday: false,
      saturday: false,
      sunday: false,
    },
    // A single target event -- OnboardRequest technically accepts a list
    // (with `target_event` picking among several), but the onboarding form
    // only collects one; see this module's own doc comment / the build
    // report for why multi-event entry is out of scope for this slice.
    eventName: '',
    eventDate: '',
    eventDistanceM: '',
    eventFormat: 'single_day',
    currentVolumeM: '',
    peakVolumeM: '',
    macroStart: '',
    slug: '', // optional, advanced/rarely-used -- see views.js's <details>
  };
}

/** The onboarding-mode slice of main.js's app state -- `active` gates
 * whether the onboarding form renders instead of the ordinary tabs (see
 * main.js's render()). `token` is the onboarding-scoped session's bearer
 * token (distinct from state.settingsForm.token during the brief window
 * where an athlete-bound token is being minted -- see main.js's
 * handleOnboardSubmit). */
export function createOnboardingState() {
  return {
    active: false, token: null, submitting: false, error: null, form: createOnboardForm(),
  };
}

/** Required-field + CSS-pace-or-test-times validation, mirroring
 * backend/app/routes/onboard.py's OnboardRequest.model_validator (the same
 * "css_pace_s_per_100m, or both test_400 and test_200, is required" rule)
 * plus the fields this form treats as required beyond what the pydantic
 * model itself requires (a target event -- OnboardRequest technically
 * allows zero events, but a self-service athlete with no event isn't a
 * useful state for scaffold_macro to build a plan around, so the form
 * requires one). Checked client-side so a submit never round-trips to the
 * backend just to learn "name is required." Returns `{valid, errors}` where
 * `errors` is a flat list of user-facing strings -- the form is short
 * enough for one error list above the submit button rather than per-field
 * messages (same convention as the Log tab's single RPE-required hint). */
export function validateOnboardForm(form) {
  const errors = [];

  if (!(form.name || '').trim()) errors.push('Name is required.');

  if (form.cssMode === 'test') {
    if (parsePaceToSeconds(form.test400) === null || parsePaceToSeconds(form.test200) === null) {
      errors.push('Enter both your 400m and 200m time-trial results (mm:ss).');
    }
  } else if (parsePaceToSeconds(form.cssPace) === null) {
    errors.push('Enter your CSS pace (mm:ss per 100m).');
  }

  if (!(form.eventName || '').trim()) errors.push('Target event name is required.');
  if (!form.eventDate) errors.push('Target event date is required.');
  const distance = Number(form.eventDistanceM);
  if (form.eventDistanceM === '' || !Number.isFinite(distance) || distance <= 0) {
    errors.push('Target event distance (in meters) must be a positive number.');
  }

  return { valid: errors.length === 0, errors };
}

/** Serializes the onboarding form's state into a `POST /api/onboard` body.
 * Assumes `validateOnboardForm(form).valid` is already true -- callers
 * (main.js's handleOnboardSubmit) must check that first; this function
 * doesn't re-validate, it just maps whatever's there. */
export function onboardPayloadFromForm(form) {
  const payload = { name: (form.name || '').trim() };

  if (form.cssMode === 'test') {
    payload.test_400 = (form.test400 || '').trim();
    payload.test_200 = (form.test200 || '').trim();
  } else {
    payload.css_pace_s_per_100m = parsePaceToSeconds(form.cssPace);
  }

  if (form.sex) payload.sex = form.sex;
  if (form.dob) payload.dob = form.dob;

  const heightCm = feetInchesToCm(form.heightFeet, form.heightInches);
  if (heightCm !== null) payload.height_cm = heightCm;

  const weightKg = lbToKg(form.weightLb);
  if (weightKg !== null) payload.weight_kg = weightKg;

  payload.pool_schedule = dayMapToPoolSchedule(form.poolDays);

  payload.events = [{
    name: (form.eventName || '').trim(),
    event_date: form.eventDate,
    distance_m: Number(form.eventDistanceM),
    event_format: form.eventFormat === 'multi_day_stage' ? 'multi_day_stage' : 'single_day',
  }];

  const currentVolume = Number(form.currentVolumeM);
  if (form.currentVolumeM !== '' && Number.isFinite(currentVolume)) payload.current_volume_m = currentVolume;

  const peakVolume = Number(form.peakVolumeM);
  if (form.peakVolumeM !== '' && Number.isFinite(peakVolume)) payload.peak_volume_m = peakVolume;

  if (form.macroStart) payload.macro_start = form.macroStart;

  const slug = (form.slug || '').trim();
  if (slug) payload.slug = slug;

  return payload;
}

// --- Response handling (pure reducers, DOM-free) ------------------------
// Same "inject the side-effecting dependency" convention as session.js's
// performSignOut -- these take the exchange/submit outcome plus whatever
// main.js's state already holds and return what main.js should assign back
// into state, without touching localStorage/DOM/window directly themselves
// (the injected `saveSettings` is the one exception, exactly like
// performSignOut's injected `logout`/`saveSettings`/`signOut` -- it's
// settings.js's real persistence function, just passed in so this stays
// testable against a fake).

/** Given identity.js's onboarding exchange outcome (`{onboarding: true,
 * token}`, see identity.js's signIn doc comment) and the current
 * settingsForm, returns the new `{settingsForm, onboarding}` to assign into
 * main.js's state: the onboarding token persisted via the injected
 * `saveSettings`, and a fresh, active onboarding state slice. */
export function startOnboardingSession({ outcome, settingsForm, saveSettings }) {
  return {
    settingsForm: saveSettings({ baseUrl: settingsForm.baseUrl, token: outcome.token }),
    onboarding: { ...createOnboardingState(), active: true, token: outcome.token },
  };
}

/** Maps a successful `POST /api/onboard` response (api.js's `onboard`) into
 * the `{name, athlete, role}` shape identity.js's saveIdentity/main.js's
 * applyAthleteSession expect -- identical mapping to identity.js's own
 * exchange-success branch, factored out here so main.js's handleOnboardSubmit
 * doesn't have to inline it a second time. */
export function identityFromOnboardSession(session) {
  return { name: session.name, athlete: session.athlete, role: session.role };
}

// --- "Am I mid-onboarding?" persistence --------------------------------
// A tiny, separate localStorage flag -- NOT folded into identity.js's own
// storage (that module's contract is specifically "the resolved {name,
// athlete, role} identity", and an onboarding session has no athlete yet,
// so mixing shapes there would force every identity.js caller to guard
// against a null-athlete identity it never otherwise needs to consider).
// Exists purely so a reload mid-form-fill still shows the onboarding form
// (main.js reads this at boot, alongside settingsForm.token, to compute
// state.onboarding.active) instead of silently dumping the athlete back to
// the plain sign-in gate with no explanation. Losing this flag is harmless
// either way -- the pending invite is still allowlisted server-side, so a
// fresh Google sign-in just mints another onboarding session for the same
// email and lands back on an (empty) onboarding form.

const ONBOARDING_ACTIVE_KEY = 'swimcoach_onboarding_active';

export function loadOnboardingActive(storage = localStorage) {
  try {
    return storage.getItem(ONBOARDING_ACTIVE_KEY) === '1';
  } catch {
    return false;
  }
}

export function saveOnboardingActive(active, storage = localStorage) {
  try {
    if (active) storage.setItem(ONBOARDING_ACTIVE_KEY, '1');
    else storage.removeItem(ONBOARDING_ACTIVE_KEY);
  } catch {
    // localStorage unavailable -- just won't survive a reload; the
    // in-memory onboarding state still works for the current session.
  }
}
