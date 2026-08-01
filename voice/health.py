from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping


HEARTBEAT_REFRESH_SECONDS = 2.0
HEARTBEAT_LEASE_SECONDS = {
    "lavalink-client": 20.0,
    "redbot": 60.0,
    "voice": 90.0,
}
_HEARTBEAT_LOCK = threading.RLock()
_HEARTBEAT_LEASES: dict[str, dict[str, Any]] = {}
_HEARTBEAT_THREADS: set[str] = set()


def health_directory(project_root: Path | None = None) -> Path:
    configured = os.environ.get("DJGOO_HEALTH_DIR", "").strip()
    if configured:
        return Path(configured)
    root = project_root or Path(__file__).resolve().parents[1]
    return root / "data" / "health"


def heartbeat_path(component: str, project_root: Path | None = None) -> Path:
    safe_name = "".join(
        character
        for character in component.lower()
        if character.isalnum() or character in "-_"
    )
    if not safe_name:
        raise ValueError("Heartbeat component name cannot be empty")
    return health_directory(project_root) / f"{safe_name}.json"


def _write_payload(
    component: str,
    *,
    project_root: Path | None,
    fields: Mapping[str, Any],
) -> None:
    path = heartbeat_path(component, project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "component": component,
        "pid": os.getpid(),
        "timestamp": time.time(),
        **dict(fields),
    }
    temp = path.with_suffix(path.suffix + ".tmp")
    with _HEARTBEAT_LOCK:
        temp.write_text(
            json.dumps(payload, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)


def _lease_is_active(
    component: str,
    *,
    source_monotonic: float,
    now_monotonic: float,
) -> bool:
    lease = float(HEARTBEAT_LEASE_SECONDS.get(component, 0.0))
    return lease > 0 and 0.0 <= now_monotonic - source_monotonic <= lease


def _leased_fields(component: str, state: Mapping[str, Any], source_age: float) -> dict[str, Any]:
    fields = dict(state.get("fields") or {})
    source_event = fields.get("event")
    fields["heartbeat_lease_refreshed"] = True
    fields["heartbeat_source_age_seconds"] = round(max(0.0, source_age), 1)
    if source_event is not None:
        fields["heartbeat_source_event"] = source_event
    if component == "redbot":
        fields["event"] = "redbot.lease"
    return fields


def _refresh_heartbeat_lease_once(component: str) -> bool:
    with _HEARTBEAT_LOCK:
        state = dict(_HEARTBEAT_LEASES.get(component) or {})
        if not state:
            return False
        now_monotonic = time.monotonic()
        source_monotonic = float(state["source_monotonic"])
        if not _lease_is_active(
            component,
            source_monotonic=source_monotonic,
            now_monotonic=now_monotonic,
        ):
            _HEARTBEAT_LEASES.pop(component, None)
            return False
        _write_payload(
            component,
            project_root=state.get("project_root"),
            fields=_leased_fields(
                component,
                state,
                now_monotonic - source_monotonic,
            ),
        )
        return True


def _heartbeat_lease_loop(component: str) -> None:
    try:
        while True:
            time.sleep(HEARTBEAT_REFRESH_SECONDS)
            if not _refresh_heartbeat_lease_once(component):
                return
    finally:
        with _HEARTBEAT_LOCK:
            _HEARTBEAT_THREADS.discard(component)
            restart = component in _HEARTBEAT_LEASES
        if restart:
            _ensure_heartbeat_lease_thread(component)


def _ensure_heartbeat_lease_thread(component: str) -> None:
    if component not in HEARTBEAT_LEASE_SECONDS:
        return
    with _HEARTBEAT_LOCK:
        if component in _HEARTBEAT_THREADS:
            return
        _HEARTBEAT_THREADS.add(component)
    threading.Thread(
        target=_heartbeat_lease_loop,
        args=(component,),
        name=f"djgoo-heartbeat-{component}",
        daemon=True,
    ).start()


def write_heartbeat(
    component: str,
    *,
    project_root: Path | None = None,
    fields: Mapping[str, Any] | None = None,
) -> None:
    heartbeat_fields = dict(fields or {})
    with _HEARTBEAT_LOCK:
        _write_payload(
            component,
            project_root=project_root,
            fields={**heartbeat_fields, "heartbeat_lease_refreshed": False},
        )
        if component in HEARTBEAT_LEASE_SECONDS:
            _HEARTBEAT_LEASES[component] = {
                "source_monotonic": time.monotonic(),
                "project_root": project_root,
                "fields": heartbeat_fields,
            }
    _ensure_heartbeat_lease_thread(component)


def read_heartbeat(
    component: str,
    *,
    project_root: Path | None = None,
) -> dict[str, Any] | None:
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
