# Air-gapped deployment — preparing and transferring artifacts

ppt2kb needs **no internet at runtime**. The only network destinations are the
internal Qwen Vision endpoint and the internal ServiceNow instance, both
explicitly configured. This document is the repeatable process for producing
the installation artifacts on a connected (or mirror-connected) build host and
moving them into the closed network.

## What has to cross the boundary

| Artifact | Produced by | Used for |
|---|---|---|
| `ppt2kb-<ver>-image.tar.gz` + `SHA256SUMS` | `scripts/build-image.sh` + `scripts/export-image.sh` | Option A (Docker) |
| `ppt2kb-<ver>-offline-py<X.Y>-<arch>.tar.gz` + `SHA256SUMS` | `scripts/build-offline-bundle.sh` | Option B (standalone) |
| OS packages: python3(+venv), LibreOffice, fonts | enterprise OS mirror (already inside) | Option B hosts |
| `deploy/`, `docs/`, `sbom/` | repository | configuration, review |
| Internal CA chain (PEM) | PKI team | TLS to Qwen / ServiceNow |

The source repository itself can also be transferred (it is small); building
inside the closed network then only needs an internal PyPI mirror (for wheels)
and the OS mirror (for LibreOffice) — or the wheelhouse from the bundle
(`deploy/docker/wheelhouse/`, `pip install --no-index`).

## Step-by-step

### 1. Build host (connected)

```bash
git clone <repo> ppt2kb && cd ppt2kb && git checkout v1.1.0
python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt -e ".[dev]"
python -m pytest                              # must be green (needs LibreOffice locally)
pip-audit -r requirements.txt                 # must be clean; refresh sbom/ if versions changed
scripts/build-image.sh ppt2kb:1.1.0           # Option A
scripts/export-image.sh ppt2kb:1.1.0 dist
scripts/build-offline-bundle.sh --python 3.12 --arch x86_64 --out dist    # Option B (repeat per target Python)
ls dist/ && cat dist/SHA256SUMS
```

### 2. Transfer

Move `dist/` through the approved transfer mechanism (data diode, scanned
media, transfer gateway). Transfer `SHA256SUMS` separately (e.g. by e-mail or
ticket) so the integrity check is independent of the payload.

### 3. Target side

```bash
sha256sum -c SHA256SUMS                                       # all OK
# Option A
scripts/import-image.sh ppt2kb-1.1.0-image.tar.gz             # docker load
# Option B
tar xzf ppt2kb-1.1.0-offline-py3.12-x86_64.tar.gz
sudo ppt2kb-1.1.0-offline-py3.12-x86_64/deploy/standalone/install.sh
```

Then configure (`docs/INSTALL_DOCKER.md` §3 / `docs/INSTALL_STANDALONE.md` §4)
and verify (**Settings → Test connection** in the UI, or
`curl -X POST http://127.0.0.1:8080/api/config/test/qwen`).

## Runtime network policy (what to allow on the firewall)

| Direction | Source | Destination | Port | Purpose |
|---|---|---|---|---|
| out | ppt2kb host/container | Qwen API host | 443 (or as configured) | slide analysis |
| out | ppt2kb host/container | ServiceNow instance | 443 | knowledge article + attachments |
| in | users / reverse proxy | ppt2kb | 8080 (configurable) | web UI |

Everything else can be denied. The application additionally enforces this
itself (`PPT2KB_ALLOWED_OUTBOUND_HOSTS`), ignores proxy environment variables
and starts LibreOffice with networking variables cleared. The UI loads no
external resources (CSP `default-src 'self'`).

## Verifying "no internet at runtime"

1. Start the application with the firewall/egress rules in place (or in a
   network namespace without a default route) and the mock services on
   localhost; process a presentation and create a draft on the mock ServiceNow.
   The automated suite does exactly this: the test environment's proxy
   variables are ignored (`test_outbound_ignores_proxy_env`) and any request to
   a host outside the allow-list is refused before a socket is opened
   (`test_outbound_allowlist_blocks_unknown_hosts`).
2. Optionally run `tcpdump -i any 'not host <qwen> and not host <servicenow> and not port 8080'`
   on the host during a full run — it should stay empty apart from DNS for
   the two configured names.

## Updating in the air-gapped network

Repeat the build on the connected side for the new version, transfer, and
follow the upgrade sections of the two install guides. Keep the previous
image/bundle for rollback. OS-level patches (LibreOffice, fonts, Python)
continue to come from the enterprise mirror on the standalone hosts; for the
container they are included in a new image build.
