# backend/

FastAPI service + Cloud Run scheduled job for swim-coach. See the repo root
[`README.md`](../README.md) for local setup, the chat API, and the
`deploy-backend.yml` deploy flow for the **API service** (`swim-coach-api`).
This file covers the **intervals.icu auto-sync job** (`swim-coach-sync`) —
the piece that pulls new Garmin activities in automatically instead of
waiting for a manual `.fit` upload through the PWA.

## intervals.icu sync job (`backend/app/sync.py`)

### What it does

Garmin -> Garmin Connect -> intervals.icu (already live for any athlete with
Garmin connected there — zero setup on our end) -> this job pulls the
trailing 14 days of activities via the athlete's personal intervals.icu API
key, downloads each new one's **original** device `.fit` file, runs it
through the same enrichment a manual PWA upload gets
(`backend/app/enrich.py::enrich_draft` — raw-file copy, series sidecar,
analytics), and saves it via the normal `store.save_workout`. The PWA
history/detail views and the coach's `get_workouts` tool pick it up with no
further action — they read the same store.

Endpoints (HTTP Basic auth, username literally `API_KEY`, password = the
athlete's personal key — verified live 2026-07-12):

- `GET /api/v1/athlete/{athlete_id}/activities?oldest=...&newest=...` — list.
- `GET /api/v1/activity/{id}/file` — the **original** Garmin device `.fit`
  (has pool length frames, correct pool/open-water sub-sport, SWOLF-capable).

**Never** `GET /api/v1/activity/{id}/fit-file` — that's intervals.icu's own
lossy re-encode (manufacturer id 30051): it drops every pool length frame,
loses the pool/open-water sub-sport distinction, and drops session-level HR
fields. `IntervalsClient.download_fit` in `sync.py` only ever calls `/file`;
if you're ever tempted to "simplify" that URL, don't.

Runs stateless — every invocation re-lists the trailing window and relies on
dedupe (primarily `Workout.external_id`, e.g. `"intervals:i132013445"`; a
secondary date+sport+duration heuristic catches manual uploads of the same
session that carry no `external_id`) to make re-runs idempotent.

### One-time setup (repo owner only)

The job shares the API service's image (same `backend/Dockerfile`, command
override `python -m app.sync`) and most of its env — only
`INTERVALS_SYNC_CONFIG` is new. **Each athlete supplies their own
intervals.icu API key directly to the repo owner** (Settings -> Developer on
their own intervals.icu account) — Renee provides hers directly; it is never
written to the repo, logged, or handled by an agent session.

1. **Create the secret** (JSON array, one entry per synced athlete — see
   `.env.example`'s `INTERVALS_SYNC_CONFIG` for the documented shape):

   ```bash
   cat <<'JSON' > /tmp/intervals-sync-config.json
   [
     {"slug": "andrew", "intervals_athlete_id": "i00000001", "api_key": "REPLACE_ME"},
     {"slug": "renee",  "intervals_athlete_id": "i00000002", "api_key": "REPLACE_ME"}
   ]
   JSON
   gcloud secrets create intervals-sync-config \
     --data-file=/tmp/intervals-sync-config.json \
     --project open-swim-coach-ashaber
   rm /tmp/intervals-sync-config.json   # never leave the real keys on disk
   ```

2. **Create the Cloud Run Job** (same image/env as the API service, plus the
   new secret — see `deploy-backend.yml`'s API deploy step for the env vars
   this mirrors):

   ```bash
   gcloud run jobs create swim-coach-sync \
     --image us-central1-docker.pkg.dev/open-swim-coach-ashaber/swim-coach-repo/api:latest \
     --region us-central1 \
     --project open-swim-coach-ashaber \
     --set-env-vars=ATHLETES_DIR=/app/athletes,LIBRARY_DIR=/app/library,STORE_BACKEND=db \
     --set-secrets=ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,API_TOKEN=API_TOKEN:latest,DATABASE_URL=DATABASE_URL:latest,INTERVALS_SYNC_CONFIG=intervals-sync-config:latest \
     --command=python \
     --args=-m,app.sync
   ```

   (`ANTHROPIC_API_KEY`/`API_TOKEN` aren't actually used by `sync.py`, but
   `app.config.Settings.from_env()` — reused here for `STORE_BACKEND`/
   `DATABASE_URL` handling — still requires them at startup; mounting the
   same secrets the API service already uses is simpler than forking the
   config loader.)

   From then on, `.github/workflows/deploy-backend.yml`'s manual dispatch
   updates this job's image tag alongside the API service's on every deploy
   (`gcloud run jobs update`, best-effort — it's a no-op failure with a
   workflow warning until this one-time `create` has run).

3. **Create the Cloud Scheduler job** to invoke it every 6 hours via the
   Cloud Run Jobs `run` API, authenticated with an OIDC service account:

   ```bash
   gcloud scheduler jobs create http swim-coach-sync-trigger \
     --schedule="0 */6 * * *" \
     --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.io/v1/namespaces/open-swim-coach-ashaber/jobs/swim-coach-sync:run" \
     --http-method=POST \
     --oauth-service-account-email=github-deployer@open-swim-coach-ashaber.iam.gserviceaccount.com \
     --location=us-central1 \
     --project open-swim-coach-ashaber
   ```

### Verifying it worked

```bash
gcloud run jobs execute swim-coach-sync --wait --project open-swim-coach-ashaber --region us-central1
gcloud logging read 'resource.type=cloud_run_job AND resource.labels.job_name=swim-coach-sync' \
  --project open-swim-coach-ashaber --limit 50 --format='value(textPayload)'
```

Look for `sync.run_end` with per-athlete `listed`/`new`/`saved`/
`skipped_duplicate`/`failed` counts. Run it a second time immediately after —
`new` should drop to `0` for every athlete (dedupe idempotency).
