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
from typing import Callable, Iterable, List, Optional, Tuple

from ..schemas.deck import SlideData

_HEBREW_RE = re.compile(r"[֐-׿]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_STEP_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+")
_NUM_RE = re.compile(r"^\s*\d+[.)]\s+")
_BUL_RE = re.compile(r"^\s*[-*•]\s+")
_LABEL_RE = re.compile(r"^[^\n]{2,60}:\s*$")


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
    """Convert plain text to safe HTML.

    Blank lines separate paragraphs; consecutive numbered lines become ``<ol>``,
    bullet lines become ``<ul>``; a short line ending with ':' directly before
    a list becomes a bold label (e.g. "Procedure:" / "שלבים:"). Everything is
    HTML-escaped; only p/ol/ul/li/strong/br are emitted.
    """
    if not text or not text.strip():
        return ""
    out: List[str] = []
    paragraphs = re.split(r"\n\s*\n", text.strip())
    for para in paragraphs:
        lines = [ln.rstrip() for ln in para.splitlines() if ln.strip()]
        if not lines:
            continue
        label = None
        if len(lines) > 1 and _LABEL_RE.match(lines[0]) and all(_STEP_RE.match(ln) for ln in lines[1:]):
            label, lines = lines[0], lines[1:]
        d = detect_direction("\n".join(lines))  # direction of the items themselves, not of the label
        if label:
            out.append(f'<p dir="{detect_direction(label)}"><strong>{html.escape(label)}</strong></p>')
        if lines and all(_NUM_RE.match(ln) for ln in lines):
            items = "".join(f"<li>{html.escape(_NUM_RE.sub('', ln))}</li>" for ln in lines)
            out.append(f'<ol dir="{d}">{items}</ol>')
        elif lines and all(_BUL_RE.match(ln) for ln in lines):
            items = "".join(f"<li>{html.escape(_BUL_RE.sub('', ln))}</li>" for ln in lines)
            out.append(f'<ul dir="{d}">{items}</ul>')
        elif len(lines) > 1 and all(_STEP_RE.match(ln) for ln in lines):
            items = "".join(f"<li>{html.escape(_STEP_RE.sub('', ln))}</li>" for ln in lines)
            out.append(f'<ol dir="{d}">{items}</ol>')
        else:
            body = "<br>".join(html.escape(ln) for ln in lines)
            out.append(f'<p dir="{d}">{body}</p>')
    return "\n".join(out)


def _heading_for(s: SlideData) -> str:
    return s.title or (s.description.title if s.description else "") or f"Slide {s.number}"


def _slide_section(s: SlideData, figures: List[Tuple[str, str]], heading_level: int = 2, figures_first: bool = False) -> str:
    """One article section: heading, then explanation and figures (src, alt).

    ``figures_first`` puts the figures directly under the heading and the explanation
    beneath them - used for the full slide render (the explanation describes the slide
    shown above it); embedded images follow the explanation they illustrate."""
    content = s.edited_content if s.edited_content is not None else s.content
    title = _heading_for(s)
    # drop a first line that merely repeats the heading
    first, _, rest = (content or "").strip().partition("\n")
    if first.strip().rstrip(".:") == title.strip().rstrip(".:"):
        content = rest
    d = detect_direction(title + " " + (content or ""))
    h = f"h{heading_level}"
    parts = [f'<section class="ppt2kb-slide" data-slide="{s.number}" dir="{d}">']
    parts.append(f'<{h} dir="{detect_direction(title)}">{s.number}. {html.escape(title)}</{h}>')
    figs = [
        f'<figure class="ppt2kb-figure"><img src="{html.escape(src, quote=True)}" alt="{html.escape(alt, quote=True)}" '
        f'style="max-width:100%;height:auto;border:1px solid #ccc"></figure>'
        for src, alt in figures
    ]
    body = text_to_html(content or "")
    parts.extend(figs + [body] if figures_first else [body] + figs)
    parts.append("</section>")
    return "\n".join(p for p in parts if p)


def build_article_html(
    *,
    title: str,
    slides: Iterable[SlideData],
    image_src: Optional[Callable[[SlideData], str]] = None,
    figures_for: Optional[Callable[[SlideData], List[Tuple[str, str]]]] = None,
    marker: str = "",
    deck_name: str = "",
    sections_only: bool = False,
) -> str:
    """Body HTML for the kb_knowledge ``text`` field (no html/head/body wrapper).

    ``figures_for(slide)`` returns the (src, alt) pairs to place under the slide's
    explanation (embedded-images mode). ``image_src(slide)`` is the legacy
    full-slide screenshot mode (one figure per slide). Both may be given;
    ``figures_for`` wins when it returns anything.
    """
    slides = list(slides)
    d = detect_direction(title)
    parts = [marker] if marker else []
    parts.append(f'<div class="ppt2kb-article" dir="{d}">')
    if deck_name and not sections_only:
        parts.append(f'<p class="ppt2kb-source"><em>Source presentation: {html.escape(deck_name)} ({len(slides)} slides)</em></p>')
    if not sections_only:
        toc = "".join(f'<li><a href="#ppt2kb-slide-{s.number}">{s.number}. {html.escape(_heading_for(s))}</a></li>' for s in slides)
        parts.append(f'<details class="ppt2kb-toc"><summary>Contents</summary><ol dir="{d}">{toc}</ol></details>')
    for s in slides:
        figs: List[Tuple[str, str]] = []
        first = False
        if figures_for:
            figs = list(figures_for(s) or [])
        if not figs and image_src:
            src = image_src(s)
            if src:
                figs = [(src, f"{_heading_for(s)} - slide {s.number}")]
                first = True  # the full slide render goes above its explanation
        parts.append(f'<a id="ppt2kb-slide-{s.number}"></a>')
        parts.append(_slide_section(s, figs, figures_first=first))
    parts.append("</div>")
    return "\n".join(parts)


def _data_uri(p: Path) -> str:
    mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64,{base64.b64encode(p.read_bytes()).decode('ascii')}"


def build_standalone_html(*, title: str, slides: Iterable[SlideData], job_dir: Optional[Path], embed_images: bool = True, mode: str = "full_slide") -> str:
    """Self-contained HTML document for download/offline review."""
    slides = list(slides)

    def src(s: SlideData) -> str:
        if not s.image_ref:
            return ""
        if embed_images and job_dir:
            p = job_dir / s.image_ref
            if p.is_file():
                return _data_uri(p)
        return s.image_ref

    def figs(s: SlideData) -> List[Tuple[str, str]]:
        out: List[Tuple[str, str]] = []
        for i, im in enumerate(s.images or [], start=1):
            if not im.get("selected") or not im.get("file_ref"):
                continue
            alt = f"{_heading_for(s)} - image {i}"
            if embed_images and job_dir and (job_dir / im["file_ref"]).is_file():
                out.append((_data_uri(job_dir / im["file_ref"]), alt))
            else:
                out.append((im["file_ref"], alt))
        return out

    from ..schemas.deck import body_uses_full_slide

    body = build_article_html(title=title, slides=slides, image_src=src if body_uses_full_slide(mode) else None, figures_for=figs if mode == "embedded" else None)
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
