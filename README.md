# ppt2kb — Secure on-premise PowerPoint → ServiceNow Knowledge

ppt2kb turns a PowerPoint presentation into a reviewable **ServiceNow Knowledge
article (Draft)**: every slide is rendered to an image and explained by your
internal **Qwen Vision** model as a technical knowledge section (purpose,
components, procedures, key facts — not a description of how the slide
looks); the pictures and screenshots embedded in the PPTX are extracted,
filtered conservatively, previewed, and attached with meaningful file names
(`004_משואה_750.png`, `004_משואה_750_image_01.png`) in one of three image output
modes chosen per presentation (embedded images only / embedded images + full
slides / full slides only); everything is reviewed/edited
in an internal web UI (answers that fail validation are held for review) and
then published as a draft. It is built on
[ppt2desc](https://github.com/ALucek/ppt2desc) (MIT) and hardened for a closed
enterprise network: no cloud SDKs, no telemetry, an outbound-host allow-list,
isolated document conversion, and two deployment options built from the same
code base (Docker image, or a standalone Linux service).

```
 Browser ──► ppt2kb (FastAPI + static UI)
                │
                ├─► LibreOffice (headless, isolated process)  PPT/PPTX → PDF
                ├─► pdfium (in-process)                        PDF → PNG per slide
                ├─► python-pptx (in-process)                   PPTX → embedded pictures (PNG/JPEG, crops, groups)
                ├─► Qwen Vision API  (internal, OpenAI-compatible)   slide image + PPTX text → technical explanation (JSON)
                ├─► quality validation                          retry with correction → needs-review queue
                └─► ServiceNow Table + Attachment API (internal)      kb_knowledge draft + embedded images (or full slides)
```

## Release packages (v1.1.2)

| Package | What it is | Guide |
|---|---|---|
| `PPT2KB-Setup.exe` | Self-contained Windows 10/11 x64 installer: embedded Python, the application, LibreOffice headless + fonts. Install → desktop shortcut → browser UI on 127.0.0.1. No Python/Docker/LibreOffice needed on the PC. | [docs/INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md) |
| `ppt2kb-web-offline.tar` | Pre-built OCI/Docker image (`ppt2kb:1.1.2`) for the internal container host: `docker load`, configure `.env`, `docker compose up -d`. | [docs/DEPLOY_DOCKER_OFFLINE.md](docs/DEPLOY_DOCKER_OFFLINE.md) |
| `ppt2kb-1.1.2-offline-py3.1x-x86_64.tar.gz` | Linux standalone service (no Docker) with all wheels, systemd unit and installer. | [docs/INSTALL_STANDALONE.md](docs/INSTALL_STANDALONE.md) |
| `ppt2kb-1.1.2-src.tar.gz` | Complete source, tests, build scripts, SBOM. Rebuild any package with [docs/BUILD_REPRODUCIBLE.md](docs/BUILD_REPRODUCIBLE.md). | |

All packages are built from this code base and provide the same UI and
functionality. `SHA256SUMS` accompanies every delivery.

| Document | Purpose |
|---|---|
| [docs/INSTALL_WINDOWS.md](docs/INSTALL_WINDOWS.md) | Windows desktop edition – install, configure, validate offline, uninstall |
| [docs/DEPLOY_DOCKER_OFFLINE.md](docs/DEPLOY_DOCKER_OFFLINE.md) | Importing and running the pre-built image (exact commands: import, configure, start, stop, update) |
| [docs/BUILD_REPRODUCIBLE.md](docs/BUILD_REPRODUCIBLE.md) | Reproducing both packages from source (for the security team) |
| [docs/INSTALL_DOCKER.md](docs/INSTALL_DOCKER.md) | Building the image yourself, Compose reference, offline image transfer |
| [docs/INSTALL_STANDALONE.md](docs/INSTALL_STANDALONE.md) | Linux service without Docker (installer, systemd, upgrade) |
| [docs/AIRGAP.md](docs/AIRGAP.md) | Preparing and transferring artifacts into the air-gapped network |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | Every setting (Qwen, ServiceNow, TLS, limits, prompts) |
| [docs/SERVICENOW.md](docs/SERVICENOW.md) | ServiceNow (Zurich) integration details, required roles, instance configuration |
| [docs/SECURITY_REVIEW.md](docs/SECURITY_REVIEW.md) | Security review of ppt2desc, findings, mitigations, remaining risks |
| [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) | Test suite, what was executed, results, what was not verified |
| [docs/DECISIONS.md](docs/DECISIONS.md) | Implementation decisions and how to extend (topic-based splitting etc.) |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Using the web UI (English / עברית) |
| [sbom/](sbom/) | CycloneDX SBOM, dependency inventory with licenses, vulnerability scan |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | Attribution (ppt2desc, LibreOffice, fonts, Python packages) |

## Quick start (evaluation on one Linux machine, with the mock services)

Prerequisites: Python ≥ 3.11, LibreOffice (`soffice`), Hebrew + Latin fonts.
`deploy/standalone/check-prereqs.sh` tells you what is missing.

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -e .            # or: pip install --no-index --find-links wheelhouse ...
# start the mocks (replace with your real endpoints later)
python -m mocks.mock_qwen --port 9001 &          # OpenAI-compatible vision endpoint
python -m mocks.mock_servicenow --port 9002 &    # kb_knowledge + attachment API, user admin/admin
export PPT2KB_DATA_DIR=./data PPT2KB_PORT=8080 \
       PPT2KB_QWEN_BASE_URL=http://127.0.0.1:9001/v1 PPT2KB_QWEN_MODEL=mock \
       PPT2KB_SERVICENOW_URL=http://127.0.0.1:9002 PPT2KB_SERVICENOW_USERNAME=admin PPT2KB_SERVICENOW_PASSWORD=admin
ppt2kb                                            # open http://127.0.0.1:8080/
```

Upload a `.pptx`, watch the per-slide progress, edit the generated text, pick a
knowledge base and click **Create draft article**. The result shows the article
number (`KB0001001`) and links. With the mock, `http://127.0.0.1:9002/_mock/articles`
shows what was created.

## Production configuration in three lines

Everything is configured through `PPT2KB_*` environment variables (or the env
file). The minimum for a real deployment:

```
PPT2KB_QWEN_BASE_URL=https://qwen.internal/v1      PPT2KB_QWEN_MODEL=Qwen2.5-VL-72B-Instruct   PPT2KB_QWEN_API_KEY=...
PPT2KB_SERVICENOW_URL=https://servicenow.internal  PPT2KB_SERVICENOW_USERNAME=svc_ppt2kb        PPT2KB_SERVICENOW_PASSWORD=...
PPT2KB_CA_BUNDLE=/etc/ppt2kb/ca.pem                PPT2KB_ALLOWED_OUTBOUND_HOSTS=qwen.internal,servicenow.internal
```

See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for the full reference and
`deploy/docker/.env.example` / `deploy/standalone/config.env.example` for
complete sample files (no real credentials).

## Repository layout

```
src/ppt2kb/            application package
  app.py               FastAPI factory, auth/security middleware, startup checks
  desktop.py           Windows desktop launcher (start server, open browser, --stop)
  api.py               REST API used by the UI
  config.py            settings (PPT2KB_* environment variables)
  runtime.py           effective config = env + UI overrides (secrets stay in memory)
  converters/          PPT→PDF (LibreOffice, sandboxed) and PDF→PNG (pdfium)   [from ppt2desc]
  llm/qwen.py          OpenAI-compatible vision client with retries/limits     [from ppt2desc]
  pipeline/            job runner: convert → describe → persist, resume, retry [from ppt2desc]
  servicenow/          Table/Attachment API client and the idempotent publisher
  export/html.py       article HTML (escaped, RTL aware) and standalone HTML export
  security/            upload validation (magic bytes, ZIP bomb, traversal), outbound allow-list
  storage/db.py        SQLite persistence (jobs, slides, settings)
  web/static/          UI (vanilla JS, EN/HE, RTL) – no build step, no external assets
  cli.py               batch CLI (ppt2desc-style JSON output)
mocks/                 mock Qwen and mock ServiceNow services (tests + offline POC)
tests/                 pytest suite incl. 60-slide end-to-end scenario
deploy/docker/         Dockerfile, docker-compose.yml, .env.example, entrypoint
deploy/standalone/     install.sh, systemd unit, start/stop, config example
deploy/windows/        NSIS installer script, launcher source, build-windows.sh, config template, tools
scripts/               build-image, export/import-image, build-offline-bundle
sbom/                  CycloneDX SBOM, dependency inventory, pip-audit result
docs/                  documentation
```

## Command line

```bash
ppt2kb                       # web application (reads PPT2KB_* variables)
ppt2kb-cli --input deck.pptx --output_dir out --save-images --html   # batch mode, ppt2desc-compatible JSON
python -m pytest             # test suite (needs LibreOffice; mocks start automatically)
```

## License

MIT — see `LICENSE`. Includes code from ppt2desc © 2025 Adam Łucek (MIT,
`LICENSE.ppt2desc`). Third-party components: `THIRD_PARTY_NOTICES.md`.
