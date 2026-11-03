"""
Meaningful attachment file names.

  full slide render : ``001_משואה_750.png``
  embedded image    : ``001_משואה_750_image_01.png``

``<slide:03d>_<sanitised title>[_image_<nn>].<ext>`` - Hebrew and English
letters, digits, ``-`` and ``_`` are kept; everything else becomes ``_``;
length is capped; duplicates get a numeric suffix. With ``ascii_only`` the
title part is reduced to ASCII (Hebrew removed; ``slide`` if nothing is left)
for instances that reject Unicode file names.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Set

_KEEP = re.compile(r"[^0-9A-Za-z֐-׿_-]+")
_ASCII_KEEP = re.compile(r"[^0-9A-Za-z_-]+")
_MULTI = re.compile(r"_+")


def sanitize_title(title: str, *, ascii_only: bool = False, max_len: int = 48) -> str:
    t = unicodedata.normalize("NFC", (title or "").strip())
    t = t.replace(" ", "_")
    t = (_ASCII_KEEP if ascii_only else _KEEP).sub("_", t)
    t = _MULTI.sub("_", t).strip("_-")
    if len(t) > max_len:
        t = t[:max_len].rstrip("_")
    return t or "slide"


def _unique(base: str, ext: str, used: Set[str]) -> str:
    ext = "jpg" if ext.lower() in ("jpeg", "jpg") else "png"
    name = f"{base}.{ext}"
    n = 2
    while name.lower() in used:
        name = f"{base}-{n}.{ext}"
        n += 1
    used.add(name.lower())
    return name


def attachment_filename(slide_number: int, title: str, image_index: int, ext: str, *, used: Set[str], ascii_only: bool = False) -> str:
    """Name of an embedded image: ``004_משואה_750_image_01.png``."""
    return _unique(f"{slide_number:03d}_{sanitize_title(title, ascii_only=ascii_only)}_image_{image_index:02d}", ext, used)


def slide_filename(slide_number: int, title: str, ext: str, *, used: Set[str], ascii_only: bool = False) -> str:
    """Name of a full-slide render: ``004_משואה_750.png``."""
    return _unique(f"{slide_number:03d}_{sanitize_title(title, ascii_only=ascii_only)}", ext, used)
