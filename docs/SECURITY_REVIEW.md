# Security review and remediation summary

Scope: the upstream repository `ALucek/ppt2desc` (commit `695d6462`, 2025-11-11),
its dependencies and container files, and the extended application (ppt2kb 1.0.0).
Method: manual review of every source file, dependency inventory and license
check, `pip-audit` vulnerability scan, threat-model driven hardening, and
automated tests for each control (see `tests/test_security.py`).

Status legend: **Fixed** = mitigated in code and covered by a test; **Mitigated**
= reduced by configuration/documentation; **Open** = remaining risk, see §6.

## 1. Findings in the upstream project (ppt2desc)

| # | Finding | Severity | Status in ppt2kb |
|---|---|---|---|
| U1 | Depends on six cloud SDKs (`openai`, `anthropic`, `boto3`, `google-cloud-aiplatform`, `google-generativeai`, `grpcio`, …). Each contains credential discovery (env vars, `~/.aws`, GCE metadata server `169.254.169.254`) and/or usage telemetry (`google-api-core` client-info headers, `grpcio` channelz). Slide content is sent to public cloud endpoints by design. | High (for on-prem) | **Fixed** – all cloud SDKs removed; only `httpx` against the configured internal Qwen URL. 25 runtime packages instead of ~55. |
| U2 | `src/llm/openai.py` hard-codes the OpenAI SDK default base URL (`api.openai.com`); no way to pin an internal endpoint with custom CA. | High | **Fixed** – `QwenClient` takes base URL, auth header/scheme, CA bundle, client certificate; outbound allow-list refuses anything else (`AllowListTransport`). |
| U3 | Credentials accepted on the command line (`--api_key`, `--azure_openai_api_key`) → visible in `ps`, shell history and process listings. | Medium | **Fixed** – credentials only from environment/env file (mode 0640) or typed in the UI (memory only, never echoed back). |
| U4 | `PyMuPDF` (`pymupdf`) is **AGPL-3.0** (or commercial). Linking it into an internal application creates a copyleft obligation that many enterprises forbid. | Medium (legal) | **Fixed** – replaced by `pypdfium2` (BSD-3/Apache-2.0, bundles Google pdfium). |
| U5 | `docker_converter.py` sends the entire presentation to an HTTP service (`http://localhost:2002`) with `requests` honouring `HTTP_PROXY`; the LibreOffice container (`src/libreoffice_docker/app.py`) writes the uploaded file under its **original name** into a temp dir (`input_path = temp_path / file.filename`) → path traversal (`../../`) and shell-metacharacter exposure. | High | **Fixed** – component removed. Conversion is in-process (subprocess) and the input is copied to a random UUID file name in a private directory. |
| U6 | LibreOffice invoked with the user profile of the service account, macros at default security level, no timeout, no resource limits; `subprocess.run(check=True, capture_output=True)` without `timeout`. A malicious or huge file can hang the process or exhaust memory. | High | **Fixed** – `-env:UserInstallation` throw-away profile with macros disabled (`MacroSecurityLevel=3`, `DisableMacrosExecution`), `--norestore --nolockcheck`, wall-clock timeout, `RLIMIT_AS`/`RLIMIT_CPU`/`RLIMIT_NPROC`/`RLIMIT_CORE`, process-group kill, minimal environment with proxies cleared. Test: `test_conversion_timeout_kills_process`. |
| U7 | No input validation: any file with `.ppt/.pptx` suffix is processed; no size limit; no ZIP-bomb protection (a PPTX is a ZIP container). | High | **Fixed** – magic bytes, OOXML content-type check, entry count / uncompressed size / compression-ratio limits, member path checks, upload size cap enforced while streaming. Tests: 12 cases in `test_security.py`. |
| U8 | `logger.error(..., exc_info=True)` and `f"... {e.stderr}"` log raw exception/stderr content, which for the OpenAI SDK includes request details; `tqdm` progress output to stdout. | Medium | **Fixed** – redacting log filter (api keys, passwords, bearer/basic tokens, base64 image data), error messages never include response bodies, slide content is never logged. Test: `test_log_redaction_masks_secrets`. |
| U9 | Partial results written as plain JSON next to the output (`slides_partial.json`) with no access control; images copied into the output directory. | Low | **Mitigated** – all data under one `PPT2KB_DATA_DIR` (0750, service user only); retention cleanup; delete-job endpoint removes files. |
| U10 | `docker-compose.yml` exposes the converter on `0.0.0.0:2002` with no authentication; health check uses `curl`. | Medium | **Fixed** – component removed; new image is non-root, read-only FS, `cap_drop ALL`, `no-new-privileges`, bind address configurable (default loopback in Compose). |
| U11 | Dependencies pinned to late-2024 versions (`certifi 2024.12`, `pillow 11.0.0`, `urllib3 2.3.0`, `requests 2.32.3`, …) with multiple published CVEs. | Medium | **Fixed** – fresh pins, `pip-audit` clean (see §3). |
| U12 | No tests for the security-relevant code paths; CLI tests only. | Low | **Fixed** – 52 automated tests, 24 of them security controls. |
| U13 | License/attribution: MIT license present and preserved. No NOTICE file for third-party components. | Info | **Fixed** – `LICENSE.ppt2desc`, `THIRD_PARTY_NOTICES.md`, `sbom/DEPENDENCY_INVENTORY.md`. |

No hard-coded credentials, no analytics/tracking code and no unexpected
external URLs were found in the upstream source itself (only
`https://www.googleapis.com/auth/cloud-platform` as an OAuth scope string in
the Vertex client, which was removed).

## 2. Findings in the new dependency set

| # | Finding | Status |
|---|---|---|
| D1 | **FastAPI ≥ 0.160 bundles OpenTelemetry instrumentation** (`fastapi/telemetry/`). It pulls `opentelemetry-api` and, when `FASTAPI_OTEL_AUTO_CONFIGURE=true`/`OTEL_EXPORTER_OTLP_ENDPOINT` are set *and* the SDK/exporter packages are installed, would export traces/metrics/logs over HTTP. | **Fixed** – `FastAPI(telemetry={tracing/metrics/logs/operation_spans/auto_configure: False})` in `app.py`; `OTEL_SDK_DISABLED=true` set by the entrypoint, the systemd unit and Compose; the SDK/exporter packages are **not** installed (API package is a no-op). Verified: `app._telemetry` shows everything disabled. |
| D2 | `certifi` ships the Mozilla public CA bundle. Not a leak, but internal services use the enterprise CA. | **Mitigated** – `PPT2KB_CA_BUNDLE` is used for all outbound TLS; certifi is only the fallback when no bundle is configured. |
| D3 | `pip-audit` on the first pin set reported 39 advisories for `pillow 12.3.0` and 1 for `opentelemetry-api 1.45.0`. | **Fixed** – upgraded to `pillow 13.0.0` and `opentelemetry-api 1.45.2`; rescan: *No known vulnerabilities found* (`sbom/pip-audit.txt`). |
| D4 | `python-pptx` parses attacker-controlled XML with `lxml`. | **Mitigated** – only run after the ZIP-bomb/traversal checks; failures are non-fatal (the slide image is authoritative); lxml's default parser has entity expansion disabled (`resolve_entities` false for `XMLParser` used by python-pptx since 1.0). |
| D5 | `uvicorn` server header reveals version. | **Fixed** – `server_header=False`, `date_header=False`, access log disabled (would contain file names). |

## 3. Dependency audit and SBOM

* `sbom/ppt2kb-sbom.cdx.json` – CycloneDX 1.6 SBOM of the 25 runtime packages (`cyclonedx-py requirements`).
* `sbom/DEPENDENCY_INVENTORY.md` – table with version, license, purpose, source URL, plus system packages (LibreOffice MPL-2.0, fonts OFL/GPL-font-exception, tini MIT).
* `sbom/pip-audit.txt` / `pip-audit.json` – vulnerability scan result at build time (clean).
* Licensing: all Python packages are permissive (MIT/BSD/Apache/MPL-2.0/PSF). No GPL/AGPL Python code. Culmus fonts are GPL-2 with the font-embedding exception (output documents are not affected).

Re-run before every release: `pip-audit -r requirements.txt` and `cyclonedx-py requirements requirements.txt --of JSON -o sbom/ppt2kb-sbom.cdx.json`.

## 4. Controls implemented in ppt2kb (threat model → control → test)

| Threat | Control | Test |
|---|---|---|
| Data exfiltration to the internet | `AllowListTransport`: every outbound request must target a host in `PPT2KB_ALLOWED_OUTBOUND_HOSTS` (or the configured Qwen/ServiceNow hosts); `trust_env=False` (proxy variables ignored); redirects not followed; UI cannot set URLs outside the allow-list when it is locked. LibreOffice runs with proxies unset and `NO_PROXY=*`. No CDN/fonts/analytics in the UI (CSP `default-src 'self'`). | `test_outbound_allowlist_blocks_unknown_hosts`, `test_outbound_ignores_proxy_env`, `test_outbound_no_redirect_follow`, `test_config_rejects_non_allowlisted_hosts` |
| Malicious PowerPoint (bomb, traversal, macros, spoofed type) | `security/upload_validation.py` + isolated LibreOffice (U6/U7) + page limit (`PPT2KB_MAX_SLIDES`) | 12 upload tests, `test_conversion_page_limit`, `test_conversion_timeout_kills_process` |
| Prompt injection via slide content | System prompt declares slide content as data; model output is parsed as data only (JSON fields), never executed, never used to build URLs or commands; HTML is generated by escaping text into a fixed tag set. | `test_prompt_treats_slide_as_data`, `test_text_to_html_escapes_and_lists`, e2e asserts no `<script` in article |
| Hallucination | Prompt forbids inventing steps/values; `uncertainties` field; original PPTX text is passed as a reference (capped at 4 kB); human review before any article is created; article stays in Draft. | — (human process) |
| Credential leakage | Secrets from env/env-file only; UI secrets kept in memory (`PPT2KB_PERSIST_UI_SECRETS=false` default); API never returns secrets; redacting log filter; error texts exclude response bodies. | `test_secrets_never_returned`, `test_log_redaction_masks_secrets`, `test_wrong_api_key_marks_slides_failed` (asserts the key is not in the error) |
| Path traversal / IDOR in the API | Job ids are 32-hex UUIDs validated by regex; images served only from the job's own directory after `resolve()` containment check; display names sanitised and never used in paths. | `test_image_path_traversal_blocked`, `test_display_name_sanitized` |
| Unauthenticated access | Optional HTTP Basic auth (`PPT2KB_UI_USERNAME/PASSWORD`, constant-time compare); recommended: reverse proxy with SSO in front; bind to loopback by default. | `test_basic_auth_required_when_configured` |
| Browser-side attacks (XSS, clickjacking, MIME sniffing) | CSP, `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`; UI renders model text via `textContent`/textarea; preview HTML is server-escaped. | `test_security_headers` |
| Loss of work / partial failure | Per-slide state in SQLite; resume after crash; retry single slides; idempotent publishing with local + remote duplicate detection; attachment reuse. | `test_interrupted_processing_is_resumed`, `test_partial_failure_and_single_slide_retry`, `test_publish_partial_failure_recovery`, `test_duplicate_detection_after_local_state_loss` |
| Privilege escalation on the host | Non-root user (uid 10001) in the image; read-only root FS, `cap_drop: ALL`, `no-new-privileges`, pids limit; systemd unit with `ProtectSystem=strict`, `NoNewPrivileges`, `PrivateTmp`, `CapabilityBoundingSet=`, syscall filter, memory/task limits. | manual (`systemd-analyze verify` passed) |
| TLS downgrade | `PPT2KB_TLS_VERIFY=false` is possible for lab use only, logged at CRITICAL at startup and on every client creation; minimum TLS 1.2; custom CA bundle and mTLS client certificates supported. | — |

## 4a. Changes in v1.1 (embedded image extraction, quality validation)

| Area | Control | Test |
|---|---|---|
| New parsing surface: embedded pictures read from the PPTX with `python-pptx` and Pillow | Runs on the already validated ZIP (U1–U5 checks, size/slide limits); parts are read through `python-pptx`'s package API (no path handling from ZIP entry names); Pillow decodes only raster blobs (PNG/JPEG/GIF/BMP/TIFF/WebP) and refuses, from the header alone, any picture above 40 M pixels (`MAX_EMBEDDED_PIXELS`, decompression-bomb guard; below Pillow's own 89 M limit); vector formats (EMF/WMF/SVG), OLE and other parts are never decoded — they are reported as *unsupported*; extraction stops at `PPT2KB_MAX_SLIDES`; a failing picture is skipped with a note, never aborting the job; untransformed PNG/JPEG blobs are stored byte-for-byte, transformed ones re-encoded as PNG (no metadata/EXIF is interpreted). Output files are written with fixed names under the job directory (`images/emb/s003_02.png`); the reviewer-facing names are generated by `export/filenames.py` and never used as paths. | `test_extraction_covers_all_cases`, `test_decorative_filtering_is_conservative`, `test_oversized_embedded_picture_is_reported_not_decoded`, upload-validation suite (unchanged) |
| Attachment file names derived from slide titles | `sanitize_title()` keeps only Hebrew/Latin letters, digits, `-`, `_` (NFC-normalised), caps length, de-duplicates; `/`, `\`, `..`, control and bidi-override characters cannot appear in a name. Names are sent as the `file_name` query parameter (URL-encoded by httpx) of the Attachment API — never written to the local file system. | `test_embedded_mode_end_to_end`, `test_mode_setting_is_persistent_and_ascii_filenames` |
| Model output used in HTML | Unchanged escaping path: all text goes through `html.escape`; the fixed tag set gained `strong`, `ul`, `figure` only; `alt` attributes are escaped; model text never reaches an attribute other than escaped `alt`. The new single-section preview uses the same renderer. | `test_text_to_html_escapes_and_lists`, `test_rtl_and_structure_in_html`, e2e asserts no `<script` |
| Quality validation / prompt corrections | Validation is pure Python over the parsed answer; corrective hints are fixed strings — nothing from the model is fed back as instructions, only the slide's own reliable text is re-sent. Slides failing validation are `needs_review` and block publishing (HTTP 409); acceptance is an explicit reviewer action (`POST …/accept`). | `test_visual_description_is_rejected_and_retried`, `test_persistently_bad_answers_need_review`, `test_validation_rules` |
| ServiceNow write scope | The publisher creates/updates only articles carrying its own job marker; attachments are matched by stored `sys_id`/name and reused; the tool issues no DELETE against the instance (the client's `delete_attachment` exists but is unused by the publisher). | `test_embedded_publish_partial_failure_recovery`, `test_duplicate_detection_after_local_state_loss` |
| New API endpoints (`GET/PATCH …/images/{idx}`, `POST …/accept`, `POST …/images/extract`, `GET preview.html?slide=N`) | Same job-id regex and Basic-auth gate; image bytes served only from the job's own directory after the existing containment check; `idx` is an integer bound to the job's rows; extraction endpoint refuses while the job is processing. | e2e tests above, `test_image_path_traversal_blocked` |

No new outbound destinations, no new dependencies (python-pptx and Pillow were
already in the SBOM), no change to the CSP (`default-src 'self'`): thumbnails
are served by the application itself.

## 5. Data handling

* Uploaded presentations, rendered slide images, extracted text and generated
  descriptions are stored under `PPT2KB_DATA_DIR` (SQLite + files). Treat this
  directory with the same classification as the presentations.
* Data leaves the host only to the Qwen endpoint (slide image + extracted text
  + prompt) and to ServiceNow (article HTML + images + optionally the PPTX).
* Retention: jobs older than `PPT2KB_RETENTION_DAYS` (default 30) are deleted at
  startup; users can delete a job at any time from the UI.
* Logs contain job ids, slide numbers, status and HTTP status codes — not slide
  content and not credentials.

## 6. Remaining risks and recommendations

1. **Qwen endpoint and ServiceNow are trusted by design.** The application sends
   slide content to them; their own access control and logging are out of scope.
2. **LibreOffice parsing is the largest attack surface** (C++ code processing
   untrusted files). The process is isolated with rlimits and a throw-away
   profile, but not with a kernel sandbox. Recommended for high-assurance
   deployments: run the container with a seccomp/AppArmor profile (Docker's
   default seccomp profile applies), keep LibreOffice patched through the OS
   mirror, and consider `PPT2KB_MAX_UPLOAD_MB` tuned to real needs.
3. **The web UI has no per-user authorization** – everyone who can reach it can
   see all jobs. Put it behind the enterprise reverse proxy / SSO and restrict
   network access to the knowledge-management team. Basic auth is available as
   a minimum.
4. **Model output quality** is not a security control: hallucinations are
   mitigated by prompt design and mandatory human review, not eliminated.
5. **Macro-enabled files** (`.pptm`/VBA inside PPTX) are flagged in the UI
   (`⚠ macro-enabled file`); macros are disabled in LibreOffice, but you may
   prefer to reject them entirely (set an upload policy at the proxy or extend
   `validate_presentation`).
6. **Secrets typed in the UI are lost on restart** unless
   `PPT2KB_PERSIST_UI_SECRETS=true`, in which case they are stored in clear in
   the SQLite database (protected only by file permissions). Prefer the env file.
7. The Windows package was validated under **Wine on Linux** (installer,
   launcher, conversion, DPAPI, uninstall) and not yet on a physical/virtual
   Windows 11 machine — run `tools\validate-offline.ps1` on your clean VM
   (see §9 and `docs/TEST_RESULTS.md`).

## 7. Verification checklist for the enterprise security review

- [ ] `pip-audit -r requirements.txt` clean at release time
- [ ] SBOM attached to the change record (`sbom/ppt2kb-sbom.cdx.json`)
- [ ] `PPT2KB_ALLOWED_OUTBOUND_HOSTS` set; egress firewall allows only those hosts
- [ ] `PPT2KB_TLS_VERIFY=true`, `PPT2KB_CA_BUNDLE` points to the internal CA chain
- [ ] UI behind SSO/reverse proxy or Basic auth enabled; bind address restricted
- [ ] Service account in ServiceNow limited to the roles in `docs/SERVICENOW.md`
- [ ] Data directory permissions 0750, owned by the service user; retention set
- [ ] Container: non-root, read-only, `cap_drop: ALL` (as in the provided Compose file)

## 8. Final packages (v1.0.0) — packaging review

### 8.1 `ppt2kb-web-offline.tar` (OCI image, built with buildah)

* Base `python:3.12-slim-bookworm` (Debian 12, Python 3.12.16); 256 Debian
  packages (`sbom/docker-image-debian-packages.tsv`), LibreOffice 7.4.7
  (Debian LTS build with security backports, `1+deb12u14`), fonts, `tini`.
  Image digest `sha256:9f166cfa…061b90`, 5 layers, 617 MB.
* Runs as uid 10001; pip/setuptools removed from the venv (no package
  installation possible inside the container); no shell tricks in the
  entrypoint beyond validating `/data` and clearing proxy variables.
* Build-time proxy/CA arguments (`BUILD_PROXY`, `BUILD_CA_FILE`) exist for
  enterprise build hosts; they are consumed in the same `RUN` layer and removed,
  verified by inspecting the final layer (no `/etc/apt/apt.conf.d/99build-*`,
  no CA file; the mirror URL is reset to the default).
* Found and fixed by actually building: `groupadd`/`useradd` were not on the
  restricted `PATH` of the runtime stage (build failed at that step) — now
  called with absolute paths.
* Tested: container started as the non-root user with a mounted volume,
  processed the 60-slide deck with the in-image LibreOffice, published to the
  mock ServiceNow (60 attachments). See `docs/TEST_RESULTS.md` §B.

### 8.2 `PPT2KB-Setup.exe` (Windows 10/11 x64)

| Component | Origin / verification | Notes |
|---|---|---|
| CPython 3.13.17 embeddable (amd64) | python.org, SHA-256 pinned in `deploy/windows/components.sha256` | latest 3.13 with Windows binaries; `._pth` restricts `sys.path` to the bundle (no user site, no cwd) |
| Python packages | same `requirements.txt` as the server edition; `win_amd64`/`abi3` wheels from PyPI, `pip-audit` clean | identical versions in both deployments |
| LibreOffice 25.8.7 (Windows x86-64) | TDF MSI, SHA-256 pinned, **GPG signature verified** (key `C283 9ECA D940 8FBE 9531 C3E9 F434 A1EF AFEE AEA3`) | extracted with `msiextract`, trimmed (no Java, no bundled Python 3.11, no extensions/dictionaries/galleries/templates/help; en-US + Hebrew). Still the largest attack surface (C++ parser of untrusted files); runs with a throw-away profile, macros disabled, inside a Windows **Job Object** (memory limit, active-process limit, kill-on-close), minimal environment, no proxy, hidden window |
| VC++ runtime DLLs | the merge modules inside the LibreOffice MSI | kept private in the install folder (no system-wide redistributable install, no admin rights needed) |
| `PPT2KB.exe` launcher | `deploy/windows/launcher/ppt2kb_launcher.c`, MinGW | 55 kB, no network, no registry, `asInvoker` manifest; starts `pythonw.exe -B -s -m ppt2kb.desktop` with NUL std handles |
| Installer | NSIS 3.09 (`deploy/windows/ppt2kb.nsi`) | per-user (`%LOCALAPPDATA%\Programs\PPT2KB`, no UAC) or per-machine; one Add/Remove-Programs registry key; shortcuts; no services, no PATH or file-association changes; `/S` silent; uninstaller removes everything except the data folder (asks interactively) |

Runtime behaviour on Windows: the server binds to `127.0.0.1` only
(`PPT2KB_HOST` is fixed in the template), data in the user profile
(`%LOCALAPPDATA%\PPT2KB`), configuration in `<install>\config\ppt2kb.env`
(template ships with **empty** credentials and URLs), UI-entered secrets stored
with **DPAPI (current user, local machine)** — verified: the SQLite value is a
`dpapi:` blob and the plain text does not appear in the database. The
`/api/shutdown` endpoint used by *Stop PPT2KB* is only enabled in desktop mode
and only for loopback clients (tests `test_shutdown_endpoint_only_in_desktop_mode`).

Found and fixed during packaging tests (Wine): launcher used `%s` with
MinGW's `swprintf` (narrow vs wide semantics → wrong path → blocking error
dialog); desktop defaults were set as environment variables and therefore
**overrode the user's env file** (port/data-dir settings ignored) — defaults are
now applied only for keys absent from both. Both would have surfaced on real
Windows as "nothing happens" / "settings ignored".

Residual risks specific to the Windows edition: (a) installer not code-signed
(SmartScreen warning) — sign with the organisational certificate or whitelist
the SHA-256; (b) anti-virus heuristics may flag an NSIS installer that
contains a full office suite — the payload inventory
(`PPT2KB-Setup-payload.sha256`) lets AV teams whitelist precisely; (c) the
data folder is protected only by NTFS user permissions (like any desktop
application); (d) LibreOffice is updated only by shipping a new installer
(there is no auto-update by design); (e) validated under Wine 9.0, not yet on
a clean Windows 11 — the provided `tools\validate-offline.ps1` performs the
same acceptance run there.

### 8.3 No-internet guarantee for both packages

Neither package contacts anything at install or run time except the
configured Qwen and ServiceNow URLs: the Python code enforces the host
allow-list; `trust_env=False` ignores proxy variables; LibreOffice is started
with proxy variables cleared and performs no network access when converting a
local file (online update and extension checks are disabled in the profile); FastAPI telemetry is disabled; the UI is self-hosted (CSP
`default-src 'self'`); `pip` is absent from the container venv and never
invoked by the Windows edition. The Windows installer has no download step
(the NSIS script contains no `NSISdl`/`inetc` calls — grep `deploy/windows/ppt2kb.nsi`).

## 9. Updated verification checklist

- [ ] `sha256sum -c SHA256SUMS` for the received artifacts
- [ ] `sbom/ppt2kb-docker-image-sbom.cdx.json` / `sbom/ppt2kb-windows-sbom.cdx.json` attached to the approval record
- [ ] (Windows) run `tools\validate-offline.ps1` on a clean VM with the network adapter disabled — expect `RESULT: PASS`
- [ ] (Docker) `docker load`, `docker run --rm ppt2kb:1.0.0 soffice --version`, then the functional test in `docs/DEPLOY_DOCKER_OFFLINE.md` §6
- [ ] `PPT2KB_ALLOWED_OUTBOUND_HOSTS` set in the deployed configuration; egress firewall allows only those hosts
- [ ] `PPT2KB_CA_BUNDLE` points to the internal CA chain; `PPT2KB_TLS_VERIFY=true`
