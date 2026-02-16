# muzic channelz - Docker image (Debian-based), version 1.0
# Build frontend
FROM node:20-alpine AS frontend
WORKDIR /app/frontend
COPY frontend/package.json ./
RUN npm install --omit=dev
COPY frontend/ ./
RUN npm run build

# Runtime: Debian-based Python image
FROM python:3.12-slim-bookworm
LABEL org.opencontainers.image.title="muzic-channelz" \
      org.opencontainers.image.version="1.0" \
      org.opencontainers.image.description="Music channel streaming with Azuracast, overlay, and ErsatzTV output"

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY --from=frontend /app/frontend/dist ./frontend/dist

ENV MUZIC_HOST=0.0.0.0
ENV MUZIC_PORT=8484
EXPOSE 8484
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8484"]
