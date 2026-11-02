"""
Publish a processed presentation as ONE draft Knowledge article.

Steps (each step is persisted in ``jobs.servicenow`` so a partial failure can
be resumed without creating duplicates):

  1. duplicate check   - local record, then remote search for the job marker
  2. create article    - kb_knowledge draft with a preliminary body
  3. upload images     - Attachment API, one file per slide (skip already uploaded)
  4. optional PPTX     - original presentation as attachment
  5. final body        - HTML with <img src="/sys_attachment.do?sys_id=..."> per slide
  6. record result     - number, sys_id, links

The article is never moved out of ``draft``; publication stays with the
normal ServiceNow review workflow.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Dict, Optional

from ..export.html import build_article_html, job_marker
from ..schemas.deck import JobStatus
from ..storage.db import Database
from .client import ServiceNowClient, ServiceNowError

logger = logging.getLogger(__name__)

ProgressCb = Callable[[str, int, int], None]


class PublishError(Exception):
    pass


def publish_job(
    db: Database,
    client: ServiceNowClient,
    job_id: str,
    *,
    kb_sys_id: str,
    jobs_dir: Path,
    attach_pptx: bool = False,
    force_new: bool = False,
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
    failed = [s.number for s in slides if s.status.value != "done"]
    if failed:
        raise PublishError(f"slides not processed: {failed[:20]}{'...' if len(failed) > 20 else ''}")
    if not kb_sys_id:
        raise PublishError("knowledge base not selected")

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
            _save(sys_id=sys_id, number=number, kb_sys_id=kb_sys_id, stage="created")
            _progress("create", 1, 1)
        else:
            _save(sys_id=sys_id, number=number, kb_sys_id=kb_sys_id)

        # 3) images -------------------------------------------------------------
        attachment_map = db.attachment_map(job_id)
        remote_attachments = {a["file_name"]: a["sys_id"] for a in client.list_attachments("kb_knowledge", sys_id)}
        total = len(slides)
        for i, s in enumerate(slides, start=1):
            file_name = Path(s.image_ref).name
            if s.number in attachment_map and attachment_map[s.number] in remote_attachments.values():
                _progress("attachments", i, total)
                continue
            if file_name in remote_attachments:
                db.update_slide(job_id, s.number, attachment_sys_id=remote_attachments[file_name])
                _progress("attachments", i, total)
                continue
            img_path = jobs_dir / job_id / s.image_ref
            if not img_path.is_file():
                raise PublishError(f"image for slide {s.number} is missing on disk")
            ctype = "image/jpeg" if img_path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
            res = client.upload_attachment("kb_knowledge", sys_id, file_name, ctype, img_path.read_bytes())
            db.update_slide(job_id, s.number, attachment_sys_id=res["sys_id"])
            _progress("attachments", i, total)
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
        attachment_map = db.attachment_map(job_id)
        slides = db.get_slides(job_id)
        html = build_article_html(
            title=title,
            slides=slides,
            image_src=lambda s: f"/sys_attachment.do?sys_id={attachment_map[s.number]}" if s.number in attachment_map else "",
            marker=marker,
            deck_name=job["display_name"],
        )
        _progress("body", 0, 1)
        updated = client.update_article(sys_id, {"text": html, "short_description": title[:160]})
        number = updated.get("number", number)
        links = client.article_links(sys_id, number)
        _save(stage="done", number=number, links=links, workflow_state=updated.get("workflow_state", "draft"), error=None)
        _progress("body", 1, 1)
        db.update_job(job_id, status=JobStatus.published, servicenow=state)
        return state
    except (ServiceNowError, PublishError) as e:
        logger.error("Publishing job %s failed: %s", job_id, e)
        _save(error=str(e))
        db.update_job(job_id, status=JobStatus.publish_failed, servicenow=state)
        raise PublishError(str(e)) from e
