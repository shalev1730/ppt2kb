"""
Mock Qwen Vision endpoint (OpenAI-compatible Chat Completions).

Used by the automated tests and for the offline POC when the real endpoint
is not reachable. It returns a deterministic structured JSON description and
can simulate failures:

  * ``MOCK_QWEN_FAIL_SLIDES="3,7"``   -> slides 3 and 7 always fail with HTTP 500
  * ``MOCK_QWEN_FLAKY_EVERY=5``       -> every 5th request fails once (tests retries)
  * ``MOCK_QWEN_API_KEY=secret``      -> require ``Authorization: Bearer secret``
  * ``MOCK_QWEN_DELAY_MS=200``        -> simulated latency

Control endpoints (test use only): ``POST /_mock/config`` with the same keys,
``GET /_mock/stats``.

Run: ``python -m mocks.mock_qwen --port 9001``
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="mock-qwen")
_state = {
    "fail_slides": {int(x) for x in os.environ.get("MOCK_QWEN_FAIL_SLIDES", "").split(",") if x.strip().isdigit()},
    "flaky_every": int(os.environ.get("MOCK_QWEN_FLAKY_EVERY", "0") or 0),
    "api_key": os.environ.get("MOCK_QWEN_API_KEY", ""),
    "delay_ms": int(os.environ.get("MOCK_QWEN_DELAY_MS", "0") or 0),
    "plain_text": False,  # answer without JSON (tests parser fallback)
    "degenerate_first": False,  # first answer per slide: truncated JSON + runaway newlines (small-model loop)
    "visual_first": False,  # first answer per slide describes appearance only (tests the quality retry)
    "visual_always": False,  # every answer describes appearance only (tests needs_review)
    "reject_json_mode": False,  # 400 when response_format is sent (tests fallback)
}
_stats = {"requests": 0, "failures": 0, "images_seen": 0, "flaky_counter": 0, "hashes": [], "penalised_requests": 0, "degenerate_sent": set(), "visual_sent": set(), "corrections_seen": 0, "prompts": []}
_lock = threading.Lock()
_SLIDE_RE = re.compile(r"slide (\d+) of (\d+)", re.IGNORECASE)


@app.get("/v1/models")
@app.get("/models")
async def models(request: Request):
    if not _auth_ok(request):
        return JSONResponse({"error": {"message": "unauthorized"}}, status_code=401)
    return {"object": "list", "data": [{"id": "mock-qwen2.5-vl", "object": "model"}]}


def _auth_ok(request: Request) -> bool:
    key = _state["api_key"]
    if not key:
        return True
    return request.headers.get("authorization", "") == f"Bearer {key}"


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat(request: Request):
    body = await request.json()
    if not _auth_ok(request):
        return JSONResponse({"error": {"message": "unauthorized"}}, status_code=401)
    if _state["reject_json_mode"] and "response_format" in body:
        return JSONResponse({"error": {"message": "response_format is not supported"}}, status_code=400)
    with _lock:
        _stats["requests"] += 1
        _stats["flaky_counter"] += 1
        if "frequency_penalty" in body:
            _stats["penalised_requests"] += 1
        flaky_hit = _state["flaky_every"] and _stats["flaky_counter"] % _state["flaky_every"] == 0

    # Extract the user text and image (base64) from the request
    user_text, image_b64 = "", ""
    for m in body.get("messages", []):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            user_text = content
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    user_text += part.get("text", "")
                elif part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:image/"):
                        image_b64 = url.split(",", 1)[1]
    slide_no, slide_total = 0, 0
    m = _SLIDE_RE.search(user_text)
    if m:
        slide_no, slide_total = int(m.group(1)), int(m.group(2))
    img_hash = ""
    if image_b64:
        try:
            raw = base64.b64decode(image_b64)
            img_hash = hashlib.sha256(raw).hexdigest()[:12]
            with _lock:
                _stats["images_seen"] += 1
                _stats["hashes"].append((slide_no, img_hash, len(raw)))
        except Exception:
            img_hash = "invalid"
    if _state["delay_ms"]:
        time.sleep(_state["delay_ms"] / 1000.0)
    if slide_no in _state["fail_slides"] or flaky_hit:
        with _lock:
            _stats["failures"] += 1
        return JSONResponse({"error": {"message": "simulated failure"}}, status_code=500)

    extracted = ""
    em = re.search(r"<(?:extracted_text|slide_text)>\s*(.*?)\s*</(?:extracted_text|slide_text)>", user_text, re.DOTALL)
    if em:
        extracted = em.group(1)
    with _lock:
        if "previous answer" in user_text:
            _stats["corrections_seen"] += 1
        if len(_stats["prompts"]) < 200:
            _stats["prompts"].append(user_text[:600])
    title = (extracted.splitlines()[0] if extracted else f"Slide {slide_no}")[:120]
    hebrew = bool(re.search(r"[֐-׿]", extracted))
    desc = {
        "title": title,
        "slide_kind": "title" if slide_no == 1 else "content",
        "summary": (f"(mock) Slide {slide_no} of {slide_total}: השקף מסביר את הנושא '{title}' - רכיבי המערכת, הקשר ביניהם והפעולה שהמשתמש מבצע. Image hash {img_hash}."
                    if hebrew else f"(mock) Slide {slide_no} of {slide_total} explains '{title}': the components involved, how they relate and what the user does. Image hash {img_hash}."),
        "details": f"(mock) The client sends an HTTP request to the API service, which validates it and queries the database table; the arrows indicate the direction of the call. Technical identifiers on the slide: incident, sys_user, gs.info('Message')." if slide_no % 3 == 0 else "",
        "procedures": "1. (mock) Open the admin console\n2. (mock) Enter the server address\n3. (mock) Click Apply" if slide_no % 2 == 0 else "",
        "key_facts": "table: incident\nscript: gs.info('Message')" if slide_no % 3 == 0 else "",
        "visible_text": extracted or f"(mock) visible text of slide {slide_no}",
        "uncertainties": "",
        "language": "he+en" if hebrew else "en",
        "confidence": "high",
    }
    if _state["visual_always"] or (_state["visual_first"] and "frequency_penalty" not in body and "previous answer" not in user_text):
        with _lock:
            first = slide_no not in _stats["visual_sent"]
            _stats["visual_sent"].add(slide_no)
        if _state["visual_always"] or first:
            desc["summary"] = "(mock) The slide has a dark blue background with a white logo in the top left corner, a centered title in a large font and three rounded boxes in light grey."
            desc["details"] = ""
            desc["procedures"] = ""
            desc["key_facts"] = ""
    text = json.dumps(desc, ensure_ascii=False)
    if _state["plain_text"]:
        text = desc["summary"]
    if _state["degenerate_first"] and "frequency_penalty" not in body:
        with _lock:
            if slide_no not in _stats["degenerate_sent"]:
                _stats["degenerate_sent"].add(slide_no)
                text = '{\n"title": ' + json.dumps(title, ensure_ascii=False) + ',\n"visible_text": "SLA Problem Change' + "\\n" * 3000
    return {
        "id": f"chatcmpl-mock-{_stats['requests']}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "mock"),
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200},
    }


@app.post("/_mock/config")
async def mock_config(request: Request):
    body = await request.json()
    with _lock:
        if "fail_slides" in body:
            _state["fail_slides"] = set(int(x) for x in body["fail_slides"])
        for k in ("flaky_every", "delay_ms"):
            if k in body:
                _state[k] = int(body[k])
        for k in ("api_key",):
            if k in body:
                _state[k] = str(body[k])
        for k in ("plain_text", "reject_json_mode", "degenerate_first", "visual_first", "visual_always"):
            if k in body:
                _state[k] = bool(body[k])
        if body.get("reset_stats"):
            _stats.update({"requests": 0, "failures": 0, "images_seen": 0, "flaky_counter": 0, "hashes": [], "penalised_requests": 0, "degenerate_sent": set(), "visual_sent": set(), "corrections_seen": 0, "prompts": []})
    return {"ok": True, "state": {k: (sorted(v) if isinstance(v, set) else v) for k, v in _state.items()}}


@app.get("/_mock/stats")
async def mock_stats():
    with _lock:
        return {**_stats, "hashes": list(_stats["hashes"]), "degenerate_sent": sorted(_stats["degenerate_sent"]), "visual_sent": sorted(_stats["visual_sent"]), "prompts": list(_stats["prompts"])}


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9001)
    a = p.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
