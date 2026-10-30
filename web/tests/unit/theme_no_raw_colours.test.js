// Token discipline guard: outside index.html's :root token block, no raw colours.
// CSS: scans declaration bodies (inside { }) with comments stripped, so selectors like
// `#thread-sheet` and prose like "PR #173" never match. JS: scans src/*.js with comments
// stripped for hex literals not part of an id/entity, rgb()/hsl() calls, and named colours
// assigned to colour-ish properties. Allowed: transparent, currentColor, inherit, none.
// Explicit exceptions (chart data palettes consumed as JS values and contrast-tested elsewhere):
//   src/shape.js (ZONE_COLORS), src/raceHeat.js (HEAT/NEUTRAL/PAR).
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const here = (p) => fileURLToPath(new URL(p, import.meta.url));
const html = readFileSync(here('../../index.html'), 'utf8');
const JS_PALETTE_FILES = new Set(['shape.js', 'raceHeat.js']);

const NAMES = 'white|black|red|green|blue|gray|grey|orange|yellow|purple|pink|silver|navy|teal|maroon|olive|lime|aqua|fuchsia|brown|gold|cyan|magenta';
const HEX = /(?<![\w&])#[0-9a-fA-F]{3,8}(?![\w-])/g;
const FUNC = /\b(?:rgba?|hsla?)\(/g;
const NAMED_CSS = new RegExp(`(?:color|background(?:-color)?|border(?:-[a-z]+)*|fill|stroke|outline(?:-color)?)\\s*:[^;{}]*?(?<![-\\w])(?:${NAMES})\\b(?![-(])`, 'gi');
const NAMED_JS = new RegExp(`(?:color|background|fill|stroke)\\s*[:=]\\s*\\\\?["']?(?:${NAMES})\\b`, 'gi');

const stripBlock = (s) => s.replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, ' '));
const stripJs = (s) => stripBlock(s).replace(/(^|[^:'"`\\])\/\/[^\n]*/g, '$1');

function cssBodies() {
  const style = html.slice(html.indexOf('<style>') + 7, html.indexOf('</style>'));
  const rootStart = style.indexOf(':root {');
  const rootEnd = style.indexOf('}', rootStart) + 1;
  const css = stripBlock(style.slice(0, rootStart) + style.slice(rootEnd));
  const bodies = [];
  const re = /\{([^{}]*)\}/g;
  let m;
  while ((m = re.exec(css))) bodies.push(m[1]);
  return bodies;
}

const hits = (text, res) => res.flatMap((re) => text.match(re) ?? []);

describe('no raw colours outside :root tokens', () => {
  it('index.html rules use only var(--token) colours', () => {
    const bad = cssBodies().flatMap((b) => hits(b, [HEX, FUNC, NAMED_CSS]));
    expect(bad).toEqual([]);
  });

  it('src/*.js has no raw colours (palette files excepted)', () => {
    const dir = here('../../src/');
    const bad = [];
    for (const f of readdirSync(dir).filter((n) => n.endsWith('.js') && !JS_PALETTE_FILES.has(n))) {
      const src = stripJs(readFileSync(dir + f, 'utf8'));
      for (const h of hits(src, [HEX, FUNC, NAMED_JS])) bad.push(`${f}: ${h}`);
    }
    expect(bad).toEqual([]);
  });

  it('the scanner itself catches violations', () => {
    expect(hits('color: #fff; x', [HEX])).toHaveLength(1);
    expect(hits('a { color: white; }', [NAMED_CSS])).toHaveLength(1);
    expect(hits('box-shadow: 0 0 rgba(0,0,0,.3)', [FUNC])).toHaveLength(1);
    expect(hits('$("#swim-sets") &#8593; var(--c-signal)', [HEX, FUNC])).toEqual([]);
    expect(hits('background: var(--fill-orange); color: transparent; border: 1px solid var(--line)', [NAMED_CSS])).toEqual([]);
  });
});
