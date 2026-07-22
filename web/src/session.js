// Pure sign-out orchestration, factored out of main.js's handleSignOut so
// it's unit-testable without main.js's DOM/window side effects (main.js
// boots the whole app -- render(), event listeners, loadPlan() -- at import
// time, so importing it directly in a Node-environment vitest run isn't
// practical; see this repo's other pure-logic modules, e.g. chat.js/
// workouts.js, for the same pattern of keeping main.js a thin DOM-glue
// orchestrator around testable pieces like this one).
//
// Every side-effecting dependency is injected (api.js's `logout`,
// settings.js's `saveSettings`, identity.js's `signOut`) so the test can
// assert both *that* they were called and the resulting settings, without
// touching real localStorage/GIS/network.

/**
 * Revokes the server session (best-effort -- see api.js's `logout` doc
 * comment: it never throws) when there's an actual token to revoke, clears
 * the local identity, and returns settings with the token emptied. Skips the
 * revoke call entirely when there's no token or base URL to send it to --
 * nothing to revoke, and it'd just be a wasted request.
 */
export async function performSignOut({
  settingsForm, logout, saveSettings, signOut,
}) {
  const { baseUrl, token } = settingsForm;
  if (baseUrl && token) {
    await logout({ baseUrl, token });
  }
  signOut();
  return saveSettings({ baseUrl, token: '' });
}
