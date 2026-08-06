# Single-origin deploy (docs/SINGLE_ORIGIN_DEPLOY.md): this image builds both
# Next.js frontends to static exports, then bakes them into the same image
# uvicorn runs from - one process, one port, serves the UI + API. Build
# context is the REPO ROOT (see docker-compose.yml's build.context), not
# ai-search-engine/, so both frontend directories are visible here.

FROM node:20-slim AS frontend-build
WORKDIR /build
COPY admin-portal ./admin-portal
COPY bot-ui ./bot-ui
# --legacy-peer-deps: @dotlottie/react-player@1.6.19's peerDependencies only
# list React 16-18, but this project is on React 19 - npm ci validates peer
# deps strictly and errors (ERESOLVE) on this in a clean environment, even
# though it's the exact dependency set already in package-lock.json (this
# only relaxes peer-dep validation, it does not change which versions get
# installed - npm ci is still deterministic from the lockfile).
RUN cd admin-portal && npm ci --legacy-peer-deps && npm run build
RUN cd bot-ui && npm ci --legacy-peer-deps && npm run build

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1

# System deps for PyMuPDF etc.
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential tesseract-ocr && rm -rf /var/lib/apt/lists/*

COPY ai-search-engine/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ai-search-engine/app ./app
COPY ai-search-engine/config ./config
COPY ai-search-engine/scripts ./scripts

# Matches Settings.admin_static_dir / root_static_dir (app/core/config.py).
COPY --from=frontend-build /build/admin-portal/out ./app/static/admin
COPY --from=frontend-build /build/bot-ui/out ./app/static/root

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
