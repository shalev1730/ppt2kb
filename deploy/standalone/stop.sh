#!/usr/bin/env bash
# Stop a ppt2kb instance started with start.sh --daemon (graceful, then SIGKILL after 30s).
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/ppt2kb.paths"
PIDFILE="$DATA_DIR/ppt2kb.pid"
if [ ! -f "$PIDFILE" ]; then echo "not running (no pid file)"; exit 0; fi
PID="$(cat "$PIDFILE")"
if ! kill -0 "$PID" 2>/dev/null; then echo "stale pid file"; rm -f "$PIDFILE"; exit 0; fi
kill -TERM "$PID"
for _ in $(seq 1 30); do kill -0 "$PID" 2>/dev/null || { rm -f "$PIDFILE"; echo "stopped"; exit 0; }; sleep 1; done
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PIDFILE"
echo "killed"
