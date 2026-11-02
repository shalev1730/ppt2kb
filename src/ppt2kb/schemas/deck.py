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


class SlideStatus(str, Enum):
    pending = "pending"
    processing = "processing"
    done = "done"
    failed = "failed"


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
    """Structured answer expected from the vision model for one slide."""

    title: str = ""
    visible_text: str = ""
    technical_description: str = ""
    visuals_explanation: str = ""
    procedures: str = ""
    uncertainties: str = ""
    language: str = ""  # e.g. "he", "en", "he+en"

    def as_markdownish(self) -> str:
        """Flatten to the plain text ppt2desc style ``content`` field."""
        parts = []
        if self.title:
            parts.append(self.title)
        if self.visible_text:
            parts.append(self.visible_text)
        if self.technical_description:
            parts.append(self.technical_description)
        if self.visuals_explanation:
            parts.append(self.visuals_explanation)
        if self.procedures:
            parts.append(self.procedures)
        if self.uncertainties:
            parts.append("Uncertain / unreadable: " + self.uncertainties)
        return "\n\n".join(p.strip() for p in parts if p and p.strip())


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
    schema_version: int = 2
