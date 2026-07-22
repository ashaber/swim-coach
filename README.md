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