import { describe, it, expect } from 'vitest';
import {
  zoomAbout, panBy, fitBounds, resetView, clampView, zoomLevel, isZoomed, boundsOfPoints, clientToMap, viewBoxAttr, dragAction, pageScrollDelta,
} from '../../src/mapView.js';

const FULL = { x: 0, y: 0, w: 320, h: 200 };

describe('mapView', () => {
  it('zooms about a point so that point stays put', () => {
    const v = zoomAbout(FULL, FULL, 2, 240, 50);
    expect(v.w).toBe(160);
    expect(v.h).toBe(100);
    // the fixed point keeps its relative position inside the view
    expect((240 - v.x) / v.w).toBeCloseTo((240 - FULL.x) / FULL.w);
    expect((50 - v.y) / v.h).toBeCloseTo((50 - FULL.y) / FULL.h);
  });

  it('clamps zoom to 1x..8x', () => {
    expect(zoomAbout(FULL, FULL, 0.5, 100, 100)).toEqual(FULL);
    let v = FULL;
    for (let i = 0; i < 10; i += 1) v = zoomAbout(v, FULL, 2, 160, 100);
    expect(zoomLevel(v, FULL)).toBeCloseTo(8);
  });

  it('keeps the lap in bounds when zooming near an edge or panning', () => {
    const corner = zoomAbout(FULL, FULL, 4, 320, 200);
    expect(corner.x + corner.w).toBeLessThanOrEqual(320 + 1e-9);
    expect(corner.y + corner.h).toBeLessThanOrEqual(200 + 1e-9);
    const panned = panBy({ x: 100, y: 50, w: 80, h: 50 }, FULL, -500, 900);
    expect(panned).toEqual({ x: 0, y: 150, w: 80, h: 50 });
  });

  it('cannot pan at 1x', () => {
    expect(panBy(FULL, FULL, 40, 40)).toEqual(FULL);
  });

  it('fits a sector with a margin, at the map aspect ratio, inside the lap', () => {
    const v = fitBounds({ minX: 100, maxX: 140, minY: 80, maxY: 100 }, FULL);
    expect(v.w / v.h).toBeCloseTo(FULL.w / FULL.h);
    expect(v.x).toBeLessThanOrEqual(100);
    expect(v.x + v.w).toBeGreaterThanOrEqual(140);
    expect(v.y).toBeLessThanOrEqual(80);
    expect(v.y + v.h).toBeGreaterThanOrEqual(100);
    expect(isZoomed(v, FULL)).toBe(true);
  });

  it('never zooms past 8x for a tiny sector, and a huge sector fits the whole lap', () => {
    expect(zoomLevel(fitBounds({ minX: 10, maxX: 11, minY: 10, maxY: 11 }, FULL), FULL)).toBeLessThanOrEqual(8);
    expect(fitBounds({ minX: 0, maxX: 320, minY: 0, maxY: 200 }, FULL)).toEqual(FULL);
  });

  it('resets to the whole lap', () => {
    expect(resetView(FULL)).toEqual(FULL);
    expect(resetView(FULL)).not.toBe(FULL);
    expect(isZoomed(FULL, FULL)).toBe(false);
    expect(isZoomed(null, FULL)).toBe(false);
  });

  it('clamps an oversized view back to the lap', () => {
    expect(clampView({ x: -10, y: -10, w: 900, h: 900 }, FULL)).toEqual(FULL);
  });

  it('reads bounds from an SVG points string', () => {
    expect(boundsOfPoints('10,20 30,5 15,40')).toEqual({ minX: 10, maxX: 30, minY: 5, maxY: 40 });
  });

  it('maps client positions through the letterboxed viewBox', () => {
    const rect = { left: 10, top: 20, width: 320, height: 400 }; // taller than the 320x200 map: letterboxed vertically
    const p = clientToMap(FULL, rect, 10 + 160, 20 + 200);
    expect(p.x).toBeCloseTo(160);
    expect(p.y).toBeCloseTo(100);
    const zoomed = { x: 80, y: 50, w: 160, h: 100 };
    const q = clientToMap(zoomed, rect, 10 + 160, 20 + 200);
    expect(q.x).toBeCloseTo(160);
    expect(q.y).toBeCloseTo(100);
  });

  it('formats the viewBox attribute', () => {
    expect(viewBoxAttr({ x: 1.234, y: 2, w: 100, h: 62.5 })).toBe('1.23 2 100 62.5');
  });
});

describe('map gesture decisions', () => {
  it('two fingers always pinch, zoomed or not, in any direction', () => {
    expect(dragAction(2, false)).toBe('pinch');
    expect(dragAction(2, true)).toBe('pinch');
  });

  it('one finger pans the map while zoomed and scrolls the page at 1x', () => {
    expect(dragAction(1, true)).toBe('pan');
    expect(dragAction(1, false)).toBe('scroll');
  });

  it('ignores no-finger and 3+ finger states', () => {
    expect(dragAction(0, false)).toBe('none');
    expect(dragAction(3, true)).toBe('none');
  });

  it('page scroll follows only the vertical finger movement', () => {
    expect(pageScrollDelta({ x: 10, y: 100 }, { x: 80, y: 90 })).toBe(10);
    expect(pageScrollDelta({ x: 10, y: 100 }, { x: -50, y: 130 })).toBe(-30);
    expect(pageScrollDelta({ x: 10, y: 100 }, { x: 60, y: 100 })).toBe(0);
  });
});
