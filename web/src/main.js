import log from './log.js';
import {
  renderApp, renderLoading, renderError, renderTabBar, renderCoachTab, renderSettingsTab,
  renderLogTab, renderCheckinTab, renderBackendNeededNotice, renderFeedbackTab,
} from './views.js';
import {
  loadChatSession, saveChatSession, clearChatStorage,
  appendUserMessage, applyStreamEvent, isStreaming, setExpertMode, clearMessages, toApiHistory,
} from './chat.js';
import { loadSettings, saveSettings, isConfigured } from './settings.js';
import {
  streamChat, testConnection, postWorkout, postWellness, fetchPlan, getAthlete, patchAthlete,
  postFeedback, listFeedback,
} from './api.js';
import {
  serializeWorkoutForm, serializeWellnessForm, profileFormFromAthlete, serializeProfileForm,
  serializeFeedbackForm,
} from './forms.js';
import { currentIdentity, signIn, signOut } from './identity.js';

const appEl = document.getElementById('app');
const ACTIVE_TAB_KEY = 'swimcoach_active_tab';
const KNOWN_TABS = ['plan', 'log', 'checkin', 'coach', 'feedback', 'settings'];
// Chat sessions are keyed per-athlete in localStorage (see chat.js); this is
// just the storage key used before any real identity has ever signed in.
const SIGNED_OUT_CHAT_KEY = 'signed-out';

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function createLogForm() {
  return { date: todayIso(), sport: 'swim_pool', distance_m: '', duration_min: '', rpe: 5, notes: '' };
}

function createCheckinForm() {
  return {
    date: todayIso(), sleep_quality: 3, sleep_hours: '', stress: 3, soreness: 3, motivation: 3,
    resting_hr: '', hrv: '', notes: '',
  };
}

function createProfileForm() {
  return {
    name: '', dob: '', sex: '', heightFeet: '', heightInches: '', weightLb: '', cssPace: '',
    poolDays: {
      monday: false, tuesday: false, wednesday: false, thursday: false, friday: false, saturday: false, sunday: false,
    },
  };
}

function createFeedbackForm() {
  return { type: 'feature_request', body: '' };
}

const initialIdentity = currentIdentity();

// Central app state. main.js owns this; views.js stays pure (data in,
// markup out) and chat.js/settings.js own their own reducers/persistence
// so this object is mostly just "which slice is currently loaded".
//
// `identity` (see src/identity.js) is the signed-in Google account resolved
// to {email, athlete, role} -- it drives which athlete every API call
// targets. It's UX-only, not a security boundary: the backend still just
// checks the shared bearer token in settingsForm. Signed out (identity ===
// null), the app forces the Settings tab (the sign-in gate) instead of
// defaulting to any particular athlete.
const state = {
  tab: initialIdentity ? loadActiveTab() : 'settings',
  identity: initialIdentity,
  identityError: null,
  plan: { status: 'idle', data: null, error: null },
  chat: loadChatSession(initialIdentity?.athlete || SIGNED_OUT_CHAT_KEY),
  settingsForm: loadSettings(),
  connectionTest: null,
  online: navigator.onLine,
  logForm: createLogForm(),
  logSubmit: { status: 'idle', message: null },
  checkinForm: createCheckinForm(),
  checkinSubmit: { status: 'idle', message: null },
  profileForm: createProfileForm(),
  profileLoad: { status: 'idle', error: null },
  profileSubmit: { status: 'idle', message: null },
  feedbackForm: createFeedbackForm(),
  feedbackSubmit: { status: 'idle', message: null },
  feedbackEntries: { status: 'idle', data: [] },
};

function athleteSlug() {
  return state.identity?.athlete || null;
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
  // Folds both "backend URL + token saved" and "signed in" into one flag --
  // see settings.js's isConfigured. Every write/chat/plan feature needs both,
  // and either gap is fixed the same way (visit Settings), so one generic
  // notice covers both cases (see the message text in views.js).
  const backendConfigured = isConfigured(state.settingsForm, state.identity);
  switch (state.tab) {
    case 'log':
      return renderLogTab({
        form: state.logForm,
        submit: state.logSubmit,
        backendConfigured,
        online: state.online,
      });
    case 'checkin':
      return renderCheckinTab({
        form: state.checkinForm,
        submit: state.checkinSubmit,
        backendConfigured,
        online: state.online,
      });
    case 'coach':
      return renderCoachTab({
        messages: state.chat.messages,
        expertMode: state.chat.expertMode,
        sending: isStreaming(state.chat),
        backendConfigured,
        online: state.online,
        role: state.identity?.role,
      });
    case 'feedback':
      return renderFeedbackTab({
        form: state.feedbackForm,
        submit: state.feedbackSubmit,
        entries: state.feedbackEntries.data,
        entriesStatus: state.feedbackEntries.status,
        backendConfigured,
        online: state.online,
      });
    case 'settings':
      return renderSettingsTab({
        baseUrl: state.settingsForm.baseUrl,
        token: state.settingsForm.token,
        testStatus: state.connectionTest,
        identity: state.identity,
        identityError: state.identityError,
        backendConfigured,
        profileForm: state.profileForm,
        profileLoad: state.profileLoad,
        profileSubmit: state.profileSubmit,
      });
    case 'plan':
    default:
      if (!backendConfigured) {
        return renderBackendNeededNotice('The Plan tab needs you to sign in and set a backend URL and token in Settings.');
      }
      if (state.plan.status === 'loading' || state.plan.status === 'idle') return renderLoading();
      if (state.plan.status === 'error') return renderError(state.plan.error);
      return renderApp(state.plan.data);
  }
}

function render() {
  appEl.innerHTML = `${renderTabContent()}${renderTabBar(state.tab)}`;
  if (state.tab === 'coach') stickChatScrollToBottom();
  if (state.tab === 'settings' && !state.identity) mountGoogleSignIn();
}

// Mounts (or re-mounts, on every Settings re-render while signed out) the
// real Google Sign-In button into the placeholder div views.js renders. This
// is the one bit of DOM glue identity.js's signIn() needs from main.js --
// see identity.js for why the actual GIS init/decode/resolve logic lives
// there instead, kept unit-testable and separate from this DOM wiring.
function mountGoogleSignIn() {
  const buttonEl = document.getElementById('google-signin-btn');
  if (!buttonEl) return;
  signIn({ buttonEl, onIdentity: handleIdentityResolved });
}

function handleIdentityResolved(identity) {
  if (!identity) {
    state.identityError = "Signed in, but that Google account isn't an authorized user of this app.";
    render();
    return;
  }
  state.identity = identity;
  state.identityError = null;
  state.chat = loadChatSession(identity.athlete);
  // Left idle rather than eagerly fetched here -- setTab('plan') lazily
  // loads it (or retries) the moment the Plan tab is actually visited, which
  // is also what covers the "just saved settings, now ready" case, so there
  // isn't a second load-triggering path to keep in sync with this one.
  state.plan = { status: 'idle', data: null, error: null };
  state.profileForm = createProfileForm();
  state.profileLoad = { status: 'idle', error: null };
  state.profileSubmit = { status: 'idle', message: null };
  // Same lazy-load convention for the Feedback tab's list (see setTab).
  state.feedbackEntries = { status: 'idle', data: [] };
  log.info('identity.resolved', { athlete: identity.athlete, role: identity.role });
  render();
  maybeLoadProfile();
}

function handleSignOut() {
  signOut();
  state.identity = null;
  state.identityError = null;
  state.chat = loadChatSession(SIGNED_OUT_CHAT_KEY);
  state.plan = { status: 'idle', data: null, error: null };
  state.profileForm = createProfileForm();
  state.profileLoad = { status: 'idle', error: null };
  state.profileSubmit = { status: 'idle', message: null };
  state.feedbackEntries = { status: 'idle', data: [] };
  state.tab = 'settings';
  saveActiveTab('settings');
  log.info('identity.signed_out', {});
  render();
}

function stickChatScrollToBottom() {
  const list = document.getElementById('chat-messages');
  if (list) list.scrollTop = list.scrollHeight;
}

// --- Plan tab ----------------------------------------------------------------
// Fetches the live GET /api/plan?athlete=<slug> from the backend (see
// api.js's fetchPlan) instead of the static baked data/<slug>.json, so each
// signed-in identity sees their own (live) plan. The service worker's
// NetworkFirst runtimeCaching entry for /api/plan (see vite.config.js) keeps
// this working offline after the first successful load.

async function loadPlan() {
  const settings = state.settingsForm;
  const identity = state.identity;
  if (!isConfigured(settings, identity)) {
    state.plan = { status: 'idle', data: null, error: null };
    render();
    return;
  }

  state.plan = { status: 'loading', data: state.plan.data, error: null };
  render();

  const result = await fetchPlan({ baseUrl: settings.baseUrl, token: settings.token, athlete: identity.athlete });
  if (result.ok) {
    log.info('app.plan.loaded', {
      athlete_slug: result.data.slug,
      weeks: result.data.weeks?.length ?? 0,
      events: result.data.events?.length ?? 0,
    });
    state.plan = { status: 'ready', data: result.data, error: null };
  } else {
    log.error('app.plan.load_failed', { error: result.error });
    state.plan = { status: 'error', data: null, error: result.error };
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
  if (!isConfigured(settings, state.identity)) {
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
  // No eager (re)fetch of the plan here -- setTab('plan') lazily loads it
  // (or retries a previous error) the moment the Plan tab is actually
  // visited, so saving Settings from any other tab never fires an
  // unsolicited /api/plan request. The profile section, though, lives on
  // this same tab -- becoming "configured" right here is exactly the moment
  // it should fetch, so maybeLoadProfile() is called explicitly.
  maybeLoadProfile();
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

// --- Log tab (workout logging) ------------------------------------------------

async function handleSubmitLog() {
  if (state.logSubmit.status === 'submitting') return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }

  const payload = serializeWorkoutForm(state.logForm);
  state.logSubmit = { status: 'submitting', message: null };
  render();
  log.info('log.submit', { athlete: athleteSlug(), sport: payload.sport });

  const result = await postWorkout({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), payload,
  });
  if (result.ok) {
    log.info('log.submit_success', { athlete: athleteSlug() });
    state.logForm = createLogForm();
    state.logSubmit = { status: 'success', message: 'Saved.' };
  } else {
    log.error('log.submit_failed', { athlete: athleteSlug(), error: result.error });
    state.logSubmit = { status: 'error', message: result.error };
  }
  render();
}

// --- Check-in tab (daily wellness) ---------------------------------------------

async function handleSubmitCheckin() {
  if (state.checkinSubmit.status === 'submitting') return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }

  const payload = serializeWellnessForm(state.checkinForm);
  state.checkinSubmit = { status: 'submitting', message: null };
  render();
  log.info('checkin.submit', { athlete: athleteSlug() });

  const result = await postWellness({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), payload,
  });
  if (result.ok) {
    log.info('checkin.submit_success', { athlete: athleteSlug() });
    state.checkinForm = createCheckinForm();
    state.checkinSubmit = { status: 'success', message: 'Saved.' };
  } else {
    log.error('checkin.submit_failed', { athlete: athleteSlug(), error: result.error });
    state.checkinSubmit = { status: 'error', message: result.error };
  }
  render();
}

// --- Profile edit (Settings tab section) --------------------------------------
// Self-service profile editing (Phase 2.5): GET /api/athlete prefills the
// form the moment the Settings tab is opened (or becomes configured), PATCH
// saves it. Lazy-loaded the same way loadPlan() is -- see setTab() below --
// rather than eagerly fetched on every identity/settings change.

async function loadProfile() {
  const settings = state.settingsForm;
  const identity = state.identity;
  if (!isConfigured(settings, identity)) {
    state.profileLoad = { status: 'idle', error: null };
    render();
    return;
  }

  state.profileLoad = { status: 'loading', error: null };
  render();

  const result = await getAthlete({ baseUrl: settings.baseUrl, token: settings.token, athlete: identity.athlete });
  if (result.ok) {
    log.info('profile.loaded', { athlete: identity.athlete });
    state.profileForm = profileFormFromAthlete(result.data);
    state.profileLoad = { status: 'ready', error: null };
  } else {
    log.error('profile.load_failed', { athlete: identity.athlete, error: result.error });
    state.profileLoad = { status: 'error', error: result.error };
  }
  render();
}

// --- Feedback tab (durable feedback log) ---------------------------------------

async function loadFeedback() {
  const settings = state.settingsForm;
  const identity = state.identity;
  if (!isConfigured(settings, identity)) {
    state.feedbackEntries = { status: 'idle', data: [] };
    render();
    return;
  }

  state.feedbackEntries = { status: 'loading', data: state.feedbackEntries.data };
  render();

  const result = await listFeedback({ baseUrl: settings.baseUrl, token: settings.token, athlete: identity.athlete });
  if (result.ok) {
    log.info('feedback.list_loaded', { athlete: identity.athlete, count: result.data.length });
    state.feedbackEntries = { status: 'ready', data: result.data };
  } else {
    log.error('feedback.list_load_failed', { error: result.error });
    state.feedbackEntries = { status: 'error', data: [] };
  }
  render();
}

// Triggers loadProfile() only when it's actually useful: on the Settings tab,
// backend+identity configured, and not already loading/loaded. Safe to call
// from anywhere (identity resolution, settings save, tab switch) without
// double-fetching or fetching while the athlete is looking at another tab.
function maybeLoadProfile() {
  if (state.tab !== 'settings') return;
  if (!isConfigured(state.settingsForm, state.identity)) return;
  if (state.profileLoad.status === 'loading' || state.profileLoad.status === 'ready') return;
  loadProfile();
}

async function handleSubmitProfile() {
  if (state.profileSubmit.status === 'submitting') return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  const payload = serializeProfileForm(state.profileForm);
  state.profileSubmit = { status: 'submitting', message: null };
  render();
  log.info('profile.submit', { athlete: athleteSlug() });

  const result = await patchAthlete({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), payload,
  });
  if (result.ok) {
    log.info('profile.submit_success', { athlete: athleteSlug() });
    state.profileForm = profileFormFromAthlete(result.data);
    state.profileSubmit = { status: 'success', message: 'Saved.' };
  } else {
    log.error('profile.submit_failed', { athlete: athleteSlug(), error: result.error });
    state.profileSubmit = { status: 'error', message: result.error };
  }
  render();
}

async function handleSubmitFeedback() {
  if (state.feedbackSubmit.status === 'submitting') return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }

  const payload = serializeFeedbackForm(state.feedbackForm);
  if (!payload.body) {
    state.feedbackSubmit = { status: 'error', message: 'Add some details first.' };
    render();
    return;
  }

  state.feedbackSubmit = { status: 'submitting', message: null };
  render();
  log.info('feedback.submit', { athlete: athleteSlug(), type: payload.type });

  const result = await postFeedback({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), payload,
  });
  if (result.ok) {
    log.info('feedback.submit_success', { athlete: athleteSlug() });
    state.feedbackForm = createFeedbackForm();
    state.feedbackSubmit = { status: 'success', message: 'Saved.' };
    loadFeedback(); // calls render() itself
  } else {
    log.error('feedback.submit_failed', { athlete: athleteSlug(), error: result.error });
    state.feedbackSubmit = { status: 'error', message: result.error };
    render();
  }
}

// --- Tab switching ------------------------------------------------------------

function setTab(tab) {
  if (!KNOWN_TABS.includes(tab) || tab === state.tab) return;
  state.tab = tab;
  saveActiveTab(tab);
  log.info('tab.switch', { tab });
  // Lazily (re)loads the plan the moment the Plan tab is actually visited,
  // rather than eagerly on every settings-save / sign-in -- covers both
  // "never loaded yet" (idle) and "let's retry" (a previous fetch errored).
  if (tab === 'plan' && (state.plan.status === 'idle' || state.plan.status === 'error')
    && isConfigured(state.settingsForm, state.identity)) {
    loadPlan(); // calls render() itself
    return;
  }
  if (tab === 'feedback' && (state.feedbackEntries.status === 'idle' || state.feedbackEntries.status === 'error')
    && isConfigured(state.settingsForm, state.identity)) {
    loadFeedback(); // calls render() itself
    return;
  }
  render();
  maybeLoadProfile();
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
    case 'log:submit': handleSubmitLog(); break;
    case 'checkin:submit': handleSubmitCheckin(); break;
    case 'profile:submit': handleSubmitProfile(); break;
    case 'feedback:submit': handleSubmitFeedback(); break;
    case 'identity:signout': handleSignOut(); break;
    default: break;
  }
}

function onAppChange(e) {
  if (e.target.matches('[data-a="chat:expert-toggle"]')) {
    handleToggleExpertMode(e.target.checked);
  }
}

// Log/Check-in form fields carry `data-form`/`data-field` instead of feeding
// through full state + render() on every keystroke -- a full re-render on
// every keystroke would tear out focus and slider drag position (the DOM
// under #app is fully replaced each render()). Instead this handler mutates
// `state.logForm`/`state.checkinForm` directly (read back on submit) and,
// for range sliders, updates their `data-slider-out` <output> label in
// place -- no render() call here.
function onAppInput(e) {
  const el = e.target;
  const formName = el.dataset.form;
  const field = el.dataset.field;
  if (!formName || !field) return;

  if (formName === 'log') state.logForm[field] = el.value;
  else if (formName === 'checkin') state.checkinForm[field] = el.value;
  else if (formName === 'profile') {
    if (field === 'pool_days') {
      // Each pool-day checkbox carries data-day (see views.js's
      // POOL_DAY_LABELS) instead of a distinct data-field, since they all
      // toggle keys within the same profileForm.poolDays map.
      const day = el.dataset.day;
      if (day) state.profileForm.poolDays[day] = el.checked;
    } else {
      state.profileForm[field] = el.value;
    }
  }
  else if (formName === 'feedback') state.feedbackForm[field] = el.value;

  const outId = el.dataset.sliderOut;
  if (outId) {
    const out = document.getElementById(outId);
    if (out) out.textContent = el.value;
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
appEl.addEventListener('input', onAppInput);
appEl.addEventListener('keydown', onAppKeydown);

log.info('app.init', { version: __APP_VERSION__ ?? 'dev' });
updateOfflineBanner();
initTheme();
render();
loadPlan();
maybeLoadProfile();
