from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path


CRYPTPROTECT_UI_FORBIDDEN = 0x01
DESCRIPTION = "DjGoo private release update token"


class UpdateCredentialError(RuntimeError):
    pass


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_ubyte)),
    ]


def _input_blob(data: bytes) -> tuple[_DataBlob, object]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    return blob, buffer


def _windows_libraries() -> tuple[object, object]:
    if os.name != "nt":
        raise UpdateCredentialError("Windows DPAPI is only available on Windows")

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        wintypes.LPCWSTR,
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL

    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL
    return crypt32, kernel32


def _raise_windows_error(message: str) -> None:
    code = ctypes.get_last_error()
    detail = ctypes.FormatError(code).strip() if code else "unknown Windows error"
    raise UpdateCredentialError(f"{message} ({code}: {detail})")


def protect_secret(secret: str) -> str:
    token = secret.strip()
    if not token:
        raise UpdateCredentialError("The update token is empty")

    input_blob, input_buffer = _input_blob(token.encode("utf-8"))
    output_blob = _DataBlob()
    crypt32, kernel32 = _windows_libraries()
    ok = crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        DESCRIPTION,
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del input_buffer
    if not ok:
        _raise_windows_error("Could not encrypt the update token")
    try:
        protected = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))
    return base64.b64encode(protected).decode("ascii")


def unprotect_secret(protected: str) -> str:
    try:
        encrypted = base64.b64decode(protected.encode("ascii"), validate=True)
    except (ValueError, UnicodeError) as exc:
        raise UpdateCredentialError("The saved update credential is malformed") from exc

    input_blob, input_buffer = _input_blob(encrypted)
    output_blob = _DataBlob()
    description = wintypes.LPWSTR()
    crypt32, kernel32 = _windows_libraries()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        ctypes.byref(description),
        None,
        None,
        None,
        CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(output_blob),
    )
    del input_buffer
    if not ok:
        _raise_windows_error("Could not decrypt the saved update token for this Windows account")
    try:
        raw = ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        if description:
            kernel32.LocalFree(ctypes.cast(description, wintypes.HLOCAL))
        kernel32.LocalFree(ctypes.cast(output_blob.pbData, wintypes.HLOCAL))
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise UpdateCredentialError("The saved update credential is invalid") from exc


def load_token(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        protected = str(payload.get("protected_token") or "")
        if int(payload.get("schema", 0)) != 1 or not protected:
            return None
        return unprotect_secret(protected).strip() or None
    except (OSError, ValueError, TypeError, UpdateCredentialError):
        return None


def save_token(path: Path, token: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": 1,
        "provider": "github",
        "protected_token": protect_secret(token),
    }
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def clear_token(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
