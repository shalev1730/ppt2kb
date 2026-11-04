"""Generators for test presentations (used by the test-suite and the Windows validation script)."""
from __future__ import annotations

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _font(size: int):
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def screenshot_png(w: int = 900, h: int = 560, seed: int = 1, label: str = "Settings") -> bytes:
    """A synthetic application screenshot: window chrome, menu, form fields, table rows."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), (245, 246, 248))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, w, 36], fill=(44, 62, 80))
    d.text((12, 9), f"ServiceNow - {label}", fill="white", font=_font(16))
    d.rectangle([0, 36, 180, h], fill=(236, 240, 241))
    for i in range(10):
        d.text((14, 50 + i * 30), f"Menu item {i+1}", fill=(52, 73, 94), font=_font(13))
    for i in range(8):
        y = 60 + i * 52
        d.text((210, y), f"Field {i+1}:", fill=(30, 30, 30), font=_font(14))
        d.rectangle([330, y - 4, 330 + rnd.randint(200, 480), y + 24], outline=(149, 165, 166), fill="white")
        d.text((336, y), f"value_{rnd.randint(100, 999)}", fill=(44, 62, 80), font=_font(13))
    d.rectangle([210, 480, w - 20, h - 20], outline=(127, 140, 141))
    for i in range(3):
        d.line([210, 500 + i * 20, w - 20, 500 + i * 20], fill=(189, 195, 199))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def diagram_icon_png(kind: str = "server", size: int = 96) -> bytes:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if kind == "server":
        d.rectangle([12, 8, size - 12, size - 8], fill=(52, 152, 219), outline=(41, 128, 185), width=3)
        for i in range(3):
            d.rectangle([20, 16 + i * 24, size - 20, 30 + i * 24], fill=(236, 240, 241))
            d.ellipse([size - 32, 19 + i * 24, size - 24, 27 + i * 24], fill=(46, 204, 113))
    elif kind == "db":
        d.ellipse([14, 8, size - 14, 36], fill=(155, 89, 182), outline=(142, 68, 173), width=3)
        d.rectangle([14, 22, size - 14, size - 20], fill=(155, 89, 182))
        d.ellipse([14, size - 34, size - 14, size - 6], fill=(142, 68, 173))
    else:  # client
        d.rectangle([8, 16, size - 8, size - 28], fill=(52, 73, 94), outline=(44, 62, 80), width=3)
        d.rectangle([14, 22, size - 14, size - 34], fill=(236, 240, 241))
        d.rectangle([size // 2 - 14, size - 26, size // 2 + 14, size - 12], fill=(44, 62, 80))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def logo_png(size: int = 120) -> bytes:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse([4, 4, size - 4, size - 4], fill=(31, 95, 191))
    d.text((size // 2 - 14, size // 2 - 10), "KB", fill="white", font=_font(22))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def separator_png() -> bytes:
    im = Image.new("RGB", (1200, 6), (31, 95, 191))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def photo_jpeg() -> bytes:
    rnd = random.Random(7)
    im = Image.new("RGB", (640, 420))
    px = im.load()
    for y in range(420):
        for x in range(640):
            px[x, y] = (int(120 + 100 * (x / 640)), int(60 + 150 * (y / 420)), rnd.randint(40, 200))
    d = ImageDraw.Draw(im)
    d.text((40, 40), "Error: connection refused (port 443)", fill="white", font=_font(28))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def build_embedded_deck(path: Path, slides: int = 60) -> Path:
    """A deck exercising every extraction case. Slide plan:

    1  title slide (logo only)                              -> no informative image
    2  'תהליך התחברות' screenshot + logo                    -> 1 image
    3  'ארכיטקטורה' screenshot + grouped diagram (3 icons)  -> 4 images (1 + group of 3)
    4  'משואה 750' cropped screenshot + rotated icon        -> 2 images, cropped & rotated
    5  text only, no logo                                  -> no embedded image at all
    6  reused screenshot (same bytes as slide 2) + separator line -> 1 informative + 1 decorative
    7  JPEG photo with an error message                    -> 1 jpeg kept as jpeg
    8..N text slides, logo on each, screenshot every 5th slide   (80 images in total, 59 of them the logo)
    """
    from pptx import Presentation
    from pptx.util import Inches, Emu

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank, title_only = prs.slide_layouts[6], prs.slide_layouts[5]
    logo = io.BytesIO(logo_png())
    shot_a = screenshot_png(seed=1, label="Login")
    shot_b = screenshot_png(seed=2, label="Architecture")
    shot_c = screenshot_png(seed=3, label="Beacon 750")

    def add_logo(slide):
        logo.seek(0)
        slide.shapes.add_picture(logo, Inches(12.2), Inches(0.2), width=Inches(0.8))

    def title(slide, text, body=None):
        slide.shapes.title.text = text
        if body:
            tb = slide.shapes.add_textbox(Inches(0.6), Inches(1.4), Inches(6), Inches(2))
            tb.text_frame.text = body

    s = prs.slides.add_slide(title_only)
    title(s, "ServiceNow Fundamentals / יסודות המערכת")
    add_logo(s)

    s = prs.slides.add_slide(title_only)
    title(s, "תהליך התחברות", "1. פתח את הקונסולה\n2. הזן שם משתמש וסיסמה\n3. לחץ Login")
    s.shapes.add_picture(io.BytesIO(shot_a), Inches(6.5), Inches(1.4), width=Inches(6))
    add_logo(s)

    s = prs.slides.add_slide(title_only)
    title(s, "ארכיטקטורה - Client, API, Database")
    s.shapes.add_picture(io.BytesIO(shot_b), Inches(0.6), Inches(1.5), width=Inches(5.5))
    grp = s.shapes.add_group_shape()
    for i, kind in enumerate(("client", "server", "db")):
        grp.shapes.add_picture(io.BytesIO(diagram_icon_png(kind)), Inches(7 + i * 2), Inches(3), width=Inches(1))
    add_logo(s)

    s = prs.slides.add_slide(title_only)
    title(s, "משואה 750")
    pic = s.shapes.add_picture(io.BytesIO(shot_c), Inches(0.8), Inches(1.5), width=Inches(5))
    pic.crop_left, pic.crop_right, pic.crop_top = 0.25, 0.25, 0.1
    rot = s.shapes.add_picture(io.BytesIO(diagram_icon_png("server", 160)), Inches(8), Inches(2), width=Inches(1.5))
    rot.rotation = 90
    add_logo(s)

    s = prs.slides.add_slide(title_only)
    title(s, "Business Rules - הסבר", "Before / After\ncurrent.short_description\ngs.info('Message')")
    # deliberately no logo: a slide with no embedded image at all

    s = prs.slides.add_slide(title_only)
    title(s, "Login screen (reused)")
    s.shapes.add_picture(io.BytesIO(shot_a), Inches(6.5), Inches(1.4), width=Inches(6))
    s.shapes.add_picture(io.BytesIO(separator_png()), Inches(0.5), Inches(7.0), width=Inches(12))
    add_logo(s)

    s = prs.slides.add_slide(title_only)
    title(s, "Error handling - שגיאת חיבור")
    s.shapes.add_picture(io.BytesIO(photo_jpeg()), Inches(1), Inches(1.5), width=Inches(6))
    add_logo(s)

    for i in range(8, slides + 1):
        s = prs.slides.add_slide(title_only)
        title(s, f"Topic {i} / נושא {i}", f"Step 1: configure the field on slide {i}\nשלב 2: שמור את הרשומה")
        if i % 5 == 0:
            s.shapes.add_picture(io.BytesIO(screenshot_png(seed=i, label=f"Form {i}")), Inches(6.5), Inches(1.4), width=Inches(6))
        add_logo(s)
    prs.save(path)
    return path


if __name__ == "__main__":
    import sys

    build_embedded_deck(Path(sys.argv[1] if len(sys.argv) > 1 else "embedded_test.pptx"), int(sys.argv[2]) if len(sys.argv) > 2 else 60)


def theme_background_png(w: int = 1600, h: int = 900, seed: int = 7) -> bytes:
    """A soft gradient 'theme' picture with a few shapes - looks like a slide background."""
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(0, w, 1):
            px[x, y] = (20 + x * 60 // w, 60 + y * 80 // h, 120 + (x + y) * 60 // (w + h))
    d = ImageDraw.Draw(im)
    for _ in range(12):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(40, 200)
        d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 255, 255), width=3)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def _set_background_picture(slide_like, png: bytes) -> None:
    """Give a slide / layout / master a picture background fill (``<p:bg><p:bgPr><a:blipFill>``)."""
    from pptx.oxml import parse_xml
    from pptx.oxml.ns import qn

    _, r_id = slide_like.part.get_or_add_image_part(io.BytesIO(png))
    bg = parse_xml(
        '<p:bg xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<p:bgPr><a:blipFill dpi="0" rotWithShape="1"><a:blip r:embed="{r_id}"/><a:srcRect/><a:stretch><a:fillRect/></a:stretch></a:blipFill>'
        "<a:effectLst/></p:bgPr></p:bg>"
    )
    c_sld = slide_like._element.find(qn("p:cSld"))
    old = c_sld.find(qn("p:bg"))
    if old is not None:
        c_sld.remove(old)
    c_sld.insert(0, bg)


def build_background_deck(path: Path) -> Path:
    """A deck exercising the background / decoration cases (1.1.2). Slide plan:

    1  'Login flow'      : picture background fill + one content screenshot        -> bg excluded, screenshot kept
    2  'Theme 1'         : full-bleed theme picture at the back, title + text over it -> full_bleed excluded
    3  'Theme 2'         : same theme picture + a JPEG photo (content)              -> theme excluded, photo kept
    4  'Theme 3'         : same theme picture only                                   -> excluded (repeated x4 as well)
    5  'Theme 4'         : same theme picture + diagram group (content)              -> theme excluded, group kept
    6  (blank layout)    : one photo as the sole content, ~90% of the slide          -> KEPT (large is not background)
    7  'Layout bg'       : layout 'Title and Content' with a picture background      -> master_background excluded
    8  'Plain'           : text only
    The slide master carries a small logo picture -> a layout_picture row on every slide, excluded.
    """
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank, title_only, title_content = prs.slide_layouts[6], prs.slide_layouts[5], prs.slide_layouts[1]
    theme = theme_background_png()
    # master logo (shown on every slide) - python-pptx has no add_picture on masters, so build the <p:pic> directly
    from pptx.oxml.shapes.picture import CT_Picture

    _, logo_rid = prs.slide_master.part.get_or_add_image_part(io.BytesIO(logo_png(90)))
    prs.slide_master.shapes._spTree.append(CT_Picture.new_pic(900, "Master logo", "logo.png", logo_rid, Inches(12.4), Inches(6.7), Inches(0.6), Inches(0.6)))
    # layout with a picture background (used by slide 7 only)
    _set_background_picture(title_content, theme_background_png(seed=11))

    def title(slide, text, body=None):
        slide.shapes.title.text = text
        if body:
            tb = slide.shapes.add_textbox(Inches(0.6), Inches(1.4), Inches(6), Inches(2))
            tb.text_frame.text = body

    s = prs.slides.add_slide(title_only)
    _set_background_picture(s, theme_background_png(seed=3))
    title(s, "Login flow / תהליך התחברות", "1. Open the portal\n2. Enter credentials")
    s.shapes.add_picture(io.BytesIO(screenshot_png(seed=21, label="Login")), Inches(6.5), Inches(1.4), width=Inches(6))

    for i, (name, extra) in enumerate((("Theme 1", None), ("Theme 2", "photo"), ("Theme 3", None), ("Theme 4", "group")), start=2):
        s = prs.slides.add_slide(title_only)
        # full-bleed picture first = back-most; the title placeholder already exists above it in z-order? No:
        # placeholders come first in the shape tree, so move the picture to the back explicitly.
        pic = s.shapes.add_picture(io.BytesIO(theme), 0, 0, width=prs.slide_width, height=prs.slide_height)
        sp_tree = s.shapes._spTree
        sp_tree.remove(pic._element)
        sp_tree.insert(2, pic._element)  # after nvGrpSpPr and grpSpPr -> back-most shape
        title(s, f"{name} - שלב {i}", f"Configuration value for step {i}: param_{i} = value_{i}")
        if extra == "photo":
            s.shapes.add_picture(io.BytesIO(photo_jpeg()), Inches(7), Inches(1.5), width=Inches(5))
        if extra == "group":
            icons = [s.shapes.add_picture(io.BytesIO(diagram_icon_png(k, 140)), Inches(7 + j * 1.8), Inches(3), width=Inches(1.2)) for j, k in enumerate(("client", "server", "db"))]
            s.shapes.add_group_shape(icons)

    s = prs.slides.add_slide(blank)
    s.shapes.add_picture(io.BytesIO(screenshot_png(w=1600, h=900, seed=31, label="Full-screen screenshot")), Inches(0.6), Inches(0.4), width=Inches(12.2), height=Inches(6.8))

    s = prs.slides.add_slide(title_content)
    title(s, "Layout background slide", "Field: incident.short_description")
    s.shapes.add_picture(io.BytesIO(diagram_icon_png("server", 160)), Inches(8), Inches(2), width=Inches(1.5))

    s = prs.slides.add_slide(title_only)
    title(s, "Plain text slide", "gs.info('done')")
    prs.save(path)
    return path
