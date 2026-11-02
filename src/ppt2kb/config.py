"""
Application configuration.

All settings are read from environment variables prefixed with ``PPT2KB_``
(or from an env file whose path is given in ``PPT2KB_ENV_FILE``).
Credentials are *only* accepted from the environment / env file or from the
UI at runtime; they are never written to logs.

See docs/CONFIGURATION.md for the full reference.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, List
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _env_file() -> Optional[str]:
    return os.environ.get("PPT2KB_ENV_FILE") or None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PPT2KB_",
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ------------------------------------------------------------------ server
    host: str = "127.0.0.1"
    port: int = 8080
    data_dir: Path = Path("./data")
    log_level: str = "INFO"
    log_json: bool = False
    # Optional HTTP basic auth for the web UI / API. Empty = disabled
    # (recommended: put the app behind the enterprise reverse proxy / SSO).
    ui_username: str = ""
    ui_password: SecretStr = SecretStr("")
    # Comma separated list of hosts (host[:port]) the application is allowed to
    # contact. Empty = only the hosts of the configured Qwen / ServiceNow URLs.
    allowed_outbound_hosts: str = ""
    # Secrets typed into the UI are kept in memory only, unless this is true.
    persist_ui_secrets: bool = False

    # --------------------------------------------------------------- uploads
    max_upload_mb: int = 200
    max_slides: int = 300
    # Zip-bomb protection for PPTX (which is a ZIP container)
    max_zip_entries: int = 20000
    max_zip_uncompressed_mb: int = 2048
    max_zip_ratio: int = 200
    retention_days: int = 30

    # ------------------------------------------------------------ conversion
    libreoffice_path: Path = Path("/usr/bin/soffice")
    conversion_timeout_s: int = 600
    conversion_memory_mb: int = 3072
    conversion_cpu_seconds: int = 900
    image_width: int = 1920
    image_height: int = 1080
    image_format: str = "png"  # png | jpeg

    # ------------------------------------------------------------------ qwen
    qwen_base_url: str = ""  # e.g. https://qwen.internal.example/v1
    qwen_model: str = "Qwen2.5-VL-72B-Instruct"
    qwen_api_key: SecretStr = SecretStr("")
    qwen_auth_header: str = "Authorization"  # header name
    qwen_auth_scheme: str = "Bearer"  # prefix; empty = raw key
    qwen_timeout_s: int = 180
    qwen_max_retries: int = 3
    qwen_concurrency: int = 4
    qwen_rate_limit_per_min: int = 60
    qwen_max_tokens: int = 4096
    qwen_temperature: float = 0.1
    qwen_prompt_file: Optional[Path] = None
    qwen_extra_body_json: str = ""  # JSON object merged into the request body

    # ------------------------------------------------------------ servicenow
    servicenow_url: str = ""  # e.g. https://servicenow.internal.example
    servicenow_auth_type: str = "basic"  # basic | bearer | oauth_password
    servicenow_username: str = ""
    servicenow_password: SecretStr = SecretStr("")
    servicenow_token: SecretStr = SecretStr("")
    servicenow_oauth_client_id: str = ""
    servicenow_oauth_client_secret: SecretStr = SecretStr("")
    servicenow_timeout_s: int = 120
    servicenow_max_retries: int = 3
    servicenow_default_kb: str = ""  # sys_id of the default knowledge base
    servicenow_attach_pptx: bool = False
    # JSON object with extra kb_knowledge fields to set on creation
    servicenow_extra_fields_json: str = ""

    # ------------------------------------------------------------------- tls
    ca_bundle: Optional[Path] = None  # custom CA bundle (PEM)
    tls_verify: bool = True  # must stay true in production; see docs
    client_cert: Optional[Path] = None
    client_key: Optional[Path] = None

    # ---------------------------------------------------------------- limits
    max_concurrent_jobs: int = 1

    @field_validator("ca_bundle", "client_cert", "client_key", "qwen_prompt_file", mode="before")
    @classmethod
    def _empty_path_is_none(cls, v):
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return v

    def validate_files(self) -> List[str]:
        """Return a list of configuration problems (empty = ok). Called at startup."""
        problems: List[str] = []
        for name in ("ca_bundle", "client_cert", "client_key", "qwen_prompt_file"):
            p = getattr(self, name)
            if p is not None and not Path(p).is_file():
                problems.append(f"PPT2KB_{name.upper()} points to a missing file: {p}")
        if self.max_upload_mb <= 0 or self.max_slides <= 0:
            problems.append("PPT2KB_MAX_UPLOAD_MB and PPT2KB_MAX_SLIDES must be positive")
        if self.ui_username and not self.ui_password.get_secret_value():
            problems.append("PPT2KB_UI_USERNAME is set but PPT2KB_UI_PASSWORD is empty")
        return problems

    @field_validator("image_format")
    @classmethod
    def _fmt(cls, v: str) -> str:
        v = v.lower()
        if v not in ("png", "jpeg", "jpg"):
            raise ValueError("image_format must be png or jpeg")
        return "jpeg" if v == "jpg" else v

    @field_validator("servicenow_auth_type")
    @classmethod
    def _auth(cls, v: str) -> str:
        v = v.lower()
        if v not in ("basic", "bearer", "oauth_password"):
            raise ValueError("servicenow_auth_type must be basic, bearer or oauth_password")
        return v

    # ------------------------------------------------------------- helpers
    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ppt2kb.sqlite3"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.upload_dir, self.jobs_dir, self.tmp_dir):
            d.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(d, 0o750)
            except OSError:
                pass

    def allowed_hosts(self) -> List[str]:
        """Hosts the outbound HTTP layer may contact."""
        hosts: List[str] = []
        for raw in self.allowed_outbound_hosts.split(","):
            raw = raw.strip().lower()
            if raw:
                hosts.append(raw)
        for url in (self.qwen_base_url, self.servicenow_url):
            h = host_of(url)
            if h and h not in hosts:
                hosts.append(h)
        return hosts


def host_of(url: str) -> str:
    """Return ``host`` or ``host:port`` (lower-case) of a URL, '' if invalid."""
    if not url:
        return ""
    try:
        p = urlparse(url)
    except ValueError:
        return ""
    if not p.hostname:
        return ""
    if p.port:
        return f"{p.hostname.lower()}:{p.port}"
    return p.hostname.lower()


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def reset_settings() -> None:
    """Used by tests."""
    global _settings
    _settings = None
