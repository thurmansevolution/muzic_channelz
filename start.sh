#!/bin/bash
# Simple startup script for muzic channelz
cd "$(dirname "$0")"
source .venv/bin/activate
exec uvicorn app.main:app --host 0.0.0.0 --port 8484
