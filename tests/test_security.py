"""Security controls: upload validation, outbound allow-list, log redaction, auth."""
from __future__ import annotations

import io
import logging
import zipfile
from pathlib import Path

import httpx
import pytest

from ppt2kb.logging_utils import RedactingFilter, redact, register_secret
from ppt2kb.security.outbound import OutboundBlocked, make_client
from ppt2kb.security.upload_validation import UploadValidationError, validate_presentation, sanitize_display_name

KW = dict(max_bytes=50 * 1024 * 1024, max_zip_entries=1000, max_zip_uncompressed=100 * 1024 * 1024, max_zip_ratio=100)


def _write_zip(path: Path, members: dict[str, bytes], content_types: bytes | None = None):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        if content_types is not None:
            z.writestr("[Content_Types].xml", content_types)
        for name, data in members.items():
            z.writestr(name, data)


PPTX_CT = b'<?xml version="1.0"?><Types><Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/></Types>'


def test_valid_pptx_accepted(deck60):
    res = validate_presentation(deck60, "vpn_training_60.pptx", **KW)
    assert res.kind == "pptx" and not res.macro_enabled and res.size_bytes > 0


def test_rejects_wrong_extension(tmp_path, deck60):
    with pytest.raises(UploadValidationError, match="Only PowerPoint"):
        validate_presentation(deck60, "deck.docx", **KW)


def test_rejects_non_zip_content(tmp_path):
    p = tmp_path / "x.pptx"
    p.write_bytes(b"MZ\x90\x00 this is not a presentation" * 10)
    with pytest.raises(UploadValidationError, match="not a recognised"):
        validate_presentation(p, "x.pptx", **KW)


def test_rejects_docx_disguised_as_pptx(tmp_path):
    p = tmp_path / "x.pptx"
    _write_zip(p, {"word/document.xml": b"<w/>"}, b'<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    with pytest.raises(UploadValidationError, match="not a PowerPoint"):
        validate_presentation(p, "x.pptx", **KW)


def test_rejects_path_traversal_member(tmp_path):
    p = tmp_path / "x.pptx"
    _write_zip(p, {"../../etc/passwd": b"root:x", "ppt/presentation.xml": b"<p/>"}, PPTX_CT)
    with pytest.raises(UploadValidationError, match="unsafe member"):
        validate_presentation(p, "x.pptx", **KW)


def test_rejects_absolute_member(tmp_path):
    p = tmp_path / "x.pptx"
    _write_zip(p, {"/etc/passwd": b"root:x"}, PPTX_CT)
    with pytest.raises(UploadValidationError, match="unsafe member"):
        validate_presentation(p, "x.pptx", **KW)


def test_rejects_zip_bomb_ratio(tmp_path):
    p = tmp_path / "x.pptx"
    _write_zip(p, {"ppt/media/bomb.bin": b"\0" * (30 * 1024 * 1024), "ppt/presentation.xml": b"<p/>"}, PPTX_CT)
    with pytest.raises(UploadValidationError, match="ZIP bomb"):
        validate_presentation(p, "x.pptx", **KW)


def test_rejects_zip_bomb_total_size(tmp_path):
    p = tmp_path / "x.pptx"
    _write_zip(p, {"ppt/presentation.xml": b"<p/>", "big.bin": b"\0" * (5 * 1024 * 1024)}, PPTX_CT)
    with pytest.raises(UploadValidationError, match="too much data"):
        validate_presentation(p, "x.pptx", **{**KW, "max_zip_uncompressed": 1024 * 1024, "max_zip_ratio": 100000})


def test_rejects_too_many_entries(tmp_path):
    p = tmp_path / "x.pptx"
    _write_zip(p, {f"ppt/m/{i}.xml": b"<a/>" for i in range(50)}, PPTX_CT)
    with pytest.raises(UploadValidationError, match="too many entries"):
        validate_presentation(p, "x.pptx", **{**KW, "max_zip_entries": 10})


def test_detects_macro_enabled(tmp_path):
    p = tmp_path / "x.pptx"
    _write_zip(p, {"ppt/vbaProject.bin": b"\0" * 10, "ppt/presentation.xml": b"<p/>"}, PPTX_CT)
    res = validate_presentation(p, "x.pptx", **KW)
    assert res.macro_enabled


def test_rejects_oversize(tmp_path, deck60):
    with pytest.raises(UploadValidationError, match="maximum allowed size"):
        validate_presentation(deck60, "a.pptx", **{**KW, "max_bytes": 1000})


def test_rejects_empty(tmp_path):
    p = tmp_path / "x.pptx"
    p.write_bytes(b"")
    with pytest.raises(UploadValidationError, match="empty"):
        validate_presentation(p, "x.pptx", **KW)


def test_display_name_sanitized():
    assert "/" not in sanitize_display_name("../../x/..\\..\\evil<script>.pptx")
    assert sanitize_display_name("מצגת 2024.pptx") == "מצגת 2024.pptx"


# ------------------------------------------------------------ outbound policy
def test_outbound_allowlist_blocks_unknown_hosts():
    c = make_client(allowed_hosts=["qwen.internal:443"], timeout_s=2)
    with pytest.raises(OutboundBlocked):
        c.get("https://api.openai.com/v1/models")
    with pytest.raises(OutboundBlocked):
        c.get("https://example.com/")
    c.close()


def test_outbound_allowlist_allows_configured_host(mock_qwen):
    c = make_client(allowed_hosts=[f"127.0.0.1:{mock_qwen.port}"], timeout_s=5)
    r = c.get(mock_qwen.base + "/_mock/stats")
    assert r.status_code == 200
    c.close()


def test_outbound_ignores_proxy_env(monkeypatch, mock_qwen):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    c = make_client(allowed_hosts=[f"127.0.0.1:{mock_qwen.port}"], timeout_s=5)
    assert c.get(mock_qwen.base + "/_mock/stats").status_code == 200
    c.close()


def test_outbound_no_redirect_follow(mock_qwen):
    c = make_client(allowed_hosts=[f"127.0.0.1:{mock_qwen.port}"], timeout_s=5)
    assert c.follow_redirects is False
    c.close()


# ---------------------------------------------------------------- redaction
def test_log_redaction_masks_secrets():
    register_secret("sk-very-secret-value-123")
    assert "sk-very-secret-value-123" not in redact("key sk-very-secret-value-123 leaked")
    assert "abcdefghijklmnop" not in redact("Authorization: Bearer abcdefghijklmnop")
    assert redact("sent Bearer abcdefghijklmnop to server") == "sent Bearer *** to server"
    assert redact('{"api_key": "abcd1234efgh"}').endswith('***"}') or "***" in redact('{"api_key": "abcd1234efgh"}')
    assert "password=***" in redact("password=hunter2222")
    out = redact("data:image/png;base64," + "A" * 100)
    assert out == "data:image/png;base64,***"


def test_logging_filter_applies(caplog):
    logger = logging.getLogger("ppt2kb.test")
    handler = logging.StreamHandler(io.StringIO())
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    logger.propagate = True
    with caplog.at_level(logging.INFO):
        logger.info("token=%s", "abcdefgh12345")
    logger.removeHandler(handler)
    assert "abcdefgh12345" not in handler.stream.getvalue()


# --------------------------------------------------------------- web auth
def test_basic_auth_required_when_configured(app_settings):
    from fastapi.testclient import TestClient
    from ppt2kb.app import create_app

    app_settings = app_settings.model_copy(update={"ui_username": "kbuser", "ui_password": __import__("pydantic").SecretStr("s3cret")})
    app = create_app(app_settings)
    with TestClient(app) as c:
        assert c.get("/api/jobs").status_code == 401
        assert c.get("/api/health").status_code == 200  # health is exempt for probes
        assert c.get("/api/jobs", auth=("kbuser", "s3cret")).status_code == 200
        assert c.get("/api/jobs", auth=("kbuser", "wrong")).status_code == 401


def test_security_headers(client):
    r = client.get("/")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]
    assert r.headers.get("server") is None


def test_image_path_traversal_blocked(client):
    r = client.get("/api/jobs/../../etc/passwd")
    assert r.status_code in (404, 422)
    assert client.get("/api/jobs/zzzz/slides/1/image").status_code == 404


def test_config_rejects_non_allowlisted_hosts(app_settings):
    from fastapi.testclient import TestClient
    from ppt2kb.app import create_app

    s = app_settings.model_copy(update={"allowed_outbound_hosts": "qwen.internal,servicenow.internal"})
    with TestClient(create_app(s)) as c:
        r = c.put("/api/config", json={"values": {"qwen_base_url": "https://evil.example.com/v1"}}).json()
        assert "qwen_base_url" in r["rejected"]
        r = c.put("/api/config", json={"values": {"qwen_base_url": "https://qwen.internal/v1"}}).json()
        assert r["rejected"] == []


def test_secrets_never_returned(client):
    client.put("/api/config", json={"values": {"qwen_api_key": "ui-entered-secret"}})
    body = client.get("/api/config").text
    assert "ui-entered-secret" not in body
    assert client.get("/api/config").json()["secrets"]["qwen_api_key"]["set"] is True
