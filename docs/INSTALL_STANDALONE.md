# Option B — Standalone on-premise application (Linux, no Docker)

Same code, same UI and features as the container. Installed into
`/opt/ppt2kb` (virtualenv), configured in `/etc/ppt2kb/ppt2kb.env`, data in
`/var/lib/ppt2kb`, managed by **systemd** (`ppt2kb.service`) or by
`start.sh`/`stop.sh` where systemd is not available.

## 1. Operating-system prerequisites (from the enterprise OS mirror)

| Component | Debian / Ubuntu | RHEL / Rocky / Alma 9 |
|---|---|---|
| Python ≥ 3.11 with venv | `python3 python3-venv` (3.11 on Debian 12, 3.12 on Ubuntu 24.04) | `python3.12 python3.12-pip` (AppStream) |
| LibreOffice headless | `libreoffice-impress libreoffice-draw libreoffice-core libreoffice-common` | `libreoffice-impress libreoffice-draw libreoffice-headless` |
| Fonts | `fonts-dejavu-core fonts-liberation2 fonts-crosextra-carlito fonts-crosextra-caladea fonts-noto-core culmus` | `dejavu-sans-fonts liberation-fonts google-noto-sans-hebrew-fonts google-carlito-fonts` (+ Culmus from EPEL or the Culmus RPM) |
| fontconfig | `fontconfig` | `fontconfig` |

Verify with `deploy/standalone/check-prereqs.sh` (prints OK/MISSING per item).
Note: the Python version on the server decides which offline bundle you need
(the wheels are built per Python minor version, see §2).

## 2. Build the offline bundle (connected side)

```bash
git clone <internal repo>/ppt2kb && cd ppt2kb
scripts/build-offline-bundle.sh --python 3.12 --arch x86_64 --out dist
#  -> dist/ppt2kb-1.1.0-offline-py3.12-x86_64.tar.gz  (+ SHA256SUMS)
```

Use `--python 3.11` for Debian 12 servers, `--python 3.12` for Ubuntu 24.04 /
RHEL 9 (python3.12), `--arch aarch64` for ARM servers. The bundle contains all
wheels (application + pinned dependencies + pip), the installer, the systemd
unit, example config, docs, the SBOM and the mock services. Transfer the
tarball and `SHA256SUMS` to the target server.

## 3. Install (target server, as root)

```bash
sha256sum -c SHA256SUMS                                  # verify the transfer
tar xzf ppt2kb-1.1.0-offline-py3.12-x86_64.tar.gz
cd ppt2kb-1.1.0-offline-py3.12-x86_64
sudo deploy/standalone/install.sh                        # options: --prefix --data-dir --conf-dir --user --python --no-systemd
```

The installer is idempotent: it creates the `ppt2kb` system user, the
directories (0750), the virtualenv (`pip install --no-index --find-links wheelhouse`),
`/etc/ppt2kb/ppt2kb.env` (from the example, only if absent), `start.sh`/`stop.sh`,
and enables `ppt2kb.service`. It never contacts the network.

## 4. Configure

```bash
sudo vi /etc/ppt2kb/ppt2kb.env           # Qwen, ServiceNow, CA bundle, allowed hosts, port
sudo cp internal-ca-chain.pem /etc/ppt2kb/ca.pem && sudo chmod 644 /etc/ppt2kb/ca.pem
```

`ppt2kb.env` is `root:ppt2kb 0640` — it is the only place where credentials
live. Full reference: `docs/CONFIGURATION.md`.

## 5. Start / stop / status

```bash
sudo systemctl start ppt2kb          # enabled at boot by the installer
sudo systemctl status ppt2kb
sudo journalctl -u ppt2kb -f         # logs (credentials and slide content are never logged)
sudo systemctl stop ppt2kb
```

Without systemd: `/opt/ppt2kb/start.sh` (foreground) or `/opt/ppt2kb/start.sh --daemon`
and `/opt/ppt2kb/stop.sh` (pid file in the data dir, log in `/var/log/ppt2kb/`).

The unit file applies resource limits (`MemoryMax=6G`, `TasksMax=512`,
`CPUQuota=400%`) and hardening (`ProtectSystem=strict`, `NoNewPrivileges`,
`PrivateTmp`, no capabilities, syscall filter). Adjust `MemoryMax` for very
large decks.

## 6. Verify

```bash
curl -s http://127.0.0.1:8080/api/health
# UI: http://<server>:8080/  -> Settings -> "Test connection" for Qwen and ServiceNow
```

For an offline functional test without the real endpoints, run the bundled
mocks on the same server (`python -m mocks.mock_qwen --port 9001`,
`python -m mocks.mock_servicenow --port 9002` using `/opt/ppt2kb/venv/bin/python`)
and point `PPT2KB_QWEN_BASE_URL=http://127.0.0.1:9001/v1`,
`PPT2KB_SERVICENOW_URL=http://127.0.0.1:9002` (admin/admin) at them.

## 7. Upgrade

```bash
sudo systemctl stop ppt2kb
tar xzf ppt2kb-1.1.0-offline-py3.12-x86_64.tar.gz && cd ppt2kb-1.1.0-offline-py3.12-x86_64
sudo deploy/standalone/install.sh        # reinstalls the venv from the new wheelhouse, keeps /etc/ppt2kb/ppt2kb.env and data
sudo systemctl start ppt2kb
```

Compare `/etc/ppt2kb/ppt2kb.env.example` (always refreshed) with your
`ppt2kb.env` for new settings. The SQLite schema is created/extended
automatically at startup (`CREATE TABLE IF NOT EXISTS`); take a backup of
`/var/lib/ppt2kb` before upgrading.

Roll back: install the previous bundle the same way.

## 8. Uninstall

```bash
sudo deploy/standalone/uninstall.sh /opt/ppt2kb           # keeps data + config
sudo deploy/standalone/uninstall.sh /opt/ppt2kb --purge   # removes everything incl. the user
```

## 9. Reverse proxy

Keep `PPT2KB_HOST=127.0.0.1` and publish the UI through nginx/Apache with TLS
and SSO (`proxy_pass http://127.0.0.1:8080; client_max_body_size 250m;
proxy_read_timeout 600;`). Set `PPT2KB_HOST=0.0.0.0` only if the server itself
is the endpoint users connect to (then enable Basic auth).
