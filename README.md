# swim-coach

AI coaching system + PWA for ultra-distance open-water swimmers. Phase 1 is a
deterministic Python engine (`engine/swim_coach/`) that owns all plan math —
zones, load, progression, adaptation — validated against typed YAML athlete
data. See `ROADMAP.md` for the full plan and `CLAUDE.md` for standing rules.

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

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /health` | none | `{"status":"ok"}` |
| `GET /api/plan?athlete=renee` | bearer | exported plan JSON |
| `POST /api/chat` | bearer | streamed (SSE) coach reply |
| `POST /api/workouts?athlete=renee` | bearer | logs a completed workout; body matches `Workout` (date, sport, distance_m, duration_min, rpe, notes, …) minus server-assigned fields; returns the created object |
| `GET /api/workouts?athlete=renee` | bearer | lists logged workouts, newest-last |
| `POST /api/wellness?athlete=renee` | bearer | logs a daily check-in; body matches `Wellness` (date, sleep_quality, sleep_hours, stress, soreness, motivation, resting_hr, hrv, notes) minus server-assigned fields; returns the created object |
| `GET /api/wellness?athlete=renee` | bearer | lists logged check-ins, newest-last |

Authed endpoints require `Authorization: Bearer <API_TOKEN>`. `POST /api/chat`
body: `{"message": str, "history": [{"role","content"}], "athlete": "renee",
"expert_mode": bool}`; the response streams `data: {json}` events of type
`text` / `tool_use` / `done` / `refusal` / `error`.

The four workout/wellness endpoints assign `id`/`athlete_id`/`schema_version`
server-side, validate the body by constructing the pydantic model (422
`{"error": ...}` on failure), and persist via `make_store(settings)` — the
same `FileStore`/`DbStore` seam `GET /api/plan` reads through. In production
(`STORE_BACKEND=db`) a logged workout or check-in reaches the live coach
immediately, with no redeploy.

```bash
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
every route goes through it. **The default is `file`, so the live backend is
unchanged** — the DB layer is fully dormant until the flag is flipped. `DbStore`
imports `psycopg` lazily (optional extra `pip install -e "engine/[db]"`), so the
engine core and CLI run without it.

Schema, RLS-deferred note, and migration commands live in
[`supabase/README.md`](supabase/README.md). **RLS is intentionally deferred** to
Phase 3 (service-role access only from the backend for now).

### Cutover (file → DB), done during low usage — rollback is instant

1. **Build** the DB layer (this phase) — additive, nothing deployed.
2. **Provision Supabase**, then apply the schema:
   `psql "<direct-5432-url>" -f supabase/migrations/20260706000000_init.sql`.
3. **Migrate** the current file tree in (idempotent, never deletes files):
   `python scripts/migrate_files_to_db.py --dry-run` then
   `DATABASE_URL=<pooler-6543-url> python scripts/migrate_files_to_db.py`.
4. **Shadow-verify**: with the file tree still authoritative, compare
   `DbStore` reads against `FileStore` reads for the same athlete until they
   agree.
5. **Flip** `STORE_BACKEND=db` (+ `DATABASE_URL`) on the backend (Cloud Run env
   var / Secret Manager) and redeploy. Now logged workouts and check-ins reach
   the live coach with no rebuild.
6. **Rollback** at any time by setting `STORE_BACKEND=file` again — the file
   tree stays the source of truth / archive until the DB is validated.

`DATABASE_URL` uses the **transaction pooler** (pgbouncer, port 6543); `DbStore`
disables prepared statements (`prepare_threshold=None`) so it works against it.
Run migrations/DDL against the **direct** connection (port 5432).

### DB contract tests (gated)

`tests/integration/test_store_db_contract.py` runs the same store-contract suite
against a real `DbStore`; it is **skipped** unless `SWIM_COACH_TEST_DB_URL`
points at a throwaway schema. `pytest tests/unit -v` never needs a DB or network.
See `supabase/README.md` for how to run it.

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