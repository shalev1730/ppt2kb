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


IS_WINDOWS = sys.platform == "win32"


def _minimal_env(profile_dir: Path, soffice: Path) -> dict:
    if IS_WINDOWS:
        return _minimal_env_windows(profile_dir, soffice)
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


def _minimal_env_windows(profile_dir: Path, soffice: Path) -> dict:
    """Minimal environment for soffice.exe: system paths it needs, nothing inherited."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    tmp = str(profile_dir / "tmp")
    env = {
        "SystemRoot": sysroot,
        "windir": sysroot,
        "SystemDrive": os.environ.get("SystemDrive", "C:"),
        "ComSpec": os.environ.get("ComSpec", sysroot + r"\System32\cmd.exe"),
        "PATH": f"{soffice.parent};{sysroot}\\System32;{sysroot}",
        "PATHEXT": ".EXE;.COM",
        "TEMP": tmp,
        "TMP": tmp,
        "USERPROFILE": str(profile_dir),
        "APPDATA": str(profile_dir / "appdata"),
        "LOCALAPPDATA": str(profile_dir / "localappdata"),
        "HOMEDRIVE": os.environ.get("SystemDrive", "C:"),
        "HOMEPATH": "\\",
        "NO_PROXY": "*",
        "no_proxy": "*",
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "SAL_DISABLE_OPENCL": "1",
    }
    for key in ("NUMBER_OF_PROCESSORS", "PROCESSOR_ARCHITECTURE", "OS"):
        if key in os.environ:
            env[key] = os.environ[key]
    (profile_dir / "appdata").mkdir(exist_ok=True)
    (profile_dir / "localappdata").mkdir(exist_ok=True)
    return env


class _WindowsJob:
    """Windows Job Object: memory limit + kill-on-close for the LibreOffice process tree."""

    def __init__(self, memory_mb: int):
        import ctypes
        from ctypes import wintypes

        self.k32 = ctypes.windll.kernel32
        self.handle = self.k32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError("CreateJobObject failed")

        class IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong), ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION), ("IoInfo", IO_COUNTERS), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        JOB_OBJECT_LIMIT_JOB_MEMORY = 0x200
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
        JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x8
        info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
        info.BasicLimitInformation.ActiveProcessLimit = 32
        if memory_mb > 0:
            info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY
            info.JobMemoryLimit = memory_mb * 1024 * 1024
        JobObjectExtendedLimitInformation = 9
        if not self.k32.SetInformationJobObject(self.handle, JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info)):
            raise OSError("SetInformationJobObject failed")

    def assign(self, pid: int) -> None:
        PROCESS_SET_QUOTA, PROCESS_TERMINATE = 0x0100, 0x0001
        h = self.k32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, pid)
        if not h:
            raise OSError("OpenProcess failed")
        try:
            if not self.k32.AssignProcessToJobObject(self.handle, h):
                raise OSError("AssignProcessToJobObject failed")
        finally:
            self.k32.CloseHandle(h)

    def close(self) -> None:
        if self.handle:
            self.k32.CloseHandle(self.handle)  # KILL_ON_JOB_CLOSE terminates any leftovers
            self.handle = None


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
    if IS_WINDOWS:
        # bundled copy next to the embedded interpreter (PPT2KB-Setup.exe layout), then system installs
        base = Path(sys.executable).resolve().parent.parent
        candidates += [base / "libreoffice" / "program" / "soffice.exe"]
        for pf in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            candidates.append(Path(pf) / "LibreOffice" / "program" / "soffice.exe")
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
        f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
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
    popen = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL, cwd=str(work), env=_minimal_env(profile_dir, soffice), close_fds=True)
    job = None
    try:
        if IS_WINDOWS:
            proc, job = _launch_windows(cmd, popen, memory_mb)
        else:
            proc = subprocess.Popen(cmd, preexec_fn=_limits_preexec(memory_mb, cpu_seconds), **popen)
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
        if job is not None:
            job.close()
        shutil.rmtree(work, ignore_errors=True)


CREATE_SUSPENDED = 0x00000004


def _launch_windows(cmd: list, popen: dict, memory_mb: int):  # pragma: no cover - windows only
    """Start soffice.exe inside a Job Object (memory limit, kill-on-close).

    The process is created suspended, assigned to the job, then resumed, so
    that its children (soffice.bin) inherit the job. If anything in that
    sequence fails the process is killed and started again without a job
    (conversion still works, only without the memory limit).
    """
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        job = _WindowsJob(memory_mb)
        proc = subprocess.Popen(cmd, creationflags=flags | CREATE_SUSPENDED, **popen)
        try:
            job.assign(proc.pid)
            _resume_suspended(proc.pid)
            return proc, job
        except Exception as e:
            logger.warning("Job Object setup failed (%s); restarting LibreOffice without memory limit", e)
            try:
                proc.kill()
                proc.wait(timeout=10)
            except Exception:
                pass
            job.close()
    except Exception as e:
        logger.warning("Could not create a Job Object (%s); LibreOffice runs without memory limit", e)
    return subprocess.Popen(cmd, creationflags=flags, **popen), None


def _resume_suspended(pid: int) -> None:  # pragma: no cover - windows only
    """Resume a process started with CREATE_SUSPENDED (after it was placed in the Job Object)."""
    import ctypes

    k32 = ctypes.windll.kernel32
    ntdll = ctypes.windll.ntdll
    PROCESS_SUSPEND_RESUME = 0x0800
    h = k32.OpenProcess(PROCESS_SUSPEND_RESUME, False, pid)
    if not h:
        raise OSError("OpenProcess(resume) failed")
    try:
        ntdll.NtResumeProcess(h)
    finally:
        k32.CloseHandle(h)


def _kill_group(proc: subprocess.Popen) -> None:
    if IS_WINDOWS:
        try:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
    else:
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
