# Test suite and execution results

## What was executed

Environment: Ubuntu 24.04 (x86_64), Python 3.13.18, LibreOffice 24.2.7.2,
pypdfium2 5.13.0, Pillow 13.0.0 — the application was installed with
`pip install -e .`, mock Qwen and mock ServiceNow services were started by the
test fixtures on random localhost ports. Date: 2026-11-01.

Command: `python -m pytest tests -v --durations=8`

Result: **52 passed, 0 failed, 0 skipped in 103.8 s.**

```
tests/test_e2e.py::test_full_flow_60_slides PASSED
tests/test_e2e.py::test_partial_failure_and_single_slide_retry PASSED
tests/test_e2e.py::test_transient_errors_are_retried PASSED
tests/test_e2e.py::test_plain_text_answer_and_json_mode_fallback PASSED
tests/test_e2e.py::test_wrong_api_key_marks_slides_failed PASSED
tests/test_e2e.py::test_interrupted_processing_is_resumed PASSED
tests/test_e2e.py::test_publish_partial_failure_recovery PASSED
tests/test_e2e.py::test_duplicate_detection_after_local_state_loss PASSED
tests/test_e2e.py::test_servicenow_auth_failure_reported PASSED
tests/test_e2e.py::test_connection_tests PASSED
tests/test_e2e.py::test_upload_rejections_via_api PASSED
tests/test_e2e.py::test_delete_job_removes_files PASSED
tests/test_e2e.py::test_ui_served PASSED
tests/test_e2e.py::test_cli PASSED
tests/test_security.py::test_valid_pptx_accepted PASSED
tests/test_security.py::test_rejects_wrong_extension PASSED
tests/test_security.py::test_rejects_non_zip_content PASSED
tests/test_security.py::test_rejects_docx_disguised_as_pptx PASSED
tests/test_security.py::test_rejects_path_traversal_member PASSED
tests/test_security.py::test_rejects_absolute_member PASSED
tests/test_security.py::test_rejects_zip_bomb_ratio PASSED
tests/test_security.py::test_rejects_zip_bomb_total_size PASSED
tests/test_security.py::test_rejects_too_many_entries PASSED
tests/test_security.py::test_detects_macro_enabled PASSED
tests/test_security.py::test_rejects_oversize PASSED
tests/test_security.py::test_rejects_empty PASSED
tests/test_security.py::test_display_name_sanitized PASSED
tests/test_security.py::test_outbound_allowlist_blocks_unknown_hosts PASSED
tests/test_security.py::test_outbound_allowlist_allows_configured_host PASSED
tests/test_security.py::test_outbound_ignores_proxy_env PASSED
tests/test_security.py::test_outbound_no_redirect_follow PASSED
tests/test_security.py::test_log_redaction_masks_secrets PASSED
tests/test_security.py::test_logging_filter_applies PASSED
tests/test_security.py::test_basic_auth_required_when_configured PASSED
tests/test_security.py::test_security_headers PASSED
tests/test_security.py::test_image_path_traversal_blocked PASSED
tests/test_security.py::test_config_rejects_non_allowlisted_hosts PASSED
tests/test_security.py::test_secrets_never_returned PASSED
tests/test_units.py::test_parse_description_json PASSED
tests/test_units.py::test_parse_description_fenced PASSED
tests/test_units.py::test_parse_description_prose_fallback PASSED
tests/test_units.py::test_parse_description_extra_keys_ignored_and_non_string_values PASSED
tests/test_units.py::test_prompt_treats_slide_as_data PASSED
tests/test_units.py::test_detect_direction PASSED
tests/test_units.py::test_text_to_html_escapes_and_lists PASSED
tests/test_units.py::test_article_html_structure PASSED
tests/test_units.py::test_standalone_html_embeds_images PASSED
tests/test_units.py::test_slide_description_flatten PASSED
tests/test_units.py::test_conversion_isolated PASSED
tests/test_units.py::test_conversion_page_limit PASSED
tests/test_units.py::test_conversion_timeout_kills_process PASSED
tests/test_units.py::test_text_extraction PASSED
7.06s call     tests/test_e2e.py::test_wrong_api_key_marks_slides_failed
======================== 52 passed in 103.81s (0:01:43) ========================
```

## Acceptance scenario mapping (section 10 of the requirements)

| # | Requirement | Test(s) | Evidence |
|---|---|---|---|
| 1 | Upload a presentation containing 60 slides | `test_full_flow_60_slides` (fixture `deck60` builds a 60-slide PPTX with Hebrew + English titles, bullet steps, tables, shapes and speaker notes) | job `slide_count == 60` |
| 2 | Convert all slides into images | `test_conversion_isolated`, e2e | 60 PNG files `slide_001..060.png`, numbering preserved, LibreOffice work dirs cleaned |
| 3 | Send images to a mock/configured Qwen API | e2e | mock counted 60 requests / 60 images; SHA-256 of each served image equals the hash the mock received for that slide number |
| 4 | Store descriptions associated with the correct slides | e2e | description of slide N contains "Slide N of 60"; Hebrew text preserved (`שלב 2`), language `he+en` |
| 5 | Preview and edit in the web UI | e2e (API), Playwright screenshots in EN and HE | `PATCH /slides/3` edited text appears in JSON export, HTML export and the ServiceNow article; UI rendered and exercised in a headless browser (upload → progress → KB selection → publish → result) |
| 6 | Generate properly structured HTML | `test_article_html_structure`, `test_text_to_html_escapes_and_lists`, e2e | 60 `<section>` elements in slide order, `<ol>` for numbered steps, `dir="rtl"` for Hebrew, all user/model text escaped, no `<script>` |
| 7 | Create a ServiceNow Knowledge Draft via the mock API | e2e, `test_servicenow_auth_failure_reported` | `kb_knowledge` record with `workflow_state=draft`, number `KB0001001`, selected `kb_knowledge_base`, links returned |
| 8 | Upload and reference slide images correctly | e2e | 60 attachments on the record; 60 `<img src="/sys_attachment.do?sys_id=…">` in slide order; attachment bytes start with the PNG signature |
| 9 | Interrupted processing and partial failures | `test_interrupted_processing_is_resumed`, `test_partial_failure_and_single_slide_retry`, `test_transient_errors_are_retried`, `test_publish_partial_failure_recovery`, `test_duplicate_detection_after_local_state_loss` | resume sends only the remaining slides (request count = 60 − done); failed slides 3/7/58 retried individually; attachment upload failing after 20 resumes to 60 without duplicates; a lost local record does not create a second article |
| 10 | Running without internet access | `test_outbound_allowlist_blocks_unknown_hosts`, `test_outbound_ignores_proxy_env`, standalone POC (below) | requests to non-allow-listed hosts are refused before connecting; proxy env ignored; full run completed with `PIP_NO_INDEX`/no external hosts |

## Additional manual verification performed

* **Standalone installation from the offline bundle** (`scripts/build-offline-bundle.sh --python 3.13`
  → 23 MB tarball, 30 wheels; `install.sh --no-systemd` run as root with
  `PIP_NO_INDEX=1` and an empty environment). Started as the unprivileged
  service user via `start.sh --daemon`; uploaded the 60-slide deck through the
  HTTP API; status `ready 60` after 8 s; published to the mock ServiceNow:
  `published KB0001001`, 1 article, 60 attachments; `stop.sh` stopped the
  service cleanly. Two defects were found and fixed during this run
  (config directory not group-readable by the service user; empty
  `PPT2KB_CA_BUNDLE=` parsed as a directory) — both now fail fast with clear
  messages, and the installer sets the right ownership.
* **systemd unit**: `systemd-analyze verify` passes on the rendered unit.
* **Web UI**: Playwright (Chromium) run against the real server + mocks:
  jobs list, upload page, job page (EN and HE/RTL), settings page; publishing
  through the UI produced the article number and links on screen.
* **Dependency audit**: `pip-audit` clean after upgrading Pillow 12.3.0 → 13.0.0
  and opentelemetry-api 1.45.0 → 1.45.2; CycloneDX SBOM generated.

## Not verified in this environment (must be done in your pipeline)

| Item | Why | How to verify |
|---|---|---|
| Docker image build and run | no Docker daemon available in the review sandbox (client only) | `scripts/build-image.sh && docker run --rm ppt2kb:1.0.0 soffice --version`, then run the e2e test against the container (`PPT2KB_*` env + mocks) or simply process a deck through the UI |
| Real Qwen endpoint | not reachable from the sandbox | **Settings → Test connection**; process a 2-slide deck; check `description` JSON fields are populated. If your gateway rejects `response_format`, the automatic fallback kicks in (logged once) |
| Real ServiceNow Zurich instance | not reachable | **Test connection** (GET `kb_knowledge_base`), then publish a small deck into a test KB; check the article, its 2 attachments and that images render in the article view and in the portal; confirm `article_type` choice value (see `docs/SERVICENOW.md`) |
| Behaviour with LibreOffice versions other than 24.2 | only 24.2.7 was available | run `tests/test_units.py::test_conversion_isolated` on the target host |
| Legacy binary `.ppt` files | the test deck generator only writes PPTX | upload a `.ppt`; validation accepts the OLE2 signature and LibreOffice converts it |

## Running the tests yourself

```bash
pip install -r requirements.txt -e ".[dev]"      # pytest, pytest-timeout, pip-audit, cyclonedx-bom
python -m pytest -v                              # ~2 minutes; LibreOffice must be installed
python -m pytest tests/test_security.py -v       # security controls only (fast)
```

The suite needs no network: the mock services bind to `127.0.0.1` on free ports.
