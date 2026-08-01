from __future__ import annotations

import base64
import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Any, Mapping


STORE_SCHEMA = 1
_DPAPI_DESCRIPTION = "DjGoo Voice device credential"
_DPAPI_ENTROPY = b"DjGoo Voice credential v1"


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


def _is_windows() -> bool:
    return os.name == "nt"


def _blob(data: bytes) -> tuple[_DataBlob, ctypes.Array[ctypes.c_char]]:
    buffer = ctypes.create_string_buffer(data)
    return (
        _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))),
        buffer,
    )


def _protect_windows(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    input_blob, input_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(_DPAPI_ENTROPY)
    output_blob = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(input_blob),
        _DPAPI_DESCRIPTION,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)
        del input_buffer, entropy_buffer


def _unprotect_windows(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    input_blob, input_buffer = _blob(data)
    entropy_blob, entropy_buffer = _blob(_DPAPI_ENTROPY)
    output_blob = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(input_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(output_blob),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(output_blob.pbData, output_blob.cbData)
    finally:
        kernel32.LocalFree(output_blob.pbData)
        del input_buffer, entropy_buffer


def save_protected_json(path: Path, payload: Mapping[str, Any]) -> None:
    raw = json.dumps(
        dict(payload),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if _is_windows():
        encoded = base64.b64encode(_protect_windows(raw)).decode("ascii")
        envelope = {
            "schema": STORE_SCHEMA,
            "protection": "windows-dpapi-current-user",
            "ciphertext": encoded,
        }
    else:
        # Non-Windows source/test environments lack DPAPI. File permissions are
        # restricted, and public Windows packages always use DPAPI.
        envelope = {
            "schema": STORE_SCHEMA,
            "protection": "restricted-file",
            "payload": dict(payload),
        }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)
    try:
        path.chmod(0o600)
    except OSError:
        pass


def load_protected_json(path: Path) -> dict[str, Any]:
    envelope = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(envelope, dict):
        raise ValueError("DjGoo credential store is invalid")

    # Backward compatibility: migrate the former plaintext credential object on
    # the next save without preventing existing paired devices from connecting.
    if "device_token" in envelope and "protection" not in envelope:
        return envelope

    protection = str(envelope.get("protection") or "")
    if protection == "windows-dpapi-current-user":
        if not _is_windows():
            raise RuntimeError(
                "This DjGoo credential belongs to a Windows account and cannot be opened here"
            )
        try:
            ciphertext = base64.b64decode(
                str(envelope["ciphertext"]),
                validate=True,
            )
            payload = json.loads(_unprotect_windows(ciphertext).decode("utf-8"))
        except (
            KeyError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError("DjGoo credential could not be decrypted") from exc
    elif protection == "restricted-file":
        payload = envelope.get("payload")
    else:
        raise ValueError("DjGoo credential protection method is not supported")

    if not isinstance(payload, dict):
        raise ValueError("DjGoo credential payload is invalid")
    return payload
