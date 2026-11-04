# Test suite and execution results

## What was executed

Environment: Ubuntu 24.04 (x86_64), Python 3.13.18, LibreOffice 24.2.7.2,
pypdfium2 5.x, Pillow 13.0.0, Playwright + Chromium (UI tests) — the application
was installed with `pip install -e .`, mock Qwen and mock ServiceNow services
were started by the test fixtures on random localhost ports. Date of the final
v1.1.2 run: 2026-11-04.

Command: `python -m pytest tests -v --durations=8`

Result: **85 passed, 0 failed, 0 skipped in 208.2 s** (78 tests in 1.1.1 plus 7 new
tests for v1.1.2 in `tests/test_backgrounds.py`).

```
tests/test_backgrounds.py::test_background_detection_is_structural_first_and_conservative PASSED
tests/test_backgrounds.py::test_embedded_only_mode_excludes_backgrounds PASSED
tests/test_backgrounds.py::test_embedded_full_mode_keeps_full_slides_and_excludes_backgrounds PASSED
tests/test_backgrounds.py::test_full_slide_mode_is_unchanged_by_the_option PASSED
tests/test_backgrounds.py::test_include_backgrounds_keeps_everything PASSED
tests/test_backgrounds.py::test_option_persists_and_retry_keeps_it_and_change_requires_republish PASSED
tests/test_backgrounds.py::test_backward_compatibility_old_presentations_keep_their_images PASSED
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
tests/test_embedded.py::test_extraction_covers_all_cases PASSED
tests/test_embedded.py::test_decorative_filtering_is_conservative PASSED
tests/test_embedded.py::test_embedded_mode_end_to_end PASSED
tests/test_embedded.py::test_embedded_publish_partial_failure_recovery PASSED
tests/test_embedded.py::test_full_slide_mode_still_available PASSED
tests/test_embedded.py::test_presentation_saved_by_older_version_gets_images_on_publish PASSED
tests/test_embedded.py::test_mode_setting_is_persistent_and_ascii_filenames PASSED
tests/test_embedded.py::test_visual_description_is_rejected_and_retried PASSED
tests/test_embedded.py::test_persistently_bad_answers_need_review PASSED
tests/test_embedded.py::test_validation_rules PASSED
tests/test_embedded.py::test_rtl_and_structure_in_html PASSED
tests/test_embedded.py::test_oversized_embedded_picture_is_reported_not_decoded PASSED
tests/test_embedded.py::test_embedded_full_mode_is_default_and_attaches_both PASSED
tests/test_embedded.py::test_embedded_full_partial_failure_recovery PASSED
tests/test_embedded.py::test_mode_change_after_publish_requires_explicit_republish PASSED
tests/test_embedded.py::test_backward_compatibility_with_older_presentations PASSED
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
tests/test_ui.py::test_dark_mode_toggle_and_persistence PASSED
tests/test_ui.py::test_rtl_and_ltr_layouts_keep_the_toggle_top_right PASSED
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
tests/test_units.py::test_secretstore_roundtrip_non_windows PASSED
tests/test_units.py::test_persisted_ui_secrets_survive_restart PASSED
tests/test_units.py::test_shutdown_endpoint_only_in_desktop_mode PASSED
tests/test_units.py::test_desktop_launcher_start_stop PASSED
tests/test_units.py::test_desktop_defaults_do_not_override_env_file PASSED
tests/test_units.py::test_parse_description_salvages_truncated_repetition_loop PASSED
tests/test_units.py::test_parse_description_collapses_blank_runs_in_valid_json PASSED
tests/test_units.py::test_degenerate_answer_triggers_penalised_retry PASSED
======================== 85 passed in 208.16s (0:03:28) ========================
```

### v1.1.2 mapping (exclude slide backgrounds)

| # | Requirement | Test | Evidence |
|---|---|---|---|
| 1 | True image background + one content image | `test_background_detection_is_structural_first_and_conservative`, `test_embedded_only_mode_excludes_backgrounds` | slide 1: background fill flagged `slide_background`, master logo `layout_picture`, the screenshot kept and the only figure of the section |
| 2 | Repeated background across slides | same | the theme picture on slides 2–5 (full-bleed, back-most, 2–3 shapes over it, reuse 4) is excluded; no `002_/004_` attachments |
| 3 | Full-slide mode unchanged | `test_full_slide_mode_is_unchanged_by_the_option` | 8 renders and 8 figures with the option on and off |
| 4 | Embedded Images Only | `test_embedded_only_mode_excludes_backgrounds` | 21 extracted, 14 backgrounds, 7 content images attached/shown; background-only slides get title + explanation |
| 5 | Embedded Images + Full Slides | `test_embedded_full_mode_keeps_full_slides_and_excludes_backgrounds` | 8 renders + 7 content images = 15 attachments, one full-slide figure per section |
| 6 | Backward compatibility | `test_backward_compatibility_old_presentations_keep_their_images`, `test_include_backgrounds_keeps_everything` | 1.1.1-style job (no option, unflagged rows) publishes all 11 distinct originals; re-extraction classifies 14 backgrounds; option off reproduces 1.1.1 output |
| — | Persistence, retry, explicit republish, server default | `test_option_persists_and_retry_keeps_it_and_change_requires_republish` | retry after 3 uploads completes to 7 with the option kept; PATCH flags `mode_changed`, republish adds the 4 background assets without duplicates; `PUT /api/config exclude_backgrounds` applies to new uploads |
| — | Qwen unaffected | mode tests | `images_seen == 8` whatever the option; the prompt rule is additive |

### v1.1.1 regression mapping (three image output modes, Dark Mode)

| # | Requirement | Test(s) | Evidence |
|---|---|---|---|
| 1 | Embedded Images Only | `test_embedded_mode_end_to_end` | body: 20 selected figures under their slides, no slide renders; attachments: all 80 originals → 21 distinct files (logo ×59 once, reused screenshot once); names `004_משואה_750_image_01.png`, `007_Error_handling_-_שגיאת_חיבור_image_01.jpg` |
| 2 | Embedded Images + Full Slides (default) | `test_embedded_full_mode_is_default_and_attaches_both` | default without a choice; body: exactly one figure per section = its own render, above the explanation; attachments 60 renders (`004_משואה_750.png`) + 21 originals = 81; render vs. picture bytes verified |
| 3 | Full Slides Only | `test_full_slide_mode_still_available`, `test_full_flow_60_slides` | 60 renders only, no `_image_` files, one figure per section, order 1..60 |
| 4 | Slides without embedded images | `test_extraction_covers_all_cases`, `test_embedded_mode_end_to_end`, `test_embedded_full_mode_is_default_and_attaches_both` | slide 5 has no picture: text-only section in mode 1, its render only in mode 2, no `005_*_image_*` attachment |
| 5 | Slides with multiple embedded images | same | slide 3: 4 pictures (1 + group of 3), slide 4: 2 (cropped + rotated) |
| 6 | 60+ slides | all e2e tests | 60-slide decks throughout |
| 7 | Article body ordering | modes 2/3 tests, `test_full_flow_60_slides` | sections 1..60 in order; figure references map to `001_…` → `060_…` in order |
| 8 | Image-to-slide mapping | modes 1/2 tests | every `sys_attachment.do?sys_id` in the body belongs to the article; per-image `attachment_sys_id` exposed to the UI, repeated logo shares one sys_id |
| 9 | Attachment counts | modes 1/2/3 tests | 21 / 81 / 60 and `servicenow.attachments` reports the same |
| 10 | Hebrew filenames | modes 1/2/3 tests, `test_mode_setting_is_persistent_and_ascii_filenames` | Hebrew kept (NFC); ASCII option still works (`004_750_image_01.png`) |
| 11 | Retry and duplicate prevention | `test_embedded_full_partial_failure_recovery`, `test_embedded_publish_partial_failure_recovery`, `test_publish_partial_failure_recovery` | failure after 65 / 7 / 20 uploads → retry completes to 81 / 21 / 60 with unique names, one article, mode unchanged |
| 12 | Light/Dark switching | `test_dark_mode_toggle_and_persistence` | one click: `data-theme`, body/card/input colours (#0F1117 / #1A1D27 / #242936), aria-pressed, label |
| 13 | Theme persistence after refresh | same | `localStorage` value; reload and navigation keep dark; no white surfaces left on jobs/settings/upload; system preference honoured without a stored choice |
| 14 | RTL and LTR layouts | `test_rtl_and_ltr_layouts_keep_the_toggle_top_right` | toggle top-right and non-overlapping in both; Hebrew labels תמונות בלבד / תמונות ושקופיות / שקופיות בלבד; dark works in both |
| 15 | Backward compatibility | `test_backward_compatibility_with_older_presentations`, `test_presentation_saved_by_older_version_gets_images_on_publish`, `test_mode_change_after_publish_requires_explicit_republish` | 1.0 article with `slide_NNN.png` files reused, not re-uploaded; job without a stored mode = `embedded`; 1.1.0 jobs get images lazily; DB column added by migration |

### v1.1.0 acceptance mapping (requirements "Embedded Image Extraction and Context-Aware Technical Knowledge Generation")

| Requirement | Test(s) | Evidence |
|---|---|---|
| Extract PNG/JPEG, screenshots, multiple images per slide, picture groups, reused assets, cropped (visible portion only), rotated; flag what cannot be extracted; no full-slide fallback | `test_extraction_covers_all_cases` | 60-slide generated deck with a planned image layout: 81 pictures found; crop 0.25/0.25/0.10 of a 900×900 screenshot yields a pixel-exact 450×504 PNG; 90° rotation yields the rotated pixels; reuse counted across 12 slides; JPEG stored byte-identical; vector placeholders reported `supported=False` with a note |
| Conservative decorative filtering with reasons; manual include/exclude; overrides preserved | `test_decorative_filtering_is_conservative`, `test_embedded_mode_end_to_end` | 20 of 81 auto-selected: repeated logo (12 slides) and a 1200×6 separator excluded, screenshots, grouped icons and the cropped picture kept, every decision carries reasons; `PATCH …/images/{idx}` toggles survive re-extraction (`replace_slide_images` keeps `selected != auto_selected`) |
| Meaningful file names, Hebrew preserved, unique, original format, reliable mapping to sys_ids | `test_embedded_mode_end_to_end`, `test_mode_setting_is_persistent_and_ascii_filenames` | `004_משואה_750_01.png`, `004_משואה_750_02.png`, `003_ארכיטקטורה_-_Client_API_Database_01.png`, `007_Error_handling_-_שגיאת_חיבור_01.jpg`; `attachment_sys_id` per image matches the attachment record; ASCII mode: `004_750_01.png`, `007_Error_handling_01.jpg` |
| Qwen prompt explains meaning, uses reliable PPTX text and neighbour context, each slide independent | `test_embedded_mode_end_to_end` (prompt capture), `test_prompt_treats_slide_as_data` | every request carries `<slide_text>` with the PPTX text and *previous/next slide title* context; 60 independent sections |
| Professional HTML: one heading per section, no raw JSON, no blank-line runs, lists, alt text, RTL | `test_rtl_and_structure_in_html`, `test_article_html_structure`, `test_text_to_html_escapes_and_lists` | `<section>` per slide, single `<h2>`, `<ol>`/`<ul>` with item direction, `<figure><img alt>`; no `<script` |
| Strict validation: visual-only, raw OCR, truncated, loops, empty, duplicates → retry with correction, then needs_review; never silently accepted; never auto-published | `test_visual_description_is_rejected_and_retried`, `test_persistently_bad_answers_need_review`, `test_validation_rules`, `test_plain_text_answer_and_json_mode_fallback`, `test_parse_description_salvages_truncated_repetition_loop` | visual-first mock: 120 requests for 60 slides, 60 corrective prompts seen, all slides end `done`; visual-always mock: 60 slides `needs_review`, publish → HTTP 409, edit + `POST …/accept` → `done` |
| UI: image mode setting (persistent), full slide preview + extracted images, include/exclude, text editing, section preview | `test_mode_setting_is_persistent_and_ascii_filenames`, `test_embedded_mode_end_to_end` (`preview.html?slide=4`), Playwright run (below) | `PUT /api/config image_attachment_mode` survives restart and applies to new jobs; the UI run exercised thumbnails, toggles, review/accept, section preview and publish without console errors |
| ServiceNow: draft, selected images with meaningful names under the correct slide, no duplicates on retry, recovery preserved, previously created articles not modified automatically, HTML sanitised | `test_embedded_mode_end_to_end`, `test_embedded_publish_partial_failure_recovery`, `test_duplicate_detection_after_local_state_loss`, `test_presentation_saved_by_older_version_gets_images_on_publish` | 20 attachments, each referenced in its slide's section in order; failure after 7 attachments → retry completes to 20 with no duplicate names; re-publish → still 1 article / 20 attachments; a 1.0 job gets images extracted lazily on publish |
| Full-slide mode still available | `test_full_slide_mode_still_available` | `image_mode=full_slide` → 60 `slide_NNN.png` attachments |
| Decompression-bomb guard on embedded pictures | `test_oversized_embedded_picture_is_reported_not_decoded` | a 9000×9000 PNG is refused from its header, flagged, the next picture is still extracted |

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
  **v1.1.0 run** (12-slide embedded deck, one slide forced to *needs review*):
  publish button disabled and the review counter shown; thumbnails of the
  extracted images with reasons; unticking/ticking *Include* on slide 4
  changed `selected` on the server; *Preview section* rendered slide 4 alone
  with its two figures; filtering *Only needing review*, editing the text and
  *Accept for publishing* moved the job to `ready`; Hebrew UI publish produced
  `KB0001001` with 10 attachments named e.g. `004_משואה_750_01.png`; the
  *Images and quality* settings form persisted the mode. No browser console
  errors.
* **Dependency audit**: `pip-audit` clean after upgrading Pillow 12.3.0 → 13.0.0
  and opentelemetry-api 1.45.0 → 1.45.2; CycloneDX SBOM generated.

## B. Deployment package tests (final packages)

### B.1 `ppt2kb-web-offline.tar` — image build and container start (executed)

* Built with `buildah bud --isolation chroot` from `deploy/docker/Dockerfile`
  (no Docker daemon in the build sandbox; buildah performs a real OCI build:
  base image pulled, apt/pip steps executed). First build **failed** at the
  user-creation step (`groupadd` not on the restricted PATH) — fixed, rebuilt.
* Exported with `buildah push ... docker-archive:` → 617 MB tar, tags
  `ppt2kb:1.0.0`; `skopeo inspect` OK (5 layers, labels, amd64/linux).
* Container start test (`buildah run --isolation chroot --user 10001:10001`,
  volume mounted at `/data`, entrypoint `ppt2kb`): health `ok`,
  LibreOffice 7.4.7 present, 68 Hebrew font faces; uploaded the 60-slide deck
  through the API from inside the container → `ready 60/60`; published to the
  mock ServiceNow → `KB0001001`, 1 article, 60 attachments; slide image served
  as PNG. Repeated for every release: the 1.1.1 image (`ppt2kb:1.1.1`, same
  256 Debian packages) processed the 60-slide embedded deck in default mode
  `embedded_full` → 80 pictures extracted, published `KB0001001` with 81
  attachments (60 renders + 21 distinct originals), 60 body figures, re-publish
  idempotent (`container-test111.log`).
* Not executed: `docker load` / `docker compose up` themselves (no daemon).
  The tar is in the standard docker-archive format (manifest.json +
  repositories + layers) that `docker load` and `podman load` consume.

### B.2 `PPT2KB-Setup.exe` — build and installation test (executed under Wine 9.0)

The installer was built by `deploy/windows/build-windows.sh` (components
checksum-verified; LibreOffice MSI GPG signature verified). Because the build
environment is Linux, the installation test used Wine 9.0 (WoW64 prefix) with
a virtual display — a close but not identical substitute for Windows 11:

| Step | Result (v1.1.1 installer, 2026-11-04) |
|---|---|
| `PPT2KB-Setup.exe /S /D=C:\PPT2KB` on a fresh prefix | 21 s; 4,748 files; 8 shortcuts; Add/Remove Programs entry `PPT2KB 1.1.1` |
| Bundled mock services started with the embedded Python (`tools\start-mock-services.cmd` equivalent) | up after 4 s |
| `PPT2KB.exe` (desktop launcher) | returns in 0.14 s, server healthy after 5 s (`version 1.1.1`, `libreoffice: true`) |
| Second `PPT2KB.exe` while running | detects the running instance (no second server) |
| Upload the 60-slide *embedded-images* test deck | `ready 60/60` after 14 s; image output mode **`embedded_full` by default**; 80 embedded pictures extracted, 20 auto-selected, 0 slides needing review (deterministic mock); slide 4: cropped 450×504 PNG, 160×160 PNG rotated 90°, 120×120 repeated logo |
| Manual include/exclude (`PATCH …/images/1`) and section preview (`preview.html?slide=4`) | toggles persisted; preview shows `<h2 dir="rtl">4. משואה 750</h2>` with the one full-slide figure of mode 2 |
| UI secret (`PUT /api/config`) | stored as `dpapi:` blob (DPAPI), not in clear text |
| Create draft | `published KB0001001`, **81 attachments**: 60 slide renders (`003_ארכיטקטורה_-_Client_API_Database.png`) + 21 distinct originals (`002_תהליך_התחברות_image_01.png`); body: 60 figures (one full slide per section); re-publish → still 1 article / 81 attachments |
| Data folder | 60 slide renders + 80 extracted image files under `%LOCALAPPDATA%\PPT2KB\data` |
| `PPT2KB.exe --stop` | 1.8 s, server gone |
| `uninstall.exe /S` | finished in 7 s: shortcuts and registry key removed, data folder kept (by design); `config` kept; `python` folder remained only because the test's mock processes were still running from it |

The 1.1.0 run (Embedded Images Only, 20 attachments) and the 1.0.1 run (60-slide
VPN deck, full-slide mode) of the same script are kept in the build logs.

Earlier iterations of this test found and fixed: launcher `swprintf` wide-string
bug (server never started, blocking dialog); desktop defaults overriding the
env file (`PPT2KB_PORT` ignored); `/D=` ignored by MultiUser; 64-bit default
folder; `BUILD-INFO.txt` left behind by the uninstaller.

Also verified under Wine: the trimmed LibreOffice converts the 60-slide deck
to a 60-page PDF with correct Hebrew rendering (bundled fonts); the embedded
Python imports every compiled dependency (`pydantic_core`, `lxml`, `Pillow`,
`pdfium`).

## Not verified in this environment (must be done in your pipeline)

| Item | Why | How to verify |
|---|---|---|
| `docker load` / Compose on a real Docker host | no daemon in the sandbox (image was built and run with buildah) | `docs/DEPLOY_DOCKER_OFFLINE.md` §1 and §6 |
| Windows installer on a clean Windows 11 x64 (physical/VM, network disabled) | only Wine was available | install `PPT2KB-Setup.exe`, then `powershell -ExecutionPolicy Bypass -File "<install>\tools\validate-offline.ps1"` → expect `RESULT: PASS`; double-click PPT2KB and check the browser opens |
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
