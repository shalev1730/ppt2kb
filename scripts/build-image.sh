#!/usr/bin/env bash
# Build the ppt2kb OCI image.
#   scripts/build-image.sh [tag]            (default tag: ppt2kb:1.0.0)
# Optional env: PIP_INDEX_URL, PIP_TRUSTED_HOST, APT_MIRROR, PYTHON_IMAGE
set -euo pipefail
cd "$(dirname "$0")/.."
TAG="${1:-ppt2kb:1.0.0}"
ARGS=()
[ -n "${PIP_INDEX_URL:-}" ] && ARGS+=(--build-arg "PIP_INDEX_URL=$PIP_INDEX_URL")
[ -n "${PIP_TRUSTED_HOST:-}" ] && ARGS+=(--build-arg "PIP_TRUSTED_HOST=$PIP_TRUSTED_HOST")
[ -n "${APT_MIRROR:-}" ] && ARGS+=(--build-arg "APT_MIRROR=$APT_MIRROR")
[ -n "${PYTHON_IMAGE:-}" ] && ARGS+=(--build-arg "PYTHON_IMAGE=$PYTHON_IMAGE")
echo "Building $TAG ..."
docker build -f deploy/docker/Dockerfile -t "$TAG" "${ARGS[@]}" .
echo "Done. Verify with: docker run --rm $TAG ppt2kb --help || docker run --rm $TAG python -c 'import ppt2kb;print(ppt2kb.__version__)'"
