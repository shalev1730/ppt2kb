"""
Qwen Vision client (OpenAI-compatible Chat Completions API).

Adapted from ppt2desc ``src/llm/openai.py`` (MIT, (c) 2025 Adam Łucek).
The request shape (``messages`` with a text part and a base64 ``image_url``
data URI) is the same; the implementation uses ``httpx`` directly instead of
the ``openai`` SDK so that:

  * the base URL, auth header, CA bundle and client certificate are fully
    under our control (internal endpoint only, no fall-back to api.openai.com);
  * timeouts, retries with exponential back-off and an outbound host
    allow-list are enforced by :mod:`ppt2kb.security.outbound`;
  * the dependency footprint for the air-gapped bundle stays small.

Nothing from the slide (image or text) is ever logged.
"""
from __future__ import annotations

import base64
import json
import logging
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union

import httpx

from ..schemas.deck import SlideDescription
from ..security.outbound import make_client

logger = logging.getLogger(__name__)


class QwenError(Exception):
    def __init__(self, message: str, *, status: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class QwenConfig:
    base_url: str
    model: str
    api_key: str = ""
    auth_header: str = "Authorization"
    auth_scheme: str = "Bearer"
    timeout_s: float = 180.0
    max_retries: int = 3
    max_tokens: int = 4096
    temperature: float = 0.1
    extra_body: dict = field(default_factory=dict)
    ca_bundle: Optional[str] = None
    verify: bool = True
    client_cert: Optional[str] = None
    client_key: Optional[str] = None
    allowed_hosts: tuple = ()
    # If true, ask for JSON mode (response_format). Some OpenAI-compatible
    # servers (vLLM, SGLang) support it; others reject it. Auto-disabled on 400.
    json_mode: bool = True

    def chat_url(self) -> str:
        base = self.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            return base
        return base + "/chat/completions"


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_description(text: str) -> SlideDescription:
    """Parse the model answer into a :class:`SlideDescription`.

    Tolerates markdown code fences and leading/trailing prose. Falls back to
    treating the whole answer as the technical description.
    """
    raw = (text or "").strip()
    candidate = raw
    fence = re.search(r"```(?:json)?\s*(.*?)```", raw, re.DOTALL)
    if fence:
        candidate = fence.group(1).strip()
    obj = None
    for attempt in (candidate, raw):
        try:
            obj = json.loads(attempt)
            break
        except Exception:
            m = _JSON_RE.search(attempt)
            if m:
                try:
                    obj = json.loads(m.group(0))
                    break
                except Exception:
                    obj = None
    if not isinstance(obj, dict):
        return SlideDescription(technical_description=raw, uncertainties="Model did not return structured JSON; raw answer kept.")
    data = {}
    for key in SlideDescription.model_fields:
        v = obj.get(key, "")
        if isinstance(v, list):
            v = "\n".join(str(x) for x in v)
        elif v is None:
            v = ""
        elif not isinstance(v, str):
            v = json.dumps(v, ensure_ascii=False)
        data[key] = v
    return SlideDescription(**data)


class QwenClient:
    """OpenAI-compatible vision chat client for the internal Qwen endpoint."""

    def __init__(self, cfg: QwenConfig, system_prompt: str):
        if not cfg.base_url:
            raise ValueError("Qwen base URL is not configured")
        if not cfg.model:
            raise ValueError("Qwen model is not configured")
        self.cfg = cfg
        self.model_name = cfg.model
        self.system_prompt = system_prompt
        self._json_mode = cfg.json_mode
        self._lock = threading.Lock()
        headers = {"Content-Type": "application/json", "Accept": "application/json", "User-Agent": "ppt2kb/1.0"}
        if cfg.api_key:
            value = f"{cfg.auth_scheme} {cfg.api_key}".strip() if cfg.auth_scheme else cfg.api_key
            headers[cfg.auth_header] = value
        self._client = make_client(
            allowed_hosts=cfg.allowed_hosts,
            timeout_s=cfg.timeout_s,
            ca_bundle=cfg.ca_bundle,
            verify=cfg.verify,
            client_cert=cfg.client_cert,
            client_key=cfg.client_key,
            base_url="",
            headers=headers,
            extra_allowed=[],
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ api
    @staticmethod
    def _encode_image(image_path: Union[str, Path]) -> tuple[str, str]:
        p = Path(image_path)
        mime = "image/jpeg" if p.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        return mime, base64.b64encode(p.read_bytes()).decode("ascii")

    def _body(self, prompt: str, mime: str, b64: str) -> dict:
        body = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    ],
                },
            ],
            "max_tokens": self.cfg.max_tokens,
            "temperature": self.cfg.temperature,
            "stream": False,
        }
        if self._json_mode:
            body["response_format"] = {"type": "json_object"}
        if self.cfg.extra_body:
            body.update(self.cfg.extra_body)
        return body

    def generate(self, prompt: str, image_path: Union[str, Path]) -> str:
        """ppt2desc-compatible: return the raw text answer."""
        p = Path(image_path)
        if not p.is_file():
            raise FileNotFoundError(f"Image file not found at {p}")
        mime, b64 = self._encode_image(p)
        return self._request(prompt, mime, b64)

    def describe(self, prompt: str, image_path: Union[str, Path]) -> tuple[SlideDescription, str]:
        raw = self.generate(prompt, image_path)
        return parse_description(raw), raw

    def ping(self) -> dict:
        """Connectivity test: GET /models if available, otherwise a tiny chat."""
        base = self.cfg.base_url.rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        try:
            r = self._client.get(base + "/models")
            if r.status_code == 200:
                try:
                    ids = [m.get("id") for m in r.json().get("data", []) if isinstance(m, dict)]
                except Exception:
                    ids = []
                return {"ok": True, "detail": "models endpoint reachable", "models": ids[:50]}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"connection failed: {e.__class__.__name__}"}
        # Fallback: minimal completion
        try:
            body = {"model": self.cfg.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}
            r = self._client.post(self.cfg.chat_url(), json=body)
            return {"ok": r.status_code < 400, "detail": f"chat endpoint returned HTTP {r.status_code}"}
        except httpx.HTTPError as e:
            return {"ok": False, "detail": f"connection failed: {e.__class__.__name__}"}

    # ------------------------------------------------------------- internals
    def _request(self, prompt: str, mime: str, b64: str) -> str:
        attempts = max(1, self.cfg.max_retries + 1)
        last: Optional[QwenError] = None
        for attempt in range(1, attempts + 1):
            try:
                return self._once(prompt, mime, b64)
            except QwenError as e:
                last = e
                if not e.retryable or attempt == attempts:
                    raise
                delay = min(30.0, (2 ** (attempt - 1)) + random.uniform(0, 0.5))
                logger.warning("Qwen request failed (attempt %s/%s, %s); retrying in %.1fs", attempt, attempts, e, delay)
                time.sleep(delay)
        assert last is not None
        raise last

    def _once(self, prompt: str, mime: str, b64: str) -> str:
        body = self._body(prompt, mime, b64)
        try:
            r = self._client.post(self.cfg.chat_url(), json=body)
        except httpx.TimeoutException as e:
            raise QwenError("request timed out", retryable=True) from e
        except httpx.HTTPError as e:
            raise QwenError(f"connection error: {e.__class__.__name__}", retryable=True) from e

        if r.status_code == 400 and "response_format" in body and "response_format" in r.text:
            with self._lock:
                if self._json_mode:
                    self._json_mode = False
                    logger.info("Endpoint rejected response_format; falling back to plain text mode")
            return self._once(prompt, mime, b64)
        if r.status_code in (408, 409, 425, 429, 500, 502, 503, 504):
            raise QwenError(f"HTTP {r.status_code}", status=r.status_code, retryable=True)
        if r.status_code >= 400:
            # Do not include the response body: it could echo the prompt/slide.
            raise QwenError(f"HTTP {r.status_code}", status=r.status_code, retryable=False)
        try:
            data = r.json()
        except ValueError as e:
            raise QwenError("invalid JSON in response", retryable=True) from e
        content = self._extract_content(data)
        if not content or not content.strip():
            raise QwenError("empty response from model", retryable=True)
        return content

    @staticmethod
    def _extract_content(data: dict) -> str:
        # Mirrors ppt2desc's defensive extraction of message content.
        try:
            message = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as e:
            raise QwenError("unexpected response structure", retryable=False) from e
        content = message.get("content")
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("text"):
                    return str(block["text"])
        return str(content)
