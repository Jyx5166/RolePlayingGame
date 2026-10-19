FROM node:22-bookworm-slim AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/index.html frontend/styles.css frontend/tsconfig.json frontend/vite.config.ts ./
COPY frontend/scripts/sync-build.mjs ./scripts/sync-build.mjs
COPY frontend/src ./src
COPY frontend/assets ./assets
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    AI_MURDER_MYSTERY_DATA_DIR=/data \
    APP_ENV=development \
    LLM_PROVIDER=echo \
    LLM_BASE_URL=http://host.docker.internal:11434/v1

WORKDIR /app
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt \
    && groupadd --system --gid 10001 jujing \
    && useradd --system --uid 10001 --gid jujing --no-create-home jujing \
    && mkdir -p /data \
    && chown jujing:jujing /data

COPY backend/app ./backend/app
COPY backend/resources ./backend/resources
COPY backend/config/workflow.yaml ./backend/config/workflow.yaml
COPY --from=frontend-build /build/frontend/index.html /build/frontend/app.js /build/frontend/app.css /build/frontend/styles.css ./frontend/
COPY --from=frontend-build /build/frontend/assets ./frontend/assets

USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]
CMD ["python", "-m", "uvicorn", "main:app", "--app-dir", "backend/app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
