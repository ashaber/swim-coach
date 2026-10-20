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

describe('background C theme tokens', () => {
  it('resolves surfaces and text to the cream palette', () => {
    expect(token('--ground')).toBe('#1f4a59');
    expect(token('--paper')).toBe('#fbf8f0');
    expect(token('--card-border')).toBe('#2e5d6d');
    expect(token('--chip-off')).toBe('#ffffff');
    expect(token('--band')).toBe('#b5dee7');
    expect(token('--on-band')).toBe('#0b2a36');
    expect(token('--on-band-soft')).toBe('#23434f');
    expect(token('--on-band-link')).toBe('#0e5e75');
    expect(token('--on-ground')).toBe('#f2f7f8');
    expect(token('--on-ground-soft')).toBe('#c5d8de');
    expect(token('--on-ground-link')).toBe('#a3e4d7');
    expect(token('--bubble-out-bg')).toBe('#b5dee7');
    expect(token('--bubble-out-border')).toBe('#9fd3df');
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
      for (const s of ['--paper', '--paper-2', '--inset']) {
        expect(contrast(token(t), token(s))).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it('keeps text on the deep page and on the header bands legible', () => {
    for (const t of ['--on-ground', '--on-ground-soft', '--on-ground-link']) {
      expect(contrast(token(t), token('--ground'))).toBeGreaterThanOrEqual(4.5);
    }
    for (const t of ['--on-band', '--on-band-soft', '--on-band-link', '--bubble-out-ink']) {
      expect(contrast(token(t), token('--band'))).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(token('--on-accent'), token('--accent'))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token('--ink-soft'), token('--chip-off'))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token('--tab-inactive'), token('--paper'))).toBeGreaterThanOrEqual(4.5);
    expect(contrast(token('--tab-active'), token('--paper'))).toBeGreaterThanOrEqual(4.5);
  });

  it('keeps sport and zone graphic colours at 3:1 on white', () => {
    const sport = ['--c-pool', '--c-ow', '--c-bike', '--c-strength', '--c-recovery', '--c-cross-train',
      '--c-nutrition', '--c-yoga', '--c-form', '--c-signal'].map(token);
    for (const hex of [...sport, ...Object.values(ZONE_COLORS)]) {
      expect(contrast(hex, '#ffffff')).toBeGreaterThanOrEqual(3);
    }
  });

  it('uses the deep-blue theme-color in meta and manifest', () => {
    expect(html).toContain('<meta name="theme-color" content="#1f4a59">');
    expect(html).toContain('content="black-translucent"');
    const vite = readFileSync(fileURLToPath(new URL('../../vite.config.js', import.meta.url)), 'utf8');
    expect(vite).toContain("theme_color: '#1f4a59'");
    expect(vite).toContain("background_color: '#1f4a59'");
  });
});
