import './fonts.js';
import { registerSW } from 'virtual:pwa-register';
import log from './log.js';
import {
  renderApp, renderLoading, renderError, renderTabBar, renderCoachTab, renderSettingsTab,
  renderLogTab, renderCheckinTab, renderBackendNeededNotice, renderFeedbackTab, renderUpdateBanner,
  renderOnboardingForm,
} from './views.js';
import {
  loadChatSession, saveChatSession, clearChatStorage,
  appendUserMessage, applyStreamEvent, isStreaming, setExpertMode, clearMessages, toApiHistory,
} from './chat.js';
import { loadSettings, saveSettings, isConfigured } from './settings.js';
import {
  streamChat, postWorkout, postWellness, fetchPlan, getAthlete, patchAthlete,
  postFeedback, listFeedback, uploadWorkoutFile, listWorkouts, syncWorkouts, logout, onboard,
} from './api.js';
import {
  serializeWorkoutForm, serializeWellnessForm, profileFormFromAthlete, serializeProfileForm,
  serializeFeedbackForm, logFormFromDraft,
} from './forms.js';
import { currentIdentity, signIn, signOut, saveIdentity } from './identity.js';
import {
  createOnboardingState, validateOnboardForm, onboardPayloadFromForm,
  loadOnboardingActive, saveOnboardingActive, startOnboardingSession, identityFromOnboardSession,
} from './onboarding.js';
import { sortWorkoutsNewestFirst, HISTORY_DISPLAY_CAP, formatSyncResult } from './workouts.js';
import { performSignOut } from './session.js';
import {
  createPwaUpdateState, markNeedRefresh, markOfflineReady,
  dismissNeedRefresh, dismissOfflineReady, triggerUpdate,
} from './pwaUpdate.js';

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
  return {
    date: todayIso(), sport: 'swim_pool', distance_m: '', duration_min: '', rpe: 5, notes: '',
    // Set by logFormFromDraft (forms.js) once a file has been parsed -- see
    // handleLogFileSelected. `source` (fit/tcx/csv) rides along to the
    // confirm-save POST /api/workouts call; `warnings` is read by
    // views.js's renderLogTab review card and never sent to the backend.
    source: null,
    warnings: [],
  };
}

function createLogIngest() {
  return { status: 'idle', fileName: null, error: null };
}

function createLogSync() {
  return { status: 'idle', message: null };
}

// The single source of truth for "which file extensions the Log tab's
// upload accepts," checked client-side before ever making a network call --
// the backend (see backend/app/routes/workouts.py's PARSERS_BY_EXTENSION)
// enforces the same allowlist independently, so a stale/bypassed client
// check can never let an unsupported file actually get ingested.
const SUPPORTED_INGEST_EXTENSIONS = ['.fit', '.tcx', '.csv'];

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
const initialSettingsForm = loadSettings();
// True only when there's no resolved athlete identity, an onboarding
// session token is actually sitting in settings, AND the last thing this
// browser did was start (not finish) onboarding -- see src/onboarding.js's
// loadOnboardingActive doc comment for why this is a separate flag rather
// than folded into identity.js's own storage. All three must hold: a signed
// -out athlete with a stale flag (e.g. after a full sign-out cleared the
// token but somehow not this flag) must never show the onboarding form with
// no token to submit against.
const initialOnboardingActive = !initialIdentity && !!initialSettingsForm.token && loadOnboardingActive();

// Central app state. main.js owns this; views.js stays pure (data in,
// markup out) and chat.js/settings.js/onboarding.js own their own
// reducers/persistence so this object is mostly just "which slice is
// currently loaded".
//
// `identity` (see src/identity.js) is the signed-in Google account resolved
// to {name, athlete, role} -- it drives which athlete every API call
// targets. The backend resolves and enforces this (POST /api/auth/google
// mints a session bound to one athlete; require_auth/resolve_athlete 403 a
// session requesting a different athlete) -- identity here is just the
// frontend's copy of what the backend already decided. Signed out (identity
// === null), the app forces the Settings tab (the sign-in gate) instead of
// defaulting to any particular athlete.
//
// `onboarding` (see src/onboarding.js's createOnboardingState) is the third
// state alongside "signed out" and "signed in as an athlete": allowlisted,
// but no athlete exists yet. While `onboarding.active` is true, `identity`
// stays null (there IS no athlete yet) and render() shows the onboarding
// form instead of both the sign-in gate and the ordinary tabs -- see
// handleIdentityResolved's onboarding branch and handleOnboardSubmit below.
const state = {
  tab: initialIdentity ? loadActiveTab() : 'settings',
  identity: initialIdentity,
  identityError: null,
  onboarding: {
    ...createOnboardingState(),
    active: initialOnboardingActive,
    token: initialOnboardingActive ? initialSettingsForm.token : null,
  },
  plan: { status: 'idle', data: null, error: null },
  chat: loadChatSession(initialIdentity?.athlete || SIGNED_OUT_CHAT_KEY),
  settingsForm: initialSettingsForm,
  online: navigator.onLine,
  // The "new version -- reload" prompt (see src/pwaUpdate.js / views.js's
  // renderUpdateBanner) -- fed by registerSW()'s onNeedRefresh/onOfflineReady
  // callbacks at the bottom of this file.
  pwaUpdate: createPwaUpdateState(),
  logForm: createLogForm(),
  logSubmit: { status: 'idle', message: null },
  logIngest: createLogIngest(),
  logSync: createLogSync(),
  // Secondary manual-entry/upload section is collapsed by default (Phase 3:
  // "Sync from watch" is the Log tab's primary action) -- reset on leaving
  // the Log tab (setTab), same convention as workoutDetailId below.
  logManualOpen: false,
  workoutHistory: { status: 'idle', data: [], error: null },
  // Slice 2: null shows the history list; a workout id opens that
  // workout's in-tab detail view instead (see views.js's renderHistorySection).
  // Reset on leaving the Log tab (setTab) and pruned in loadHistory if a
  // refresh's new data no longer contains the id.
  workoutDetailId: null,
  // The detail view's embedded scoped chat (Phase C slice 1):
  // {workoutId, messages} while a detail is open, null otherwise.
  // Deliberately EPHEMERAL -- in-memory only, never persisted, cleared
  // whenever the detail closes (closeWorkoutChat) -- a scoped thread about
  // one workout isn't a durable conversation worth carrying across
  // sessions the way the Coach tab's chat is (chat.js's localStorage).
  workoutChat: null,
  checkinForm: createCheckinForm(),
  checkinSubmit: { status: 'idle', message: null },
  profileForm: createProfileForm(),
  profileLoad: { status: 'idle', error: null },
  profileSubmit: { status: 'idle', message: null },
  feedbackForm: createFeedbackForm(),
  feedbackSubmit: { status: 'idle', message: null },
  feedbackEntries: { status: 'idle', data: [] },
};

// Set once at boot by registerSW() (see the bottom of this file) -- the
// function it returns, which handleReloadForUpdate calls (via
// pwaUpdate.js's triggerUpdate) to activate a waiting service worker.
let updateSW = null;

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
        ingest: state.logIngest,
        backendConfigured,
        online: state.online,
        history: state.workoutHistory,
        detailId: state.workoutDetailId,
        sync: state.logSync,
        manualOpen: state.logManualOpen,
        workoutChat: state.workoutChat,
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
  // Onboarding is a full-screen gate, same spirit as the sign-in gate but
  // replacing the tab bar entirely rather than just one tab's content --
  // there's nothing else useful to navigate to yet (no athlete, so no plan/
  // log/checkin/coach/feedback/profile exists to show). See
  // src/onboarding.js's createOnboardingState / handleOnboardingSessionStarted.
  if (state.onboarding.active) {
    appEl.innerHTML = `${renderUpdateBanner(state.pwaUpdate)}${renderOnboardingForm({
      form: state.onboarding.form,
      submitting: state.onboarding.submitting,
      error: state.onboarding.error,
    })}`;
    return;
  }
  appEl.innerHTML = `${renderUpdateBanner(state.pwaUpdate)}${renderTabContent()}${renderTabBar(state.tab)}`;
  if (state.tab === 'coach') stickChatScrollToBottom();
  if (state.tab === 'log' && state.workoutChat) stickWorkoutChatScrollToBottom();
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
  signIn({ buttonEl, baseUrl: state.settingsForm.baseUrl, onIdentity: handleIdentityResolved });
}

/** Shared tail of "we now have a brand-new athlete-bound session" --
 * fired from both an ordinary Google sign-in (handleIdentityResolved below)
 * and a just-completed onboarding submit (handleOnboardSubmit) since both
 * end up in the exact same place: a resolved {name, athlete, role} identity
 * plus a fresh athlete-bound session token. Persists the token into
 * settingsForm (not identity.js -- token storage is settings.js's job) so
 * every existing api.js call site keeps reading settingsForm.token exactly
 * as before; only *where* that token comes from differs between the two
 * callers. Every identity-scoped slice of state resets to idle/empty the
 * same way it does on any fresh sign-in -- a just-onboarded athlete has no
 * cached plan/profile/history/feedback from a previous session to carry
 * over. */
function applyAthleteSession(identity, token) {
  state.identity = identity;
  state.identityError = null;
  state.settingsForm = saveSettings({ baseUrl: state.settingsForm.baseUrl, token });
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
  state.workoutHistory = { status: 'idle', data: [], error: null };
  state.workoutDetailId = null;
  closeWorkoutChat();
}

/** Fired once per real Google sign-in attempt with the outcome of the
 * exchange (see identity.js's signIn doc comment for the exact shape). */
function handleIdentityResolved(outcome) {
  if (!outcome?.ok) {
    state.identityError = outcome?.message
      || "Signed in, but that Google account isn't an authorized user of this app.";
    render();
    return;
  }
  if (outcome.onboarding) {
    handleOnboardingSessionStarted(outcome);
    return;
  }
  applyAthleteSession(outcome.identity, outcome.token);
  log.info('identity.resolved', { athlete: outcome.identity.athlete, role: outcome.identity.role });
  render();
  maybeLoadProfile();
}

/** Resets every identity-scoped slice of state back to signed-out and
 * routes to the Settings tab (the sign-in gate) -- the common tail shared by
 * an explicit sign-out (handleSignOut) and an involuntary one (a 401 from
 * any API call, see handleSessionExpired). Does NOT touch settingsForm or
 * call identity.js's signOut()/api.js's logout() -- callers do that
 * themselves first, since they differ (an expired session has nothing valid
 * left to revoke). */
function resetToSignedOut({ identityError = null } = {}) {
  state.identity = null;
  state.identityError = identityError;
  state.onboarding = createOnboardingState();
  saveOnboardingActive(false);
  state.chat = loadChatSession(SIGNED_OUT_CHAT_KEY);
  state.plan = { status: 'idle', data: null, error: null };
  state.profileForm = createProfileForm();
  state.profileLoad = { status: 'idle', error: null };
  state.profileSubmit = { status: 'idle', message: null };
  state.feedbackEntries = { status: 'idle', data: [] };
  state.workoutHistory = { status: 'idle', data: [], error: null };
  state.workoutDetailId = null;
  closeWorkoutChat();
  state.tab = 'settings';
  saveActiveTab('settings');
}

/** Revokes the server session (best-effort -- see api.js's `logout` doc
 * comment for why it never throws), clears the identity, and empties the
 * stored session token (see session.js's `performSignOut` for the pure,
 * unit-tested core of this) before resetting every identity-scoped slice of
 * state and routing back to the sign-in gate. Awaited by the click handler
 * (see onAppClick's `identity:signout` case) so the revoke call actually
 * fires before this function returns -- sign-out itself still feels
 * instant to the athlete since there's nothing else to wait on afterward. */
async function handleSignOut() {
  state.settingsForm = await performSignOut({
    settingsForm: state.settingsForm, logout, saveSettings, signOut,
  });
  resetToSignedOut();
  log.info('identity.signed_out', {});
  render();
}

/** Every api.js call site funnels its result through this before doing its
 * own ok/error branching -- a 401 means the session token is no longer
 * valid (expired, or revoked by a sign-out elsewhere), and there is no
 * refresh endpoint by design (see identity.js), so the only way forward is
 * a fresh Google sign-in. Returns true (caller should bail out, having
 * already rendered) when it handled a 401; false otherwise. */
function handleUnauthorized(result) {
  if (result?.status !== 401) return false;
  handleSessionExpired();
  return true;
}

function handleSessionExpired() {
  signOut();
  state.settingsForm = saveSettings({ baseUrl: state.settingsForm.baseUrl, token: '' });
  resetToSignedOut({ identityError: 'Your session expired -- sign in again.' });
  log.warn('identity.session_expired', {});
  render();
}

// --- Onboarding form (Slice 3 of self-service in-app onboarding) -----------
// Fired from identity.js's signIn() when the Google exchange resolves to an
// onboarding-scoped session (allowlisted, no athlete yet -- see that
// module's doc comment), and from the form's own submit handler below. See
// src/onboarding.js for the pure form-state/validation/payload logic this
// wiring delegates to, and views.js's renderOnboardingForm for the markup.

/** Enters onboarding mode: persists the onboarding-scoped token (settings.js
 * storage, same as an ordinary session token -- every api.js call already
 * reads settingsForm.token) and the "mid-onboarding" flag (see
 * onboarding.js's saveOnboardingActive doc comment for why that's a
 * separate flag from settingsForm/identity.js), then renders the form.
 * state.identity stays null throughout -- there is no athlete yet. */
function handleOnboardingSessionStarted(outcome) {
  state.identity = null;
  state.identityError = null;
  const next = startOnboardingSession({ outcome, settingsForm: state.settingsForm, saveSettings });
  state.settingsForm = next.settingsForm;
  state.onboarding = next.onboarding;
  saveOnboardingActive(true);
  log.info('onboard.session_started', {});
  render();
}

async function handleOnboardSubmit() {
  if (state.onboarding.submitting) return;

  const { valid, errors } = validateOnboardForm(state.onboarding.form);
  if (!valid) {
    state.onboarding = { ...state.onboarding, error: errors.join(' ') };
    log.warn('onboard.validation_failed', { error_count: errors.length });
    render();
    return;
  }

  const payload = onboardPayloadFromForm(state.onboarding.form);
  state.onboarding = { ...state.onboarding, submitting: true, error: null };
  render();
  log.info('onboard.submit', {});

  try {
    const session = await onboard({
      baseUrl: state.settingsForm.baseUrl, token: state.onboarding.token, payload,
    });
    const identity = identityFromOnboardSession(session);
    saveIdentity(identity);
    applyAthleteSession(identity, session.token);
    state.onboarding = createOnboardingState();
    saveOnboardingActive(false);
    // Unlike an ordinary Google sign-in (which happens FROM the Settings
    // tab and just stays there -- see handleIdentityResolved), onboarding
    // has no "tab" to fall back to: there was never a normal app underneath
    // it (render() replaced the whole tab bar while onboarding.active was
    // true). Land the newly-provisioned athlete straight on their plan
    // rather than an empty Settings tab -- that's the whole point of
    // finishing onboarding.
    state.tab = 'plan';
    saveActiveTab('plan');
    log.info('onboard.success', { athlete: identity.athlete });
    render();
    loadPlan(); // calls render() itself
    maybeLoadProfile();
  } catch (err) {
    // A 401 here means the onboarding session itself expired/was revoked
    // mid-fill -- no amount of retrying the form will fix that, so route
    // back to the sign-in gate the same way any other 401 does
    // (handleUnauthorized/handleSessionExpired), rather than showing an
    // inline error the athlete can't act on. Every other failure (403/409
    // from api.js's onboard, 422 validation, network) is shown inline with
    // the form's entered data left exactly as-is, so the athlete can fix
    // the one field it complained about (e.g. a taken slug) and resubmit
    // without retyping everything.
    if (err.status === 401) {
      handleSessionExpired();
      return;
    }
    log.error('onboard.failed', { error: err.message, status: err.status });
    state.onboarding = { ...state.onboarding, submitting: false, error: err.message };
    render();
  }
}

// --- PWA update prompt ---------------------------------------------------
// Thin wiring around src/pwaUpdate.js's pure reducers/predicate -- see that
// module's doc comment for why the state logic lives there instead of here
// (unit-testable without importing this file's `virtual:pwa-register`
// import, a Vite build-time-only module). registerSW() itself is called
// once, at boot, at the bottom of this file.

function handleReloadForUpdate() {
  log.info('pwa.update_reload', {});
  triggerUpdate(updateSW);
}

function handleDismissNeedRefresh() {
  state.pwaUpdate = dismissNeedRefresh(state.pwaUpdate);
  render();
}

function handleDismissOfflineReady() {
  state.pwaUpdate = dismissOfflineReady(state.pwaUpdate);
  render();
}

function stickChatScrollToBottom() {
  const list = document.getElementById('chat-messages');
  if (list) list.scrollTop = list.scrollHeight;
}

function stickWorkoutChatScrollToBottom() {
  const list = document.getElementById('workout-chat-messages');
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
  if (handleUnauthorized(result)) return;
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
      if (event.type === 'error' && event.status === 401) {
        handleSessionExpired();
        return;
      }
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
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('log.submit_success', { athlete: athleteSlug(), source: payload.source || 'manual' });
    state.logForm = createLogForm();
    state.logIngest = createLogIngest();
    state.logSubmit = { status: 'success', message: 'Saved.' };
    loadHistory(); // refreshes the history list to include the just-logged workout; calls render() itself
  } else {
    log.error('log.submit_failed', { athlete: athleteSlug(), error: result.error });
    state.logSubmit = { status: 'error', message: result.error };
    render();
  }
}

// --- Log tab: sync from watch (Phase 3 primary action) -----------------------
// Calls POST /api/workouts/sync -- the same on-demand intervals.icu sync the
// coach chat's sync_workouts tool triggers server-side (see
// backend/app/sync.py's sync_on_demand, shared by both). Manual entry/upload
// (handleSubmitLog/handleLogFileSelected below) is the secondary path now,
// collapsed behind state.logManualOpen -- see handleToggleManualLog.

async function handleSyncWorkouts() {
  if (state.logSync.status === 'syncing') return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }

  state.logSync = { status: 'syncing', message: null };
  render();
  log.info('sync.requested', { athlete: athleteSlug() });

  const result = await syncWorkouts({ baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug() });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('sync.completed', {
      athlete: athleteSlug(),
      listed: result.data.listed,
      new: result.data.new,
      saved: result.data.saved,
      failed: result.data.failed,
    });
    state.logSync = { status: 'success', message: formatSyncResult(result.data) };
    if (result.data.saved > 0) {
      loadHistory(); // refreshes the history list to include the synced workout(s); calls render() itself
    } else {
      render();
    }
  } else {
    log.error('sync.failed', { athlete: athleteSlug(), error: result.error });
    state.logSync = { status: 'error', message: result.error };
    render();
  }
}

function handleToggleManualLog() {
  state.logManualOpen = !state.logManualOpen;
  log.info('log.manual_toggle', { open: state.logManualOpen });
  render();
}

// --- Workout history (Log tab section) ------------------------------------------
// Fetches the same GET /api/workouts?athlete=<slug> that postWorkout has
// always POSTed to (see api.js's listWorkouts, which existed but nothing
// called it) -- so imported .fit/.tcx/.csv/coach-text workouts, previously
// invisible in the app, now show up alongside manually-logged ones. Lazy-
// loaded on Log-tab open the same way loadFeedback() is on Feedback-tab open
// (see setTab) -- not eagerly on every identity/settings change.

// --- Workout detail view (Slice 2: tap a history row) ----------------------
// Renders from the workout dump already sitting in state.workoutHistory.data
// -- no second API call (see views.js's renderHistorySection/renderWorkoutDetail).

function handleOpenHistoryDetail(id) {
  if (!id) return;
  state.workoutDetailId = id;
  // A fresh, empty scoped chat thread for this workout (see
  // closeWorkoutChat for the matching teardown on every close path).
  state.workoutChat = { workoutId: id, messages: [] };
  // Pushes an in-app history entry so hardware/gesture back (which fires a
  // `popstate`, handled below) closes the detail instead of navigating the
  // PWA away entirely -- see handlePopState and onAppClick's `history:back`
  // case, which now goes through `history.back()` rather than calling
  // handleCloseHistoryDetail() directly, keeping browser history and app
  // state symmetric either way the detail gets closed.
  history.pushState({ workoutDetail: id }, '');
  log.info('history.detail_opened', { athlete: athleteSlug(), workout_id: id });
  render();
}

/** Tears down the detail view's EPHEMERAL scoped chat -- aborts any
 * in-flight stream (its onEvent guard also drops late events, see
 * handleSendWorkoutChat) and drops the thread. Called from every path that
 * closes/loses the detail view: explicit close, tab leave, and the
 * stale-id prune. */
function closeWorkoutChat() {
  if (isStreaming(state.workoutChat || { messages: [] })) workoutChatAbortController?.abort();
  state.workoutChat = null;
}

function handleCloseHistoryDetail() {
  if (!state.workoutDetailId) return; // avoids a redundant render on popstate re-entrancy
  state.workoutDetailId = null;
  closeWorkoutChat();
  render();
}

// Closes the detail view on a hardware/gesture back press. Deliberately
// does NOT call history.back()/pushState itself -- it's the *target* of a
// popstate that already happened, so doing either here would create a
// pushState/popstate loop. handleCloseHistoryDetail's own guard makes this
// safe to call unconditionally on every popstate, including ones unrelated
// to the detail view (e.g. none currently exist, but this stays inert if
// one is added later).
function handlePopState() {
  handleCloseHistoryDetail();
}

/** Clears a stale detail selection after a history refresh whose new data
 * no longer contains that workout id (e.g. it aged out past
 * HISTORY_DISPLAY_CAP) -- called from loadHistory right after
 * state.workoutHistory.data is replaced. */
function pruneDetailIdIfMissing(workouts) {
  if (state.workoutDetailId && !workouts.some((w) => w.id === state.workoutDetailId)) {
    state.workoutDetailId = null;
    closeWorkoutChat();
  }
}

// --- Embedded workout chat (detail view's "Ask your coach" section) --------
// Reuses the Coach tab's exact send/stream plumbing (chat.js reducers +
// api.js streamChat) against state.workoutChat instead of state.chat -- the
// reducers only touch `.messages` and spread the rest, so workoutId rides
// along untouched. Differences from the Coach tab, all deliberate:
// scoped via `workoutId` (backend injects that workout's full detail into
// context), never persisted (see state.workoutChat's comment), and no
// expert-mode toggle (a scoped "how did this workout go" thread is
// athlete-voice by definition).

let workoutChatAbortController = null;

function handleSendWorkoutChat() {
  const chat = state.workoutChat;
  if (!chat || isStreaming(chat)) return;
  const input = document.getElementById('workout-chat-input');
  const text = input?.value.trim();
  if (!text) return;

  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  const workoutId = chat.workoutId;
  const history = toApiHistory(chat.messages);
  state.workoutChat = appendUserMessage(chat, text);
  if (input) input.value = '';
  render();

  workoutChatAbortController = new AbortController();
  log.info('workout_chat.send', { athlete: athleteSlug(), workout_id: workoutId });

  streamChat({
    baseUrl: settings.baseUrl,
    token: settings.token,
    athlete: athleteSlug(),
    message: text,
    history,
    expertMode: false,
    workoutId,
    signal: workoutChatAbortController.signal,
    onEvent: (event) => {
      if (event.type === 'error' && event.status === 401) {
        handleSessionExpired();
        return;
      }
      // The detail (and its thread) may have closed mid-stream -- a late
      // event must not resurrect state or apply to a different workout's
      // fresh thread.
      if (!state.workoutChat || state.workoutChat.workoutId !== workoutId) return;
      state.workoutChat = applyStreamEvent(state.workoutChat, event);
      if (event.type === 'done' || event.type === 'refusal' || event.type === 'error') {
        log.info('workout_chat.turn_complete', { workout_id: workoutId, type: event.type });
      }
      render();
    },
  });
}

/** Shared "should loadHistory() fire right now?" check -- used both by
 * setTab's Log-tab branch (a real tab switch) and by the boot sequence at
 * the bottom of this file (the active tab already being 'log' on a fresh
 * page load, e.g. reopening the PWA -- see that call site's comment for
 * why setTab alone doesn't cover that case). Covers "never loaded yet"
 * (idle) and "let's retry" (a previous fetch errored), gated on `online`
 * too: history fetches only when configured *and* online -- offline just
 * shows whatever's already cached in state, or a quiet notice if nothing
 * is. */
function shouldLoadHistoryNow() {
  return (state.workoutHistory.status === 'idle' || state.workoutHistory.status === 'error')
    && isConfigured(state.settingsForm, state.identity) && state.online;
}

async function loadHistory() {
  const settings = state.settingsForm;
  const identity = state.identity;
  if (!isConfigured(settings, identity)) {
    state.workoutHistory = { status: 'idle', data: [], error: null };
    render();
    return;
  }

  state.workoutHistory = { status: 'loading', data: state.workoutHistory.data, error: null };
  render();

  const result = await listWorkouts({ baseUrl: settings.baseUrl, token: settings.token, athlete: identity.athlete });
  if (handleUnauthorized(result)) return;
  if (result.ok && Array.isArray(result.data)) {
    const sorted = sortWorkoutsNewestFirst(result.data).slice(0, HISTORY_DISPLAY_CAP);
    log.info('history.loaded', { athlete: identity.athlete, count: sorted.length });
    state.workoutHistory = { status: 'ready', data: sorted, error: null };
    pruneDetailIdIfMissing(sorted);
  } else if (result.ok) {
    // Defensive: an unexpected (non-array) 2xx body shouldn't crash the
    // history section -- treat it the same as "nothing to show" rather than
    // throwing on the array-only helpers in workouts.js.
    log.warn('history.unexpected_response_shape', { athlete: identity.athlete });
    state.workoutHistory = { status: 'ready', data: [], error: null };
    pruneDetailIdIfMissing([]);
  } else {
    log.error('history.load_failed', { athlete: identity.athlete, error: result.error });
    state.workoutHistory = { status: 'error', data: state.workoutHistory.data, error: result.error };
  }
  render();
}

// --- Log tab: file upload (Phase 3 -- .fit/.tcx/.csv from the athlete's
// watch) -------------------------------------------------------------------
// Two-step design: this parses the file and pre-fills state.logForm as a
// *draft* (never saves); handleSubmitLog above does the actual save once
// the athlete has reviewed the fields, added RPE (never in the file), and
// clicked Save/Confirm. See api.js's uploadWorkoutFile and forms.js's
// logFormFromDraft for the two halves of that mapping.

async function handleLogFileSelected(file) {
  if (!file) return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }

  const lastDot = file.name.lastIndexOf('.');
  const ext = lastDot >= 0 ? file.name.slice(lastDot).toLowerCase() : '';
  if (!SUPPORTED_INGEST_EXTENSIONS.includes(ext)) {
    state.logIngest = {
      status: 'error',
      fileName: file.name,
      error: `Unsupported file type${ext ? ` "${ext}"` : ''} -- use .fit, .tcx, or .csv.`,
    };
    log.warn('log.file_unsupported_type', { athlete: athleteSlug(), ext });
    render();
    return;
  }

  state.logIngest = { status: 'uploading', fileName: file.name, error: null };
  render();
  // Filename isn't logged (an athlete-chosen filename can carry PII, e.g.
  // "Renee_swim.fit") -- only the extension and size, per the global
  // logging standard's "never log secrets or PII."
  log.info('log.file_upload_start', { athlete: athleteSlug(), ext, size_bytes: file.size });

  const result = await uploadWorkoutFile({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), file,
  });

  if (handleUnauthorized(result)) return;
  if (result.ok) {
    const draft = result.data;
    log.info('log.file_parsed', {
      athlete: athleteSlug(),
      source: draft.source,
      sport: draft.sport,
      distance_m: draft.distance_m,
      warning_count: (draft.warnings || []).length,
    });
    state.logForm = logFormFromDraft(draft, state.logForm);
    state.logIngest = { status: 'ready', fileName: file.name, error: null };
  } else {
    log.error('log.file_parse_failed', { athlete: athleteSlug(), error: result.error });
    state.logIngest = { status: 'error', fileName: file.name, error: result.error };
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
  if (handleUnauthorized(result)) return;
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
  if (handleUnauthorized(result)) return;
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
  if (handleUnauthorized(result)) return;
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
  if (handleUnauthorized(result)) return;
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
  if (handleUnauthorized(result)) return;
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
  // Leaving the Log tab always collapses the secondary manual-entry/upload
  // section back down -- coming back to Log should land on the primary sync
  // button, not wherever the athlete last left the secondary section.
  if (state.tab === 'log') {
    state.logManualOpen = false;
  }
  // Leaving the Log tab always drops any open workout-detail view -- coming
  // back to Log should land on the list, not wherever the athlete last was.
  if (state.tab === 'log' && state.workoutDetailId) {
    state.workoutDetailId = null;
    closeWorkoutChat();
    // Consumes the pushState entry handleOpenHistoryDetail added (see
    // there), keeping browser history symmetric with app state -- without
    // this, a dangling entry would sit in the stack and silently swallow
    // the athlete's *next* hardware/gesture back press instead of doing
    // anything visible. Safe: handlePopState's handleCloseHistoryDetail()
    // call is a no-op once workoutDetailId is already null (set above), so
    // this can't re-trigger any state change when the resulting popstate
    // fires.
    history.back();
  }
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
  // Same lazy-load convention as Plan/Feedback above -- see
  // shouldLoadHistoryNow()'s doc comment.
  if (tab === 'log' && shouldLoadHistoryNow()) {
    loadHistory(); // calls render() itself
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

async function onAppClick(e) {
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
    case 'workout-chat:send': handleSendWorkoutChat(); break;
    case 'log:submit': handleSubmitLog(); break;
    case 'sync:start': handleSyncWorkouts(); break;
    case 'log:toggle-manual': handleToggleManualLog(); break;
    case 'checkin:submit': handleSubmitCheckin(); break;
    case 'profile:submit': handleSubmitProfile(); break;
    case 'feedback:submit': handleSubmitFeedback(); break;
    case 'onboard:submit': handleOnboardSubmit(); break;
    case 'history:retry': loadHistory(); break;
    case 'history:open': handleOpenHistoryDetail(el.dataset.id); break;
    // Goes through history.back() (not handleCloseHistoryDetail() directly)
    // so the in-app "back" affordance and a hardware/gesture back press
    // close the detail via the exact same path -- see handlePopState.
    case 'history:back': history.back(); break;
    // Awaited (unlike every other handler above) so the server-side revoke
    // this now does (see performSignOut) actually fires before this handler
    // returns, rather than being fired-and-forgotten mid-click.
    case 'identity:signout': await handleSignOut(); break;
    case 'pwa:reload': handleReloadForUpdate(); break;
    case 'pwa:dismiss-update': handleDismissNeedRefresh(); break;
    case 'pwa:dismiss-offline-ready': handleDismissOfflineReady(); break;
    default: break;
  }
}

function onAppChange(e) {
  if (e.target.matches('[data-a="chat:expert-toggle"]')) {
    handleToggleExpertMode(e.target.checked);
  } else if (e.target.matches('[data-a="log:file-select"]')) {
    handleLogFileSelected(e.target.files?.[0]);
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
  else if (formName === 'onboard') {
    if (field === 'pool_days') {
      // Same data-day convention as the profile form's pool-day checkboxes
      // (see views.js's POOL_DAY_LABELS) -- every checkbox shares the
      // pool_days data-field and toggles its own key in the poolDays map.
      const day = el.dataset.day;
      if (day) state.onboarding.form.poolDays[day] = el.checked;
    } else {
      state.onboarding.form[field] = el.value;
    }
    // The CSS-mode select swaps which input(s) are visible (a CSS-pace
    // field vs. two time-trial fields, see views.js's renderOnboardingForm)
    // -- unlike every other field here, that's a structural change to the
    // DOM, not just a value to read back on submit, so it needs a real
    // render() rather than the direct-DOM-patch convention the rest of this
    // handler uses to avoid disrupting an in-progress edit elsewhere.
    if (field === 'cssMode') render();
  }

  const outId = el.dataset.sliderOut;
  if (outId) {
    const out = document.getElementById(outId);
    if (out) out.textContent = el.value;
  }

  // The Log tab's Save button is gated on RPE being set (see
  // views.js's renderLogTab `rpeMissing` -- a file upload resets rpe to ''
  // so the athlete must move the slider at least once). That gate has to
  // update live as the slider is dragged, but this handler deliberately
  // avoids a full render() on every input event (see comment above) to not
  // interrupt an in-progress drag -- so patch just the affected elements
  // directly instead.
  if (formName === 'log' && field === 'rpe') {
    const rpeMissing = state.logForm.rpe === '' || state.logForm.rpe === null || state.logForm.rpe === undefined;
    const saveBtn = document.querySelector('[data-a="log:submit"]');
    if (saveBtn) saveBtn.disabled = rpeMissing || state.logSubmit.status === 'submitting' || !state.online;
    document.getElementById('log-rpe-required-badge')?.toggleAttribute('hidden', !rpeMissing);
    document.getElementById('log-rpe-hint')?.toggleAttribute('hidden', !rpeMissing);
  }
}

function onAppKeydown(e) {
  if (e.target.id === 'chat-input' && e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSendChat();
  }
  if (e.target.id === 'workout-chat-input' && e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    handleSendWorkoutChat();
  }
}

// --- Offline (unchanged) -------------------------------------------------

function updateOfflineBanner() {
  const banner = document.getElementById('offline-banner');
  if (banner) banner.classList.toggle('show', !navigator.onLine);
}

// Tabs whose own tab-content markup depends on `online` (a `.chat-banner`
// notice, and inputs/buttons disabled while offline) -- re-rendered so that
// content actually reflects the new state rather than only the always-in-DOM
// #offline-banner updating. Every other tab either doesn't touch `online` in
// its render function or isn't worth a re-render on a background
// connectivity change (Plan/Settings/Feedback keep whatever they last
// rendered until the athlete next interacts with them).
const TABS_SENSITIVE_TO_ONLINE_STATE = ['coach', 'log', 'checkin'];

function updateOnlineState() {
  state.online = navigator.onLine;
  updateOfflineBanner();
  if (TABS_SENSITIVE_TO_ONLINE_STATE.includes(state.tab)) render();
}

window.addEventListener('online', updateOnlineState);
window.addEventListener('offline', updateOnlineState);
// See handleOpenHistoryDetail/handleCloseHistoryDetail/setTab for the rest
// of the detail-view <-> browser-history wiring this closes the loop on.
window.addEventListener('popstate', handlePopState);

appEl.addEventListener('click', onAppClick);
appEl.addEventListener('change', onAppChange);
appEl.addEventListener('input', onAppInput);
appEl.addEventListener('keydown', onAppKeydown);

log.info('app.init', { version: __APP_VERSION__ ?? 'dev' });
updateOfflineBanner();
render();
loadPlan();
maybeLoadProfile();
// loadPlan() above self-gates on isConfigured and is otherwise unconditional
// at boot; loadHistory() has no such caller-independent self-gate -- until
// now the only caller was setTab's Log-tab branch, so history stayed stuck
// on 'idle' forever if the athlete reopened the PWA with Log already the
// persisted active tab (state.tab restores from localStorage without ever
// calling setTab, since no navigation happened). Covers that case the same
// way setTab does -- see shouldLoadHistoryNow(). state.identity is already
// resolved synchronously above (identity.js's currentIdentity() is a plain
// localStorage read, no network round trip -- see initialIdentity at the
// top of this file), so this reads the same populated state setTab would.
if (state.tab === 'log' && shouldLoadHistoryNow()) {
  loadHistory();
}

// Registers the service worker with an explicit update *prompt* (see
// vite.config.js's `registerType: 'prompt'`) instead of vite-plugin-pwa's
// silent 'autoUpdate' -- onNeedRefresh fires once a new build has installed
// and is waiting to activate; onOfflineReady fires once the first install
// finishes precaching. Both just fold into state.pwaUpdate (src/pwaUpdate.js)
// and re-render -- see views.js's renderUpdateBanner for the actual banner,
// and handleReloadForUpdate/handleDismissNeedRefresh/
// handleDismissOfflineReady above for the click handlers.
updateSW = registerSW({
  onNeedRefresh() {
    log.info('pwa.need_refresh', {});
    state.pwaUpdate = markNeedRefresh(state.pwaUpdate);
    render();
  },
  onOfflineReady() {
    log.info('pwa.offline_ready', {});
    state.pwaUpdate = markOfflineReady(state.pwaUpdate);
    render();
  },
});
