import { describe, it, expect } from 'vitest';
import {
  serializeWorkoutForm, serializeWellnessForm, serializeFeedbackForm,
  parsePaceToSeconds, formatSecondsToPace,
  cmToFeetInches, feetInchesToCm,
  kgToLb, lbToKg,
  poolScheduleToDayMap, dayMapToPoolSchedule,
  profileFormFromAthlete, serializeProfileForm,
} from '../../src/forms.js';

describe('serializeWorkoutForm', () => {
  it('coerces numeric fields and passes through strings', () => {
    const form = {
      date: '2026-07-07', sport: 'swim_pool', distance_m: '3000', duration_min: '60', rpe: '6', notes: 'felt good',
    };
    expect(serializeWorkoutForm(form)).toEqual({
      date: '2026-07-07',
      sport: 'swim_pool',
      distance_m: 3000,
      duration_min: 60,
      rpe: 6,
      notes: 'felt good',
    });
  });

  it('sends null for blank notes and blank rpe rather than empty strings', () => {
    const form = {
      date: '2026-07-07', sport: 'swim_ow', distance_m: '1000', duration_min: '20', rpe: '', notes: '   ',
    };
    const result = serializeWorkoutForm(form);
    expect(result.notes).toBeNull();
    expect(result.rpe).toBeNull();
  });

  it('treats a non-numeric distance/duration as 0 rather than NaN', () => {
    const form = { date: '2026-07-07', sport: 'strength', distance_m: '', duration_min: '', rpe: '', notes: '' };
    const result = serializeWorkoutForm(form);
    expect(result.distance_m).toBe(0);
    expect(result.duration_min).toBe(0);
  });
});

describe('serializeWellnessForm', () => {
  it('coerces all score/number fields and trims notes', () => {
    const form = {
      date: '2026-07-07',
      sleep_quality: '4',
      sleep_hours: '7.5',
      stress: '2',
      soreness: '3',
      motivation: '4',
      resting_hr: '52',
      hrv: '61.2',
      notes: '  felt good  ',
    };
    expect(serializeWellnessForm(form)).toEqual({
      date: '2026-07-07',
      sleep_quality: 4,
      sleep_hours: 7.5,
      stress: 2,
      soreness: 3,
      motivation: 4,
      resting_hr: 52,
      hrv: 61.2,
      notes: 'felt good',
    });
  });

  it('sends null for blank optional fields (resting_hr, hrv, notes)', () => {
    const form = {
      date: '2026-07-07', sleep_quality: '3', sleep_hours: '8', stress: '3', soreness: '3', motivation: '3',
      resting_hr: '', hrv: '', notes: '',
    };
    const result = serializeWellnessForm(form);
    expect(result.resting_hr).toBeNull();
    expect(result.hrv).toBeNull();
    expect(result.notes).toBeNull();
  });
});

describe('parsePaceToSeconds', () => {
  it('parses mm:ss into seconds', () => {
    expect(parsePaceToSeconds('1:40')).toBe(100);
    expect(parsePaceToSeconds('1:30')).toBe(90);
  });

  it('parses mm:ss.f into fractional seconds', () => {
    expect(parsePaceToSeconds('1:35.5')).toBe(95.5);
  });

  it('parses a plain-seconds string with no colon', () => {
    expect(parsePaceToSeconds('90')).toBe(90);
  });

  it('returns null for blank/unparseable input', () => {
    expect(parsePaceToSeconds('')).toBeNull();
    expect(parsePaceToSeconds('abc')).toBeNull();
    expect(parsePaceToSeconds('1:abc')).toBeNull();
    expect(parsePaceToSeconds(null)).toBeNull();
    expect(parsePaceToSeconds(undefined)).toBeNull();
  });
});

describe('formatSecondsToPace', () => {
  it('formats whole seconds as mm:ss with zero-padded seconds', () => {
    expect(formatSecondsToPace(90)).toBe('1:30');
    expect(formatSecondsToPace(65)).toBe('1:05');
    expect(formatSecondsToPace(100)).toBe('1:40');
  });

  it('rounds to the nearest whole second', () => {
    expect(formatSecondsToPace(95.6)).toBe('1:36');
  });

  it('returns an empty string for null/undefined', () => {
    expect(formatSecondsToPace(null)).toBe('');
    expect(formatSecondsToPace(undefined)).toBe('');
  });
});

describe('cmToFeetInches / feetInchesToCm', () => {
  it('converts cm to whole feet + inches', () => {
    expect(cmToFeetInches(182.88)).toEqual({ feet: 6, inches: 0 });
    expect(cmToFeetInches(168)).toEqual({ feet: 5, inches: 6 });
  });

  it('converts feet + inches back to cm', () => {
    expect(feetInchesToCm(6, 0)).toBeCloseTo(182.88, 1);
    expect(feetInchesToCm(5, 6)).toBeCloseTo(167.64, 1);
  });

  it('round-trips within half an inch', () => {
    const { feet, inches } = cmToFeetInches(175);
    const roundTripped = feetInchesToCm(feet, inches);
    expect(Math.abs(roundTripped - 175)).toBeLessThan(1.5);
  });

  it('cmToFeetInches returns blanks for null/undefined', () => {
    expect(cmToFeetInches(null)).toEqual({ feet: '', inches: '' });
    expect(cmToFeetInches(undefined)).toEqual({ feet: '', inches: '' });
  });

  it('feetInchesToCm returns null when both parts are blank', () => {
    expect(feetInchesToCm('', '')).toBeNull();
  });

  it('feetInchesToCm treats a blank inches as 0', () => {
    expect(feetInchesToCm(5, '')).toBeCloseTo(152.4, 1);
  });
});

describe('kgToLb / lbToKg', () => {
  it('converts kg to lb', () => {
    expect(kgToLb(72.6)).toBeCloseTo(160.1, 1);
  });

  it('converts lb to kg', () => {
    expect(lbToKg(160)).toBeCloseTo(72.6, 1);
  });

  it('kgToLb returns empty string for null/undefined', () => {
    expect(kgToLb(null)).toBe('');
    expect(kgToLb(undefined)).toBe('');
  });

  it('lbToKg returns null for blank/non-positive input', () => {
    expect(lbToKg('')).toBeNull();
    expect(lbToKg(0)).toBeNull();
    expect(lbToKg(-5)).toBeNull();
    expect(lbToKg('abc')).toBeNull();
  });
});

describe('poolScheduleToDayMap / dayMapToPoolSchedule', () => {
  it('reads plain-string pool_schedule entries', () => {
    const map = poolScheduleToDayMap(['tuesday', 'thursday']);
    expect(map.tuesday).toBe(true);
    expect(map.thursday).toBe(true);
    expect(map.monday).toBe(false);
  });

  it('reads dict-shaped pool_schedule entries (day/duration_min/source)', () => {
    const map = poolScheduleToDayMap([
      { day: 'monday', duration_min: 90, source: 'USMS coached' },
      { day: 'friday', duration_min: 90, source: 'USMS coached' },
    ]);
    expect(map.monday).toBe(true);
    expect(map.friday).toBe(true);
    expect(map.wednesday).toBe(false);
  });

  it('defaults every day to false for an empty schedule', () => {
    const map = poolScheduleToDayMap([]);
    expect(Object.values(map).every((v) => v === false)).toBe(true);
  });

  it('serializes a day map back to a sorted (Mon-Sun) plain-string list', () => {
    const schedule = dayMapToPoolSchedule({
      sunday: true, monday: true, wednesday: true, tuesday: false, thursday: false, friday: false, saturday: false,
    });
    expect(schedule).toEqual(['monday', 'wednesday', 'sunday']);
  });
});

describe('profileFormFromAthlete', () => {
  it('prefills and converts units from an athlete profile', () => {
    const athlete = {
      name: 'Andrew', dob: '1975-04-07', sex: 'male', height_cm: 182.88, weight_kg: 72.6,
      css_pace_s_per_100m: 100.0, pool_schedule: ['tuesday', 'thursday'],
    };
    const form = profileFormFromAthlete(athlete);
    expect(form.name).toBe('Andrew');
    expect(form.dob).toBe('1975-04-07');
    expect(form.sex).toBe('male');
    expect(form.heightFeet).toBe('6');
    expect(form.heightInches).toBe('0');
    expect(form.weightLb).toBe('160.1');
    expect(form.cssPace).toBe('1:40');
    expect(form.poolDays.tuesday).toBe(true);
    expect(form.poolDays.thursday).toBe(true);
    expect(form.poolDays.monday).toBe(false);
  });

  it('leaves fields blank when the athlete has no value yet', () => {
    const form = profileFormFromAthlete({ name: 'Andrew', pool_schedule: [] });
    expect(form.dob).toBe('');
    expect(form.sex).toBe('');
    expect(form.heightFeet).toBe('');
    expect(form.heightInches).toBe('');
    expect(form.weightLb).toBe('');
    expect(form.cssPace).toBe('');
  });
});

describe('serializeProfileForm', () => {
  it('builds a PATCH payload converting US units back to cm/kg/seconds', () => {
    const form = {
      name: 'Andrew Shaber', dob: '1975-04-07', sex: 'male',
      heightFeet: '6', heightInches: '0', weightLb: '160',
      cssPace: '1:40', poolDays: { tuesday: true, thursday: true },
    };
    const payload = serializeProfileForm(form);
    expect(payload.name).toBe('Andrew Shaber');
    expect(payload.dob).toBe('1975-04-07');
    expect(payload.sex).toBe('male');
    expect(payload.height_cm).toBeCloseTo(182.88, 1);
    expect(payload.weight_kg).toBeCloseTo(72.6, 1);
    expect(payload.css_pace_s_per_100m).toBe(100);
    expect(payload.pool_schedule).toEqual(['tuesday', 'thursday']);
  });

  it('sends null for a blank dob/sex (explicit clear)', () => {
    const form = {
      name: 'Andrew', dob: '', sex: '', heightFeet: '', heightInches: '', weightLb: '', cssPace: '', poolDays: {},
    };
    const payload = serializeProfileForm(form);
    expect(payload.dob).toBeNull();
    expect(payload.sex).toBeNull();
  });

  it('omits height/weight/css_pace when unparseable rather than sending garbage', () => {
    const form = {
      name: 'Andrew', dob: '', sex: '', heightFeet: '', heightInches: '', weightLb: 'abc', cssPace: 'abc', poolDays: {},
    };
    const payload = serializeProfileForm(form);
    expect(payload.height_cm).toBeUndefined();
    expect(payload.weight_kg).toBeUndefined();
    expect(payload.css_pace_s_per_100m).toBeUndefined();
  });

  it('trims the name and never sends a blank one', () => {
    const form = {
      name: '  Andrew  ', dob: '', sex: '', heightFeet: '', heightInches: '', weightLb: '', cssPace: '', poolDays: {},
    };
    expect(serializeProfileForm(form).name).toBe('Andrew');

    const blankNameForm = { ...form, name: '   ' };
    expect(serializeProfileForm(blankNameForm).name).toBeUndefined();
  });
});

describe('serializeFeedbackForm', () => {
  it('passes through type and trims body', () => {
    const form = { type: 'feature_request', body: '  add a pace calculator  ' };
    expect(serializeFeedbackForm(form)).toEqual({
      type: 'feature_request',
      body: 'add a pace calculator',
    });
  });

  it('supports comment and bug types', () => {
    expect(serializeFeedbackForm({ type: 'comment', body: 'nice app' }).type).toBe('comment');
    expect(serializeFeedbackForm({ type: 'bug', body: 'plan tab crashed' }).type).toBe('bug');
  });
});
