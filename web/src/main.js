import log from './log.js';
import { renderApp, renderLoading, renderError, renderTabBar, renderCoachTab, renderSettingsTab } from './views.js';
import {
  loadChatSession, saveChatSession, clearChatStorage,
  appendUserMessage, applyStreamEvent, isStreaming, setExpertMode, clearMessages, toApiHistory,
} from './chat.js';
import { loadSettings, saveSettings, isConfigured } from './settings.js';
import { streamChat, testConnection } from './api.js';

const base = import.meta.env.BASE_URL;
const appEl = document.getElementById('app');
const ACTIVE_TAB_KEY = 'swimcoach_active_tab';
const KNOWN_TABS = ['plan', 'coach', 'settings'];
const DEFAULT_ATHLETE_SLUG = 'renee';

// Central app state. main.js owns this; views.js stays pure (data in,
// markup out) and chat.js/settings.js own their own reducers/persistence
// so this object is mostly just "which slice is currently loaded".
const state = {
  tab: loadActiveTab(),
  plan: { status: 'loading', data: null, error: null },
  chat: loadChatSession(DEFAULT_ATHLETE_SLUG),
  settingsForm: loadSettings(),
  connectionTest: null,
  online: navigator.onLine,
};

function athleteSlug() {
  return state.plan.data?.slug || DEFAULT_ATHLETE_SLUG;
}

function loadActiveTab() {
  try {
    const stored = localStorage.getItem(ACTIVE_TAB_KEY);
    return KNOWN_TABS.includes(stored) ? stored : 'plan';
  } catch {
    return 'plan';
  }
}

function saveActiveTab(tab) {
  try {
    localStorage.setItem(ACTIVE_TAB_KEY, tab);
  } catch {
    // ignore
  }
}

// --- Rendering ---------------------------------------------------------------

function renderTabContent() {
  switch (state.tab) {
    case 'coach':
      return renderCoachTab({
        messages: state.chat.messages,
        expertMode: state.chat.expertMode,
        sending: isStreaming(state.chat),
        backendConfigured: isConfigured(state.settingsForm),
        online: state.online,
      });
    case 'settings':
      return renderSettingsTab({
        baseUrl: state.settingsForm.baseUrl,
        token: state.settingsForm.token,
        testStatus: state.connectionTest,
      });
    case 'plan':
    default:
      if (state.plan.status === 'loading') return renderLoading();
      if (state.plan.status === 'error') return renderError(state.plan.error);
      return renderApp(state.plan.data);
  }
}

function render() {
  appEl.innerHTML = `${renderTabContent()}${renderTabBar(state.tab)}`;
  if (state.tab === 'coach') stickChatScrollToBottom();
}

function stickChatScrollToBottom() {
  const list = document.getElementById('chat-messages');
  if (list) list.scrollTop = list.scrollHeight;
}

// --- Plan tab (unchanged data flow, now feeding into the shared shell) ------

async function fetchJson(path) {
  const res = await fetch(path);
  if (!res.ok) throw new Error(`${path} responded ${res.status}`);
  return res.json();
}

async function loadPlan() {
  try {
    const index = await fetchJson(`${base}data/index.json`);
    if (!Array.isArray(index) || index.length === 0) {
      throw new Error('no athletes in data/index.json');
    }
    const params = new URLSearchParams(location.search);
    const wanted = params.get('athlete');
    const entry = index.find((a) => a.slug === wanted) || index[0];

    const data = await fetchJson(`${base}data/${entry.slug}.json`);
    log.info('app.plan.loaded', {
      athlete_slug: data.slug,
      weeks: data.weeks.length,
      events: data.events.length,
    });
    state.plan = { status: 'ready', data, error: null };
    // The chat session was initially loaded under DEFAULT_ATHLETE_SLUG
    // before the real plan (and its athlete slug) was known -- reload it
    // under the real slug now, in case they ever differ (today there's
    // only one athlete, so this is a no-op in practice).
    if (data.slug && data.slug !== DEFAULT_ATHLETE_SLUG) {
      state.chat = loadChatSession(data.slug);
    }
  } catch (err) {
    log.error('app.plan.load_failed', { error: err.message });
    state.plan = { status: 'error', data: null, error: err.message };
  }
  render();
}

// --- Coach chat tab ----------------------------------------------------------

let chatAbortController = null;

function handleSendChat() {
  if (isStreaming(state.chat)) return;
  const input = document.getElementById('chat-input');
  const text = input?.value.trim();
  if (!text) return;

  const settings = state.settingsForm;
  if (!isConfigured(settings)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }

  const history = toApiHistory(state.chat.messages);
  state.chat = appendUserMessage(state.chat, text);
  if (input) input.value = '';
  render();
  persistChat();

  chatAbortController = new AbortController();
  log.info('chat.send', { athlete: athleteSlug(), expert_mode: state.chat.expertMode });

  streamChat({
    baseUrl: settings.baseUrl,
    token: settings.token,
    athlete: athleteSlug(),
    message: text,
    history,
    expertMode: state.chat.expertMode,
    signal: chatAbortController.signal,
    onEvent: (event) => {
      state.chat = applyStreamEvent(state.chat, event);
      if (event.type === 'done' || event.type === 'refusal' || event.type === 'error') {
        persistChat();
        log.info('chat.turn_complete', { type: event.type });
      }
      render();
    },
  });
}

function handleClearChat() {
  if (isStreaming(state.chat)) chatAbortController?.abort();
  state.chat = clearMessages(state.chat);
  clearChatStorage(athleteSlug());
  log.info('chat.cleared', { athlete: athleteSlug() });
  render();
}

function handleToggleExpertMode(checked) {
  state.chat = setExpertMode(state.chat, checked);
  persistChat();
  log.info('chat.expert_mode_toggled', { expert_mode: checked });
}

function persistChat() {
  saveChatSession(athleteSlug(), state.chat);
}

// --- Settings tab ------------------------------------------------------------

function handleSaveSettings() {
  const baseUrl = document.getElementById('settings-base-url')?.value ?? '';
  const token = document.getElementById('settings-token')?.value ?? '';
  state.settingsForm = saveSettings({ baseUrl, token });
  state.connectionTest = null;
  log.info('settings.saved', { has_base_url: !!state.settingsForm.baseUrl, has_token: !!state.settingsForm.token });
  render();
}

async function handleTestConnection() {
  // Test whatever is currently in the fields (may not be saved yet).
  const baseUrl = (document.getElementById('settings-base-url')?.value ?? '').trim().replace(/\/+$/, '');
  const token = (document.getElementById('settings-token')?.value ?? '').trim();
  if (!baseUrl) {
    state.connectionTest = { ok: false, message: 'Enter a backend URL first.' };
    render();
    return;
  }
  state.connectionTest = { ok: false, message: 'Testing…', pending: true };
  render();
  const result = await testConnection({ baseUrl, token });
  log.info('settings.test_connection', { ok: result.ok });
  state.connectionTest = result;
  render();
}

// --- Tab switching ------------------------------------------------------------

function setTab(tab) {
  if (!KNOWN_TABS.includes(tab) || tab === state.tab) return;
  state.tab = tab;
  saveActiveTab(tab);
  log.info('tab.switch', { tab });
  render();
}

// --- Event delegation ---------------------------------------------------------
// A single click/change/keydown listener on #app handles every `data-a`
// action across all tabs -- the DOM under #app is fully replaced on every
// render(), so delegation (rather than per-element listeners) is what
// survives that.

function onAppClick(e) {
  const el = e.target.closest('[data-a]');
  if (!el) return;
  const action = el.dataset.a;
  if (action.startsWith('tab:')) {
    setTab(action.slice(4));
    return;
  }
  switch (action) {
    case 'chat:send': handleSendChat(); break;
    case 'chat:clear': handleClearChat(); break;
    case 'settings:save': handleSaveSettings(); break;
    case 'settings:test': handleTestConnection(); break;
    default: break;
  }
}

function onAppChange(e) {
  if (e.target.matches('[data-a="chat:expert-toggle"]')) {
    handleToggleExpertMode(e.target.checked);
  }
}

function onAppKeydown(e) {
  if (e.target.id === 'chat-input' && e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSendChat();
  }
}

// --- Theme + offline (unchanged) ---------------------------------------------

function updateOfflineBanner() {
  const banner = document.getElementById('offline-banner');
  if (banner) banner.classList.toggle('show', !navigator.onLine);
}

function updateOnlineState() {
  state.online = navigator.onLine;
  updateOfflineBanner();
  if (state.tab === 'coach') render();
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

window.addEventListener('online', updateOnlineState);
window.addEventListener('offline', updateOnlineState);

appEl.addEventListener('click', onAppClick);
appEl.addEventListener('change', onAppChange);
appEl.addEventListener('keydown', onAppKeydown);

log.info('app.init', { version: __APP_VERSION__ ?? 'dev' });
updateOfflineBanner();
initTheme();
render();
loadPlan();
