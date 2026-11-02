"""
FastAPI application factory.

Run with ``ppt2kb`` (console script) or ``uvicorn ppt2kb.app:app``.
"""
from __future__ import annotations

import logging
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import __version__
from .config import Settings, get_settings
from .logging_utils import configure_logging, register_secret
from .pipeline import JobRunner
from .runtime import RuntimeConfig
from .storage import Database

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "web" / "static"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; "
            "connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'; object-src 'none'",
        )
        return response


class BasicAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self._user = username.encode()
        self._pass = password.encode()

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/api/health", "/healthz"):
            return await call_next(request)
        import base64

        header = request.headers.get("authorization", "")
        ok = False
        if header.startswith("Basic "):
            try:
                raw = base64.b64decode(header[6:]).split(b":", 1)
                if len(raw) == 2:
                    ok = secrets.compare_digest(raw[0], self._user) and secrets.compare_digest(raw[1], self._pass)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="ppt2kb"'})
        return await call_next(request)


class AppState:
    def __init__(self, settings: Settings):
        self.settings = settings
        settings.ensure_dirs()
        self.db = Database(settings.db_path)
        self.runtime = RuntimeConfig(settings, self.db)
        self.runner = JobRunner(settings, self.db, self.runtime)
        self.publish_threads: dict[str, threading.Thread] = {}
        self.started_at = time.time()


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_json, log_file=settings.log_file)
    register_secret(settings.ui_password.get_secret_value())
    problems = settings.validate_files()
    if problems:
        for p in problems:
            logger.critical("Configuration error: %s", p)
        raise SystemExit("ppt2kb cannot start: " + "; ".join(problems))
    state = AppState(settings)

    # Security: recent FastAPI versions bundle OpenTelemetry instrumentation that
    # can auto-configure an OTLP exporter from OTEL_* environment variables.
    # Disable it explicitly so no telemetry can ever leave the process; the
    # deployment files additionally set OTEL_SDK_DISABLED=true as belt-and-braces.
    os.environ.setdefault("OTEL_SDK_DISABLED", "true")
    fastapi_kwargs = {}
    try:
        import inspect

        if "telemetry" in inspect.signature(FastAPI.__init__).parameters:
            fastapi_kwargs["telemetry"] = {"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}
    except (TypeError, ValueError):  # pragma: no cover
        pass
    app = FastAPI(
        title="ppt2kb - PowerPoint to ServiceNow Knowledge",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        **fastapi_kwargs,
    )
    app.state.ctx = state
    app.add_middleware(SecurityHeadersMiddleware)
    if settings.ui_username:
        app.add_middleware(BasicAuthMiddleware, username=settings.ui_username, password=settings.ui_password.get_secret_value())

    from .api import router

    app.include_router(router, prefix="/api")
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    async def index():
        return Response(content=(STATIC_DIR / "index.html").read_bytes(), media_type="text/html; charset=utf-8")

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return JSONResponse({"status": "ok"})

    @app.on_event("startup")
    def _startup():
        state.runner.start()
        logger.info("ppt2kb %s started; data dir %s", __version__, settings.data_dir)
        if not settings.tls_verify:
            logger.critical("TLS verification disabled by configuration")
        _cleanup_old_jobs(state)

    @app.on_event("shutdown")
    def _shutdown():
        state.runner.stop()
        state.db.close()

    return app


def _cleanup_old_jobs(state: AppState) -> None:
    """Delete jobs (and their files) older than the retention period."""
    import shutil

    days = state.settings.retention_days
    if days <= 0:
        return
    cutoff = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - days * 86400))
    for job in state.db.old_jobs(cutoff):
        logger.info("Retention: deleting job %s from %s", job["id"], job["created_at"])
        shutil.rmtree(state.settings.jobs_dir / job["id"], ignore_errors=True)
        try:
            Path(job["source_path"]).unlink(missing_ok=True)
        except OSError:
            pass
        state.db.delete_job(job["id"])


app = None


def __getattr__(name: str):
    # Lazy module-level ``app`` so ``uvicorn ppt2kb.app:app`` works without
    # creating the application at import time of other modules.
    if name == "app":
        global app
        if app is None:
            app = create_app()
        return app
    raise AttributeError(name)


def main() -> None:
    import uvicorn

    settings = get_settings()
    application = create_app(settings)
    uvicorn.run(application, host=settings.host, port=settings.port, log_level=settings.log_level.lower(), access_log=False, server_header=False, date_header=False)


if __name__ == "__main__":
    main()
