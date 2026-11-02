"""
HTML generation for the Knowledge article and for the standalone export.

All model/user supplied text is HTML-escaped; the generated markup contains
only a fixed set of tags (h1/h2/h3/p/ol/li/img/div/section/table), so no
script or active content can reach ServiceNow or the browser from slide
content. Hebrew paragraphs get ``dir="rtl"`` automatically.
"""
from __future__ import annotations

import base64
import html
import re
from pathlib import Path
from typing import Callable, Iterable, List, Optional

from ..schemas.deck import SlideData

_HEBREW_RE = re.compile(r"[֐-׿]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_STEP_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")


def job_marker(job_id: str) -> str:
    """Hidden, searchable marker placed in the article body for duplicate detection."""
    return f"<!-- ppt2kb:job={job_id} -->"


_STRONG_RE = re.compile(r"[֐-׿A-Za-z]")


def detect_direction(text: str) -> str:
    """Return 'rtl' if the first strong character is Hebrew (same rule as HTML dir=auto), else 'ltr'."""
    if not text:
        return "ltr"
    m = _STRONG_RE.search(text)
    if m and _HEBREW_RE.match(m.group(0)):
        return "rtl"
    return "ltr"


def text_to_html(text: str) -> str:
    """Convert plain text (with blank-line paragraphs and numbered steps) to safe HTML."""
    if not text or not text.strip():
        return ""
    out: List[str] = []
    paragraphs = re.split(r"\n\s*\n", text.strip())
    for para in paragraphs:
        lines = [ln.rstrip() for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue
        if len(lines) > 1 and all(_STEP_RE.match(ln) for ln in lines):
            items = "".join(f"<li>{html.escape(_STEP_RE.sub('', ln))}</li>" for ln in lines)
            d = detect_direction(para)
            out.append(f'<ol dir="{d}">{items}</ol>')
        else:
            d = detect_direction(para)
            body = "<br>".join(html.escape(ln) for ln in lines)
            out.append(f'<p dir="{d}">{body}</p>')
    return "\n".join(out)


def _slide_section(s: SlideData, img_src: str, heading_level: int = 2) -> str:
    content = s.edited_content if s.edited_content is not None else s.content
    title = s.title or (s.description.title if s.description else "") or f"Slide {s.number}"
    d = detect_direction(title + " " + content)
    h = f"h{heading_level}"
    parts = [f'<section class="ppt2kb-slide" data-slide="{s.number}" dir="{d}">']
    parts.append(f'<{h} dir="{detect_direction(title)}">{s.number}. {html.escape(title)}</{h}>')
    if img_src:
        parts.append(
            f'<p class="ppt2kb-image"><img src="{html.escape(img_src, quote=True)}" alt="{html.escape(f"Slide {s.number}", quote=True)}" '
            f'style="max-width:100%;height:auto;border:1px solid #ccc"></p>'
        )
    parts.append(text_to_html(content))
    parts.append("</section>")
    return "\n".join(p for p in parts if p)


def build_article_html(
    *,
    title: str,
    slides: Iterable[SlideData],
    image_src: Callable[[SlideData], str],
    marker: str = "",
    deck_name: str = "",
) -> str:
    """Body HTML for the kb_knowledge ``text`` field (no html/head/body wrapper)."""
    slides = list(slides)
    d = detect_direction(title)
    parts = [marker] if marker else []
    parts.append(f'<div class="ppt2kb-article" dir="{d}">')
    if deck_name:
        parts.append(f'<p class="ppt2kb-source"><em>Source presentation: {html.escape(deck_name)} ({len(slides)} slides)</em></p>')
    toc = "".join(
        f'<li><a href="#ppt2kb-slide-{s.number}">{s.number}. {html.escape(s.title or (s.description.title if s.description else "") or f"Slide {s.number}")}</a></li>'
        for s in slides
    )
    parts.append(f'<details class="ppt2kb-toc"><summary>Contents</summary><ol dir="{d}">{toc}</ol></details>')
    for s in slides:
        parts.append(f'<a id="ppt2kb-slide-{s.number}"></a>')
        parts.append(_slide_section(s, image_src(s)))
    parts.append("</div>")
    return "\n".join(parts)


def build_standalone_html(*, title: str, slides: Iterable[SlideData], job_dir: Optional[Path], embed_images: bool = True) -> str:
    """Self-contained HTML document for download/offline review."""
    slides = list(slides)

    def src(s: SlideData) -> str:
        if not s.image_ref:
            return ""
        if embed_images and job_dir:
            p = job_dir / s.image_ref
            if p.is_file():
                mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
                return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"
        return s.image_ref

    body = build_article_html(title=title, slides=slides, image_src=src)
    d = detect_direction(title)
    return f"""<!DOCTYPE html>
<html lang="{'he' if d == 'rtl' else 'en'}" dir="{d}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font-family:Arial,"Segoe UI",Tahoma,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;line-height:1.5;color:#1b1b1b}}
section.ppt2kb-slide{{border-top:1px solid #ddd;padding:1.5rem 0}}
.ppt2kb-image img{{max-width:100%;height:auto;border:1px solid #ccc}}
h1{{font-size:1.8rem}} h2{{font-size:1.3rem}}
details{{margin-bottom:1rem}}
</style>
</head>
<body>
<h1 dir="{d}">{html.escape(title)}</h1>
{body}
</body>
</html>
"""
