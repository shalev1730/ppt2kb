# ppt2kb-web-offline.tar — deployment guide (internal container environment)

`ppt2kb-web-offline.tar` is a complete, pre-built OCI/Docker image
(`ppt2kb:1.1.0`, Debian 12, Python 3.12, LibreOffice 7.4 headless, Hebrew and
Latin fonts, non-root). Import it into the internal Docker host; no registry
or internet access is needed at any point.

## 1. Transfer and import

```bash
sha256sum -c SHA256SUMS                         # the lines for ppt2kb-web-offline.tar(.gz) must say OK
docker load -i ppt2kb-web-offline.tar           # -> Loaded image: ppt2kb:1.1.0
#   (if you received the compressed file: `docker load -i ppt2kb-web-offline.tar.gz` works directly,
#    or `gunzip -k ppt2kb-web-offline.tar.gz` to obtain the exact .tar listed in SHA256SUMS)
docker images ppt2kb                            # ppt2kb  1.1.0  ...  ~620MB
docker run --rm ppt2kb:1.1.0 soffice --version  # smoke test: prints the LibreOffice version
```

Podman works the same way (`podman load -i ...`, `podman-compose` or
`podman run` with the flags below).

## 2. Configure

Copy the `deploy/docker` folder next to the image, then:

```bash
cd deploy/docker
cp .env.example .env
chmod 600 .env
vi .env            # Qwen URL/model/key, ServiceNow URL/credentials, allowed hosts, port
mkdir -p certs && cp /path/to/internal-ca-chain.pem certs/ca.pem
```

Minimum settings to change in `.env`:

```
PPT2KB_BIND_ADDRESS=0.0.0.0                # or 127.0.0.1 behind a reverse proxy on the host
PPT2KB_HOST_PORT=8080                      # internal web address: http://<host>:8080/
PPT2KB_QWEN_BASE_URL=https://qwen.internal.example/v1
PPT2KB_QWEN_MODEL=Qwen2.5-VL-72B-Instruct
PPT2KB_QWEN_API_KEY=...
PPT2KB_SERVICENOW_URL=https://servicenow.internal.example
PPT2KB_SERVICENOW_USERNAME=svc_ppt2kb
PPT2KB_SERVICENOW_PASSWORD=...
PPT2KB_CA_BUNDLE=/certs/ca.pem             # the file mounted from ./certs/ca.pem
PPT2KB_ALLOWED_OUTBOUND_HOSTS=qwen.internal.example,servicenow.internal.example
```

Optional: `PPT2KB_UI_USERNAME` / `PPT2KB_UI_PASSWORD` for Basic authentication
(recommended: SSO on your reverse proxy instead), `PPT2KB_CPUS` /
`PPT2KB_MEMORY` resource limits, `PPT2KB_RETENTION_DAYS`. The full reference is
`docs/CONFIGURATION.md`.

## 3. Start, check, stop

```bash
docker compose up -d                                   # from deploy/docker
docker compose ps                                      # State: Up (healthy) after ~20 s
curl -s http://127.0.0.1:8080/api/health               # {"status":"ok","version":"1.0.0","libreoffice":true,...}
docker compose logs -f                                 # application log (no slide content, no credentials)
docker compose stop                                    # stop (data volume kept)
docker compose down                                    # remove the container (data volume kept)
```

Open `http://<docker-host>:8080/` from an internal browser (**Settings → Test
connection** for both endpoints first).

Persistent storage: the named volume `ppt2kb-data` (mounted at `/data`)
holds uploaded presentations (`uploads/`), generated slide images and JSON
state (`jobs/<id>/`) and the SQLite database (`ppt2kb.sqlite3`). To use a host
directory instead, uncomment the `driver_opts` block in `docker-compose.yml`
and `chown -R 10001:10001` the directory. Back it up like any other store of
the presentations' content.

Security defaults applied by the Compose file: non-root user (uid 10001),
read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, `pids_limit`,
CPU/memory limits, tmpfs `/tmp`, health check on `/healthz`,
`restart: unless-stopped`, JSON log rotation, OpenTelemetry disabled.

Without Compose:

```bash
docker volume create ppt2kb-data
docker run -d --name ppt2kb --restart unless-stopped --env-file .env \
  -e PPT2KB_CA_BUNDLE=/certs/ca.pem -p 8080:8080 \
  -v ppt2kb-data:/data -v "$PWD/certs:/certs:ro" \
  --read-only --tmpfs /tmp:size=1g --cap-drop ALL --security-opt no-new-privileges \
  --memory 6g --cpus 4 --pids-limit 512 ppt2kb:1.1.0
```

## 4. Update to a new version

```bash
sha256sum -c SHA256SUMS && docker load -i ppt2kb-web-offline.tar   # new tar, e.g. ppt2kb:1.1.0 (from 1.0.x: the database is migrated automatically on first start)
sed -i 's/^PPT2KB_IMAGE=.*/PPT2KB_IMAGE=ppt2kb:1.1.0/' .env
docker compose up -d                 # recreates the container; the data volume and .env are reused
docker image rm ppt2kb:1.0.1         # optional: remove the previous image after verifying the new version
```

Roll back by setting `PPT2KB_IMAGE` to the previous tag and `docker compose up -d`.

## 5. Network policy

| Direction | From | To | Port |
|---|---|---|---|
| inbound | users / reverse proxy | Docker host | `PPT2KB_HOST_PORT` (8080) |
| outbound | container | Qwen API host | 443 (or as configured) |
| outbound | container | ServiceNow instance | 443 |

Nothing else is required. If the internal names do not resolve from the Docker
host, add `extra_hosts` entries in `docker-compose.yml`. Proxy environment
variables are ignored by the application and cleared for LibreOffice.

## 6. Verifying the image before approval

```bash
docker run --rm ppt2kb:1.1.0 id                                   # uid=10001(ppt2kb)
docker run --rm ppt2kb:1.1.0 python -c "import ppt2kb;print(ppt2kb.__version__)"
docker run --rm ppt2kb:1.1.0 /opt/ppt2kb/bin/pip list 2>/dev/null || docker run --rm ppt2kb:1.1.0 ls /opt/ppt2kb/lib/python3.12/site-packages
docker run --rm ppt2kb:1.1.0 cat /app/THIRD_PARTY_NOTICES.md
# reproduce the image from source (see docs/BUILD_REPRODUCIBLE.md)
```

A full functional test without the real endpoints: run the mock services from
the source archive on the Docker host (`python3 -m mocks.mock_qwen --port 9001`,
`python3 -m mocks.mock_servicenow --port 9002`) and point the container at
`http://host.docker.internal:9001/v1` / `:9002` (add
`extra_hosts: ["host.docker.internal:host-gateway"]`), credentials
`admin`/`admin`.
