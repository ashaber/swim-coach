import './fonts.js';
import { registerSW } from 'virtual:pwa-register';
import log from './log.js';
import {
  renderApp, renderLoading, renderError, renderTabBar, renderCoachTab, renderSettingsTab,
  renderDashboardTab, renderCheckinTab, renderBackendNeededNotice, renderFeedbackTab, renderUpdateBanner,
  renderOnboardingForm, renderRosterTab, cr10AnchorLabel,
} from './views.js';
import { findSessionById, LOAD_CHART_WINDOW_DAYS, LOAD_CHART_WINDOW_OPTIONS } from './plan.js';
import { buildHistoryFeed } from './history.js';
import {
  loadChatSession, saveChatSession, clearChatStorage,
  appendUserMessage, applyStreamEvent, isStreaming, setExpertMode, clearMessages, toApiHistory,
} from './chat.js';
import { loadSettings, saveSettings, isConfigured } from './settings.js';
import {
  streamChat, postWorkout, postWellness, fetchPlan, fetchPlanLoad, getAthlete, patchAthlete, patchWorkout,
  postFeedback, listFeedback, uploadWorkoutFile, listWorkouts, syncWorkouts, logout, onboard,
  pushSessionToIntervals,
  downloadGarminFit,
  createGrant, listGrants, revokeGrant,
  listCoachedAthletes, fetchCoachWorkouts, fetchCoachFeedback, fetchCoachLoad, fetchCoachPlan, replyToCoachFeedback,
  fetchCoachHealthStatus, postCoachHealthStatus, resolveCoachHealthStatus,
  askAboutSession, askAboutWorkout,
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
import { sortWorkoutsNewestFirst, formatSyncResult } from './workouts.js';
import { performSignOut } from './session.js';
import {
  createPwaUpdateState, markNeedRefresh, markOfflineReady,
  dismissNeedRefresh, dismissOfflineReady, triggerUpdate,
} from './pwaUpdate.js';
import { loadLastSeen, saveLastSeen, countUnread } from './unread.js';

const appEl = document.getElementById('app');
const ACTIVE_TAB_KEY = 'swimcoach_active_tab';
// The training-load chart's selected window (web/two-panel-load-chart) --
// stored as the string 'season' or a decimal day count ('42'/'84'), since
// localStorage only holds strings; `null` (plan.js's "no slicing, full
// series" sentinel) can't round-trip through it directly. See
// loadLoadWindowDays/saveLoadWindowDays below.
const LOAD_WINDOW_DAYS_KEY = 'swimcoach_load_window_days';
// 'log' and 'history' merged into one 'dashboard' tab (Build 1 of the
// wellness-ingestion + training-dashboard plan) -- see views.js's
// renderDashboardTab/renderTrainingDashboardBody.
const KNOWN_TABS = ['plan', 'dashboard', 'checkin', 'coach', 'feedback', 'roster', 'settings'];
// The roster tab's own sub-navigation (Build 2: Coach per-athlete sub-tab
// restructure) -- see views.js's ROSTER_SUB_TABS/renderRosterSubTabBar for
// the matching label/render side, and handleSelectRosterSubTab below.
const ROSTER_SUB_TABS = ['conversations', 'dashboard', 'plan'];
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
    // views.js's renderDashboardTab review card and never sent to the backend.
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
    name: '', dob: '', sex: '', heightFeet: '', heightInches: '', weightLb: '', cssPace: '', lthrBpm: '',
    poolDays: {
      monday: false, tuesday: false, wednesday: false, thursday: false, friday: false, saturday: false, sunday: false,
    },
    // B4: defaults true, matching Athlete.email_notifications_enabled's own
    // server-side default (engine/swim_coach/models.py) -- overwritten the
    // moment loadProfile's real GET /api/athlete response lands
    // (forms.js's profileFormFromAthlete).
    emailNotificationsEnabled: true,
  };
}

function createFeedbackForm() {
  return { type: 'feature_request', body: '' };
}

// --- Ask-the-coach Q&A (coach-mode Q&A build) -------------------------------
// The Plan tab's session detail and the Dashboard tab's workout detail share
// this one flat form/submit slice -- only one detail view (of either kind)
// is ever open at a time in the athlete's own tabs (same "one shared slot"
// convention state.workoutRpeEdit/state.workoutChat already use), so there's
// no need for two separate per-surface slices.

function createAskCoachForm() {
  return { body: '' };
}

function createAskCoachSubmit() {
  return { status: 'idle', error: null };
}

// Coach mode Phase 1 (roster/grants surface). See applyAthleteSession /
// resetToSignedOut for the reset call sites -- a fresh sign-in or sign-out
// must not carry over a previous identity's coached-athlete view or
// in-progress grant form.
function createRosterState() {
  return {
    actingAsAthlete: null,
    athletes: { status: 'idle', data: [], error: null },
    workouts: { status: 'idle', data: [], error: null },
    feedback: { status: 'idle', data: [], error: null },
    // The coach roster's CTL/ATL/TSB training-load chart for whichever
    // athlete is currently acted-as (views.js's renderLoadChart, fed by
    // GET /api/coach/athletes/<slug>/load -- see api.js's fetchCoachLoad).
    // Same {status, data, error} shape as `workouts`/`feedback` above.
    load: { status: 'idle', data: null, error: null },
    replyDrafts: {},
    replySubmit: { status: 'idle', error: null, feedbackId: null },
    // Slice: null shows the workouts/feedback lists for the acting-as
    // athlete; a workout id opens that workout's read-only detail view
    // instead (reuses renderWorkoutDetail -- see views.js's renderRosterTab).
    // Same convention as state.workoutDetailId (the Dashboard tab).
    workoutDetailId: null,
    // Whether the roster's own Training Dashboard feed (Build 1) is showing
    // the full completed-workout list or just the paginated recent slice --
    // same "Show more" convention as state.dashboardFeedExpanded below, its
    // own bit of state since the coach roster and the athlete's own
    // dashboard are two independent feeds. Reset whenever a different
    // athlete is selected (handleSelectCoachedAthlete) or the coach backs
    // out to the athlete list (handleBackToRoster).
    feedExpanded: false,
    // Whether the roster's own training-load chart narrative (views.js's
    // renderCtlAtlTsbNarrative, web/two-panel-load-chart's truncation) is
    // showing its full text or just the first line -- same one-way "Show
    // more" convention as `feedExpanded` just above, its own bit of state
    // for the same reason: the coach roster and the athlete's own dashboard
    // are two independent narratives. Reset alongside `feedExpanded`
    // wherever that resets.
    narrativeExpanded: false,
    // The acted-as athlete's plan export (Build 2's new
    // GET /api/coach/athletes/<slug>/plan route -- see api.js's
    // fetchCoachPlan) -- feeds the Training Plan sub-tab's weeks/macro
    // sections AND, via its `weeks`, the Workouts + Dashboard sub-tab's
    // skip-derivation (views.js's renderRosterTab, buildHistoryFeed). Same
    // {status, data, error} async-state shape as `workouts`/`feedback`/
    // `load` above.
    plan: { status: 'idle', data: null, error: null },
    // Which of the roster's three sub-tabs (Build 2: Conversations /
    // Workouts + Dashboard / Training Plan) is currently showing for the
    // acted-as athlete -- see views.js's renderRosterTab/
    // renderRosterSubTabBar. Defaults to 'dashboard', the sub-tab that used
    // to be the entire acting-as-athlete view before this split. Reset
    // alongside the other per-athlete slices above.
    subTab: 'dashboard',
    // Slice: null shows the Training Plan sub-tab's weeks/macro lists; a
    // session id opens that session's in-tab detail view instead (see
    // views.js's renderRosterTrainingPlanBody). Its OWN slice, deliberately
    // separate from the athlete's own `state.planSessionDetailId` -- a coach
    // could plausibly have their own Plan tab's session open at the same
    // time as a coached athlete's, and the two must never collide. No
    // matching `state.roster.sessionPush`: the Garmin push action is
    // suppressed entirely in this view (see renderPlanSessionDetail's
    // `showGarminActions` param), so there is no coach-side push result to
    // track. Reset whenever a different athlete is selected
    // (handleSelectCoachedAthlete), the coach backs out to the athlete list
    // (handleBackToRoster), or the sub-tab is switched away from 'plan'
    // (handleSelectRosterSubTab) -- same conventions as workoutDetailId.
    sessionDetailId: null,
    // Durable health-status record (backend/health-status-record build):
    // the acted-as athlete's full health-status history (most-recent-first,
    // per GET .../health-status's ordering), same {status, data, error}
    // async-state shape as `workouts`/`feedback`/`load`/`plan` above.
    healthStatus: { status: 'idle', data: [], error: null },
    // Stale-response guard for loadCoachHealthStatus below (a real review
    // bug caught before merge): incremented every time a fresh load STARTS
    // and every time a local mutation (submit/resolve) patches `data`
    // directly. A slow in-flight GET's success handler only applies its
    // result if this counter hasn't moved since ITS OWN load started --
    // otherwise a slow GET completing after a coach's own submit/resolve
    // would silently clobber that already-durably-saved, just-applied
    // local change with a stale pre-mutation snapshot, potentially
    // prompting a confusing duplicate submission.
    healthStatusVersion: 0,
    // The coach's in-progress "log a new health status" form draft --
    // deliberately its own flat object (not per-row-keyed like
    // `replyDrafts`, since there's only ever one such form per athlete, not
    // one per list row). Reset whenever a different athlete is selected or
    // a submission succeeds.
    healthStatusForm: {
      description: '', restriction: 'light_only', source: 'self_reported', expected_review_date: '',
    },
    // Submitting the "log a new health status" form -- same {status, error}
    // shape convention as `replySubmit`, minus the per-row `feedbackId`
    // (there's only one form, not one per row).
    healthStatusSubmit: { status: 'idle', error: null },
    // Marking the CURRENT active entry resolved -- `id` pins the result to
    // the specific entry being resolved, same "which row is this about"
    // convention `replySubmit.feedbackId` already establishes.
    healthStatusResolve: { status: 'idle', error: null, id: null },
  };
}

function createGrantsState() {
  return {
    entries: { status: 'idle', data: [], error: null },
    createForm: { coachSlug: '' },
    createSubmit: { status: 'idle', error: null },
  };
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
  // The Dashboard tab's CTL/ATL/TSB training-load chart (views.js's
  // renderLoadChart, via renderTrainingDashboardBody -- Build 1 moved this
  // chart off the Plan tab and into the merged Log+History Dashboard tab) --
  // GET /api/plan/load, a minimal separate fetch from `plan` above since
  // it's the only consumer of this field (see api.js's fetchPlanLoad). Same
  // {status, data, error} async-state shape as `plan`. Keeps the `planLoad`
  // name despite moving tabs -- minimizes unrelated diff surface, and it's
  // still fetched from the same GET /api/plan/load endpoint either way.
  planLoad: { status: 'idle', data: null, error: null },
  // Slice: null shows the ordinary "This week"/"Next week" cards; a session
  // id opens that session's in-tab detail view instead (see views.js's
  // renderWeeksSection). Reset on leaving the Plan tab (setTab) and pruned
  // in loadPlan if a refresh's new weeks no longer contain the id -- same
  // conventions as workoutDetailId below.
  planSessionDetailId: null,
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
  // Result of the Plan tab's per-session "Push to Garmin" action. A single
  // { id, status, message } rather than a per-session map: only one session
  // detail is open at a time, and a push is a short-lived foreground action
  // (same shape and reasoning as logSync above). `id` scopes the message to
  // the session it belongs to -- see views.js's renderGarminPush. Cleared on
  // leaving the Plan tab / closing the detail, like planSessionDetailId.
  sessionPush: null,
  // Whether the Plan tab's all-weeks <details> accordion is expanded. Native
  // <details> keeps this in the DOM, but every render() rebuilds that DOM --
  // so without mirroring it here, any unrelated re-render silently snapped
  // the accordion shut while the athlete was reading it. Synced from the
  // element's own `toggle` event (see the listener near the bottom of this
  // file), never by intercepting the click, so the native behaviour stays
  // exactly as it was.
  allWeeksOpen: false,
  // Same "mirror the native <details> open state across re-renders"
  // reasoning as allWeeksOpen just above, for the Plan tab's collapsed
  // "Terms & zones" glossary (views.js's renderGlossaryPanel) -- a distinct
  // flag, not reused from allWeeksOpen, so toggling one accordion never
  // silently opens/closes the other on the next render.
  glossaryOpen: false,
  // Secondary manual-entry/upload section is collapsed by default (Phase 3:
  // "Sync from watch" is the Dashboard tab's primary action) -- reset on
  // leaving the Dashboard tab (setTab), same convention as workoutDetailId
  // below.
  logManualOpen: false,
  // Whether the Dashboard tab's Training Dashboard feed (Build 1: the
  // merged Log+History tab) is showing the full completed+missed feed or
  // just the paginated recent slice, per views.js's
  // renderTrainingDashboardBody -- same "Show more" convention as
  // state.roster.feedExpanded. Reset on leaving the Dashboard tab (setTab).
  dashboardFeedExpanded: false,
  // The Dashboard tab's training-load chart narrative (views.js's
  // renderCtlAtlTsbNarrative, web/two-panel-load-chart's truncation) --
  // same one-way "Show more" convention as dashboardFeedExpanded just
  // above, its own bit of state since expanding the feed and expanding the
  // narrative are two independent affordances. Reset on leaving the
  // Dashboard tab (setTab), same as dashboardFeedExpanded.
  loadNarrativeExpanded: false,
  // The training-load chart's selected time window (plan.js's
  // LOAD_CHART_WINDOW_OPTIONS: 42/84/null days) -- persisted across
  // sessions (see loadLoadWindowDays/saveLoadWindowDays below), same
  // "remember a view preference" convention as ACTIVE_TAB_KEY/
  // loadActiveTab. Deliberately the SAME app-level flag the coach roster's
  // acting-as-athlete view uses too (not a separate
  // state.roster.loadWindowDays) -- a shared, low-stakes chart-window
  // preference, same "acceptable tradeoff" precedent allWeeksOpen already
  // establishes for page-level state shared between the athlete's own tabs
  // and the roster view (see views.js's renderRosterTab doc comment).
  loadWindowDays: loadLoadWindowDays(),
  workoutHistory: { status: 'idle', data: [], error: null },
  // Slice 2: null shows the history list; a workout id opens that
  // workout's in-tab detail view instead (see views.js's
  // renderTrainingDashboardBody). Reset on leaving the Dashboard tab
  // (setTab) and pruned in loadHistory if a refresh's new data no longer
  // contains the id.
  workoutDetailId: null,
  // The detail view's embedded scoped chat (Phase C slice 1):
  // {workoutId, messages} while a detail is open, null otherwise.
  // Deliberately EPHEMERAL -- in-memory only, never persisted, cleared
  // whenever the detail closes (closeWorkoutChat) -- a scoped thread about
  // one workout isn't a durable conversation worth carrying across
  // sessions the way the Coach tab's chat is (chat.js's localStorage).
  workoutChat: null,
  // A6b: the workout-detail RPE editor. `null` when no edit is in progress;
  // else `{workoutId, rpe, status, error}` (same async-state shape as
  // logSubmit/checkinSubmit above). Reset alongside workoutChat -- both are
  // per-detail-view-scoped and there's only ever one detail view open at a
  // time (handleOpenHistoryDetail, handleCloseHistoryDetail, setTab leaving
  // the Dashboard tab). Never populated on the coach roster's read-only
  // renderWorkoutDetail call site -- see renderTrainingDashboardBody's
  // `editable` doc comment for why (PATCH /api/workouts is self-access
  // only, a coach session could never save it anyway).
  workoutRpeEdit: null,
  // Coach-mode Q&A build: the Ask-the-coach draft/submit state shared by the
  // Plan tab's session detail and the Dashboard tab's workout detail (see
  // createAskCoachForm's doc comment for why one shared slice is enough).
  // Reset alongside workoutChat/workoutRpeEdit and planSessionDetailId's own
  // reset paths -- every open/close of either detail view.
  askCoachForm: createAskCoachForm(),
  askCoachSubmit: createAskCoachSubmit(),
  checkinForm: createCheckinForm(),
  checkinSubmit: { status: 'idle', message: null },
  profileForm: createProfileForm(),
  profileLoad: { status: 'idle', error: null },
  profileSubmit: { status: 'idle', message: null },
  feedbackForm: createFeedbackForm(),
  feedbackSubmit: { status: 'idle', message: null },
  feedbackEntries: { status: 'idle', data: [] },
  // Coach mode Phase 1 (roster/grants surface only -- direct-to-coach chat
  // and the workout-comment box are a separate follow-up piece).
  // `coachFor` mirrors `state.identity?.coachFor` once resolved -- copied
  // out to the top level (rather than reading through `identity` every
  // time) purely so render()/renderTabBar's "does this identity coach
  // anyone" check reads the same regardless of whether identity is null
  // (signed out) -- see handleIdentityResolved/applyAthleteSession/
  // resetToSignedOut for where this gets kept in sync.
  coachFor: initialIdentity?.coachFor || [],
  // `roster.actingAsAthlete`: the coached-athlete slug currently being
  // viewed (detail view), or null (list-of-athletes view) -- same "null
  // shows the list, an id opens detail" convention as
  // planSessionDetailId/workoutDetailId. `roster.replyDrafts`: in-progress
  // reply text per feedback row, keyed by feedback id -- a plain object
  // (not a Map) since it's read/written the same data-form/data-field way
  // onAppInput already handles every other form, just keyed per-row
  // instead of flat. `grants.entries` is MY grants (who can coach me) --
  // Settings tab, self-access.
  roster: createRosterState(),
  grants: createGrantsState(),
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

/** Reads the persisted training-load chart window (`LOAD_WINDOW_DAYS_KEY`)
 * back into one of `LOAD_CHART_WINDOW_OPTIONS`' own `days` values (a number,
 * or `null` for "Season") -- falls back to `LOAD_CHART_WINDOW_DAYS` (the
 * default option) for a missing/corrupt/stale stored value, same
 * "known-good fallback, never trust storage blindly" convention as
 * loadActiveTab's KNOWN_TABS check. */
function loadLoadWindowDays() {
  try {
    const stored = localStorage.getItem(LOAD_WINDOW_DAYS_KEY);
    if (stored === 'season') return null;
    const days = Number(stored);
    if (LOAD_CHART_WINDOW_OPTIONS.some((o) => o.days === days)) return days;
    return LOAD_CHART_WINDOW_DAYS;
  } catch {
    return LOAD_CHART_WINDOW_DAYS;
  }
}

function saveLoadWindowDays(days) {
  try {
    localStorage.setItem(LOAD_WINDOW_DAYS_KEY, days === null ? 'season' : String(days));
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
    case 'dashboard':
      // Build 1 (Log+History merge): the feed needs BOTH sides -- completed
      // workouts (workoutHistory) and the plan's past sessions
      // (plan.data.weeks) to derive skips from. Both loads are kicked off
      // by setTab; until the plan lands, `weeks` is empty and the feed is
      // simply completed-only rather than wrongly reporting everything as
      // skipped.
      return renderDashboardTab({
        load: state.planLoad,
        feed: buildHistoryFeed({
          weeks: state.plan.data?.weeks || [],
          workouts: state.workoutHistory.data,
          now: new Date(),
        }),
        status: historyFeedStatus(),
        error: state.workoutHistory.error || state.plan.error,
        online: state.online,
        detailId: state.workoutDetailId,
        workoutChat: state.workoutChat,
        backendConfigured,
        form: state.logForm,
        submit: state.logSubmit,
        ingest: state.logIngest,
        sync: state.logSync,
        manualOpen: state.logManualOpen,
        feedExpanded: state.dashboardFeedExpanded,
        rpeEdit: state.workoutRpeEdit,
        // Coach-mode Q&A build: the athlete's own real Ask-the-coach
        // section, wired to a real submit action (`form` set) -- see
        // renderWorkoutDetail's `askCoach` doc comment. `feedback` is the
        // FULL already-fetched list; renderWorkoutDetail filters it down to
        // just the open workout by workout_id.
        askCoach: { feedback: state.feedbackEntries.data, form: state.askCoachForm, submit: state.askCoachSubmit },
        loadWindowDays: state.loadWindowDays,
        loadNarrativeExpanded: state.loadNarrativeExpanded,
      });
    case 'checkin':
      return renderCheckinTab({
        form: state.checkinForm,
        submit: state.checkinSubmit,
        backendConfigured,
        online: state.online,
        // Resolved decision (web/two-panel-load-chart): reuses the
        // already-fetched Dashboard-tab load state -- see renderCheckinTab's
        // own doc comment for why this never fires a second fetch.
        load: state.planLoad,
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
    case 'roster':
      return renderRosterTab({
        athletes: state.roster.athletes,
        actingAsAthlete: state.roster.actingAsAthlete,
        workouts: state.roster.workouts,
        feedback: state.roster.feedback,
        replyDrafts: state.roster.replyDrafts,
        replySubmit: state.roster.replySubmit,
        workoutDetailId: state.roster.workoutDetailId,
        backendConfigured,
        online: state.online,
        load: state.roster.load,
        feedExpanded: state.roster.feedExpanded,
        plan: state.roster.plan,
        subTab: state.roster.subTab,
        // Shared with the athlete's own Plan tab (`case 'plan':` below) --
        // see views.js's renderRosterTrainingPlanBody doc comment for why
        // this deliberately isn't its own state.roster.allWeeksOpen slice.
        allWeeksOpen: state.allWeeksOpen,
        sessionDetailId: state.roster.sessionDetailId,
        // web/two-panel-load-chart: shared app-level window preference (see
        // views.js's renderRosterTab doc comment) plus the roster's own
        // per-surface narrative-expanded slice.
        loadWindowDays: state.loadWindowDays,
        loadNarrativeExpanded: state.roster.narrativeExpanded,
        // B3: unread count for the roster's own Feedback section heading --
        // see src/unread.js's countUnread doc comment. Only ever meaningful
        // once an athlete's own feedback has actually been fetched (0
        // beforehand -- no per-athlete data to count from yet, same
        // limitation the tab bar's own rosterUnread badge below accepts).
        feedbackUnread: countUnread(state.roster.feedback.data, loadLastSeen('coach'), 'coach'),
        healthStatus: state.roster.healthStatus,
        healthStatusForm: state.roster.healthStatusForm,
        healthStatusSubmit: state.roster.healthStatusSubmit,
        healthStatusResolve: state.roster.healthStatusResolve,
      });
    case 'settings':
      return renderSettingsTab({
        identity: state.identity,
        identityError: state.identityError,
        backendConfigured,
        profileForm: state.profileForm,
        profileLoad: state.profileLoad,
        profileSubmit: state.profileSubmit,
        grants: state.grants.entries,
        grantsForm: state.grants.createForm,
        grantsSubmit: state.grants.createSubmit,
      });
    case 'plan':
    default:
      if (!backendConfigured) {
        return renderBackendNeededNotice('The Plan tab needs you to sign in and set a backend URL and token in Settings.');
      }
      if (state.plan.status === 'loading' || state.plan.status === 'idle') return renderLoading();
      if (state.plan.status === 'error') return renderError(state.plan.error);
      return renderApp(
        {
          ...state.plan.data,
          sessionPush: state.sessionPush,
          allWeeksOpen: state.allWeeksOpen,
          glossaryOpen: state.glossaryOpen,
          // Coach-mode Q&A build: same shape/rationale as the Dashboard
          // tab's own `askCoach` above, just scoped to a planned Session
          // instead of a completed Workout.
          askCoach: { feedback: state.feedbackEntries.data, form: state.askCoachForm, submit: state.askCoachSubmit },
        },
        state.planSessionDetailId,
      );
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
  // `roster` (coach mode Phase 1) is hidden from the tab bar unless the
  // signed-in identity actually coaches someone -- an athlete with no coach
  // grants has nothing to see there. Every other tab always shows;
  // renderTabBar's `hideRoster` flag is the one visibility knob (see its
  // doc comment for why that's the chosen signature over a full allowlist).
  //
  // B3: feedbackUnread/rosterUnread badges -- see src/unread.js's
  // countUnread doc comment for the asymmetric athlete/coach field choice.
  // rosterUnread only ever reflects the CURRENTLY acted-as athlete's
  // feedback (state.roster.feedback is per-selected-athlete, not
  // aggregated across every coached athlete -- no new backend endpoint
  // exists to aggregate that, and this build doesn't add one); 0 before any
  // athlete has been selected, same accepted tradeoff as the roster's own
  // section-level badge (renderTabContent's 'roster' case).
  appEl.innerHTML = `${renderUpdateBanner(state.pwaUpdate)}${renderTabContent()}${
    renderTabBar(state.tab, {
      hideRoster: !state.coachFor.length,
      feedbackUnread: countUnread(state.feedbackEntries.data, loadLastSeen('athlete'), 'athlete'),
      rosterUnread: countUnread(state.roster.feedback.data, loadLastSeen('coach'), 'coach'),
    })}`;
  if (state.tab === 'coach') stickChatScrollToBottom();
  if (state.tab === 'dashboard' && state.workoutChat) stickWorkoutChatScrollToBottom();
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
  state.coachFor = identity.coachFor || [];
  state.settingsForm = saveSettings({ baseUrl: state.settingsForm.baseUrl, token });
  state.chat = loadChatSession(identity.athlete);
  // Left idle rather than eagerly fetched here -- setTab('plan') lazily
  // loads it (or retries) the moment the Plan tab is actually visited, which
  // is also what covers the "just saved settings, now ready" case, so there
  // isn't a second load-triggering path to keep in sync with this one.
  state.plan = { status: 'idle', data: null, error: null };
  state.planLoad = { status: 'idle', data: null, error: null };
  state.planSessionDetailId = null;
  state.sessionPush = null;
  state.askCoachForm = createAskCoachForm();
  state.askCoachSubmit = createAskCoachSubmit();
  state.profileForm = createProfileForm();
  state.profileLoad = { status: 'idle', error: null };
  state.profileSubmit = { status: 'idle', message: null };
  // Same lazy-load convention for the Feedback tab's list (see setTab).
  state.feedbackEntries = { status: 'idle', data: [] };
  state.workoutHistory = { status: 'idle', data: [], error: null };
  state.workoutDetailId = null;
  state.dashboardFeedExpanded = false;
  state.loadNarrativeExpanded = false;
  closeWorkoutChat();
  state.roster = createRosterState();
  state.grants = createGrantsState();
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
  maybeLoadGrants();
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
  state.coachFor = [];
  state.roster = createRosterState();
  state.grants = createGrantsState();
  state.onboarding = createOnboardingState();
  saveOnboardingActive(false);
  state.chat = loadChatSession(SIGNED_OUT_CHAT_KEY);
  state.plan = { status: 'idle', data: null, error: null };
  state.planLoad = { status: 'idle', data: null, error: null };
  state.planSessionDetailId = null;
  state.sessionPush = null;
  state.askCoachForm = createAskCoachForm();
  state.askCoachSubmit = createAskCoachSubmit();
  state.profileForm = createProfileForm();
  state.profileLoad = { status: 'idle', error: null };
  state.profileSubmit = { status: 'idle', message: null };
  state.feedbackEntries = { status: 'idle', data: [] };
  state.workoutHistory = { status: 'idle', data: [], error: null };
  state.workoutDetailId = null;
  state.dashboardFeedExpanded = false;
  state.loadNarrativeExpanded = false;
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
    loadPlanLoad(); // calls render() itself
    maybeLoadProfile();
    maybeLoadGrants();
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

/** Scrolls the page back to its top -- called right after a detail view
 * (session or workout) renders, so the athlete lands on the content they
 * just tapped instead of wherever the page happened to be scrolled before
 * (e.g. down near the macro section). The page body itself scrolls (no
 * dedicated scroll container on #app), so `window` is the right target. */
function scrollToTop() {
  window.scrollTo(0, 0);
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
    pruneSessionDetailIdIfMissing(result.data.weeks);
  } else {
    log.error('app.plan.load_failed', { error: result.error });
    state.plan = { status: 'error', data: null, error: result.error };
  }
  render();
}

/** Fetches GET /api/plan/load?athlete=<slug> for the Plan tab's CTL/ATL/TSB
 * training-load chart (views.js's renderLoadChart) -- a minimal, separate
 * fetch from loadPlan() above (see api.js's fetchPlanLoad doc comment for
 * why). Called alongside loadPlan() at every one of its own call sites
 * (initial load, tab-visit, History tab's shared Plan fetch) rather than
 * inventing a new refresh trigger -- the chart refreshes exactly when the
 * rest of the Plan tab's data does. */
async function loadPlanLoad() {
  const settings = state.settingsForm;
  const identity = state.identity;
  if (!isConfigured(settings, identity)) {
    state.planLoad = { status: 'idle', data: null, error: null };
    render();
    return;
  }

  state.planLoad = { status: 'loading', data: state.planLoad.data, error: null };
  render();

  const result = await fetchPlanLoad({ baseUrl: settings.baseUrl, token: settings.token, athlete: identity.athlete });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('app.plan_load.loaded', { points: result.data.ctl_atl_tsb?.length ?? 0 });
    state.planLoad = { status: 'ready', data: result.data, error: null };
  } else {
    log.error('app.plan_load.load_failed', { error: result.error });
    state.planLoad = { status: 'error', data: null, error: result.error };
  }
  render();
}

// --- Plan session detail view (tapping a session row) ----------------------
// Renders from the plan's weeks already sitting in state.plan.data -- no
// second API call (see views.js's renderWeeksSection/renderPlanSessionDetail).
// Mirrors the workout-detail handlers (handleOpenHistoryDetail/
// handleCloseHistoryDetail above) exactly: history.pushState/popstate wiring
// for hardware/gesture back, closed on tab-leave, pruned if the id
// disappears after a plan refresh.

function handleOpenSessionDetail(id) {
  if (!id) return;
  // data-a="session:open" is shared verbatim between the athlete's own Plan
  // tab and the coach roster's Training Plan sub-tab (renderSession/
  // renderWeeksSection markup, Build 2). onAppClick's own 'session:open'
  // case branches on state.tab to route the click to this handler or to
  // handleOpenCoachSessionDetail below, so this should only ever be called
  // while state.tab === 'plan' -- the guard here is defense-in-depth against
  // ever setting the athlete's OWN state.planSessionDetailId from a stray
  // roster-context click (which would open a session under the wrong
  // identity's Garmin actions -- see renderPlanSessionDetail's
  // showGarminActions doc comment for why those two surfaces must never
  // share this piece of state).
  if (state.tab !== 'plan') return;
  state.planSessionDetailId = id;
  // Coach-mode Q&A build: a fresh Ask-the-coach draft for this session --
  // same "one shared slot, reset on every open" convention as
  // handleOpenHistoryDetail's own workoutChat/workoutRpeEdit reset below.
  state.askCoachForm = createAskCoachForm();
  state.askCoachSubmit = createAskCoachSubmit();
  // Pushes an in-app history entry so hardware/gesture back (a `popstate`,
  // handled by handlePopState) closes the detail instead of navigating the
  // PWA away entirely -- same reasoning as handleOpenHistoryDetail's own
  // pushState.
  history.pushState({ planSessionDetail: id }, '');
  log.info('plan.session_detail_opened', { athlete: athleteSlug(), session_id: id });
  render();
  scrollToTop(); // land on the detail content -- was a gap in both this and
  // handleOpenHistoryDetail (neither scrolled), so the page previously
  // stayed wherever it was scrolled (e.g. down near the macro section).
  maybeLoadFeedback(); // so the section's past Q&A actually has data to show
}

/** Downloads a session's Garmin `.fit` file (see views.js's
 * renderGarminDownload / backend/app/routes/garmin.py) and saves it via a
 * synthetic, momentarily-appended `<a download>` -- the standard
 * Blob-to-file-save pattern, since a plain `<a href>` pointing straight at
 * the API can't carry the `Authorization` header the route requires. */
async function handleDownloadGarminFit(sessionId) {
  if (!sessionId) return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }

  log.info('plan.garmin_download_requested', { athlete: athleteSlug(), session_id: sessionId });
  const result = await downloadGarminFit({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), sessionId,
  });
  if (handleUnauthorized(result)) return;
  if (!result.ok) {
    log.error('plan.garmin_download_failed', { athlete: athleteSlug(), session_id: sessionId, error: result.error });
    window.alert(`Couldn't download the Garmin file: ${result.error}`);
    return;
  }

  const url = URL.createObjectURL(result.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = result.filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  log.info('plan.garmin_download_completed', { athlete: athleteSlug(), session_id: sessionId });
}

/** Pushes a session's workout to the athlete's Garmin watch via her
 * intervals.icu calendar (see views.js's renderGarminPush /
 * backend/app/routes/garmin.py's push-intervals route). Mirrors
 * handleDownloadGarminFit's shape -- config gate, log, call, unauthorized
 * check -- but the result is an inline message rendered from state rather
 * than a file save, since there's nothing to hand the browser. */
async function handlePushSessionToGarmin(sessionId) {
  if (!sessionId) return;
  if (state.sessionPush?.id === sessionId && state.sessionPush.status === 'pushing') return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }

  state.sessionPush = { id: sessionId, status: 'pushing', message: null };
  render();
  log.info('plan.garmin_push_requested', { athlete: athleteSlug(), session_id: sessionId });

  const result = await pushSessionToIntervals({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), sessionId,
  });
  if (handleUnauthorized(result)) return;

  if (result.ok) {
    log.info('plan.garmin_push_completed', { athlete: athleteSlug(), session_id: sessionId });
    state.sessionPush = {
      id: sessionId,
      status: 'success',
      // Deliberately mentions the one-time setup: from here a push looks
      // identical whether or not the athlete has ticked "Upload planned
      // workouts" in intervals.icu, so the only honest thing we can claim
      // is that it reached the calendar.
      message: 'Sent to your Intervals.icu calendar — it syncs to your watch from there.',
    };
  } else {
    log.error('plan.garmin_push_failed', {
      athlete: athleteSlug(), session_id: sessionId, error: result.error,
    });
    state.sessionPush = { id: sessionId, status: 'error', message: result.error };
  }
  render();
}

function handleCloseSessionDetail() {
  if (!state.planSessionDetailId) return; // avoids a redundant render on popstate re-entrancy
  state.planSessionDetailId = null;
  state.sessionPush = null;
  state.askCoachForm = createAskCoachForm();
  state.askCoachSubmit = createAskCoachSubmit();
  render();
}

/** Clears a stale session-detail selection after a plan refresh whose new
 * weeks no longer contain that session id (e.g. the week rolled off the
 * "current"/"next" window) -- called from loadPlan right after
 * state.plan.data is replaced, mirrors pruneDetailIdIfMissing for workouts. */
function pruneSessionDetailIdIfMissing(weeks) {
  if (state.planSessionDetailId && !findSessionById(weeks || [], state.planSessionDetailId)) {
    state.planSessionDetailId = null;
    state.sessionPush = null;
  }
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
// -- no second API call (see views.js's renderTrainingDashboardBody/renderWorkoutDetail).

/** `rpeEdit`, when given, opens the detail straight into A6b's RPE-edit
 * mode (see handleOpenHistoryDetailForRating below, the A6c chip's
 * handler) -- `null` (the default, every other caller) leaves
 * `state.workoutRpeEdit` cleared, same "only one detail-scoped edit at a
 * time" convention as `workoutChat`. */
function handleOpenHistoryDetail(id, { rpeEdit = null } = {}) {
  if (!id) return;
  state.workoutDetailId = id;
  // A fresh, empty scoped chat thread for this workout (see
  // closeWorkoutChat for the matching teardown on every close path).
  state.workoutChat = { workoutId: id, messages: [] };
  state.workoutRpeEdit = rpeEdit;
  // Coach-mode Q&A build: same "fresh draft on every open" reset as
  // handleOpenSessionDetail's own.
  state.askCoachForm = createAskCoachForm();
  state.askCoachSubmit = createAskCoachSubmit();
  // Pushes an in-app history entry so hardware/gesture back (which fires a
  // `popstate`, handled below) closes the detail instead of navigating the
  // PWA away entirely -- see handlePopState and onAppClick's `history:back`
  // case, which now goes through `history.back()` rather than calling
  // handleCloseHistoryDetail() directly, keeping browser history and app
  // state symmetric either way the detail gets closed.
  history.pushState({ workoutDetail: id }, '');
  log.info('history.detail_opened', { athlete: athleteSlug(), workout_id: id });
  render();
  scrollToTop(); // see handleOpenSessionDetail's matching call -- was a gap
  // in both handlers, not just the Plan tab's.
  maybeLoadFeedback(); // so the section's past Q&A actually has data to show
}

/** A6c: the "Rate this workout" row chip's action -- opens the same detail
 * view as a normal row tap, but with the RPE editor already open. Looks up
 * the workout in the already-loaded history (no second fetch) purely to
 * seed the editor's initial value (an unrated workout has none, so `''`,
 * matching the manual-log form's own "unset" convention). */
function handleOpenHistoryDetailForRating(id) {
  if (!id) return;
  const workout = (state.workoutHistory.data || []).find((w) => w.id === id);
  handleOpenHistoryDetail(id, {
    rpeEdit: {
      workoutId: id, rpe: workout?.rpe ?? '', status: 'idle', error: null,
    },
  });
}

/** The workout-detail RPE editor's "Edit RPE"/"Rate this workout" toggle
 * (renderRpeEditSection's non-editing button) -- opens edit mode for the
 * workout ALREADY showing in the detail view, unlike
 * handleOpenHistoryDetailForRating above (which also opens the detail
 * itself from a list row). */
function handleEditWorkoutRpe(id) {
  if (!id) return;
  const workout = (state.workoutHistory.data || []).find((w) => w.id === id);
  state.workoutRpeEdit = {
    workoutId: id, rpe: workout?.rpe ?? '', status: 'idle', error: null,
  };
  render();
}

function handleCancelEditWorkoutRpe() {
  state.workoutRpeEdit = null;
  render();
}

/** Saves the RPE editor's current value via `PATCH /api/workouts/{id}` --
 * mirrors handleSubmitLog's exact submit/api-call/re-render shape. On
 * success, refetches via the existing `loadHistory()` (never a hand-rolled
 * optimistic merge -- the just-saved workout's `load_au`/`load_tier` are
 * server-computed and would otherwise go stale in state until the next
 * natural refresh). */
async function handleSaveWorkoutRpe(id) {
  if (!state.workoutRpeEdit || state.workoutRpeEdit.workoutId !== id) return;
  if (state.workoutRpeEdit.status === 'submitting') return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.tab = 'settings';
    saveActiveTab(state.tab);
    render();
    return;
  }
  const rpeValue = state.workoutRpeEdit.rpe;
  if (rpeValue === '' || rpeValue === null || rpeValue === undefined) return;

  state.workoutRpeEdit = { ...state.workoutRpeEdit, status: 'submitting', error: null };
  render();
  log.info('workout.rpe_edit_submit', { athlete: athleteSlug(), workout_id: id });

  const result = await patchWorkout({
    baseUrl: settings.baseUrl,
    token: settings.token,
    athlete: athleteSlug(),
    workoutId: id,
    payload: { rpe: Number(rpeValue) },
  });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('workout.rpe_edit_success', { athlete: athleteSlug(), workout_id: id });
    state.workoutRpeEdit = null;
    loadHistory(); // refreshes history so the detail reflects the corrected rpe/load_au/load_tier; calls render() itself
  } else {
    log.error('workout.rpe_edit_failed', { athlete: athleteSlug(), workout_id: id, error: result.error });
    state.workoutRpeEdit = { ...state.workoutRpeEdit, status: 'error', error: result.error };
    render();
  }
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
  state.workoutRpeEdit = null;
  state.askCoachForm = createAskCoachForm();
  state.askCoachSubmit = createAskCoachSubmit();
  render();
}

/** Expands the Training Dashboard feed's paginated "Show more" affordance
 * (Build 1's renderTrainingDashboardBody, shared by both surfaces) -- keyed
 * off which tab is actually visible so the one `dashboard:show-more`
 * action name works for both without either surface needing to know about
 * the other's state slice. One-way (sets true, never toggles back) -- see
 * the click-delegation comment at this action's case for why. */
function handleShowMoreDashboardFeed() {
  if (state.tab === 'roster') {
    state.roster.feedExpanded = true;
  } else {
    state.dashboardFeedExpanded = true;
  }
  log.info('dashboard.feed_show_more', { athlete: athleteSlug(), tab: state.tab });
  render();
}

/** Expands the training-load chart's narrative (views.js's
 * renderCtlAtlTsbNarrative, web/two-panel-load-chart's first-line
 * truncation) -- same "keyed off which tab is actually visible, one-way
 * expand" convention as handleShowMoreDashboardFeed just above. */
function handleShowMoreLoadNarrative() {
  if (state.tab === 'roster') {
    state.roster.narrativeExpanded = true;
  } else {
    state.loadNarrativeExpanded = true;
  }
  log.info('load_chart.narrative_show_more', { athlete: athleteSlug(), tab: state.tab });
  render();
}

/** Selects the training-load chart's time window (plan.js's
 * LOAD_CHART_WINDOW_OPTIONS) from one of the pill buttons' own `data-key`
 * ('season', or a decimal day count) -- see views.js's
 * renderLoadChartWindowControls for how each pill encodes its own option.
 * A shared app-level preference (see state.loadWindowDays's own doc
 * comment for why), so this one handler covers both the athlete's own
 * Dashboard tab and the coach roster's acting-as-athlete view without
 * needing to branch on state.tab the way the per-surface handlers above
 * do. */
function handleSelectLoadWindow(key) {
  const days = key === 'season' ? null : Number(key);
  if (!LOAD_CHART_WINDOW_OPTIONS.some((o) => o.days === days)) return;
  if (state.loadWindowDays === days) return;
  state.loadWindowDays = days;
  saveLoadWindowDays(days);
  log.info('load_chart.window_selected', { athlete: athleteSlug(), days: days ?? 'season' });
  render();
}

// Closes whichever detail view is open on a hardware/gesture back press.
// Deliberately does NOT call history.back()/pushState itself -- it's the
// *target* of a popstate that already happened, so doing either here would
// create a pushState/popstate loop. All three handlers' own guards make this
// safe to call unconditionally on every popstate, including ones unrelated
// to any detail view. The three detail views live on different tabs (Log,
// Plan, roster) and are mutually exclusive in practice, but calling all
// three closers unconditionally needs no extra bookkeeping to stay correct
// if that ever changes.
function handlePopState() {
  handleCloseHistoryDetail();
  handleCloseSessionDetail();
  handleCloseCoachWorkoutDetail();
  handleCloseCoachSessionDetail();
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
/** The History tab's combined load status. It draws on two independent
 * fetches (workouts + plan), so it reports the worse of the two: an error in
 * either half means the feed on screen is incomplete and the athlete
 * deserves the retry affordance, and it's still "loading" while either is in
 * flight. Only "ready" once neither is pending or failed. */
function historyFeedStatus() {
  const statuses = [state.workoutHistory.status, state.plan.status];
  if (statuses.includes('error')) return 'error';
  if (statuses.includes('loading')) return 'loading';
  return 'ready';
}

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
    // Keeps the FULL list in state; HISTORY_DISPLAY_CAP is applied at
    // render time by the Dashboard tab instead (see
    // renderTrainingDashboardBody). It used to be truncated here, which the
    // dashboard's skip derivation can't tolerate: matching a planned session
    // against a 20-workout window would report every older session as
    // skipped purely because its workout had fallen off the end (see
    // history.js's buildHistoryFeed note).
    const sorted = sortWorkoutsNewestFirst(result.data);
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

/** Coach-mode Q&A build: unlike `maybeLoadProfile`/`maybeLoadGrants` above,
 * this is NOT gated on which tab is active -- the athlete's own Feedback
 * list (`state.feedbackEntries`) now also backs the Ask-the-coach section on
 * BOTH the Plan tab's session detail and the Dashboard tab's workout detail
 * (views.js's renderAskCoachSection call sites), not just the Feedback tab
 * itself, so it needs to load lazily on demand from whichever of those three
 * surfaces asks for it first. Called from handleOpenSessionDetail/
 * handleOpenHistoryDetail (in addition to setTab's own Feedback-tab lazy
 * load) -- same "never loaded yet, or let's retry" idle/error gate as every
 * other maybeLoad* helper in this file. */
function maybeLoadFeedback() {
  if (!isConfigured(state.settingsForm, state.identity)) return;
  if (state.feedbackEntries.status === 'loading' || state.feedbackEntries.status === 'ready') return;
  loadFeedback(); // calls render() itself
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

// --- Ask-the-coach Q&A (coach-mode Q&A build) -------------------------------
// The Plan tab's session detail and the Dashboard tab's workout detail each
// call POST /api/feedback/questions through a different linkage (session
// date+sport vs. workout_id -- see api.js's askAboutSession/askAboutWorkout),
// but otherwise share the exact same submit/render shape as
// handleSubmitFeedback above. `state.askCoachForm`/`state.askCoachSubmit`
// are shared across both call sites (see createAskCoachForm's doc comment)
// -- onAppClick's `ask-coach:submit` case branches on which detail view is
// actually open (state.tab + planSessionDetailId/workoutDetailId) to route
// to the right one of these two, same "branch on state, not a second action
// name" convention `session:open`'s click-dispatch case already uses.

async function handleSubmitAskCoachForSession() {
  if (state.askCoachSubmit.status === 'submitting') return;
  const id = state.planSessionDetailId;
  if (!id) return;
  const session = findSessionById(state.plan.data?.weeks || [], id);
  if (!session) return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  const body = (state.askCoachForm.body || '').trim();
  if (!body) {
    state.askCoachSubmit = { status: 'error', error: 'Ask something first.' };
    render();
    return;
  }

  state.askCoachSubmit = { status: 'submitting', error: null };
  render();
  log.info('ask_coach.submit', { athlete: athleteSlug(), scope: 'session', session_id: id });

  const result = await askAboutSession({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(),
    date: session.date, sport: session.sport, body,
  });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('ask_coach.submit_success', { athlete: athleteSlug(), scope: 'session' });
    state.askCoachForm = createAskCoachForm();
    state.askCoachSubmit = createAskCoachSubmit();
    // Optimistically prepend the new entry (the same shape a subsequent
    // GET /api/feedback would return it in -- most-recent-first) rather than
    // a full loadFeedback() refetch -- this is a one-shot AI answer already
    // fully resolved server-side by the time this response lands, so there's
    // nothing further for a refetch to pick up that this response doesn't
    // already have.
    state.feedbackEntries = {
      ...state.feedbackEntries,
      data: [result.data, ...state.feedbackEntries.data],
    };
  } else {
    log.error('ask_coach.submit_failed', { athlete: athleteSlug(), scope: 'session', error: result.error });
    state.askCoachSubmit = { status: 'error', error: result.error };
  }
  render();
}

async function handleSubmitAskCoachForWorkout() {
  if (state.askCoachSubmit.status === 'submitting') return;
  const id = state.workoutDetailId;
  if (!id) return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  const body = (state.askCoachForm.body || '').trim();
  if (!body) {
    state.askCoachSubmit = { status: 'error', error: 'Ask something first.' };
    render();
    return;
  }

  state.askCoachSubmit = { status: 'submitting', error: null };
  render();
  log.info('ask_coach.submit', { athlete: athleteSlug(), scope: 'workout', workout_id: id });

  const result = await askAboutWorkout({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), workoutId: id, body,
  });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('ask_coach.submit_success', { athlete: athleteSlug(), scope: 'workout' });
    state.askCoachForm = createAskCoachForm();
    state.askCoachSubmit = createAskCoachSubmit();
    // Same optimistic-prepend reasoning as handleSubmitAskCoachForSession.
    state.feedbackEntries = {
      ...state.feedbackEntries,
      data: [result.data, ...state.feedbackEntries.data],
    };
  } else {
    log.error('ask_coach.submit_failed', { athlete: athleteSlug(), scope: 'workout', error: result.error });
    state.askCoachSubmit = { status: 'error', error: result.error };
  }
  render();
}

// --- Coach mode (Phase 1): roster (My Athletes tab) + grants (Settings) ---
// See backend/app/routes/coach.py & grants.py. Two wholly separate access
// modes: the roster loaders below hit the coach-side routes (path-segment-
// scoped, resolved server-side from the caller's own coach_for -- NEVER
// athleteSlug(), which is the SELF-access helper), while the grants loaders
// hit the athlete-self-access routes (?athlete=<own slug> via athleteSlug()
// -- the athlete-side "who can coach me" view surfaced in Settings).

async function loadCoachedAthletes() {
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) {
    state.roster.athletes = { status: 'idle', data: [], error: null };
    render();
    return;
  }

  state.roster.athletes = { status: 'loading', data: state.roster.athletes.data, error: null };
  render();

  const result = await listCoachedAthletes({ baseUrl: settings.baseUrl, token: settings.token });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('roster.athletes_loaded', { count: result.data.length });
    state.roster.athletes = { status: 'ready', data: result.data, error: null };
  } else {
    log.error('roster.athletes_load_failed', { error: result.error });
    state.roster.athletes = { status: 'error', data: [], error: result.error };
  }
  render();
}

async function loadCoachWorkouts(slug) {
  const settings = state.settingsForm;
  if (!slug || !isConfigured(settings, state.identity)) {
    state.roster.workouts = { status: 'idle', data: [], error: null };
    render();
    return;
  }

  state.roster.workouts = { status: 'loading', data: state.roster.workouts.data, error: null };
  render();

  const result = await fetchCoachWorkouts({ baseUrl: settings.baseUrl, token: settings.token, athlete: slug });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('roster.workouts_loaded', { athlete: slug, count: result.data.length });
    state.roster.workouts = { status: 'ready', data: result.data, error: null };
  } else {
    log.error('roster.workouts_load_failed', { athlete: slug, error: result.error });
    state.roster.workouts = { status: 'error', data: [], error: result.error };
  }
  render();
}

async function loadCoachFeedback(slug) {
  const settings = state.settingsForm;
  if (!slug || !isConfigured(settings, state.identity)) {
    state.roster.feedback = { status: 'idle', data: [], error: null };
    render();
    return;
  }

  state.roster.feedback = { status: 'loading', data: state.roster.feedback.data, error: null };
  render();

  const result = await fetchCoachFeedback({ baseUrl: settings.baseUrl, token: settings.token, athlete: slug });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('roster.feedback_loaded', { athlete: slug, count: result.data.length });
    state.roster.feedback = { status: 'ready', data: result.data, error: null };
  } else {
    log.error('roster.feedback_load_failed', { athlete: slug, error: result.error });
    state.roster.feedback = { status: 'error', data: [], error: result.error };
  }
  render();
}

/** Fetches GET /api/coach/athletes/<slug>/health-status -- the acted-as
 * athlete's full health-status history (backend/health-status-record
 * build). Same {status, data, error} fetch-lifecycle shape as
 * `loadCoachFeedback` just above. */
async function loadCoachHealthStatus(slug) {
  const settings = state.settingsForm;
  if (!slug || !isConfigured(settings, state.identity)) {
    state.roster.healthStatus = { status: 'idle', data: [], error: null };
    render();
    return;
  }

  state.roster.healthStatus = { status: 'loading', data: state.roster.healthStatus.data, error: null };
  // Snapshot the version BEFORE awaiting -- see healthStatusVersion's own
  // doc comment above for the race this guards against.
  const startedAtVersion = state.roster.healthStatusVersion;
  render();

  const result = await fetchCoachHealthStatus({ baseUrl: settings.baseUrl, token: settings.token, athlete: slug });
  if (handleUnauthorized(result)) return;
  if (state.roster.healthStatusVersion !== startedAtVersion) {
    // A submit/resolve mutated state.roster.healthStatus.data while this
    // GET was in flight -- that local state is already more current (and
    // already durably saved server-side) than this response's snapshot,
    // so applying it now would silently undo a real, successful action.
    log.info('roster.health_status_load_discarded_stale', { athlete: slug });
    return;
  }
  if (result.ok) {
    log.info('roster.health_status_loaded', { athlete: slug, count: result.data.length });
    state.roster.healthStatus = { status: 'ready', data: result.data, error: null };
  } else {
    log.error('roster.health_status_load_failed', { athlete: slug, error: result.error });
    state.roster.healthStatus = { status: 'error', data: [], error: result.error };
  }
  render();
}

/** Submits the coach's "log a new health status" form (state.roster.
 * healthStatusForm) via POST /api/coach/athletes/<slug>/health-status. On
 * success, prepends the new entry to the loaded history (most-recent-first,
 * matching the GET route's own ordering) and clears the form draft --
 * same "patch state.roster.X.data locally instead of a full refetch"
 * convention `handleSubmitCoachReply` already uses. */
async function handleSubmitHealthStatus() {
  if (state.roster.healthStatusSubmit.status === 'submitting') return;
  const slug = state.roster.actingAsAthlete;
  if (!slug) return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  const form = state.roster.healthStatusForm;
  const description = (form.description || '').trim();
  if (!description) {
    state.roster.healthStatusSubmit = { status: 'error', error: 'Add a description first.' };
    render();
    return;
  }

  state.roster.healthStatusSubmit = { status: 'submitting', error: null };
  render();
  log.info('roster.health_status_submit', { athlete: slug, restriction: form.restriction });

  const result = await postCoachHealthStatus({
    baseUrl: settings.baseUrl,
    token: settings.token,
    athlete: slug,
    description,
    restriction: form.restriction,
    source: form.source,
    expectedReviewDate: form.expected_review_date,
  });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('roster.health_status_submit_success', { athlete: slug });
    state.roster.healthStatus = {
      ...state.roster.healthStatus,
      data: [result.data, ...state.roster.healthStatus.data],
    };
    state.roster.healthStatusVersion += 1; // see its own doc comment (stale-GET guard)
    state.roster.healthStatusForm = {
      description: '', restriction: 'light_only', source: 'self_reported', expected_review_date: '',
    };
    state.roster.healthStatusSubmit = { status: 'idle', error: null };
  } else {
    log.error('roster.health_status_submit_failed', { athlete: slug, error: result.error });
    state.roster.healthStatusSubmit = { status: 'error', error: result.error };
  }
  render();
}

/** Marks the athlete's current active health status resolved via
 * PATCH .../health-status/<id>. Same local-patch-on-success convention as
 * `handleSubmitHealthStatus`/`handleSubmitCoachReply` above. */
async function handleResolveHealthStatus(healthStatusId) {
  if (!healthStatusId) return;
  if (state.roster.healthStatusResolve.status === 'submitting') return;
  const slug = state.roster.actingAsAthlete;
  if (!slug) return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  state.roster.healthStatusResolve = { status: 'submitting', error: null, id: healthStatusId };
  render();
  log.info('roster.health_status_resolve', { athlete: slug, health_status_id: healthStatusId });

  const result = await resolveCoachHealthStatus({
    baseUrl: settings.baseUrl, token: settings.token, athlete: slug, healthStatusId,
  });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('roster.health_status_resolve_success', { athlete: slug, health_status_id: healthStatusId });
    state.roster.healthStatus = {
      ...state.roster.healthStatus,
      data: state.roster.healthStatus.data.map((entry) => (entry.id === result.data.id ? result.data : entry)),
    };
    state.roster.healthStatusVersion += 1; // see its own doc comment (stale-GET guard)
    state.roster.healthStatusResolve = { status: 'idle', error: null, id: null };
  } else {
    log.error('roster.health_status_resolve_failed', { athlete: slug, health_status_id: healthStatusId, error: result.error });
    state.roster.healthStatusResolve = { status: 'error', error: result.error, id: healthStatusId };
  }
  render();
}

/** Fetches GET /api/coach/athletes/<slug>/load for the roster tab's
 * CTL/ATL/TSB training-load chart (views.js's renderLoadChart) -- same
 * shape and pattern as loadCoachWorkouts/loadCoachFeedback above, just its
 * own state.roster.load slice (see api.js's fetchCoachLoad doc comment). */
async function loadCoachLoad(slug) {
  const settings = state.settingsForm;
  if (!slug || !isConfigured(settings, state.identity)) {
    state.roster.load = { status: 'idle', data: null, error: null };
    render();
    return;
  }

  state.roster.load = { status: 'loading', data: state.roster.load.data, error: null };
  render();

  const result = await fetchCoachLoad({ baseUrl: settings.baseUrl, token: settings.token, athlete: slug });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('roster.load_loaded', { athlete: slug, points: result.data.ctl_atl_tsb?.length ?? 0 });
    state.roster.load = { status: 'ready', data: result.data, error: null };
  } else {
    log.error('roster.load_load_failed', { athlete: slug, error: result.error });
    state.roster.load = { status: 'error', data: null, error: result.error };
  }
  render();
}

/** Fetches GET /api/coach/athletes/<slug>/plan (Build 2's new coach-plan
 * route) for the roster tab's Training Plan sub-tab (weeks/macro) and, via
 * its `weeks`, the Workouts + Dashboard sub-tab's skip-derivation -- same
 * shape/pattern as loadCoachWorkouts/loadCoachFeedback/loadCoachLoad above,
 * its own state.roster.plan slice (see api.js's fetchCoachPlan doc
 * comment). */
async function loadCoachPlan(slug) {
  const settings = state.settingsForm;
  if (!slug || !isConfigured(settings, state.identity)) {
    state.roster.plan = { status: 'idle', data: null, error: null };
    render();
    return;
  }

  state.roster.plan = { status: 'loading', data: state.roster.plan.data, error: null };
  render();

  const result = await fetchCoachPlan({ baseUrl: settings.baseUrl, token: settings.token, athlete: slug });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('roster.plan_loaded', { athlete: slug, weeks: result.data.weeks?.length ?? 0 });
    state.roster.plan = { status: 'ready', data: result.data, error: null };
    pruneRosterSessionDetailIdIfMissing(result.data.weeks);
  } else {
    log.error('roster.plan_load_failed', { athlete: slug, error: result.error });
    state.roster.plan = { status: 'error', data: null, error: result.error };
  }
  render();
}

/** Clears a stale coach-side session-detail selection after a plan refresh
 * whose new weeks no longer contain that session id (e.g. the week rolled
 * off the "current"/"next" window) -- mirrors pruneSessionDetailIdIfMissing
 * for the athlete's own Plan tab, scoped to state.roster.sessionDetailId. */
function pruneRosterSessionDetailIdIfMissing(weeks) {
  if (state.roster.sessionDetailId && !findSessionById(weeks || [], state.roster.sessionDetailId)) {
    state.roster.sessionDetailId = null;
  }
}

/** Opens one coached athlete's detail view (workouts + feedback + training
 * load + plan), fetching all four -- mirrors handleOpenHistoryDetail/
 * handleOpenSessionDetail's "set the selection, render, then fetch" shape,
 * minus the pushState/popstate wiring those two use (this is a tab-internal
 * list<->detail swap, not something a hardware back press needs to unwind
 * separately -- setTab already tears down every other tab's own detail view
 * the same way on tab-leave; there is no cross-tab back-button expectation
 * here). */
function handleSelectCoachedAthlete(slug) {
  if (!slug) return;
  state.roster.actingAsAthlete = slug;
  state.roster.workouts = { status: 'idle', data: [], error: null };
  state.roster.feedback = { status: 'idle', data: [], error: null };
  state.roster.load = { status: 'idle', data: null, error: null };
  state.roster.plan = { status: 'idle', data: null, error: null };
  state.roster.workoutDetailId = null;
  state.roster.sessionDetailId = null;
  state.roster.feedExpanded = false;
  state.roster.narrativeExpanded = false;
  state.roster.subTab = 'dashboard';
  state.roster.healthStatus = { status: 'idle', data: [], error: null };
  state.roster.healthStatusForm = {
    description: '', restriction: 'light_only', source: 'self_reported', expected_review_date: '',
  };
  state.roster.healthStatusSubmit = { status: 'idle', error: null };
  state.roster.healthStatusResolve = { status: 'idle', error: null, id: null };
  log.info('roster.athlete_selected', { athlete: slug });
  render();
  loadCoachWorkouts(slug); // calls render() itself
  loadCoachFeedback(slug); // calls render() itself
  loadCoachLoad(slug); // calls render() itself
  loadCoachPlan(slug); // calls render() itself
  loadCoachHealthStatus(slug); // calls render() itself
}

/** B3: leaving the roster's 'dashboard' sub-tab -- where the roster's own
 * Feedback section lives -- marks the coach role's unread badge seen.
 * Deliberately fired on LEAVE, not on entry/selection: marking seen the
 * instant the athlete is selected (before `loadCoachFeedback`'s fetch has
 * even resolved) would zero the badge before the coach ever actually saw
 * a nonzero count, defeating its whole purpose. Firing on leave instead
 * means the badge stays accurate (reflecting real unread state) for the
 * whole visit, only clearing once she's actually done looking and moves on
 * -- called from both ways out of the 'dashboard' sub-tab:
 * handleBackToRoster (closing the acted-as-athlete view entirely) and
 * handleSelectRosterSubTab (switching to a sibling sub-tab). A no-op if
 * `subTab` isn't (or wasn't) 'dashboard' -- e.g. backing out from the
 * Training Plan sub-tab never showed the Feedback section, so there's
 * nothing to mark seen. */
function markCoachFeedbackSeenIfLeavingDashboardSubTab(subTab) {
  if (subTab === 'dashboard') saveLastSeen('coach');
}

function handleBackToRoster() {
  markCoachFeedbackSeenIfLeavingDashboardSubTab(state.roster.subTab);
  state.roster.actingAsAthlete = null;
  state.roster.workouts = { status: 'idle', data: [], error: null };
  state.roster.feedback = { status: 'idle', data: [], error: null };
  state.roster.load = { status: 'idle', data: null, error: null };
  state.roster.plan = { status: 'idle', data: null, error: null };
  state.roster.workoutDetailId = null;
  state.roster.sessionDetailId = null;
  state.roster.feedExpanded = false;
  state.roster.narrativeExpanded = false;
  state.roster.subTab = 'dashboard';
  state.roster.healthStatus = { status: 'idle', data: [], error: null };
  state.roster.healthStatusForm = {
    description: '', restriction: 'light_only', source: 'self_reported', expected_review_date: '',
  };
  state.roster.healthStatusSubmit = { status: 'idle', error: null };
  state.roster.healthStatusResolve = { status: 'idle', error: null, id: null };
  render();
}

/** Switches the roster's acted-as-athlete view between its three sub-tabs
 * (Build 2: Conversations / Workouts + Dashboard / Training Plan) -- same
 * "no-op on unknown id or already-active" guard as setTab, scoped to
 * state.roster.subTab instead of state.tab. Closes any open workout-detail
 * or session-detail view first (same teardown setTab already does when
 * leaving the Dashboard/roster tabs entirely) so switching sub-tabs never
 * leaves a detail view open under a sub-tab it doesn't belong to. */
function handleSelectRosterSubTab(subTab) {
  if (!ROSTER_SUB_TABS.includes(subTab) || subTab === state.roster.subTab) return;
  // B3: same "mark seen on leave, not entry" reasoning as
  // handleBackToRoster's own call -- checked against the OLD sub-tab,
  // before it's overwritten below.
  markCoachFeedbackSeenIfLeavingDashboardSubTab(state.roster.subTab);
  if (state.roster.workoutDetailId) {
    state.roster.workoutDetailId = null;
    // Consumes the pushState entry handleOpenCoachWorkoutDetail added --
    // see setTab's matching roster teardown for why this is safe.
    history.back();
  }
  if (state.roster.sessionDetailId) {
    state.roster.sessionDetailId = null;
    // Consumes the pushState entry handleOpenCoachSessionDetail added --
    // see setTab's matching roster teardown for why this is safe.
    history.back();
  }
  state.roster.feedExpanded = false;
  state.roster.narrativeExpanded = false;
  state.roster.subTab = subTab;
  log.info('roster.subtab_switch', { subtab: subTab });
  render();
}

/** Opens one coached athlete's workout detail view (read-only -- no
 * embedded chat, see views.js's renderRosterTab, which calls the same
 * renderWorkoutDetail the athlete's own History tab uses with `chat: null`
 * so the chat section renders as a no-op). */
function handleOpenCoachWorkoutDetail(id) {
  if (!id) return;
  state.roster.workoutDetailId = id;
  // Pushes an in-app history entry so hardware/gesture back (a `popstate`,
  // handled by handlePopState) closes the detail instead of navigating the
  // PWA away entirely -- same reasoning as handleOpenHistoryDetail's own
  // pushState.
  history.pushState({ rosterWorkoutDetail: id }, '');
  log.info('roster.workout_detail_opened', { athlete: state.roster.actingAsAthlete, workout: id });
  render();
}

function handleCloseCoachWorkoutDetail() {
  if (!state.roster.workoutDetailId) return; // avoids a redundant render on popstate re-entrancy
  state.roster.workoutDetailId = null;
  render();
}

/** Opens one coached athlete's session detail view from the Training Plan
 * sub-tab (fixing the reported "can't open workouts to see the detail" bug)
 * -- read-only, same real structure/targets/zone breakdown/rationale/purpose
 * content the athlete sees (views.js's renderPlanSessionDetail), but with
 * the two Garmin push/download actions suppressed (`showGarminActions:
 * false` -- see that function's doc comment for why: they'd act on the
 * SIGNED-IN coach's own athlete slug via athleteSlug(), not the coached
 * athlete's, and the backend routes have no resolve_coach_athlete support).
 * Sets state.roster.sessionDetailId, its OWN slice -- deliberately separate
 * from the athlete's own state.planSessionDetailId/state.sessionPush, so a
 * coach's own Plan tab session and a coached athlete's session can be open
 * independently without colliding. Mirrors handleOpenCoachWorkoutDetail's
 * pushState/popstate shape exactly, for the same hardware/gesture
 * back-button support. */
function handleOpenCoachSessionDetail(id) {
  if (!id) return;
  state.roster.sessionDetailId = id;
  // Pushes an in-app history entry so hardware/gesture back (a `popstate`,
  // handled by handlePopState) closes the detail instead of navigating the
  // PWA away entirely -- same reasoning as handleOpenCoachWorkoutDetail's
  // own pushState.
  history.pushState({ rosterSessionDetail: id }, '');
  log.info('roster.session_detail_opened', { athlete: state.roster.actingAsAthlete, session: id });
  render();
}

function handleCloseCoachSessionDetail() {
  if (!state.roster.sessionDetailId) return; // avoids a redundant render on popstate re-entrancy
  state.roster.sessionDetailId = null;
  render();
}

async function handleSubmitCoachReply(feedbackId) {
  if (!feedbackId) return;
  if (state.roster.replySubmit.status === 'submitting') return;
  const slug = state.roster.actingAsAthlete;
  if (!slug) return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  const draft = (state.roster.replyDrafts[feedbackId] || '').trim();
  if (!draft) {
    state.roster.replySubmit = { status: 'error', error: 'Write a reply first.', feedbackId };
    render();
    return;
  }

  state.roster.replySubmit = { status: 'submitting', error: null, feedbackId };
  render();
  log.info('roster.reply_submit', { athlete: slug, feedback_id: feedbackId });

  const result = await replyToCoachFeedback({
    baseUrl: settings.baseUrl, token: settings.token, athlete: slug, feedbackId, coachReply: draft,
  });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('roster.reply_submit_success', { athlete: slug, feedback_id: feedbackId });
    state.roster.feedback = {
      ...state.roster.feedback,
      data: state.roster.feedback.data.map((entry) => (entry.id === result.data.id ? result.data : entry)),
    };
    delete state.roster.replyDrafts[feedbackId];
    state.roster.replySubmit = { status: 'idle', error: null, feedbackId: null };
  } else {
    log.error('roster.reply_submit_failed', { athlete: slug, feedback_id: feedbackId, error: result.error });
    state.roster.replySubmit = { status: 'error', error: result.error, feedbackId };
  }
  render();
}

// --- Grants (Settings tab: "who can coach me") ------------------------------

async function loadGrants() {
  const settings = state.settingsForm;
  const identity = state.identity;
  if (!isConfigured(settings, identity)) {
    state.grants.entries = { status: 'idle', data: [], error: null };
    render();
    return;
  }

  state.grants.entries = { status: 'loading', data: state.grants.entries.data, error: null };
  render();

  const result = await listGrants({ baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug() });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('grants.list_loaded', { count: result.data.length });
    state.grants.entries = { status: 'ready', data: result.data, error: null };
  } else {
    log.error('grants.list_load_failed', { error: result.error });
    state.grants.entries = { status: 'error', data: [], error: result.error };
  }
  render();
}

// Triggers loadGrants() only when it's actually useful -- same "on the
// right tab, configured, not already loading/loaded" gate as
// maybeLoadProfile(), which this is called alongside everywhere (see every
// maybeLoadProfile() call site below).
function maybeLoadGrants() {
  if (state.tab !== 'settings') return;
  if (!isConfigured(state.settingsForm, state.identity)) return;
  if (state.grants.entries.status === 'loading' || state.grants.entries.status === 'ready') return;
  loadGrants();
}

async function handleGrantSubmit() {
  if (state.grants.createSubmit.status === 'submitting') return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  const coachSlug = (state.grants.createForm.coachSlug || '').trim();
  if (!coachSlug) {
    state.grants.createSubmit = { status: 'error', error: 'Enter a coach slug first.' };
    render();
    return;
  }

  state.grants.createSubmit = { status: 'submitting', error: null };
  render();
  log.info('grants.create_submit', { athlete: athleteSlug() });

  const result = await createGrant({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), coachSlug,
  });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('grants.create_submit_success', { athlete: athleteSlug() });
    state.grants.entries = { ...state.grants.entries, data: [...state.grants.entries.data, result.data] };
    state.grants.createForm = { coachSlug: '' };
    state.grants.createSubmit = { status: 'idle', error: null };
  } else {
    log.error('grants.create_submit_failed', { athlete: athleteSlug(), error: result.error });
    state.grants.createSubmit = { status: 'error', error: result.error };
  }
  render();
}

/** Fire-and-forget with logging, no dedicated submit-status slot -- a
 * revoke is a single small state flip on an already-visible row (same
 * spirit as the Plan tab's Garmin push not needing its own draft-form
 * state). On failure the row just stays as-is and the failure is logged;
 * the athlete can simply try again. */
async function handleRevokeGrant(grantId) {
  if (!grantId) return;
  const settings = state.settingsForm;
  if (!isConfigured(settings, state.identity)) return;

  log.info('grants.revoke', { athlete: athleteSlug(), grant_id: grantId });
  const result = await revokeGrant({
    baseUrl: settings.baseUrl, token: settings.token, athlete: athleteSlug(), grantId,
  });
  if (handleUnauthorized(result)) return;
  if (result.ok) {
    log.info('grants.revoke_success', { athlete: athleteSlug(), grant_id: grantId });
    state.grants.entries = {
      ...state.grants.entries,
      data: state.grants.entries.data.map((g) => (g.id === result.data.id ? result.data : g)),
    };
    render();
  } else {
    log.error('grants.revoke_failed', { athlete: athleteSlug(), grant_id: grantId, error: result.error });
  }
}

// --- Tab switching ------------------------------------------------------------

function setTab(tab) {
  if (!KNOWN_TABS.includes(tab) || tab === state.tab) return;
  // Leaving the Dashboard tab always collapses the secondary manual-entry/
  // upload section back down, and the paginated feed back to its default
  // recent slice -- coming back to the Dashboard should land on the primary
  // sync button and the short feed, not wherever the athlete last left
  // either secondary affordance.
  if (state.tab === 'dashboard') {
    state.logManualOpen = false;
    state.dashboardFeedExpanded = false;
  state.loadNarrativeExpanded = false;
  }
  // Leaving the Dashboard tab always drops any open workout-detail view --
  // coming back should land on the feed, not wherever the athlete last was.
  if (state.tab === 'dashboard' && state.workoutDetailId) {
    state.workoutDetailId = null;
    closeWorkoutChat();
    state.workoutRpeEdit = null;
    state.askCoachForm = createAskCoachForm();
    state.askCoachSubmit = createAskCoachSubmit();
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
  // Same teardown for the roster tab's workout-detail view -- coming back to
  // My Athletes should land on the acting-as athlete's lists, not wherever
  // the coach last was.
  if (state.tab === 'roster' && state.roster.workoutDetailId) {
    state.roster.workoutDetailId = null;
    // Consumes the pushState entry handleOpenCoachWorkoutDetail added, keeping
    // browser history symmetric with app state -- see the matching Log-tab
    // comment above for why this is safe (handlePopState's
    // handleCloseCoachWorkoutDetail() is a no-op once the id is already null).
    history.back();
  }
  // Same teardown for the roster's Training Plan sub-tab's session-detail
  // view -- coming back to My Athletes should land on the acted-as
  // athlete's lists, not a stale session detail from a sub-tab that isn't
  // even showing any more.
  if (state.tab === 'roster' && state.roster.sessionDetailId) {
    state.roster.sessionDetailId = null;
    // Consumes the pushState entry handleOpenCoachSessionDetail added,
    // keeping browser history symmetric with app state -- see the matching
    // Log-tab comment above for why this is safe (handlePopState's
    // handleCloseCoachSessionDetail() is a no-op once the id is already
    // null).
    history.back();
  }
  // Same teardown for the Plan tab's session-detail view -- coming back to
  // Plan should land on "This week"/"Next week", not wherever the athlete
  // last was.
  if (state.tab === 'plan' && state.planSessionDetailId) {
    state.planSessionDetailId = null;
    state.sessionPush = null;
    state.askCoachForm = createAskCoachForm();
    state.askCoachSubmit = createAskCoachSubmit();
    // Consumes the pushState entry handleOpenSessionDetail added, keeping
    // browser history symmetric with app state -- see the matching Log-tab
    // comment above for why this is safe (handlePopState's
    // handleCloseSessionDetail() is a no-op once the id is already null).
    history.back();
  }
  state.tab = tab;
  saveActiveTab(tab);
  log.info('tab.switch', { tab });
  // B3: the athlete's Feedback tab is the "relevant section" for the
  // athlete-role unread badge -- mark it seen the moment she opens it,
  // regardless of whether a fetch below is also triggered. Using "now" (not
  // waiting for the fetch to resolve) is correct: every entry's
  // coach_reply_at is already fixed in the past relative to this instant, so
  // nothing the in-flight fetch returns can retroactively count as unread.
  if (tab === 'feedback') saveLastSeen('athlete');
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
  // Same lazy-load convention as Feedback above. Note: only the athletes
  // LIST is refetched on tab-entry -- entering with `actingAsAthlete` still
  // set (e.g. a re-render while already inside a coached athlete's detail
  // view) deliberately does NOT re-fetch that athlete's workouts/feedback
  // here; those loads happen once, from handleSelectCoachedAthlete, when
  // the athlete is first selected.
  if (tab === 'roster' && (state.roster.athletes.status === 'idle' || state.roster.athletes.status === 'error')
    && isConfigured(state.settingsForm, state.identity)) {
    loadCoachedAthletes(); // calls render() itself
    return;
  }
  // The merged Dashboard tab (Build 1: Log+History) needs THREE things:
  // the workouts it shows as completed (shouldLoadHistoryNow -- was Log's
  // own trigger), the plan weeks it derives skipped sessions from (was
  // History's own trigger), and the CTL/ATL/TSB chart's data (was the Plan
  // tab's own trigger, moved here since the chart moved off the Plan tab).
  // Any of the three may already be loaded (from a previous Plan/Dashboard
  // visit), so each is requested independently; all three call render()
  // themselves as they land, and the tab renders whatever's already in
  // state in the meantime rather than blocking on all three at once.
  if (tab === 'dashboard') {
    let requested = false;
    if ((state.plan.status === 'idle' || state.plan.status === 'error')
      && isConfigured(state.settingsForm, state.identity)) {
      loadPlan();
      requested = true;
    }
    if ((state.planLoad.status === 'idle' || state.planLoad.status === 'error')
      && isConfigured(state.settingsForm, state.identity)) {
      loadPlanLoad();
      requested = true;
    }
    if (shouldLoadHistoryNow()) {
      loadHistory();
      requested = true;
    }
    if (requested) return;
  }
  render();
  maybeLoadProfile();
  maybeLoadGrants();
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
  if (action.startsWith('roster:subtab:')) {
    handleSelectRosterSubTab(action.slice('roster:subtab:'.length));
    return;
  }
  if (action.startsWith('load-chart:window:')) {
    handleSelectLoadWindow(action.slice('load-chart:window:'.length));
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
    // Coach-mode Q&A build: one shared button action, routed to whichever
    // detail view is actually open -- same "branch on state, not a second
    // action name for the same shared markup" convention `session:open`'s
    // own case below already uses. A stray click while NEITHER detail view
    // is open (shouldn't happen -- the button only renders inside one of
    // them) is simply a no-op, since both handlers bail out when their own
    // detail id is unset.
    case 'ask-coach:submit':
      if (state.tab === 'plan') handleSubmitAskCoachForSession();
      else handleSubmitAskCoachForWorkout();
      break;
    case 'roster:select-athlete': handleSelectCoachedAthlete(el.dataset.slug); break;
    case 'roster:back': handleBackToRoster(); break;
    case 'roster:open-workout': handleOpenCoachWorkoutDetail(el.dataset.id); break;
    // Goes through history.back() (not handleCloseCoachWorkoutDetail()
    // directly) so the in-app "close" affordance and a hardware/gesture
    // back press close the detail via the exact same path -- see
    // handlePopState. Same reasoning as history:back/session:back below.
    case 'roster:close-workout': history.back(); break;
    case 'roster:reply-submit': handleSubmitCoachReply(el.dataset.id); break;
    case 'roster:health-status-submit': handleSubmitHealthStatus(); break;
    case 'roster:health-status-resolve': handleResolveHealthStatus(el.dataset.id); break;
    case 'grants:submit': handleGrantSubmit(); break;
    case 'grants:revoke': handleRevokeGrant(el.dataset.id); break;
    case 'onboard:submit': handleOnboardSubmit(); break;
    case 'history:retry': loadHistory(); break;
    case 'history:open': handleOpenHistoryDetail(el.dataset.id); break;
    // A6c: the "Rate this workout" row chip -- opens the same detail view
    // as a plain row tap, with the RPE editor already open.
    case 'history:open-rate': handleOpenHistoryDetailForRating(el.dataset.id); break;
    // A6b: the workout-detail RPE editor.
    case 'workout:edit-rpe': handleEditWorkoutRpe(el.dataset.id); break;
    case 'workout:cancel-edit-rpe': handleCancelEditWorkoutRpe(); break;
    case 'workout:save-rpe': await handleSaveWorkoutRpe(el.dataset.id); break;
    // Shared by both Training Dashboard surfaces (Build 1's
    // renderTrainingDashboardBody) -- expands the athlete's own dashboard
    // feed while on the Dashboard tab, or the coach roster's feed while
    // acting as an athlete on the roster tab. One-way expand (no collapse
    // control): "show everything" is the only direction a "Show more"
    // affordance needs.
    case 'dashboard:show-more': handleShowMoreDashboardFeed(); break;
    // Shared by both Training Dashboard surfaces the same way
    // 'dashboard:show-more' just above is -- expands the training-load
    // chart's narrative (web/two-panel-load-chart) on whichever surface is
    // currently visible.
    case 'load-chart:narrative-more': handleShowMoreLoadNarrative(); break;
    // Goes through history.back() (not handleCloseHistoryDetail() directly)
    // so the in-app "back" affordance and a hardware/gesture back press
    // close the detail via the exact same path -- see handlePopState.
    case 'history:back': history.back(); break;
    // Shared data-a="session:open" markup between the athlete's own Plan tab
    // and the coach roster's Training Plan sub-tab (views.js's renderSession)
    // -- branch on state.tab to route the click to the right piece of state
    // rather than inventing a second, differently-named action for the same
    // row markup. See handleOpenSessionDetail's doc comment for why its own
    // internal guard still exists as defense-in-depth.
    case 'session:open':
      if (state.tab === 'roster') handleOpenCoachSessionDetail(el.dataset.id);
      else handleOpenSessionDetail(el.dataset.id);
      break;
    // Same history.back()-not-direct-close reasoning as history:back above.
    // Generic on purpose: whichever of handleCloseSessionDetail/
    // handleCloseCoachSessionDetail actually has an open id is the one
    // handlePopState's resulting popstate will close (each is a no-op when
    // its own id is already null), so this single case correctly closes
    // either the athlete's own Plan tab detail or the coach's, without
    // needing to know which one is open.
    case 'session:back': history.back(); break;
    case 'session:garmin-download': await handleDownloadGarminFit(el.dataset.id); break;
    case 'session:push-intervals': await handlePushSessionToGarmin(el.dataset.id); break;
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
    } else if (field === 'email_notifications_enabled') {
      // B4: a plain checkbox, not a text/select input -- read `.checked`,
      // same convention as the pool-day checkboxes just above.
      state.profileForm.emailNotificationsEnabled = el.checked;
    } else {
      state.profileForm[field] = el.value;
    }
  }
  else if (formName === 'feedback') state.feedbackForm[field] = el.value;
  // Coach-mode Q&A build: shared draft field for both Ask-the-coach call
  // sites (Plan tab session detail, Dashboard tab workout detail) -- see
  // createAskCoachForm's doc comment for why one flat slice covers both.
  else if (formName === 'askCoach') state.askCoachForm[field] = el.value;
  // Keyed by per-row feedback id (data-id), not a flat form field like every
  // other case here -- see state.roster.replyDrafts's doc comment at its
  // declaration for why a plain object keyed this way is enough.
  else if (formName === 'roster-reply') {
    const id = el.dataset.id;
    if (id) state.roster.replyDrafts[id] = el.value;
  }
  // The roster's "log a health status" form -- a plain flat draft object
  // (state.roster.healthStatusForm), same convention as `feedbackForm`/
  // `askCoachForm` above (there is only ever one such form per athlete, not
  // one per row, unlike `roster-reply`'s per-feedback-id draft map).
  else if (formName === 'roster-health-status') state.roster.healthStatusForm[field] = el.value;
  else if (formName === 'grants') state.grants.createForm[field] = el.value;
  // A6b: the workout-detail RPE editor's own slider -- guarded on
  // workoutRpeEdit still being set (defensive against a stray late event
  // after Cancel/Save already cleared it).
  else if (formName === 'workoutRpe' && state.workoutRpeEdit) state.workoutRpeEdit[field] = el.value;
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
  // A6a: the CR-10 slider's live verbal-anchor caption (renderCr10SliderField's
  // `data-slider-anchor`, shared by both the manual-log form and the
  // workout-detail RPE editor) -- same direct-DOM-patch convention as
  // `data-slider-out` above, updated as one number-in/anchor-out pair.
  const anchorId = el.dataset.sliderAnchor;
  if (anchorId) {
    const anchorEl = document.getElementById(anchorId);
    if (anchorEl) anchorEl.textContent = cr10AnchorLabel(el.value) || '—';
  }

  // The Dashboard tab's manual-entry Save button is gated on RPE being set
  // (see views.js's renderManualLogSection `rpeMissing` -- a file upload
  // resets rpe to '' so the athlete must move the slider at least once). That gate has to
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
  // Same live-gating convention for the workout-detail RPE editor's own
  // Save button (views.js's renderRpeEditSection).
  if (formName === 'workoutRpe' && field === 'rpe' && state.workoutRpeEdit) {
    const missing = state.workoutRpeEdit.rpe === '' || state.workoutRpeEdit.rpe === null || state.workoutRpeEdit.rpe === undefined;
    const saveBtn = document.querySelector('[data-a="workout:save-rpe"]');
    if (saveBtn) saveBtn.disabled = missing || state.workoutRpeEdit.status === 'submitting';
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
const TABS_SENSITIVE_TO_ONLINE_STATE = ['coach', 'dashboard', 'checkin'];

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
// `toggle` does not bubble, so this listens in the capture phase rather than
// relying on the delegation onAppClick uses. Records the accordion's state
// WITHOUT re-rendering -- the DOM is already in the right shape; this only
// makes the NEXT render reproduce it.
appEl.addEventListener('toggle', (event) => {
  const details = event.target;
  if (!(details instanceof HTMLDetailsElement)) return;
  // Two independently-tracked accordions share this one listener (see each
  // flag's own doc comment at its state declaration) -- deliberately NOT an
  // else-if, though only one class is ever present on a given element, so
  // there's no ordering hazard either way. Every other <details> in the app
  // (e.g. a per-step coaching-cue expand, views.js's .struct-step-toggle)
  // is intentionally NOT tracked here -- its open/closed state resetting on
  // the next re-render is an acceptable, low-stakes tradeoff for a
  // step-level toggle, unlike these two page-level accordions.
  if (details.classList.contains('all-weeks')) state.allWeeksOpen = details.open;
  if (details.classList.contains('glossary')) state.glossaryOpen = details.open;
}, true);
appEl.addEventListener('change', onAppChange);
appEl.addEventListener('input', onAppInput);
appEl.addEventListener('keydown', onAppKeydown);

log.info('app.init', { version: __APP_VERSION__ ?? 'dev' });
updateOfflineBanner();
render();
loadPlan();
loadPlanLoad();
maybeLoadProfile();
maybeLoadGrants();
// loadPlan() above self-gates on isConfigured and is otherwise unconditional
// at boot; loadHistory() has no such caller-independent self-gate -- until
// now the only caller was setTab's Dashboard-tab branch, so history stayed
// stuck on 'idle' forever if the athlete reopened the PWA with the
// Dashboard already the persisted active tab (state.tab restores from
// localStorage without ever calling setTab, since no navigation happened).
// Covers that case the same way setTab does -- see shouldLoadHistoryNow().
// state.identity is already resolved synchronously above (identity.js's
// currentIdentity() is a plain localStorage read, no network round trip --
// see initialIdentity at the top of this file), so this reads the same
// populated state setTab would.
if (state.tab === 'dashboard' && shouldLoadHistoryNow()) {
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
