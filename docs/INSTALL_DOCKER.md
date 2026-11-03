# Option A — Docker image with web UI

The image contains Python 3.12, the application, LibreOffice Impress
(headless), pdfium and Hebrew/Latin fonts. It runs as user `ppt2kb` (uid 10001),
with a read-only root file system; all state is in the `/data` volume.

## 1. Build (on a machine with internet or with internal mirrors)

```bash
git clone <internal repo>/ppt2kb && cd ppt2kb
scripts/build-image.sh ppt2kb:1.1.1
#   equivalent: docker build -f deploy/docker/Dockerfile -t ppt2kb:1.1.1 .
```

Using internal mirrors instead of the internet:

```bash
PIP_INDEX_URL=https://nexus.internal/repository/pypi/simple \
PIP_TRUSTED_HOST=nexus.internal \
APT_MIRROR=http://mirror.internal/debian \
scripts/build-image.sh ppt2kb:1.1.1
```

Fully offline build (no PyPI at all): put the wheels produced by
`scripts/build-offline-bundle.sh --python 3.12` into `deploy/docker/wheelhouse/`
before building; the Dockerfile then installs with `--no-index`. The Debian
packages (LibreOffice, fonts) still need an APT mirror or a pre-built base
image — in practice the simplest air-gapped route is to **build once on the
connected side and transfer the image** (next section).

Smoke test the image:

```bash
docker run --rm ppt2kb:1.1.1 python -c "import ppt2kb;print(ppt2kb.__version__)"
docker run --rm ppt2kb:1.1.1 soffice --version
```

## 2. Export / import for the air-gapped site

```bash
scripts/export-image.sh ppt2kb:1.1.1 dist      # -> dist/ppt2kb-1.1.1-image.tar.gz + SHA256SUMS
# transfer dist/ to the target site (approved media / transfer gateway)
scripts/import-image.sh dist/ppt2kb-1.1.1-image.tar.gz   # verifies the checksum, docker load
```

Also transfer `deploy/docker/` (Compose file + `.env.example`) and `docs/`.

## 3. Configure

```bash
cd deploy/docker
cp .env.example .env            # edit: Qwen URL/model/key, ServiceNow URL/credentials, CA bundle
mkdir -p certs && cp /path/to/internal-ca-chain.pem certs/ca.pem
chmod 600 .env
```

Key variables (full list in `docs/CONFIGURATION.md`):

| Variable | Meaning |
|---|---|
| `PPT2KB_HOST_PORT`, `PPT2KB_BIND_ADDRESS` | host port / interface for the web UI (default 8080 on all interfaces; use `127.0.0.1` behind a reverse proxy) |
| `PPT2KB_QWEN_BASE_URL`, `PPT2KB_QWEN_MODEL`, `PPT2KB_QWEN_API_KEY` | internal Qwen Vision endpoint (OpenAI-compatible `/chat/completions`) |
| `PPT2KB_SERVICENOW_URL`, `PPT2KB_SERVICENOW_USERNAME/PASSWORD` (or `_TOKEN`) | ServiceNow instance and service account |
| `PPT2KB_CA_BUNDLE` | PEM chain of the internal CA (mounted at `/certs/ca.pem`) |
| `PPT2KB_ALLOWED_OUTBOUND_HOSTS` | lock outbound traffic to exactly these hosts |
| `PPT2KB_CPUS`, `PPT2KB_MEMORY` | container resource limits (LibreOffice needs ~1–3 GB for large decks) |

## 4. Run

```bash
docker compose -f deploy/docker/docker-compose.yml up -d
docker compose -f deploy/docker/docker-compose.yml logs -f
curl -s http://127.0.0.1:8080/api/health     # {"status":"ok","version":"1.0.0","libreoffice":true,...}
```

Open `http://<host>:8080/`. The Compose file sets `restart: unless-stopped`, a
health check (`/healthz`), CPU/memory limits, `pids_limit`, a named volume for
`/data`, tmpfs `/tmp`, read-only root FS, `cap_drop: ALL` and
`no-new-privileges`.

Without Compose:

```bash
docker volume create ppt2kb-data
docker run -d --name ppt2kb --restart unless-stopped \
  --env-file deploy/docker/.env -e PPT2KB_CA_BUNDLE=/certs/ca.pem \
  -p 8080:8080 -v ppt2kb-data:/data -v $PWD/deploy/docker/certs:/certs:ro \
  --read-only --tmpfs /tmp:size=1g --cap-drop ALL --security-opt no-new-privileges \
  --memory 6g --cpus 4 --pids-limit 512 ppt2kb:1.1.1
```

## 5. Data volume

`/data` holds `uploads/` (original files), `jobs/<id>/images/` (slide PNGs),
`ppt2kb.sqlite3` (jobs, slides, generated text, UI settings) and `tmp/`
(LibreOffice work dirs). Back it up like any other sensitive data store; the
retention job deletes jobs older than `PPT2KB_RETENTION_DAYS`.

If you bind-mount a host directory instead of the named volume, it must be
writable by uid 10001: `chown -R 10001:10001 /srv/ppt2kb/data`.

## 6. Reverse proxy / TLS for the UI

The container serves plain HTTP on its internal port. Terminate TLS and
authenticate users on the enterprise reverse proxy (nginx/Apache/F5 with SSO);
allow large request bodies (`client_max_body_size 250m;`) and long timeouts for
uploads. Alternatively enable Basic auth with `PPT2KB_UI_USERNAME/PASSWORD`.

## 7. Upgrade

```bash
scripts/import-image.sh dist/ppt2kb-1.1.1-image.tar.gz
sed -i 's/^PPT2KB_IMAGE=.*/PPT2KB_IMAGE=ppt2kb:1.1.1/' deploy/docker/.env
docker compose -f deploy/docker/docker-compose.yml up -d     # data volume is reused; schema migrates automatically
```

## 8. Network requirements

Outbound from the container: only the Qwen API host and the ServiceNow host
(HTTPS). Inbound: the UI port from the users' network / reverse proxy. No DNS
or internet access is required; use `extra_hosts` in the Compose file if the
internal names are not resolvable from the Docker host.

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| `status: degraded`, `libreoffice: false` in `/api/health` | image build incomplete; `docker run --rm ppt2kb:1.1.1 soffice --version` |
| job status `failed: conversion failed: LibreOffice conversion timed out` | raise `PPT2KB_CONVERSION_TIMEOUT_S` / `PPT2KB_CONVERSION_MEMORY_MB` and the container memory limit |
| slides `failed: connection error` | Qwen URL/DNS/CA; test with **Settings → Test connection**; check `PPT2KB_ALLOWED_OUTBOUND_HOSTS` |
| `Outbound host ... is not allow-listed` in logs | add the host (host or host:port) to `PPT2KB_ALLOWED_OUTBOUND_HOSTS` |
| `ServiceNow authentication/authorization failed (HTTP 403)` | service-account roles, see `docs/SERVICENOW.md` |
| Hebrew rendered as boxes | fonts missing in a custom base image: `fc-list :lang=he` inside the container |
