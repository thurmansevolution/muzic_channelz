#!/bin/bash
# Simple management script for muzic channelz (run from project root)
cd "$(dirname "$0")"
if [ ! -d "app" ] || [ ! -f "requirements.txt" ]; then
    echo "Error: Run this script from the muzic_channelz project root (directory containing app/ and requirements.txt)."
    exit 1
fi
if [ ! -f ".venv/bin/activate" ]; then
    echo "Error: Virtualenv not found. Create it with: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi
if [ ! -x ".venv/bin/python" ]; then
    echo "Error: .venv/bin/python not found. Create the venv with: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements.txt"
    exit 1
fi

case "$1" in
  start)
    if pgrep -f "uvicorn app.main" > /dev/null; then
      echo "Server is already running (PID: $(pgrep -f 'uvicorn app.main'))"
      exit 1
    fi
    VENV_PYTHON="$(dirname "$0")/.venv/bin/python"
    nohup "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "${MUZIC_PORT:-8484}" > /tmp/muzic-channelz.log 2>&1 &
    sleep 2
    if pgrep -f "uvicorn app.main" > /dev/null; then
      echo "✓ Server started (PID: $(pgrep -f 'uvicorn app.main'))"
      echo "  Access at: http://localhost:8484"
      echo "  Logs: tail -f /tmp/muzic-channelz.log"
    else
      echo "✗ Failed to start server. Check logs: cat /tmp/muzic-channelz.log"
      exit 1
    fi
    ;;
  stop)
    if ! pgrep -f "uvicorn app.main" > /dev/null; then
      echo "Server is not running"
      exit 1
    fi
    pkill -f "uvicorn app.main"
    pkill -f ffmpeg  # Also stop any running FFmpeg processes
    sleep 1
    echo "✓ Server stopped"
    ;;
  restart)
    $0 stop
    sleep 2
    $0 start
    ;;
  status)
    if pgrep -f "uvicorn app.main" > /dev/null; then
      PID=$(pgrep -f 'uvicorn app.main')
      echo "✓ Server is running (PID: $PID)"
      echo "  Access at: http://localhost:8484"
      if curl -s http://localhost:8484/api/admin/state > /dev/null 2>&1; then
        echo "  Status: Responding OK"
      else
        echo "  Status: Not responding"
      fi
    else
      echo "✗ Server is not running"
    fi
    ;;
  logs)
    tail -f /tmp/muzic-channelz.log
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs}"
    exit 1
    ;;
esac
