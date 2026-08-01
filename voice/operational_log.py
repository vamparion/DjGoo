from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from voice.health import write_heartbeat


MAX_VALUE_LENGTH = 1000


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


def _event_heartbeat(event: str, fields: dict[str, Any]) -> None:
    component = ""
    if event.startswith("voice."):
        component = "voice"
    elif event.startswith("redbot."):
        component = "redbot"
    if not component:
        return
    stopped = event.endswith((".stopped", ".crashed"))
    try:
        write_heartbeat(
            component,
            fields={
                "ready": not stopped,
                "event": event,
                **{key: _safe_value(value) for key, value in fields.items() if key in {"guild_count", "audio_loaded"}},
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
