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
# Install runtime dependencies. Avoid BuildKit-only --mount cache so this
# Dockerfile works with both classic docker-compose and BuildKit builds.
# Intel/AMD VAAPI: ffmpeg uses libva; we need the driver so libva can open /dev/dri/renderD*.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    shared-mime-info \
    libva-drm2 \
    intel-media-va-driver \
    i965-va-driver \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
# Default artist icon when no image found (used by now_playing)
COPY frontend/public/logo.png ./app/static/default-art.png
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Default to i965 VAAPI driver: supports H.264 encoding on the widest range of Intel GPUs.
# Override via docker-compose env LIBVA_DRIVER_NAME=iHD for newer Intel (Gen9+) if needed.
ENV LIBVA_DRIVER_NAME=i965
ENV MUZIC_HOST=0.0.0.0
ENV MUZIC_PORT=8484
EXPOSE 8484
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8484"]
