from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Mapping


class PendingChoiceStore:
    """Cross-process handoff for fast voice disambiguation."""

    def __init__(self, path: Path, *, timeout_seconds: float = 15.0) -> None:
        self.path = path
        self.timeout_seconds = float(timeout_seconds)
        self._lock = threading.RLock()

    def set(self, *, query: str, options: list[Mapping[str, Any]], guild_id: int = 0) -> None:
        payload = {
            "schema": 1,
            "query": str(query),
            "guild_id": int(guild_id),
            "created_at": time.time(),
            "expires_at": time.time() + self.timeout_seconds,
            "options": [dict(option) for option in options[:4]],
        }
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)

    def get(self) -> dict[str, Any] | None:
        with self._lock:
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            if not isinstance(payload, dict):
                return None
            if time.time() > float(payload.get("expires_at") or 0):
                self.path.unlink(missing_ok=True)
                return None
            options = payload.get("options")
            return payload if isinstance(options, list) and options else None

    def choose(self, index: int) -> dict[str, Any] | None:
        with self._lock:
            payload = self.get()
            if payload is None:
                return None
            options = payload.get("options", [])
            if index < 0 or index >= len(options):
                return None
            selected = dict(options[index]) if isinstance(options[index], dict) else None
            self.path.unlink(missing_ok=True)
            return selected

    def clear(self) -> None:
        with self._lock:
            self.path.unlink(missing_ok=True)
