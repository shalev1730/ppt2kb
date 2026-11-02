"""
Protection for secrets persisted by the application (``PPT2KB_PERSIST_UI_SECRETS=true``).

* Windows: Data Protection API (``CryptProtectData``, current-user scope).
  The value can only be decrypted by the same Windows user on the same machine,
  which fits the desktop edition where the data directory lives in the user's
  profile. Stored form: ``dpapi:<base64>``.
* Other platforms: stored as ``plain:<value>``; protection relies on file
  permissions of the data directory (documented in the security review).
"""
from __future__ import annotations

import base64
import sys

PREFIX_DPAPI = "dpapi:"
PREFIX_PLAIN = "plain:"


def _dpapi(data: bytes, protect: bool) -> bytes:  # pragma: no cover - windows only
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))
    blob_out = DATA_BLOB()
    entropy = ctypes.create_string_buffer(b"ppt2kb-ui-secret", 16)
    blob_entropy = DATA_BLOB(16, ctypes.cast(entropy, ctypes.POINTER(ctypes.c_char)))
    CRYPTPROTECT_UI_FORBIDDEN = 0x01
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    if protect:
        ok = fn(ctypes.byref(blob_in), "ppt2kb", ctypes.byref(blob_entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    else:
        ok = fn(ctypes.byref(blob_in), None, ctypes.byref(blob_entropy), None, None, CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(blob_out))
    if not ok:
        raise OSError("DPAPI call failed")
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def protect(value: str) -> str:
    raw = value.encode("utf-8")
    if sys.platform == "win32":
        return PREFIX_DPAPI + base64.b64encode(_dpapi(raw, True)).decode("ascii")
    return PREFIX_PLAIN + value


def unprotect(stored: str) -> str:
    if stored.startswith(PREFIX_DPAPI):
        if sys.platform != "win32":
            raise ValueError("DPAPI-protected secret cannot be read on this platform")
        return _dpapi(base64.b64decode(stored[len(PREFIX_DPAPI):]), False).decode("utf-8")
    if stored.startswith(PREFIX_PLAIN):
        return stored[len(PREFIX_PLAIN):]
    return stored  # legacy value stored before this module existed
