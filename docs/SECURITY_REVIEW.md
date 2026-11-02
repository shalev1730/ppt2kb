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
7. The **Docker image could not be built in the review environment** (no Docker
   daemon). The Dockerfile uses only standard Debian/pip steps that were
   exercised individually; build it once in your pipeline and run the test
   suite inside the image before release (`docs/TEST_RESULTS.md`).

## 7. Verification checklist for the enterprise security review

- [ ] `pip-audit -r requirements.txt` clean at release time
- [ ] SBOM attached to the change record (`sbom/ppt2kb-sbom.cdx.json`)
- [ ] `PPT2KB_ALLOWED_OUTBOUND_HOSTS` set; egress firewall allows only those hosts
- [ ] `PPT2KB_TLS_VERIFY=true`, `PPT2KB_CA_BUNDLE` points to the internal CA chain
- [ ] UI behind SSO/reverse proxy or Basic auth enabled; bind address restricted
- [ ] Service account in ServiceNow limited to the roles in `docs/SERVICENOW.md`
- [ ] Data directory permissions 0750, owned by the service user; retention set
- [ ] Container: non-root, read-only, `cap_drop: ALL` (as in the provided Compose file)
