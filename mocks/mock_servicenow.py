"""
Mock ServiceNow instance - the subset of the Table API and Attachment API
used by ppt2kb.

  GET    /api/now/table/kb_knowledge_base
  GET    /api/now/table/kb_knowledge?sysparm_query=...
  GET    /api/now/table/kb_knowledge/{sys_id}
  POST   /api/now/table/kb_knowledge
  PATCH  /api/now/table/kb_knowledge/{sys_id}
  GET    /api/now/attachment?sysparm_query=...
  POST   /api/now/attachment/file?table_name=&table_sys_id=&file_name=
  DELETE /api/now/attachment/{sys_id}
  GET    /sys_attachment.do?sys_id=   (serves attachment bytes; lets the article HTML render)
  POST   /oauth_token.do              (password grant)

Auth: Basic ``admin`` / ``admin`` (override with MOCK_SN_USER / MOCK_SN_PASSWORD)
or Bearer ``MOCK_SN_TOKEN`` (default "mock-token").

Failure simulation (``POST /_mock/config``): ``fail_attachment_after=N`` makes
every attachment upload after the N-th fail with HTTP 500 until reset.

Run: ``python -m mocks.mock_servicenow --port 9002``
"""
from __future__ import annotations

import argparse
import base64
import os
import re
import secrets
import threading
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

app = FastAPI(title="mock-servicenow")
_lock = threading.Lock()
_user = os.environ.get("MOCK_SN_USER", "admin")
_password = os.environ.get("MOCK_SN_PASSWORD", "admin")
_token = os.environ.get("MOCK_SN_TOKEN", "mock-token")
_counter = {"kb": 1000, "attach_calls": 0}
_cfg = {"fail_attachment_after": 0, "delay_ms": 0}

KBS = {
    "a1b2c3d4e5f60718293a4b5c6d7e8f90": {"sys_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90", "title": "IT Knowledge", "description": "Internal IT", "kb_version": "3"},
    "0f1e2d3c4b5a69788796a5b4c3d2e1f0": {"sys_id": "0f1e2d3c4b5a69788796a5b4c3d2e1f0", "title": "מאגר ידע - תמיכה", "description": "Hebrew KB", "kb_version": "3"},
}
ARTICLES: dict[str, dict] = {}
ATTACHMENTS: dict[str, dict] = {}


def _auth_ok(request: Request) -> bool:
    h = request.headers.get("authorization", "")
    if h.startswith("Basic "):
        try:
            u, p = base64.b64decode(h[6:]).decode().split(":", 1)
            return secrets.compare_digest(u, _user) and secrets.compare_digest(p, _password)
        except Exception:
            return False
    if h.startswith("Bearer "):
        return secrets.compare_digest(h[7:], _token)
    return False


def _unauth():
    return JSONResponse({"error": {"message": "User is not authenticated", "detail": "Required to provide Auth information"}, "status": "failure"}, status_code=401)


def _fields(record: dict, fields: str | None) -> dict:
    if not fields:
        return record
    wanted = [f.strip() for f in fields.split(",") if f.strip()]
    return {k: record.get(k, "") for k in wanted}


@app.post("/oauth_token.do")
async def oauth(request: Request):
    form = await request.form()
    if form.get("grant_type") == "password" and form.get("username") == _user and form.get("password") == _password and form.get("client_id"):
        return {"access_token": _token, "token_type": "Bearer", "expires_in": 1800, "scope": "useraccount"}
    return JSONResponse({"error": "access_denied"}, status_code=401)


@app.get("/api/now/table/kb_knowledge_base")
async def kbs(request: Request):
    if not _auth_ok(request):
        return _unauth()
    fields = request.query_params.get("sysparm_fields")
    return {"result": [_fields(k, fields) for k in KBS.values()]}


@app.get("/api/now/table/kb_knowledge")
async def query_articles(request: Request):
    if not _auth_ok(request):
        return _unauth()
    q = request.query_params.get("sysparm_query", "")
    fields = request.query_params.get("sysparm_fields")
    limit = int(request.query_params.get("sysparm_limit", "100"))
    res = list(ARTICLES.values())
    m = re.match(r"^textLIKE(.+)$", q)
    if m:
        needle = m.group(1)
        res = [a for a in res if needle in a.get("text", "")]
    elif q:
        res = []
    return {"result": [_fields(a, fields) for a in res[:limit]]}


@app.get("/api/now/table/kb_knowledge/{sys_id}")
async def get_article(request: Request, sys_id: str):
    if not _auth_ok(request):
        return _unauth()
    a = ARTICLES.get(sys_id)
    if not a:
        return JSONResponse({"error": {"message": "No Record found"}, "status": "failure"}, status_code=404)
    return {"result": _fields(a, request.query_params.get("sysparm_fields"))}


@app.post("/api/now/table/kb_knowledge", status_code=201)
async def create_article(request: Request):
    if not _auth_ok(request):
        return _unauth()
    body = await request.json()
    if body.get("kb_knowledge_base") not in KBS:
        return JSONResponse({"error": {"message": "Invalid kb_knowledge_base"}, "status": "failure"}, status_code=400)
    with _lock:
        _counter["kb"] += 1
        sys_id = uuid.uuid4().hex
        rec = {
            "sys_id": sys_id,
            "number": f"KB{_counter['kb']:07d}",
            "short_description": body.get("short_description", ""),
            "text": body.get("text", ""),
            "kb_knowledge_base": body.get("kb_knowledge_base", ""),
            "workflow_state": body.get("workflow_state", "draft"),
            "article_type": body.get("article_type", "text"),
            "sys_created_on": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        for k, v in body.items():
            rec.setdefault(k, v)
        ARTICLES[sys_id] = rec
    return {"result": _fields(rec, request.query_params.get("sysparm_fields"))}


@app.patch("/api/now/table/kb_knowledge/{sys_id}")
async def patch_article(request: Request, sys_id: str):
    if not _auth_ok(request):
        return _unauth()
    a = ARTICLES.get(sys_id)
    if not a:
        return JSONResponse({"error": {"message": "No Record found"}, "status": "failure"}, status_code=404)
    body = await request.json()
    with _lock:
        a.update(body)
    return {"result": _fields(a, request.query_params.get("sysparm_fields"))}


@app.get("/api/now/attachment")
async def list_attachments(request: Request):
    if not _auth_ok(request):
        return _unauth()
    q = request.query_params.get("sysparm_query", "")
    m = re.match(r"^table_name=(\w+)\^table_sys_id=([0-9a-f]+)$", q)
    res = list(ATTACHMENTS.values())
    if m:
        res = [a for a in res if a["table_name"] == m.group(1) and a["table_sys_id"] == m.group(2)]
    fields = request.query_params.get("sysparm_fields")
    return {"result": [_fields({k: v for k, v in a.items() if k != "data"}, fields) for a in res]}


@app.post("/api/now/attachment/file", status_code=201)
async def upload(request: Request):
    if not _auth_ok(request):
        return _unauth()
    table = request.query_params.get("table_name", "")
    sys_id = request.query_params.get("table_sys_id", "")
    name = request.query_params.get("file_name", "")
    if table != "kb_knowledge" or sys_id not in ARTICLES or not name:
        return JSONResponse({"error": {"message": "Invalid table or record"}, "status": "failure"}, status_code=400)
    data = await request.body()
    with _lock:
        _counter["attach_calls"] += 1
        if _cfg["fail_attachment_after"] and _counter["attach_calls"] > _cfg["fail_attachment_after"]:
            return JSONResponse({"error": {"message": "simulated failure"}, "status": "failure"}, status_code=500)
        aid = uuid.uuid4().hex
        ATTACHMENTS[aid] = {
            "sys_id": aid,
            "file_name": name,
            "table_name": table,
            "table_sys_id": sys_id,
            "size_bytes": str(len(data)),
            "content_type": request.headers.get("content-type", "application/octet-stream"),
            "download_link": f"/api/now/attachment/{aid}/file",
            "data": data,
        }
    if _cfg["delay_ms"]:
        time.sleep(_cfg["delay_ms"] / 1000.0)
    return {"result": {k: v for k, v in ATTACHMENTS[aid].items() if k != "data"}}


@app.delete("/api/now/attachment/{sys_id}", status_code=204)
async def delete_attachment(request: Request, sys_id: str):
    if not _auth_ok(request):
        return _unauth()
    ATTACHMENTS.pop(sys_id, None)
    return Response(status_code=204)


@app.get("/sys_attachment.do")
@app.get("/api/now/attachment/{sys_id}/file")
async def download(request: Request, sys_id: str = ""):
    sys_id = sys_id or request.query_params.get("sys_id", "")
    a = ATTACHMENTS.get(sys_id)
    if not a:
        return Response(status_code=404)
    return Response(content=a["data"], media_type=a["content_type"])


# ----------------------------------------------------------- test helpers
@app.post("/_mock/config")
async def mock_config(request: Request):
    body = await request.json()
    with _lock:
        for k in ("fail_attachment_after", "delay_ms"):
            if k in body:
                _cfg[k] = int(body[k])
        if body.get("reset_counters"):
            _counter["attach_calls"] = 0
        if body.get("clear"):
            ARTICLES.clear()
            ATTACHMENTS.clear()
            _counter["attach_calls"] = 0
    return {"ok": True, "cfg": _cfg}


@app.get("/_mock/articles")
async def mock_articles():
    return {"articles": list(ARTICLES.values()), "attachments": [{k: v for k, v in a.items() if k != "data"} for a in ATTACHMENTS.values()]}


def main() -> None:
    import uvicorn

    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=9002)
    a = p.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
