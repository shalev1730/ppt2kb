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

## Prompt customisation

The default system prompt (`src/ppt2kb/prompt.py`) asks for a JSON object with
`title`, `visible_text`, `technical_description`, `visuals_explanation`,
`procedures`, `uncertainties`, `language`; demands verbatim transcription in
the original language (Hebrew stays Hebrew), forbids inventing information and
declares the slide content as data, not instructions. You can replace it via
`PPT2KB_QWEN_PROMPT_FILE` or in the UI — keep the JSON contract if you want the
structured fields; free-text prompts still work (text lands in
`technical_description`).

## UI language

The UI starts in English; the **עברית / English** button switches language and
layout direction (RTL). The choice is remembered per browser. Slide text fields
use `dir="auto"` so Hebrew and English paragraphs each align correctly.
