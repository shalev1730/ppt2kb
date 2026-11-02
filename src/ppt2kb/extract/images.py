"""
Extraction of the images embedded in a PPTX (the original picture assets, not
slide screenshots).

What is handled:
  * picture shapes (``p:pic``) anywhere in the shape tree, including inside
    groups (recursively) and picture placeholders;
  * picture fills of auto-shapes and of the slide background (``a:blipFill``),
    which are how screenshots are sometimes placed;
  * PNG / JPEG / GIF / BMP / TIFF / WebP assets (anything Pillow can decode);
    EMF / WMF / SVG vector assets are reported as *unsupported* and flagged,
    never silently dropped;
  * PowerPoint cropping (``a:srcRect`` / python-pptx ``crop_*``): only the
    visible portion is kept, the hidden area is never exposed;
  * rotation and horizontal / vertical flips (``a:xfrm`` attributes);
  * reused assets (same bytes on several slides or several times on a slide):
    every placement is extracted, the shared ``sha256`` identifies the asset.

The visible appearance is reproduced losslessly where possible: an
untransformed PNG/JPEG is stored byte-for-byte; a cropped/rotated/flipped
image is re-encoded as PNG (lossless) from the decoded original.
"""
from __future__ import annotations

import hashlib
import io
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

RASTER_EXTS = {"png", "jpg", "jpeg", "gif", "bmp", "tif", "tiff", "webp"}
VECTOR_EXTS = {"emf", "wmf", "svg", "eps", "pdf"}
MAX_EMBEDDED_PIXELS = 40_000_000  # decompression-bomb guard (below Pillow's own 89 M default); larger pictures are reported, not decoded


class ImageTooLarge(ValueError):
    pass


def _check_dims(im: Image.Image) -> None:
    if im.width * im.height > MAX_EMBEDDED_PIXELS:
        raise ImageTooLarge(f"{im.width}x{im.height} exceeds {MAX_EMBEDDED_PIXELS} pixels")
NS = {
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "p": "http://schemas.openxmlformats.org/presentationml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}


@dataclass
class ExtractedImage:
    slide_number: int
    index: int  # 1-based order on the slide (z-order / document order)
    shape_name: str
    source_kind: str  # picture | placeholder | shape_fill | background | group_picture
    original_ext: str  # ext of the asset in the package (png, jpeg, emf, ...)
    sha256: str  # of the original asset bytes (identifies reused assets)
    file_ref: str = ""  # relative path of the saved visible image (images/emb/...)
    file_ext: str = ""  # png | jpeg - format of the saved file
    width: int = 0  # pixels of the saved image
    height: int = 0
    # placement on the slide as fractions of slide width/height (0..1)
    left: float = 0.0
    top: float = 0.0
    rel_width: float = 0.0
    rel_height: float = 0.0
    cropped: bool = False
    rotation: float = 0.0
    flip_h: bool = False
    flip_v: bool = False
    in_group: bool = False
    group_pictures: int = 1  # number of pictures in the same group (1 = not grouped)
    reuse_count: int = 1  # how many slides show the same asset
    supported: bool = True
    note: str = ""  # limitation / flag for review

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- helpers
def _frac(v: Optional[int], total: int) -> float:
    if v is None or not total:
        return 0.0
    return max(-1.0, min(2.0, v / total))


def _crop_from_srcrect(el) -> Tuple[float, float, float, float]:
    """Return (l, t, r, b) crop fractions from an <a:srcRect> element (values in 1/1000 %)."""
    if el is None:
        return (0.0, 0.0, 0.0, 0.0)
    vals = []
    for k in ("l", "t", "r", "b"):
        raw = el.get(k)
        try:
            vals.append(max(0.0, min(0.99, int(raw) / 100000.0)) if raw else 0.0)
        except ValueError:
            vals.append(0.0)
    return tuple(vals)  # type: ignore[return-value]


def _xfrm_flags(sp_element) -> Tuple[float, bool, bool]:
    """Rotation (degrees) and flips from the shape's <a:xfrm>."""
    xfrm = sp_element.find(".//a:xfrm", NS)
    if xfrm is None:
        return 0.0, False, False
    rot = xfrm.get("rot")
    try:
        rotation = (int(rot) / 60000.0) if rot else 0.0
    except ValueError:
        rotation = 0.0
    return rotation, xfrm.get("flipH") == "1", xfrm.get("flipV") == "1"


def _apply_transform(img: Image.Image, crop: Tuple[float, float, float, float], rotation: float, flip_h: bool, flip_v: bool) -> Image.Image:
    l, t, r, b = crop
    if any(v > 0 for v in crop):
        w, h = img.size
        box = (int(round(l * w)), int(round(t * h)), int(round(w - r * w)), int(round(h - b * h)))
        if box[2] - box[0] >= 2 and box[3] - box[1] >= 2:
            img = img.crop(box)
    if flip_h:
        img = ImageOps.mirror(img)
    if flip_v:
        img = ImageOps.flip(img)
    if rotation and abs(rotation % 360) > 0.01:
        # PowerPoint rotates clockwise; PIL rotates counter-clockwise
        img = img.rotate(-rotation, expand=True, resample=Image.BICUBIC)
    return img


def _save(img_bytes: bytes, ext: str, transform_needed: bool, dest: Path) -> Tuple[Path, str, int, int]:
    """Save the visible image. Returns (path, format, width, height)."""
    if not transform_needed and ext in ("png", "jpeg", "jpg"):
        fmt = "jpeg" if ext in ("jpg", "jpeg") else "png"
        out = dest.with_suffix("." + ("jpg" if fmt == "jpeg" else "png"))
        with Image.open(io.BytesIO(img_bytes)) as im:
            _check_dims(im)  # header only - nothing decoded yet
            w, h = im.width, im.height
        out.write_bytes(img_bytes)
        return out, fmt, w, h
    with Image.open(io.BytesIO(img_bytes)) as im:
        _check_dims(im)
        im.load()
        if im.mode in ("P", "LA", "RGBA") or "transparency" in im.info:
            im2 = im.convert("RGBA")
        else:
            im2 = im.convert("RGB")
        out = dest.with_suffix(".png")
        im2.save(out, "PNG", optimize=True)
        return out, "png", im2.width, im2.height


# ------------------------------------------------------------------------ extraction
def _iter_pictures(shapes, in_group: bool = False, group_count: int = 1):
    """Yield (shape, in_group, group_picture_count) for every picture-like shape, depth first."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in shapes:
        st = shape.shape_type
        if st == MSO_SHAPE_TYPE.GROUP:
            members = list(shape.shapes)
            n_pics = sum(1 for m in members if m.shape_type in (MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.PLACEHOLDER, MSO_SHAPE_TYPE.GROUP) or _has_blip(m))
            yield from _iter_pictures(members, True, max(1, n_pics))
        else:
            yield shape, in_group, group_count


def _has_blip(shape) -> bool:
    try:
        return shape._element.find(".//a:blip", NS) is not None
    except Exception:
        return False


def _blob_for(part, blip) -> Optional[Tuple[bytes, str]]:
    r_id = blip.get(f"{{{NS['r']}}}embed")
    if not r_id:
        return None
    try:
        image_part = part.related_part(r_id)
    except KeyError:
        return None
    blob = getattr(image_part, "blob", None)
    if not blob:
        return None
    ext = (getattr(image_part, "ext", None) or Path(getattr(image_part, "partname", "x.bin")).suffix.lstrip(".") or "bin").lower()
    if ext == "jpg":
        ext = "jpeg"
    return blob, ext


def extract_slide_images(pptx_path: Path, out_dir: Path, *, max_slides: int = 300, min_pixels: int = 8) -> List[ExtractedImage]:
    """Extract every embedded image placement of the presentation into ``out_dir``."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    out_dir.mkdir(parents=True, exist_ok=True)
    prs = Presentation(str(pptx_path))
    slide_w, slide_h = prs.slide_width or 1, prs.slide_height or 1
    results: List[ExtractedImage] = []
    seen_sha_slides: Dict[str, set] = {}

    for s_idx, slide in enumerate(prs.slides, start=1):
        if s_idx > max_slides:
            break
        placements: List[tuple] = []  # (shape_or_None, kind, blob, ext, crop, rot, flipH, flipV, bbox, in_group, group_n, name)

        # background picture fill
        try:
            bg = slide._element.find(".//p:cSld/p:bg//a:blip", NS)
            if bg is not None:
                got = _blob_for(slide.part, bg)
                if got:
                    src_rect = slide._element.find(".//p:cSld/p:bg//a:srcRect", NS)
                    placements.append((None, "background", got[0], got[1], _crop_from_srcrect(src_rect), 0.0, False, False, (0, 0, slide_w, slide_h), False, 1, "background"))
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("background inspection failed on slide %s: %s", s_idx, e)

        for shape, in_group, group_n in _iter_pictures(slide.shapes):
            try:
                el = shape._element
                blips = el.findall(".//a:blip", NS)
                if not blips:
                    continue
                st = shape.shape_type
                is_picture = st == MSO_SHAPE_TYPE.PICTURE or (st == MSO_SHAPE_TYPE.PLACEHOLDER and hasattr(shape, "image"))
                kind = "group_picture" if (in_group and is_picture) else ("picture" if st == MSO_SHAPE_TYPE.PICTURE else ("placeholder" if is_picture else "shape_fill"))
                blip = blips[0]
                got = _blob_for(shape.part, blip)
                if not got:
                    continue
                blob, ext = got
                if is_picture:
                    crop = (
                        max(0.0, float(getattr(shape, "crop_left", 0) or 0)),
                        max(0.0, float(getattr(shape, "crop_top", 0) or 0)),
                        max(0.0, float(getattr(shape, "crop_right", 0) or 0)),
                        max(0.0, float(getattr(shape, "crop_bottom", 0) or 0)),
                    )
                else:
                    crop = _crop_from_srcrect(el.find(".//a:srcRect", NS))
                rotation, flip_h, flip_v = _xfrm_flags(el)
                bbox = (shape.left or 0, shape.top or 0, shape.width or 0, shape.height or 0)
                placements.append((shape, kind, blob, ext, crop, rotation, flip_h, flip_v, bbox, in_group, group_n, shape.name or ""))
            except Exception as e:
                logger.warning("Slide %s: could not inspect shape %s: %s", s_idx, getattr(shape, "name", "?"), e.__class__.__name__)

        for idx, (shape, kind, blob, ext, crop, rotation, flip_h, flip_v, bbox, in_group, group_n, name) in enumerate(placements, start=1):
            sha = hashlib.sha256(blob).hexdigest()
            seen_sha_slides.setdefault(sha, set()).add(s_idx)
            item = ExtractedImage(
                slide_number=s_idx,
                index=idx,
                shape_name=name[:80],
                source_kind=kind,
                original_ext=ext,
                sha256=sha,
                left=_frac(bbox[0], slide_w),
                top=_frac(bbox[1], slide_h),
                rel_width=_frac(bbox[2], slide_w),
                rel_height=_frac(bbox[3], slide_h),
                cropped=any(v > 0.001 for v in crop),
                rotation=rotation,
                flip_h=flip_h,
                flip_v=flip_v,
                in_group=in_group,
                group_pictures=group_n,
            )
            if ext in VECTOR_EXTS or ext not in RASTER_EXTS:
                item.supported = False
                item.note = f"unsupported image format '{ext}' (vector/other) - cannot reproduce its visible appearance; review the full-slide rendering"
                results.append(item)
                continue
            dest = out_dir / f"s{s_idx:03d}_{idx:02d}"
            try:
                transform_needed = item.cropped or bool(rotation) or flip_h or flip_v or ext not in ("png", "jpeg", "jpg")
                if transform_needed:
                    with Image.open(io.BytesIO(blob)) as im:
                        _check_dims(im)
                        im.load()
                        im2 = _apply_transform(im.convert("RGBA") if im.mode in ("P", "LA", "RGBA") or "transparency" in im.info else im.convert("RGB"), crop, rotation, flip_h, flip_v)
                        buf = io.BytesIO()
                        im2.save(buf, "PNG", optimize=True)
                        saved, fmt, w, h = _save(buf.getvalue(), "png", False, dest)
                else:
                    saved, fmt, w, h = _save(blob, ext, False, dest)
                if w < min_pixels or h < min_pixels:
                    item.note = "image is only a few pixels"
                item.file_ref = f"images/emb/{saved.name}"
                item.file_ext = fmt
                item.width, item.height = w, h
            except Exception as e:
                item.supported = False
                item.note = f"could not decode/transform the image ({e.__class__.__name__}); review the full-slide rendering"
                logger.warning("Slide %s image %s: %s", s_idx, idx, item.note)
            results.append(item)

    for item in results:
        item.reuse_count = len(seen_sha_slides.get(item.sha256, {item.slide_number}))
    return results
