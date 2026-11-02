from __future__ import annotations

import os
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

os.environ.setdefault("PPT2KB_LOG_LEVEL", "WARNING")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Server:
    def __init__(self, app, port: int):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"
        cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False)
        self.server = uvicorn.Server(cfg)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self):
        self.thread.start()
        for _ in range(100):
            try:
                httpx.get(self.base + "/", timeout=0.5)
                return self
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("mock server did not start")

    def stop(self):
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture(scope="session")
def mock_qwen():
    from mocks import mock_qwen as mq

    srv = _Server(mq.app, _free_port()).start()
    yield srv
    srv.stop()


@pytest.fixture(scope="session")
def mock_sn():
    from mocks import mock_servicenow as ms

    srv = _Server(ms.app, _free_port()).start()
    yield srv
    srv.stop()


@pytest.fixture
def qwen_ctl(mock_qwen):
    """Reset mock Qwen state before each test and return a control helper."""

    def set_(**kw):
        return httpx.post(mock_qwen.base + "/_mock/config", json=kw, timeout=5).json()

    def stats():
        return httpx.get(mock_qwen.base + "/_mock/stats", timeout=5).json()

    set_(fail_slides=[], flaky_every=0, delay_ms=0, api_key="test-key", plain_text=False, reject_json_mode=False, degenerate_first=False, visual_first=False, visual_always=False, reset_stats=True)
    yield type("Ctl", (), {"set": staticmethod(set_), "stats": staticmethod(stats), "base": mock_qwen.base})
    set_(fail_slides=[], flaky_every=0, delay_ms=0, api_key="test-key", plain_text=False, reject_json_mode=False, degenerate_first=False, visual_first=False, visual_always=False)


@pytest.fixture
def sn_ctl(mock_sn):
    def set_(**kw):
        return httpx.post(mock_sn.base + "/_mock/config", json=kw, timeout=5).json()

    def articles():
        return httpx.get(mock_sn.base + "/_mock/articles", timeout=5).json()

    set_(clear=True, fail_attachment_after=0, delay_ms=0)
    yield type("Ctl", (), {"set": staticmethod(set_), "articles": staticmethod(articles), "base": mock_sn.base})
    set_(fail_attachment_after=0, delay_ms=0)


@pytest.fixture(scope="session")
def deck60(tmp_path_factory) -> Path:
    """A 60-slide presentation with Hebrew + English text, tables and shapes."""
    from pptx import Presentation
    from pptx.util import Inches, Pt
    from pptx.enum.shapes import MSO_SHAPE

    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    for i in range(1, 61):
        layout = prs.slide_layouts[1] if i % 5 else prs.slide_layouts[5]
        slide = prs.slides.add_slide(layout)
        if i % 2:
            slide.shapes.title.text = f"Slide {i}: Configuring the VPN gateway"
        else:
            slide.shapes.title.text = f"שקף {i}: הגדרת שער VPN"
        if i % 5:
            body = slide.placeholders[1].text_frame
            body.text = f"Step 1: open the admin console (slide {i})"
            p = body.add_paragraph()
            p.text = "שלב 2: הזן את כתובת ה-IP של השרת"
            p = body.add_paragraph()
            p.text = "Step 3: click Apply and verify the status LED"
        else:
            rows, cols = 3, 3
            tbl = slide.shapes.add_table(rows, cols, Inches(1), Inches(2), Inches(8), Inches(2)).table
            for r in range(rows):
                for c in range(cols):
                    tbl.cell(r, c).text = f"R{r}C{c}" if r else ["Parameter", "Value", "ערך"][c]
            box = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(9.5), Inches(2), Inches(3), Inches(1.2))
            box.text_frame.text = "Router\n→ Firewall"
        notes = slide.notes_slide.notes_text_frame
        notes.text = f"Speaker notes for slide {i}"
    out = tmp_path_factory.mktemp("decks") / "vpn_training_60.pptx"
    prs.save(out)
    return out


@pytest.fixture
def app_settings(tmp_path, mock_qwen, mock_sn):
    from ppt2kb.config import Settings

    return Settings(
        data_dir=tmp_path / "data",
        qwen_base_url=mock_qwen.base + "/v1",
        qwen_model="mock-qwen2.5-vl",
        qwen_api_key="test-key",
        qwen_concurrency=6,
        qwen_rate_limit_per_min=0,
        qwen_timeout_s=30,
        qwen_max_retries=2,
        servicenow_url=mock_sn.base,
        servicenow_username="admin",
        servicenow_password="admin",
        servicenow_timeout_s=30,
        servicenow_max_retries=1,
        retention_days=0,
        log_level="WARNING",
    )


@pytest.fixture
def client(app_settings):
    from fastapi.testclient import TestClient
    from ppt2kb.app import create_app

    app = create_app(app_settings)
    with TestClient(app) as c:
        c.app_settings = app_settings
        yield c


def wait_for(client, job_id: str, statuses=("ready", "partial", "failed", "interrupted", "published", "publish_failed"), timeout: float = 240.0) -> dict:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = client.get(f"/api/jobs/{job_id}?slides=false").json()
        if last["status"] in statuses and not last["active"]:
            return last
        time.sleep(0.5)
    raise AssertionError(f"timeout waiting for job; last status {last and last['status']}")


def upload(client, path: Path, **form) -> dict:
    with path.open("rb") as f:
        r = client.post("/api/jobs", files={"file": (path.name, f, "application/octet-stream")}, data=form)
    assert r.status_code == 201, r.text
    return r.json()
