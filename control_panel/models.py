from __future__ import annotations

from typing import Any, Dict


def ok(data: Dict[str, Any] | None = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ok": True}
    if data:
        payload.update(data)
    return payload


def error(message: str, *, status: int = 400) -> Dict[str, Any]:
    return {"ok": False, "error": message, "status": status}
