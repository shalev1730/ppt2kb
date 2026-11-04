"""
Embedded-image mode: extraction, decorative filtering, manual selection,
meaningful Hebrew file names, slide->image->attachment mapping, retry and
duplicate prevention, quality validation / review, RTL HTML - on a 60-slide
deck that exercises every extraction case (see tests/deckgen.py).
"""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import pytest
from PIL import Image

from conftest import upload, wait_for
from deckgen import build_embedded_deck, screenshot_png, diagram_icon_png, logo_png

pytestmark = pytest.mark.timeout(900)
KB = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


@pytest.fixture(scope="session")
def deck_emb(tmp_path_factory) -> Path:
    return build_embedded_deck(tmp_path_factory.mktemp("decks") / "embedded_60.pptx", 60)


def _sections(html: str) -> dict:
    """{slide_number: section html} parsed from the article body."""
    return {int(m.group(1)): m.group(2) for m in re.finditer(r'<section class="ppt2kb-slide" data-slide="(\d+)"[^>]*>(.*?)</section>', html, re.DOTALL)}


# ------------------------------------------------------------------ extraction
def test_extraction_covers_all_cases(deck_emb, tmp_path):
    from ppt2kb.extract import extract_slide_images

    imgs = extract_slide_images(deck_emb, tmp_path / "emb")
    per_slide = {}
    for im in imgs:
        per_slide.setdefault(im.slide_number, []).append(im)
    assert len(imgs) == 80
    assert [len(per_slide.get(n, [])) for n in range(1, 8)] == [1, 2, 5, 3, 0, 3, 2]  # logo on every slide except 5
    # multiple images + group members on slide 3
    s3 = per_slide[3]
    assert sum(1 for i in s3 if i.in_group) == 3 and all(i.group_pictures == 3 for i in s3 if i.in_group)
    # cropped image keeps only the visible 50% x 90% area, pixel-exact
    s4 = per_slide[4]
    cropped = next(i for i in s4 if i.cropped)
    with Image.open(tmp_path / "emb" / Path(cropped.file_ref).name) as got, Image.open(io.BytesIO(screenshot_png(seed=3, label="Beacon 750"))) as orig:
        w, h = orig.size
        expected = orig.crop((int(round(0.25 * w)), int(round(0.10 * h)), int(round(w - 0.25 * w)), h)).convert("RGB")
        assert got.size == expected.size == (450, 504)
        assert got.convert("RGB").tobytes() == expected.tobytes()
    # rotated image (90 degrees clockwise) is reproduced
    rotated = next(i for i in s4 if i.rotation == 90)
    with Image.open(tmp_path / "emb" / Path(rotated.file_ref).name) as got, Image.open(io.BytesIO(diagram_icon_png("server", 160))) as orig:
        assert got.size == (160, 160)
        assert got.convert("RGBA").tobytes() == orig.rotate(-90, expand=True).convert("RGBA").tobytes()
    # reused assets share a sha256 and report the reuse count
    logo_sha = hashlib.sha256(logo_png()).hexdigest()
    logos = [i for i in imgs if i.sha256 == logo_sha]
    assert len(logos) == 59 and all(i.reuse_count == 59 for i in logos)
    shot_a = [i for i in imgs if i.slide_number in (2, 6) and i.width == 900]
    assert len(shot_a) == 2 and shot_a[0].sha256 == shot_a[1].sha256 and shot_a[0].reuse_count == 2
    # untransformed JPEG is stored byte-for-byte in its original format
    jpg = next(i for i in per_slide[7] if i.original_ext == "jpeg")
    assert jpg.file_ext == "jpeg" and jpg.file_ref.endswith(".jpg")
    assert hashlib.sha256((tmp_path / "emb" / Path(jpg.file_ref).name).read_bytes()).hexdigest() == jpg.sha256
    # slide 5 has no picture at all; placements of the others are recorded
    assert 5 not in per_slide and 0 < per_slide[1][0].rel_width < 0.1


def test_decorative_filtering_is_conservative(deck_emb, tmp_path):
    from ppt2kb.extract import classify_images, extract_slide_images

    imgs = extract_slide_images(deck_emb, tmp_path / "images" / "emb")
    cls = classify_images(imgs, tmp_path, 60)
    by = {(i.slide_number, i.index): (i, c) for i, c in zip(imgs, cls)}
    logo_sha = hashlib.sha256(logo_png()).hexdigest()
    # repeated logo excluded everywhere, with a human-readable reason
    for i, c in zip(imgs, cls):
        if i.sha256 == logo_sha:
            assert not c["selected"] and any("repeated" in r for r in c["reasons"])
    # screenshots, the JPEG error photo, the cropped and rotated images are kept
    assert by[(2, 1)][1]["selected"] and by[(3, 1)][1]["selected"] and by[(7, 1)][1]["selected"]
    assert by[(4, 1)][1]["selected"] and by[(4, 2)][1]["selected"]
    # small icons inside the diagram group are kept (small is not decorative by itself)
    assert all(by[(3, k)][1]["selected"] for k in (2, 3, 4))
    # separator line excluded
    sep = by[(6, 2)]
    assert sep[0].width == 1200 and not sep[1]["selected"] and any("aspect" in r for r in sep[1]["reasons"])
    assert sum(c["selected"] for c in cls) == 20


# ------------------------------------------------------------- end-to-end
def test_embedded_mode_end_to_end(client, deck_emb, qwen_ctl, sn_ctl):
    job = wait_for(client, upload(client, deck_emb, title="ServiceNow Fundamentals", image_mode="embedded", exclude_backgrounds="false")["id"])
    assert job["status"] == "ready" and job["counts"]["done"] == 60
    full = client.get(f"/api/jobs/{job['id']}").json()
    assert full["image_mode"] == "embedded" and full["exclude_backgrounds"] is False
    assert full["images_total"] == 80 and full["images_selected"] == 20 and full["images_background"] == 60  # logo x59 + separator
    s2 = full["slides"][1]
    assert s2["title"] == "תהליך התחברות"  # editable PPTX title preferred over the AI title
    assert [im["selected"] for im in s2["images"]] == [True, False]
    assert s2["images"][0]["url"] and client.get(s2["images"][0]["url"]).headers["content-type"] == "image/png"
    assert full["slides"][4]["images"] == []  # slide 5: no embedded image -> title + explanation only
    # the full slide image is still available for the reviewer (and was what the model received)
    assert client.get(s2["image_url"]).status_code == 200
    stats = qwen_ctl.stats()
    assert stats["images_seen"] == 60
    # the model got the reliable PPTX text and neighbour titles as context
    assert any("<slide_text>" in p and "תהליך התחברות" in p for p in stats["prompts"])
    assert any("previous slide title" in p and "next slide title" in p for p in stats["prompts"])

    # manual selection: exclude the screenshot of slide 2, include the logo of slide 1
    r = client.patch(f"/api/jobs/{job['id']}/slides/2/images/1", json={"selected": False})
    assert r.status_code == 200 and r.json()["selected"] is False and r.json()["auto_selected"] is True
    assert client.patch(f"/api/jobs/{job['id']}/slides/1/images/1", json={"selected": True}).json()["selected"] is True
    j = client.get(f"/api/jobs/{job['id']}?slides=false").json()
    assert j["images_selected"] == 20

    # preview: figures under the right sections, no figure where nothing is selected
    prev = client.get(f"/api/jobs/{job['id']}/preview.html").text
    sec = _sections(prev)
    assert len(sec) == 60 and "<figure" not in sec[2] and "<figure" not in sec[5]
    assert sec[1].count("<figure") == 1 and sec[3].count("<figure") == 4 and sec[4].count("<figure") == 2
    assert 'dir="rtl"' in sec[2] and "<h2" in sec[2] and sec[2].count("<h2") == 1
    assert "slides/4/images/1" in sec[4] and 'alt="משואה 750 - image 1"' in sec[4]
    assert "<script" not in prev and "background" not in prev.lower()
    # single-section preview (UI "Preview section"): the same renderer, only that slide, no deck header/TOC
    one = client.get(f"/api/jobs/{job['id']}/preview.html?slide=4").text
    assert one.count("<h2") == 1 and "משואה 750" in one and one.count("<figure") == 2 and "ppt2kb-toc" not in one
    assert client.get(f"/api/jobs/{job['id']}/preview.html?slide=999").status_code == 404
    assert full["source_kind"] == "pptx" and all(k in full["slides"][0] for k in ("quality", "reviewed", "images"))

    # publish (Embedded Images Only): every original image is attached - identical images once - with
    # meaningful file names; the body shows the selected images under their slides; no slide renders
    r = client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    assert r.status_code == 202, r.text
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and job["servicenow"]["image_mode"] == "embedded" and job["servicenow"]["attachments"] == 21
    data = sn_ctl.articles()
    art = data["articles"][0]
    atts = {a["file_name"]: a["sys_id"] for a in data["attachments"] if a["table_sys_id"] == art["sys_id"]}
    assert len(atts) == 21 and not any(n.startswith("slide_") for n in atts)  # 80 images, 21 distinct (logo x59, screenshot x2)
    assert "004_משואה_750_image_01.png" in atts and "004_משואה_750_image_02.png" in atts
    assert "003_ארכיטקטורה_-_Client_API_Database_image_01.png" in atts
    assert "007_Error_handling_-_שגיאת_חיבור_image_01.jpg" in atts  # JPEG kept as JPEG
    assert "001_ServiceNow_Fundamentals_יסודות_המערכת_image_01.png" in atts  # the logo, attached once under its first slide
    assert "002_תהליך_התחברות_image_01.png" in atts  # attached (all originals) even though excluded from the body
    sec = _sections(art["text"])
    refs4 = re.findall(r'sys_attachment\.do\?sys_id=([0-9a-f]{32})', sec[4])
    assert [atts["004_משואה_750_image_01.png"], atts["004_משואה_750_image_02.png"]] == refs4
    assert "<figure" not in sec[2] and "<figure" not in sec[5]  # excluded by the reviewer / no image at all
    assert art["text"].count("<figure") == 20 and art["workflow_state"] == "draft"
    # every figure reference resolves to an attachment of this article (no broken images)
    refs = re.findall(r'sys_attachment\.do\?sys_id=([0-9a-f]{32})', art["text"])
    assert refs and set(refs) <= set(atts.values())
    # slide->image->attachment mapping is exposed to the UI; repeated logo shares one attachment
    full = client.get(f"/api/jobs/{job['id']}").json()
    im = full["slides"][3]["images"][0]
    assert im["file_name"] == "004_משואה_750_image_01.png" and im["attachment_sys_id"] == atts["004_משואה_750_image_01.png"]
    logo_ids = {i["attachment_sys_id"] for s in full["slides"] for i in s["images"] if i["reuse_count"] == 59}
    assert logo_ids == {atts["001_ServiceNow_Fundamentals_יסודות_המערכת_image_01.png"]}
    # attachment bytes are the extracted (cropped) image, not a slide screenshot
    import httpx

    png = httpx.get(sn_ctl.base + f"/sys_attachment.do?sys_id={im['attachment_sys_id']}").content
    with Image.open(io.BytesIO(png)) as got:
        assert got.size == (450, 504)

    # idempotent re-publish: no second article, no duplicate attachments, same names
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    assert len(data["articles"]) == 1 and len(data["attachments"]) == 21


def test_embedded_publish_partial_failure_recovery(client, deck_emb, qwen_ctl, sn_ctl):
    job = wait_for(client, upload(client, deck_emb, image_mode="embedded", exclude_backgrounds="false")["id"])
    sn_ctl.set(fail_attachment_after=7)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "publish_failed" and len(sn_ctl.articles()["attachments"]) == 7
    sn_ctl.set(fail_attachment_after=0, reset_counters=True)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    assert job["status"] == "published" and len(data["articles"]) == 1 and len(data["attachments"]) == 21
    assert job["image_mode"] == "embedded" and job["servicenow"]["image_mode"] == "embedded"  # the retry kept the mode
    names = [a["file_name"] for a in data["attachments"]]
    assert len(names) == len(set(names))


def test_full_slide_mode_still_available(client, deck_emb, sn_ctl):
    """Mode 3 (Full Slides Only): 60 slide renders, meaningful names, no embedded images."""
    job = wait_for(client, upload(client, deck_emb, image_mode="full_slide")["id"])
    assert job["image_mode"] == "full_slide"
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    names = sorted(a["file_name"] for a in data["attachments"])
    assert job["status"] == "published" and len(names) == 60 and job["servicenow"]["attachments"] == 60
    assert names[1] == "002_תהליך_התחברות.png" and names[3] == "004_משואה_750.png" and not any("_image_" in n for n in names)
    sec = _sections(data["articles"][0]["text"])
    assert len(sec) == 60 and all(sec[n].count("<figure") == 1 for n in sec)  # exactly one full-slide figure per section
    assert list(sec) == list(range(1, 61))


def test_presentation_saved_by_older_version_gets_images_on_publish(client, deck_emb, sn_ctl):
    """Old jobs have no slide_images rows (and 1.1.0 jobs carry mode 'embedded'): extraction runs lazily on publish."""
    job = wait_for(client, upload(client, deck_emb, image_mode="embedded", exclude_backgrounds="false")["id"])
    ctx = client.app.state.ctx
    ctx.db._exec("DELETE FROM slide_images WHERE job_id = ?", (job["id"],))
    assert client.get(f"/api/jobs/{job['id']}?slides=false").json()["images_total"] == 0
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and job["servicenow"]["attachments"] == 21
    # explicit re-extraction endpoint also works
    assert client.post(f"/api/jobs/{job['id']}/images/extract").json()["images"] == 80


def test_mode_setting_is_persistent_and_ascii_filenames(app_settings, deck_emb, sn_ctl):
    from fastapi.testclient import TestClient
    from ppt2kb.app import create_app

    with TestClient(create_app(app_settings)) as c:
        r = c.put("/api/config", json={"values": {"image_attachment_mode": "full_slide", "ascii_filenames": True}}).json()
        assert r["rejected"] == [] and r["config"]["image_attachment_mode"] == "full_slide"
        assert c.put("/api/config", json={"values": {"image_attachment_mode": "bogus"}}).json()["rejected"] == ["image_attachment_mode"]
    with TestClient(create_app(app_settings)) as c:  # restart
        cfg = c.get("/api/config").json()
        assert cfg["image_attachment_mode"] == "full_slide" and cfg["ascii_filenames"] is True
        job = wait_for(c, upload(c, deck_emb)["id"])
        assert c.get(f"/api/jobs/{job['id']}?slides=false").json()["image_mode"] == "full_slide"
        # switch this job to embedded with ASCII names
        c.patch(f"/api/jobs/{job['id']}", json={"image_mode": "embedded"})
        c.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
        job = wait_for(c, job["id"], statuses=("published", "publish_failed"))
        names = sorted(a["file_name"] for a in sn_ctl.articles()["attachments"])
        assert job["status"] == "published" and "004_750_image_01.png" in names and "007_Error_handling_image_01.jpg" in names and "003_Client_API_Database_image_01.png" in names
        assert all(n.isascii() for n in names)


# ------------------------------------------------------------- quality gate
def test_visual_description_is_rejected_and_retried(client, deck_emb, qwen_ctl):
    qwen_ctl.set(visual_first=True)
    job = wait_for(client, upload(client, deck_emb)["id"])
    assert job["status"] == "ready" and job["counts"]["done"] == 60
    st = qwen_ctl.stats()
    assert st["requests"] == 120 and st["corrections_seen"] == 60  # every slide retried once with a corrective hint
    s = client.get(f"/api/jobs/{job['id']}").json()["slides"][2]
    assert "background" not in s["content"] and s["quality"] == []


def test_persistently_bad_answers_need_review(client, deck_emb, qwen_ctl):
    qwen_ctl.set(visual_always=True)
    job = wait_for(client, upload(client, deck_emb)["id"])
    assert job["status"] == "partial" and job["counts"]["needs_review"] == 60 and "need review" in job["error"]
    s = client.get(f"/api/jobs/{job['id']}").json()["slides"][0]
    assert s["status"] == "needs_review" and "visual_only" in s["quality"] and "background" in s["content"]
    assert client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB}).status_code == 409
    # resume must not silently re-run reviewed slides; accepting after editing makes them publishable
    client.patch(f"/api/jobs/{job['id']}/slides/1", json={"edited_content": "מסך הכניסה: המשתמש מזין שם משתמש וסיסמה ולוחץ Login."})
    assert client.post(f"/api/jobs/{job['id']}/slides/1/accept").status_code == 200
    j = client.get(f"/api/jobs/{job['id']}?slides=false").json()
    assert j["counts"]["done"] == 1 and j["counts"]["needs_review"] == 59


def test_validation_rules():
    from ppt2kb.llm.validate import validate_description, is_blocking
    from ppt2kb.schemas.deck import SlideDescription

    ocr = "ACL הרשאות\nField Level\nTable Level\nread write create\nServer Side"
    assert "raw_ocr" in validate_description(SlideDescription(title="ACL", summary=ocr), ocr, original_text=ocr)
    assert "empty_summary" in validate_description(SlideDescription(title="ACL", summary=""), "{}", original_text=ocr)
    dup = "Access control lists restrict read, write and create operations per table and per field."
    assert "duplicate" in validate_description(SlideDescription(title="x", summary=dup), "", previous_content=dup)
    good = SlideDescription(title="ACL", summary="Access control lists restrict read, write and create operations on the incident table per field.", confidence="high")
    assert validate_description(good, "", original_text=ocr) == []
    assert is_blocking(["visual_only"]) and not is_blocking(["low_confidence"])


def test_rtl_and_structure_in_html():
    from ppt2kb.export.html import build_article_html
    from ppt2kb.schemas.deck import SlideData, SlideStatus

    s = SlideData(number=2, title="תהליך התחברות", status=SlideStatus.done, content="המשתמש מזין פרטי התחברות ולוחץ Login.\n\nשלבים:\n1. פתח את הקונסולה\n2. הזן שם משתמש\n\nמידע טכני חשוב:\n- table: sys_user\n- URL: https://sn.internal/login.do")
    html = build_article_html(title="מצגת", slides=[s], figures_for=lambda x: [("/sys_attachment.do?sys_id=abc", "תהליך התחברות - image 1")])
    assert '<h2 dir="rtl">2. תהליך התחברות</h2>' in html
    assert '<ol dir="rtl"><li>פתח את הקונסולה</li>' in html and '<strong>שלבים:</strong>' in html
    assert '<ul dir="ltr"><li>table: sys_user</li>' in html  # English list stays LTR inside an RTL section
    assert html.index("<figure") > html.index("</ul>")  # images come after the explanation
    assert 'alt="תהליך התחברות - image 1"' in html


def test_oversized_embedded_picture_is_reported_not_decoded(tmp_path):
    """A PPTX carrying a 9000x9000 PNG (decompression-bomb pattern): the picture is flagged, nothing is decoded, the job continues."""
    import struct
    import zlib
    from pptx import Presentation
    from pptx.util import Inches
    from ppt2kb.extract.images import extract_slide_images

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    bomb = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 9000, 9000, 8, 2, 0, 0, 0)) + chunk(b"IEND", b"")
    bomb_path = tmp_path / "bomb.png"
    bomb_path.write_bytes(bomb)
    good = tmp_path / "good.png"
    Image.new("RGB", (300, 200), (10, 20, 30)).save(good)
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.shapes.add_picture(str(bomb_path), Inches(0.5), Inches(0.5), width=Inches(4))
    s.shapes.add_picture(str(good), Inches(5), Inches(0.5), width=Inches(4))
    deck = tmp_path / "bomb.pptx"
    prs.save(deck)
    imgs = extract_slide_images(deck, tmp_path / "out")
    assert len(imgs) == 2
    assert not imgs[0].supported and "ImageTooLarge" in (imgs[0].note or "") and not imgs[0].file_ref
    assert imgs[1].supported and imgs[1].width == 300


# ------------------------------------------------------- image output modes (1.1.1)
def test_embedded_full_mode_is_default_and_attaches_both(client, deck_emb, qwen_ctl, sn_ctl):
    """Mode 2 (Embedded Images + Full Slides): body shows the 60 full slides only; attachments are the
    60 slide renders plus every original image (identical ones once); Qwen still gets the full slide."""
    job = wait_for(client, upload(client, deck_emb, title="Mode 2 deck")["id"])
    assert job["image_mode"] == "embedded_full" and job["exclude_backgrounds"] is True and job["status"] == "ready"  # defaults
    assert qwen_ctl.stats()["images_seen"] == 60  # analysis unchanged by the mode
    full = client.get(f"/api/jobs/{job['id']}").json()
    assert full["images_total"] == 20 and full["images_excluded"] == 60  # repeated logo and separator strip are decoration
    # preview: one full-slide figure per section, no embedded figures in the body
    prev = _sections(client.get(f"/api/jobs/{job['id']}/preview.html").text)
    assert len(prev) == 60 and all(prev[n].count("<figure") == 1 and f"slides/{n}/image\"" in prev[n] for n in prev)
    assert "slides/4/images/" not in prev[4]
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and job["servicenow"]["image_mode"] == "embedded_full"
    data = sn_ctl.articles()
    art = data["articles"][0]
    atts = {a["file_name"]: a["sys_id"] for a in data["attachments"] if a["table_sys_id"] == art["sys_id"]}
    slides_att = {n for n in atts if "_image_" not in n}
    images_att = {n for n in atts if "_image_" in n}
    assert len(slides_att) == 60 and len(images_att) == 19 and job["servicenow"]["attachments"] == 79  # 21 distinct originals minus logo and separator
    assert "004_משואה_750.png" in slides_att and "004_משואה_750_image_01.png" in images_att and "004_משואה_750_image_02.png" in images_att
    assert "001_ServiceNow_Fundamentals_יסודות_המערכת_image_01.png" not in images_att  # the repeated logo is excluded
    assert "005_Business_Rules_-_הסבר.png" in slides_att and not any(n.startswith("005_") for n in images_att)  # slide without embedded images
    # body: 60 sections in order, each exactly one figure = its own full slide render, nothing else
    sec = _sections(art["text"])
    assert list(sec) == list(range(1, 61))
    refs = re.findall(r'sys_attachment\.do\?sys_id=([0-9a-f]{32})', art["text"])
    assert len(refs) == 60
    by_id = {v: k for k, v in atts.items()}
    assert [by_id[r] for r in refs] == sorted(slides_att, key=lambda n: int(n[:3]))
    assert all(sec[n].count("<figure") == 1 for n in sec)
    # the full slide sits directly under the heading, the explanation beneath it
    assert sec[4].index("<figure") < sec[4].index("<p") and "Open the admin console" in sec[4]
    # attachment bytes: the full slide is the render, the embedded image is the extracted picture
    import httpx

    with Image.open(io.BytesIO(httpx.get(sn_ctl.base + f"/sys_attachment.do?sys_id={atts['004_משואה_750_image_01.png']}").content)) as im:
        assert im.size == (450, 504)
    with Image.open(io.BytesIO(httpx.get(sn_ctl.base + f"/sys_attachment.do?sys_id={atts['004_משואה_750.png']}").content)) as im:
        assert im.size[0] > 900  # a rendered slide, not the embedded picture
    # mapping exposed to the UI: every embedded image has a sys_id that is on the record
    full = client.get(f"/api/jobs/{job['id']}").json()
    ids = [i["attachment_sys_id"] for s in full["slides"] for i in s["images"] if not i["excluded"]]
    assert len(ids) == 20 and all(i in atts.values() for i in ids)
    assert all(i["attachment_sys_id"] == "" for s in full["slides"] for i in s["images"] if i["excluded"])  # never uploaded
    # idempotent re-publish
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert len(sn_ctl.articles()["attachments"]) == 79


def test_embedded_full_partial_failure_recovery(client, deck_emb, sn_ctl):
    job = wait_for(client, upload(client, deck_emb, exclude_backgrounds="false")["id"])  # mode 2, all originals
    sn_ctl.set(fail_attachment_after=65)  # fails after the 60 slides and 5 embedded images
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "publish_failed" and len(sn_ctl.articles()["attachments"]) == 65
    sn_ctl.set(fail_attachment_after=0, reset_counters=True)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    names = [a["file_name"] for a in data["attachments"]]
    assert job["status"] == "published" and len(data["articles"]) == 1 and len(names) == 81 and len(set(names)) == 81
    assert job["image_mode"] == "embedded_full"


def test_mode_change_after_publish_requires_explicit_republish(client, deck_emb, sn_ctl):
    """Changing the mode never touches the article by itself; a retry keeps the mode the article was created with;
    republishing rewrites the body with the new mode without duplicating anything."""
    job = wait_for(client, upload(client, deck_emb, image_mode="full_slide", exclude_backgrounds="false")["id"])
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and len(sn_ctl.articles()["attachments"]) == 60
    # switch to Embedded Images Only
    r = client.patch(f"/api/jobs/{job['id']}", json={"image_mode": "embedded"}).json()
    assert r["image_mode"] == "embedded" and r["servicenow"]["mode_changed"] is True
    assert len(sn_ctl.articles()["attachments"]) == 60  # nothing happened on ServiceNow
    # explicit republish with the new mode
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    assert job["status"] == "published" and job["servicenow"]["image_mode"] == "embedded" and not job["servicenow"].get("mode_changed")
    assert len(data["articles"]) == 1 and len(data["attachments"]) == 60 + 21  # old full-slide files are kept, new images added once
    sec = _sections(data["articles"][0]["text"])
    assert "<figure" not in sec[5] and sec[4].count("<figure") == 2 and "004_משואה_750.png" not in data["articles"][0]["text"]
    # a simulated failed retry must not switch modes silently: stored mode stays what the article was published with
    ctx = client.app.state.ctx
    j = ctx.db.get_job(job["id"])
    st = dict(j["servicenow"]); st["image_mode"] = "full_slide"  # pretend the article was created in another mode
    ctx.db.update_job(job["id"], servicenow=st, status="publish_failed")
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["servicenow"]["image_mode"] == "full_slide" and job["image_mode"] == "full_slide"
    # the mode cannot be changed while publishing (409) - checked through the state machine
    ctx.db.update_job(job["id"], status="publishing")
    assert client.patch(f"/api/jobs/{job['id']}", json={"image_mode": "embedded"}).status_code == 409
    ctx.db.update_job(job["id"], status="published")


def test_backward_compatibility_with_older_presentations(client, deck_emb, sn_ctl):
    """A job stored by 1.1.0 (no attachment_file_name column value, mode 'embedded' or no mode at all) and an
    article already carrying slide_NNN.png attachments from 1.0 keep working and keep their names."""
    job = wait_for(client, upload(client, deck_emb, image_mode="full_slide")["id"])
    ctx = client.app.state.ctx
    # simulate a 1.0.x article: attachments named slide_NNN.png already on the record, no stored names
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    ctx.db._exec("UPDATE slides SET attachment_file_name = '' WHERE job_id = ?", (job["id"],))
    sn_ctl.rename_attachments(job["servicenow"]["sys_id"], lambda n: f"slide_{int(n[:3]):03d}.png" if n[:3].isdigit() else n)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    names = sorted(a["file_name"] for a in data["attachments"])
    assert job["status"] == "published" and len(names) == 60 and names[0] == "slide_001.png"  # reused, not re-uploaded under new names
    # a job without any stored mode (pre-1.1 options) is treated as 'embedded'
    ctx.db.update_job(job["id"], options={})
    assert client.get(f"/api/jobs/{job['id']}?slides=false").json()["image_mode"] == "embedded"
