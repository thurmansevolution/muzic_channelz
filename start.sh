#!/bin/bash
# Simple startup script for muzic channelz (run from project root)
cd "$(dirname "$0")"
if [ ! -d "app" ] || [ ! -f "requirements.txt" ]; then
    echo "Error: Run this script from the muzic_channelz project root (directory containing app/ and requirements.txt)."
    exit 1
fi
if [ ! -f ".venv/bin/activate" ]; then
    echo "Error: Virtualenv not found. Create it with: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi
exec "$(dirname "$0")/.venv/bin/python" -m uvicorn app.main:app --host 0.0.0.0 --port "${MUZIC_PORT:-8484}"
