# syntax=docker/dockerfile:1

FROM node:24-alpine AS frontend-builder

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ROBOARM_DB_PATH=/app/data/roboarm.db \
    ROBOARM_STATIC_DIR=/app/frontend/dist

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 roboarm

COPY backend/ ./backend/
COPY --from=frontend-builder /build/frontend/dist ./frontend/dist/

RUN mkdir -p /app/data && chown -R roboarm:roboarm /app

USER roboarm
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" || exit 1

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
