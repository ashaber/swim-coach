# Design: self-service in-app onboarding

Status: **proposal** — not implemented. No feature code changes in this PR.

## Goal

Replace admin-run CLI provisioning (`cli.py onboard`, PR #62 / issue #61)
with a flow where an *invited* user signs in with Google, enters their own
hard data, defines their plan by chatting with the coach, and is
provisioned — no admin hand-authoring YAML, no `migrate_files_to_db.py`.

## End-state UX

1. Andrew invites an email (allowlisted) — **no athlete record exists yet**.
2. That user's first Google sign-in resolves to "allowlisted, no athlete" →
   the app enters **onboarding mode** instead of the ordinary tabs.
3. Hard-data form: CSS pace (or a 400m/200m test time), height, weight,
   sex, target event(s) (date + distance + format).
4. Coach chat collects periodization intent (target event, current + peak
   weekly volume, macro start) and triggers the engine
   (`scaffold_macro`/`generate_week`).
5. `provision_athlete` (engine/swim_coach/provision.py) persists
   athlete + zones + macro + first week + allowlist link — the same
   function `cli.py onboard` calls today (PR #62), reused verbatim.

---

## 1. The allowlist-before-athlete tension

### The blocker

`allowed_emails.athlete_id` is `uuid NOT NULL references athletes`
(`supabase/migrations/20260714000000_identity.sql:30`). Every current
write path creates the athlete **first**, then the allowlist row:
`provision_athlete` calls `store.save_athlete(athlete)` before
`store.add_allowed_email(athlete.slug, email, ...)`
(`engine/swim_coach/provision.py:145,180`), and the standalone `cli invite`
command explicitly documents that it "can't provision a brand-new athlete"
against a DB store because the FK requires the athlete to already exist
(`engine/swim_coach/cli.py:703-716`). Self-service inverts this: the whole
point is to invite an email with **no** athlete behind it yet.

`POST /api/auth/google` makes the same assumption on the read side —
`allowed = store.get_allowed_email(email)`, then unconditionally
`athlete = store.load_athlete(allowed.athlete_slug)`
(`backend/app/routes/auth.py:73-80`) — there's no code path today for "the
email is allowlisted but there's no athlete slug to load yet."

### Proposed change: nullable `athlete_id`, not a parallel table

Make `athlete_id` nullable on both `allowed_emails` and `auth_sessions`,
and treat `athlete_id IS NULL` as the pending/onboarding state. Rejected
alternative: a separate `pending_invites` table mirroring `allowed_emails`.
That duplicates the email-uniqueness/note/created_at shape and adds a
second lookup `POST /api/auth/google` must check — nullable FK keeps one
table, one query, and the state transition is a single `UPDATE` (see
below), not a delete-from-one-table-insert-into-another migration.

```sql
alter table allowed_emails alter column athlete_id drop not null;
alter table auth_sessions alter column athlete_id drop not null;
alter table auth_sessions add column email text;
create index if not exists auth_sessions_email_idx on auth_sessions(email)
  where athlete_id is null;
```

`auth_sessions.email` is new and only populated for a pending/onboarding
session — an athlete-bound session still resolves everything it needs via
its `athlete_id` FK (unchanged). It's needed because a session with no
`athlete_id` has nothing else to join back to `athletes` through, and
`require_auth` needs *some* stable identity to key the onboarding
principal, the per-athlete-style daily chat cap (§4), and the eventual
`provision_athlete(email=...)` call on.

**Model changes** (`engine/swim_coach/models.py`):
- `AllowedEmail.athlete_slug: str` → `str | None = None`.
- `AuthSession.athlete_slug: str` → `str | None = None`; add
  `email: str | None = None`.

**Store changes**:
- New `StoreInterface.invite_pending_email(email, *, note=None) ->
  AllowedEmail` — inserts a row with `athlete_id NULL`, no slug argument
  (there's no athlete to validate against, unlike `add_allowed_email`,
  which deliberately keeps validating its `slug` argument for the existing
  admin-invites-an-existing-athlete path — see `add_allowed_email`'s own
  docstring, `store.py:155-164`). Keeping these as two methods rather than
  making `slug` optional on `add_allowed_email` preserves that method's
  fail-fast-on-unknown-athlete invariant for every existing caller.
- `add_allowed_email` (already an upsert keyed by email — `store_db.py:592-593`
  `on conflict (email) do update set athlete_id = excluded.athlete_id`)
  needs **no change** to *link* a pending invite once the athlete is
  created: `provision_athlete`'s existing call
  (`store.add_allowed_email(athlete.slug, email, note=note)`,
  `provision.py:180`) already overwrites the pending row's `athlete_id`
  from `NULL` to the new athlete — the upsert *is* the state transition.
- `DbStore.get_allowed_email`/`list_allowed_emails` currently `join`
  (inner) `athletes` (`store_db.py:611,625`) — this silently **drops any
  pending invite** from every read. Both must become `left join`, and
  `row_to_allowed_email` must tolerate `athlete_slug is None`
  (`store_db.py:168-178`). `FileStore`'s JSON-dict version already
  tolerates this shape once the model allows `athlete_slug: None` — no
  read-path change needed there, only the model.
- `create_session`/`get_session` gain an `email` param/field alongside the
  now-optional `slug`, threading straight from `auth_sessions.email`.

### `POST /api/auth/google`'s new branch

```
allowed = store.get_allowed_email(email)
if allowed is None: 403 "request access"          # unchanged
if allowed.athlete_id is None:                     # NEW: pending invite
    session = store.create_session(slug=None, email=email, token_hash=..., expires_at=...)
    return {"token": raw_token, "onboarding": True, "expires_at": ...}
# unchanged athlete-bound path
athlete = store.load_athlete(allowed.athlete_slug)
session = store.create_session(allowed.athlete_slug, ..., ...)
return {"token": raw_token, "athlete": athlete.slug, "name": ..., "role": ..., "expires_at": ...}
```

The response shape is deliberately distinguishable (`"onboarding": true`
vs. `"athlete": "..."`) so `web/src/identity.js`'s `signIn()` can route to
the onboarding UI instead of the normal signed-in state without an extra
round trip.

### Implication for `resolve_athlete` / `Principal`

`Principal.kind` (`backend/app/auth.py:53,70`) gains a third value:
`Literal["service", "athlete", "onboarding"]`. An onboarding principal
carries `email: str`, `athlete: None`. `resolve_athlete`
(`auth.py:115-137`) is unchanged and must **stay** unreachable for an
onboarding principal — every existing athlete-scoped route (`/api/chat`,
`/api/athlete`, `/api/workouts`, `/api/wellness`, ...) should keep 403ing
it, the same guarantee `resolve_athlete` already gives against
cross-athlete access (`auth.py:134`, "a mismatched athlete in the request
is a 403") (§5 covers this as the security requirement, not just an
incidental type change).

---

## 2. New backend endpoint: create-athlete-from-onboarding

Contrast with `PATCH /api/athlete` (`backend/app/routes/athlete.py`):
that route is edit-only — it 404s if `store.load_athlete(athlete)` raises
`FileNotFoundError` (`athlete.py:66-68`) and has no create path by design.
The onboarding endpoint is the create path that route deliberately
doesn't have.

**`POST /api/onboarding/provision`** (new router,
`backend/app/routes/onboarding.py`):

- **Auth**: a new `require_onboarding_principal` dependency — 403 unless
  `principal.kind == "onboarding"`. Never accepts a `service` or already-
  provisioned `athlete` principal (an athlete re-hitting this after
  provisioning has no reason to, and shouldn't be able to re-provision
  themselves under a different profile).
- **Request body** — the hard-data form fields plus the chat-derived
  periodization intent (see §3 for how the latter gets here):

  ```json
  {
    "name": "...",
    "dob": "1990-05-14",
    "sex": "female",
    "height_cm": 168,
    "weight_kg": 63,
    "css_pace_s_per_100m": 95.0,
    "css_test": {"distance_m": 400, "time_s": 380.0},
    "pool_schedule": ["Mon", "Wed", "Fri"],
    "target_event": {
      "name": "...", "event_date": "2027-06-01", "distance_m": 33300,
      "event_format": "single_day", "wetsuit": false, "priority": "A"
    },
    "current_volume_m": 12000,
    "peak_volume_m": 28000,
    "macro_start": "2026-08-01"
  }
  ```

  `css_pace_s_per_100m` and `css_test` are mutually exclusive; when
  `css_test` is given, the handler calls the same
  `zones.css_from_test`/CLI's `parse_time_to_s`-equivalent conversion
  `cli.py`'s `onboard` and `zones` subcommands already use (`cli.py`
  imports `css_from_test` — reused, never re-derived here).

- **Handler**:
  1. Reject if `store.get_allowed_email(principal.email).athlete_id` is
     already set (defends against a replayed/duplicate onboarding request
     racing a first successful one — belt-and-suspenders alongside the
     session-revocation in step 4).
  2. Build an `Athlete` (new UUID; slug from a slugified `name` with a
     collision check against `store.load_athlete` — retry with a short
     suffix on collision, since `provision_athlete` treats a same-slug
     different-id write as a slug collision it will NOT safely resolve for
     you, see `provision.py`'s own docstring on this).
  3. Call `provision_athlete(store, profile=athlete, events=[event] if
     target_event else [], email=principal.email, target_event=event,
     current_volume_m=..., peak_volume_m=..., macro_start=...)` —
     **unchanged, reused exactly as PR #62 built it.**
  4. On success: `store.revoke_session(hash_token(principal.token))` (the
     onboarding session is single-purpose and now done) and
     `store.create_session(athlete.slug, ..., ...)` — mint a normal
     athlete session and return it in the same `{token, athlete, name,
     role, expires_at}` shape `POST /api/auth/google`'s athlete-bound
     branch returns, so the frontend swaps tokens in place with no second
     Google sign-in.
  5. `ValueError` from `provision_athlete` (e.g. `scaffold_macro` rejects
     too-little runway before the event) → 422 with the message verbatim,
     same "propagate as real, actionable information" contract
     `provision_athlete`'s docstring already establishes
     (`provision.py:114-122`) — the frontend re-shows the target-event
     step, not a generic error.

---

## 3. Frontend onboarding wizard

Gating: `main.js` already branches on `state.identity` for the sign-in
gate (`if (state.tab === 'settings' && !state.identity)
mountGoogleSignIn()`, `main.js:229`). Add a parallel `state.onboarding`
flag, set when `exchangeGoogleToken`'s response carries `{onboarding:
true}` instead of `{athlete: ...}` (`identity.js`'s `signIn()` currently
only handles the athlete-bound shape, `identity.js:151-160` — it needs a
third outcome alongside its existing `ok:true`/`requestAccess` cases).
While `state.onboarding` is true, `main.js` renders the wizard instead of
the normal tab set — same "force into one screen until resolved" pattern
the sign-in gate already uses, just a different screen.

**Step 1 — hard-data form**: a plain form (no chat), matching
`PATCH /api/athlete`'s existing field set (`name`, `dob`, `sex`,
`height_cm`, `weight_kg`, `css_pace_s_per_100m` — same validated fields,
same pydantic `Athlete` model on the backend) plus a CSS-test-time toggle
and the target-event sub-form (mirrors `Event`'s fields,
`models.py:53-71`). Deterministic, immediately validated client-side
(same shape `PATCH /api/athlete`'s 422 already enforces server-side) —
no LLM involved, consistent with CLAUDE.md's "never hand-compute... in
chat" for anything that becomes an engine input.

**Step 2 — coach-chat-to-plan**: see §4 for the mechanism. UI-wise: a chat
panel seeded with the step-1 data as context (so the coach doesn't re-ask
for the athlete's name/CSS pace), ending in a review screen that shows the
exact `current_volume_m`/`peak_volume_m`/`macro_start` about to be sent,
with an explicit "Create my plan" confirm button that fires
`POST /api/onboarding/provision`.

On success, `main.js` treats the response exactly like a normal
`handleIdentityResolved` outcome (`main.js:243-274`) — same code path,
new token — and the wizard unmounts in favor of the ordinary tabs.

---

## 4. The coach-chat → engine bridge

This is the part with real design tension: how does a conversation turn
into `scaffold_macro`/`generate_week`'s typed arguments?

### Recommended: guided form for the numbers, chat for judgment — not chat-driven extraction, in v1

Everything that becomes a literal `provision_athlete` parameter
(`current_volume_m`, `peak_volume_m`, `macro_start`, and the target event
fields) is collected via a **structured sub-form** in step 2, not parsed
out of free text. The chat panel alongside it is read-only/informational
— the athlete can ask "what's a reasonable peak volume for a 33k swim?"
or "why do you need my current volume?" and get a real, grounded answer
(the same `/api/chat` endpoint, in a scoped no-plan-yet context, see
below) — but the chat's answers inform what the athlete *types into the
form*, they don't get parsed by the backend as the plan definition.

**Rationale**: CLAUDE.md's standing rule is "never hand-compute
zones/loads/volumes in chat," and the safety rails require weekly-volume
and long-swim ramp changes to have explicit athlete confirmation before
they take effect. A form field is unambiguous (a number, validated by the
same `Event`/`current_volume_m` types `provision_athlete` already takes);
free-text extraction risks exactly the kind of misparse this project's
evidence/citation discipline exists to prevent elsewhere (units, "around
20k a week" ambiguity, a target date parsed wrong). The review screen
before the confirm button *is* the explicit-confirmation step the safety
rails already require elsewhere (adapted here from `/adapt`'s own
"judgment review → finalize" pattern).

### Alternative (rejected for v1, real v2 candidate): coach tool-calls collect params conversationally

Mirror `propose_adaptation`'s existing pattern exactly
(`backend/app/tools.py:46-68,176-248`): add a `propose_provision` tool to
a *separate*, onboarding-scoped tool schema (never mixed into the
post-onboarding `TOOLS_SCHEMA`, since an onboarding principal has no
athlete to call `propose_adaptation`/`get_plan_summary`/etc. against in
the first place — §5 covers why those tools can't run for this
principal). The coach extracts `target_event`/`current_volume_m`/
`peak_volume_m`/`macro_start` from the conversation, calls
`propose_provision` with those as the tool's typed `input_schema` (not
free text passed to the backend — the *extraction* still happens inside
Claude's structured tool-calling, which is far more reliable than parsing
raw prose server-side), and the handler returns a **draft** (calls
`scaffold_macro`/`generate_week` read-only, same "never persist, only
propose" contract `propose_adaptation` already has, `tools.py:53-56`) for
the athlete to see and confirm — never auto-provisions on the tool call
alone.

**Tradeoff**: this is a materially better conversational UX (no
sub-form to fill in) and reuses a proven pattern (`propose_adaptation`
already ships this exact "tool extracts + drafts, explicit confirm
persists" shape). It's deferred to v2 because it's new *product* surface
(a tool that can trigger `scaffold_macro` for an athlete that doesn't
exist yet needs its own error handling for "too little runway," bad
dates, ambiguous volumes, etc. — same as `propose_adaptation`'s
`ValueError` propagation, but exercised for the first time in a context
with no prior week to fall back to) and the highest-risk moment to get
wrong is the *first* one for a brand-new user, not the best moment to
debut chat-driven extraction. Ship the deterministic form first (§8's
Slice 1), promote to this once real onboarding volume validates the
schema/endpoint plumbing.

---

## 5. Security & cost

- **Stays invite-only.** `require_onboarding_principal` only ever accepts
  a session `POST /api/auth/google` minted for an email that already
  passed the `allowed_emails` check (unchanged 403 "request access" gate,
  `routes/auth.py:73-78`) — there is no new anonymous-signup surface. The
  admin step of allowlisting an email doesn't disappear; what disappears
  is the admin hand-authoring the athlete's *profile data* after that.
- **Onboarding principal must not reach any athlete's data.** Add a
  `require_athlete_principal` dependency (403 unless `kind in
  {"service", "athlete"}`) and swap every existing athlete-scoped route
  (`/api/chat`, `/api/athlete`, `/api/workouts`, `/api/wellness`, ...) to
  depend on it instead of bare `require_auth`, so an onboarding session
  is rejected by construction — the same way `resolve_athlete` already
  guarantees one athlete session can't read another's (`auth.py:134`)
  extends to "an onboarding session can't read *any* athlete's."
- **Onboarding chat needs its own (smaller) context, not
  `build_per_request_context` reused.** That function unconditionally
  does `store.load_athlete(slug)` and reads plan/workouts/rollup data that
  don't exist yet for an unprovisioned user (`context.py:598-636`). The
  read-only Q&A chat in §4 needs a distinct, minimal context builder (no
  plan, no history, no rollup — just the library + whatever step-1 form
  data has been entered so far) — new code, explicitly not a reuse of the
  athlete-scoped assembler.
- **Daily chat cap must still apply.** `require_daily_chat_cap`
  (`auth.py:201-214`) currently no-ops for anything but `kind ==
  "athlete"` — as written, an onboarding principal's chat calls would hit
  **no cap at all**, a real gap since the Anthropic key is Andrew's shared
  key. Fix: extend the check to also apply when `kind == "onboarding"`,
  keyed by `principal.email` instead of `principal.athlete` (`
  DailyChatLimiter.check` already takes an arbitrary string key,
  `auth.py:182` — no structural change needed there, just call it with
  the email for this principal kind). The per-minute `ChatRateLimiter`
  already keys by `principal.token` (`ChatRateLimiter`'s own docstring,
  `auth.py:140-149`; called with `principal.token` from
  `backend/app/routes/chat.py:79`), which every principal kind has, so it
  needs no change.
- **Abandoned onboarding sessions.** A pending invite with no
  `SESSION_TTL_DAYS` follow-through just expires like any other session —
  no special cleanup needed; the email stays allowlisted (`athlete_id`
  still NULL) and a fresh sign-in mints a new onboarding session.

---

## 6. Phasing

- **Slice 0 — schema/plumbing (foundational, ship first).** The
  migration (§1), model changes, `invite_pending_email`, the `left join`
  fixes, `Principal.kind == "onboarding"`, and `require_athlete_principal`
  guarding every existing athlete-scoped route. No user-facing behavior
  change yet — existing admin `cli onboard` keeps working exactly as
  today; this only makes the *schema* capable of a pending invite.
- **Slice 1 — minimal self-service, form-only (the real MVP).** A new
  `cli invite-pending --email` admin command (inserts the
  `athlete_id NULL` row); `POST /api/onboarding/provision` (§2); the
  step-1 hard-data form *and* step-2 collapsed into one plain form (no
  chat at all yet — `current_volume_m`/`peak_volume_m`/`macro_start` as
  ordinary fields). This alone achieves "no admin CLI, no YAML" for
  provisioning — ship it and run Andrew's next real beta user through it
  before building any chat layer, to validate the schema change and the
  new endpoint under real usage first.
- **Slice 2 — coach chat for Q&A alongside the form.** Add the read-only
  onboarding-scoped chat context (§5) next to the still-form-driven step
  2. Improves UX, zero new engine-reuse risk (chat still never writes).
- **Slice 3 — conversational param extraction.** The `propose_provision`
  tool-calling path (§4's alternative), gated behind the same explicit
  review/confirm screen slice 1 already established. Only after slice 1
  has proven the plumbing in production.

---

## References

- `engine/swim_coach/provision.py` — `provision_athlete` (reused verbatim
  by the new endpoint).
- `backend/app/routes/auth.py`, `backend/app/auth.py` — verified identity
  (PR #59), the FK tension's read side.
- `backend/app/routes/athlete.py` — edit-only `PATCH /api/athlete`,
  contrasted with the new create path.
- `engine/swim_coach/store.py`, `store_db.py` — `StoreInterface`,
  `add_allowed_email`/`get_allowed_email` upsert/join behavior.
- `supabase/migrations/20260714000000_identity.sql` — the `NOT NULL` FK
  this proposal relaxes.
- `engine/swim_coach/models.py` — `Athlete` demographic fields (PR #19),
  `AllowedEmail`/`AuthSession`.
- `backend/app/routes/chat.py`, `backend/app/context.py`,
  `backend/app/tools.py` — the existing chat context/tool-loop patterns
  (`propose_adaptation`) this proposal's §4 alternative mirrors.
- PR #59 (Google session login), PR #62 / issue #61 (Tier C
  `provision_athlete`/`cli onboard`), PR #19 (demographic fields).
