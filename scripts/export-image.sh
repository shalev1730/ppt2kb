#!/usr/bin/env bash
# Export the built image for transfer into an air-gapped environment.
#   scripts/export-image.sh [tag] [out-dir]
# Produces <out-dir>/ppt2kb-<version>-image.tar.gz and a SHA256SUMS file.
set -euo pipefail
TAG="${1:-ppt2kb:1.0.0}"
OUT="${2:-dist}"
mkdir -p "$OUT"
NAME="$(echo "$TAG" | tr ':/' '--')-image.tar.gz"
echo "Saving $TAG to $OUT/$NAME ..."
docker save "$TAG" | gzip -6 > "$OUT/$NAME"
( cd "$OUT" && sha256sum "$NAME" >> SHA256SUMS )
echo "Written $OUT/$NAME"
echo "Transfer the file and SHA256SUMS to the target site, then run scripts/import-image.sh"
