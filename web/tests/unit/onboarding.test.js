import { describe, it, expect, beforeEach } from 'vitest';
import {
  createOnboardForm, createOnboardingState, validateOnboardForm, onboardPayloadFromForm,
  startOnboardingSession, identityFromOnboardSession, loadOnboardingActive, saveOnboardingActive,
} from '../../src/onboarding.js';

function makeFakeStorage() {
  const store = new Map();
  return {
    getItem: (key) => (store.has(key) ? store.get(key) : null),
    setItem: (key, value) => store.set(key, String(value)),
    removeItem: (key) => store.delete(key),
  };
}

describe('createOnboardingState', () => {
  it('starts inactive with a fresh, empty form', () => {
    const state = createOnboardingState();
    expect(state.active).toBe(false);
    expect(state.token).toBeNull();
    expect(state.submitting).toBe(false);
    expect(state.error).toBeNull();
    expect(state.form).toEqual(createOnboardForm());
  });
});

describe('validateOnboardForm', () => {
  function validForm(overrides = {}) {
    return {
      ...createOnboardForm(),
      name: 'Jamie',
      cssMode: 'pace',
      cssPace: '1:40',
      eventName: 'Catalina Channel',
      eventDate: '2027-08-01',
      eventDistanceM: '33300',
      ...overrides,
    };
  }

  it('accepts a fully-filled form (CSS pace mode)', () => {
    expect(validateOnboardForm(validForm())).toEqual({ valid: true, errors: [] });
  });

  it('accepts a fully-filled form (test-time mode)', () => {
    const form = validForm({ cssMode: 'test', cssPace: '', test400: '7:20', test200: '3:20' });
    expect(validateOnboardForm(form)).toEqual({ valid: true, errors: [] });
  });

  it('requires a name', () => {
    const { valid, errors } = validateOnboardForm(validForm({ name: '  ' }));
    expect(valid).toBe(false);
    expect(errors).toContain('Name is required.');
  });

  it('requires a CSS pace when in pace mode', () => {
    const { valid, errors } = validateOnboardForm(validForm({ cssPace: '' }));
    expect(valid).toBe(false);
    expect(errors).toContain('Enter your CSS pace (mm:ss per 100m).');
  });

  it('requires BOTH 400m and 200m test times when in test mode -- one alone is not enough', () => {
    const missing200 = validateOnboardForm(validForm({ cssMode: 'test', cssPace: '', test400: '7:20', test200: '' }));
    expect(missing200.valid).toBe(false);
    expect(missing200.errors).toContain('Enter both your 400m and 200m time-trial results (mm:ss).');

    const missing400 = validateOnboardForm(validForm({ cssMode: 'test', cssPace: '', test400: '', test200: '3:20' }));
    expect(missing400.valid).toBe(false);
  });

  it('does not require a CSS pace when a complete test-time pair is given, even if cssPace is blank', () => {
    const form = validForm({ cssMode: 'test', cssPace: '', test400: '7:20', test200: '3:20' });
    const { errors } = validateOnboardForm(form);
    expect(errors).not.toContain('Enter your CSS pace (mm:ss per 100m).');
  });

  it('requires a target event name, date, and a positive distance', () => {
    const { valid, errors } = validateOnboardForm(validForm({ eventName: '', eventDate: '', eventDistanceM: '' }));
    expect(valid).toBe(false);
    expect(errors).toContain('Target event name is required.');
    expect(errors).toContain('Target event date is required.');
    expect(errors).toContain('Target event distance (in meters) must be a positive number.');
  });

  it('rejects a zero or negative event distance', () => {
    const { valid, errors } = validateOnboardForm(validForm({ eventDistanceM: '0' }));
    expect(valid).toBe(false);
    expect(errors).toContain('Target event distance (in meters) must be a positive number.');
  });

  it('collects every violation at once, not just the first', () => {
    const { errors } = validateOnboardForm(createOnboardForm());
    expect(errors.length).toBeGreaterThan(1);
  });
});

describe('onboardPayloadFromForm', () => {
  function baseForm(overrides = {}) {
    return {
      ...createOnboardForm(),
      name: '  Jamie  ',
      cssMode: 'pace',
      cssPace: '1:40',
      eventName: 'Catalina Channel',
      eventDate: '2027-08-01',
      eventDistanceM: '33300',
      ...overrides,
    };
  }

  it('mirrors backend/app/routes/onboard.py OnboardRequest field names exactly', () => {
    const payload = onboardPayloadFromForm(baseForm());
    expect(payload).toEqual({
      name: 'Jamie',
      css_pace_s_per_100m: 100, // "1:40" -> 100s
      pool_schedule: [],
      events: [{
        name: 'Catalina Channel', event_date: '2027-08-01', distance_m: 33300, event_format: 'single_day',
      }],
    });
  });

  it('sends test_400/test_200 as raw mm:ss strings (not converted to seconds) when in test mode', () => {
    const payload = onboardPayloadFromForm(baseForm({ cssMode: 'test', cssPace: '', test400: '7:20', test200: '3:20' }));
    expect(payload.css_pace_s_per_100m).toBeUndefined();
    expect(payload.test_400).toBe('7:20');
    expect(payload.test_200).toBe('3:20');
  });

  it('includes sex/dob/height/weight only when given, converting height/weight to cm/kg', () => {
    const withDemographics = onboardPayloadFromForm(baseForm({
      sex: 'female', dob: '1990-05-14', heightFeet: '5', heightInches: '7', weightLb: '140',
    }));
    expect(withDemographics.sex).toBe('female');
    expect(withDemographics.dob).toBe('1990-05-14');
    expect(withDemographics.height_cm).toBeCloseTo(170.2, 5);
    expect(withDemographics.weight_kg).toBeCloseTo(63.5, 5);

    const withoutDemographics = onboardPayloadFromForm(baseForm());
    expect(withoutDemographics).not.toHaveProperty('sex');
    expect(withoutDemographics).not.toHaveProperty('dob');
    expect(withoutDemographics).not.toHaveProperty('height_cm');
    expect(withoutDemographics).not.toHaveProperty('weight_kg');
  });

  it('serializes checked pool days in Mon-Sun order, omits unchecked ones', () => {
    const form = baseForm();
    form.poolDays.tuesday = true;
    form.poolDays.friday = true;
    const payload = onboardPayloadFromForm(form);
    expect(payload.pool_schedule).toEqual(['tuesday', 'friday']);
  });

  it('includes current/peak volume and macro_start only when given', () => {
    const withVolume = onboardPayloadFromForm(baseForm({
      currentVolumeM: '12000', peakVolumeM: '28000', macroStart: '2026-08-01',
    }));
    expect(withVolume.current_volume_m).toBe(12000);
    expect(withVolume.peak_volume_m).toBe(28000);
    expect(withVolume.macro_start).toBe('2026-08-01');

    const withoutVolume = onboardPayloadFromForm(baseForm());
    expect(withoutVolume).not.toHaveProperty('current_volume_m');
    expect(withoutVolume).not.toHaveProperty('peak_volume_m');
    expect(withoutVolume).not.toHaveProperty('macro_start');
  });

  it('includes a custom slug only when given (advanced/optional field)', () => {
    expect(onboardPayloadFromForm(baseForm({ slug: '  jamie-custom  ' })).slug).toBe('jamie-custom');
    expect(onboardPayloadFromForm(baseForm())).not.toHaveProperty('slug');
  });

  it('maps eventFormat to multi_day_stage only when explicitly set, defaulting to single_day', () => {
    const staged = onboardPayloadFromForm(baseForm({ eventFormat: 'multi_day_stage' }));
    expect(staged.events[0].event_format).toBe('multi_day_stage');

    const single = onboardPayloadFromForm(baseForm({ eventFormat: 'single_day' }));
    expect(single.events[0].event_format).toBe('single_day');
  });
});

describe('startOnboardingSession', () => {
  it('persists the onboarding token via the injected saveSettings and returns an active onboarding slice', () => {
    let savedWith = null;
    const fakeSaveSettings = (settings) => {
      savedWith = settings;
      return { ...settings, version: 2 };
    };

    const result = startOnboardingSession({
      outcome: { onboarding: true, token: 'onboard-tok-123' },
      settingsForm: { baseUrl: 'https://api.example.com', token: '' },
      saveSettings: fakeSaveSettings,
    });

    expect(savedWith).toEqual({ baseUrl: 'https://api.example.com', token: 'onboard-tok-123' });
    expect(result.settingsForm).toEqual({ baseUrl: 'https://api.example.com', token: 'onboard-tok-123', version: 2 });
    expect(result.onboarding.active).toBe(true);
    expect(result.onboarding.token).toBe('onboard-tok-123');
    expect(result.onboarding.submitting).toBe(false);
    expect(result.onboarding.error).toBeNull();
    expect(result.onboarding.form).toEqual(createOnboardForm());
  });
});

describe('identityFromOnboardSession', () => {
  it('maps a POST /api/onboard success response to {name, athlete, role}', () => {
    const session = {
      token: 'athlete-tok', athlete: 'jamie', name: 'Jamie', role: 'athlete', expires_at: '2026-08-01T00:00:00Z',
    };
    expect(identityFromOnboardSession(session)).toEqual({ name: 'Jamie', athlete: 'jamie', role: 'athlete' });
  });
});

describe('onboarding-active persistence', () => {
  let storage;
  beforeEach(() => {
    storage = makeFakeStorage();
  });

  it('defaults to false when nothing is stored', () => {
    expect(loadOnboardingActive(storage)).toBe(false);
  });

  it('round-trips true/false', () => {
    saveOnboardingActive(true, storage);
    expect(loadOnboardingActive(storage)).toBe(true);
    saveOnboardingActive(false, storage);
    expect(loadOnboardingActive(storage)).toBe(false);
  });
});
