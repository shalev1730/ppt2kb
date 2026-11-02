# syntax=docker/dockerfile:1.6
#
# ppt2kb - PowerPoint -> ServiceNow Knowledge (on-premise)
#
# Build (online):   docker build -f deploy/docker/Dockerfile -t ppt2kb:1.0.0 .
# Build (offline):  docker build -f deploy/docker/Dockerfile -t ppt2kb:1.0.0 \
#                     --build-arg PIP_INDEX_URL=http://nexus.internal/repository/pypi/simple \
#                     --build-arg APT_MIRROR=http://mirror.internal/debian .
#                   or build once online, then `scripts/export-image.sh` and import in the air-gapped site.
#
# The image contains: Python runtime, the application, LibreOffice Impress
# (headless), Hebrew/Latin fonts and pdfium (bundled in the pypdfium2 wheel).
# It runs as a non-root user, has no shell entrypoint tricks and makes no
# network connections except those configured through PPT2KB_* variables.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

# ----------------------------------------------------------------- builder
FROM ${PYTHON_IMAGE} AS builder
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_INDEX_URL=${PIP_INDEX_URL}
WORKDIR /build
COPY requirements.txt pyproject.toml README.md ./
COPY src ./src
# A pre-downloaded wheelhouse (see scripts/build-offline-bundle.sh) can be used
# by placing it in deploy/docker/wheelhouse/ before building.
COPY deploy/docker/wheelhouse* ./wheelhouse/
RUN python -m venv /opt/ppt2kb \
 && if ls wheelhouse/*.whl >/dev/null 2>&1; then \
      /opt/ppt2kb/bin/pip install --no-index --find-links=wheelhouse -r requirements.txt . ; \
    else \
      /opt/ppt2kb/bin/pip install ${PIP_TRUSTED_HOST:+--trusted-host $PIP_TRUSTED_HOST} -r requirements.txt . ; \
    fi \
 && /opt/ppt2kb/bin/pip uninstall -y pip setuptools wheel >/dev/null 2>&1 || true

# ----------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE}
ARG APT_MIRROR=
LABEL org.opencontainers.image.title="ppt2kb" \
      org.opencontainers.image.description="Secure on-premise PowerPoint to ServiceNow Knowledge converter" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.source="internal"

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/ppt2kb/bin:/usr/local/bin:/usr/bin:/bin \
    PPT2KB_HOST=0.0.0.0 \
    PPT2KB_PORT=8080 \
    PPT2KB_DATA_DIR=/data \
    PPT2KB_LIBREOFFICE_PATH=/usr/bin/soffice \
    OTEL_SDK_DISABLED=true \
    HOME=/home/ppt2kb

RUN set -eux; \
    if [ -n "$APT_MIRROR" ]; then sed -i "s#http://deb.debian.org/debian#${APT_MIRROR}#g" /etc/apt/sources.list.d/debian.sources; fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        libreoffice-impress libreoffice-draw libreoffice-core libreoffice-common \
        fonts-dejavu-core fonts-liberation2 fonts-noto-core fonts-crosextra-carlito fonts-crosextra-caladea \
        culmus fonts-noto-color-emoji \
        fontconfig tini ca-certificates; \
    fc-cache -f; \
    apt-get purge -y --auto-remove; \
    apt-get clean; \
    rm -rf /var/lib/apt/lists/* /usr/share/doc /usr/share/man; \
    groupadd -r -g 10001 ppt2kb; \
    useradd -r -u 10001 -g ppt2kb -d /home/ppt2kb -s /usr/sbin/nologin ppt2kb; \
    mkdir -p /data /home/ppt2kb /app; \
    chown -R ppt2kb:ppt2kb /data /home/ppt2kb /app

COPY --from=builder --chown=root:root /opt/ppt2kb /opt/ppt2kb
COPY --chown=root:root deploy/docker/entrypoint.sh /app/entrypoint.sh
COPY --chown=root:root LICENSE LICENSE.ppt2desc THIRD_PARTY_NOTICES.md /app/
RUN chmod 0755 /app/entrypoint.sh

USER ppt2kb:ppt2kb
WORKDIR /home/ppt2kb
VOLUME ["/data"]
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["/opt/ppt2kb/bin/python", "-c", "import os,sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/healthz'%os.environ.get('PPT2KB_PORT','8080'),timeout=4).status==200 else 1)"]

ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]
CMD ["ppt2kb"]
