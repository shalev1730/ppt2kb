"""
Command line interface (ppt2desc-style batch mode, no web UI).

    ppt2kb-cli --input deck.pptx --output_dir ./out [--save-images]

Uses the same configuration (environment variables) as the web application
and writes a ppt2desc-compatible JSON file (``slides[].number`` /
``slides[].content``) extended with the ppt2kb fields.
"""
from __future__ import annotations

import argparse
import logging
import shutil
import sys
import uuid
from pathlib import Path

from .config import get_settings
from .logging_utils import configure_logging
from .pipeline import JobRunner
from .pipeline.processor import sha256_file
from .runtime import RuntimeConfig
from .security.upload_validation import UploadValidationError, validate_presentation
from .storage import Database


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Convert a PowerPoint file to structured slide descriptions using the configured Qwen endpoint.")
    p.add_argument("--input", required=True, help="PPT/PPTX file")
    p.add_argument("--output_dir", required=True, help="Output directory")
    p.add_argument("--save-images", action="store_true", help="Also copy slide images to the output directory")
    p.add_argument("--html", action="store_true", help="Also write a standalone HTML file")
    args = p.parse_args(argv)

    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    settings.ensure_dirs()
    log = logging.getLogger("ppt2kb.cli")

    src = Path(args.input)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        res = validate_presentation(
            src,
            src.name,
            max_bytes=settings.max_upload_mb * 1024 * 1024,
            max_zip_entries=settings.max_zip_entries,
            max_zip_uncompressed=settings.max_zip_uncompressed_mb * 1024 * 1024,
            max_zip_ratio=settings.max_zip_ratio,
        )
    except UploadValidationError as e:
        log.error("Input rejected: %s", e)
        return 2

    db = Database(settings.db_path)
    runtime = RuntimeConfig(settings, db)
    runner = JobRunner(settings, db, runtime)
    job_id = uuid.uuid4().hex
    stored = settings.upload_dir / f"{job_id}{src.suffix.lower()}"
    shutil.copyfile(src, stored)
    db.create_job(job_id=job_id, display_name=res.display_name, title="", source_path=str(stored), source_sha256=sha256_file(stored),
                  source_kind=res.kind, source_size=res.size_bytes, macro_enabled=res.macro_enabled)
    (settings.jobs_dir / job_id).mkdir(parents=True, exist_ok=True)
    runner.run(job_id)
    deck = db.deck(job_id)
    out_json = out_dir / f"{src.stem}.json"
    out_json.write_text(deck.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    log.info("Wrote %s (status %s)", out_json, deck.status.value)
    if args.save_images:
        dest = out_dir / src.stem
        dest.mkdir(exist_ok=True)
        for s in deck.slides:
            img = settings.jobs_dir / job_id / s.image_ref
            if img.is_file():
                shutil.copy2(img, dest / img.name)
    if args.html:
        from .export import build_standalone_html

        (out_dir / f"{src.stem}.html").write_text(
            build_standalone_html(title=deck.title or src.stem, slides=deck.slides, job_dir=settings.jobs_dir / job_id), encoding="utf-8"
        )
    return 0 if deck.status.value == "ready" else 1


if __name__ == "__main__":
    sys.exit(main())
