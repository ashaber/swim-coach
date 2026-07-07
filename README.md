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

Authed endpoints require `Authorization: Bearer <API_TOKEN>`. `POST /api/chat`
body: `{"message": str, "history": [{"role","content"}], "athlete": "renee",
"expert_mode": bool}`; the response streams `data: {json}` events of type
`text` / `tool_use` / `done` / `refusal` / `error`.

```bash
TOKEN=$(grep '^API_TOKEN=' .env | cut -d= -f2-)
curl -sN -X POST http://localhost:8000/api/chat \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"message":"what should I focus on this week?","history":[],"athlete":"renee","expert_mode":false}'
```

### Deployed (GCP Cloud Run)

Live: **https://swim-coach-api-901329634103.us-central1.run.app**
(project `ashaber-open-brain`, region `us-central1`, model `claude-opus-4-8`).
Secrets live in GCP Secret Manager (never in the image): `anthropic-api-key`,
`swim-coach-api-token`. Config (`CLAUDE_MODEL`, `ALLOWED_ORIGINS`, …) is passed
as plain env vars. The image builds from `backend/Dockerfile` with the repo root
as context (`cloudbuild.yaml`).

```bash
PROJECT=ashaber-open-brain; REGION=us-central1
IMG=$REGION-docker.pkg.dev/$PROJECT/swim-coach/api:latest

# build
gcloud builds submit --config cloudbuild.yaml --substitutions=_IMAGE=$IMG --project $PROJECT .

# deploy (public URL; protected at the app layer by the bearer token + CORS + rate limit)
gcloud run deploy swim-coach-api --image $IMG --region $REGION --project $PROJECT \
  --allow-unauthenticated \
  --set-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest,API_TOKEN=swim-coach-api-token:latest \
  --set-env-vars CLAUDE_MODEL=claude-opus-4-8,ALLOWED_ORIGINS=https://ashaber.github.io,ATHLETES_DIR=/app/athletes,LIBRARY_DIR=/app/library \
  --min-instances=0 --max-instances=2
```

### Rotating a secret (Anthropic key or bearer token)

```bash
printf '%s' "<new value>" | gcloud secrets versions add anthropic-api-key --data-file=-   # or swim-coach-api-token
gcloud run services update swim-coach-api --region us-central1 \
  --update-secrets ANTHROPIC_API_KEY=anthropic-api-key:latest,API_TOKEN=swim-coach-api-token:latest
```

Update the matching value in local `.env` and the PWA Settings too — the bearer
token must match across `.env`, Secret Manager, and the caller, or requests 401.

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