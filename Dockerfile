# Multi-stage: build React UI, then run FastAPI + static files.
FROM node:22-alpine AS ui
WORKDIR /ui
COPY web-ui/package.json web-ui/package-lock.json* ./
RUN npm install
COPY web-ui/ ./
# Empty base URL = same-origin /api when served by FastAPI
ENV VITE_API_BASE_URL=
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOORING_WEB_HOST=0.0.0.0 \
    MOORING_WEB_PORT=8000 \
    MOORING_CORS_ALLOW_ALL=true

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY config ./config
RUN pip install --no-cache-dir ".[web]"

COPY --from=ui /ui/dist ./web-ui/dist

# Persistent volume should mount here in production (Render disk).
RUN mkdir -p /data
ENV MOORING_DATA_DIR=/data

EXPOSE 8000
CMD ["python", "-m", "mooring_fields.web.api"]
