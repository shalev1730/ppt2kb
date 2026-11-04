"""
"Exclude slide backgrounds" (1.1.2): structural and heuristic background detection, the
per-presentation option across the three image output modes, retries, explicit republish
and backward compatibility - on a deck built for the background cases (tests/deckgen.py).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import upload, wait_for
from deckgen import build_background_deck

pytestmark = pytest.mark.timeout(600)
KB = "a1b2c3d4e5f60718293a4b5c6d7e8f90"


@pytest.fixture(scope="session")
def deck_bg(tmp_path_factory) -> Path:
    return build_background_deck(tmp_path_factory.mktemp("decks") / "backgrounds.pptx")


def _sections(html: str) -> dict:
    return {int(m.group(1)): m.group(2) for m in re.finditer(r'<section class="ppt2kb-slide" data-slide="(\d+)"[^>]*>(.*?)</section>', html, re.DOTALL)}


def _by_slide(job_json):
    return {s["number"]: s["images"] for s in job_json["slides"]}


# ------------------------------------------------------------- detection
def test_background_detection_is_structural_first_and_conservative(deck_bg, tmp_path):
    from ppt2kb.extract import classify_images, extract_slide_images

    imgs = extract_slide_images(deck_bg, tmp_path / "images" / "emb")
    cls = classify_images(imgs, tmp_path, 8)
    by = {(i.slide_number, i.index): (i, c) for i, c in zip(imgs, cls)}
    # 1) true picture background + one content screenshot
    bg, cbg = by[(1, 1)]
    assert bg.source_kind == "background" and bg.is_background_candidate and cbg["is_background"] and bg.background_reason.startswith("slide_background")
    shot = [i for (n, _), (i, c) in by.items() if n == 1 and i.source_kind == "picture"]
    assert len(shot) == 1 and not shot[0].background_reason and by[(1, shot[0].index)][1]["is_background"] is False
    # 2) master/layout graphics: the master logo appears on every slide, the layout background on slide 7
    master_logo = [i for i, c in zip(imgs, cls) if i.source_kind == "layout_picture"]
    assert len(master_logo) == 8 and all(i.is_master_background and c["is_background"] for i, c in zip(imgs, cls) if i.source_kind == "layout_picture")
    lbg = [i for i in imgs if i.source_kind == "master_background"]
    assert len(lbg) == 1 and lbg[0].slide_number == 7 and lbg[0].is_master_background and "layout" in lbg[0].background_reason
    # 3) full-bleed theme picture behind title/text, repeated on slides 2-5
    theme = [i for i in imgs if i.slide_number in (2, 3, 4, 5) and i.source_kind == "picture" and i.rel_width > 0.9]
    assert len(theme) == 4 and all(i.is_background_candidate and i.z_index == 0 and i.shapes_above >= 2 and i.reuse_count == 4 for i in theme)
    assert all(i.background_reason.startswith("full_bleed") for i in theme)
    # content on top of the theme picture is kept: the JPEG photo (slide 3) and the diagram group (slide 5)
    photo = [i for i in imgs if i.slide_number == 3 and i.original_ext == "jpeg"]
    assert len(photo) == 1 and not photo[0].background_reason and by[(3, photo[0].index)][1]["is_background"] is False
    group = [i for i in imgs if i.slide_number == 5 and i.in_group]
    assert len(group) == 3 and all(not i.background_reason for i in group)
    # 4) a large screenshot that IS the content (nothing drawn over it) is never a background
    big = [i for i in imgs if i.slide_number == 6 and i.source_kind == "picture"]
    assert len(big) == 1 and big[0].rel_width * big[0].rel_height > 0.8 and big[0].shapes_above == 0
    assert not big[0].background_reason and by[(6, big[0].index)][1]["is_background"] is False and by[(6, big[0].index)][1]["selected"]
    # the icon on the layout-background slide is content
    icon = [i for i in imgs if i.slide_number == 7 and i.source_kind == "picture"]
    assert len(icon) == 1 and not icon[0].background_reason
    # flags are visible in debug output
    d = theme[0].to_dict()
    assert d["is_background_candidate"] is True and "background_reason" in d and "z_index" in d


# ------------------------------------------------------------- modes
def test_embedded_only_mode_excludes_backgrounds(client, deck_bg, qwen_ctl, sn_ctl):
    job = wait_for(client, upload(client, deck_bg, title="Backgrounds", image_mode="embedded")["id"])
    assert job["status"] == "ready" and job["exclude_backgrounds"] is True
    assert qwen_ctl.stats()["images_seen"] == 8  # the full slide still goes to Qwen for every slide
    full = client.get(f"/api/jobs/{job['id']}").json()
    assert full["images_background"] == 14 and full["images_total"] == 7 and full["images_selected"] == 7  # 21 rows: 14 backgrounds, 7 content images
    by = _by_slide(full)
    assert [im["excluded"] for im in by[1]] == [True, True, False]  # bg fill, master logo, screenshot
    assert all(im["excluded"] for im in by[4]) and all(im["excluded"] for im in by[8])  # theme only / master logo only
    assert sum(1 for im in by[3] if not im["excluded"]) == 1 and sum(1 for im in by[5] if not im["excluded"]) == 3
    # body: only content images, slides without content images get title + explanation only
    prev = _sections(client.get(f"/api/jobs/{job['id']}/preview.html").text)
    assert prev[1].count("<figure") == 1 and prev[2].count("<figure") == 0 and prev[3].count("<figure") == 1
    assert prev[5].count("<figure") == 3 and prev[6].count("<figure") == 1 and prev[7].count("<figure") == 1 and prev[8].count("<figure") == 0
    assert len(prev) == 8 and list(prev) == list(range(1, 9))
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    names = sorted(a["file_name"] for a in data["attachments"])
    assert job["status"] == "published" and job["servicenow"]["exclude_backgrounds"] is True and len(names) == 7 and all("_image_" in n for n in names)
    assert names[0].startswith("001_Login_flow") and not any(n.startswith(("002_", "004_", "008_")) for n in names)
    sec = _sections(data["articles"][0]["text"])
    assert sec[1].count("<figure") == 1 and sec[2].count("<figure") == 0 and sec[5].count("<figure") == 3
    refs = re.findall(r'sys_attachment\.do\?sys_id=([0-9a-f]{32})', data["articles"][0]["text"])
    assert len(refs) == 7 and set(refs) == {a["sys_id"] for a in data["attachments"]}
    # excluded rows were never uploaded
    full = client.get(f"/api/jobs/{job['id']}").json()
    assert all(im["attachment_sys_id"] == "" for s in full["slides"] for im in s["images"] if im["excluded"])


def test_embedded_full_mode_keeps_full_slides_and_excludes_backgrounds(client, deck_bg, sn_ctl):
    job = wait_for(client, upload(client, deck_bg, title="Backgrounds mode 2")["id"])  # default mode, default exclusion
    assert job["image_mode"] == "embedded_full" and job["exclude_backgrounds"] is True
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    names = sorted(a["file_name"] for a in data["attachments"])
    slides_att = [n for n in names if "_image_" not in n]
    images_att = [n for n in names if "_image_" in n]
    assert job["status"] == "published" and len(slides_att) == 8 and len(images_att) == 7 and job["servicenow"]["attachments"] == 15
    sec = _sections(data["articles"][0]["text"])
    assert len(sec) == 8 and all(sec[n].count("<figure") == 1 for n in sec)  # every slide: its own full render, nothing else
    # the full-slide render of a background-only slide is still attached and shown
    assert any(n.startswith("002_Theme_1") and "_image_" not in n for n in names)


def test_full_slide_mode_is_unchanged_by_the_option(client, deck_bg, sn_ctl):
    for flag in ("true", "false"):
        sn_ctl.set(clear=True)
        job = wait_for(client, upload(client, deck_bg, image_mode="full_slide", exclude_backgrounds=flag)["id"])
        client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
        job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
        data = sn_ctl.articles()
        names = [a["file_name"] for a in data["attachments"]]
        assert job["status"] == "published" and len(names) == 8 and not any("_image_" in n for n in names), flag
        sec = _sections(data["articles"][0]["text"])
        assert all(sec[n].count("<figure") == 1 for n in sec)


def test_include_backgrounds_keeps_everything(client, deck_bg, sn_ctl):
    job = wait_for(client, upload(client, deck_bg, image_mode="embedded", exclude_backgrounds="false")["id"])
    full = client.get(f"/api/jobs/{job['id']}").json()
    assert full["exclude_backgrounds"] is False and full["images_total"] == 21 and full["images_background"] == 14
    assert not any(im["excluded"] for s in full["slides"] for im in s["images"])
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    names = [a["file_name"] for a in sn_ctl.articles()["attachments"]]
    # 21 rows, identical assets once: theme picture x4 -> 1, master logo x8 -> 1  => 21 - 3 - 7 = 11
    assert job["status"] == "published" and len(names) == 11 and len(set(names)) == 11


# ------------------------------------------------------------- persistence / retry / republish
def test_option_persists_and_retry_keeps_it_and_change_requires_republish(client, deck_bg, sn_ctl):
    job = wait_for(client, upload(client, deck_bg, image_mode="embedded")["id"])
    assert job["exclude_backgrounds"] is True
    # a retry after a failed upload keeps the option the article was created with
    sn_ctl.set(fail_attachment_after=3)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "publish_failed" and len(sn_ctl.articles()["attachments"]) == 3
    sn_ctl.set(fail_attachment_after=0, reset_counters=True)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    names = [a["file_name"] for a in sn_ctl.articles()["attachments"]]
    assert job["status"] == "published" and len(names) == 7 and len(set(names)) == 7 and job["exclude_backgrounds"] is True
    # changing the option after publishing does nothing by itself and flags the article for an explicit republish
    r = client.patch(f"/api/jobs/{job['id']}", json={"exclude_backgrounds": False}).json()
    assert r["exclude_backgrounds"] is False and r["servicenow"]["mode_changed"] is True
    assert len(sn_ctl.articles()["attachments"]) == 7
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    data = sn_ctl.articles()
    assert job["status"] == "published" and not job["servicenow"].get("mode_changed") and job["servicenow"]["exclude_backgrounds"] is False
    assert len(data["articles"]) == 1 and len(data["attachments"]) == 11  # the 4 background assets were added, nothing duplicated
    assert _sections(data["articles"][0]["text"])[2].count("<figure") == 0  # backgrounds are still not auto-selected for the body
    # the server-side default is configurable and persistent
    assert client.put("/api/config", json={"values": {"exclude_backgrounds": False}}).json()["config"]["exclude_backgrounds"] is False
    j2 = wait_for(client, upload(client, deck_bg, image_mode="embedded")["id"])
    assert j2["exclude_backgrounds"] is False
    client.put("/api/config", json={"values": {"exclude_backgrounds": True}})


def test_backward_compatibility_old_presentations_keep_their_images(client, deck_bg, sn_ctl):
    """Presentations stored by 1.1.1 have no exclude_backgrounds option and no flags: nothing changes for them."""
    from ppt2kb.schemas.deck import excludes_backgrounds

    assert excludes_backgrounds(None) is False and excludes_backgrounds({}) is False and excludes_backgrounds({"image_mode": "embedded"}) is False
    job = wait_for(client, upload(client, deck_bg, image_mode="embedded")["id"])
    ctx = client.app.state.ctx
    j = ctx.db.get_job(job["id"])
    ctx.db.update_job(job["id"], options={"image_mode": "embedded"})  # as written by 1.1.1
    ctx.db._exec("UPDATE slide_images SET is_background = 0, background_reason = '' WHERE job_id = ?", (job["id"],))  # migrated rows
    v = client.get(f"/api/jobs/{job['id']}").json()
    assert v["exclude_backgrounds"] is False and v["images_background"] == 0 and v["images_total"] == 21
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": KB})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and len(sn_ctl.articles()["attachments"]) == 11  # 1.1.1 behaviour: all originals
    # re-extraction classifies the old rows and the user can then opt in
    assert client.post(f"/api/jobs/{job['id']}/images/extract").json()["images"] == 21
    assert client.get(f"/api/jobs/{job['id']}?slides=false").json()["images_background"] == 14
    assert j["options"]["image_mode"] == "embedded"
