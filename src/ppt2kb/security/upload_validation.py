"""
Validation of uploaded PowerPoint files.

Defends against:
  * wrong / spoofed file types (extension + magic bytes + OOXML content type)
  * ZIP bombs (entry count, total uncompressed size, compression ratio)
  * path traversal via ZIP member names (``../`` or absolute paths)
  * over-sized uploads (checked while streaming, before anything is parsed)
  * dangerous names (we never use the user supplied name for file-system paths)

The validated file is always stored under a random, application generated
name; the original name is kept only as display metadata.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PPTX_MAGIC = b"PK\x03\x04"
PPTX_EMPTY_MAGIC = b"PK\x05\x06"
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

PRESENTATION_CONTENT_TYPES = (
    "application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml",
    "application/vnd.openxmlformats-officedocument.presentationml.slideshow.main+xml",
    "application/vnd.openxmlformats-officedocument.presentationml.template.main+xml",
    "application/vnd.ms-powerpoint.presentation.macroEnabled.main+xml",
    "application/vnd.ms-powerpoint.slideshow.macroEnabled.main+xml",
)

ALLOWED_EXTENSIONS = {".pptx", ".ppt", ".ppsx", ".pps", ".potx"}

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.\-֐-׿ ]+")


class UploadValidationError(ValueError):
    """Raised when an uploaded file is rejected."""


@dataclass
class ValidationResult:
    kind: str  # "pptx" | "ppt"
    macro_enabled: bool
    size_bytes: int
    display_name: str


def sanitize_display_name(name: str, max_len: int = 120) -> str:
    """Keep a human readable version of the original name for display only."""
    base = PurePosixPath(name.replace("\\", "/")).name or "presentation.pptx"
    base = _SAFE_NAME_RE.sub("_", base).strip(" .")
    if not base:
        base = "presentation.pptx"
    return base[:max_len]


def _check_zip(path: Path, max_entries: int, max_uncompressed: int, max_ratio: int) -> tuple[bool, bool]:
    """Return (is_presentation, macro_enabled). Raises on bomb/traversal."""
    try:
        zf = zipfile.ZipFile(path)
    except zipfile.BadZipFile as e:
        raise UploadValidationError("File is not a valid PPTX (ZIP) container") from e
    with zf:
        infos = zf.infolist()
        if len(infos) > max_entries:
            raise UploadValidationError(f"Archive has too many entries (> {max_entries})")
        total_uncompressed = 0
        total_compressed = 0
        for info in infos:
            name = info.filename
            if name.startswith("/") or name.startswith("\\") or ".." in PurePosixPath(name.replace("\\", "/")).parts:
                raise UploadValidationError("Archive contains unsafe member paths")
            if re.match(r"^[A-Za-z]:", name):
                raise UploadValidationError("Archive contains unsafe member paths")
            total_uncompressed += info.file_size
            total_compressed += info.compress_size
            if total_uncompressed > max_uncompressed:
                raise UploadValidationError("Archive expands to too much data (possible ZIP bomb)")
            if info.compress_size > 0 and info.file_size / info.compress_size > max_ratio and info.file_size > 1_000_000:
                raise UploadValidationError("Archive member has a suspicious compression ratio (possible ZIP bomb)")
        if total_compressed > 0 and total_uncompressed / total_compressed > max_ratio and total_uncompressed > 50_000_000:
            raise UploadValidationError("Archive has a suspicious overall compression ratio (possible ZIP bomb)")
        try:
            ct = zf.read("[Content_Types].xml")
        except KeyError as e:
            raise UploadValidationError("Not an Office Open XML package") from e
        if len(ct) > 2_000_000:
            raise UploadValidationError("Content types part too large")
        text = ct.decode("utf-8", errors="replace")
        is_pres = any(c in text for c in PRESENTATION_CONTENT_TYPES)
        if not is_pres:
            raise UploadValidationError("The package is not a PowerPoint presentation")
        macro = "macroEnabled" in text or any(i.filename.lower().endswith("vbaproject.bin") for i in infos)
        return True, macro


def validate_presentation(
    path: Path,
    original_name: str,
    *,
    max_bytes: int,
    max_zip_entries: int,
    max_zip_uncompressed: int,
    max_zip_ratio: int,
) -> ValidationResult:
    """Validate an uploaded file that has already been written to ``path``."""
    size = path.stat().st_size
    if size == 0:
        raise UploadValidationError("Uploaded file is empty")
    if size > max_bytes:
        raise UploadValidationError(f"File exceeds the maximum allowed size of {max_bytes // (1024 * 1024)} MB")

    ext = PurePosixPath(original_name.replace("\\", "/")).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise UploadValidationError("Only PowerPoint files (.pptx, .ppt) are accepted")

    with path.open("rb") as f:
        head = f.read(8)

    if head.startswith(PPTX_MAGIC):
        _, macro = _check_zip(path, max_zip_entries, max_zip_uncompressed, max_zip_ratio)
        return ValidationResult("pptx", macro, size, sanitize_display_name(original_name))
    if head.startswith(OLE_MAGIC):
        if ext not in (".ppt", ".pps"):
            raise UploadValidationError("File content does not match its extension")
        # Legacy binary format: LibreOffice performs the parsing in an isolated
        # process; we only confirm the OLE2 signature here.
        return ValidationResult("ppt", False, size, sanitize_display_name(original_name))
    if head.startswith(PPTX_EMPTY_MAGIC):
        raise UploadValidationError("Archive is empty")
    raise UploadValidationError("File content is not a recognised PowerPoint format")
