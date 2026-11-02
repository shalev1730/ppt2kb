"""
Effective runtime configuration = environment settings + UI overrides.

Non-secret overrides (URLs, model name, concurrency, default KB) are stored in
the SQLite ``settings`` table. Secrets entered in the UI are kept in process
memory only (lost on restart) unless ``PPT2KB_PERSIST_UI_SECRETS=true``.
Secrets are never returned to the browser; the API only reports whether a
secret is set.
"""
from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import Settings, host_of
from .llm.qwen import QwenConfig
from .logging_utils import register_secret
from .servicenow.client import ServiceNowConfig
from .storage.db import Database

logger = logging.getLogger(__name__)

# UI-editable, non-secret keys and their types
PUBLIC_KEYS: Dict[str, type] = {
    "qwen_base_url": str,
    "qwen_model": str,
    "qwen_auth_header": str,
    "qwen_auth_scheme": str,
    "qwen_timeout_s": int,
    "qwen_max_retries": int,
    "qwen_concurrency": int,
    "qwen_rate_limit_per_min": int,
    "qwen_max_tokens": int,
    "qwen_temperature": float,
    "qwen_system_prompt": str,
    "qwen_extra_body_json": str,
    "servicenow_url": str,
    "servicenow_auth_type": str,
    "servicenow_username": str,
    "servicenow_oauth_client_id": str,
    "servicenow_timeout_s": int,
    "servicenow_default_kb": str,
    "servicenow_attach_pptx": bool,
    "servicenow_extra_fields_json": str,
}
SECRET_KEYS = ("qwen_api_key", "servicenow_password", "servicenow_token", "servicenow_oauth_client_secret")


@dataclass
class SecretState:
    value: str = ""
    source: str = "none"  # env | ui | none


class RuntimeConfig:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self._lock = threading.Lock()
        self._secrets: Dict[str, SecretState] = {}
        for key in SECRET_KEYS:
            env_val = getattr(settings, key).get_secret_value()
            if env_val:
                register_secret(env_val)
                self._secrets[key] = SecretState(env_val, "env")
            else:
                self._secrets[key] = SecretState("", "none")
            if settings.persist_ui_secrets:
                stored = db.get_setting("secret:" + key)
                if stored:
                    register_secret(stored)
                    self._secrets[key] = SecretState(stored, "ui")

    # ------------------------------------------------------------ accessors
    def get(self, key: str) -> Any:
        if key not in PUBLIC_KEYS:
            raise KeyError(key)
        stored = self.db.get_setting(key)
        typ = PUBLIC_KEYS[key]
        if stored is not None:
            return _coerce(stored, typ)
        if key == "qwen_system_prompt":
            from .prompt import load_prompt

            return load_prompt(self.settings.qwen_prompt_file)
        return getattr(self.settings, key)

    def secret(self, key: str) -> str:
        with self._lock:
            return self._secrets[key].value

    def public_view(self) -> dict:
        out = {k: self.get(k) for k in PUBLIC_KEYS}
        out["secrets"] = {k: {"set": bool(v.value), "source": v.source} for k, v in self._secrets.items()}
        out["tls_verify"] = self.settings.tls_verify
        out["ca_bundle"] = str(self.settings.ca_bundle) if self.settings.ca_bundle else ""
        out["allowed_outbound_hosts"] = self.settings.allowed_hosts()
        out["locked_hosts"] = bool(self.settings.allowed_outbound_hosts)
        out["max_upload_mb"] = self.settings.max_upload_mb
        out["max_slides"] = self.settings.max_slides
        return out

    def update(self, values: dict) -> list[str]:
        """Apply UI changes. Returns list of rejected keys."""
        rejected: list[str] = []
        allowed_hosts = self.settings.allowed_hosts()
        for key, val in values.items():
            if key in SECRET_KEYS:
                val = "" if val is None else str(val)
                with self._lock:
                    if val == "":
                        continue  # empty = keep existing
                    register_secret(val)
                    self._secrets[key] = SecretState(val, "ui")
                if self.settings.persist_ui_secrets:
                    self.db.set_setting("secret:" + key, val)
                continue
            if key not in PUBLIC_KEYS:
                rejected.append(key)
                continue
            if key in ("qwen_base_url", "servicenow_url") and val:
                h = host_of(str(val))
                if not h or not str(val).lower().startswith(("http://", "https://")):
                    rejected.append(key)
                    continue
                if self.settings.allowed_outbound_hosts and h not in allowed_hosts:
                    logger.warning("Rejected %s: host %s not in PPT2KB_ALLOWED_OUTBOUND_HOSTS", key, h)
                    rejected.append(key)
                    continue
            if key.endswith("_json") and val:
                try:
                    parsed = json.loads(str(val))
                    if not isinstance(parsed, dict):
                        raise ValueError
                except ValueError:
                    rejected.append(key)
                    continue
            try:
                coerced = _coerce(val, PUBLIC_KEYS[key])
            except (TypeError, ValueError):
                rejected.append(key)
                continue
            if val is None or val == "":
                self.db.delete_setting(key)
            else:
                self.db.set_setting(key, json.dumps(coerced) if isinstance(coerced, bool) else str(coerced))
        return rejected

    def clear_secret(self, key: str) -> None:
        with self._lock:
            env_val = getattr(self.settings, key).get_secret_value()
            self._secrets[key] = SecretState(env_val, "env") if env_val else SecretState("", "none")
        self.db.delete_setting("secret:" + key)

    # ------------------------------------------------------------- builders
    def _allowed(self) -> tuple:
        hosts = set(self.settings.allowed_hosts())
        for key in ("qwen_base_url", "servicenow_url"):
            h = host_of(str(self.get(key) or ""))
            if h and not self.settings.allowed_outbound_hosts:
                hosts.add(h)
        return tuple(sorted(hosts))

    def qwen_config(self) -> QwenConfig:
        extra = {}
        raw = self.get("qwen_extra_body_json")
        if raw:
            try:
                extra = json.loads(raw)
            except ValueError:
                extra = {}
        return QwenConfig(
            base_url=str(self.get("qwen_base_url") or ""),
            model=str(self.get("qwen_model") or ""),
            api_key=self.secret("qwen_api_key"),
            auth_header=str(self.get("qwen_auth_header") or "Authorization"),
            auth_scheme=str(self.get("qwen_auth_scheme") or ""),
            timeout_s=float(self.get("qwen_timeout_s")),
            max_retries=int(self.get("qwen_max_retries")),
            max_tokens=int(self.get("qwen_max_tokens")),
            temperature=float(self.get("qwen_temperature")),
            extra_body=extra,
            ca_bundle=str(self.settings.ca_bundle) if self.settings.ca_bundle else None,
            verify=self.settings.tls_verify,
            client_cert=str(self.settings.client_cert) if self.settings.client_cert else None,
            client_key=str(self.settings.client_key) if self.settings.client_key else None,
            allowed_hosts=self._allowed(),
        )

    def servicenow_config(self) -> ServiceNowConfig:
        extra = {}
        raw = self.get("servicenow_extra_fields_json")
        if raw:
            try:
                extra = json.loads(raw)
            except ValueError:
                extra = {}
        return ServiceNowConfig(
            instance_url=str(self.get("servicenow_url") or ""),
            auth_type=str(self.get("servicenow_auth_type") or "basic"),
            username=str(self.get("servicenow_username") or ""),
            password=self.secret("servicenow_password"),
            token=self.secret("servicenow_token"),
            oauth_client_id=str(self.get("servicenow_oauth_client_id") or ""),
            oauth_client_secret=self.secret("servicenow_oauth_client_secret"),
            timeout_s=float(self.get("servicenow_timeout_s")),
            max_retries=int(self.settings.servicenow_max_retries),
            extra_fields=extra,
            ca_bundle=str(self.settings.ca_bundle) if self.settings.ca_bundle else None,
            verify=self.settings.tls_verify,
            client_cert=str(self.settings.client_cert) if self.settings.client_cert else None,
            client_key=str(self.settings.client_key) if self.settings.client_key else None,
            allowed_hosts=self._allowed(),
        )


def _coerce(value: Any, typ: type) -> Any:
    if typ is bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")
    if typ is int:
        return int(value)
    if typ is float:
        return float(value)
    return "" if value is None else str(value)
