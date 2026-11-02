#!/usr/bin/env bash
# Import an exported image inside the air-gapped environment.
#   scripts/import-image.sh dist/ppt2kb-1.0.0-image.tar.gz
set -euo pipefail
FILE="${1:?usage: import-image.sh <image.tar.gz>}"
DIR="$(dirname "$FILE")"
if [ -f "$DIR/SHA256SUMS" ]; then
  echo "Verifying checksum ..."
  ( cd "$DIR" && grep " $(basename "$FILE")\$" SHA256SUMS | sha256sum -c - )
fi
echo "Loading image ..."
gunzip -c "$FILE" | docker load
echo "Loaded. List with: docker images | grep ppt2kb"
