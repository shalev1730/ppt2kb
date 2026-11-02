"""
Minimal ServiceNow REST client (Table API + Attachment API).

Only standard, documented APIs are used:

  * ``GET  /api/now/table/kb_knowledge_base``   list knowledge bases
  * ``GET  /api/now/table/kb_knowledge``        duplicate detection
  * ``POST /api/now/table/kb_knowledge``        create the draft article
  * ``PATCH /api/now/table/kb_knowledge/{id}``  update article HTML
  * ``POST /api/now/attachment/file``           upload slide images / PPTX
  * ``GET  /api/now/attachment?sysparm_query``  list existing attachments
  * ``POST /oauth_token.do``                    (only for auth_type=oauth_password)

Authentication: HTTP Basic, static Bearer token, or OAuth2 password grant
(the token is refreshed automatically). Credentials never appear in logs.
"""
from __future__ import annotations

import logging
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

from ..security.outbound import make_client

logger = logging.getLogger(__name__)


class ServiceNowError(Exception):
    def __init__(self, message: str, *, status: Optional[int] = None, retryable: bool = False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


@dataclass
class ServiceNowConfig:
    instance_url: str
    auth_type: str = "basic"  # basic | bearer | oauth_password
    username: str = ""
    password: str = ""
    token: str = ""
    oauth_client_id: str = ""
    oauth_client_secret: str = ""
    timeout_s: float = 120.0
    max_retries: int = 3
    extra_fields: Dict[str, Any] = field(default_factory=dict)
    ca_bundle: Optional[str] = None
    verify: bool = True
    client_cert: Optional[str] = None
    client_key: Optional[str] = None
    allowed_hosts: tuple = ()

    def base(self) -> str:
        return self.instance_url.rstrip("/")


class ServiceNowClient:
    def __init__(self, cfg: ServiceNowConfig):
        if not cfg.instance_url:
            raise ValueError("ServiceNow URL is not configured")
        self.cfg = cfg
        self._lock = threading.Lock()
        self._oauth_token: Optional[str] = None
        self._oauth_expiry: float = 0.0
        self._client = make_client(
            allowed_hosts=cfg.allowed_hosts,
            timeout_s=cfg.timeout_s,
            ca_bundle=cfg.ca_bundle,
            verify=cfg.verify,
            client_cert=cfg.client_cert,
            client_key=cfg.client_key,
            base_url=cfg.base(),
            headers={"Accept": "application/json", "User-Agent": "ppt2kb/1.0"},
        )

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------ auth
    def _auth_headers(self) -> Dict[str, str]:
        t = self.cfg.auth_type
        if t == "basic":
            if not self.cfg.username:
                raise ServiceNowError("ServiceNow username is not configured")
            return {}  # handled via httpx auth
        if t == "bearer":
            if not self.cfg.token:
                raise ServiceNowError("ServiceNow token is not configured")
            return {"Authorization": f"Bearer {self.cfg.token}"}
        if t == "oauth_password":
            return {"Authorization": f"Bearer {self._oauth()}"}
        raise ServiceNowError(f"Unsupported auth type {t}")

    def _basic(self) -> Optional[httpx.BasicAuth]:
        if self.cfg.auth_type == "basic":
            return httpx.BasicAuth(self.cfg.username, self.cfg.password)
        return None

    def _oauth(self) -> str:
        with self._lock:
            if self._oauth_token and time.time() < self._oauth_expiry - 60:
                return self._oauth_token
            data = {
                "grant_type": "password",
                "client_id": self.cfg.oauth_client_id,
                "client_secret": self.cfg.oauth_client_secret,
                "username": self.cfg.username,
                "password": self.cfg.password,
            }
            r = self._client.post("/oauth_token.do", data=data, headers={"Accept": "application/json"})
            if r.status_code != 200:
                raise ServiceNowError(f"OAuth token request failed with HTTP {r.status_code}", status=r.status_code)
            body = r.json()
            self._oauth_token = body["access_token"]
            self._oauth_expiry = time.time() + float(body.get("expires_in", 1800))
            return self._oauth_token

    # --------------------------------------------------------------- request
    def _request(self, method: str, path: str, *, params=None, json_body=None, content=None, headers=None) -> httpx.Response:
        attempts = max(1, self.cfg.max_retries + 1)
        for attempt in range(1, attempts + 1):
            hdrs = dict(headers or {})
            hdrs.update(self._auth_headers())
            try:
                r = self._client.request(method, path, params=params, json=json_body, content=content, headers=hdrs, auth=self._basic())
            except httpx.TimeoutException as e:
                err = ServiceNowError("ServiceNow request timed out", retryable=True)
                r = None
            except httpx.HTTPError as e:
                err = ServiceNowError(f"ServiceNow connection error: {e.__class__.__name__}", retryable=True)
                r = None
            if r is not None:
                if r.status_code in (401, 403):
                    raise ServiceNowError(f"ServiceNow authentication/authorization failed (HTTP {r.status_code})", status=r.status_code)
                if r.status_code in (408, 429, 500, 502, 503, 504):
                    err = ServiceNowError(f"ServiceNow returned HTTP {r.status_code}", status=r.status_code, retryable=True)
                elif r.status_code >= 400:
                    detail = ""
                    try:
                        detail = r.json().get("error", {}).get("message", "")
                    except Exception:
                        pass
                    raise ServiceNowError(f"ServiceNow returned HTTP {r.status_code}: {detail[:200]}", status=r.status_code)
                else:
                    return r
            if attempt == attempts:
                raise err
            delay = min(20.0, 2 ** (attempt - 1) + random.uniform(0, 0.5))
            logger.warning("%s; retrying in %.1fs (attempt %s/%s)", err, delay, attempt, attempts)
            time.sleep(delay)
        raise ServiceNowError("unreachable")  # pragma: no cover

    # ------------------------------------------------------------------- api
    def ping(self) -> dict:
        try:
            r = self._request("GET", "/api/now/table/kb_knowledge_base", params={"sysparm_limit": "1", "sysparm_fields": "sys_id"})
            return {"ok": True, "detail": f"HTTP {r.status_code}"}
        except ServiceNowError as e:
            return {"ok": False, "detail": str(e)}

    def list_knowledge_bases(self) -> List[dict]:
        r = self._request(
            "GET",
            "/api/now/table/kb_knowledge_base",
            params={
                "sysparm_query": "active=true^ORDERBYtitle",
                "sysparm_fields": "sys_id,title,description,kb_version",
                "sysparm_limit": "200",
                "sysparm_display_value": "false",
            },
        )
        return [
            {"sys_id": x.get("sys_id", ""), "title": x.get("title", ""), "description": x.get("description", "")}
            for x in r.json().get("result", [])
        ]

    def find_article_by_marker(self, marker: str) -> Optional[dict]:
        """Duplicate detection: look for an article whose text contains our marker."""
        r = self._request(
            "GET",
            "/api/now/table/kb_knowledge",
            params={"sysparm_query": f"textLIKE{marker}", "sysparm_fields": "sys_id,number,workflow_state,short_description", "sysparm_limit": "1"},
        )
        res = r.json().get("result", [])
        return res[0] if res else None

    def get_article(self, sys_id: str) -> Optional[dict]:
        try:
            r = self._request("GET", f"/api/now/table/kb_knowledge/{quote(sys_id)}", params={"sysparm_fields": "sys_id,number,workflow_state,short_description,kb_knowledge_base"})
        except ServiceNowError as e:
            if e.status == 404:
                return None
            raise
        return r.json().get("result")

    def create_article(self, *, short_description: str, text_html: str, kb_sys_id: str, extra: Optional[dict] = None) -> dict:
        body: Dict[str, Any] = {
            "short_description": short_description[:160],
            "text": text_html,
            "kb_knowledge_base": kb_sys_id,
            "workflow_state": "draft",
            "article_type": "text",  # HTML article (standard field, value "text" = HTML on current releases)
        }
        body.update(self.cfg.extra_fields or {})
        body.update(extra or {})
        r = self._request("POST", "/api/now/table/kb_knowledge", json_body=body, params={"sysparm_fields": "sys_id,number,workflow_state"})
        return r.json()["result"]

    def update_article(self, sys_id: str, fields: dict) -> dict:
        r = self._request("PATCH", f"/api/now/table/kb_knowledge/{quote(sys_id)}", json_body=fields, params={"sysparm_fields": "sys_id,number,workflow_state"})
        return r.json()["result"]

    def list_attachments(self, table: str, sys_id: str) -> List[dict]:
        r = self._request(
            "GET",
            "/api/now/attachment",
            params={"sysparm_query": f"table_name={table}^table_sys_id={sys_id}", "sysparm_fields": "sys_id,file_name,size_bytes,content_type", "sysparm_limit": "1000"},
        )
        return r.json().get("result", [])

    def upload_attachment(self, table: str, sys_id: str, file_name: str, content_type: str, data: bytes) -> dict:
        r = self._request(
            "POST",
            "/api/now/attachment/file",
            params={"table_name": table, "table_sys_id": sys_id, "file_name": file_name},
            content=data,
            headers={"Content-Type": content_type},
        )
        return r.json()["result"]

    def delete_attachment(self, sys_id: str) -> None:
        self._request("DELETE", f"/api/now/attachment/{quote(sys_id)}")

    # -------------------------------------------------------------- helpers
    def article_links(self, sys_id: str, number: str) -> dict:
        base = self.cfg.base()
        return {
            "form": f"{base}/kb_knowledge.do?sys_id={sys_id}",
            "view": f"{base}/kb_view.do?sysparm_article={number}",
            "portal": f"{base}/sp?id=kb_article_view&sysparm_article={number}",
        }
