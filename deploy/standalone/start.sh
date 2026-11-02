#!/usr/bin/env bash
# Start ppt2kb in the foreground or as a background process (without systemd).
#   /opt/ppt2kb/start.sh            foreground
#   /opt/ppt2kb/start.sh --daemon   background, pid file in the data directory
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/ppt2kb.paths"
set -a
# shellcheck disable=SC1090
source "$CONF_DIR/ppt2kb.env"
set +a
export PPT2KB_DATA_DIR="${PPT2KB_DATA_DIR:-$DATA_DIR}" OTEL_SDK_DISABLED=true NO_PROXY='*' no_proxy='*' HOME="$DATA_DIR"
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy || true
cd "$DATA_DIR"
PIDFILE="$DATA_DIR/ppt2kb.pid"
if [ "${1:-}" = "--daemon" ]; then
  if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then echo "already running (pid $(cat "$PIDFILE"))"; exit 0; fi
  nohup "$PREFIX/venv/bin/ppt2kb" >> "$LOG_DIR/ppt2kb.log" 2>&1 &
  echo $! > "$PIDFILE"
  echo "started ppt2kb (pid $!) - log: $LOG_DIR/ppt2kb.log"
else
  exec "$PREFIX/venv/bin/ppt2kb"
fi
