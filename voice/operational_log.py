from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from voice.health import write_heartbeat


MAX_VALUE_LENGTH = 1000
_COMPONENT_READY = {"voice": False, "redbot": False}
_REDBOT_HEARTBEAT_EVENTS = {
    "redbot.ready",
    "redbot.heartbeat",
    "redbot.stopped",
    "redbot.crashed",
}


def _default_log_path() -> Path:
    configured = os.environ.get("DJGOO_EVENT_LOG", "").strip()
    if configured:
        return Path(configured)
    return Path.cwd() / "logs" / "djgoo-events.jsonl"


def _safe_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, dict):
        return {str(key): _safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    text = str(value)
    if len(text) > MAX_VALUE_LENGTH:
        return text[:MAX_VALUE_LENGTH] + "...<truncated>"
    return text


def _configured_component() -> str:
    value = os.environ.get("DJGOO_COMPONENT_NAME", "").strip().lower()
    return value if value in {"voice", "redbot"} else ""


def _event_component(event: str) -> str:
    """Return the process that owns a heartbeat-producing event.

    Redbot emits many events whose names begin with ``voice.`` for its gateway,
    queue, and playback bridge. Those events must never overwrite the separate
    microphone-listener heartbeat. Portable child processes identify their owner
    explicitly through ``DJGOO_COMPONENT_NAME``.
    """

    configured = _configured_component()
    if configured == "redbot":
        return "redbot" if event.startswith("redbot.") else ""
    if configured == "voice":
        return "voice" if event.startswith("voice.") else ""

    # Development and direct-test fallback when no supervisor environment exists.
    if event.startswith("redbot."):
        return "redbot"
    if event.startswith("voice.listener.") or event.startswith("voice.hotkey."):
        return "voice"
    return ""


def _event_publishes_heartbeat(component: str, event: str) -> bool:
    """Keep diagnostic events from replacing authoritative readiness state.

    The supervisor requires ``audio_loaded`` and ``discord_ready`` in Redbot's
    heartbeat. Events such as ``redbot.command.invoke`` do not carry those fields.
    Publishing them as heartbeats erases the readiness contract and causes the
    supervisor to kill Music Core while a command is still executing.
    """

    if component == "redbot":
        return event in _REDBOT_HEARTBEAT_EVENTS
    return bool(component)


def _update_ready_state(component: str, event: str) -> bool:
    if event in {"voice.listener.starting"}:
        _COMPONENT_READY[component] = False
    elif event in {"voice.listener.ready", "redbot.ready", "redbot.heartbeat"}:
        _COMPONENT_READY[component] = True
    elif event.endswith((".stopped", ".crashed")):
        _COMPONENT_READY[component] = False
    return _COMPONENT_READY.get(component, False)


def _event_heartbeat(event: str, fields: dict[str, Any]) -> None:
    component = _event_component(event)
    if not component or not _event_publishes_heartbeat(component, event):
        return
    ready = _update_ready_state(component, event)
    allowed_fields = {"guild_count", "audio_loaded", "discord_ready"}
    try:
        write_heartbeat(
            component,
            fields={
                "ready": ready,
                "event": event,
                **{
                    key: _safe_value(value)
                    for key, value in fields.items()
                    if key in allowed_fields
                },
            },
        )
    except OSError:
        return


def log_event(event: str, **fields: Any) -> None:
    record = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "event": event,
        **{str(key): _safe_value(value) for key, value in fields.items()},
    }
    path = _default_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=True, separators=(",", ":")))
            fp.write("\n")
    except OSError:
        pass
    _event_heartbeat(event, fields)
