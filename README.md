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