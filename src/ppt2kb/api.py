"""
REST API used by the web UI.

All endpoints are same-origin JSON; file uploads are multipart. Job and
slide identifiers are validated so they can never be used for path
traversal (job ids are UUID hex, slide numbers are integers, images are
served only from the job's own directory).
"""
from __future__ import annotations

import logging
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field

from . import __version__
from .export import build_article_html, build_standalone_html
from .llm import QwenClient
from .pipeline.processor import sha256_file
from .schemas.deck import JobStatus, SlideStatus
from .security.upload_validation import UploadValidationError, validate_presentation
from .servicenow import PublishError, ServiceNowClient, ServiceNowError, publish_job

logger = logging.getLogger(__name__)
router = APIRouter()

_JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _ctx(request: Request):
    return request.app.state.ctx


def _job_or_404(ctx, job_id: str) -> dict:
    if not _JOB_ID_RE.match(job_id):
        raise HTTPException(404, "job not found")
    job = ctx.db.get_job(job_id)
    if not job:
        raise HTTPException(404, "job not found")
    return job


# ----------------------------------------------------------------- health
@router.get("/health")
async def health(request: Request):
    ctx = _ctx(request)
    from .converters.ppt_converter import find_libreoffice, LibreOfficeNotFoundError

    try:
        lo = str(find_libreoffice(ctx.settings.libreoffice_path))
    except LibreOfficeNotFoundError:
        lo = ""
    return {"status": "ok" if lo else "degraded", "version": __version__, "libreoffice": bool(lo), "uptime_s": int(__import__("time").time() - ctx.started_at)}


@router.post("/shutdown")
async def shutdown(request: Request):
    """Desktop edition only: stop the local server (used by the "Stop PPT2KB" shortcut)."""
    ctx = _ctx(request)
    client_host = request.client.host if request.client else ""
    if not ctx.settings.desktop_mode or client_host not in ("127.0.0.1", "::1"):
        raise HTTPException(404, "not found")
    for j in ctx.db.list_jobs(50):
        if ctx.runner.is_active(j["id"]):
            ctx.runner.cancel(j["id"])
    import os
    import threading
    import time

    hook = getattr(ctx, "shutdown_hook", None)

    def _exit():
        time.sleep(0.3)
        if hook:
            hook()  # graceful: tells the uvicorn server to exit
        else:
            os._exit(0)

    threading.Thread(target=_exit, daemon=True).start()
    return {"ok": True, "detail": "shutting down"}


# ----------------------------------------------------------------- config
class ConfigUpdate(BaseModel):
    values: dict = Field(default_factory=dict)


@router.get("/config")
async def get_config(request: Request):
    return _ctx(request).runtime.public_view()


@router.put("/config")
async def put_config(request: Request, body: ConfigUpdate):
    ctx = _ctx(request)
    rejected = ctx.runtime.update(body.values)
    return {"ok": not rejected, "rejected": rejected, "config": ctx.runtime.public_view()}


@router.delete("/config/secret/{key}")
async def delete_secret(request: Request, key: str):
    ctx = _ctx(request)
    from .runtime import SECRET_KEYS

    if key not in SECRET_KEYS:
        raise HTTPException(404, "unknown secret")
    ctx.runtime.clear_secret(key)
    return {"ok": True}


@router.post("/config/test/qwen")
async def test_qwen(request: Request):
    ctx = _ctx(request)
    try:
        client = QwenClient(ctx.runtime.qwen_config(), "ping")
    except ValueError as e:
        return {"ok": False, "detail": str(e)}
    try:
        return client.ping()
    finally:
        client.close()


@router.post("/config/test/servicenow")
async def test_servicenow(request: Request):
    ctx = _ctx(request)
    try:
        client = ServiceNowClient(ctx.runtime.servicenow_config())
    except ValueError as e:
        return {"ok": False, "detail": str(e)}
    try:
        return client.ping()
    except Exception as e:
        return {"ok": False, "detail": f"{e.__class__.__name__}"}
    finally:
        client.close()


@router.get("/servicenow/knowledge-bases")
async def knowledge_bases(request: Request):
    ctx = _ctx(request)
    try:
        client = ServiceNowClient(ctx.runtime.servicenow_config())
    except ValueError as e:
        raise HTTPException(400, str(e))
    try:
        return {"knowledge_bases": client.list_knowledge_bases(), "default": ctx.runtime.get("servicenow_default_kb")}
    except ServiceNowError as e:
        raise HTTPException(502, str(e))
    finally:
        client.close()


# ------------------------------------------------------------------- jobs
def _job_view(ctx, job: dict, include_slides: bool = True) -> dict:
    counts = ctx.db.slide_status_counts(job["id"])
    out = {
        "id": job["id"],
        "display_name": job["display_name"],
        "title": job["title"],
        "status": job["status"],
        "slide_count": job["slide_count"],
        "created_at": job["created_at"],
        "updated_at": job["updated_at"],
        "error": job["error"],
        "model": job["model"],
        "macro_enabled": job["macro_enabled"],
        "source_size": job["source_size"],
        "kb_sys_id": job["kb_sys_id"],
        "servicenow": job["servicenow"],
        "counts": counts,
        "image_mode": (job.get("options") or {}).get("image_mode", "embedded"),
        "source_kind": job.get("source_kind"),
        "active": ctx.runner.is_active(job["id"]) or job["id"] in ctx.publish_threads and ctx.publish_threads[job["id"]].is_alive(),
    }
    all_images = ctx.db.get_slide_images(job["id"])
    out["images_total"] = len(all_images)
    out["images_selected"] = sum(1 for im in all_images if im["selected"])
    if include_slides:
        images_by_slide: dict = {}
        for im in all_images:
            images_by_slide.setdefault(im["slide_number"], []).append(_image_view(job["id"], im))
        out["slides"] = [
            {
                "number": s.number,
                "images": images_by_slide.get(s.number, []),
                "quality": s.quality,
                "reviewed": s.reviewed,
                "title": s.title,
                "original_text": s.original_text,
                "notes_text": s.notes_text,
                "content": s.content,
                "edited_content": s.edited_content,
                "description": s.description.model_dump() if s.description else None,
                "image_url": f"/api/jobs/{job['id']}/slides/{s.number}/image",
                "status": s.status.value,
                "error": s.error,
                "attempts": s.attempts,
                "processed_at": s.processed_at,
                "render_error": s.render_error,
            }
            for s in ctx.db.get_slides(job["id"])
        ]
    return out


def _image_view(job_id: str, im: dict) -> dict:
    return {
        "idx": im["idx"],
        "slide_number": im["slide_number"],
        "url": f"/api/jobs/{job_id}/slides/{im['slide_number']}/images/{im['idx']}" if im["file_ref"] else None,
        "file_ref": im["file_ref"],
        "format": im["file_ext"],
        "original_format": im["original_ext"],
        "width": im["width"],
        "height": im["height"],
        "shape_name": im["shape_name"],
        "source_kind": im["source_kind"],
        "cropped": im["cropped"],
        "rotation": im["rotation"],
        "in_group": im["in_group"],
        "reuse_count": im["reuse_count"],
        "supported": im["supported"],
        "selected": im["selected"],
        "auto_selected": im["auto_selected"],
        "score": im["score"],
        "reasons": im["reasons"],
        "flagged": im["flagged"],
        "note": im["note"],
        "file_name": im["file_name"],
        "attachment_sys_id": im["attachment_sys_id"],
    }


@router.get("/jobs")
async def list_jobs(request: Request):
    ctx = _ctx(request)
    return {"jobs": [_job_view(ctx, j, include_slides=False) for j in ctx.db.list_jobs()]}


@router.post("/jobs", status_code=201)
async def create_job(request: Request, file: UploadFile = File(...), title: str = Form(""), autostart: bool = Form(True)):
    ctx = _ctx(request)
    s = ctx.settings
    job_id = uuid.uuid4().hex
    max_bytes = s.max_upload_mb * 1024 * 1024
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".ppt", ".pptx", ".pps", ".ppsx", ".potx"):
        raise HTTPException(400, "Only PowerPoint files (.pptx, .ppt) are accepted")
    dest = s.upload_dir / f"{job_id}{ext if ext in ('.ppt', '.pptx') else '.pptx'}"
    size = 0
    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(413, f"File exceeds the maximum allowed size of {s.max_upload_mb} MB")
                out.write(chunk)
        result = validate_presentation(
            dest,
            file.filename or "presentation.pptx",
            max_bytes=max_bytes,
            max_zip_entries=s.max_zip_entries,
            max_zip_uncompressed=s.max_zip_uncompressed_mb * 1024 * 1024,
            max_zip_ratio=s.max_zip_ratio,
        )
    except UploadValidationError as e:
        dest.unlink(missing_ok=True)
        logger.warning("Upload rejected: %s", e)
        raise HTTPException(400, str(e))
    except HTTPException:
        dest.unlink(missing_ok=True)
        raise
    except Exception:
        dest.unlink(missing_ok=True)
        logger.exception("Upload failed")
        raise HTTPException(500, "upload failed")

    ctx.db.create_job(
        job_id=job_id,
        display_name=result.display_name,
        title=(title or "").strip()[:160],
        source_path=str(dest),
        source_sha256=sha256_file(dest),
        source_kind=result.kind,
        source_size=result.size_bytes,
        macro_enabled=result.macro_enabled,
        options={"image_mode": str(ctx.runtime.get("image_attachment_mode") or "embedded")},
    )
    (s.jobs_dir / job_id).mkdir(parents=True, exist_ok=True)
    if autostart:
        ctx.runner.submit(job_id)
    job = ctx.db.get_job(job_id)
    return _job_view(ctx, job)


@router.get("/jobs/{job_id}")
async def get_job(request: Request, job_id: str, slides: bool = True):
    ctx = _ctx(request)
    job = _job_or_404(ctx, job_id)
    return _job_view(ctx, job, include_slides=slides)


class JobUpdate(BaseModel):
    title: Optional[str] = None
    kb_sys_id: Optional[str] = None
    image_mode: Optional[str] = None


@router.patch("/jobs/{job_id}")
async def update_job(request: Request, job_id: str, body: JobUpdate):
    ctx = _ctx(request)
    _job_or_404(ctx, job_id)
    fields = {}
    if body.title is not None:
        fields["title"] = body.title.strip()[:160]
    if body.kb_sys_id is not None:
        if not re.match(r"^[0-9a-fA-F]{0,32}$", body.kb_sys_id):
            raise HTTPException(400, "invalid knowledge base id")
        fields["kb_sys_id"] = body.kb_sys_id
    if body.image_mode is not None:
        if body.image_mode not in ("embedded", "full_slide"):
            raise HTTPException(400, "image_mode must be embedded or full_slide")
        job = ctx.db.get_job(job_id)
        opts = dict(job.get("options") or {})
        opts["image_mode"] = body.image_mode
        fields["options"] = opts
    ctx.db.update_job(job_id, **fields)
    return _job_view(ctx, ctx.db.get_job(job_id), include_slides=False)


@router.delete("/jobs/{job_id}")
async def delete_job(request: Request, job_id: str):
    ctx = _ctx(request)
    job = _job_or_404(ctx, job_id)
    if ctx.runner.is_active(job_id):
        ctx.runner.cancel(job_id)
        raise HTTPException(409, "job is processing; cancel requested - try again shortly")
    shutil.rmtree(ctx.settings.jobs_dir / job_id, ignore_errors=True)
    Path(job["source_path"]).unlink(missing_ok=True)
    ctx.db.delete_job(job_id)
    return {"ok": True}


@router.post("/jobs/{job_id}/start")
@router.post("/jobs/{job_id}/resume")
async def resume_job(request: Request, job_id: str):
    ctx = _ctx(request)
    job = _job_or_404(ctx, job_id)
    if job["status"] in (JobStatus.converting.value, JobStatus.describing.value, JobStatus.publishing.value):
        raise HTTPException(409, "job is already running")
    try:
        ctx.runner.submit(job_id)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


class RetryRequest(BaseModel):
    slides: List[int] = Field(default_factory=list)  # empty = all failed/pending


@router.post("/jobs/{job_id}/retry")
async def retry_slides(request: Request, job_id: str, body: RetryRequest):
    ctx = _ctx(request)
    job = _job_or_404(ctx, job_id)
    if ctx.runner.is_active(job_id):
        raise HTTPException(409, "job is already running")
    existing = {s.number for s in ctx.db.get_slides(job_id)}
    if not existing:
        raise HTTPException(409, "job has no slides yet; use resume")
    numbers = [n for n in body.slides if n in existing] if body.slides else None
    if body.slides and not numbers:
        raise HTTPException(400, "no valid slide numbers")
    try:
        ctx.runner.submit(job_id, phase="describe", slides=numbers)
    except RuntimeError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "slides": numbers}


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(request: Request, job_id: str):
    ctx = _ctx(request)
    _job_or_404(ctx, job_id)
    return {"ok": ctx.runner.cancel(job_id)}


# ----------------------------------------------------------------- slides
class SlideUpdate(BaseModel):
    edited_content: Optional[str] = None
    title: Optional[str] = None
    reset: bool = False


@router.patch("/jobs/{job_id}/slides/{number}")
async def update_slide(request: Request, job_id: str, number: int, body: SlideUpdate):
    ctx = _ctx(request)
    _job_or_404(ctx, job_id)
    slide = ctx.db.get_slide(job_id, number)
    if not slide:
        raise HTTPException(404, "slide not found")
    fields = {}
    if body.reset:
        fields["edited_content"] = None
    elif body.edited_content is not None:
        fields["edited_content"] = body.edited_content[:100_000]
    if body.title is not None:
        fields["title"] = body.title.strip()[:300]
    ctx.db.update_slide(job_id, number, **fields)
    s = ctx.db.get_slide(job_id, number)
    return {"number": s.number, "title": s.title, "content": s.content, "edited_content": s.edited_content, "status": s.status.value}


@router.get("/jobs/{job_id}/slides/{number}/image")
async def slide_image(request: Request, job_id: str, number: int):
    ctx = _ctx(request)
    _job_or_404(ctx, job_id)
    slide = ctx.db.get_slide(job_id, number)
    if not slide or not slide.image_ref:
        raise HTTPException(404, "image not found")
    base = (ctx.settings.jobs_dir / job_id).resolve()
    path = (base / slide.image_ref).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404, "image not found")
    media = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return FileResponse(str(path), media_type=media, headers={"Cache-Control": "private, max-age=3600"})


@router.get("/jobs/{job_id}/slides/{number}/images/{idx}")
async def slide_embedded_image(request: Request, job_id: str, number: int, idx: int):
    ctx = _ctx(request)
    _job_or_404(ctx, job_id)
    rows = [im for im in ctx.db.get_slide_images(job_id, number) if im["idx"] == idx]
    if not rows or not rows[0]["file_ref"]:
        raise HTTPException(404, "image not found")
    base = (ctx.settings.jobs_dir / job_id).resolve()
    path = (base / rows[0]["file_ref"]).resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(404, "image not found")
    media = "image/jpeg" if path.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return FileResponse(str(path), media_type=media, headers={"Cache-Control": "private, max-age=3600"})


class ImageUpdate(BaseModel):
    selected: bool


@router.patch("/jobs/{job_id}/slides/{number}/images/{idx}")
async def update_slide_image(request: Request, job_id: str, number: int, idx: int, body: ImageUpdate):
    """Manually include/exclude an embedded image from the Knowledge article."""
    ctx = _ctx(request)
    _job_or_404(ctx, job_id)
    rows = [im for im in ctx.db.get_slide_images(job_id, number) if im["idx"] == idx]
    if not rows:
        raise HTTPException(404, "image not found")
    if body.selected and not rows[0]["supported"]:
        raise HTTPException(400, "this image could not be extracted and cannot be attached")
    ctx.db.update_slide_image(job_id, number, idx, selected=body.selected)
    rows = [im for im in ctx.db.get_slide_images(job_id, number) if im["idx"] == idx]
    return _image_view(job_id, rows[0])


@router.post("/jobs/{job_id}/slides/{number}/accept")
async def accept_slide(request: Request, job_id: str, number: int):
    """Reviewer accepts a needs_review slide (after editing) so the article can be published."""
    ctx = _ctx(request)
    _job_or_404(ctx, job_id)
    slide = ctx.db.get_slide(job_id, number)
    if not slide:
        raise HTTPException(404, "slide not found")
    if slide.status not in (SlideStatus.needs_review, SlideStatus.done):
        raise HTTPException(409, "slide is not in a reviewable state")
    ctx.db.update_slide(job_id, number, status=SlideStatus.done, reviewed=True, error=None)
    ctx.runner._finalize(job_id)
    return {"ok": True, "number": number, "status": "done"}


@router.post("/jobs/{job_id}/images/extract")
async def extract_images(request: Request, job_id: str):
    """(Re-)extract the embedded images of the PPTX - e.g. for presentations processed by an older version."""
    ctx = _ctx(request)
    job = _job_or_404(ctx, job_id)
    if ctx.runner.is_active(job_id):
        raise HTTPException(409, "job is processing")
    if job["source_kind"] != "pptx":
        raise HTTPException(400, "embedded image extraction is only available for .pptx files")
    n = ctx.runner.extract_images(job_id)
    return {"ok": True, "images": n}


# ----------------------------------------------------------------- export
@router.get("/jobs/{job_id}/export.json")
async def export_json(request: Request, job_id: str):
    ctx = _ctx(request)
    _job_or_404(ctx, job_id)
    deck = ctx.db.deck(job_id)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(deck.deck).stem) or "presentation"
    return Response(
        content=deck.model_dump_json(indent=2, exclude_none=True),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
    )


@router.get("/jobs/{job_id}/export.html")
async def export_html(request: Request, job_id: str, embed: bool = True):
    ctx = _ctx(request)
    job = _job_or_404(ctx, job_id)
    slides = _slides_with_images(ctx, job_id)
    mode = (job.get("options") or {}).get("image_mode", "embedded")
    html = build_standalone_html(title=job["title"] or job["display_name"], slides=slides, job_dir=ctx.settings.jobs_dir / job_id, embed_images=embed, mode=mode)
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(job["display_name"]).stem) or "presentation"
    return Response(content=html, media_type="text/html; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{name}.html"'})


@router.get("/jobs/{job_id}/preview.html")
async def preview_html(request: Request, job_id: str, slide: Optional[int] = None):
    """Article body exactly as it will be sent to ServiceNow, with local image URLs.

    ``?slide=N`` previews the section of one slide only (same renderer, same markup)."""
    ctx = _ctx(request)
    job = _job_or_404(ctx, job_id)
    slides = _slides_with_images(ctx, job_id)
    if slide is not None:
        slides = [s for s in slides if s.number == slide]
        if not slides:
            raise HTTPException(404, "slide not found")
    mode = (job.get("options") or {}).get("image_mode", "embedded")
    body = build_article_html(
        title=job["title"] or job["display_name"],
        slides=slides,
        image_src=(lambda s: f"/api/jobs/{job_id}/slides/{s.number}/image") if mode == "full_slide" else None,
        figures_for=(lambda s: [(f"/api/jobs/{job_id}/slides/{s.number}/images/{im['idx']}", f"{s.title or 'slide ' + str(s.number)} - image {im['idx']}") for im in s.images if im.get("selected") and im.get("file_ref")]) if mode == "embedded" else None,
        deck_name=job["display_name"],
        sections_only=slide is not None,
    )
    return Response(content=body, media_type="text/html; charset=utf-8")


def _slides_with_images(ctx, job_id: str):
    slides = ctx.db.get_slides(job_id)
    by_slide: dict = {}
    for im in ctx.db.get_slide_images(job_id):
        by_slide.setdefault(im["slide_number"], []).append(im)
    for s in slides:
        s.images = by_slide.get(s.number, [])
    return slides


# ---------------------------------------------------------------- publish
class PublishRequest(BaseModel):
    kb_sys_id: str = ""
    attach_pptx: Optional[bool] = None
    force_new: bool = False
    image_mode: Optional[str] = None  # embedded | full_slide (default: the job's mode)


@router.post("/jobs/{job_id}/publish", status_code=202)
async def publish(request: Request, job_id: str, body: PublishRequest):
    ctx = _ctx(request)
    job = _job_or_404(ctx, job_id)
    if ctx.runner.is_active(job_id):
        raise HTTPException(409, "job is still processing")
    t = ctx.publish_threads.get(job_id)
    if t and t.is_alive():
        raise HTTPException(409, "publishing already in progress")
    counts = ctx.db.slide_status_counts(job_id)
    if counts.get("needs_review"):
        raise HTTPException(409, f"{counts['needs_review']} slide(s) need review: edit and accept them (or re-run) before publishing")
    if counts["done"] != job["slide_count"] or job["slide_count"] == 0:
        raise HTTPException(409, "all slides must be processed before publishing")
    mode = body.image_mode or (job.get("options") or {}).get("image_mode") or "embedded"
    if mode not in ("embedded", "full_slide"):
        raise HTTPException(400, "image_mode must be embedded or full_slide")
    if mode == "embedded" and job["source_kind"] == "pptx" and not ctx.db.get_slide_images(job_id):
        ctx.runner.extract_images(job_id)  # presentation processed by an older version
    ascii_names = bool(ctx.runtime.get("ascii_filenames"))
    kb = body.kb_sys_id or job["kb_sys_id"] or str(ctx.runtime.get("servicenow_default_kb") or "")
    if not re.match(r"^[0-9a-fA-F]{32}$", kb):
        raise HTTPException(400, "a valid knowledge base must be selected")
    try:
        client = ServiceNowClient(ctx.runtime.servicenow_config())
    except ValueError as e:
        raise HTTPException(400, str(e))
    attach = body.attach_pptx if body.attach_pptx is not None else bool(ctx.runtime.get("servicenow_attach_pptx"))

    st = dict(job.get("servicenow") or {})
    st["progress"] = {"stage": "starting", "done": 0, "total": 0}
    ctx.db.update_job(job_id, servicenow=st, kb_sys_id=kb, status=JobStatus.publishing)

    def progress(stage: str, done: int, total: int):
        j = ctx.db.get_job(job_id)
        s2 = dict(j.get("servicenow") or {})
        s2["progress"] = {"stage": stage, "done": done, "total": total}
        ctx.db.update_job(job_id, servicenow=s2)

    def run():
        try:
            publish_job(ctx.db, client, job_id, kb_sys_id=kb, jobs_dir=ctx.settings.jobs_dir, attach_pptx=attach, force_new=body.force_new,
                        image_mode=mode, ascii_filenames=ascii_names, progress=progress)
        except PublishError:
            pass
        except Exception as e:  # pragma: no cover
            logger.exception("publish crashed: %s", e.__class__.__name__)
            j = ctx.db.get_job(job_id)
            s2 = dict(j.get("servicenow") or {})
            s2["error"] = f"internal error: {e.__class__.__name__}"
            ctx.db.update_job(job_id, status=JobStatus.publish_failed, servicenow=s2)
        finally:
            client.close()

    th = threading.Thread(target=run, name=f"publish-{job_id[:8]}", daemon=True)
    ctx.publish_threads[job_id] = th
    th.start()
    return {"ok": True, "status": "publishing"}
