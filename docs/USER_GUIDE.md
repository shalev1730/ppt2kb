# User guide — web interface

Language: the **עברית / English** button (top right) switches the UI language
and layout direction; the choice is remembered in the browser.

## 1. Settings (once)

**Settings** → *Qwen Vision API*: base URL, model, credential, timeouts,
concurrency and rate limit, the system prompt. → *ServiceNow*: instance URL,
authentication, default knowledge base. **Test connection** checks each
endpoint with the current values. Values entered here override the server
defaults; secrets are never shown again (the field states "set (ui)" / "set (env)").
If the administrator locked the outbound hosts, URLs outside the allow-list are
rejected with "Rejected values".

## 2. Upload

**Upload** → drop a `.pptx`/`.ppt` file (size and slide limits are shown), add an
optional article title, **Upload and process**. The file is validated (type,
size, ZIP structure), converted to images in an isolated process and each
slide is sent to Qwen. You are taken to the presentation page, which refreshes
itself while processing runs (status *Converting…*, *Analysing slides…*).

## 3. Review

The presentation page shows:

* the status line with **done / pending / failed** counters and a progress bar;
* one card per slide: the original slide image on one side, the **Heading** and
  the **Description** text on the other. Edit the text freely and press **Save**
  (the card is marked *edited*); **Revert to AI text** restores the generated
  version. *Show extracted text* reveals the raw text from the PPTX and the
  speaker notes; *Structured model output* shows the JSON fields the model
  returned, including *uncertainties* (unreadable or ambiguous content you
  should check against the image).
* failed slides are highlighted; **Re-run this slide** sends only that slide
  again, **Retry failed slides** retries all of them. *Only failed* filters the list.
* **Cancel** stops a running analysis; **Resume** continues an interrupted or
  partial job without re-sending finished slides.
* the presentation title is editable in place (press Enter or click outside).

**Preview article** shows the HTML exactly as it will be created in ServiceNow
(with the local images). **Export JSON** downloads the structured data
(ppt2desc-compatible plus extensions); **Export HTML** downloads a
self-contained HTML file with the images embedded — handy for offline review
or e-mail.

## 4. Create the ServiceNow draft

In *Create ServiceNow Knowledge draft* click **Load from ServiceNow**, pick the
knowledge base, optionally tick *Attach original PPTX*, then **Create draft
article** (enabled only when all slides are done) and confirm. Progress is
shown (*attachments 23/60* …). On success the box shows **Draft article
KB0001234 created** with the sys_id and two links: *Open in ServiceNow* (form)
and *View article*. The article is in **Draft**; publishing follows your
normal knowledge workflow.

If creation fails (network, permissions), the error is shown and **Create draft
article** acts as *retry*: the same article is reused and only the missing
images are uploaded. Re-creating after further edits updates the same draft
(no duplicates).

## 5. Housekeeping

**Presentations** lists all jobs with status and article number. **Delete**
removes the upload, images and generated text from the server. Jobs older than
the configured retention period are removed automatically.
