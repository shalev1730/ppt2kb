#!/usr/bin/env bash
# ppt2kb standalone installer (Linux, no Docker).
#
#   sudo deploy/standalone/install.sh [--prefix /opt/ppt2kb] [--wheelhouse ./wheelhouse] [--no-systemd] [--user ppt2kb]
#
# What it does (idempotent; re-run for upgrades):
#   1. checks prerequisites (python >= 3.11, LibreOffice, fonts)
#   2. creates the service user and directories
#        /opt/ppt2kb            virtualenv + application
#        /etc/ppt2kb/ppt2kb.env configuration (created from example, never overwritten)
#        /var/lib/ppt2kb        data (uploads, slide images, SQLite database)
#        /var/log/ppt2kb        logs (when not using journald)
#   3. installs the application and its pinned dependencies from the local wheelhouse
#      (no network access required)
#   4. installs start/stop scripts and the systemd unit
set -euo pipefail

PREFIX="/opt/ppt2kb"
CONF_DIR="/etc/ppt2kb"
DATA_DIR="/var/lib/ppt2kb"
LOG_DIR="/var/log/ppt2kb"
SVC_USER="ppt2kb"
USE_SYSTEMD=1
HERE="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_ROOT="$(cd "$HERE/../.." && pwd)"
WHEELHOUSE="$BUNDLE_ROOT/wheelhouse"
PYTHON="${PPT2KB_PYTHON:-python3}"

while [ $# -gt 0 ]; do
  case "$1" in
    --prefix) PREFIX="$2"; shift 2;;
    --wheelhouse) WHEELHOUSE="$2"; shift 2;;
    --user) SVC_USER="$2"; shift 2;;
    --data-dir) DATA_DIR="$2"; shift 2;;
    --conf-dir) CONF_DIR="$2"; shift 2;;
    --no-systemd) USE_SYSTEMD=0; shift;;
    --python) PYTHON="$2"; shift 2;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

if [ "$(id -u)" -ne 0 ]; then echo "Run as root (sudo)." >&2; exit 1; fi
echo "==> Checking prerequisites"
PPT2KB_PYTHON="$PYTHON" bash "$HERE/check-prereqs.sh" || { echo "Install the missing OS packages first (docs/INSTALL_STANDALONE.md)."; exit 1; }
[ -d "$WHEELHOUSE" ] || { echo "Wheelhouse not found at $WHEELHOUSE (build it with scripts/build-offline-bundle.sh)" >&2; exit 1; }

echo "==> Creating user and directories"
if ! id "$SVC_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$DATA_DIR" --shell /usr/sbin/nologin --user-group "$SVC_USER"
fi
mkdir -p "$PREFIX" "$CONF_DIR" "$DATA_DIR" "$LOG_DIR"
chown "$SVC_USER:$SVC_USER" "$DATA_DIR" "$LOG_DIR"
chown "root:$SVC_USER" "$CONF_DIR"
chmod 0750 "$DATA_DIR" "$LOG_DIR" "$CONF_DIR"

echo "==> Installing virtualenv in $PREFIX/venv (offline, from $WHEELHOUSE)"
if [ ! -x "$PREFIX/venv/bin/python" ]; then
  "$PYTHON" -m venv --without-pip "$PREFIX/venv"
  "$PREFIX/venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || \
    "$PYTHON" -m pip install --no-index --find-links="$WHEELHOUSE" --target "$PREFIX/venv/lib/python$("$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])')/site-packages" pip >/dev/null
fi
"$PREFIX/venv/bin/python" -m pip install --no-index --find-links="$WHEELHOUSE" --upgrade pip >/dev/null 2>&1 || true
"$PREFIX/venv/bin/python" -m pip install -q --no-index --find-links="$WHEELHOUSE" --upgrade -r "$BUNDLE_ROOT/requirements.txt" ppt2kb
"$PREFIX/venv/bin/python" -c 'import ppt2kb, sys; print("    installed ppt2kb", ppt2kb.__version__, "on python", sys.version.split()[0])'

echo "==> Installing scripts and configuration"
install -m 0755 "$HERE/start.sh" "$PREFIX/start.sh"
install -m 0755 "$HERE/stop.sh" "$PREFIX/stop.sh"
install -m 0755 "$HERE/check-prereqs.sh" "$PREFIX/check-prereqs.sh"
install -m 0644 "$HERE/config.env.example" "$CONF_DIR/ppt2kb.env.example"
if [ ! -f "$CONF_DIR/ppt2kb.env" ]; then
  install -m 0640 -o root -g "$SVC_USER" "$HERE/config.env.example" "$CONF_DIR/ppt2kb.env"
  sed -i "s#^PPT2KB_DATA_DIR=.*#PPT2KB_DATA_DIR=$DATA_DIR#" "$CONF_DIR/ppt2kb.env"
  echo "    created $CONF_DIR/ppt2kb.env - EDIT IT (Qwen / ServiceNow settings and credentials)"
else
  echo "    kept existing $CONF_DIR/ppt2kb.env"
fi
cat > "$PREFIX/ppt2kb.paths" <<EOF
PREFIX=$PREFIX
CONF_DIR=$CONF_DIR
DATA_DIR=$DATA_DIR
LOG_DIR=$LOG_DIR
SVC_USER=$SVC_USER
EOF
chmod 0644 "$PREFIX/ppt2kb.paths"

if [ "$USE_SYSTEMD" = 1 ] && command -v systemctl >/dev/null 2>&1; then
  echo "==> Installing systemd unit"
  sed -e "s#@PREFIX@#$PREFIX#g" -e "s#@CONF_DIR@#$CONF_DIR#g" -e "s#@DATA_DIR@#$DATA_DIR#g" -e "s#@USER@#$SVC_USER#g" \
      "$HERE/ppt2kb.service" > /etc/systemd/system/ppt2kb.service
  systemctl daemon-reload
  systemctl enable ppt2kb.service >/dev/null
  echo "    enabled ppt2kb.service (start with: systemctl start ppt2kb)"
fi

cat <<EOF

ppt2kb installed.
  configuration : $CONF_DIR/ppt2kb.env
  data          : $DATA_DIR
  start         : systemctl start ppt2kb      (or $PREFIX/start.sh)
  status        : systemctl status ppt2kb ; journalctl -u ppt2kb -f
  web UI        : http://<server>:\$PPT2KB_PORT/  (default 8080)
EOF
