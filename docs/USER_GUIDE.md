# User guide — web interface

Language: the **עברית / English** button switches the UI language and layout
direction; the choice is remembered in the browser. The **sun/moon button** in
the top-right corner switches between Light and Dark Mode (also remembered per
browser; without a choice the system preference is used).

## 1. Settings (once)

**Settings** → *Qwen Vision API*: base URL, model, credential, timeouts,
concurrency and rate limit, the system prompt. → *Images and quality*: the
default **Image output mode** for new presentations, the number of quality
retries and whether attachment names must be ASCII-only. → *ServiceNow*: instance URL,
authentication, default knowledge base. **Test connection** checks each
endpoint with the current values. Values entered here override the server
defaults and are persisted; secrets are never shown again (the field states
"set (ui)" / "set (env)"). If the administrator locked the outbound hosts, URLs
outside the allow-list are rejected with "Rejected values".

## 2. Upload

**Upload** → drop a `.pptx`/`.ppt` file (size and slide limits are shown), add an
optional article title and choose the **Image output mode** for this
presentation (it is stored with the presentation and shown on its page):

| Mode | Article body | Attachments |
|---|---|---|
| **Embedded Images Only** (תמונות בלבד) | the original images of each slide + the explanation | the original images only |
| **Embedded Images + Full Slides** (תמונות ושקופיות) — default | the complete slide + the explanation beneath it | the complete slides and the original images |
| **Full Slides Only** (שקופיות בלבד) | the complete slide + the explanation beneath it | the complete slides only |

Whatever the mode, Qwen analyses the complete slide. Leave **Exclude slide
backgrounds** ticked (the default) so that background pictures, theme/master
graphics and repeated decoration are not treated as presentation images;
screenshots, diagrams and photos are kept. Then **Upload and process**. The file is validated (type,
size, ZIP structure), converted to images in an isolated process and each
slide is sent to Qwen. You are taken to the presentation page, which refreshes
itself while processing runs (status *Converting…*, *Analysing slides…*).

## 3. Review

The presentation page shows:

* the status line with **done / pending / need review / failed** counters, the
  number of embedded images selected for attachment, and a progress bar;
* one card per slide:
  * the **full slide render** — this is the image that was sent to Qwen for
    analysis. In *Embedded Images Only* mode it is not attached to the article;
    in the other two modes it is the image shown in the article body;
  * **Embedded images (attached to the article)** — every picture extracted
    from that slide of the PPTX, with its format, pixel size and properties
    (cropped, rotated, part of a group, reused on N slides), the automatic
    decision and its reasons ("auto-excluded: repeated on many slides (logo?)")
    and — in *Embedded Images Only* mode — an **Include** checkbox that decides
    which images appear in the article body (every original image is attached
    regardless); the choice is saved immediately and kept if the presentation
    is re-processed. In the other modes all original images are attached and
    the slide render is what the body shows, so there is nothing to tick. Pictures the application cannot extract (vector formats)
    are listed as unsupported, never silently replaced by a screenshot.
    Images classified as background/decoration carry a *Background — excluded*
    badge with the reason (slide background picture, picture on the layout/
    master, full-bleed picture behind the content, repeated branding); they are
    neither attached nor shown. After publishing, each attached image shows its
    file name (`004_משואה_750_image_01.png ✔`);
  * the **Heading** (taken from the slide title in the PPTX when there is one)
    and the **Description** text. Edit the text freely and press **Save** (the
    card is marked *edited*); **Revert to AI text** restores the generated
    version; **Preview section** shows exactly the HTML section that will be
    created for this slide, with its images. *Show extracted text* reveals the
    raw text from the PPTX and the speaker notes; *Structured model output*
    shows the JSON fields the model returned.
* slides marked **needs review** (purple) carry a box explaining why the
  model's answer was rejected (for example *describes appearance instead of
  technical meaning*, *copied the slide text*, *answer was cut off*) and the
  model's own notes about unreadable content. Correct the text, then press
  **Accept for publishing** — or **Re-run this slide** to ask the model again.
  *Only needing review* filters the list. The article cannot be created while
  any slide needs review; nothing incomplete is ever published automatically.
* failed slides are highlighted; **Re-run this slide** sends only that slide
  again, **Retry failed slides** retries all of them. *Only failed* filters the list.
* **Cancel** stops a running analysis; **Resume** continues an interrupted or
  partial job without re-sending finished or reviewed slides.
* the presentation title is editable in place (press Enter or click outside).

**Preview article** shows the HTML exactly as it will be created in ServiceNow
(with the local images). **Export JSON** downloads the structured data
(ppt2desc-compatible plus extensions); **Export HTML** downloads a
self-contained HTML file with the images embedded — handy for offline review
or e-mail.

## 4. Create the ServiceNow draft

In *Create ServiceNow Knowledge draft* click **Load from ServiceNow**, pick the
knowledge base, check the **Image output mode** shown for this presentation
(attachment names are meaningful in every mode: `002_תהליך_התחברות.png` for a
slide render, `002_תהליך_התחברות_image_01.png` for an original image),
optionally tick *Attach original PPTX*, then **Create draft article** (enabled only when
all slides are done and none needs review) and confirm. The note under the
buttons tells you how many images will be attached. Progress is shown
(*attachments 12/20* …). On success the box shows **Draft article KB0001234
created** with the sys_id and two links: *Open in ServiceNow* (form) and *View
article*. The article is in **Draft**; publishing follows your normal
knowledge workflow.

If creation fails (network, permissions), the error is shown and **Create draft
article** acts as *retry*: the same article is reused and only the missing
images are uploaded, under the same names — no duplicates. Re-creating after
further edits or image changes updates the same draft. The application never
touches Knowledge articles it did not create.

Changing the **Image output mode** or the **Exclude slide backgrounds** option
after an article exists does nothing by itself: the page shows a notice and the button becomes **Republish with the
new mode**; only that explicit action rewrites the article body and attaches
the images of the new mode (attachments of the previous mode stay on the
article until you remove them in ServiceNow). A retry of a failed publish
always keeps the mode the article was created with.

## 5. Housekeeping

**Presentations** lists all jobs with status and article number. **Delete**
removes the upload, images and generated text from the server. Jobs older than
the configured retention period are removed automatically.
