# Changelog

## 1.1.1 (2026-11-03) — three image output modes, Dark Mode

* **Image output mode per presentation**, chosen on the upload page before processing and stored
  with the presentation (default from `PPT2KB_IMAGE_ATTACHMENT_MODE`, now `embedded_full`):
  * `embedded` — *Embedded Images Only* (תמונות בלבד): body = selected original images under each
    slide's explanation; attachments = every original image (identical images once).
  * `embedded_full` — *Embedded Images + Full Slides* (תמונות ושקופיות), **default**: body = the full
    slide render with the explanation beneath it; attachments = full slides + every original image.
  * `full_slide` — *Full Slides Only* (שקופיות בלבד): body = full slide render + explanation;
    attachments = full slides only.
  Qwen analysis is identical in all modes (full slide render + PPTX text, independent sections).
* Attachment names: `NNN_<slide title>.png` for slide renders, `NNN_<slide title>_image_KK.<png|jpg>`
  for embedded images; Hebrew preserved, unique, assigned once (new `slides.attachment_file_name`
  column, added by migration); identical pictures are uploaded once and shared; 1.0 articles keep
  their `slide_NNN.png` files.
* Changing the mode of a published presentation never modifies the article silently: the page shows
  a notice and an explicit **Republish with the new mode** action; a retry of a failed publish keeps
  the mode the article was created with.
* **Dark Mode**: sun/moon toggle in the top-right corner (LTR and RTL), one click, remembered per
  browser, applied before first paint, system preference used when nothing is stored; full coverage
  of header, navigation, tables, cards, forms, dialogs, thumbnails, preview, status messages.
* Tests: 6 new (78 total) — mode 2 end-to-end with counts/order/mapping, mode 2 retry recovery,
  mode change / republish / no silent switch, backward compatibility, Dark Mode toggle and
  persistence, RTL/LTR layouts (Playwright, skipped when unavailable).

## 1.1.0 (2026-11-02) — embedded image extraction, context-aware technical explanations

* **Embedded images instead of slide screenshots** (`PPT2KB_IMAGE_ATTACHMENT_MODE=embedded`, default; `full_slide`
  keeps the 1.0 behaviour). Pictures are extracted from the PPTX with python-pptx: PNG/JPEG, screenshots, several
  per slide, picture groups, reused assets (counted), cropped pictures (visible portion only, pixel-exact),
  rotated/flipped pictures, background fills. Vector pictures (EMF/WMF/SVG), OLE, shapes and SmartArt are reported
  as *unsupported*, never faked, and no full-slide image is attached unless the reviewer switches the mode.
  The full slide render is still produced and sent to Qwen for analysis.
* **Conservative decorative filtering** with per-image reasons (repeated on ≥3 slides, extreme aspect ratio,
  near-uniform, background, <1 % placement vs. large/detailed/grouped/cropped). Small icons are kept unless
  repeated. Every decision can be overridden per image in the UI; overrides survive re-processing.
* **Meaningful attachment names** `NNN_<slide title>_KK.<png|jpg>` with Hebrew preserved (NFC), sanitised,
  unique, original format kept; `PPT2KB_ASCII_FILENAMES` for instances that reject Unicode names. Each image
  keeps its attachment `sys_id`; retries reuse names and attachments (no duplicates).
* **New Qwen objective and prompt (v3)**: technical writer persona — explain the meaning and purpose of the
  slide, exact identifiers (tables, fields, scripts, URLs, parameters), procedures and key facts; never
  colours, layout or fonts; prefer the reliable PPTX text over OCR; Hebrew stays Hebrew; neighbouring slide
  titles as context only; every slide an independent section. Fields: `title, slide_kind, summary, details,
  procedures, key_facts, visible_text, uncertainties, language, confidence` (1.0 answers still parsed).
* **Strict validation and review queue**: answers that are not JSON, truncated, looping, empty, appearance-only,
  copied slide text or duplicates of the previous slide are retried with a corrective hint
  (`PPT2KB_QWEN_QUALITY_RETRIES`, default 1) and otherwise marked **needs review**; publishing is blocked
  (HTTP 409) until the reviewer edits and accepts the slide or re-runs it. Warnings (low confidence,
  unreadable parts, short for a dense slide, missing title) are shown to the reviewer.
* **HTML**: one `<h2>` per section (PPTX title preferred), summary/details paragraphs, procedures as `<ol>`,
  key facts as `<ul>`, labels as `<p><strong>`, figures with alt text under the text, list direction from the
  items, no blank-line runs, no raw JSON. Single-section preview (`preview.html?slide=N`).
* **Web UI**: *Images and quality* settings (persistent image mode, quality retries, ASCII names); per
  presentation image mode; slide cards show the full render ("sent to Qwen"), the extracted images with
  include/exclude, properties, reasons and final file names, the validation findings, **Accept for
  publishing** and **Preview section**; *need review* counter and filter; publish disabled while any slide
  needs review. Hebrew/RTL throughout.
* **API**: `GET/PATCH /api/jobs/{id}/slides/{n}/images/{idx}`, `POST …/slides/{n}/accept`,
  `POST …/images/extract` (lazy extraction for presentations processed by 1.0), `image_mode` on
  `PATCH /api/jobs/{id}` and on publish; job view carries `image_mode`, `images_total`, `images_selected`,
  per-slide `images`, `quality`, `reviewed`; `slide_images` table and `quality_json`/`reviewed` columns are
  added by migration — existing data is preserved.
* **Security**: decompression-bomb guard for embedded pictures (header check, 40 M pixels); file names never
  used as paths; same escaping path for HTML; no new outbound hosts or dependencies.
* Tests: 12 new (72 total, all passing with the mocks); mock Qwen gained `visual_first` / `visual_always` and
  prompt capture.

## 1.0.1 (2026-11-01)

Robustness against weak / small vision models (observed with a local Qwen-VL on a real deck):

* Truncated JSON answers (model stuck in a `\n\n\n…` repetition loop until `max_tokens`) are now
  salvaged: the completed fields are kept, runaway blank runs are collapsed, and the slide is
  flagged in *uncertainties* ("answer was cut off … please verify") instead of dumping thousands of
  empty lines into the article.
* When such a loop is detected the slide is automatically re-requested once with
  `frequency_penalty` / `presence_penalty` (OpenAI-compatible; vLLM, Ollama and gateways accept them).
* The slide heading is no longer repeated as the first line of the description.
* Prompt: the title must be the slide's own heading (never "Slide N" or the deck name); explicit
  guidance on Hebrew right-to-left word order; no padding with blank lines.
* Mock Qwen gained `degenerate_first` mode; 3 new tests (60 total).

## 1.0.0 (2026-11-01)

Initial release: web application, Qwen Vision + ServiceNow integration, Docker image,
Linux standalone bundle, Windows installer, security review, SBOM.
