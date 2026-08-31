# swim-coach

AI coaching system + PWA for ultra-distance open-water swimmers — built and
deployed. A deterministic Python engine (`engine/swim_coach/`) owns all plan
math (zones, load, progression, adaptation), each constant cited to a
`library/` research file. A FastAPI backend on GCP Cloud Run wraps the engine
and a Claude-powered coach chat, reading/writing athlete data through a
swappable store (local YAML tree, or Supabase/Postgres in prod). A PWA on
GitHub Pages talks to that backend with per-athlete Google sign-in. See
`ROADMAP.md` for the full plan and current status, and `CLAUDE.md` for
standing rules.

**Privacy note:** ingested `.fit`/`.tcx` device files are committed to this
repo verbatim under `athletes/<slug>/logs/files/` (policy as of the .fit
workout-analytics feature — see `.gitignore`). These raw files may contain
precise GPS coordinates for open-water/outdoor sessions; uploading one means
accepting that data is visible in the repo history to Andrew and any Claude
agent working in it, not just the derived workout summary.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e "engine/[dev]"
```

## Running tests

```bash
pytest tests/unit -v
```

No LLM calls and no network access happen in the test suite.




## Backend (Phase 2) — coach chat API

FastAPI service in `backend/` that serves the plan and the AI coach chat (the
coach can call the deterministic `/adapt` engine as a tool). Reuses the engine.

### Run locally

```bash
cp .env.example .env          # then fill in ANTHROPIC_API_KEY and API_TOKEN
.venv/bin/pip install -e engine -r backend/requirements.txt   # once
cd backend
../.venv/bin/uvicorn app.main:app --reload --port 8000
```

`.env` is auto-loaded (python-dotenv) and gitignored — never commit it. The app
fails fast if `ANTHROPIC_API_KEY` or `API_TOKEN` is missing. (It only checks the
key is *present* at startup; an invalid key surfaces on the first `/api/chat`.)

### Endpoints

Every authed endpoint takes the same `Authorization: Bearer <token>` header.
Two credential kinds resolve through it (`backend/app/auth.py`): a **session
token** minted by `POST /api/auth/google` (what the PWA and every real
athlete uses — bound to exactly one athlete, `?athlete=`/body `athlete`
mismatches 403) or the legacy shared `API_TOKEN` (a **service** credential —
CLI/scripts/sync job — may act as any athlete via `?athlete=`, default
`renee`).

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /health` | none | `{"status":"ok"}` |
| `POST /api/auth/google` | none | body `{"id_token"}` — verifies a Google ID token server-side, 403 `{"error":"request access"}` if the email isn't allowlisted, else mints a session: `{"token","athlete","name","role","expires_at"}` |
| `GET /api/me` | bearer (session) | resolves the caller's own identity from the token |
| `POST /api/auth/logout` | bearer | revokes the calling session |
| `GET /api/plan?athlete=renee` | bearer | exported plan JSON |
| `GET /api/athlete?athlete=renee` | bearer | the athlete's own profile |
| `PATCH /api/athlete?athlete=renee` | bearer | edits profile fields; `zones` is always server-derived from `css_pace_s_per_100m` via the engine's `zone_table()`, never accepted from the client |
| `POST /api/chat` | bearer | streamed (SSE) coach reply; rate-limited per session/minute and per athlete/day |
| `POST /api/workouts?athlete=renee` | bearer | logs a completed workout; body matches `Workout` minus server-assigned fields |
| `GET /api/workouts?athlete=renee` | bearer | lists logged workouts, newest-last |
| `POST /api/workouts/sync?athlete=renee` | bearer | on-demand intervals.icu pull for this athlete (409 if sync isn't configured for them) |
| `POST /api/workouts/ingest?athlete=renee` | bearer | multipart `.fit`/`.tcx`/`.csv` upload, parsed in memory into a draft (not saved until the caller `POST`s it via `/api/workouts`) |
| `POST /api/wellness?athlete=renee` | bearer | logs a daily check-in; body matches `Wellness` minus server-assigned fields |
| `GET /api/wellness?athlete=renee` | bearer | lists logged check-ins, newest-last |
| `POST /api/feedback?athlete=renee` | bearer | athlete-submitted feature request / comment / bug report |
| `GET /api/feedback?athlete=renee` | bearer | the durable feedback log, newest-first, including the coach's own auto-logged research questions |
| `PATCH /api/feedback/{id}` | bearer | marks a feedback/research-question entry resolved |

`POST /api/chat` body: `{"message": str, "history": [{"role","content"}],
"athlete": "renee", "expert_mode": bool, "workout_id": str | null}`; the
response streams `data: {json}` events of type `text` / `tool_use` / `done` /
`refusal` / `error`.

The write endpoints assign `id`/`athlete_id`/`schema_version` server-side,
validate the body by constructing the pydantic model (422 `{"error": ...}`
on failure), and persist via `make_store(settings)` — the same
`FileStore`/`DbStore` seam `GET /api/plan` reads through. In production
(`STORE_BACKEND=db`) a logged workout or check-in reaches the live coach
immediately, with no redeploy.

```bash
# Service-token smoke test (curl doesn't have a Google account -- this is
# the legacy shared API_TOKEN credential, fine for local/CI, not what real
# athletes authenticate with):
TOKEN=$(grep '^API_TOKEN=' .env | cut -d= -f2-)
curl -sN -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"what should I focus on this week?","history":[],"athlete":"renee","expert_mode":false}'
```

### Deploying the backend (GCP Cloud Run)

Live: **https://swim-coach-api-445273334913.us-central1.run.app** — service
`swim-coach-api` in GCP project **`open-swim-coach-ashaber`** (project number
445273334913), region `us-central1`.

**A stale duplicate `swim-coach-api` service also lives in the
`ashaber-open-brain` project** (no `DATABASE_URL`, different env vars) — it
predates the move to `open-swim-coach-ashaber` and `gcloud config` may still
default to it. Never deploy there. Always pass `--project open-swim-coach-ashaber`
explicitly, or check `gcloud config get-value project` first.

Deploys do **not** happen automatically on merge — `.github/workflows/deploy-backend.yml`
("Deploy backend") is `workflow_dispatch`-only, on purpose (it swaps
production traffic):

```bash
git checkout main && git pull
gh workflow run deploy-backend.yml --ref main
gh run watch <run-id>          # run-id from the previous command, or `gh run list --workflow=deploy-backend.yml`

# verify
curl -s https://swim-coach-api-445273334913.us-central1.run.app/health
gcloud run services describe swim-coach-api \
  --project open-swim-coach-ashaber --region us-central1 \
  --format='value(status.latestReadyRevisionName,spec.template.spec.containers[0].image)'
# confirm the image's sha tag matches `git rev-parse HEAD` on main
```

Auth: GitHub Actions authenticates via Workload Identity Federation (pool
`github-pool`, service account
`github-deployer@open-swim-coach-ashaber.iam.gserviceaccount.com`) using repo
secrets `GCP_PROJECT_ID` / `GCP_SERVICE_ACCOUNT` / `GCP_WORKLOAD_IDENTITY_PROVIDER`.
Runtime secrets (`ANTHROPIC_API_KEY`, `API_TOKEN`, `DATABASE_URL`) live in
Secret Manager in `open-swim-coach-ashaber` and are mounted by the workflow —
never in `.env` in prod, never baked into the image.

**Two separate deploy pipelines — don't confuse them:**

| Workflow | Trigger | Deploys |
|---|---|---|
| `deploy.yml` ("Deploy") | automatic, on push to `main` touching `web/`, `athletes/`, `library/`, … | GitHub Pages **frontend** |
| `deploy-backend.yml` ("Deploy backend") | manual (`workflow_dispatch`) only | Cloud Run **backend** |

A green "Deploy" check on `main` means the frontend shipped — it says
nothing about the backend. Run `deploy-backend.yml` explicitly whenever
backend or engine code needs to reach production (the image also bakes in
`library/`, so a library-only change needs a backend redeploy too before the
live chat coach sees it — see "Publishing a reviewed library file" below).

### Rotating a secret (Anthropic key, bearer token, or DB URL)

```bash
printf '%s' "<new value>" | gcloud secrets versions add ANTHROPIC_API_KEY \
  --data-file=- --project open-swim-coach-ashaber   # or API_TOKEN / DATABASE_URL
```

Then redeploy (`gh workflow run deploy-backend.yml --ref main`) so the new
revision mounts the updated secret version — Cloud Run doesn't hot-reload
secrets on an already-running revision. Update the matching value in local
`.env` and the PWA Settings too — the bearer token must match across `.env`,
Secret Manager, and the caller, or requests 401.

## Storage backend (Phase 2.5) — FileStore ⇄ DbStore

The backend reads/writes athlete data through a swappable store
(`StoreInterface` in `engine/swim_coach/store.py`). Two implementations:

| Backend | Class | Selected by |
|---|---|---|
| YAML tree (default) | `FileStore` | `STORE_BACKEND=file` (or unset) |
| Supabase/Postgres | `DbStore` (`store_db.py`) | `STORE_BACKEND=db` + `DATABASE_URL` |

The store factory `backend/app/store_factory.py::make_store(settings)` picks one;
every route goes through it. **`file` is the default (local dev/CI unless you set
`STORE_BACKEND=db`); the deployed backend runs `STORE_BACKEND=db`** (see
`deploy-backend.yml`) — production reads/writes Supabase, not the repo's
`athletes/` tree. `DbStore` imports `psycopg` lazily (optional extra
`pip install -e "engine/[db]"`), so the engine core and CLI run without it.

Schema, RLS-deferred note, and migration commands live in
[`supabase/README.md`](supabase/README.md). **RLS is intentionally deferred** to
Phase 3 (service-role access only from the backend for now).

### Cutover (file → DB) — already done in prod; here's how a schema change ships

The one-time cutover already happened (`STORE_BACKEND=db` has been live since
before the auth/provisioning work landed); this is the process for adding a
new migration, and the rollback path if a DB change goes wrong:

1. **Apply the new migration** against the **direct** (port 5432) connection:
   `psql "<direct-5432-url>" -f supabase/migrations/<new file>.sql`. Migrations
   are applied **manually** — the `db` CI job only validates a migration
   (applies it twice, for idempotency, against a throwaway Postgres) and runs
   the `DbStore` contract suite; it never touches the real Supabase instance.
2. **Redeploy the backend** (`gh workflow run deploy-backend.yml --ref main`)
   if the schema change is paired with code that depends on it.
3. **Rollback** at any time by setting `STORE_BACKEND=file` on the backend and
   redeploying — falls back to the repo's `athletes/` tree. (One-way in
   practice once real athletes are writing to the DB day-to-day: anything
   written to Postgres after the cutover isn't in the file tree.)

`DATABASE_URL` (the backend's runtime connection) uses the **transaction
pooler** (pgbouncer, port 6543); `DbStore` disables prepared statements
(`prepare_threshold=None`) so it works against it. Migrations/DDL always run
against the **direct** connection (port 5432) instead — see
`scripts/migrate_files_to_db.py` for the (now-historical) one-shot file→DB
migration script, still useful as a reference for the FK-safe write order.

### DB contract tests (gated)

`tests/integration/test_store_db_contract.py` runs the same store-contract suite
against a real `DbStore`; it is **skipped** unless `SWIM_COACH_TEST_DB_URL`
points at a throwaway schema. `pytest tests/unit -v` never needs a DB or network.
See `supabase/README.md` for how to run it.

## Onboarding a new athlete

Invite-only. Adding an athlete is a data operation against the prod DB, not a
deploy — `python -m swim_coach.cli onboard` (issue #61 "Tier C") provisions
profile + zones + macro scaffold + first week + allowlist entry in one
idempotent command, reusing `engine/swim_coach/provision.py::provision_athlete`
(the same function a future in-app onboarding route will call — see
`docs/design-self-service-onboarding.md` / PR #63 for that design).

**Honest caveat first:** `cli onboard` still requires `--profile <path>`, a
locally-authored, uncommitted `profile.yaml` (athlete-tree format: `slug`,
`name`, `css_pace_s_per_100m` or a CSS test, pool schedule, etc.). It removed
the *old* two steps — committing that file to the repo, and running
`scripts/migrate_files_to_db.py` afterward — but it is **not** file-free:
someone still has to hand-author a YAML file locally before running the
command. Fully file-free onboarding (fields as CLI flags, or the in-app
self-service wizard from PR #63) is a roadmap item, not built yet — see
`ROADMAP.md`.

```bash
# profile.yaml and (optionally) events.yaml are LOCAL and UNCOMMITTED --
# author them by hand, don't add them to git.
python -m swim_coach.cli onboard \
  --profile /tmp/new-athlete-profile.yaml \
  --events /tmp/new-athlete-events.yaml --event "Event Name" \
  --current-volume 15000 \
  --email their-google-account@gmail.com \
  --database-url "<prod direct-5432 DSN>"        # or export DATABASE_URL
```

`--events`/`--event`/`--current-volume`/`--peak-volume`/`--start` are all
optional — omit them (or a CSS pace/test) and `provision_athlete` still
creates the athlete + zones + allowlist entry, just skipping the macro
scaffold and first week (reported in the command's `skipped` field). Re-running
the same command is safe: every write is an upsert keyed on the profile's
`slug`/`id`, so it updates rather than duplicates.

Once provisioned, the athlete signs in at the PWA
(https://ashaber.github.io/swim-coach/) with the Google account named in
`--email` — no token, no separate account creation step; `POST
/api/auth/google` finds their `allowed_emails` row and mints their session.

To grant access to an athlete who **already exists** in the DB (e.g. a second
Google account for the same person), skip `onboard` and use the lighter
`invite` instead: `python -m swim_coach.cli invite <email> --athlete <slug>
--database-url <prod DSN>` (also `list-invites` / `revoke-invite`).

## Research library (`library/`)

Grounds engine constants and the `/coach` skill. See `library/00-conventions.md`
for the evidence-tag scheme and `library/INDEX.md` for the file index and
topic-routing table. Every claim resolves to `library/reference_list.md` —
the **only** citable source list (cite by title + author + year, never a
URL or PubMed/PMC ID — earlier Gemini-assisted research fabricated those).

### Adding research to a topic file

The pipeline used for `library/07-strength-dryland.md` and
`library/10-recovery-hrv.md`:

1. Research pass produces a **verified dossier**: every candidate source
   confirmed to exist by title/author web search, with citation (title +
   author + year + journal), verification basis, a proposed ✓/~/⚠ marker, an
   honest 2-4 sentence summary, and a proposed evidence tag. Commit it under
   `library/research-dossiers/` — provenance, not a citable source itself.
2. Add the verified sources to `library/reference_list.md`, matching its
   existing grouping and style.
3. Author or extend the topic file (`library/NN-topic.md`, ≤ ~2,500 words):
   every claim tagged `[EVIDENCE: swim-ultra|swim]` or
   `[ADAPTED: cycling|running|tri|general-endurance]` (the latter always with
   `Confidence:` and `Test:` lines), or `Coach judgment:`. Mark new/changed
   content **`UNREVIEWED`**. If it grounds an engine constant, the constant's
   code comment and the topic file must cite each other.
4. Update `library/INDEX.md` — the file's summary row, any routing-table
   entries, and "Known gaps".
5. Ship via feature branch + PR — library changes never go straight to
   `main`, even research-only ones.

### Publishing a reviewed library file

Once a human has reviewed an `UNREVIEWED` topic file (e.g. `10-recovery-hrv.md`):

1. Read it critically — fix or delete anything wrong (that's part of review),
   and spot-check citations against `reference_list.md`.
2. Delete the `UNREVIEWED` marker line(s).
3. Still goes via branch + PR (the PR is the review sign-off record, even for
   a one-line marker removal):
   ```bash
   git checkout -b library/review-<NN>
   git commit -am "mark library/<NN> reviewed"
   git push -u origin library/review-<NN>
   gh pr create
   ```
4. After merge, `/coach` and the other skills may treat the file as settled
   grounding truth immediately — the repo-side skills read `library/` live.
   The **deployed backend does not**: its image bakes `library/` in at
   `/app/library` at build time, so the live chat coach only sees the
   reviewed text after a backend redeploy (see "Deploying the backend"
   above). A library-only merge needs no redeploy for anything except that.

## Training-load methodology (load, wellness, RPE)

How this system measures training stress and recovery, and how confident to
be in each piece. Full citations and constants live in
`library/03-periodization.md`'s "Load monitoring" section — this is a
map of that territory, not a replacement for it.

### What's measured today

Every load number below — actual or planned, whichever tier produced it —
is in **AU** (arbitrary units): a nominal, project-internal scale, not a
physical unit with external meaning. It's what the PWA's "Load (AU)"
stats/chips (workout rows, workout detail, coach roster) and the Plan tab's
"Target load (AU)" tile both display — same unit name everywhere it
surfaces, not a different label per screen. See
`library/15-tiered-session-load.md`'s "Unit: AU" section.

- **Tiered session load** (`load.session_load`) — a workout's real training
  load doesn't depend on whether the athlete bothered to survey it, so this
  falls through four tiers of decreasing fidelity, the last always
  returning a number (never `None`, never silently excluding a workout
  from the day's total):
  1. **sRPE** (`duration_min × RPE`) — Foster's method, the base unit
     everything else is built from when a survey exists. Specifically
     validated in swimmers (real correlation coefficients against TRIMP,
     not just assumed to transfer from other sports). The in-app survey is
     the actual published **Foster CR-10 modified Borg scale — 0 to 10, not
     the old bare 1-10 slider** (`library/19-srpe-protocol.md`): 0 ("Rest /
     Nothing at all") is now a legitimate response — an easy recovery
     session or technique day has somewhere to report itself at the bottom
     of the scale, rather than an unreachable floor. Ratings 6/8/9 are
     deliberately left unanchored in Foster's own published instrument
     (still selectable, just with no verbal label), and the app renders
     them as a blank/em-dash rather than inventing anchor text Foster never
     validated. The app also asks the question roughly 30 minutes after a
     workout's estimated end time (a recency-bias-avoidance convention, not
     itself a separately-cited claim) and nudges the athlete in-app (a row
     chip, not a push notification) if it's still unanswered by then.
  2. **HR-based TRIMP** (Banister heart-rate-reserve training impulse) —
     used when `avg_hr` plus a derivable `hr_max`/`hr_rest` are available;
     sex-specific exponential weighting (0.64·e^(1.92x) men, 0.86·e^(1.67x)
     women — many popular calculators wrongly apply the male coefficient to
     both sexes). `hr_max` is estimated from the athlete's own observed
     history; `hr_rest` from a short rolling average of logged readings,
     falling back to a documented 60bpm default in the load-*under*-
     estimating direction when no reading exists at all.
  3. **Swim pace-based intensity** (a TSS-family formula) — used for swims
     when tier 2 isn't available but both the workout's pace and the
     athlete's CSS are known: `duration_hours × IF³ × 100`, where `IF =
     css_pace / avg_pace`. Cubes the intensity factor rather than squaring
     it (the cycling-TSS convention), per TrainingPeaks' own swim-specific
     documentation — water resistance scales with speed faster than air.
  4. **Duration-only fallback** — `duration_min × 5` (the 1-10 "somewhat
     hard" midpoint), unconditional, last resort only.

  This closed a real bug found in production: 62 of Renee's 63 real logged
  workouts (synced from her watch, no subjective survey attached) had no
  RPE and were being silently excluded from every downstream load signal.
  RPE now adds *fidelity* on top of a real objective load — it never gates
  whether one exists. Known limitation: the tiers aren't on one numeric
  scale (a TRIMP-scored session typically reads as a third to a half of
  what the same effort would score via sRPE) — `daily_loads` sums whatever
  tier each workout resolves to anyway, since a real lower-fidelity number
  still beats a silently excluded one, but this under-represents
  HR/pace-scored sessions relative to sRPE-scored ones on a mixed day. See
  `library/15-tiered-session-load.md` for full citations and the
  hr_max/hr_rest derivation reasoning.
- **ACWR** (`load.acute_chronic_ratio`, 7-day acute : 28-day chronic) — the
  simple rolling-window load-spike signal already driving parts of `/adapt`.
- **CTL / ATL / TSB** (`load.ctl_atl_tsb_series`) — the Banister
  impulse-response model: exponentially-weighted "fitness" (CTL), "fatigue"
  (ATL), and "form" (TSB = CTL − ATL). Read-only monitoring, surfaced via
  `get_plan_summary` and a Plan-tab/coach-roster chart — deliberately not
  wired into `plan.py`'s taper/periodization math.
- **Wellness composite** (`load.wellness_composite`) — a Hooper &
  Mackinnon-style daily check-in (sleep, stress, soreness, motivation),
  already feeding `/adapt`'s judgment review.
- **RHR/HRV baseline deviation** (`load.wellness_baseline_deviation`) — a
  rolling acute-vs-chronic deviation for resting heart rate and
  HRV, added as an independent, physiologically-measured cross-check against
  the sRPE-derived CTL/ATL/TSB trend — kept as its own field, never blended
  into one number, since it's corroboration, not a replacement.
- **Projected/target load** (`load.session_target_load_au`) — a *planned*
  session has no RPE (nobody has done it yet), so this derives a projected
  load from the session's `intensity.zone` instead: `duration_min ×
  ZONE_ASSUMED_RPE[zone]`, a Coach-judgment Z1–Z5 → assumed-CR-10-RPE
  mapping (not an `[EVIDENCE]`/`[ADAPTED]` citation — no source calibrates
  "what RPE does a Z3 swim feel like"), falling back to the same flat
  duration-only constant tier 4 above uses when a session has no recognized
  zone. Computed **on the fly at read time, with no persisted field and no
  migration** — `scripts/export_plan_json.py` attaches it to every session
  in the exported plan, so every already-active plan gets it for free on
  its next `GET /api/plan`/`GET /api/coach/athletes/{slug}/plan` fetch (the
  Plan tab's "Target load (AU)" tile). This is the *planned* half of a
  planned-vs-actual comparison — `load.session_load` above (tiered, from
  what actually happened, surfaced as the "Load (AU)" stat/chip next to a
  reliability label: "from RPE"/"from HR"/"from pace"/"estimated") is the
  *actual* half. They're deliberately never conflated into one number.
- **Validating the model against reality**
  (`python -m swim_coach.cli validate-load-model --athlete <slug>`) — the
  honest answer to "how do we know any of this tracks reality." Matches
  every logged workout to a planned session
  (`quality.match_workout_to_session`) and compares projected vs. actual
  load for each match (`quality.workout_quality`'s `load_delta_pct`),
  printing one JSON object: `{"athlete", "scanned", "matched",
  "mean_delta_pct", "median_delta_pct", "pct_within_20pct_band"}` —
  `scanned` is every logged workout regardless of match, `matched` is how
  many found a planned session at all, and the three stats are computed
  only over workouts that both matched and produced a real
  `load_delta_pct` (`None`, never a fabricated 0 or 100, when that set is
  empty). The ±20% "close enough" band is itself a documented Coach
  judgment, not a citation — deliberately generous given
  `ZONE_ASSUMED_RPE`'s own provisional footing. **Read-only and diagnostic
  only** — like `wellness_baseline_signal`'s "visible, not gating, until
  proven" precedent, this is never wired into `adapt_week`; it exists to
  let a human see whether the projected-load model is worth trusting more,
  not to act on its own.

Every one of these follows the same design rule: **multiple independent
signals, not one master number.** A single "readiness score" would hide
exactly the disagreements (self-report vs. physiological measurement, or
fitness eroding vs. fatigue clearing) that are the actual coaching signal.

### Research gaps (honest, current as of this writing)

- **sRPE's validity is well-supported; its reliability is more mixed.**
  Swim-specific correlation with TRIMP is real, but session-RPE's
  consistency (ICC) has been reported anywhere from ~0.55 to ~0.95
  depending on sport/protocol, and no swim-specific *reliability* study was
  found — only the swim-specific *validity* one. Validity and reliability
  are different properties; don't conflate them.
- **CTL/ATL time constants are borrowed from cycling, unverified for
  swimming.** A swim-specific data point exists (elite swimmers training
  45-50 km/week showing a ~19-day fatigue time constant, vs. the 7-day
  cycling convention used here) but only via a secondary summary, not the
  primary source — see `library/03-periodization.md`'s citation-debt entry.
- **No validated adjustment found for sex, age, or cross-modal (e.g.
  strength/cross-training vs. swim) load weighting.** Sex differences in
  recovery are contested and inconsistent in the literature. Age-related
  recovery decline is less settled than commonly assumed — much of it may
  be a detraining confound, not age itself, in an athlete who stays
  systematically trained. Multi-modal weighting has no validated scheme;
  sRPE's cross-modal-agnostic design is the accepted simple answer, not a
  gap to patch. None of these get a fabricated correction factor — an
  athlete's own measured trajectory is the real individualization
  mechanism.
- **Taper duration literature is genuinely split, not just under-cited.**
  A cross-sport meta-analysis (Bosquet et al. 2007) finds ~2 weeks optimal;
  a swim-specific individualized model study (Thomas, Mujika & Busso 2008)
  finds 33±16 days — closer to a month. There is no single correct
  constant to substitute for the current provisional one; the real
  individual optimum varies enormously, which is the actual argument for
  building the CTL/ATL/TSB model rather than picking a different fixed
  number.
- **The race-day TSB reference band (+5 to +25) is a cycling-coaching
  convention** (TrainingPeaks/Joe Friel), not swim-specific or
  peer-reviewed, and the source itself notes individual variation up to 15
  points between athletes. Rendered as a loose reference, never a target.

### Roadmap

**Shipped since this section was first written:** the CTL/ATL/TSB chart
(Plan tab + coach roster view) and the RHR/HRV baseline-deviation
cross-check alongside it; the tiered session-load fallback described
above; a distinct Race-phase/week (carb-loading's real 36-72-hour window,
honestly-caveated bodywork timing, race-specific logistics) layered onto
the final taper week.

- Resolve the CTL/ATL time-constant citation debt once the Thomas, Mujika &
  Busso (2008) primary text is accessible (currently paywalled).
- An athlete effort/wellness survey that compares *prescribed* relative
  intensity against *reported* effort — the concrete mechanism this system
  is missing to ever resolve `quality.py`'s `intensity_match` field out of
  its permanent `"unknown"` state.
- The taper-duration/individualization algorithm itself: using an
  athlete's own CTL/ATL/TSB trajectory (once trusted) to size and time a
  taper, rather than any fixed duration — cross-checked against the
  athlete's own subjective effort/wellness reports, not either signal
  alone.
- A way to mark a life event (illness, travel, other disruption) and have
  the plan adapt around it — e.g. treating a travel week like a recovery
  week and re-ramping the weeks after it — rather than only ever adjusting
  one session at a time.