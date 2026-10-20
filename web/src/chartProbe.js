// Touch/hover probe for the race view's power charts: a vertical marker plus a readout line under the
// chart. Writes straight to the DOM (a probe never re-renders the page). Maths lives in raceView.js.
// The chart wrapper is `touch-action: pan-y`, so vertical scrolling still works over it.

import { probeIndex, probeLeftPct, probeReadout } from './raceView.js';
import log from './log.js';

function seriesOf(wrap) {
  try {
    return JSON.parse(wrap.dataset.probe);
  } catch (err) {
    log.warn('chart_probe.bad_series', { error: err.message });
    return null;
  }
}

function probe(e) {
  const wrap = e.target.closest?.('.rv-probe');
  if (!wrap) return;
  const series = seriesOf(wrap);
  const n = series?.w?.length || 0;
  if (n < 2) return;
  const i = probeIndex(e.clientX, wrap.getBoundingClientRect(), n);
  const line = wrap.querySelector('.rv-probe-line');
  if (line) {
    line.hidden = false;
    line.style.left = `${probeLeftPct(i, n)}%`;
  }
  const read = document.getElementById(wrap.dataset.probeRead);
  if (read) read.textContent = probeReadout(series, i);
}

/** `root` is the delegated container (#app). */
export function attachChartProbes(root) {
  root.addEventListener('pointermove', probe);
  root.addEventListener('pointerdown', probe);
}
