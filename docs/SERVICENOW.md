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
  then one `<section>` per slide in original order with `<h2>N. title</h2>`,
  the slide image and the reviewed text (paragraphs, numbered steps as `<ol>`).
  Hebrew paragraphs get `dir="rtl"`. Only `div/section/details/summary/h2/p/ol/li/img/a/em`
  are emitted; all text is HTML-escaped, so nothing from a slide or from the
  model can inject markup or scripts into the article.
* **Images**: attached to the article record via the Attachment API and
  referenced as `<img src="/sys_attachment.do?sys_id=<attachment sys_id>">`,
  the same form the knowledge editor uses for uploaded images. They are visible
  to anyone who can read the article (attachment access follows the record).
  The images also appear in the *Attachments* list of the article.
* **State**: always `draft`. Publishing stays with your knowledge workflow
  (review/approve/publish); once published the article is indexed by AI Search
  like any other HTML article — the generated text is plain, searchable HTML.

## Idempotency and recovery

Each job stores the created `sys_id`/`number` locally. On re-publish:

1. If a `sys_id` is known and still exists → it is updated (title, body) and
   missing images are uploaded; existing attachments (matched by `sys_id`
   recorded per slide, or by file name) are reused.
2. If the local record was lost, the hidden marker is searched remotely
   (`textLIKEppt2kb:job=<uuid>`); a match is reused.
3. Otherwise a new article is created. `force_new=true` on the API skips 1–2.

Partial failures (network drop after 20 of 60 attachments, 5xx from the
instance, wrong credentials) leave the job in `publish_failed` with the error
shown in the UI; **Retry publishing** continues from where it stopped. The
automated tests cover both (`test_publish_partial_failure_recovery`,
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
