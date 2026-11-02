"""
Quality validation of a model answer for one slide.

Returns a list of issue codes. *Blocking* issues mean the answer must not be
accepted as a successfully processed slide (the pipeline retries with a
corrective hint and finally marks the slide ``needs_review``); *warnings*
are kept with the slide for the reviewer.

Codes
  blocking: not_json, truncated, degenerate, empty_summary, visual_only, raw_ocr, duplicate
  warning : low_confidence, unreadable, short_for_dense_slide, missing_title
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import List, Optional

from ..schemas.deck import SlideDescription

BLOCKING = {"not_json", "truncated", "degenerate", "empty_summary", "visual_only", "raw_ocr", "duplicate"}

_VISUAL_WORDS = re.compile(
    r"\b(background|backgrounds|font|fonts|typography|logo|logos|border|borders|colou?rs?|colou?red|blue|green|red|white|black|beige|grey|gray|dark|light|"
    r"layout|positioned|centered|centred|top[- ]left|top[- ]right|bottom[- ]left|bottom[- ]right|at the top|at the bottom|on the left|on the right|"
    r"decorative|icon|icons|rounded|shadow|gradient|styled|circular|rectangular)\b"
    r"|(?:רקע|גופן|גופנים|לוגו|מסגרת|צבע|צבעים|כחול|ירוק|אדום|לבן|שחור|אפור|כהה|בהיר|בפינה|ממורכז|למעלה|למטה|מימין|משמאל|עיצוב|מעוצב|עגול|מלבני|צללית|אייקון)",
    re.IGNORECASE,
)
_TECH_SIGNALS = re.compile(r"[A-Za-z_]{2,}[._/][A-Za-z_]+|\b[a-z]+_[a-z_]+\b|\bhttps?://|\b(?:GET|POST|PUT|PATCH|DELETE|API|REST|SQL|URL|JSON|sys_id|CRUD)\b|\d")
_WORD = re.compile(r"[\w֐-׿]+")


def _words(text: str) -> List[str]:
    return _WORD.findall((text or "").lower())


def _ratio(a: str, b: str) -> float:
    a, b = (a or "").strip(), (b or "").strip()
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def validate_description(
    desc: SlideDescription,
    raw: str,
    *,
    original_text: str = "",
    previous_content: Optional[str] = None,
    previous_original: Optional[str] = None,
    salvaged: bool = False,
    structured: bool = True,
) -> List[str]:
    issues: List[str] = []
    desc.normalised()
    summary = (desc.summary or "").strip()
    details = (desc.details or "").strip()
    body = (summary + "\n" + details).strip()

    if not structured:
        issues.append("not_json")
    if salvaged:
        issues.append("truncated")
    if len(summary) < 15 and len(details) < 15:
        issues.append("empty_summary")
    if not (desc.title or "").strip():
        issues.append("missing_title")

    # appearance description instead of meaning
    words = _words(body)
    if words:
        visual_hits = len(_VISUAL_WORDS.findall(body))
        tech_hits = len(_TECH_SIGNALS.findall(body))
        if visual_hits >= 3 and visual_hits / max(1, len(words)) > 0.04 and tech_hits < 2:
            issues.append("visual_only")

    # raw OCR copied as the explanation
    if original_text and len(original_text.strip()) > 40 and summary:
        if _ratio(summary, original_text) > 0.8 or _ratio(body, original_text) > 0.85:
            issues.append("raw_ocr")
    # explanation that is just the transcription field
    if desc.visible_text and summary and len(summary) > 40 and _ratio(summary, desc.visible_text) > 0.9:
        if "raw_ocr" not in issues:
            issues.append("raw_ocr")

    # copied from the previous slide (unless the slides themselves are near-identical)
    if previous_content and len(body) > 60:
        slides_alike = bool(previous_original and original_text and _ratio(original_text, previous_original) > 0.85)
        if not slides_alike and _ratio(desc.as_markdownish(), previous_content) > 0.92:
            issues.append("duplicate")

    # warnings
    if (desc.confidence or "").lower() == "low":
        issues.append("low_confidence")
    unc = (desc.uncertainties or "").lower()
    if any(k in unc for k in ("unreadable", "cannot read", "illegible", "לא קריא", "לא ניתן לקרוא")):
        issues.append("unreadable")
    if original_text and len(_words(original_text)) > 120 and len(words) < 25 and (desc.slide_kind or "content") == "content":
        issues.append("short_for_dense_slide")
    return issues


def is_blocking(issues: List[str]) -> bool:
    return any(i in BLOCKING for i in issues)
