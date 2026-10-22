// Who may see which messages in a workout's chat thread. A human coach's private "Ask AI coach"
// exchange is stored with visibility "coach_only"; the backend already strips it from every
// athlete-facing response, and this is the matching client-side guard (defence in depth).

export const COACH_ONLY = 'coach_only';
export const COACH_ONLY_LABEL = 'Only you can see this';

/** `messages` filtered for `viewerRole` ('athlete' | 'coach'): the athlete never sees coach-only. */
export function visibleThreadMessages(messages, viewerRole) {
  const all = messages || [];
  return viewerRole === 'coach' ? all : all.filter((m) => m?.visibility !== COACH_ONLY);
}
