"""
Job processing pipeline.

Adapted from ppt2desc ``src/processor.py`` (MIT, (c) 2025 Adam Łucek):
the "convert -> render -> describe each slide concurrently with a rate
limiter -> keep partial results" flow is preserved. Instead of partial JSON
files, every slide result is written to SQLite as soon as it completes, so:

  * a crash/restart leaves the job in ``interrupted`` state and it can be
    resumed (only slides without a result are sent to the model again);
  * individual failed slides can be retried without touching the others;
  * the UI can show live progress (done / pending / failed).
"""
from __future__ import annotations

import hashlib
import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from queue import Queue, Empty
from typing import Dict, Iterable, List, Optional

from ..config import Settings
from ..converters import ConversionError, convert_pdf_to_images, convert_pptx_to_pdf
from ..llm import QwenClient, ThreadSafeRateLimiter
from ..llm.qwen import QwenError
from ..prompt import build_user_prompt
from ..runtime import RuntimeConfig
from ..schemas.deck import JobStatus, SlideData, SlideStatus
from ..storage.db import Database, now_iso

logger = logging.getLogger(__name__)

MAX_ORIGINAL_TEXT = 8000


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def extract_pptx_text(path: Path, max_slides: int) -> Dict[int, dict]:
    """Extract title / text / notes per slide with python-pptx (PPTX only).

    Failures are non-fatal: the slide image is the authoritative source.
    """
    result: Dict[int, dict] = {}
    try:
        from pptx import Presentation
        from pptx.util import Emu  # noqa: F401 - ensures package import works

        prs = Presentation(str(path))
        for idx, slide in enumerate(prs.slides, start=1):
            if idx > max_slides:
                break
            title = ""
            texts: List[str] = []
            try:
                if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
                    title = slide.shapes.title.text_frame.text.strip()
            except Exception:
                title = ""
            for shape in slide.shapes:
                try:
                    if shape.has_text_frame:
                        t = shape.text_frame.text.strip()
                        if t and t != title:
                            texts.append(t)
                    elif getattr(shape, "has_table", False) and shape.has_table:
                        for row in shape.table.rows:
                            cells = [c.text.strip() for c in row.cells]
                            texts.append(" | ".join(c for c in cells if c))
                except Exception:
                    continue
            notes = ""
            try:
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
            except Exception:
                notes = ""
            result[idx] = {
                "title": title[:300],
                "text": "\n".join(texts)[:MAX_ORIGINAL_TEXT],
                "notes": notes[:MAX_ORIGINAL_TEXT],
            }
    except Exception as e:  # pragma: no cover - depends on input
        logger.warning("Text extraction with python-pptx failed (non-fatal): %s", e.__class__.__name__)
    return result


class JobRunner:
    """Background worker that executes jobs sequentially (or N in parallel)."""

    def __init__(self, settings: Settings, db: Database, runtime: RuntimeConfig):
        self.settings = settings
        self.db = db
        self.runtime = runtime
        self._queue: "Queue[tuple[str, dict]]" = Queue()
        self._cancel: Dict[str, threading.Event] = {}
        self._active: set[str] = set()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []
        self.client_factory = self._default_client_factory  # overridable in tests

    # --------------------------------------------------------------- lifecycle
    def start(self) -> None:
        self.recover_interrupted()
        for i in range(max(1, self.settings.max_concurrent_jobs)):
            t = threading.Thread(target=self._worker, name=f"ppt2kb-worker-{i}", daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self) -> None:
        self._stop.set()
        for ev in list(self._cancel.values()):
            ev.set()

    def recover_interrupted(self) -> None:
        """Mark jobs that were running when the process died."""
        for job in self.db.jobs_with_status([JobStatus.converting.value, JobStatus.describing.value]):
            logger.warning("Job %s was interrupted (status %s); marking as interrupted", job["id"], job["status"])
            self.db.update_job(job["id"], status=JobStatus.interrupted, error="processing was interrupted; resume to continue")
            for s in self.db.get_slides(job["id"]):
                if s.status == SlideStatus.processing:
                    self.db.update_slide(job["id"], s.number, status=SlideStatus.pending)
        for job in self.db.jobs_with_status([JobStatus.publishing.value]):
            st = dict(job.get("servicenow") or {})
            st["error"] = "publishing was interrupted; run publish again to resume"
            self.db.update_job(job["id"], status=JobStatus.publish_failed, servicenow=st)

    # ------------------------------------------------------------------ queue
    def submit(self, job_id: str, *, phase: str = "all", slides: Optional[Iterable[int]] = None) -> None:
        with self._lock:
            if job_id in self._active:
                raise RuntimeError("job is already being processed")
            self._active.add(job_id)
            self._cancel[job_id] = threading.Event()
        self._queue.put((job_id, {"phase": phase, "slides": list(slides) if slides else None}))

    def cancel(self, job_id: str) -> bool:
        ev = self._cancel.get(job_id)
        if ev:
            ev.set()
            return True
        return False

    def is_active(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._active

    def _worker(self) -> None:
        while not self._stop.is_set():
            try:
                job_id, opts = self._queue.get(timeout=0.5)
            except Empty:
                continue
            try:
                self.run(job_id, **opts)
            except Exception as e:  # pragma: no cover - last resort
                logger.exception("Unhandled error in job %s: %s", job_id, e.__class__.__name__)
                self.db.update_job(job_id, status=JobStatus.failed, error=f"internal error: {e.__class__.__name__}")
            finally:
                with self._lock:
                    self._active.discard(job_id)
                    self._cancel.pop(job_id, None)
                self._queue.task_done()

    # --------------------------------------------------------------- pipeline
    def job_dir(self, job_id: str) -> Path:
        return self.settings.jobs_dir / job_id

    def run(self, job_id: str, *, phase: str = "all", slides: Optional[List[int]] = None) -> None:
        job = self.db.get_job(job_id)
        if not job:
            return
        cancel = self._cancel.get(job_id) or threading.Event()
        try:
            if phase in ("all", "convert"):
                need_convert = job["status"] in (JobStatus.uploaded.value, JobStatus.failed.value) or not self.db.get_slides(job_id)
                if job["status"] == JobStatus.interrupted.value and not self._images_complete(job_id):
                    need_convert = True
                if need_convert:
                    self._convert(job_id, job)
            if phase == "convert":
                self._finalize(job_id)
                return
            self._describe(job_id, only=slides, cancel=cancel)
            self._finalize(job_id)
        except ConversionError as e:
            logger.error("Conversion failed for job %s: %s", job_id, e)
            self.db.update_job(job_id, status=JobStatus.failed, error=f"conversion failed: {e}")
        except QwenError as e:
            logger.error("Model configuration error for job %s: %s", job_id, e)
            self.db.update_job(job_id, status=JobStatus.partial, error=f"model error: {e}")
        except (ValueError, OSError) as e:  # configuration problems (missing URL / model / CA file)
            logger.error("Configuration error for job %s: %s", job_id, e)
            self._finalize(job_id, error=f"configuration error: {e}")

    def _images_complete(self, job_id: str) -> bool:
        slides = self.db.get_slides(job_id)
        if not slides:
            return False
        return all((self.job_dir(job_id) / s.image_ref).is_file() for s in slides)

    def _convert(self, job_id: str, job: dict) -> None:
        self.db.update_job(job_id, status=JobStatus.converting, error=None)
        jd = self.job_dir(job_id)
        images_dir = jd / "images"
        if images_dir.exists():
            shutil.rmtree(images_dir, ignore_errors=True)
        work = jd / "work"
        work.mkdir(parents=True, exist_ok=True)
        src = Path(job["source_path"])
        t0 = time.time()
        try:
            pdf = convert_pptx_to_pdf(
                src,
                self.settings.libreoffice_path,
                work,
                timeout_s=self.settings.conversion_timeout_s,
                memory_mb=self.settings.conversion_memory_mb,
                cpu_seconds=self.settings.conversion_cpu_seconds,
            )
            pages = convert_pdf_to_images(
                pdf,
                images_dir,
                target_size=(self.settings.image_width, self.settings.image_height),
                image_format=self.settings.image_format,
                max_pages=self.settings.max_slides,
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)
        logger.info("Job %s: rendered %s slides in %.1fs", job_id, len(pages), time.time() - t0)

        texts: Dict[int, dict] = {}
        if job["source_kind"] == "pptx":
            texts = extract_pptx_text(src, self.settings.max_slides)

        slides: List[SlideData] = []
        for p in pages:
            t = texts.get(p.number, {})
            slides.append(
                SlideData(
                    number=p.number,
                    presentation_id=job_id,
                    title=t.get("title", ""),
                    original_text=t.get("text", ""),
                    notes_text=t.get("notes", ""),
                    image_ref=f"images/{p.path.name}",
                    image_sha256=sha256_file(p.path),
                    status=SlideStatus.pending,
                    render_error=p.error,
                )
            )
        self.db.upsert_slides(job_id, slides)
        title = job["title"] or (slides[0].title if slides and slides[0].title else "") or Path(job["display_name"]).stem
        self.db.update_job(job_id, slide_count=len(slides), title=title)

    def _default_client_factory(self) -> QwenClient:
        return QwenClient(self.runtime.qwen_config(), str(self.runtime.get("qwen_system_prompt")))

    def _describe(self, job_id: str, *, only: Optional[List[int]], cancel: threading.Event) -> None:
        job = self.db.get_job(job_id)
        all_slides = self.db.get_slides(job_id)
        if only:
            wanted = set(only)
            todo = [s for s in all_slides if s.number in wanted]
            for s in todo:
                self.db.update_slide(job_id, s.number, status=SlideStatus.pending, error=None)
        else:
            todo = [s for s in all_slides if s.status != SlideStatus.done]
        if not todo:
            return
        self.db.update_job(job_id, status=JobStatus.describing, error=None)
        client = self.client_factory()
        self.db.update_job(job_id, model=client.model_name)
        concurrency = max(1, int(self.runtime.get("qwen_concurrency")))
        rate = int(self.runtime.get("qwen_rate_limit_per_min"))
        limiter = ThreadSafeRateLimiter(rate)
        deck_title = job["title"] or job["display_name"]
        total = len(all_slides)
        logger.info("Job %s: describing %s slides (concurrency %s, rate %s/min)", job_id, len(todo), concurrency, rate)

        def work(s: SlideData) -> None:
            if cancel.is_set():
                return
            self.db.update_slide(job_id, s.number, status=SlideStatus.processing)
            self.db.increment_attempts(job_id, s.number)
            extracted = "\n".join(x for x in (s.title, s.original_text) if x)
            prompt = build_user_prompt(s.number, total, deck_title, extracted)
            image = self.job_dir(job_id) / s.image_ref
            limiter.acquire()
            try:
                desc, raw = client.describe(prompt, image)
                content = desc.as_markdownish() or raw
                self.db.update_slide(
                    job_id,
                    s.number,
                    status=SlideStatus.done,
                    content=content,
                    description=desc,
                    title=(desc.title or s.title)[:300],
                    error=None,
                    model=client.model_name,
                    processed_at=now_iso(),
                )
            except (QwenError, FileNotFoundError, OSError) as e:
                logger.warning("Slide %s of job %s failed: %s", s.number, job_id, e)
                self.db.update_slide(job_id, s.number, status=SlideStatus.failed, error=str(e)[:500], model=client.model_name)

        try:
            with ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="slide") as ex:
                futures = [ex.submit(work, s) for s in todo]
                for f in as_completed(futures):
                    f.result()
        finally:
            client.close()
        if cancel.is_set():
            for s in self.db.get_slides(job_id):
                if s.status == SlideStatus.processing:
                    self.db.update_slide(job_id, s.number, status=SlideStatus.pending)

    def _finalize(self, job_id: str, error: Optional[str] = None) -> None:
        counts = self.db.slide_status_counts(job_id)
        job = self.db.get_job(job_id)
        if not job:
            return
        if job["status"] == JobStatus.failed.value:
            return
        if error:
            self.db.update_job(job_id, status=JobStatus.partial if counts["done"] else JobStatus.interrupted, error=error)
            return
        if counts["done"] and counts["done"] == job["slide_count"]:
            # keep published status if the job was already published and only text changed
            self.db.update_job(job_id, status=JobStatus.ready, error=None)
        elif counts["done"] or counts["failed"]:
            self.db.update_job(job_id, status=JobStatus.partial, error=f"{counts['failed']} slide(s) failed, {counts['pending']} pending")
        else:
            self.db.update_job(job_id, status=JobStatus.interrupted, error="no slides processed")
