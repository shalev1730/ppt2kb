# ServiceNow integration (Zurich, self-hosted)

ppt2kb uses only standard, documented REST APIs of the platform. No custom
tables, fields, scripted REST APIs or update sets are required.

## APIs used

| Call | Purpose |
|---|---|
| `GET /api/now/table/kb_knowledge_base?sysparm_query=active=true` | list knowledge bases for the selector |
| `GET /api/now/table/kb_knowledge?sysparm_query=textLIKE<marker>` | duplicate detection (see below) |
| `GET /api/now/table/kb_knowledge/{sys_id}` | verify an article recorded locally still exists |
| `POST /api/now/table/kb_knowledge` | create the article: `short_description`, `text` (HTML), `kb_knowledge_base`, `workflow_state=draft`, `article_type=text` |
| `PATCH /api/now/table/kb_knowledge/{sys_id}` | set the final HTML once image attachment sys_ids are known |
| `GET /api/now/attachment?sysparm_query=table_name=kb_knowledge^table_sys_id=…` | list existing attachments (resume without duplicates) |
| `POST /api/now/attachment/file?table_name=kb_knowledge&table_sys_id=…&file_name=slide_001.png` | upload each slide image (and optionally the PPTX) |
| `POST /oauth_token.do` | only for `PPT2KB_SERVICENOW_AUTH_TYPE=oauth_password` |

## Service account and roles

Create a dedicated integration user (e.g. `svc_ppt2kb`, *Web service access only*).
Required access:

* `knowledge` (or `knowledge_manager`) — create/update `kb_knowledge` in Draft and
  read `kb_knowledge_base`; the **knowledge base's "Can contribute" criteria**
  must include the user, otherwise `POST kb_knowledge` returns 403 or the
  record is created without the KB.
* Attachment write on `kb_knowledge` (included in the roles above; check
  *System Properties → Security → Attachment* allow-list contains `png`
  (and `pptx` if you attach the original) and the size limit
  `com.glide.attachment.max_size` ≥ the slide image size — defaults are fine).
* REST API access (`rest_api_explorer` is **not** needed; `snc_platform_rest_api_access`
  is required on instances where *Explicit roles* is enabled).

Authentication options: Basic auth (simplest), a static OAuth bearer token, or
the OAuth2 password grant (`client_id`/`client_secret` of an *OAuth API endpoint
for external clients* + the service account); the token is refreshed
automatically.

## Article content

* **Title**: the title given at upload, otherwise the title of the first slide,
  otherwise the file name. Editable in the UI (also after a first publish).
* **Body** (`text` field, HTML article type): a hidden marker
  `<!-- ppt2kb:job=<uuid> -->`, a source line, a collapsible table of contents,
  then one `<section>` per slide in original order — **never merged** — with a
  single `<h2>N. title</h2>` (the editable PPTX slide title when present), the
  reviewed explanation (summary and details paragraphs, procedures as `<ol>`,
  key facts as `<ul>`, labels as `<p><strong>`), then the slide's images as
  `<figure><img alt="…"></figure>`. Hebrew content gets `dir="rtl"`, lists take
  the direction of their items. No raw JSON, no repeated headings, no runs of
  blank lines. Only `div/section/details/summary/h2/p/strong/ol/ul/li/figure/img/a/em`
  are emitted; all text is HTML-escaped, so nothing from a slide or from the
  model can inject markup or scripts into the article.
* **Images** — two modes (`image_mode` per presentation, default from
  `PPT2KB_IMAGE_ATTACHMENT_MODE`):
  * `embedded` (default): only the pictures embedded in the PPTX that are
    selected (automatically, then confirmed or changed by the reviewer) are
    attached, in their original format (PNG stays PNG, JPEG stays JPEG;
    cropped/rotated pictures are stored as the visible portion, as PNG). File
    names are meaningful and unique:
    `<slide 3 digits>_<sanitised slide title>_<image 2 digits>.<png|jpg>`, e.g.
    `001_תהליך_התחברות_01.png`, `007_Error_handling_-_שגיאת_חיבור_01.jpg`. Hebrew
    is preserved (NFC); spaces become `_`; characters other than letters,
    digits, `-` and `_` are replaced; the title part is capped at 48
    characters; collisions get `-2`, `-3`. `PPT2KB_ASCII_FILENAMES=true` strips
    non-ASCII for instances that reject Unicode names. The full-slide render is
    *not* attached in this mode (it is only used for analysis). A slide with no
    selected image gets a text-only section — never a full-slide fallback
    unless the reviewer switches the presentation to `full_slide`.
  * `full_slide`: one rendered image per slide, `slide_001.png`… (1.0 behaviour).
  Attachments go to the article record via the Attachment API and are
  referenced as `<img src="/sys_attachment.do?sys_id=<attachment sys_id>">`
  inside the section of the slide they came from, in slide order. The mapping
  slide → image → file name → attachment `sys_id` is stored locally and shown
  in the UI.
* **State**: always `draft`. Publishing stays with your knowledge workflow
  (review/approve/publish); once published the article is indexed by AI Search
  like any other HTML article — the generated text is plain, searchable HTML.

## Idempotency and recovery

Each job stores the created `sys_id`/`number` locally. On re-publish:

1. If a `sys_id` is known and still exists → it is updated (title, body) and
   missing images are uploaded; existing attachments (matched by the
   `sys_id` recorded per image, or by file name on the article) are reused.
   Attachment names are assigned once and stored, so a retry never produces
   `004_משואה_750_01-2.png` duplicates.
2. If the local record was lost, the hidden marker is searched remotely
   (`textLIKEppt2kb:job=<uuid>`); a match is reused.
3. Otherwise a new article is created. `force_new=true` on the API skips 1–2.

The application only ever updates articles that carry its own marker for the
same job; it never modifies other Knowledge articles. Changing the image mode
or the image selection and publishing again rewrites the body of the same
draft; attachments that are no longer referenced are left on the record (they
are listed in the article's *Attachments* and can be removed by the editor) —
the tool does not delete anything on the instance.

Partial failures (network drop after 7 of 20 attachments, 5xx from the
instance, wrong credentials) leave the job in `publish_failed` with the error
shown in the UI; **Create draft article** again continues from where it
stopped. The automated tests cover both modes
(`test_embedded_publish_partial_failure_recovery`,
`test_publish_partial_failure_recovery`,
`test_duplicate_detection_after_local_state_loss`).

## Instance-specific configuration you may want

* **Category / ownership fields**: pass them with
  `PPT2KB_SERVICENOW_EXTRA_FIELDS_JSON`, e.g.
  `{"kb_category":"<sys_id>","author":"<user sys_id>","valid_to":"2027-12-31"}`.
  Unknown fields are ignored by the Table API.
* **Article type**: `article_type=text` (HTML) is sent. If your instance uses a
  different choice value, override it via the extra-fields JSON
  (`{"article_type":"html"}`), or remove it (`{"article_type":""}`).
* **Knowledge base version 3** with *article versioning* enabled: updating a
  draft does not create versions; publishing does — unchanged.
* **Proxy / IP allow-list**: add the ppt2kb host to the instance's inbound
  allow-list if one is enforced.
* **Attachment scanning**: if an AV scanner holds attachments, the image
  references still resolve once the scan completes.

## Future: topic-based splitting

The publisher takes `title + ordered slides + image source function` and
produces one article; `build_article_html()` is independent of the job. To
create several articles per presentation, group slides (e.g. by section
headers extracted in `original_text`, or by a grouping returned from the
model) and call `publish_job` per group with a group-specific marker
(`job_marker(f"{job_id}:{group}")`). The data model already keeps per-slide
attachment sys_ids, so images can be shared or re-uploaded per article.
