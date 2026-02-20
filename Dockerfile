# muzic channelz - Docker image (Debian-based), version 1.0
# syntax=docker/dockerfile:1
# Build frontend
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install
COPY frontend/ ./
RUN npm run build

# Runtime: Debian-based Python image
FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.title="muzic-channelz" \
      org.opencontainers.image.version="1.0" \
      org.opencontainers.image.description="Music channel streaming with Azuracast, overlay, and ErsatzTV output"

WORKDIR /app
# Use BuildKit cache mount so downloaded .deb files are reused across builds (first build still downloads once)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
# Default artist icon when no image found (used by now_playing)
COPY frontend/public/logo.png ./app/static/default-art.png
COPY --from=frontend /app/frontend/dist ./frontend/dist

ENV MUZIC_HOST=0.0.0.0
ENV MUZIC_PORT=8484
EXPOSE 8484
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8484"]
