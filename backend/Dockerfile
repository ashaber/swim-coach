# Cloud Run image for the swim-coach chat backend.
#
# Layout inside the image mirrors the repo layout so relative-path config
# defaults (ATHLETES_DIR=../athletes, LIBRARY_DIR=../library, and
# app/routes/plan.py's sys.path lookup of ../../../scripts) resolve the
# same way in Docker as they do when running `uvicorn app.main:app` from
# `backend/` locally:
#
#   /app/backend/...   (this package, WORKDIR)
#   /app/athletes/...   (read-only athlete data)
#   /app/library/...    (read-only research library)
#   /app/scripts/...    (export_plan_json.py, reused by routes/plan.py)
#   /engine/            (pip installed as a package, not imported by path)

FROM python:3.12-slim

# Non-root user per Andrew's global container standard.
RUN addgroup --system app && adduser --system --ingroup app app

WORKDIR /app

# Engine: installed as a package (not a sibling import path) so
# `import swim_coach` resolves the same way it does in local dev
# (`pip install -e engine/`).
COPY engine/ /engine
RUN pip install --no-cache-dir /engine

COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

COPY backend/app /app/backend/app
COPY scripts/export_plan_json.py /app/scripts/export_plan_json.py
COPY library/ /app/library
COPY athletes/ /app/athletes

RUN chown -R app:app /app
USER app

WORKDIR /app/backend

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
