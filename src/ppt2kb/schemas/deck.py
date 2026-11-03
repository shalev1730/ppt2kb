"""
Structured output schema.

Extends the ppt2desc ``DeckData``/``SlideData`` models (MIT, (c) 2025 Adam
Łucek). ``SlideData.number`` and ``SlideData.content`` keep their original
meaning (``content`` = the AI generated description) so existing ppt2desc
consumers can still read the exported JSON; the additional fields carry the
information needed for the Knowledge article workflow.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# Image output modes (1.1.1). The mode only decides which images are attached
# to the ServiceNow article and which are shown in its body; Qwen always
# analyses the full slide render.
#   embedded      - body: selected embedded images; attachments: all embedded images
#   embedded_full - body: full slide render;         attachments: full slides + all embedded images (default)
#   full_slide    - body: full slide render;         attachments: full slides only
IMAGE_MODES = ("embedded", "embedded_full", "full_slide")
DEFAULT_IMAGE_MODE = "embedded_full"


def body_uses_full_slide(mode: str) -> bool:
    return mode in ("embedded_full", "full_slide")


def attaches_embedded(mode: str) -> bool:
    return mode in ("embedded", "embedded_full")


def attaches_full_slides(mode: str) -> bool:
    return mode in ("embedded_full", "full_slide")


class SlideStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"
    needs_review = "needs_review"  # analysed, but the output failed quality validation


class JobStatus(str, Enum):
    uploaded = "uploaded"
    converting = "converting"
    describing = "describing"
    ready = "ready"  # all slides described
    partial = "partial"  # some slides failed; can be retried
    failed = "failed"  # conversion failed
    interrupted = "interrupted"  # process stopped mid-way; can be resumed
    publishing = "publishing"
    published = "published"
    publish_failed = "publish_failed"


class SlideDescription(BaseModel):
    """Structured knowledge extracted from one slide (schema v3).

    v3 fields: ``summary`` (what the slide explains), ``details`` (components,
    configuration, workflow, relationships), ``key_facts`` (commands, field
    and table names, values, error messages - verbatim), ``slide_kind``.
    The v2 fields are kept so older saved presentations still load:
    ``technical_description`` == summary, ``visuals_explanation`` == details.
    """

    title: str = ""
    summary: str = ""
    details: str = ""
    procedures: str = ""
    key_facts: str = ""
    visible_text: str = ""  # reference transcription (reviewer aid, not published)
    uncertainties: str = ""
    language: str = ""  # he | en | he+en
    slide_kind: str = ""  # title | section | content | summary
    confidence: str = ""  # high | medium | low
    # legacy (v2)
    technical_description: str = ""
    visuals_explanation: str = ""

    def normalised(self) -> "SlideDescription":
        """Map legacy fields onto the v3 ones when a v2 answer/record is loaded."""
        if not self.summary and self.technical_description:
            self.summary = self.technical_description
        if not self.details and self.visuals_explanation:
            self.details = self.visuals_explanation
        return self

    def as_markdownish(self) -> str:
        """Plain-text article body for one slide (editable in the UI; rendered by export.html).

        Layout: summary paragraph, details paragraph(s), then labelled blocks
        for procedures and key facts. Uncertainties are *not* part of the
        article; they are shown to the reviewer in the UI.
        """
        self.normalised()
        he = self.language.startswith("he") or _is_hebrew(self.summary)
        parts: list[str] = []
        if self.summary.strip():
            parts.append(self.summary.strip())
        if self.details.strip() and self.details.strip() != self.summary.strip():
            parts.append(self.details.strip())
        if self.procedures.strip():
            parts.append(("שלבים:" if he else "Procedure:") + "\n" + _as_numbered(self.procedures))
        if self.key_facts.strip():
            parts.append(("מידע טכני חשוב:" if he else "Important technical information:") + "\n" + _as_bullets(self.key_facts))
        return "\n\n".join(parts)


def _is_hebrew(text: str) -> bool:
    import re

    m = re.search(r"[\u0590-\u05FFA-Za-z]", text or "")
    return bool(m and "\u0590" <= m.group(0) <= "\u05FF")


def _as_numbered(text: str) -> str:
    import re

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out = []
    for i, ln in enumerate(lines, start=1):
        if re.match(r"^\d+[.)]\s+", ln):
            out.append(ln)
        else:
            out.append(f"{i}. {re.sub(r'^[-*•]\s*', '', ln)}")
    return "\n".join(out)


def _as_bullets(text: str) -> str:
    import re

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(ln if re.match(r"^[-*•]\s+", ln) else f"- {re.sub(r'^\d+[.)]\s*', '', ln)}" for ln in lines)


class SlideData(BaseModel):
    # --- ppt2desc compatible fields
    number: int
    content: str = ""  # AI generated description (flattened)
    # --- extensions
    presentation_id: str = ""
    title: str = ""
    original_text: str = ""  # text extracted from the PPTX itself (python-pptx)
    notes_text: str = ""
    description: Optional[SlideDescription] = None
    edited_content: Optional[str] = None  # user edited version, if any
    image_ref: str = ""  # relative path of the slide image
    image_sha256: str = ""
    status: SlideStatus = SlideStatus.pending
    error: Optional[str] = None
    attempts: int = 0
    model: str = ""
    processed_at: Optional[str] = None
    render_error: Optional[str] = None
    quality: List[str] = Field(default_factory=list)  # validation issues (codes) of the kept answer
    reviewed: bool = False  # a person accepted the content (needs_review -> done)
    images: List[dict] = Field(default_factory=list)  # embedded images (filled by the API layer)

    @property
    def final_content(self) -> str:
        return self.edited_content if self.edited_content is not None else self.content


class DeckData(BaseModel):
    # --- ppt2desc compatible fields
    deck: str
    model: str
    slides: List[SlideData]
    # --- extensions
    presentation_id: str = ""
    title: str = ""
    status: JobStatus = JobStatus.uploaded
    slide_count: int = 0
    created_at: str = ""
    updated_at: str = ""
    source_sha256: str = ""
    servicenow: dict = Field(default_factory=dict)
    image_mode: str = "embedded_full"  # see IMAGE_MODES
    schema_version: int = 3
