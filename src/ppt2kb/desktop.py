"""
Desktop launcher (Windows installer edition).

    python -m ppt2kb.desktop            start the local server (if not running) and open the browser
    python -m ppt2kb.desktop --stop     stop a running local server
    python -m ppt2kb.desktop --console  same as start, but keep the console window (troubleshooting)

Behaviour:
  * configuration comes from ``<install dir>\\config\\ppt2kb.env`` (created by the
    installer from the template) - the path is passed in ``PPT2KB_ENV_FILE``;
  * data lives in ``%LOCALAPPDATA%\\PPT2KB`` (uploads, slide images, SQLite DB, logs)
    unless ``PPT2KB_DATA_DIR`` says otherwise;
  * the server binds to 127.0.0.1 only; if the configured port is busy by a
    PPT2KB instance of the same version, the browser is simply opened on it;
  * the UI is opened in the default browser; the server keeps running until
    "Stop PPT2KB" is used (or the user logs off).
"""
from __future__ import annotations

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _install_dir() -> Path:
    # <install>\python\python.exe  ->  <install>
    return Path(sys.executable).resolve().parent.parent


def _default_env() -> None:
    """Desktop defaults, applied only for keys that are neither in the environment nor in the env file."""
    install = _install_dir()
    env_file = Path(os.environ.get("PPT2KB_ENV_FILE") or install / "config" / "ppt2kb.env")
    from_file: dict = {}
    if env_file.is_file():
        os.environ["PPT2KB_ENV_FILE"] = str(env_file)
        try:
            from dotenv import dotenv_values

            from_file = {k: v for k, v in dotenv_values(str(env_file)).items() if v not in (None, "")}
        except Exception:
            from_file = {}
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "PPT2KB"
    defaults = {
        "PPT2KB_DATA_DIR": str(local / "data"),
        "PPT2KB_LOG_FILE": str(local / "logs" / "ppt2kb.log"),
        "PPT2KB_HOST": "127.0.0.1",
        "PPT2KB_PORT": "8080",
        "PPT2KB_DESKTOP_MODE": "true",
        "PPT2KB_PERSIST_UI_SECRETS": "true",  # DPAPI-protected on Windows
    }
    lo = install / "libreoffice" / "program" / "soffice.exe"
    if lo.is_file():
        defaults["PPT2KB_LIBREOFFICE_PATH"] = str(lo)
    for key, value in defaults.items():
        if key not in os.environ and key not in from_file:
            os.environ[key] = value
    os.environ["OTEL_SDK_DISABLED"] = "true"
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        os.environ.pop(k, None)


def _health(host: str, port: int) -> dict | None:
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=2) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def _stop(host: str, port: int) -> int:
    import urllib.request

    if _port_free(host, port):
        print("PPT2KB is not running.")
        return 0
    try:
        req = urllib.request.Request(f"http://{host}:{port}/api/shutdown", method="POST", data=b"")
        with urllib.request.urlopen(req, timeout=5) as r:
            print(r.read().decode("utf-8"))
    except Exception as e:
        print(f"Could not stop PPT2KB: {e}")
        return 1
    for _ in range(50):
        if _port_free(host, port):
            print("PPT2KB stopped.")
            return 0
        time.sleep(0.2)
    print("PPT2KB did not stop in time.")
    return 1


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    _default_env()
    from . import __version__
    from .config import get_settings

    settings = get_settings()
    host, port = settings.host, settings.port
    url = f"http://{host}:{port}/"

    if "--stop" in argv:
        return _stop(host, port)

    if not _port_free(host, port):
        h = _health(host, port)
        if h and h.get("version") == __version__:
            print(f"PPT2KB already running at {url}")
            if "--no-browser" not in argv:
                webbrowser.open(url)
            return 0
        print(f"Port {port} is in use by another program. Change PPT2KB_PORT in config\\ppt2kb.env.")
        return 2

    import uvicorn

    from .app import create_app

    app = create_app(settings)
    config = uvicorn.Config(app, host=host, port=port, log_level=settings.log_level.lower(), access_log=False, server_header=False, date_header=False)
    server = uvicorn.Server(config)
    app.state.ctx.shutdown_hook = lambda: setattr(server, "should_exit", True)

    def _open_when_ready():
        for _ in range(100):
            if _health(host, port):
                if "--no-browser" not in argv:
                    webbrowser.open(url)
                return
            time.sleep(0.2)

    threading.Thread(target=_open_when_ready, daemon=True).start()
    print(f"PPT2KB {__version__} listening on {url} (data: {settings.data_dir})")
    server.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
