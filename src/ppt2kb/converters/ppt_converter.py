"""
PowerPoint -> PDF conversion with LibreOffice.

Adapted from ppt2desc (MIT, (c) 2025 Adam Łucek) ``src/converters/ppt_converter.py``.

Hardening compared to the original:
  * LibreOffice runs with a throw-away user profile (``-env:UserInstallation``)
    in a private temporary directory, so documents cannot poison a shared
    profile and no state is kept between conversions.
  * Macros are disabled, auto-recovery/first-start wizards disabled, and the
    process is started with ``--norestore --nologo --nodefault --nolockcheck``.
  * A wall-clock timeout, CPU-time limit, address-space limit and
    ``NO_PROXY=*`` / empty proxy variables are applied (``prlimit``-style via
    ``resource.setrlimit`` in the child), and the whole process group is
    killed on timeout.
  * The input file is handed to LibreOffice under a random name in a private
    directory, so the original file name never reaches the shell.
  * The environment passed to the child is minimal (no inherited secrets).
"""
from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from .exceptions import ConversionError, LibreOfficeNotFoundError

logger = logging.getLogger(__name__)


def _limits_preexec(memory_mb: int, cpu_seconds: int):
    def _apply():
        os.setsid()  # new process group => we can kill all children on timeout
        try:
            import resource

            if cpu_seconds > 0:
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 30))
            if memory_mb > 0:
                limit = memory_mb * 1024 * 1024
                resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_NPROC, (256, 256))
        except Exception:  # pragma: no cover - platform specific
            pass

    return _apply


def _minimal_env(profile_dir: Path) -> dict:
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": str(profile_dir),
        "TMPDIR": str(profile_dir / "tmp"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
        # Never let LibreOffice talk to a proxy / the network.
        "NO_PROXY": "*",
        "no_proxy": "*",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "http_proxy": "",
        "https_proxy": "",
        "SAL_USE_VCLPLUGIN": "svp",
        "SAL_DISABLE_OPENCL": "1",
        "SAL_NO_FONT_LOOKUP": "0",
        "DISPLAY": "",
    }
    if "FONTCONFIG_PATH" in os.environ:
        env["FONTCONFIG_PATH"] = os.environ["FONTCONFIG_PATH"]
    return env


def _write_profile(profile_dir: Path) -> None:
    """Pre-seed a LibreOffice profile that disables macros, updates and wizards."""
    user = profile_dir / "user"
    user.mkdir(parents=True, exist_ok=True)
    (profile_dir / "tmp").mkdir(exist_ok=True)
    registry = """<?xml version="1.0" encoding="UTF-8"?>
<oor:items xmlns:oor="http://openoffice.org/2001/registry" xmlns:xs="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="MacroSecurityLevel" oor:op="fuse"><value>3</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="DisableMacrosExecution" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="FirstRun" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="ShowTipOfTheDay" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Save/Document"><prop oor:name="AutoSave" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Recovery/AutoSave"><prop oor:name="Enabled" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="BlockUntrustedRefererLinks" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/ExternalApps"><prop oor:name="ExternalAppsLaunch" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="HyperlinksWithCtrlClick" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="WarnSaveOrSendDoc" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="UseSystemFileDialog" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Jobs/Jobs/org.openoffice.Office.Jobs:Job['UpdateCheck']/Arguments"><prop oor:name="AutoCheckEnabled" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="ExperimentalMode" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Misc"><prop oor:name="MacroRecording" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Security/Scripting"><prop oor:name="SecureURL" oor:op="fuse"><value></value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Filter/PDF/Export"><prop oor:name="UseLosslessCompression" oor:op="fuse"><value>true</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Filter/PDF/Export"><prop oor:name="ExportNotes" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Filter/PDF/Export"><prop oor:name="ExportBookmarks" oor:op="fuse"><value>false</value></prop></item>
  <item oor:path="/org.openoffice.Office.Common/Filter/PDF/Export"><prop oor:name="ExportHiddenSlides" oor:op="fuse"><value>false</value></prop></item>
</oor:items>
"""
    (user / "registrymodifications.xcu").write_text(registry, encoding="utf-8")


def find_libreoffice(configured: Path | None) -> Path:
    candidates = []
    if configured:
        candidates.append(Path(configured))
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            candidates.append(Path(found))
    candidates += [Path("/usr/bin/soffice"), Path("/usr/bin/libreoffice"), Path("/opt/libreoffice/program/soffice")]
    for c in candidates:
        if c and c.exists():
            return c
    raise LibreOfficeNotFoundError("LibreOffice (soffice) not found; set PPT2KB_LIBREOFFICE_PATH")


def convert_pptx_to_pdf(
    input_file: Path,
    libreoffice_path: Path | None,
    temp_dir: Path,
    *,
    timeout_s: int = 600,
    memory_mb: int = 3072,
    cpu_seconds: int = 900,
) -> Path:
    """
    Convert a PowerPoint file to PDF using LibreOffice in an isolated process.

    :return: Path to the output PDF file (inside ``temp_dir``)
    """
    soffice = find_libreoffice(libreoffice_path)
    temp_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="lo-", dir=temp_dir))
    profile_dir = work / "profile"
    _write_profile(profile_dir)
    in_dir = work / "in"
    out_dir = work / "out"
    in_dir.mkdir()
    out_dir.mkdir()

    # Random, shell-safe name; keep the extension so LibreOffice picks the filter.
    ext = input_file.suffix.lower() if input_file.suffix.lower() in (".ppt", ".pptx", ".pps", ".ppsx", ".potx") else ".pptx"
    safe_input = in_dir / f"{uuid.uuid4().hex}{ext}"
    shutil.copyfile(input_file, safe_input)

    cmd = [
        str(soffice),
        f"-env:UserInstallation=file://{profile_dir}",
        "--headless",
        "--invisible",
        "--nologo",
        "--norestore",
        "--nodefault",
        "--nolockcheck",
        "--nofirststartwizard",
        "--convert-to",
        "pdf:impress_pdf_Export",
        "--outdir",
        str(out_dir),
        str(safe_input),
    ]
    logger.info("Starting LibreOffice conversion (timeout %ss, mem %sMB)", timeout_s, memory_mb)
    preexec = _limits_preexec(memory_mb, cpu_seconds) if sys.platform != "win32" else None
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            cwd=str(work),
            env=_minimal_env(profile_dir),
            preexec_fn=preexec,
            close_fds=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            _kill_group(proc)
            raise ConversionError(f"LibreOffice conversion timed out after {timeout_s}s")
        if proc.returncode != 0:
            logger.error("LibreOffice exited with %s: %s", proc.returncode, _tail(err))
            raise ConversionError(f"LibreOffice exited with code {proc.returncode}")
        pdf_path = out_dir / f"{safe_input.stem}.pdf"
        if not pdf_path.exists() or pdf_path.stat().st_size == 0:
            logger.error("LibreOffice produced no PDF: %s %s", _tail(out), _tail(err))
            raise ConversionError("LibreOffice did not produce a PDF (unsupported or corrupt file)")
        final = temp_dir / f"{input_file.stem}.pdf"
        shutil.move(str(pdf_path), final)
        return final
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _kill_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
    except Exception:
        pass


def _tail(data: bytes | None, n: int = 400) -> str:
    if not data:
        return ""
    return data[-n:].decode("utf-8", errors="replace").strip()
