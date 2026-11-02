"""
End-to-end POC: 60-slide presentation -> images -> mock Qwen -> review/edit ->
HTML -> mock ServiceNow draft article with attachments; failure, retry,
interruption and idempotency scenarios.
"""
from __future__ import annotations

import hashlib
import json
import re
import time

import httpx
import pytest

from conftest import upload, wait_for

pytestmark = pytest.mark.timeout(900)


def _done_job(client, deck60):
    job = upload(client, deck60, title="VPN gateway training")
    job = wait_for(client, job["id"])
    assert job["status"] == "ready", job
    return job


def test_full_flow_60_slides(client, deck60, qwen_ctl, sn_ctl):
    # 1-4) upload, convert, describe
    t0 = time.time()
    job = _done_job(client, deck60)
    assert job["slide_count"] == 60 and job["counts"]["done"] == 60 and job["counts"]["failed"] == 0
    full = client.get(f"/api/jobs/{job['id']}").json()
    assert [s["number"] for s in full["slides"]] == list(range(1, 61))

    # images exist, are served, and the model received exactly these images
    stats = qwen_ctl.stats()
    assert stats["requests"] == 60 and stats["images_seen"] == 60
    seen = {n: h for n, h, _ in stats["hashes"]}
    for s in full["slides"][:5] + full["slides"][-3:]:
        img = client.get(s["image_url"])
        assert img.status_code == 200 and img.headers["content-type"] == "image/png"
        assert hashlib.sha256(img.content).hexdigest()[:12] == seen[s["number"]], "slide image/description association broken"

    # descriptions carry the right slide number and language, Hebrew preserved
    s1, s2 = full["slides"][0], full["slides"][1]
    assert "Slide 1 of 60" in s1["description"]["summary"]
    assert "Slide 2 of 60" in s2["description"]["summary"]
    assert s2["description"]["language"] == "he+en" and "שלב 2" in s2["description"]["visible_text"]
    assert s1["original_text"].startswith("Step 1") and "Speaker notes for slide 1" == s1["notes_text"]
    assert s1["status"] == "done" and s1["attempts"] == 1

    # this deck has no embedded pictures: use the full-slide attachment mode (1.0 behaviour)
    assert client.patch(f"/api/jobs/{job['id']}", json={"image_mode": "full_slide"}).json()["image_mode"] == "full_slide"

    # 5) review & edit
    r = client.patch(f"/api/jobs/{job['id']}/slides/3", json={"edited_content": "Reviewed text for slide 3 <b>bold</b>", "title": "Slide three"})
    assert r.status_code == 200 and r.json()["edited_content"].startswith("Reviewed")
    r = client.patch(f"/api/jobs/{job['id']}", json={"title": "VPN gateway training (reviewed)"})
    assert r.json()["title"] == "VPN gateway training (reviewed)"

    # 6) exports
    j = client.get(f"/api/jobs/{job['id']}/export.json")
    assert j.status_code == 200
    deck = json.loads(j.content)
    assert deck["deck"] == "vpn_training_60.pptx" and len(deck["slides"]) == 60 and deck["slides"][2]["edited_content"].startswith("Reviewed")
    assert deck["slides"][0]["number"] == 1 and deck["slides"][0]["content"]  # ppt2desc-compatible shape
    h = client.get(f"/api/jobs/{job['id']}/export.html")
    assert h.status_code == 200 and h.text.count("data:image/png;base64,") == 60
    assert "Reviewed text for slide 3 &lt;b&gt;bold&lt;/b&gt;" in h.text
    assert 'dir="rtl"' in h.text
    prev = client.get(f"/api/jobs/{job['id']}/preview.html").text
    assert prev.count("<section") == 60 and "<script" not in prev

    # 7) ServiceNow: KB list and draft creation
    kbs = client.get("/api/servicenow/knowledge-bases").json()["knowledge_bases"]
    assert len(kbs) == 2 and any(k["title"].startswith("מאגר") for k in kbs)
    kb = kbs[0]["sys_id"]
    r = client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": kb, "attach_pptx": True})
    assert r.status_code == 202, r.text
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published", job
    sn = job["servicenow"]
    assert re.match(r"^KB\d{7}$", sn["number"]) and len(sn["sys_id"]) == 32
    assert sn["links"]["form"].endswith(f"kb_knowledge.do?sys_id={sn['sys_id']}")

    # 8) images attached and referenced in order, article in draft
    data = sn_ctl.articles()
    assert len(data["articles"]) == 1
    art = data["articles"][0]
    assert art["workflow_state"] == "draft" and art["short_description"] == "VPN gateway training (reviewed)" and art["kb_knowledge_base"] == kb
    atts = [a for a in data["attachments"] if a["table_sys_id"] == art["sys_id"]]
    images = [a for a in atts if a["file_name"].startswith("slide_")]
    assert len(images) == 60 and any(a["file_name"] == "vpn_training_60.pptx" for a in atts)
    refs = re.findall(r'<img src="/sys_attachment\.do\?sys_id=([0-9a-f]{32})"', art["text"])
    assert len(refs) == 60
    by_id = {a["sys_id"]: a["file_name"] for a in images}
    assert [by_id[r] for r in refs] == [f"slide_{i:03d}.png" for i in range(1, 61)]
    assert f"<!-- ppt2kb:job={job['id']} -->" in art["text"]
    assert "Reviewed text for slide 3" in art["text"] and "<script" not in art["text"]
    # attachment bytes are the real slide images
    first = httpx.get(sn_ctl.base + f"/sys_attachment.do?sys_id={refs[0]}")
    assert first.status_code == 200 and first.content[:8] == b"\x89PNG\r\n\x1a\n"

    # 9) idempotency: publishing again must not create a second article or duplicate attachments
    r = client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": kb})
    assert r.status_code == 202
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and job["servicenow"]["sys_id"] == sn["sys_id"]
    data = sn_ctl.articles()
    assert len(data["articles"]) == 1 and len([a for a in data["attachments"] if a["file_name"].startswith("slide_")]) == 60
    print(f"\n[e2e] 60 slides processed and published in {time.time() - t0:.1f}s")


def test_partial_failure_and_single_slide_retry(client, deck60, qwen_ctl):
    qwen_ctl.set(fail_slides=[3, 7, 58])
    job = upload(client, deck60)
    job = wait_for(client, job["id"])
    assert job["status"] == "partial" and job["counts"]["failed"] == 3 and job["counts"]["done"] == 57
    full = client.get(f"/api/jobs/{job['id']}").json()
    failed = [s for s in full["slides"] if s["status"] == "failed"]
    assert [s["number"] for s in failed] == [3, 7, 58]
    assert all(s["error"] == "HTTP 500" and s["attempts"] == 1 for s in failed)  # HTTP retries happen inside one attempt
    assert qwen_ctl.stats()["requests"] == 60 + 3 * 2  # 2 transport-level retries per failed slide
    # publishing must be refused while slides are missing
    assert client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90"}).status_code == 409

    # retry only slide 3 while 7 and 58 still fail
    qwen_ctl.set(fail_slides=[7, 58], reset_stats=True)
    assert client.post(f"/api/jobs/{job['id']}/retry", json={"slides": [3]}).status_code == 200
    job = wait_for(client, job["id"])
    assert job["counts"]["failed"] == 2 and job["counts"]["done"] == 58 and job["status"] == "partial"
    assert qwen_ctl.stats()["requests"] == 1  # only slide 3 was re-sent
    assert client.get(f"/api/jobs/{job['id']}").json()["slides"][2]["attempts"] == 2

    # retry all remaining failed slides
    qwen_ctl.set(fail_slides=[], reset_stats=True)
    assert client.post(f"/api/jobs/{job['id']}/retry", json={"slides": []}).status_code == 200
    job = wait_for(client, job["id"])
    assert job["status"] == "ready" and job["counts"]["done"] == 60
    assert qwen_ctl.stats()["requests"] == 2


def test_transient_errors_are_retried(client, deck60, qwen_ctl):
    qwen_ctl.set(flaky_every=4)  # every 4th request fails once
    job = wait_for(client, upload(client, deck60)["id"])
    assert job["status"] == "ready" and job["counts"]["done"] == 60
    st = qwen_ctl.stats()
    assert st["failures"] > 0 and st["requests"] > 60


def test_plain_text_answer_and_json_mode_fallback(client, deck60, qwen_ctl):
    """Non-JSON answers are kept for the reviewer but never accepted silently: the slide needs review."""
    qwen_ctl.set(plain_text=True, reject_json_mode=True)
    job = wait_for(client, upload(client, deck60)["id"])
    assert job["status"] == "partial" and job["counts"]["needs_review"] == 60 and job["counts"]["done"] == 0
    s = client.get(f"/api/jobs/{job['id']}").json()["slides"][0]
    assert "(mock) Slide 1 of 60" in s["content"] and "not_json" in s["quality"]
    # publishing is refused until the slides are accepted
    assert client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90"}).status_code == 409
    # the reviewer edits and accepts a slide -> done
    client.patch(f"/api/jobs/{job['id']}/slides/1", json={"edited_content": "Reviewed explanation."})
    assert client.post(f"/api/jobs/{job['id']}/slides/1/accept").status_code == 200
    j = client.get(f"/api/jobs/{job['id']}?slides=false").json()
    assert j["counts"]["done"] == 1 and j["counts"]["needs_review"] == 59


def test_wrong_api_key_marks_slides_failed(client, deck60, qwen_ctl):
    client.put("/api/config", json={"values": {"qwen_api_key": "wrong-key"}})
    job = wait_for(client, upload(client, deck60)["id"])
    assert job["status"] == "partial" and job["counts"]["failed"] == 60
    s = client.get(f"/api/jobs/{job['id']}").json()["slides"][0]
    assert "HTTP 401" in s["error"] and "wrong-key" not in s["error"]


def test_interrupted_processing_is_resumed(app_settings, deck60, qwen_ctl):
    """Simulate a process crash mid-way and verify resume only processes the remaining slides."""
    from fastapi.testclient import TestClient
    from ppt2kb.app import create_app
    from ppt2kb.schemas.deck import JobStatus, SlideStatus

    qwen_ctl.set(delay_ms=150)
    app = create_app(app_settings)
    with TestClient(app) as c:
        job = upload(c, deck60)
        # wait until conversion finished and some slides are described, then "crash"
        deadline = time.time() + 240
        while time.time() < deadline:
            j = c.get(f"/api/jobs/{job['id']}?slides=false").json()
            if j["status"] == "describing" and j["counts"]["done"] >= 5:
                break
            time.sleep(0.2)
        assert j["status"] == "describing", j
        ctx = app.state.ctx
        ctx.runner.cancel(job["id"])  # stop the worker (as a kill would)
        for _ in range(100):
            if not ctx.runner.is_active(job["id"]):
                break
            time.sleep(0.1)
        # emulate the state a hard crash leaves behind
        ctx.db.update_job(job["id"], status=JobStatus.describing)
        slides = ctx.db.get_slides(job["id"])
        done_before = sum(1 for s in slides if s.status == SlideStatus.done)
        ctx.db.update_slide(job["id"], slides[-1].number, status=SlideStatus.processing)
        assert 5 <= done_before < 60
        ctx.db.close()

    # new process on the same data directory
    qwen_ctl.set(delay_ms=0, reset_stats=True)
    app2 = create_app(app_settings)
    with TestClient(app2) as c:
        j = c.get(f"/api/jobs/{job['id']}?slides=false").json()
        assert j["status"] == "interrupted"
        assert c.post(f"/api/jobs/{job['id']}/resume").status_code == 200
        j = wait_for(c, job["id"])
        assert j["status"] == "ready" and j["counts"]["done"] == 60
    assert qwen_ctl.stats()["requests"] == 60 - done_before


def test_publish_partial_failure_recovery(client, deck60, qwen_ctl, sn_ctl):
    job = _done_job(client, deck60)
    kb = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    client.patch(f"/api/jobs/{job['id']}", json={"image_mode": "full_slide"})
    sn_ctl.set(fail_attachment_after=20)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": kb})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "publish_failed" and "HTTP 500" in job["servicenow"]["error"]
    sys_id = job["servicenow"]["sys_id"]
    data = sn_ctl.articles()
    assert len(data["articles"]) == 1 and len(data["attachments"]) == 20
    # recover: same article, remaining 40 uploaded, no duplicates
    sn_ctl.set(fail_attachment_after=0, reset_counters=True)
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": kb})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published" and job["servicenow"]["sys_id"] == sys_id
    data = sn_ctl.articles()
    assert len(data["articles"]) == 1 and len(data["attachments"]) == 60
    assert len(re.findall(r"sys_attachment\.do\?sys_id=", data["articles"][0]["text"])) == 60


def test_duplicate_detection_after_local_state_loss(client, deck60, sn_ctl):
    """If the local record of a created article is lost, the remote marker search prevents a duplicate."""
    job = _done_job(client, deck60)
    kb = "a1b2c3d4e5f60718293a4b5c6d7e8f90"
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": kb})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "published"
    ctx = client.app.state.ctx
    ctx.db.update_job(job["id"], servicenow={}, status="ready")
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": kb})
    job2 = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job2["servicenow"]["sys_id"] == job["servicenow"]["sys_id"]
    assert len(sn_ctl.articles()["articles"]) == 1


def test_servicenow_auth_failure_reported(client, deck60, sn_ctl):
    job = _done_job(client, deck60)
    client.put("/api/config", json={"values": {"servicenow_password": "wrong"}})
    r = client.post("/api/config/test/servicenow").json()
    assert r["ok"] is False and "401" in r["detail"]
    client.post(f"/api/jobs/{job['id']}/publish", json={"kb_sys_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90"})
    job = wait_for(client, job["id"], statuses=("published", "publish_failed"))
    assert job["status"] == "publish_failed" and "401" in job["servicenow"]["error"]
    assert sn_ctl.articles()["articles"] == []


def test_connection_tests(client):
    assert client.post("/api/config/test/qwen").json()["ok"] is True
    assert client.post("/api/config/test/servicenow").json()["ok"] is True


def test_upload_rejections_via_api(client, tmp_path):
    bad = tmp_path / "bad.pptx"
    bad.write_bytes(b"not a presentation")
    with bad.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("bad.pptx", f, "application/octet-stream")})
    assert r.status_code == 400
    with bad.open("rb") as f:
        r = client.post("/api/jobs", files={"file": ("bad.exe", f, "application/octet-stream")})
    assert r.status_code == 400
    assert not list(client.app_settings.upload_dir.glob("*"))  # rejected files are removed


def test_delete_job_removes_files(client, deck60):
    job = _done_job(client, deck60)
    jd = client.app_settings.jobs_dir / job["id"]
    assert (jd / "images").is_dir()
    assert client.delete(f"/api/jobs/{job['id']}").status_code == 200
    assert not jd.exists() and client.get(f"/api/jobs/{job['id']}").status_code == 404
    assert not list(client.app_settings.upload_dir.glob("*"))


def test_ui_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "ppt2kb" in r.text and 'dir="ltr"' in r.text
    assert client.get("/static/app.js").status_code == 200
    assert "he:" in client.get("/static/i18n.js").text


def test_cli(deck60, tmp_path, app_settings, qwen_ctl, monkeypatch):
    from ppt2kb import cli
    from ppt2kb import config as cfgmod

    monkeypatch.setattr(cfgmod, "_settings", app_settings)
    rc = cli.main(["--input", str(deck60), "--output_dir", str(tmp_path / "out"), "--save-images", "--html"])
    assert rc == 0
    data = json.loads((tmp_path / "out" / "vpn_training_60.json").read_text(encoding="utf-8"))
    assert len(data["slides"]) == 60 and data["status"] == "ready"
    assert len(list((tmp_path / "out" / "vpn_training_60").glob("slide_*.png"))) == 60
    assert (tmp_path / "out" / "vpn_training_60.html").is_file()
