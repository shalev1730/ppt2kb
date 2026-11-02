#!/usr/bin/env bash
# Build the offline installation bundle for the STANDALONE (non-Docker) deployment.
#
#   scripts/build-offline-bundle.sh [--python 3.12] [--arch x86_64] [--out dist]
#
# Run on a machine WITH internet (or with access to an internal PyPI mirror) and
# the same CPU architecture family as the target. The resulting tarball contains:
#   wheelhouse/            all Python wheels (app + pinned dependencies, pip, setuptools)
#   deploy/standalone/     installer, systemd unit, scripts, example config
#   docs/, README.md, LICENSE*, THIRD_PARTY_NOTICES.md, sbom/
#   SHA256SUMS
# Operating-system packages (python3, LibreOffice, fonts) are NOT included; they
# come from the enterprise OS mirror - see docs/AIRGAP.md.
set -euo pipefail
cd "$(dirname "$0")/.."

PY="3.12"
ARCH="x86_64"
OUT="dist"
while [ $# -gt 0 ]; do
  case "$1" in
    --python) PY="$2"; shift 2;;
    --arch) ARCH="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    *) echo "unknown option $1"; exit 2;;
  esac
done
VERSION="$(python3 -c 'import re;print(re.search(r"version\s*=\s*\"([^\"]+)\"", open("pyproject.toml").read()).group(1))')"
PYTAG="cp${PY/./}"
STAGE="$(mktemp -d)"
BUNDLE="ppt2kb-${VERSION}-offline-py${PY}-${ARCH}"
mkdir -p "$STAGE/$BUNDLE/wheelhouse" "$OUT"

echo "==> Building application wheel"
python3 -m pip wheel --no-deps -w "$STAGE/$BUNDLE/wheelhouse" . >/dev/null

echo "==> Downloading pinned dependency wheels for Python $PY / $ARCH"
python3 -m pip download -r requirements.txt -d "$STAGE/$BUNDLE/wheelhouse" \
  --only-binary=:all: --platform "manylinux_2_28_${ARCH}" --platform "manylinux_2_17_${ARCH}" --platform "manylinux2014_${ARCH}" --platform any \
  --python-version "$PY" --implementation cp --abi "$PYTAG" --abi abi3 --abi none
echo "==> Downloading pip/setuptools/wheel for the venv"
python3 -m pip download pip setuptools wheel -d "$STAGE/$BUNDLE/wheelhouse" --only-binary=:all: --platform any --python-version "$PY" >/dev/null

echo "==> Copying deployment files"
cp -r deploy/standalone "$STAGE/$BUNDLE/deploy-standalone"
mkdir -p "$STAGE/$BUNDLE/deploy"; mv "$STAGE/$BUNDLE/deploy-standalone" "$STAGE/$BUNDLE/deploy/standalone"
cp -r docs README.md LICENSE LICENSE.ppt2desc THIRD_PARTY_NOTICES.md requirements.txt "$STAGE/$BUNDLE/"
[ -d sbom ] && cp -r sbom "$STAGE/$BUNDLE/"
cp -r mocks "$STAGE/$BUNDLE/"   # mock services for the offline POC

( cd "$STAGE/$BUNDLE" && find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS )
tar -C "$STAGE" -czf "$OUT/$BUNDLE.tar.gz" "$BUNDLE"
( cd "$OUT" && sha256sum "$BUNDLE.tar.gz" >> SHA256SUMS )
rm -rf "$STAGE"
echo "==> Bundle written: $OUT/$BUNDLE.tar.gz"
echo "    Transfer it to the target server and run: tar xzf $BUNDLE.tar.gz && sudo $BUNDLE/deploy/standalone/install.sh"
