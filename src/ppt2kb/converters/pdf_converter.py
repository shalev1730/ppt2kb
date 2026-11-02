"""
PDF -> slide images.

Adapted from ppt2desc (MIT, (c) 2025 Adam Łucek) ``src/converters/pdf_converter.py``.

Differences from the original:
  * Uses ``pypdfium2`` (Apache-2.0 / BSD-3) instead of PyMuPDF (AGPL-3.0),
    which removes a copyleft licensing obligation for enterprise deployment.
  * Page limit enforced (``max_pages``) so a crafted document cannot exhaust
    disk/CPU.
  * A per-page failure produces a placeholder image + an error entry instead of
    silently skipping the page, so slide numbering is always preserved.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw

from .exceptions import ConversionError

logger = logging.getLogger(__name__)


@dataclass
class RenderedPage:
    number: int
    path: Path
    width: int
    height: int
    error: str | None = None


def convert_pdf_to_images(
    pdf_path: Path,
    images_dir: Path,
    *,
    target_size: Tuple[int, int] = (1920, 1080),
    image_format: str = "png",
    max_pages: int = 300,
) -> List[RenderedPage]:
    import pypdfium2 as pdfium

    images_dir.mkdir(parents=True, exist_ok=True)
    ext = "jpg" if image_format == "jpeg" else "png"
    pages: List[RenderedPage] = []
    try:
        doc = pdfium.PdfDocument(str(pdf_path))
    except Exception as e:
        raise ConversionError(f"Cannot open converted PDF: {e}") from e
    try:
        n = len(doc)
        if n == 0:
            raise ConversionError("Converted PDF has no pages")
        if n > max_pages:
            raise ConversionError(f"Presentation has {n} slides; the limit is {max_pages}")
        for idx in range(n):
            number = idx + 1
            out = images_dir / f"slide_{number:03d}.{ext}"
            try:
                page = doc[idx]
                w, h = page.get_size()
                zoom = min(target_size[0] / w, target_size[1] / h)
                bitmap = page.render(scale=zoom, draw_annots=False, may_draw_forms=False)
                img = bitmap.to_pil().convert("RGB")
                canvas = Image.new("RGB", target_size, (255, 255, 255))
                canvas.paste(img, ((target_size[0] - img.width) // 2, (target_size[1] - img.height) // 2))
                if ext == "jpg":
                    canvas.save(out, "JPEG", quality=90, optimize=True)
                else:
                    canvas.save(out, "PNG", optimize=True)
                pages.append(RenderedPage(number, out, canvas.width, canvas.height))
                page.close()
            except Exception as e:  # keep numbering intact
                logger.error("Failed to render page %s: %s", number, e)
                canvas = Image.new("RGB", target_size, (255, 255, 255))
                ImageDraw.Draw(canvas).text((40, 40), f"Slide {number}: render failed", fill=(200, 0, 0))
                canvas.save(out)
                pages.append(RenderedPage(number, out, canvas.width, canvas.height, error=str(e)))
    finally:
        doc.close()
    return pages
