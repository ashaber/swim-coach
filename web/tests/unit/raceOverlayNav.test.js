import { describe, expect, it } from 'vitest';
import { classifySwipe, swipeTargetTab, timelineAnchorId } from '../../src/raceOverlayNav.js';

const clock = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];

describe('timelineAnchorId', () => {
  it('is the event before the current one', () => {
    expect(timelineAnchorId(clock, 'c')).toBe('b');
    expect(timelineAnchorId(clock, 'b')).toBe('a');
  });
  it('is the current one when it is first', () => {
    expect(timelineAnchorId(clock, 'a')).toBe('a');
  });
  it('is null with no current or an unknown id', () => {
    expect(timelineAnchorId(clock, null)).toBeNull();
    expect(timelineAnchorId(clock, 'zzz')).toBeNull();
    expect(timelineAnchorId([], 'a')).toBeNull();
  });
});

describe('classifySwipe', () => {
  const base = { startX: 200, startY: 400, width: 390 };
  it('detects left and right swipes', () => {
    expect(classifySwipe({ ...base, endX: 100, endY: 410 })).toBe('left');
    expect(classifySwipe({ ...base, endX: 300, endY: 380 })).toBe('right');
  });
  it('ignores taps and short moves', () => {
    expect(classifySwipe({ ...base, endX: 203, endY: 402 })).toBeNull();
    expect(classifySwipe({ ...base, endX: 150, endY: 400 })).toBeNull();
  });
  it('ignores mostly vertical or diagonal drags', () => {
    expect(classifySwipe({ ...base, endX: 120, endY: 600 })).toBeNull();
    expect(classifySwipe({ ...base, endX: 110, endY: 460 })).toBeNull();
  });
  it('ignores starts in the screen-edge zones', () => {
    expect(classifySwipe({ ...base, startX: 10, endX: 200, endY: 400 })).toBeNull();
    expect(classifySwipe({ ...base, startX: 380, endX: 100, endY: 400 })).toBeNull();
  });
});

describe('swipeTargetTab', () => {
  it('maps directions to tabs', () => {
    expect(swipeTargetTab('list', 'left')).toBe('timeline');
    expect(swipeTargetTab('timeline', 'right')).toBe('list');
    expect(swipeTargetTab('list', 'right')).toBeNull();
    expect(swipeTargetTab('timeline', 'left')).toBeNull();
    expect(swipeTargetTab('list', null)).toBeNull();
  });
});
