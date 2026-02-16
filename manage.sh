#!/bin/bash
# Simple management script for muzic channelz
cd "$(dirname "$0")"

case "$1" in
  start)
    if pgrep -f "uvicorn app.main" > /dev/null; then
      echo "Server is already running (PID: $(pgrep -f 'uvicorn app.main'))"
      exit 1
    fi
    source .venv/bin/activate
    nohup uvicorn app.main:app --host 0.0.0.0 --port 8484 > /tmp/muzic-channelz.log 2>&1 &
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
