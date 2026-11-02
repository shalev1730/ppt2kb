# Configuration reference

All settings are environment variables prefixed `PPT2KB_`. They can also be
placed in an env file whose path is given in `PPT2KB_ENV_FILE` (the systemd
unit and Compose pass the file directly). Settings marked **UI** can be
overridden at runtime in **Settings** (stored in the SQLite `settings` table);
secrets typed in the UI are held in memory only unless
`PPT2KB_PERSIST_UI_SECRETS=true`.

## Server

| Variable | Default | Description |
|---|---|---|
| `PPT2KB_HOST` | `127.0.0.1` | listen address (`0.0.0.0` in the container) |
| `PPT2KB_PORT` | `8080` | listen port |
| `PPT2KB_DATA_DIR` | `./data` | uploads, slide images, SQLite DB, temp dirs |
| `PPT2KB_LOG_LEVEL` | `INFO` | `DEBUG`/`INFO`/`WARNING`/`ERROR` |
| `PPT2KB_LOG_JSON` | `false` | JSON log lines (for SIEM ingestion) |
| `PPT2KB_UI_USERNAME` / `PPT2KB_UI_PASSWORD` | empty | enable HTTP Basic auth for UI + API (`/api/health` stays open for probes) |
| `PPT2KB_ALLOWED_OUTBOUND_HOSTS` | empty | comma-separated `host` or `host:port`. When set, outbound traffic is restricted to exactly these and URLs entered in the UI must match. When empty, the hosts of the configured Qwen/ServiceNow URLs are allowed. |
| `PPT2KB_PERSIST_UI_SECRETS` | `false` | store UI-entered secrets in the database (clear text, file-permission protected) |
| `PPT2KB_RETENTION_DAYS` | `30` | delete jobs older than this at startup (`0` = keep forever) |
| `PPT2KB_MAX_CONCURRENT_JOBS` | `1` | presentations processed in parallel (each uses up to `QWEN_CONCURRENCY` requests) |

## Uploads and limits

| Variable | Default | Description |
|---|---|---|
| `PPT2KB_MAX_UPLOAD_MB` | `200` | reject larger files (checked while streaming) |
| `PPT2KB_MAX_SLIDES` | `300` | reject decks with more pages after conversion |
| `PPT2KB_MAX_ZIP_ENTRIES` | `20000` | PPTX container limits (ZIP-bomb protection) |
| `PPT2KB_MAX_ZIP_UNCOMPRESSED_MB` | `2048` | |
| `PPT2KB_MAX_ZIP_RATIO` | `200` | max compression ratio for large members |

## Conversion sandbox

| Variable | Default | Description |
|---|---|---|
| `PPT2KB_LIBREOFFICE_PATH` | `/usr/bin/soffice` | LibreOffice binary (auto-detected if missing) |
| `PPT2KB_CONVERSION_TIMEOUT_S` | `600` | wall-clock limit; the whole LibreOffice process group is killed |
| `PPT2KB_CONVERSION_MEMORY_MB` | `3072` | `RLIMIT_AS` for LibreOffice |
| `PPT2KB_CONVERSION_CPU_SECONDS` | `900` | `RLIMIT_CPU` |
| `PPT2KB_IMAGE_WIDTH` / `PPT2KB_IMAGE_HEIGHT` | `1920`/`1080` | slide image canvas (slides are fitted and centred) |
| `PPT2KB_IMAGE_FORMAT` | `png` | `png` or `jpeg` (smaller attachments, lossy) |

## Qwen Vision (OpenAI-compatible Chat Completions)

| Variable | Default | UI | Description |
|---|---|---|---|
| `PPT2KB_QWEN_BASE_URL` | — | UI | e.g. `https://qwen.internal/v1` (`/chat/completions` is appended; a full URL ending in `/chat/completions` is also accepted) |
| `PPT2KB_QWEN_MODEL` | `Qwen2.5-VL-72B-Instruct` | UI | model identifier sent in the request |
| `PPT2KB_QWEN_API_KEY` | empty | UI (secret) | credential |
| `PPT2KB_QWEN_AUTH_HEADER` | `Authorization` | UI | header carrying the credential (`X-API-Key` for gateways) |
| `PPT2KB_QWEN_AUTH_SCHEME` | `Bearer` | UI | prefix; empty sends the raw key |
| `PPT2KB_QWEN_TIMEOUT_S` | `180` | UI | per request |
| `PPT2KB_QWEN_MAX_RETRIES` | `3` | UI | retries on timeout / 408 / 429 / 5xx with exponential back-off |
| `PPT2KB_QWEN_CONCURRENCY` | `4` | UI | parallel slide requests |
| `PPT2KB_QWEN_RATE_LIMIT_PER_MIN` | `60` | UI | token-bucket rate limit (`0` = unlimited) |
| `PPT2KB_QWEN_MAX_TOKENS` | `4096` | UI | |
| `PPT2KB_QWEN_TEMPERATURE` | `0.1` | UI | low temperature = faithful transcription |
| `PPT2KB_QWEN_PROMPT_FILE` | — | UI (text) | file with a custom system prompt (default in `src/ppt2kb/prompt.py`) |
| `PPT2KB_QWEN_EXTRA_BODY_JSON` | — | UI | JSON object merged into every request (e.g. `{"top_p":0.9}`) |

Request shape (identical to ppt2desc's OpenAI client, plus a system message):

```json
{"model": "...", "stream": false, "max_tokens": 4096, "temperature": 0.1,
 "response_format": {"type": "json_object"},
 "messages": [
   {"role": "system", "content": "<system prompt>"},
   {"role": "user", "content": [
      {"type": "text", "text": "This is slide 7 of 60 from the presentation \"...\". ... <extracted_text>...</extracted_text> ..."},
      {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}]}]}
```

If the endpoint rejects `response_format` (HTTP 400 mentioning it), the client
automatically falls back to plain text mode; non-JSON answers are still
accepted (the whole answer becomes the technical description and an
"uncertainties" note is added). Works with vLLM, SGLang, TGI (OpenAI mode),
DashScope-compatible gateways and LiteLLM.

## ServiceNow

| Variable | Default | UI | Description |
|---|---|---|---|
| `PPT2KB_SERVICENOW_URL` | — | UI | `https://servicenow.internal` (no path) |
| `PPT2KB_SERVICENOW_AUTH_TYPE` | `basic` | UI | `basic`, `bearer` (static OAuth token) or `oauth_password` (token obtained from `/oauth_token.do` with client id/secret + user/password, auto-refreshed) |
| `PPT2KB_SERVICENOW_USERNAME` / `PPT2KB_SERVICENOW_PASSWORD` | — | UI (secret) | service account |
| `PPT2KB_SERVICENOW_TOKEN` | — | UI (secret) | for `bearer` |
| `PPT2KB_SERVICENOW_OAUTH_CLIENT_ID` / `_SECRET` | — | UI | for `oauth_password` |
| `PPT2KB_SERVICENOW_TIMEOUT_S` | `120` | UI | per request (attachments of ~300 kB each) |
| `PPT2KB_SERVICENOW_MAX_RETRIES` | `3` | | retries on 408/429/5xx |
| `PPT2KB_SERVICENOW_DEFAULT_KB` | — | UI | `sys_id` of the knowledge base pre-selected in the UI |
| `PPT2KB_SERVICENOW_ATTACH_PPTX` | `false` | UI | also attach the original presentation |
| `PPT2KB_SERVICENOW_EXTRA_FIELDS_JSON` | — | UI | JSON merged into the `kb_knowledge` record on creation, e.g. `{"kb_category":"<sys_id>","valid_to":"2027-12-31"}` |

## TLS

| Variable | Default | Description |
|---|---|---|
| `PPT2KB_CA_BUNDLE` | — | PEM file with the internal CA chain, used for all outbound TLS (Qwen + ServiceNow). Missing file = startup error. |
| `PPT2KB_TLS_VERIFY` | `true` | **Keep true.** `false` is for isolated lab use only and is logged at CRITICAL. |
| `PPT2KB_CLIENT_CERT` / `PPT2KB_CLIENT_KEY` | — | mutual-TLS client certificate for the outbound connections |

Minimum TLS version is 1.2. Proxy environment variables are ignored by design;
if traffic must pass through an internal forward proxy, terminate it at the
network layer (transparent proxy) or allow direct access to the two hosts.

## Embedded images and attachment names (v1.1)

| Variable | Default | Notes |
|---|---|---|
| `PPT2KB_IMAGE_ATTACHMENT_MODE` | `embedded` | `embedded`: only the pictures embedded in the PPTX (PNG/JPEG, screenshots, photos, picture groups, cropped/rotated pictures) are attached to the article, each under the section of its slide. The full slide render is still produced and sent to Qwen for analysis but is **never** attached in this mode. `full_slide`: one rendered image per slide is attached (behaviour of 1.0). The value is the default for new uploads; each presentation can override it in the UI, and the publish request can override it again (`image_mode`). Settable in the UI (persisted). |
| `PPT2KB_ASCII_FILENAMES` | `false` | `true` drops Hebrew (and any non-ASCII) characters from attachment file names (`004_750_01.png` instead of `004_משואה_750_01.png`) for instances or proxies that reject Unicode file names. |
| `PPT2KB_QWEN_QUALITY_RETRIES` | `1` | How many times an answer that fails the quality validation (visual-only description, copied slide text, truncated/looping JSON, empty, duplicate of the previous slide) is re-requested with a corrective hint before the slide is marked **needs review**. 0 disables the retry (the validation still runs). |

Extraction uses `python-pptx` on the original file (no model involved) and is
limited to `PPT2KB_MAX_SLIDES`. Vector pictures (EMF/WMF/SVG), OLE objects,
shapes, SmartArt and text boxes are **not** extracted: they are listed as
*unsupported* in the UI so the reviewer can decide; nothing is faked. Legacy
`.ppt` files have no embedded-image extraction (the file is not a ZIP
container); for them use `full_slide` mode.

Decorative filtering is deliberately conservative: an image is excluded
automatically only when strong signals agree (the same picture repeated on 3+
slides — logos, watermarks; extreme aspect ratio — lines, separators; near-
uniform colour — backgrounds; background fills; sub-1 % placements). Small
icons that are not repeated are kept. Every decision is shown with its reasons
in the UI and can be overridden per image; overrides survive re-extraction.

## Model quality and small models

The quality of the generated text is largely the model's. Small vision models
(2B–8B parameters, e.g. a local Qwen2-VL via Ollama) read Hebrew poorly,
describe the look of the slide instead of its meaning and sometimes fall into
repetition loops. Qwen2.5-VL-32B/72B or Qwen3-VL give markedly better results.
The application mitigates what it can:

* **Prompt (v1.1)**: the model is instructed to act as a technical writer and
  explain *what the slide teaches* — purpose, components, relationships,
  procedures, exact technical identifiers — never colours, layout or fonts; to
  prefer the reliable text extracted from the PPTX over its own OCR; to answer
  in the slide's language (Hebrew stays Hebrew); and to invent nothing. The
  neighbouring slide titles are passed as context only; each slide is written
  as an independent section.
* **Validation**: every answer is checked (`src/ppt2kb/llm/validate.py`).
  Blocking problems — not JSON, truncated, repetition loop, empty, appearance-
  only, copied slide text, duplicate of the previous slide — trigger a retry
  with a corrective hint (`PPT2KB_QWEN_QUALITY_RETRIES`); if the problem
  persists the slide is marked **needs review** and the article cannot be
  created until a reviewer edits and accepts it (or re-runs the slide).
  Warnings (low confidence, unreadable parts, short answer for a dense slide)
  are shown to the reviewer but do not block.
* Truncated JSON is salvaged and flagged, repetition loops trigger a retry with
  `frequency_penalty`, the heading is taken from the PPTX when the slide has an
  editable title.

If your endpoint supports them, setting
`PPT2KB_QWEN_EXTRA_BODY_JSON={"frequency_penalty":0.3,"repetition_penalty":1.1}`
reduces loops for small models. Keep `PPT2KB_QWEN_TEMPERATURE` low (0.1).

## Prompt customisation

The default system prompt (`src/ppt2kb/prompt.py`) asks for a JSON object with
`title`, `slide_kind`, `summary`, `details`, `procedures`, `key_facts`,
`visible_text`, `uncertainties`, `language`, `confidence`; it demands
explanation of meaning rather than appearance, exact technical identifiers,
the slide's language, and declares the slide content as data, not
instructions. You can replace it via `PPT2KB_QWEN_PROMPT_FILE` or in the UI —
keep the JSON contract if you want the structured fields and the quality
validation to work as designed; free-text answers are accepted but are flagged
*needs review* (`not_json`). Answers in the 1.0 format
(`technical_description` / `visuals_explanation`) are still understood.

## UI language

The UI starts in English; the **עברית / English** button switches language and
layout direction (RTL). The choice is remembered per browser. Slide text fields
use `dir="auto"` so Hebrew and English paragraphs each align correctly.
