"""
Logging configuration with secret redaction.

Every log record passes through :class:`RedactingFilter`, which masks
anything that looks like a credential (Authorization headers, api keys,
passwords, bearer tokens, base64 image payloads). Slide *content* is never
logged by the application code itself; the filter is a second safety net.
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Iterable

_PATTERNS = [
    # key=value / "key": "value" style secrets
    re.compile(
        r"(?i)((?:api[_-]?key|password|passwd|secret|token|authorization|client_secret)"
        r"[\"']?\s*[=:]\s*[\"']?)((?:(?:bearer|basic)\s+)?[^\s\"',}]{4,})"
    ),
    # Bearer / Basic tokens
    re.compile(r"(?i)\b(bearer\s+|basic\s+)([A-Za-z0-9\-._~+/=]{8,})"),
    # base64 data URIs (slide images) - never useful in a log
    re.compile(r"(data:image/[a-z]+;base64,)[A-Za-z0-9+/=]{16,}"),
]

_registered_secrets: set[str] = set()


def register_secret(value: str | None) -> None:
    """Register a literal secret value so that it is masked wherever it appears."""
    if value and len(value) >= 4:
        _registered_secrets.add(value)


def redact(text: str) -> str:
    if not text:
        return text
    for s in list(_registered_secrets):
        if s in text:
            text = text.replace(s, "***")
    for pat in _PATTERNS:
        text = pat.sub(lambda m: m.group(1) + "***", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            msg = str(record.msg)
        record.msg = redact(msg)
        record.args = ()
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", json_logs: bool = False, quiet: Iterable[str] = (), log_file=None) -> None:
    root = logging.getLogger()
    root.handlers.clear()
    formatter = JsonFormatter() if json_logs else logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        from logging.handlers import RotatingFileHandler
        from pathlib import Path

        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(RotatingFileHandler(str(log_file), maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"))
    for handler in handlers:
        handler.setFormatter(formatter)
        handler.addFilter(RedactingFilter())
        root.addHandler(handler)
    root.setLevel(level.upper())
    # third party libraries that may log request details
    for name in ("httpx", "httpcore", "uvicorn.access", *quiet):
        logging.getLogger(name).setLevel(logging.WARNING)
