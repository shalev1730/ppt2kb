#!/usr/bin/env bash
# Verify that the target server has the operating-system prerequisites for ppt2kb.
# Safe to run as any user. Exit code 0 = ready.
set -u
PYTHON="${PPT2KB_PYTHON:-python3}"
ok=1
say() { printf '%-34s %s\n' "$1" "$2"; }

if command -v "$PYTHON" >/dev/null 2>&1; then
  ver="$("$PYTHON" -c 'import sys;print("%d.%d"%sys.version_info[:2])')"
  if "$PYTHON" -c 'import sys;sys.exit(0 if sys.version_info>=(3,11) else 1)'; then say "python ($PYTHON)" "OK $ver"; else say "python ($PYTHON)" "TOO OLD ($ver, need >= 3.11)"; ok=0; fi
  if "$PYTHON" -c 'import venv, ensurepip' 2>/dev/null; then say "python venv/ensurepip" "OK"; else say "python venv/ensurepip" "MISSING (install python3-venv)"; ok=0; fi
else
  say "python ($PYTHON)" "MISSING"; ok=0
fi

LO="$(command -v soffice || command -v libreoffice || true)"
if [ -n "$LO" ]; then say "libreoffice" "OK $LO ($("$LO" --version 2>/dev/null | head -1))"; else say "libreoffice" "MISSING (install libreoffice-impress)"; ok=0; fi

if command -v fc-list >/dev/null 2>&1; then
  if fc-list :lang=he 2>/dev/null | grep -q .; then say "Hebrew fonts" "OK ($(fc-list :lang=he | wc -l) faces)"; else say "Hebrew fonts" "MISSING (install culmus / fonts-noto-core)"; ok=0; fi
  if fc-list 2>/dev/null | grep -qiE "liberation|dejavu|carlito"; then say "Latin fonts" "OK"; else say "Latin fonts" "MISSING (install fonts-liberation2 fonts-dejavu-core)"; ok=0; fi
else
  say "fontconfig (fc-list)" "MISSING"; ok=0
fi

if command -v systemctl >/dev/null 2>&1; then say "systemd" "OK"; else say "systemd" "not found (use start.sh/stop.sh instead of the unit file)"; fi
if [ "$ok" = 1 ]; then echo "All prerequisites satisfied."; exit 0; else echo "Prerequisites missing - see docs/INSTALL_STANDALONE.md"; exit 1; fi
