import log from './log.js';
import { renderApp, renderLoading, renderError } from './views.js';

const base = import.meta.env.BASE_URL;
const appEl = document.getElementById('app');

function draw(html) {
  appEl.innerHTML = html;
}

function updateOfflineBanner() {
  const banner = document.getElementById('offline-banner');
  if (banner) banner.classList.toggle('show', !navigator.onLine);
}

async function fetchJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} responded ${res.status}`);
  return res.json();
}

async function boot() {
  draw(renderLoading());
  try {
    const index = await fetchJson(`${base}data/index.json`);
    if (!Array.isArray(index) || index.length === 0) {
      throw new Error('no athletes in data/index.json');
    }
    // Only one athlete exists today; a later ?athlete=<slug> query param
    // could select among several without changing this data contract.
    const params = new URLSearchParams(location.search);
    const wanted = params.get('athlete');
    const entry = index.find((a) => a.slug === wanted) || index[0];

    const data = await fetchJson(`${base}data/${entry.slug}.json`);
    log.info('app.plan.loaded', {
      athlete_slug: data.slug,
      weeks: data.weeks.length,
      events: data.events.length,
    });
    draw(renderApp(data));
  } catch (err) {
    log.error('app.plan.load_failed', { error: err.message });
    draw(renderError(err.message));
  }
}

function initTheme() {
  const btn = document.getElementById('themebtn');
  btn?.addEventListener('click', () => {
    const root = document.documentElement;
    const current = root.getAttribute('data-theme')
      || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    const next = current === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    log.info('theme.toggle', { theme: next });
  });
}

window.addEventListener('online', updateOfflineBanner);
window.addEventListener('offline', updateOfflineBanner);

log.info('app.init', { version: __APP_VERSION__ ?? 'dev' });
updateOfflineBanner();
initTheme();
boot();
