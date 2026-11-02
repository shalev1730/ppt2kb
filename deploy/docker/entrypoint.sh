#!/bin/sh
# Container entrypoint: validate the data volume and start the application.
set -eu

DATA_DIR="${PPT2KB_DATA_DIR:-/data}"
if [ ! -d "$DATA_DIR" ]; then
  echo "ERROR: data directory $DATA_DIR does not exist (mount a volume)" >&2
  exit 1
fi
if [ ! -w "$DATA_DIR" ]; then
  echo "ERROR: data directory $DATA_DIR is not writable by uid $(id -u). Run: chown -R 10001:10001 <host path>" >&2
  exit 1
fi

# Custom CA bundle: mount a PEM file and set PPT2KB_CA_BUNDLE=/certs/ca.pem.
if [ -n "${PPT2KB_CA_BUNDLE:-}" ] && [ ! -r "$PPT2KB_CA_BUNDLE" ]; then
  echo "ERROR: PPT2KB_CA_BUNDLE=$PPT2KB_CA_BUNDLE is not readable" >&2
  exit 1
fi

# Never allow proxy variables to influence the application or LibreOffice.
unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy || true
export NO_PROXY='*' no_proxy='*' OTEL_SDK_DISABLED=true

exec "$@"
