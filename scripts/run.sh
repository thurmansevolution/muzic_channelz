#!/usr/bin/env bash
# Run muzic channelz (production)
set -e
cd "$(dirname "$0")/.."
export MUZIC_PORT="${MUZIC_PORT:-8484}"
exec uvicorn app.main:app --host 0.0.0.0 --port "$MUZIC_PORT"
