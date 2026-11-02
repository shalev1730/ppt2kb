"""
Publish a processed presentation as ONE draft Knowledge article.

Steps (each step is persisted in ``jobs.servicenow`` so a partial failure can
be resumed without creating duplicates):

  1. duplicate check   - local record, then remote search for the job marker
  2. create article    - kb_knowledge draft with a preliminary body
  3. upload images     - Attachment API; in *embedded* mode the selected
                         embedded images with meaningful names, in
                         *full_slide* mode the rendered slide screenshots.
                         Already-uploaded files (by recorded sys_id or by
                         file name on the record) are reused, never re-sent.
  4. optional PPTX     - original presentation as attachment
  5. final body        - HTML with <figure><img src="/sys_attachment.do?sys_id=..."> under each slide
  6. record result     - number, sys_id, links

The article is never moved out of ``draft``; publication stays with the
normal ServiceNow review workflow. An article created earlier is only
updated when the user publishes the same job again (same marker).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from ..export.filenames import attachment_filename
from ..export.html import build_article_html, job_marker, _heading_for
from ..schemas.deck import JobStatus, SlideData, SlideStatus
from ..storage.db import Database
from .client import ServiceNowClient, ServiceNowError

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str, int, int], None]


class PublishError(Exception):
    pass


def _content_type(ext: str) -> str:
    return "image/jpeg" if ext.lower() in ("jpg", "jpeg") else "image/png"


def publish_job(
    db: Database,
    client: ServiceNowClient,
    job_id: str,
    *,
    kb_sys_id: str,
    jobs_dir: Path,
    attach_pptx: bool = False,
    force_new: bool = False,
    image_mode: Optional[str] = None,
    ascii_filenames: bool = False,
    progress: Optional[ProgressCb] = None,
) -> dict:
    job = db.get_job(job_id)
    if not job:
        raise PublishError("job not found")
    if job["status"] in (JobStatus.converting.value, JobStatus.describing.value):
        raise PublishError("job is still processing")
    slides = db.get_slides(job_id)
    if not slides:
        raise PublishError("job has no slides")
    not_done = [s.number for s in slides if s.status != SlideStatus.done]
    if not_done:
        raise PublishError(f"slides not processed or not reviewed: {not_done[:20]}{'...' if len(not_done) > 20 else ''}")
    if not kb_sys_id:
        raise PublishError("knowledge base not selected")
    mode = image_mode or (job.get("options") or {}).get("image_mode") or "embedded"
    if mode not in ("embedded", "full_slide"):
        raise PublishError(f"unknown image mode {mode}")

    state: Dict = dict(job.get("servicenow") or {})
    marker = job_marker(job_id)
    title = job["title"] or job["display_name"]

    def _save(**kw):
        state.update(kw)
        db.update_job(job_id, servicenow=state)

    def _progress(stage: str, done: int, total: int):
        if progress:
            progress(stage, done, total)

    db.update_job(job_id, status=JobStatus.publishing, kb_sys_id=kb_sys_id)
    try:
        # 1) duplicate protection ------------------------------------------------
        sys_id = "" if force_new else state.get("sys_id", "")
        number = state.get("number", "")
        if sys_id:
            existing = client.get_article(sys_id)
            if existing is None:
                logger.info("Previously created article no longer exists; creating a new one")
                sys_id, number = "", ""
            else:
                number = existing.get("number", number)
        if not sys_id and not force_new:
            remote = client.find_article_by_marker(marker)
            if remote:
                sys_id = remote["sys_id"]
                number = remote.get("number", "")
                logger.info("Found existing article for this job on ServiceNow; reusing it")
        # 2) create -------------------------------------------------------------
        if not sys_id:
            _progress("create", 0, 1)
            placeholder = f"{marker}<p>Importing presentation, please wait...</p>"
            created = client.create_article(short_description=title, text_html=placeholder, kb_sys_id=kb_sys_id)
            sys_id = created["sys_id"]
            number = created.get("number", "")
            _save(sys_id=sys_id, number=number, kb_sys_id=kb_sys_id, stage="created", image_mode=mode)
            _progress("create", 1, 1)
        else:
            _save(sys_id=sys_id, number=number, kb_sys_id=kb_sys_id, image_mode=mode)

        # 3) images -------------------------------------------------------------
        remote_attachments = {a["file_name"]: a["sys_id"] for a in client.list_attachments("kb_knowledge", sys_id)}
        remote_ids = set(remote_attachments.values())
        if mode == "embedded":
            _upload_embedded(db, client, job_id, sys_id, slides, jobs_dir, remote_attachments, remote_ids, ascii_filenames, _progress)
        else:
            _upload_full_slides(db, client, job_id, sys_id, slides, jobs_dir, remote_attachments, remote_ids, _progress)
        _save(stage="attachments_done")

        # 4) optional PPTX ------------------------------------------------------
        if attach_pptx and not state.get("pptx_attachment_sys_id"):
            src = Path(job["source_path"])
            if src.is_file():
                name = job["display_name"] if job["display_name"].lower().endswith((".ppt", ".pptx")) else job["display_name"] + ".pptx"
                if name in remote_attachments:
                    _save(pptx_attachment_sys_id=remote_attachments[name])
                else:
                    ctype = "application/vnd.openxmlformats-officedocument.presentationml.presentation" if name.lower().endswith(".pptx") else "application/vnd.ms-powerpoint"
                    res = client.upload_attachment("kb_knowledge", sys_id, name, ctype, src.read_bytes())
                    _save(pptx_attachment_sys_id=res["sys_id"])

        # 5) final HTML body ----------------------------------------------------
        slides = db.get_slides(job_id)
        html = build_article_html(
            title=title,
            slides=slides,
            image_src=(lambda s: _full_slide_src(db, job_id, s)) if mode == "full_slide" else None,
            figures_for=(lambda s: _embedded_figures(db, job_id, s)) if mode == "embedded" else None,
            marker=marker,
            deck_name=job["display_name"],
        )
        _progress("body", 0, 1)
        updated = client.update_article(sys_id, {"text": html, "short_description": title[:160]})
        number = updated.get("number", number)
        links = client.article_links(sys_id, number)
        n_att = len(db.image_attachment_map(job_id)) if mode == "embedded" else len(db.attachment_map(job_id))
        _save(stage="done", number=number, links=links, workflow_state=updated.get("workflow_state", "draft"), error=None, attachments=n_att)
        _progress("body", 1, 1)
        db.update_job(job_id, status=JobStatus.published, servicenow=state)
        return state
    except (ServiceNowError, PublishError) as e:
        logger.error("Publishing job %s failed: %s", job_id, e)
        _save(error=str(e))
        db.update_job(job_id, status=JobStatus.publish_failed, servicenow=state)
        raise PublishError(str(e)) from e


# ------------------------------------------------------------------ helpers
def _full_slide_src(db: Database, job_id: str, s: SlideData) -> str:
    m = db.attachment_map(job_id)
    return f"/sys_attachment.do?sys_id={m[s.number]}" if s.number in m else ""


def _embedded_figures(db: Database, job_id: str, s: SlideData) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for im in db.get_slide_images(job_id, s.number):
        if im["selected"] and im["attachment_sys_id"]:
            out.append((f"/sys_attachment.do?sys_id={im['attachment_sys_id']}", f"{_heading_for(s)} - image {im['idx']}"))
    return out


def _upload_full_slides(db, client, job_id, sys_id, slides, jobs_dir, remote_attachments, remote_ids, progress):
    attachment_map = db.attachment_map(job_id)
    total = len(slides)
    for i, s in enumerate(slides, start=1):
        file_name = Path(s.image_ref).name
        if s.number in attachment_map and attachment_map[s.number] in remote_ids:
            progress("attachments", i, total)
            continue
        if file_name in remote_attachments:
            db.update_slide(job_id, s.number, attachment_sys_id=remote_attachments[file_name])
            progress("attachments", i, total)
            continue
        img_path = jobs_dir / job_id / s.image_ref
        if not img_path.is_file():
            raise PublishError(f"image for slide {s.number} is missing on disk")
        res = client.upload_attachment("kb_knowledge", sys_id, file_name, _content_type(img_path.suffix.lstrip(".")), img_path.read_bytes())
        db.update_slide(job_id, s.number, attachment_sys_id=res["sys_id"])
        progress("attachments", i, total)


def _upload_embedded(db, client, job_id, sys_id, slides, jobs_dir, remote_attachments, remote_ids, ascii_filenames, progress):
    """Upload the selected embedded images with meaningful, unique file names."""
    by_slide = {s.number: s for s in slides}
    images = [im for im in db.get_slide_images(job_id) if im["selected"] and im["file_ref"]]
    used: set = set()
    # names already present on the record keep their place (stable across retries)
    for im in images:
        if im["file_name"]:
            used.add(im["file_name"].lower())
    total = len(images)
    counters: Dict[int, int] = {}
    for i, im in enumerate(images, start=1):
        s = by_slide.get(im["slide_number"])
        if s is None:
            continue
        counters[s.number] = counters.get(s.number, 0) + 1
        name = im["file_name"]
        if not name:
            name = attachment_filename(s.number, _heading_for(s), counters[s.number], im["file_ext"], used=used, ascii_only=ascii_filenames)
            db.update_slide_image(job_id, s.number, im["idx"], file_name=name)
        if im["attachment_sys_id"] and im["attachment_sys_id"] in remote_ids:
            progress("attachments", i, total)
            continue
        if name in remote_attachments:
            db.update_slide_image(job_id, s.number, im["idx"], attachment_sys_id=remote_attachments[name])
            progress("attachments", i, total)
            continue
        path = jobs_dir / job_id / im["file_ref"]
        if not path.is_file():
            raise PublishError(f"embedded image {im['idx']} of slide {s.number} is missing on disk")
        res = client.upload_attachment("kb_knowledge", sys_id, name, _content_type(im["file_ext"]), path.read_bytes())
        db.update_slide_image(job_id, s.number, im["idx"], attachment_sys_id=res["sys_id"])
        remote_attachments[name] = res["sys_id"]
        remote_ids.add(res["sys_id"])
        progress("attachments", i, total)
