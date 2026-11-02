#!/usr/bin/env bash
# Remove the ppt2kb service and application. Data in /var/lib/ppt2kb is kept unless --purge is given.
set -euo pipefail
PREFIX="${1:-/opt/ppt2kb}"
PURGE=0; [ "${2:-}" = "--purge" ] && PURGE=1
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
if [ -f "$PREFIX/ppt2kb.paths" ]; then source "$PREFIX/ppt2kb.paths"; else DATA_DIR=/var/lib/ppt2kb; CONF_DIR=/etc/ppt2kb; LOG_DIR=/var/log/ppt2kb; SVC_USER=ppt2kb; fi
if command -v systemctl >/dev/null 2>&1 && [ -f /etc/systemd/system/ppt2kb.service ]; then
  systemctl disable --now ppt2kb.service || true
  rm -f /etc/systemd/system/ppt2kb.service
  systemctl daemon-reload
fi
rm -rf "$PREFIX"
if [ "$PURGE" = 1 ]; then rm -rf "$DATA_DIR" "$CONF_DIR" "$LOG_DIR"; userdel "$SVC_USER" 2>/dev/null || true; echo "purged data, configuration and user"; else echo "kept $DATA_DIR and $CONF_DIR (use --purge to remove)"; fi
echo "ppt2kb removed"
