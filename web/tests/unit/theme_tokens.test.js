import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { ZONE_COLORS } from '../../src/shape.js';

const html = readFileSync(fileURLToPath(new URL('../../index.html', import.meta.url)), 'utf8');
const rootBlock = html.slice(html.indexOf(':root {'), html.indexOf('* { box-sizing'));
const token = (name) => new RegExp(`${name}\\s*:\\s*([^;]+);`).exec(rootBlock)?.[1].trim();

const lum = (hex) => {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
};
const contrast = (a, b) => {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
};

describe('cream theme tokens', () => {
  it('resolves surfaces and text to the cream palette', () => {
    expect(token('--ground')).toBe('#fbf8f0');
    expect(token('--paper')).toBe('#ffffff');
    expect(token('--paper-2')).toBe('#f6f1e6');
    expect(token('--line')).toBe('#e6decb');
    expect(token('--ink')).toBe('#0b2a36');
    expect(token('--ink-soft')).toBe('#33505b');
    expect(token('--ink-faint')).toBe('#4d6670');
    expect(token('--accent')).toBe('#45afc6');
    expect(token('--accent-ink')).toBe('#137590');
    expect(token('--c-signal')).toBe('#c42b25');
  });

  it('keeps text tokens legible on every surface', () => {
    for (const t of ['--ink', '--ink-soft', '--ink-faint', '--accent-ink', '--c-signal', '--c-attn']) {
      for (const s of ['--ground', '--paper', '--paper-2']) {
        expect(contrast(token(t), token(s))).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('keeps sport and zone graphic colours at 3:1 on white', () => {
    const sport = ['--c-pool', '--c-ow', '--c-bike', '--c-strength', '--c-recovery', '--c-cross-train',
      '--c-nutrition', '--c-yoga', '--c-form', '--c-signal'].map(token);
    for (const hex of [...sport, ...Object.values(ZONE_COLORS)]) {
      expect(contrast(hex, '#ffffff')).toBeGreaterThanOrEqual(3);
    }
  });

  it('uses the cream theme-color in meta and manifest', () => {
    expect(html).toContain('<meta name="theme-color" content="#fbf8f0">');
    const vite = readFileSync(fileURLToPath(new URL('../../vite.config.js', import.meta.url)), 'utf8');
    expect(vite).toContain("theme_color: '#fbf8f0'");
    expect(vite).toContain("background_color: '#fbf8f0'");
  });
});
