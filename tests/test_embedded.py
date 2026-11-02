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
    assert len(imgs) == 81
    assert [len(per_slide[n]) for n in range(1, 8)] == [1, 2, 5, 3, 1, 3, 2]  # logo on every slide
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
    assert len(logos) == 60 and all(i.reuse_count == 60 for i in logos)
    shot_a = [i for i in imgs if i.slide_number in (2, 6) and i.width == 900]
    assert len(shot_a) == 2 and shot_a[0].sha256 == shot_a[1].sha256 and shot_a[0].reuse_count == 2
    # untransformed JPEG is stored byte-for-byte in its original format
    jpg = next(i for i in per_slide[7] if i.original_ext == "jpeg")
    assert jpg.file_ext == "jpeg" and jpg.file_ref.endswith(".jpg")
    assert hashlib.sha256((tmp_path / "emb" / Path(jpg.file_ref).name).read_bytes()).hexdigest() == jpg.sha256
    # text-only slide 5 has only the logo; placements are recorded
    assert per_slide[5][0].sha256 == logo_sha and 0 < per_slide[5][0].rel_width < 0.1


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
    job = wait_for(client, upload(client, deck_emb, title="ServiceNow Fundamentals")["id"])
    assert job["status"] == "ready" and job["counts"]["done"] == 60
    full = client.get(f"/api/jobs/{job['id']}").json()
    assert full["image_mode"] == "embedded" and full["images_total"] == 81 and full["images_selected"] == 20
    s2 = full["slides"][1]
    assert s2["title"] == "תהליך התחברות"  # editable PPTX title preferred over the AI title
    assert [im["selected"] for im in s2["images"]] == [True, False]
    assert s2["images"][0]["url"] and client.get(s2["images"][0]["url"]).headers["content-type"] == "image/png"
    assert full["slides"][4]["images"][0]["selected"] is False  # slide 5: logo only -> text-only section
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

    # publish: selected embedded images only, meaningful file names, correct references
    r = client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    assert r.status_code == 202, r.text
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and job["servicenow"]["image_mode"] == "embedded" and job["servicenow"]["attachments"] == 20
    data = sn_ctl.articles()
    art = data["articles"][0]
    atts = {a["file_name"]: a["sys_id"] for a in data["attachments"] if a["table_sys_id"] == art["sys_id"]}
    assert len(atts) == 20 and not any(n.startswith("slide_") for n in atts)
    assert "004_משואה_750_01.png" in atts and "004_משואה_750_02.png" in atts
    assert "003_ארכיטקטורה_-_Client_API_Database_01.png" in atts
    assert "007_Error_handling_-_שגיאת_חיבור_01.jpg" in atts  # JPEG kept as JPEG
    assert "001_ServiceNow_Fundamentals_יסודות_המערכת_01.png" in atts  # manually included logo
    assert "002_תהליך_התחברות_01.png" not in atts  # manually excluded
    sec = _sections(art["text"])
    refs4 = re.findall(r'sys_attachment\.do\?sys_id=([0-9a-f]{32})', sec[4])
    assert [atts["004_משואה_750_01.png"], atts["004_משואה_750_02.png"]] == refs4
    assert "<figure" not in sec[2] and "<figure" not in sec[5]
    assert art["text"].count("<figure") == 20 and art["workflow_state"] == "draft"
    # slide->image->attachment mapping is exposed to the UI
    full = client.get(f"/api/jobs/{job['id']}").json()
    im = full["slides"][3]["images"][0]
    assert im["file_name"] == "004_משואה_750_01.png" and im["attachment_sys_id"] == atts["004_משואה_750_01.png"]
    # attachment bytes are the extracted (cropped) image, not a slide screenshot
    import httpx

    png = httpx.get(sn_ctl.base + f"/sys_attachment.do?sys_id={im['attachment_sys_id']}").content
    with Image.open(io.BytesIO(png)) as got:
        assert got.size == (450, 504)

    # idempotent re-publish: no second article, no duplicate attachments, same names
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    assert len(data["articles"]) == 1 and len(data["attachments"]) == 20


def test_embedded_publish_partial_failure_recovery(client, deck_emb, qwen_ctl, sn_ctl):
    job = wait_for(client, upload(client, deck_emb)["id"])
    sn_ctl.set(fail_attachment_after=7)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "publish_failed" and len(sn_ctl.articles()["attachments"]) == 7
    sn_ctl.set(fail_attachment_after=0, reset_counters=True)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    assert job["status"] == "published" and len(data["articles"]) == 1 and len(data["attachments"]) == 20
    names = [a["file_name"] for a in data["attachments"]]
    assert len(names) == len(set(names))


def test_full_slide_mode_still_available(client, deck_emb, sn_ctl):
    job = wait_for(client, upload(client, deck_emb)["id"])
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB, "image_mode": "full_slide"})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    names = [a["file_name"] for a in sn_ctl.articles()["attachments"]]
    assert job["status"] == "published" and len(names) == 60 and all(n.startswith("slide_") for n in names)


def test_presentation_saved_by_older_version_gets_images_on_publish(client, deck_emb, sn_ctl):
    """Old jobs have no slide_images rows: extraction runs lazily when publishing in embedded mode."""
    job = wait_for(client, upload(client, deck_emb)["id"])
    ctx = client.app.state.ctx
    ctx.db._exec("DELETE FROM slide_images WHERE job_id = ?", (job["id"],))
    assert client.get(f"/api/jobs/{job['id']}?slides=false").json()["images_total"] == 0
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and job["servicenow"]["attachments"] == 20
    # explicit re-extraction endpoint also works
    assert client.post(f"/api/jobs/{job['id']}/images/extract").json()["images"] == 81


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
        assert job["status"] == "published" and "004_750_01.png" in names and "007_Error_handling_01.jpg" in names and "003_Client_API_Database_01.png" in names
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
