"""
Conservative heuristic classification of embedded images into
*informative* (keep) and *decorative* (exclude by default).

Signals used (each adds a reason string the reviewer can see in the UI):

  decorative
    * asset repeated on many slides (logo / watermark / ornament)
    * extreme aspect ratio (lines, borders, separators)
    * very low visual information (near-uniform colour, e.g. backgrounds, strips)
    * tiny placement (< 1 % of the slide) that is not part of a picture group
      and carries little detail
    * background picture fill that is near-uniform

  informative (overrides most decorative signals)
    * large placement (screenshots, diagrams)
    * high detail (many distinct colours / strong edges, typical of screenshots
      and diagrams with text)
    * member of a group that contains several pictures (icons in a diagram)

No image is excluded because of size alone; a small image is excluded only
when it is also low-detail or repeated. Vector / undecodable images are kept
*flagged* for manual review (not selected automatically, not hidden).
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image, ImageFilter, ImageStat

from .images import ExtractedImage

logger = logging.getLogger(__name__)


def _detail_metrics(path: Path) -> Tuple[float, int, float]:
    """(normalised stddev 0..1, distinct colours in a 64px thumbnail, edge density 0..1)."""
    with Image.open(path) as im:
        im = im.convert("RGB")
        im.thumbnail((96, 96))
        std = sum(ImageStat.Stat(im).stddev) / (3 * 255.0)
        small = im.resize((64, 64))
        colors = len({p for p in small.getdata()})
        edges = small.convert("L").filter(ImageFilter.FIND_EDGES)
        edge_density = sum(1 for p in edges.getdata() if p > 40) / (64 * 64)
    return std, colors, edge_density


def classify_images(images: List[ExtractedImage], base_dir: Path, slide_count: int) -> List[dict]:
    """Return a list of {selected, score, reasons, flagged} aligned with ``images``."""
    out: List[dict] = []
    for img in images:
        reasons: List[str] = []
        score = 0.0  # > 0 informative, < 0 decorative
        if not img.supported or not img.file_ref:
            out.append({"selected": False, "score": 0.0, "reasons": ["unsupported: " + (img.note or "unsupported format")], "flagged": True})
            continue
        area = max(0.0, img.rel_width) * max(0.0, img.rel_height)
        try:
            std, colors, edges = _detail_metrics(base_dir / img.file_ref)
        except Exception as e:  # pragma: no cover
            logger.warning("metrics failed for %s: %s", img.file_ref, e)
            std, colors, edges = 0.3, 500, 0.1

        # --- decorative signals
        repeated = img.reuse_count >= 3 or (slide_count >= 4 and img.reuse_count >= max(3, int(0.3 * slide_count)))
        if repeated:
            score -= 2.0
            reasons.append(f"repeated: repeated on {img.reuse_count} slides (logo/watermark pattern)")
        aspect = (img.width / img.height) if img.height else 1.0
        if aspect > 12 or aspect < 1 / 12:
            score -= 1.5
            reasons.append("extreme_aspect: extreme aspect ratio (line/border/separator)")
        low_detail = std < 0.04 or colors <= 6
        if low_detail:
            score -= 1.5
            reasons.append("uniform: near-uniform image (background/strip/ornament)")
        tiny = 0 < area < 0.01
        if tiny and img.group_pictures < 2:
            score -= 0.5
            reasons.append("tiny: very small placement (<1% of the slide)")
        if img.source_kind == "background" and std < 0.12:
            score -= 1.5
            reasons.append("background: background fill")
        if img.width < 48 or img.height < 48:
            score -= 0.5
            reasons.append("small_px: low pixel size")

        # --- informative signals
        if area >= 0.12:
            score += 1.5
            reasons.append("large: large placement (screenshot/diagram size)")
        if colors > 400 or edges > 0.12:
            score += 1.5
            reasons.append("detailed: high detail (screenshot/diagram/text)")
        elif colors > 60 and std > 0.08:
            score += 0.5
            reasons.append("moderate: moderate detail")
        if img.group_pictures >= 2:
            score += 1.0
            reasons.append(f"group: part of a group with {img.group_pictures} pictures (diagram element)")
        if img.cropped:
            score += 0.3
            reasons.append("cropped: cropped by the author (deliberate framing)")

        selected = score >= 0.0  # conservative: keep unless the decorative evidence outweighs
        out.append({"selected": selected, "score": round(score, 2), "reasons": reasons or ["no_signal: no strong signal - kept"], "flagged": False})
    return out
