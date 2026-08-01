from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Mapping


def health_directory(project_root: Path | None = None) -> Path:
    configured = os.environ.get("DJGOO_HEALTH_DIR", "").strip()
    if configured:
        return Path(configured)
    root = project_root or Path(__file__).resolve().parents[1]
    return root / "data" / "health"


def heartbeat_path(component: str, project_root: Path | None = None) -> Path:
    safe_name = "".join(character for character in component.lower() if character.isalnum() or character in "-_")
    if not safe_name:
        raise ValueError("Heartbeat component name cannot be empty")
    return health_directory(project_root) / f"{safe_name}.json"


def write_heartbeat(
    component: str,
    *,
    project_root: Path | None = None,
    fields: Mapping[str, Any] | None = None,
) -> None:
    path = heartbeat_path(component, project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "component": component,
        "pid": os.getpid(),
        "timestamp": time.time(),
        **dict(fields or {}),
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def read_heartbeat(component: str, *, project_root: Path | None = None) -> dict[str, Any] | None:
    path = heartbeat_path(component, project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def heartbeat_is_fresh(
    component: str,
    *,
    max_age_seconds: float,
    expected_pid: int | None = None,
    project_root: Path | None = None,
    required_fields: Mapping[str, Any] | None = None,
) -> bool:
    payload = read_heartbeat(component, project_root=project_root)
    if payload is None:
        return False
    try:
        age = time.time() - float(payload.get("timestamp") or 0)
        pid = int(payload.get("pid") or 0)
    except (TypeError, ValueError):
        return False
    if age < -5 or age > max_age_seconds:
        return False
    if expected_pid is not None and pid != int(expected_pid):
        return False
    for key, expected in dict(required_fields or {}).items():
        if payload.get(key) != expected:
            return False
    return True
