import { describe, it, expect } from 'vitest';
import { serializeWorkoutForm, serializeWellnessForm, serializeFeedbackForm } from '../../src/forms.js';

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
