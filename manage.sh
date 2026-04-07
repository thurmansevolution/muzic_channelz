#!/bin/bash
# Simple management script for muzic channelz (run from project root)
cd "$(dirname "$0")"

# Return PIDs of uvicorn app.main processes running on the HOST (not inside Docker containers)
_host_pids() {
  pgrep -f "uvicorn app.main" 2>/dev/null | while read -r pid; do
    cgroup=$(cat /proc/"$pid"/cgroup 2>/dev/null || true)
    if ! echo "$cgroup" | grep -q "docker"; then
      echo "$pid"
    fi
  done
}
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
    if [ -n "$(_host_pids)" ]; then
      echo "Server is already running (PID: $(_host_pids | tr '\n' ' '))"
      exit 1
    fi
    VENV_PYTHON="$(dirname "$0")/.venv/bin/python"
    nohup "$VENV_PYTHON" -m uvicorn app.main:app --host 0.0.0.0 --port "${MUZIC_PORT:-8484}" > /tmp/muzic-channelz.log 2>&1 &
    sleep 2
    if [ -n "$(_host_pids)" ]; then
      echo "✓ Server started (PID: $(_host_pids | tr '\n' ' '))"
      echo "  Access at: http://localhost:8484"
      echo "  Logs: tail -f /tmp/muzic-channelz.log"
    else
      echo "✗ Failed to start server. Check logs: cat /tmp/muzic-channelz.log"
      exit 1
    fi
    ;;
  stop)
    PIDS=$(_host_pids)
    if [ -z "$PIDS" ]; then
      echo "Server is not running (note: Docker-managed instances must be stopped with docker-compose)"
      exit 1
    fi
    echo "$PIDS" | xargs kill -TERM
    sleep 2
    if [ -n "$(_host_pids)" ]; then
      echo "✗ Failed to stop server"
      exit 1
    fi
    echo "✓ Server stopped"
    ;;
  restart)
    $0 stop
    sleep 2
    $0 start
    ;;
  status)
    if [ -n "$(_host_pids)" ]; then
      PID=$(_host_pids | tr '\n' ' ')
      echo "✓ Server is running (PID: $PID)"
      echo "  Access at: http://localhost:8484"
      if curl -s http://localhost:8484/api/admin/state > /dev/null 2>&1; then
        echo "  Status: Responding OK"
      else
        echo "  Status: Not responding"
      fi
    else
      echo "✗ Server is not running (host)"
      if pgrep -f "uvicorn app.main" > /dev/null; then
        echo "  (Docker-managed instance detected — use docker-compose to manage it)"
      fi
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
